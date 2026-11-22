import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import {
  addToTrail, createSim, createTrail, FARBEN, formatWert, formatZahl, GRENZEN, mitWert, normalizeSim, standbild,
  type Ausschnitt, type Farbe, type GrenzFeld, type Kennwert, type Pt, type SimModellAlle, type SimSnapshot, type SimState, type Standbild,
  type Trail, type Verteilung,
} from "../../lib/physics";
import { PALETTE_VAR } from "../../lib/scene";
import { createSimLoop, TEMPO_FAKTOREN, type FrameScheduler, type LoopState, type LoopStatus, type SimLoop, type TempoFaktor } from "../../lib/simLoop";
import type { SimBlock } from "../../lib/stage";
import { useBoxSize } from "../../lib/useBoxSize";

// Baustein `simulation` (Plan docs/ui-p5-plan.md, Abschnitte 3 bis 7). Gerechnet wird in lib/physics.ts, getaktet in
// lib/simLoop.ts (höchstens 30 Bilder je Sekunde, Stopp nach der Laufzeit, verdeckt oder außer Sicht kein Schritt). Hier wird nur
// gezeichnet (Canvas 2D, gleicher Maßstab auf beiden Achsen, y nach oben; nur die Welle hat zwei Maßstäbe und sagt das) und bedient.
// Texte aus den Daten (Namen, Beschreibung) stehen nur im DOM, nie im Bild. Der Satz „Simulation, keine Messung“ und die Hinweise
// kommen von der Oberfläche, nicht von Claude.
// Pause, Weiter, Neu starten, Tempo und Regler ändern nur die Anzeige im Fenster: nichts wird gesendet, gespeichert oder abgespielt.
// Ein Regler baut mit `mitWert` eine neue Eingabe (innerhalb der Schema-Grenzen) und startet die Simulation damit neu, beim Ziehen
// und Tippen höchstens alle 200 ms und danach einmal mit dem letzten Wert. „Zurück auf die Werte von Claude“ nimmt wieder die
// gelieferten Daten.
// Bei „weniger Bewegung“ gibt es keine Schleife, sondern ein Standbild mit Textfassung und den Knopf „Trotzdem abspielen“.

const FIG_MS = 500;              // Kennwerte höchstens zweimal je Sekunde neu (nicht jedes Bild, weniger React-Arbeit)
const DIST_MS = 1000;            // Verteilung beim Gas einmal je Sekunde neu
const REGLER_MS = 200;           // Regler: höchstens ein Neustart je 200 ms beim Ziehen und Tippen
const LOG_N = 1000;              // Stufen eines logarithmischen Reglers
const DPR_MAX = 1.5;
const DEFAULT_W = 640, H_MIN = 180, H_MAX = 420, CURVE_H = 120, DIST_H = 72, PAD = 10, WELLE_RATIO = 0.4;
const REDUCE = "(prefers-reduced-motion: reduce)";
const MODELL_LABEL: Record<SimModellAlle, string> = {
  pendel: "Pendel", feder: "Federpendel", wurf: "Wurf", umlauf: "Umlaufbahnen", gas: "Gas im Kasten", doppelpendel: "Doppelpendel", welle: "Welle",
};
const FARBE_WORT: Record<Farbe, string> = {
  arc: "Cyan", amber: "Bernstein", ok: "Grün", warn: "Warnfarbe (Bernstein)", alarm: "Rot", text: "Weiß", gedaempft: "Grau",
};
const TEMPO_WORT: Record<TempoFaktor, string> = { 0.5: "halb", 1: "normal", 2: "doppelt" };
const TEIL_FARBE: readonly Farbe[] = ["amber", "ok", "text"];       // einzelne Wellen (dünn); die Summe ist Cyan und dick
const STILL_WORT = "Standbild, weniger Bewegung ist eingestellt";
const SATZ_ANZIEHUNG = "Die Körper ziehen sich gegenseitig an.";
const SATZ_OHNE_ANZIEHUNG = "Die Körper ziehen sich gegenseitig nicht an.";
const SATZ_CHAOS = "Das Doppelpendel ist chaotisch: Schon eine winzige Änderung am Start ergibt eine ganz andere Bahn. "
  + "Die Energie in Prozent des Starts zeigt, wie genau gerechnet wird.";
const SATZ_BESCHREIBUNG_ALT = "Die Beschreibung von Claude gilt für die ursprünglichen Werte.";
const SATZ_TEMPO_ZEITLUPE ="Tempo wirkt erst, wenn die Rechengrenze nicht erreicht ist.";
const SATZ_WELLE ="Waagerecht der Ort, senkrecht die Auslenkung. Die beiden Achsen haben verschiedene Maßstäbe.";

interface Pal { farbe: Record<Farbe, string>; line: string; strong: string; muted: string; amber: string }
interface Gfx {
  ctx: CanvasRenderingContext2D | null; w: number; h: number; dpr: number; pal: Pal | null;
  snap: SimSnapshot | null; trail: Trail | null; bild: Standbild | null;
}
interface Info { text: string; angepasst: number; ausschnitt: Ausschnitt; bild: Standbild | null; koerper: { name: string; farbe: Farbe }[] }
/** `ausserhalb`: Körper außerhalb des Bildausschnitts (vom Rechenkern gezählt; fehlt das Feld, gilt 0). */
interface Figures { zeit: number; einheit: string; kennwerte: Kennwert[]; ausserhalb: number }

const prefersReduced = (): boolean => {
  try { return typeof matchMedia === "function" && !!matchMedia(REDUCE).matches; } catch { return false; }
};
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const dprNow = () => Math.min(typeof window !== "undefined" && window.devicePixelRatio > 0 ? window.devicePixelRatio : 1, DPR_MAX);
const ausserhalbOf = (s: SimSnapshot): number => {
  const n = s.ausserhalb;                                              // nur Umlauf mit Anziehung; sonst fehlt das Feld
  return typeof n === "number" && Number.isFinite(n) && n > 0 ? Math.round(n) : 0;
};
const figOf = (s: SimSnapshot): Figures => ({ zeit: s.zeit, einheit: s.einheit, kennwerte: s.kennwerte, ausserhalb: ausserhalbOf(s) });
const running = (s: LoopStatus | "") => s === "laeuft" || s === "zeitlupe";

// --- Regler ------------------------------------------------------------------------------------------------------------

/** Zahl unter `parameter` entlang des Pfads eines Reglers (`laenge`, `wellen.0.frequenz`); nur endliche Zahlen, sonst null. */
function leseWert(input: unknown, feld: string): number | null {
  let o: unknown = input && typeof input === "object" ? (input as { parameter?: unknown }).parameter : undefined;
  for (const t of feld.split(".")) {
    if (Array.isArray(o)) { const i = Number(t); o = Number.isInteger(i) && i >= 0 && i < o.length ? o[i] : undefined; }
    else if (o && typeof o === "object") o = Object.prototype.hasOwnProperty.call(o, t) ? (o as Record<string, unknown>)[t] : undefined;
    else return null;
  }
  return typeof o === "number" && Number.isFinite(o) ? o : null;
}

const stellen = (s: number): number => { const t = String(s), i = t.indexOf("."); return i < 0 ? 0 : t.length - i - 1; };
/** Auf ein Vielfaches des Reglerschritts, ohne Gleitkomma-Reste, in den Grenzen. */
const aufSchritt = (v: number, g: GrenzFeld): number =>
  clamp(Number((Math.round(v / g.schritt) * g.schritt).toFixed(Math.min(12, stellen(g.schritt)))), g.min, g.max);
/** Stufen des Reglers: linear eine je Schritt, logarithmisch LOG_N. */
const stufen = (g: GrenzFeld): number => (g.skala === "log" ? LOG_N : Math.max(1, Math.round((g.max - g.min) / g.schritt)));

/** Wert zu einer Reglerstellung. Logarithmisch: min·(max/min)^(Stellung/Stufen), auf drei gültige Ziffern und den Schritt gerundet. */
function wertAusPos(g: GrenzFeld, pos: number): number {
  const n = stufen(g), p = clamp(Number.isFinite(pos) ? Math.round(pos) : 0, 0, n);
  if (g.skala === "log") return aufSchritt(Number((g.min * Math.pow(g.max / g.min, p / n)).toPrecision(3)), g);
  return aufSchritt(g.min + p * g.schritt, g);
}

/** Reglerstellung zu einem Wert (Umkehrung von `wertAusPos`, gerundet). */
function posAusWert(g: GrenzFeld, v: number): number {
  const n = stufen(g);
  if (!Number.isFinite(v)) return 0;
  if (g.skala === "log") return clamp(Math.round((n * Math.log(Math.max(v, g.min) / g.min)) / Math.log(g.max / g.min)), 0, n);
  return clamp(Math.round((v - g.min) / g.schritt), 0, n);
}

const SCHRITT_TASTE: Record<string, number> = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1, PageUp: 10, PageDown: -10 };

/** Nächster Wert für eine Taste (Pfeile ein Schritt, Bild auf/ab zehn, Pos1/Ende die Grenzen); `null`: Taste gehört nicht dem Regler.
 *  Es wird so weit geschoben, bis der gerundete Wert wirklich in Tastenrichtung liegt (ein Wert zwischen zwei Stellungen, etwa
 *  1,234 m, rundet sonst zur Nachbarstellung und von dort in die falsche Richtung); am Rand bleibt der Wert, wie er ist. */
function wertFuerTaste(g: GrenzFeld, wert: number, key: string): number | null {
  if (key === "Home") return g.min;
  if (key === "End") return g.max;
  const d = SCHRITT_TASTE[key];
  if (d === undefined) return null;
  const n = stufen(g);
  let p = posAusWert(g, wert);
  for (let i = 0; i <= n; i++) {
    p = clamp(p + d, 0, n);
    const next = wertAusPos(g, p);
    if (Math.sign(next - wert) === Math.sign(d)) return next;
    if (p === 0 || p === n) break;
  }
  return wert;
}

const reglerText = (g: GrenzFeld, v: number) => `${formatZahl(v)} ${g.einheit}`;
const reglerSatz = (liste: readonly GrenzFeld[], input: unknown) =>
  liste.map((g) => { const v = leseWert(input, g.feld); return `${g.name} ${v === null ? "unbekannt" : reglerText(g, v)}`; }).join(", ");

// --- Zeichnen ----------------------------------------------------------------------------------------------------------

/** Farben aus den CSS-Variablen der Palette (einmal je Aufbau gelesen, nicht je Bild). Ohne Stylesheet: neutrale Farbnamen. */
function readPalette(): Pal {
  let css: CSSStyleDeclaration | null = null;
  try { css = getComputedStyle(document.documentElement); } catch { css = null; }
  const v = (name: string, fallback: string) => css?.getPropertyValue(name).trim() || fallback;
  const farbe = {} as Record<Farbe, string>;
  for (const f of FARBEN) farbe[f] = v(PALETTE_VAR[f] ?? "--arc", "silver");
  return { farbe, line: v("--line", "gray"), strong: v("--line-strong", "gray"), muted: v("--text-muted", "silver"), amber: v("--amber", "orange") };
}

function getCtx(c: HTMLCanvasElement | null): CanvasRenderingContext2D | null {
  try { return c?.getContext("2d") ?? null; } catch { return null; }
}

/** Setzt die Pixelgröße einer Zeichenfläche (Pixeldichte höchstens 1,5); gibt die Pixeldichte zurück. */
function sizeCanvas(c: HTMLCanvasElement | null, w: number, h: number): number {
  const dpr = dprNow();
  if (c) {
    const W = Math.max(1, Math.round(w * dpr)), H = Math.max(1, Math.round(h * dpr));
    if (c.width !== W) c.width = W;
    if (c.height !== H) c.height = H;
  }
  return dpr;
}

/** Fester Ausschnitt auf die Fläche, gleicher Maßstab auf beiden Achsen, mittig, y nach oben. */
function mapper(a: Ausschnitt, w: number, h: number) {
  const iw = Math.max(1, w - 2 * PAD), ih = Math.max(1, h - 2 * PAD);
  const aw = a.maxX - a.minX > 0 ? a.maxX - a.minX : 1, ah = a.maxY - a.minY > 0 ? a.maxY - a.minY : 1;
  const s = Math.min(iw / aw, ih / ah);
  const ox = PAD + (iw - aw * s) / 2, oy = PAD + (ih - ah * s) / 2;
  return { s, aw, ah, X: (x: number) => ox + (x - a.minX) * s, Y: (y: number) => oy + (a.maxY - y) * s };
}
type Map2 = ReturnType<typeof mapper>;

/** Welle: jede Achse füllt die Fläche für sich (zwei Maßstäbe; die Ansicht sagt das in Worten). */
function mapperFrei(a: Ausschnitt, w: number, h: number): Map2 {
  const iw = Math.max(1, w - 2 * PAD), ih = Math.max(1, h - 2 * PAD);
  const aw = a.maxX - a.minX > 0 ? a.maxX - a.minX : 1, ah = a.maxY - a.minY > 0 ? a.maxY - a.minY : 1;
  return { s: iw / aw, aw, ah, X: (x: number) => PAD + ((x - a.minX) / aw) * iw, Y: (y: number) => PAD + ((a.maxY - y) / ah) * ih };
}

function line(ctx: CanvasRenderingContext2D, pts: Pt[], m: Map2, close = false): void {
  if (pts.length < 2) return;
  ctx.beginPath();
  ctx.moveTo(m.X(pts[0][0]), m.Y(pts[0][1]));
  for (let i = 1; i < pts.length; i++) ctx.lineTo(m.X(pts[i][0]), m.Y(pts[i][1]));
  if (close) ctx.closePath();
  ctx.stroke();
}

/** Welle: Ortsachse (Ruhelage) mit Endstrichen, im Standbild die Hülle gestrichelt, die einzelnen Wellen dünn, die Summe dick. */
function paintWelle(ctx: CanvasRenderingContext2D, g: Gfx, snap: SimSnapshot, pal: Pal): void {
  const a = snap.ausschnitt, m = mapperFrei(a, g.w, g.h), y0 = m.Y(0);
  ctx.strokeStyle = pal.strong; ctx.lineWidth = 1;
  line(ctx, [[a.minX, 0], [a.maxX, 0]], m);
  ctx.beginPath();
  for (const x of [m.X(a.minX), m.X(a.maxX)]) { ctx.moveTo(x, y0 - 6); ctx.lineTo(x, y0 + 6); }
  ctx.stroke();
  if (g.bild?.modell === "welle") {
    ctx.strokeStyle = pal.muted; ctx.lineWidth = 1.5; ctx.setLineDash([6, 4]);
    line(ctx, g.bild.huelleMin, m);
    line(ctx, g.bild.huelleMax, m);
    ctx.setLineDash([]);
  }
  const teil = snap.teilkurven ?? [];
  if (teil.length >= 2) {
    ctx.lineWidth = 1; ctx.globalAlpha = 0.7;
    teil.forEach((k, j) => { ctx.strokeStyle = pal.farbe[TEIL_FARBE[j] ?? "text"]; line(ctx, k, m); });
    ctx.globalAlpha = 1;
  }
  if (snap.kurve) { ctx.strokeStyle = pal.farbe.arc; ctx.lineWidth = 2.5; line(ctx, snap.kurve, m); }
}

/** Ein Bild der Simulation: Rahmen je Modell, Standbild-Zusätze, Spur, Aufhängung, Körper. Wirft nie; `false` heißt Zeichenfehler
 *  (dann hält die Ansicht an und sagt es, statt still kaputte Bilder zu liefern). */
function paint(g: Gfx): boolean {
  const { ctx, snap, pal } = g;
  if (!ctx || !snap || !pal) return true;
  try {
    ctx.setTransform(g.dpr, 0, 0, g.dpr, 0, 0);
    ctx.clearRect(0, 0, g.w, g.h);
    ctx.globalAlpha = 1; ctx.setLineDash([]); ctx.lineCap = "round"; ctx.lineJoin = "round";
    if (snap.modell === "welle") { paintWelle(ctx, g, snap, pal); return true; }
    const m = mapper(snap.ausschnitt, g.w, g.h), a = snap.ausschnitt;
    const body = snap.koerper[0];
    const haengt = snap.modell === "pendel" || snap.modell === "doppelpendel";
    ctx.strokeStyle = pal.strong; ctx.lineWidth = 2;
    if (snap.modell === "wurf") line(ctx, [[a.minX, 0], [a.maxX, 0]], m);                        // Boden
    if (snap.modell === "gas") { ctx.lineWidth = 1.5; ctx.strokeRect(m.X(a.minX), m.Y(a.maxY), m.aw * m.s, m.ah * m.s); }   // Kasten
    if (haengt && snap.anker) {                                                                  // Decke
      const x = m.X(snap.anker[0]), y = m.Y(snap.anker[1]);
      ctx.beginPath(); ctx.moveTo(x - 24, y); ctx.lineTo(x + 24, y); ctx.stroke();
    }
    if (snap.modell === "feder" && snap.anker) {                                                 // Wand und Ruhelage (gestrichelt)
      const x = m.X(snap.anker[0]), y = m.Y(snap.anker[1]), hh = Math.min(40, 0.35 * m.ah * m.s);
      ctx.beginPath(); ctx.moveTo(x, y - hh); ctx.lineTo(x, y + hh); ctx.stroke();
      ctx.strokeStyle = pal.line; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(m.X(0), y - hh); ctx.lineTo(m.X(0), y + hh); ctx.stroke();
      ctx.setLineDash([]);
    }
    if (g.bild?.modell === "wurf") {                                                             // ganze Bahn, Gipfel (Dreieck), Aufprall (Kreuz)
      ctx.strokeStyle = pal.muted; ctx.lineWidth = 1.5; ctx.setLineDash([6, 4]);
      line(ctx, g.bild.bahn, m);
      ctx.setLineDash([]);
      const gx = m.X(g.bild.gipfel[0]), gy = m.Y(g.bild.gipfel[1]);
      ctx.fillStyle = pal.amber;
      ctx.beginPath(); ctx.moveTo(gx, gy - 9); ctx.lineTo(gx + 8, gy + 5); ctx.lineTo(gx - 8, gy + 5); ctx.closePath(); ctx.fill();
      if (g.bild.vollstaendig) {
        const ax = m.X(g.bild.aufprall[0]), ay = m.Y(g.bild.aufprall[1]);
        ctx.strokeStyle = pal.amber; ctx.lineWidth = 2.5;
        ctx.beginPath(); ctx.moveTo(ax - 7, ay - 7); ctx.lineTo(ax + 7, ay + 7); ctx.moveTo(ax + 7, ay - 7); ctx.lineTo(ax - 7, ay + 7); ctx.stroke();
      }
    }
    if (g.bild?.modell === "umlauf") {                                                           // alle Bahnen; mit Anziehung offene Wege
      ctx.lineWidth = 1.5; ctx.globalAlpha = 0.6;
      const zu = !g.bild.offen;
      for (const b of g.bild.bahnen) { ctx.strokeStyle = pal.farbe[b.farbe] ?? pal.farbe.arc; line(ctx, b.punkte, m, zu); }
      ctx.globalAlpha = 1;
    }
    if (g.bild?.modell === "doppelpendel") {                                                     // Weg des unteren Körpers (gestrichelt)
      ctx.strokeStyle = pal.muted; ctx.lineWidth = 1.2; ctx.setLineDash([6, 4]);
      line(ctx, g.bild.bahn, m);
      ctx.setLineDash([]);
    }
    const t = g.trail, nur = snap.spurKoerper;
    if (t) {                                                                                     // Spur (Ringpuffer, älteste zuerst)
      ctx.lineWidth = 1.5; ctx.globalAlpha = 0.45;
      for (let i = 0; i < t.xs.length; i++) {
        const n = t.laenge[i];
        if (n < 2 || (nur && !nur.includes(i))) continue;
        ctx.strokeStyle = pal.farbe[snap.koerper[i]?.farbe] ?? pal.farbe.arc;
        ctx.beginPath();
        for (let j = 0; j < n; j++) {
          const q = (t.anfang[i] + j) % t.max, x = m.X(t.xs[i][q]), y = m.Y(t.ys[i][q]);
          if (j === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }
    if (snap.anker && body && haengt) {                                                          // Stange(n) und Aufhängung
      ctx.strokeStyle = pal.strong; ctx.lineWidth = 2;
      const arme: Pt[] = [snap.anker, [body.x, body.y]];
      const unten = snap.modell === "doppelpendel" ? snap.koerper[1] : undefined;
      if (unten) arme.push([unten.x, unten.y]);
      line(ctx, arme, m);
      ctx.fillStyle = pal.muted;
      ctx.beginPath(); ctx.arc(m.X(snap.anker[0]), m.Y(snap.anker[1]), 3, 0, 2 * Math.PI); ctx.fill();
    }
    if (snap.anker && body && snap.modell === "feder") {                                         // Feder als Zickzack
      const x0 = m.X(snap.anker[0]), x1 = m.X(body.x) - 9, y = m.Y(snap.anker[1]), n = 12, amp = 7;
      ctx.strokeStyle = pal.strong; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(x0, y);
      for (let i = 1; i < 2 * n; i++) ctx.lineTo(x0 + ((x1 - x0) * i) / (2 * n), y + (i % 2 ? -amp : amp));
      ctx.lineTo(x1, y); ctx.stroke();
    }
    if (snap.anker && snap.modell === "umlauf") {                                                // Zentralmasse
      ctx.fillStyle = pal.amber;
      ctx.beginPath(); ctx.arc(m.X(snap.anker[0]), m.Y(snap.anker[1]), 8, 0, 2 * Math.PI); ctx.fill();
    }
    if (snap.modell === "gas") {                                                                 // alle Teilchen in einem Pfad
      ctx.fillStyle = pal.farbe.arc;
      ctx.beginPath();
      for (const k of snap.koerper) {
        const r = Math.max(1.5, k.r * m.s), x = m.X(k.x), y = m.Y(k.y);
        ctx.moveTo(x + r, y); ctx.arc(x, y, r, 0, 2 * Math.PI);
      }
      ctx.fill();
    } else {
      const r = snap.modell === "umlauf" ? 6 : snap.modell === "doppelpendel" ? 8 : 9;
      for (const k of snap.koerper) {
        ctx.fillStyle = pal.farbe[k.farbe] ?? pal.farbe.arc;
        ctx.beginPath(); ctx.arc(m.X(k.x), m.Y(k.y), r, 0, 2 * Math.PI); ctx.fill();
      }
    }
    return true;
  } catch {
    return false;
  }
}

/** Lage-Zeit-Kurve für Pendel und Feder (Standbild): Nulllinie und Kurve, symmetrisch um null. */
function paintCurve(ctx: CanvasRenderingContext2D, w: number, h: number, dpr: number, kurve: Pt[], pal: Pal): void {
  try {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if (kurve.length < 2) return;
    const t1 = kurve[kurve.length - 1][0] > 0 ? kurve[kurve.length - 1][0] : 1;
    let vmax = 1e-12;
    for (const p of kurve) vmax = Math.max(vmax, Math.abs(p[1]));
    const X = (t: number) => PAD + (t / t1) * (w - 2 * PAD), Y = (v: number) => h / 2 - (v / vmax) * (h / 2 - PAD);
    ctx.strokeStyle = pal.line; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(PAD, h / 2); ctx.lineTo(w - PAD, h / 2); ctx.stroke();
    ctx.strokeStyle = pal.farbe.arc; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(X(kurve[0][0]), Y(kurve[0][1]));
    for (let i = 1; i < kurve.length; i++) ctx.lineTo(X(kurve[i][0]), Y(kurve[i][1]));
    ctx.stroke();
  } catch { /* nur Zeichnen */ }
}

/** Verteilung der Geschwindigkeiten als Balken (die Zahlen stehen als Tabelle daneben). */
function paintDist(ctx: CanvasRenderingContext2D, w: number, h: number, dpr: number, v: Verteilung, pal: Pal): void {
  try {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const n = v.anzahl.length;
    if (!n) return;
    const max = Math.max(1, ...v.anzahl), bw = (w - 2 * PAD) / n, ih = h - 2 * PAD;
    ctx.fillStyle = pal.farbe.arc;
    for (let i = 0; i < n; i++) {
      const bh = (ih * v.anzahl[i]) / max;
      ctx.fillRect(PAD + i * bw + 2, h - PAD - bh, Math.max(1, bw - 4), bh);
    }
    ctx.strokeStyle = pal.strong; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(PAD, h - PAD); ctx.lineTo(w - PAD, h - PAD); ctx.stroke();
  } catch { /* nur Zeichnen */ }
}

function infoOf(sim: SimState, bild: Standbild | null): Info {
  const c = sim.config;
  return {
    text: sim.text, angepasst: c.angepasst.length, ausschnitt: sim.ausschnitt, bild,
    koerper: c.modell === "umlauf" ? c.parameter.koerper.map((k) => ({ name: k.name, farbe: k.farbe })) : [],
  };
}

export function Simulation({ b }: { b: SimBlock }) {
  // Regler: die geänderte Eingabe gilt nur für genau diese Daten (neue Daten = wieder die Werte von Claude) und nur im Fenster.
  const [edit, setEdit] = useState<{ for: SimBlock; input: SimBlock } | null>(null);
  const eff: SimBlock = edit && edit.for === b ? edit.input : b;
  const cfg = useMemo(() => normalizeSim(eff), [eff]);              // nur Begrenzen, keine Vorausrechnung
  const orig = useMemo(() => normalizeSim(b), [b]);
  const [shown, setShown] = useState<{ for: SimBlock; werte: Record<string, number> } | null>(null);   // Werte beim Ziehen
  const [reduced, setReduced] = useState(prefersReduced);
  const [forcedFor, setForcedFor] = useState<SimBlock | null>(null);  // „Trotzdem abspielen“ gilt für genau diese Daten
  const forced = forcedFor === b;
  const still = reduced && !forced;
  const [tempoFor, setTempoFor] = useState<{ for: SimBlock; f: TempoFaktor } | null>(null);
  const tempo: TempoFaktor = tempoFor && tempoFor.for === b ? tempoFor.f : 1;
  const [canTempo, setCanTempo] = useState(false);
  const [info, setInfo] = useState<Info | null>(null);
  const [status, setStatus] = useState<{ status: LoopStatus | ""; wort: string }>({ status: "", wort: "" });
  const [fig, setFig] = useState<Figures | null>(null);
  const [dist, setDist] = useState<Verteilung | null>(null);
  const [noCtx, setNoCtx] = useState(false);
  const [brokenFor, setBrokenFor] = useState<SimBlock | null>(null);  // Zeichenfehler: angehalten, gilt für genau diese Daten
  const broken = brokenFor === b;

  const uid = useId();
  const wrap = useRef<HTMLElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const curve = useRef<HTMLCanvasElement>(null);
  const distCanvas = useRef<HTMLCanvasElement>(null);
  const pauseBtn = useRef<HTMLButtonElement>(null);
  const loopRef = useRef<SimLoop | null>(null);
  const effRef = useRef<SimBlock>(eff);
  const tempoRef = useRef<TempoFaktor>(tempo);
  const thr = useRef<{ timer: number | null; pending: Record<string, number> | null }>({ timer: null, pending: null });
  const clocks = useRef({ fig: -Infinity, dist: -Infinity });
  const gfx = useRef<Gfx>({ ctx: null, w: DEFAULT_W, h: H_MIN, dpr: 1, pal: null, snap: null, trail: null, bild: null }).current;

  const box = useBoxSize(frame);
  const cssW = Math.max(120, box?.width ?? DEFAULT_W);
  const a = info?.ausschnitt;
  const ratio = cfg.modell === "welle" ? WELLE_RATIO : a && a.maxX > a.minX && a.maxY > a.minY ? (a.maxY - a.minY) / (a.maxX - a.minX) : 0.5;
  const cssH = Math.round(clamp(cssW * ratio, H_MIN, H_MAX));

  useEffect(() => { effRef.current = eff; tempoRef.current = tempo; });   // vor dem Aufbau unten: der neue Lauf übernimmt das Tempo

  useEffect(() => {                                                    // „weniger Bewegung“ kann sich ändern; Listener räumt auf
    let mq: MediaQueryList | null = null;
    try { mq = typeof matchMedia === "function" ? matchMedia(REDUCE) : null; } catch { mq = null; }
    if (!mq || typeof mq.addEventListener !== "function") return;
    const on = () => setReduced(!!mq?.matches);
    mq.addEventListener("change", on);
    return () => mq?.removeEventListener("change", on);
  }, []);

  useEffect(() => {                                                    // Regler-Zeitgeber: neue Daten oder Abbau räumen ihn ab
    const t = thr.current;
    return () => { if (t.timer !== null) window.clearTimeout(t.timer); t.timer = null; t.pending = null; };
  }, [b]);

  useEffect(() => {                                                    // Größe der Zeichenfläche; neu zeichnen ohne neu zu rechnen
    gfx.w = cssW; gfx.h = cssH;
    gfx.dpr = sizeCanvas(canvas.current, cssW, cssH);
    if (!paint(gfx)) { loopRef.current?.dispose(); setBrokenFor(b); }
  }, [cssW, cssH, gfx, b]);

  useEffect(() => {                                                    // Aufbau: Standbild oder Taktschleife, abgebaut bei neuen Daten
    if (cfg.ungueltig || broken) return;                               // ungültig: keine Schleife, kein Standbild
    const ctx = getCtx(canvas.current);
    gfx.ctx = ctx; gfx.pal = readPalette(); gfx.snap = null; gfx.trail = null; gfx.bild = null;
    clocks.current = { fig: -Infinity, dist: -Infinity };
    setNoCtx(!ctx);
    if (still || !ctx) {                                               // keine Schleife: ein Bild aus der Vorausrechnung
      const sim = createSim(eff);
      const bild = still ? standbild(sim) : null;
      gfx.bild = bild; gfx.snap = sim.startBild;
      setInfo(infoOf(sim, bild));
      setFig(figOf(sim.startBild));
      setDist(bild?.modell === "gas" ? bild.verteilung : sim.startBild.verteilung);
      setStatus({ status: "", wort: still ? STILL_WORT : "" });
      setCanTempo(false);
      if (!paint(gfx)) setBrokenFor(b);
      return;
    }
    let inView = true, io: IntersectionObserver | null = null;
    const el = wrap.current;
    if (typeof IntersectionObserver === "function" && el) {
      try {
        io = new IntersectionObserver((entries) => { const e = entries[entries.length - 1]; if (e) inView = e.isIntersecting; });
        io.observe(el);
      } catch { io = null; }
    }
    let latest: SimSnapshot | null = null, dead = false, loop: SimLoop | null = null;
    const flush = () => { if (latest) { setFig(figOf(latest)); if (latest.verteilung) setDist(latest.verteilung); } };
    /** Ein Fehler in den eigenen Rückrufen hält die Schleife sichtbar an, statt sie still sterben zu lassen. */
    const fail = () => { dead = true; loop?.dispose(); io?.disconnect(); setBrokenFor(b); };
    const scheduler: FrameScheduler = {
      now: () => performance.now(),
      requestFrame: (cb) => (typeof requestAnimationFrame === "function" ? requestAnimationFrame(cb) : window.setTimeout(() => cb(performance.now()), 33)),
      cancelFrame: (id) => (typeof cancelAnimationFrame === "function" ? cancelAnimationFrame(id) : window.clearTimeout(id)),
    };
    const trails = cfg.spur && cfg.modell !== "gas" && cfg.modell !== "welle";   // Gas: der Helfer kennt nur 8 Körper; Welle: keine Körper
    loop = createSimLoop({
      input: eff, scheduler,
      isHidden: () => document.hidden || !inView,
      onFrame: (snap) => {
        if (dead) return;
        try {
          latest = snap; gfx.snap = snap;
          if (trails) { gfx.trail ??= createTrail(snap.koerper.length); addToTrail(gfx.trail, snap); }
          if (!paint(gfx)) { fail(); return; }
          const now = performance.now(), c = clocks.current;
          if (now - c.fig >= FIG_MS) { c.fig = now; setFig(figOf(snap)); }
          if (snap.verteilung && now - c.dist >= DIST_MS) { c.dist = now; setDist(snap.verteilung); }
        } catch { fail(); }
      },
      onState: (st: LoopState) => {
        if (dead) return;
        try {
          setStatus({ status: st.status, wort: st.wort });
          if (!running(st.status)) flush();                           // Stopp, Pause, Landung: die letzten Zahlen zeigen
        } catch { fail(); }
      },
    });
    if (dead) { loop.dispose(); return; }
    const own = loop;
    loopRef.current = own;
    const hatTempo = typeof own.setTempoFaktor === "function";
    if (hatTempo) own.setTempoFaktor?.(tempoRef.current);             // Neustart durch einen Regler behält das Tempo
    setCanTempo(hatTempo);
    const st = own.getState();
    setStatus({ status: st.status, wort: st.wort });
    setInfo(infoOf(own.getSim(), null));
    return () => { dead = true; own.dispose(); io?.disconnect(); if (loopRef.current === own) loopRef.current = null; };
  }, [b, eff, cfg, still, broken, gfx]);

  useEffect(() => {                                                    // Kurve im Standbild (Pendel, Feder)
    const bild = info?.bild;
    const ctx = bild && (bild.modell === "pendel" || bild.modell === "feder") ? getCtx(curve.current) : null;
    if (!ctx || !bild || (bild.modell !== "pendel" && bild.modell !== "feder")) return;
    paintCurve(ctx, cssW, CURVE_H, sizeCanvas(curve.current, cssW, CURVE_H), bild.kurve, gfx.pal ?? readPalette());
  }, [info, cssW, gfx]);

  useEffect(() => {                                                    // Balken der Verteilung (Gas)
    const ctx = dist ? getCtx(distCanvas.current) : null;
    if (!ctx || !dist) return;
    paintDist(ctx, cssW, DIST_H, sizeCanvas(distCanvas.current, cssW, DIST_H), dist, gfx.pal ?? readPalette());
  }, [dist, cssW, gfx]);

  useEffect(() => { if (forced) pauseBtn.current?.focus(); }, [forced]);   // Fokus bleibt beim Bedienen, nicht auf dem Seitenanfang

  const sync = (l: SimLoop) => { const st = l.getState(); setStatus({ status: st.status, wort: st.wort }); };
  const toggle = () => {
    const l = loopRef.current;
    if (!l) return;
    const s = l.getState().status;
    if (s === "pausiert") l.resume(); else if (running(s)) l.pause(); else return;
    sync(l);
  };
  const restart = () => {
    const l = loopRef.current;
    if (!l) return;
    gfx.trail = null;
    clocks.current = { fig: -Infinity, dist: -Infinity };
    l.restart();
    sync(l);
  };
  const setzeTempo = (f: TempoFaktor) => {
    const l = loopRef.current;
    if (!l || typeof l.setTempoFaktor !== "function") return;
    l.setTempoFaktor(f);
    setTempoFor({ for: b, f: l.getTempoFaktor?.() ?? f });
  };

  /** Neue Eingabe aus dem Regler (begrenzt durch `mitWert`); der Aufbau oben startet die Simulation damit neu. */
  const uebernimm = (werte: Record<string, number>) => {
    let next = effRef.current;
    for (const [feld, wert] of Object.entries(werte)) next = mitWert(next, feld, wert);
    effRef.current = next;
    setEdit({ for: b, input: next });
  };
  // Ziehen und Tasten gleich: der erste Wert startet sofort neu, danach höchstens ein Neustart je 200 ms mit den letzten Werten
  // (je Regler), und nach dem letzten Wert genau einer. Loslassen (Maus, Finger, Taste, Fokus weg) wartet diesen letzten Neustart ab,
  // statt sofort neu zu starten; so bleibt es auch bei schnellem Tippen bei höchstens einem Neustart je 200 ms.
  const takt = () => {
    const t = thr.current;
    t.timer = null;
    const p = t.pending;
    if (!p) { setShown(null); return; }                                // nichts Neues: der Regler zeigt wieder den gerechneten Wert
    t.pending = null;
    uebernimm(p);
    t.timer = window.setTimeout(takt, REGLER_MS);
  };
  const ziehe = (g: GrenzFeld, wert: number) => {
    setShown((s) => ({ for: b, werte: { ...(s && s.for === b ? s.werte : {}), [g.feld]: wert } }));
    const t = thr.current;
    if (t.timer === null) { t.pending = null; uebernimm({ [g.feld]: wert }); t.timer = window.setTimeout(takt, REGLER_MS); }
    else t.pending = { ...(t.pending ?? {}), [g.feld]: wert };
  };
  const loslassen = () => {
    if (thr.current.timer === null) setShown(null);                    // sonst bringt der laufende Takt den letzten Wert
  };
  const taste = (g: GrenzFeld, wert: number) => (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.ctrlKey || e.altKey || e.metaKey) return;                    // Tasten mit Strg, Alt oder Meta gehören dem Browser
    const next = wertFuerTaste(g, wert, e.key);
    if (next === null) return;
    e.preventDefault();
    if (next !== wert) ziehe(g, next);
  };
  const edited = !!edit && edit.for === b;
  const zurueck = () => {
    const t = thr.current;
    if (!edited && t.timer === null) return;
    if (t.timer !== null) window.clearTimeout(t.timer);                // kein alter Wert kommt mehr nach
    t.timer = null; t.pending = null;
    effRef.current = b;
    setShown(null);
    setEdit(null);
  };

  const label = MODELL_LABEL[cfg.modell];
  if (cfg.ungueltig || broken) {
    return (
      <section className="v-sim" aria-label="Simulation">
        <p className="s-flag">Simulation, keine Messung</p>
        <p className="v-note" role="note">Simulation kann nicht gezeigt werden.</p>
      </section>
    );
  }

  const bild = info?.bild ?? null;
  const canPause = running(status.status) || status.status === "pausiert";
  const g = dist?.grenzen ?? [];
  const regler = GRENZEN[cfg.modell] ?? [];
  const anziehung = cfg.modell === "umlauf" && cfg.parameter.anziehung === true;
  const wellen = cfg.modell === "welle" ? cfg.parameter.wellen : [];
  const playing = !still && !noCtx;
  return (
    <section ref={wrap} className="v-sim" aria-label={`Simulation: ${label}`}>
      <div className="s-head">
        <p className="s-flag">Simulation, keine Messung</p>
        <span className="label">{label}</span>
      </div>
      {cfg.modell === "umlauf" && <p className="v-note">{anziehung ? SATZ_ANZIEHUNG : SATZ_OHNE_ANZIEHUNG}</p>}
      {cfg.modell === "doppelpendel" && <p className="v-note">{SATZ_CHAOS}</p>}
      {cfg.modell === "welle" && <p className="v-note">{SATZ_WELLE}</p>}
      {info && info.angepasst > 0 && <p className="v-note">Einige Angaben fehlten oder lagen außerhalb der Grenzen und wurden angepasst.</p>}
      {noCtx && <p className="v-note" role="note">Das Bild kann hier nicht gezeichnet werden. Die Beschreibung steht darunter.</p>}
      <div ref={frame} className="s-frame" hidden={noCtx}>
        <canvas ref={canvas} className="s-canvas" style={{ height: cssH }} role="img"
          aria-label={still ? "Standbild der Simulation; die Beschreibung steht darunter als Text" : "Bild der Simulation; die Beschreibung steht darunter als Text"} />
      </div>
      <div className="m-row s-controls" role="group" aria-label="Simulation steuern">
        {still && !noCtx && <button type="button" onClick={() => setForcedFor(b)}>Trotzdem abspielen</button>}
        {playing && (
          <>
            <button ref={pauseBtn} type="button" aria-disabled={canPause ? undefined : "true"} onClick={toggle}>
              {status.status === "pausiert" ? "Weiter" : "Pause"}
            </button>
            <button type="button" onClick={restart}>Neu starten</button>
          </>
        )}
        <p className="s-state" aria-live="polite">{status.wort}</p>
      </div>
      {playing && canTempo && (
        <div className="m-row s-tempo" role="group" aria-label="Tempo">
          {TEMPO_FAKTOREN.map((f) => (
            <button key={f} type="button" aria-pressed={tempo === f} onClick={() => setzeTempo(f)}>{TEMPO_WORT[f]}</button>
          ))}
          <p className="s-tempo-wort" aria-live="polite">Tempo: {TEMPO_WORT[tempo]}</p>
          {status.status === "zeitlupe" && <p className="v-note">{SATZ_TEMPO_ZEITLUPE}</p>}
        </div>
      )}
      {fig && fig.ausserhalb > 0 && (
        <p className="v-note">{`${fig.ausserhalb} Körper außerhalb des Bildausschnitts.`}</p>
      )}
      {regler.length > 0 && (
        <div className="m-row s-regler" role="group" aria-label="Regler">
          {regler.map((r, i) => {
            const id = `${uid}-regler-${i}`;
            const gezogen = shown && shown.for === b ? shown.werte[r.feld] : undefined;
            const w = gezogen ?? leseWert(cfg, r.feld) ?? r.min;
            const txt = reglerText(r, w);
            return (
              <div key={r.feld} className="m-slider s-slider">
                <label htmlFor={id}>{r.name}</label>
                <input id={id} type="range" min={0} max={stufen(r)} step={1} value={posAusWert(r, w)} aria-valuetext={txt}
                  onChange={(e) => ziehe(r, wertAusPos(r, Number(e.currentTarget.value)))} onKeyDown={taste(r, w)} onKeyUp={loslassen}
                  onPointerUp={loslassen} onMouseUp={loslassen} onTouchEnd={loslassen} onBlur={loslassen} />
                <span className="num" aria-hidden="true">{txt}</span>
              </div>
            );
          })}
          <button type="button" aria-disabled={edited ? undefined : "true"} onClick={zurueck}>Zurück auf die Werte von Claude</button>
        </div>
      )}
      {bild && (bild.modell === "pendel" || bild.modell === "feder") && (
        <figure className="s-curve">
          <canvas ref={curve} style={{ height: CURVE_H }} aria-hidden="true" />
          <figcaption className="v-note">
            {bild.kurve.length > 1
              ? `${bild.groesse} in ${bild.einheit} über die Zeit, etwa drei Schwingungen (${formatWert(bild.dauer)} s). Die Nulllinie ist die Ruhelage.`
              : "Die Kurve kann nicht gezeigt werden."}
          </figcaption>
        </figure>
      )}
      {bild?.modell === "wurf" && (
        <p className="v-note">
          Gestrichelt: die ganze Bahn. Gipfel (Dreieck): {formatWert(bild.gipfel[1])} m hoch bei {formatWert(bild.gipfel[0])} m Weite.{" "}
          {bild.vollstaendig
            ? `Aufprall (Kreuz): bei ${formatWert(bild.aufprall[0])} m Weite nach ${formatWert(bild.flugzeit)} s.`
            : `Die Bahn ist nur bis ${formatWert(bild.flugzeit)} s vorausgerechnet; der Aufprall liegt später.`}
        </p>
      )}
      {bild?.modell === "umlauf" && (
        <p className="v-note">
          {bild.offen
            ? `Die gerechneten Wege über ${formatWert(bild.dauer ?? 0)} Jahre als offene Linien, die Körper in ihrer Startlage.`
            : "Alle Bahnen als Linien, die Körper in ihrer Startlage."}
        </p>
      )}
      {bild?.modell === "doppelpendel" && (
        <p className="v-note">
          {bild.bahn.length > 1
            ? `Gestrichelt: der Weg des unteren Körpers in den ersten ${formatWert(bild.dauer)} s. Die Arme stehen in der Startlage.`
            : "Der Weg des unteren Körpers kann nicht gezeigt werden. Die Arme stehen in der Startlage."}
        </p>
      )}
      {bild?.modell === "welle" && (
        <p className="v-note">
          Die Kurve zur Zeit 0. Gestrichelt: die Hülle, also der kleinste und größte Ausschlag an jeder Stelle über {formatWert(bild.dauer)} s.{" "}
          {bild.exakt ? "Die Hülle ist genau gerechnet." : "Die Hülle ist nur abgetastet und kann etwas zu eng sein."}
        </p>
      )}
      {cfg.modell === "welle" && info && (
        <p className="v-note">
          Waagerecht: Ort von 0 bis {formatZahl(info.ausschnitt.maxX)} m. Senkrecht: Auslenkung bis{" "}
          {formatZahl(wellen.reduce((s, q) => s + q.amplitude, 0))} m nach oben und unten (Summe der Amplituden).
          {wellen.length > 1 ? " Dicke Linie: die Summe. Dünne Linien: die einzelnen Wellen." : ""}
        </p>
      )}
      {info && info.koerper.length > 0 && (
        <ul className="s-legend" aria-label="Körper">
          <li>Zentralmasse in der Mitte (Bernstein, größerer Punkt)</li>
          {info.koerper.map((k, i) => <li key={i}><span className="s-name">{k.name}</span>: {FARBE_WORT[k.farbe] ?? "Cyan"}</li>)}
        </ul>
      )}
      {fig && (
        <div className="v-table-wrap">
          <table className="v-table s-figures">
            <caption className="label">{still || noCtx ? "Kennwerte am Start" : "Kennwerte"}</caption>
            <tbody>
              {playing && <tr><th scope="row">Zeit in der Simulation</th><td className="num">{formatWert(fig.zeit)} {fig.einheit}</td></tr>}
              {fig.kennwerte.map((k) => <tr key={k.id}><th scope="row">{k.name}</th><td className="num">{k.text}</td></tr>)}
            </tbody>
          </table>
        </div>
      )}
      {dist && (
        <figure className="s-dist">
          <figcaption className="label">
            {bild?.modell === "gas" ? `Verteilung der Geschwindigkeiten nach ${formatWert(bild.zeit)} s gerechneter Zeit`
              : still || noCtx ? "Verteilung der Geschwindigkeiten am Start" : "Verteilung der Geschwindigkeiten, einmal je Sekunde neu"}
          </figcaption>
          {!noCtx && <canvas ref={distCanvas} style={{ height: DIST_H }} aria-hidden="true" />}
          <details className="m-list">
            <summary>Verteilung als Zahlen</summary>
            <table className="v-table">
              <thead><tr><th scope="col">Geschwindigkeit in Einheiten/s</th><th scope="col">Teilchen</th></tr></thead>
              <tbody>
                {dist.anzahl.map((n, i) => (
                  <tr key={i}>
                    <td>{i === dist.anzahl.length - 1 ? `ab ${formatWert(g[i])}` : `${formatWert(g[i])} bis unter ${formatWert(g[i + 1])}`}</td>
                    <td className="num">{n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </figure>
      )}
      <div className="s-text">
        <span className="label">Beschreibung</span>
        <p>{info?.text ?? ""}</p>
        {regler.length > 0 && (
          <p>
            {`Regler: ${reglerSatz(regler, cfg)}.`}
            {edited ? ` Mit den Reglern geändert; die Werte von Claude: ${reglerSatz(regler, orig)}.` : ""}
          </p>
        )}
        {cfg.beschreibung && <p>{cfg.beschreibung}</p>}
        {cfg.beschreibung && edited && <p className="v-note">{SATZ_BESCHREIBUNG_ALT}</p>}
      </div>
    </section>
  );
}
