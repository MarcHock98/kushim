import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import {
  addEigenSpuren, advanceEigen, createEigen, createEigenSpuren, EIGEN, EIGEN_HINWEIS, eigenEndlich, eigenRegler, mitParameter, snapshotEigen,
  type EigenGrund, type EigenSnapshot, type EigenSpuren, type EigenState,
} from "../../lib/eigenSim";
import { FARBEN, formatWert, formatZahl, SPUR_MAX, type Ausschnitt, type Farbe, type GrenzFeld, type Kennwert, type Trail } from "../../lib/physics";
import { PALETTE_VAR } from "../../lib/scene";
import {
  createSimLoop, MAX_FPS, TEMPO_FAKTOREN, type FrameScheduler, type LoopState, type LoopStatus, type SimEngine, type SimLoop, type TempoFaktor,
} from "../../lib/simLoop";
import type { EigenBlock } from "../../lib/stage";
import { useBoxSize } from "../../lib/useBoxSize";
import { Tex } from "./Tex";

// Baustein `sim_eigen` (Plan docs/ui-p7-plan.md, Stufe 1): eine eigene Simulation, die kushim als Daten beschrieben hat. Gerechnet wird
// in lib/eigenSim.ts (Formeln nur als geprüftes RPN über lib/formel.ts), getaktet in lib/simLoop.ts (höchstens 30 Bilder je Sekunde,
// Stopp nach der Laufzeit, verdeckt oder außer Sicht kein Schritt). Diese Datei zeichnet nur (Canvas 2D) und bedient; sie liest nie
// Formeltext und führt keine Formel selbst aus. Gleichungen erscheinen als TeX über Tex.tsx (`trust: false`).
// Das Abzeichen „Eigene Simulation · ungeprüft“ und der Satz EIGEN_HINWEIS kommen von der Oberfläche, nicht aus der Ansicht.
// Pause, Weiter, Neu starten, Tempo und Regler ändern nur die Anzeige im Fenster: nichts wird gesendet, gespeichert oder abgespielt.
// Ein Regler baut mit `mitParameter` eine neue Eingabe (in den Grenzen der Ansicht) und startet die Simulation damit neu.
// Bei „weniger Bewegung“ gibt es keine Schleife, sondern ein vorausgerechnetes Standbild und den Knopf „Trotzdem abspielen“.

const BADGE = "Eigene Simulation · ungeprüft";
const FIG_MS = 500;              // Werte höchstens zweimal je Sekunde neu
const DESC_MS = 2000;            // Textfassung der Bilder (aria-label) höchstens alle 2 s neu
const REGLER_MS = 200;           // Regler: höchstens ein Neustart je 200 ms beim Ziehen und Tippen
const AENDERUNG_MS = 12_000;     // so lange steht „Geändert: d: 0,2 → 0,5“ nach einem neuen `zeige`
const LOG_N = 1000;
const DPR_MAX = 1.5;
const DEFAULT_W = 640, H_MIN = 180, H_MAX = 420, PAD = 10, PFEIL_MAX = 28;
const VORAUS_BILDER = 600, VORAUS_KNOTEN_MAX = 400_000;
const REDUCE = "(prefers-reduced-motion: reduce)";
const STILL_WORT = "Standbild, weniger Bewegung ist eingestellt";
const TEMPO_WORT: Record<TempoFaktor, string> = { 0.5: "halb", 1: "normal", 2: "doppelt" };
const REIHE_FARBE: readonly Farbe[] = ["arc", "amber", "ok", "text"];
const REIHE_WORT = ["Cyan, durchgezogen", "Bernstein, gestrichelt", "Grün, gepunktet", "Weiß, Strich und Punkt"];
const REIHE_DASH: readonly number[][] = [[], [7, 4], [2, 3], [9, 3, 2, 3]];
const GRUND_SATZ: Record<EigenGrund, string> = {
  nicht_endlich: "Eine Zahl ist nicht mehr endlich, etwa durch Teilen durch 0. Die Simulation ist angehalten.",
  zu_gross: "Ein Wert ist über eine Milliarde gewachsen. Die Simulation ist angehalten.",
  eingabe: "Die Angaben reichen nicht zum Rechnen.",
};
const GRIECHISCH = new Set([
  "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa", "lambda", "mu", "nu", "xi", "rho",
  "sigma", "tau", "upsilon", "phi", "chi", "psi", "omega", "Gamma", "Delta", "Theta", "Lambda", "Xi", "Sigma", "Upsilon",
  "Phi", "Psi", "Omega", "varphi", "vartheta", "varepsilon",
]);

type PlotArt = "koerper" | "pfeile" | "zeitreihe" | "phasenraum";
type Obj = Record<string, unknown>;
interface Pal { farbe: Record<Farbe, string>; line: string; strong: string; muted: string; amber: string }
interface PlotGfx { art: PlotArt; ctx: CanvasRenderingContext2D | null; w: number; h: number; dpr: number }
interface Gfx {
  pal: Pal | null; snap: EigenSnapshot | null; sp: EigenSpuren | null; sim: EigenState | null; plots: PlotGfx[];
  /** Standbild: Zeitachse der Zeitreihe von 0 bis `dauer`; sonst das gleitende Fenster der Spur. */
  still: boolean; dauer: number; faktor: number;
}
interface Figures {
  zeit: number; kennwerte: Kennwert[]; werte: { name: string; wert: number; einheit: string }[]; hinweis: string | null;
  teilchen: number; fest: number;
}
interface Gleichung { key: string; tex: string; label?: string }
interface Status { status: LoopStatus | ""; wort: string; grund: EigenGrund | null }

const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const own = (o: Obj, k: string): unknown => (Object.prototype.hasOwnProperty.call(o, k) ? o[k] : undefined);
const str = (v: unknown, max = 2000): string => (typeof v === "string" && v.length <= max ? v : "");
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const running = (s: LoopStatus | "") => s === "laeuft" || s === "zeitlupe";
const prefersReduced = (): boolean => {
  try { return typeof matchMedia === "function" && !!matchMedia(REDUCE).matches; } catch { return false; }
};
const dprNow = () => Math.min(typeof window !== "undefined" && window.devicePixelRatio > 0 ? window.devicePixelRatio : 1, DPR_MAX);
const mitEinheit = (wert: number, einheit: string) => (einheit ? `${formatWert(wert)} ${einheit}` : formatWert(wert));

// --- Gleichungen als TeX (nur Namen werden hier gesetzt; die Formeln kommen fertig als TeX aus der geprüften Ansicht) -----------

/** TeX für einen Namen wie im Backend (formel.py, _tex_name): griechisch als Befehl, ein Buchstabe kursiv, sonst aufrecht, der Teil
 *  nach dem ersten Unterstrich als Index. Nur ASCII-Buchstaben, Ziffern und Unterstrich, sonst null (dann steht der Name als Text da). */
function texName(name: string): string | null {
  if (!name || name.length > 24) return null;
  for (let i = 0; i < name.length; i++) {
    const c = name.charCodeAt(i), buchstabe = (c >= 65 && c <= 90) || (c >= 97 && c <= 122);
    if (!(buchstabe || (i > 0 && ((c >= 48 && c <= 57) || c === 95)))) return null;
  }
  const u = name.indexOf("_");
  const basis = u > 0 ? name.slice(0, u) : name, rest = u > 0 ? name.slice(u + 1) : "";
  const kopf = GRIECHISCH.has(basis) ? `\\${basis}` : basis.length === 1 ? basis : `\\mathrm{${basis}}`;
  return rest ? `${kopf}_{\\mathrm{${rest.replaceAll("_", "\\_")}}}` : kopf;
}

/** TeX einer Formel aus der Ansicht (`{rpn, tex}`), sonst "". */
const texVon = (f: unknown): string => (isObj(f) ? str(own(f, "tex")) : "");

/** Alle Gleichungen der Ansicht: Hilfsgrößen, Ableitungen (x' = …) bzw. Kräfte, Lage des Körpers, Kennwerte und Erhaltungsgröße. */
function gleichungen(input: unknown): Gleichung[] {
  if (!isObj(input)) return [];
  const out: Gleichung[] = [];
  const mit = (key: string, name: string, links: string, tex: string) => {
    if (!tex) return;
    const n = texName(name);
    out.push(n ? { key, tex: `${links.replace("%", n)} = ${tex}` } : { key, tex, label: `${name}${links.endsWith("'") ? "'" : ""} =` });
  };
  if (own(input, "form") === "teilchen") {
    const k = own(input, "kraft"), p = own(input, "paar");
    if (isObj(k)) {
      const fx = texVon(own(k, "fx")), fy = texVon(own(k, "fy"));
      if (fx) out.push({ key: "fx", tex: `F_x = ${fx}` });
      if (fy) out.push({ key: "fy", tex: `F_y = ${fy}` });
    }
    if (isObj(p)) { const t = texVon(own(p, "f_r")); if (t) out.push({ key: "paar", tex: `F(r) = ${t}`, label: "Kraft zwischen zwei Teilchen:" }); }
    return out;
  }
  const hilf = own(input, "hilf");
  if (Array.isArray(hilf)) hilf.slice(0, 12).forEach((h, i) => { if (isObj(h)) mit(`h${i}`, str(own(h, "name"), 24), "%", texVon(own(h, "formel"))); });
  const zustand = own(input, "zustand"), ab = own(input, "ableitungen");
  if (Array.isArray(zustand)) zustand.slice(0, 12).forEach((z, i) => {
    const name = isObj(z) ? str(own(z, "name"), 24) : "";
    const f = Array.isArray(ab) ? ab[i] : isObj(ab) && name ? own(ab, name) : undefined;
    if (name) mit(`a${i}`, name, "%'", texVon(f));
  });
  const dars = own(input, "darstellung");
  if (Array.isArray(dars)) for (const d of dars.slice(0, 2)) {
    if (!isObj(d) || own(d, "form") !== "koerper") continue;
    const x = texVon(own(d, "x")), y = texVon(own(d, "y"));
    if (x) out.push({ key: "kx", tex: x, label: "Körper waagerecht =" });
    if (y) out.push({ key: "ky", tex: y, label: "Körper senkrecht =" });
  }
  const kw = own(input, "kennwerte");
  if (Array.isArray(kw)) kw.slice(0, 4).forEach((k, i) => {
    const t = isObj(k) ? texVon(own(k, "formel")) : "";
    if (t && isObj(k)) out.push({ key: `k${i}`, tex: t, label: `${str(own(k, "name"), 80) || "Kennwert"} =` });
  });
  const er = texVon(own(input, "erhaltung"));
  if (er) out.push({ key: "erhaltung", tex: er, label: "Erhaltungsgröße =" });
  return out;
}

/** Federn der Teilchen als Satz (Zahlen aus der Ansicht). */
function federSatz(input: unknown): string {
  const f = isObj(input) ? own(input, "federn") : undefined;
  if (!isObj(f)) return "";
  const n = (k: string) => { const v = own(f, k); return typeof v === "number" && Number.isFinite(v) ? formatZahl(v) : "–"; };
  const paare = own(f, "paare");
  const anzahl = Array.isArray(paare) ? paare.length : 0;
  return `Federn (${anzahl}): Federkonstante ${n("k")}, Ruhelänge ${n("l0")}, Dämpfung ${n("daempfung")}.`;
}

// --- Änderung über einen neuen `zeige`-Aufruf ------------------------------------------------------------------------------

const paramListe = (v: unknown): { name: string; wert: number; einheit: string }[] => {
  const l = isObj(v) ? own(v, "parameter") : undefined;
  if (!Array.isArray(l)) return [];
  return l.filter(isObj).map((p) => ({ name: str(own(p, "name"), 24), wert: Number(own(p, "wert")), einheit: str(own(p, "einheit"), 20) }));
};
const ohneParameter = (v: Obj): string => {
  try { const { parameter: _p, ...rest } = v; return JSON.stringify(rest); } catch { return ""; }
};

/** Was sich gegenüber der vorigen Fassung derselben Ansicht geändert hat: Parameter als „d: 0,2 → 0,5“, sonst nur ein Satz. */
export function aenderungen(vorher: unknown, jetzt: unknown): { parameter: string[]; sonst: boolean } {
  if (!isObj(vorher) || !isObj(jetzt) || own(vorher, "typ") !== "sim_eigen") return { parameter: [], sonst: false };
  const alt = paramListe(vorher);
  const parameter = paramListe(jetzt).flatMap((p) => {
    const q = alt.find((a) => a.name === p.name);
    if (!q || !p.name || !Number.isFinite(q.wert) || !Number.isFinite(p.wert) || q.wert === p.wert) return [];
    return [`${p.name}: ${formatZahl(q.wert)} → ${formatZahl(p.wert)}${p.einheit ? ` ${p.einheit}` : ""}`];
  });
  const namenAlt = alt.map((a) => a.name).join(","), namenNeu = paramListe(jetzt).map((a) => a.name).join(",");
  return { parameter, sonst: namenAlt !== namenNeu || ohneParameter(vorher) !== ohneParameter(jetzt) };
}

// --- Regler (wie Simulation.tsx) -------------------------------------------------------------------------------------------

const stellen = (s: number): number => { const t = String(s), i = t.indexOf("."); return i < 0 ? 0 : t.length - i - 1; };
const aufSchritt = (v: number, g: GrenzFeld): number =>
  clamp(Number((Math.round(v / g.schritt) * g.schritt).toFixed(Math.min(12, stellen(g.schritt)))), g.min, g.max);
const stufen = (g: GrenzFeld): number => (g.skala === "log" ? LOG_N : Math.max(1, Math.round((g.max - g.min) / g.schritt)));
function wertAusPos(g: GrenzFeld, pos: number): number {
  const n = stufen(g), p = clamp(Number.isFinite(pos) ? Math.round(pos) : 0, 0, n);
  if (g.skala === "log") return aufSchritt(Number((g.min * Math.pow(g.max / g.min, p / n)).toPrecision(3)), g);
  return aufSchritt(g.min + p * g.schritt, g);
}
function posAusWert(g: GrenzFeld, v: number): number {
  const n = stufen(g);
  if (!Number.isFinite(v)) return 0;
  if (g.skala === "log") return clamp(Math.round((n * Math.log(Math.max(v, g.min) / g.min)) / Math.log(g.max / g.min)), 0, n);
  return clamp(Math.round((v - g.min) / g.schritt), 0, n);
}
const SCHRITT_TASTE: Record<string, number> = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1, PageUp: 10, PageDown: -10 };
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
const reglerText = (g: GrenzFeld, v: number) => (g.einheit ? `${formatZahl(v)} ${g.einheit}` : formatZahl(v));

// --- Darstellungen ---------------------------------------------------------------------------------------------------------

/** Welche Bilder gezeigt werden (höchstens 2), in der Reihenfolge der Ansicht; nur, was der Rechenkern auch liefern kann. */
function plotsOf(s: EigenState, input: unknown): PlotArt[] {
  const k = s.kern, wanted: string[] = [];
  const d = isObj(input) ? own(input, "darstellung") : undefined;
  if (Array.isArray(d)) for (const e of d.slice(0, 2)) { const f = isObj(e) ? own(e, "form") : undefined; if (typeof f === "string" && !wanted.includes(f)) wanted.push(f); }
  const out: PlotArt[] = [];
  for (const f of wanted) {
    if (k.art === "ode") {
      if (f === "koerper" && k.koerperX && k.koerperY) out.push("koerper");
      else if (f === "zeitreihe" && k.reihe.length) out.push("zeitreihe");
      else if (f === "phasenraum" && k.phasen) out.push("phasenraum");
    } else if (f === "koerper" || (f === "pfeile" && k.pfeile)) out.push(f);
  }
  if (!out.length) {
    if (k.art === "ode" && k.reihe.length) out.push("zeitreihe");
    else if (k.art === "teilchen") out.push(k.pfeile ? "pfeile" : "koerper");
  }
  return out.slice(0, 2);
}

/** Bereich einer oder mehrerer Größen aus der Vorausrechnung, mit Rand; zu schmal: aufgeweitet. */
function bereich(s: EigenState | null, namen: readonly string[]): [number, number] {
  let lo = Infinity, hi = -Infinity;
  for (const b of s?.bereiche ?? []) if (namen.includes(b.name) && Number.isFinite(b.min) && Number.isFinite(b.max)) { lo = Math.min(lo, b.min); hi = Math.max(hi, b.max); }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [-1, 1];
  const w = hi - lo;
  if (w < 1e-9) { const m = Math.max(1e-9, 0.1 * Math.abs(lo), Math.abs(lo) < 1e-9 ? 1 : 0); return [lo - m, hi + m]; }
  return [lo - 0.08 * w, hi + 0.08 * w];
}

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

function sizeCanvas(c: HTMLCanvasElement | null, w: number, h: number): number {
  const dpr = dprNow();
  if (c) {
    const W = Math.max(1, Math.round(w * dpr)), H = Math.max(1, Math.round(h * dpr));
    if (c.width !== W) c.width = W;
    if (c.height !== H) c.height = H;
  }
  return dpr;
}

/** Gleicher Maßstab auf beiden Achsen, mittig, y nach oben (Körper und Teilchen). */
function mapper(a: Ausschnitt, w: number, h: number) {
  const iw = Math.max(1, w - 2 * PAD), ih = Math.max(1, h - 2 * PAD);
  const aw = a.maxX - a.minX > 0 ? a.maxX - a.minX : 1, ah = a.maxY - a.minY > 0 ? a.maxY - a.minY : 1;
  const s = Math.min(iw / aw, ih / ah);
  const ox = PAD + (iw - aw * s) / 2, oy = PAD + (ih - ah * s) / 2;
  return { s, X: (x: number) => ox + (x - a.minX) * s, Y: (y: number) => oy + (a.maxY - y) * s };
}
/** Jede Achse für sich (Zeitreihe, Phasenraum). */
function mapperFrei(x0: number, x1: number, y0: number, y1: number, w: number, h: number) {
  const iw = Math.max(1, w - 2 * PAD), ih = Math.max(1, h - 2 * PAD);
  const dx = x1 - x0 > 0 ? x1 - x0 : 1, dy = y1 - y0 > 0 ? y1 - y0 : 1;
  return { s: 1, X: (x: number) => PAD + ((x - x0) / dx) * iw, Y: (y: number) => PAD + ((y1 - y) / dy) * ih };
}
type Map2 = ReturnType<typeof mapper>;

/** Zeichnet die Spur `i` (Ringpuffer, älteste zuerst); `ab`: nur Punkte mit x ≥ ab (Zeitfenster). */
function spurLinie(ctx: CanvasRenderingContext2D, t: Trail, i: number, m: Map2, ab = -Infinity): void {
  const n = t.laenge[i] ?? 0;
  if (n < 2) return;
  ctx.beginPath();
  let first = true;
  for (let j = 0; j < n; j++) {
    const q = (t.anfang[i] + j) % t.max, x = t.xs[i][q];
    if (x < ab) continue;
    const px = m.X(x), py = m.Y(t.ys[i][q]);
    if (first) { ctx.moveTo(px, py); first = false; } else ctx.lineTo(px, py);
  }
  ctx.stroke();
}

function clipRect(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  ctx.beginPath(); ctx.rect(0, 0, w, h); ctx.clip();
}

function paintKoerperOde(ctx: CanvasRenderingContext2D, g: Gfx, snap: EigenSnapshot, pal: Pal, m: Map2): void {
  const body = snap.koerper[0];
  if (g.sp && g.sim?.config.spur) {
    ctx.strokeStyle = pal.farbe.arc; ctx.lineWidth = 1.5; ctx.globalAlpha = 0.45;
    spurLinie(ctx, g.sp.koerper, 0, m);
    ctx.globalAlpha = 1;
  }
  if (snap.anker) {
    const ax = m.X(snap.anker[0]), ay = m.Y(snap.anker[1]);
    ctx.strokeStyle = pal.strong; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(ax - 24, ay); ctx.lineTo(ax + 24, ay); ctx.stroke();            // Decke
    if (body) { ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(m.X(body.x), m.Y(body.y)); ctx.stroke(); }   // Stab
    ctx.fillStyle = pal.muted;
    ctx.beginPath(); ctx.arc(ax, ay, 3, 0, 2 * Math.PI); ctx.fill();
  }
  if (body) {
    ctx.fillStyle = pal.farbe.arc;
    ctx.beginPath(); ctx.arc(m.X(body.x), m.Y(body.y), 9, 0, 2 * Math.PI); ctx.fill();
  }
}

function paintTeilchen(ctx: CanvasRenderingContext2D, g: Gfx, snap: EigenSnapshot, pal: Pal, m: Map2, pfeile: boolean): void {
  const k = g.sim?.kern;
  if (k && k.art === "teilchen") {
    ctx.strokeStyle = pal.strong; ctx.lineWidth = 1.5;
    ctx.strokeRect(m.X(0), m.Y(k.h), k.b * m.s, k.h * m.s);                                     // Kasten
    const per = k.waende === "periodisch";
    ctx.strokeStyle = pal.muted; ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (const [a, c] of snap.federn) {                                                         // Federn als Linien
      const p = snap.koerper[a], q = snap.koerper[c];
      if (!p || !q || (per && (Math.abs(p.x - q.x) > k.b / 2 || Math.abs(p.y - q.y) > k.h / 2))) continue;
      ctx.moveTo(m.X(p.x), m.Y(p.y)); ctx.lineTo(m.X(q.x), m.Y(q.y));
    }
    ctx.stroke();
  }
  const r = snap.koerper.length > 100 ? 3 : 4.5;
  ctx.fillStyle = pal.farbe.arc;
  ctx.beginPath();
  snap.koerper.forEach((p, i) => {
    if (snap.fest.includes(i)) return;
    const x = m.X(p.x), y = m.Y(p.y);
    ctx.moveTo(x + r, y); ctx.arc(x, y, r, 0, 2 * Math.PI);
  });
  ctx.fill();
  ctx.fillStyle = pal.amber;                                                                    // feste Teilchen: Quadrat in Bernstein
  for (const i of snap.fest) { const p = snap.koerper[i]; if (p) ctx.fillRect(m.X(p.x) - 5, m.Y(p.y) - 5, 10, 10); }
  if (pfeile && snap.pfeile) {
    let vmax = 0;
    for (const q of snap.pfeile) vmax = Math.max(vmax, Math.hypot(q[2], q[3]));
    if (vmax > 0) {
      ctx.strokeStyle = pal.farbe.text; ctx.lineWidth = 1.5;
      ctx.beginPath();
      for (const [x, y, vx, vy] of snap.pfeile) {
        const v = Math.hypot(vx, vy), L = (v / vmax) * PFEIL_MAX;
        if (L < 2) continue;
        const ux = vx / v, uy = -vy / v, x0 = m.X(x), y0 = m.Y(y), x1 = x0 + ux * L, y1 = y0 + uy * L;
        ctx.moveTo(x0, y0); ctx.lineTo(x1, y1);
        ctx.moveTo(x1, y1); ctx.lineTo(x1 - 6 * ux + 4 * uy, y1 - 6 * uy - 4 * ux);
        ctx.moveTo(x1, y1); ctx.lineTo(x1 - 6 * ux - 4 * uy, y1 - 6 * uy + 4 * ux);
      }
      ctx.stroke();
    }
  }
}

/** Zeitfenster der Zeitreihe: im Standbild 0 bis Dauer, sonst so viel Modellzeit, wie die Spur fasst, bis jetzt. */
function zeitFenster(g: Gfx, snap: EigenSnapshot): [number, number] {
  if (g.still) return [0, Math.max(g.dauer, 1e-6)];
  const f = (SPUR_MAX / MAX_FPS) * (g.sim?.tempo ?? 1) * g.faktor, t1 = Math.max(f, snap.zeit);
  return [t1 - f, t1];
}

function paintReihe(ctx: CanvasRenderingContext2D, g: Gfx, snap: EigenSnapshot, pal: Pal, w: number, h: number): void {
  const namen = snap.zeitreihe.map((q) => q.name), [y0, y1] = bereich(g.sim, namen), [t0, t1] = zeitFenster(g, snap);
  const m = mapperFrei(t0, t1, y0, y1, w, h);
  ctx.strokeStyle = pal.line; ctx.lineWidth = 1;
  if (y0 < 0 && y1 > 0) { ctx.beginPath(); ctx.moveTo(PAD, m.Y(0)); ctx.lineTo(w - PAD, m.Y(0)); ctx.stroke(); }   // Nulllinie
  if (!g.sp) return;
  ctx.lineWidth = 2;
  namen.forEach((_, j) => {
    ctx.strokeStyle = pal.farbe[REIHE_FARBE[j] ?? "text"]; ctx.setLineDash(REIHE_DASH[j] ?? []);
    spurLinie(ctx, g.sp!.zeitreihe, j, m, t0);
  });
  ctx.setLineDash([]);
}

function paintPhasen(ctx: CanvasRenderingContext2D, g: Gfx, snap: EigenSnapshot, pal: Pal, w: number, h: number): void {
  const p = snap.phasen;
  if (!p) return;
  const [x0, x1] = bereich(g.sim, [p.x]), [y0, y1] = bereich(g.sim, [p.y]), m = mapperFrei(x0, x1, y0, y1, w, h);
  ctx.strokeStyle = pal.line; ctx.lineWidth = 1;
  if (y0 < 0 && y1 > 0) { ctx.beginPath(); ctx.moveTo(PAD, m.Y(0)); ctx.lineTo(w - PAD, m.Y(0)); ctx.stroke(); }
  if (x0 < 0 && x1 > 0) { ctx.beginPath(); ctx.moveTo(m.X(0), PAD); ctx.lineTo(m.X(0), h - PAD); ctx.stroke(); }
  if (g.sp) { ctx.strokeStyle = pal.farbe.arc; ctx.lineWidth = 1.5; ctx.globalAlpha = 0.7; spurLinie(ctx, g.sp.phasen, 0, m); ctx.globalAlpha = 1; }
  ctx.fillStyle = pal.amber;
  ctx.beginPath(); ctx.arc(m.X(p.punkt[0]), m.Y(p.punkt[1]), 5, 0, 2 * Math.PI); ctx.fill();
}

/** Alle Bilder neu. Wirft nie; `false` heißt Zeichenfehler (dann hält die Ansicht an und sagt es). */
function paintAll(g: Gfx): boolean {
  const { snap, pal } = g;
  if (!snap || !pal) return true;
  try {
    for (const p of g.plots) {
      const ctx = p.ctx;
      if (!ctx) continue;
      ctx.setTransform(p.dpr, 0, 0, p.dpr, 0, 0);
      ctx.clearRect(0, 0, p.w, p.h);
      ctx.globalAlpha = 1; ctx.setLineDash([]); ctx.lineCap = "round"; ctx.lineJoin = "round";
      ctx.save();
      clipRect(ctx, p.w, p.h);
      if (p.art === "zeitreihe") paintReihe(ctx, g, snap, pal, p.w, p.h);
      else if (p.art === "phasenraum") paintPhasen(ctx, g, snap, pal, p.w, p.h);
      else {
        const m = mapper(snap.ausschnitt, p.w, p.h);
        if (snap.form === "ode") paintKoerperOde(ctx, g, snap, pal, m); else paintTeilchen(ctx, g, snap, pal, m, p.art === "pfeile");
      }
      ctx.restore();
    }
    return true;
  } catch {
    return false;
  }
}

// --- Zahlen und Textfassung -------------------------------------------------------------------------------------------------

const figOf = (s: EigenSnapshot): Figures => ({
  zeit: s.zeit, kennwerte: s.kennwerte, werte: s.werte, hinweis: s.hinweis, teilchen: s.form === "teilchen" ? s.koerper.length : 0, fest: s.fest.length,
});

/** Kurze Textfassung des aktuellen Bilds für die Beschriftung der Zeichenflächen. */
function descOf(f: Figures | null): string {
  if (!f) return "";
  const teile = [`Zeit ${formatWert(f.zeit)} s`];
  if (f.teilchen) teile.push(`${f.teilchen} Teilchen${f.fest ? `, davon ${f.fest} fest` : ""}`);
  if (f.werte.length) teile.push(f.werte.map((w) => `${w.name} ${mitEinheit(w.wert, w.einheit)}`).join(", "));
  if (f.kennwerte.length) teile.push(f.kennwerte.map((k) => `${k.name} ${k.text}`).join(", "));
  return `${teile.join(". ")}.`;
}

/** Namen der Zeitreihe und des Phasenraums aus dem Rechenkern (ODE), sonst leer. */
function namenOf(s: EigenState): { reihe: string[]; phasen: [string, string] | null; anker: boolean } {
  const k = s.kern;
  if (k.art !== "ode") return { reihe: [], phasen: null, anker: false };
  return { reihe: k.reihe.map((i) => k.namen[i] ?? ""), phasen: k.phasen ? [k.namen[k.phasen[0]] ?? "", k.namen[k.phasen[1]] ?? ""] : null, anker: !!k.anker };
}

function plotLabel(art: PlotArt, s: EigenState): string {
  const n = namenOf(s);
  switch (art) {
    case "koerper":
      if (s.form === "teilchen") return "Bild der Teilchen im Kasten; feste Teilchen als Quadrat, Federn als Linien";
      return n.anker ? "Bild des Körpers mit Aufhängung und Stab" : "Bild der Lage des Körpers";
    case "pfeile": return "Bild der Teilchen mit Pfeilen für die Geschwindigkeit";
    case "zeitreihe": return `Zeitreihe von ${n.reihe.join(", ")}`;
    case "phasenraum": return n.phasen ? `Phasenraum, waagerecht ${n.phasen[0]}, senkrecht ${n.phasen[1]}` : "Phasenraum";
  }
}

/** Standbild für „weniger Bewegung“: eine frische Simulation, vorausgerechnet über die Laufzeit (höchstens VORAUS_KNOTEN_MAX). */
function vorausBild(input: unknown): { sim: EigenState; snap: EigenSnapshot; sp: EigenSpuren } {
  const s = createEigen(input), sp = createEigenSpuren(s);
  let snap = s.startBild;
  if (eigenEndlich(snap)) addEigenSpuren(sp, snap);
  const je = (s.config.laufzeit * s.tempo) / VORAUS_BILDER;
  let knoten = 0;
  for (let i = 0; i < VORAUS_BILDER && s.phase === "laeuft" && knoten < VORAUS_KNOTEN_MAX; i++) {
    knoten += advanceEigen(s, je).knoten;
    const neu = snapshotEigen(s);
    if (!eigenEndlich(neu)) break;
    snap = neu;
    addEigenSpuren(sp, snap);
  }
  return { sim: s, snap, sp };
}

// --- Baustein ---------------------------------------------------------------------------------------------------------------

const PLOT_H = (art: PlotArt, w: number, a: Ausschnitt): number => {
  if (art === "zeitreihe") return Math.round(clamp(w * 0.3, 140, 220));
  if (art === "phasenraum") return Math.round(clamp(w * 0.6, H_MIN, 360));
  const ratio = a.maxX > a.minX && a.maxY > a.minY ? (a.maxY - a.minY) / (a.maxX - a.minX) : 0.5;
  return Math.round(clamp(w * ratio, H_MIN, H_MAX));
};

export function EigenSimulation({ b, vorher = null }: { b: EigenBlock; vorher?: unknown }) {
  const [edit, setEdit] = useState<{ for: EigenBlock; input: EigenBlock } | null>(null);
  const eff: EigenBlock = edit && edit.for === b ? edit.input : b;
  const sim0 = useMemo(() => createEigen(eff), [eff]);              // Prüfung, Text, Bildausschnitt; die Schleife rechnet selbst
  const ungueltig = sim0.config.ungueltig;
  const plots = useMemo(() => plotsOf(sim0, eff), [sim0, eff]);
  const regler = useMemo(() => eigenRegler(b), [b]);
  const gl = useMemo(() => gleichungen(b), [b]);
  const aend = useMemo(() => aenderungen(vorher, b), [vorher, b]);
  const [aendSichtbar, setAendSichtbar] = useState(true);
  const [shown, setShown] = useState<{ for: EigenBlock; werte: Record<string, number> } | null>(null);
  const [reduced, setReduced] = useState(prefersReduced);
  const [forcedFor, setForcedFor] = useState<EigenBlock | null>(null);
  const forced = forcedFor === b;
  const still = reduced && !forced;
  const [tempoFor, setTempoFor] = useState<{ for: EigenBlock; f: TempoFaktor } | null>(null);
  const tempo: TempoFaktor = tempoFor && tempoFor.for === b ? tempoFor.f : 1;
  const [canTempo, setCanTempo] = useState(false);
  const [status, setStatus] = useState<Status>({ status: "", wort: "", grund: null });
  const [fig, setFig] = useState<Figures | null>(null);
  const [desc, setDesc] = useState("");
  const [stillDauer, setStillDauer] = useState(0);
  const [noCtx, setNoCtx] = useState(false);
  const [brokenFor, setBrokenFor] = useState<EigenBlock | null>(null);
  const broken = brokenFor === b;

  const uid = useId();
  const wrap = useRef<HTMLElement>(null);
  const plotWrap = useRef<HTMLDivElement>(null);
  const c0 = useRef<HTMLCanvasElement>(null);
  const c1 = useRef<HTMLCanvasElement>(null);
  const pauseBtn = useRef<HTMLButtonElement>(null);
  const loopRef = useRef<SimLoop | null>(null);
  const effRef = useRef<EigenBlock>(eff);
  const tempoRef = useRef<TempoFaktor>(tempo);
  const thr = useRef<{ timer: number | null; pending: Record<string, number> | null }>({ timer: null, pending: null });
  const clocks = useRef({ fig: -Infinity, desc: -Infinity });
  const gfx = useRef<Gfx>({ pal: null, snap: null, sp: null, sim: null, plots: [], still: false, dauer: 0, faktor: 1 }).current;

  const box = useBoxSize(plotWrap);
  const cssW = Math.max(120, box?.width ?? DEFAULT_W);
  const cssWRef = useRef(cssW);
  const heights = plots.map((p) => PLOT_H(p, cssW, sim0.ausschnitt));
  const hKey = heights.join(",");
  const labels = useMemo(() => plots.map((p) => plotLabel(p, sim0)), [plots, sim0]);
  const namen = useMemo(() => namenOf(sim0), [sim0]);

  useEffect(() => { effRef.current = eff; tempoRef.current = tempo; gfx.faktor = tempo; cssWRef.current = cssW; });

  useEffect(() => {                                                    // „weniger Bewegung“ kann sich ändern; Listener räumt auf
    let mq: MediaQueryList | null = null;
    try { mq = typeof matchMedia === "function" ? matchMedia(REDUCE) : null; } catch { mq = null; }
    if (!mq || typeof mq.addEventListener !== "function") return;
    const on = () => setReduced(!!mq?.matches);
    mq.addEventListener("change", on);
    return () => mq?.removeEventListener("change", on);
  }, []);

  useEffect(() => {                                                    // Änderung kurz zeigen, Zeitgeber räumt auf
    setAendSichtbar(true);
    if (!aend.parameter.length && !aend.sonst) return;
    const t = window.setTimeout(() => setAendSichtbar(false), AENDERUNG_MS);
    return () => window.clearTimeout(t);
  }, [aend]);

  useEffect(() => {                                                    // Regler-Zeitgeber: neue Daten oder Abbau räumen ihn ab
    const t = thr.current;
    return () => { if (t.timer !== null) window.clearTimeout(t.timer); t.timer = null; t.pending = null; };
  }, [b]);

  useEffect(() => {                                                    // Größe der Zeichenflächen; neu zeichnen ohne neu zu rechnen
    const cs = [c0.current, c1.current];
    gfx.plots.forEach((p, i) => { p.w = cssW; p.h = heights[i] ?? H_MIN; p.dpr = sizeCanvas(cs[i] ?? null, p.w, p.h); });
    if (!paintAll(gfx)) { loopRef.current?.dispose(); setBrokenFor(b); }
  }, [cssW, hKey, gfx, b]);                                            // hKey steht für `heights`

  useEffect(() => {                                                    // Aufbau: Standbild oder Taktschleife, abgebaut bei neuen Daten
    if (ungueltig || broken) return;
    const cs = [c0.current, c1.current];
    const ctxs = plots.map((_, i) => getCtx(cs[i] ?? null));
    const hatCtx = plots.length > 0 && ctxs.every((c) => c !== null);
    gfx.plots = plots.map((art, i) => {
      const h = PLOT_H(art, cssWRef.current, sim0.ausschnitt);
      return { art, ctx: ctxs[i], w: cssWRef.current, h, dpr: sizeCanvas(cs[i] ?? null, cssWRef.current, h) };
    });
    gfx.pal = readPalette(); gfx.snap = null; gfx.sp = null; gfx.sim = null; gfx.still = still; gfx.dauer = 0;
    clocks.current = { fig: -Infinity, desc: -Infinity };
    setNoCtx(!hatCtx);
    if (still || !hatCtx) {                                            // keine Schleife: Standbild (vorausgerechnet) oder nur Text
      const v = still && hatCtx ? vorausBild(eff) : { sim: sim0, snap: sim0.startBild, sp: null };
      gfx.sim = v.sim; gfx.snap = v.snap; gfx.sp = v.sp; gfx.dauer = v.snap.zeit;
      const f = figOf(v.snap);
      setFig(f); setDesc(descOf(f)); setStillDauer(v.snap.zeit);
      setStatus({ status: "", wort: still ? STILL_WORT : "", grund: v.sim.phase === "instabil" ? v.sim.grund : null });
      setCanTempo(false);
      if (!paintAll(gfx)) setBrokenFor(b);
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
    let latest: EigenSnapshot | null = null, dead = false, loop: SimLoop | null = null;
    const flush = () => { if (latest) { const f = figOf(latest); setFig(f); setDesc(descOf(f)); } };
    const fail = () => { dead = true; loop?.dispose(); io?.disconnect(); setBrokenFor(b); };
    const scheduler: FrameScheduler = {
      now: () => performance.now(),
      requestFrame: (cb) => (typeof requestAnimationFrame === "function" ? requestAnimationFrame(cb) : window.setTimeout(() => cb(performance.now()), 33)),
      cancelFrame: (id) => (typeof cancelAnimationFrame === "function" ? cancelAnimationFrame(id) : window.clearTimeout(id)),
    };
    // Jeder Start (auch „Neu starten“) legt einen neuen Zustand an: Spuren dazu frisch.
    const engine: SimEngine = {
      ...EIGEN,
      create: (inp) => {
        const s = EIGEN.create(inp);
        gfx.sim = s as unknown as EigenState; gfx.sp = createEigenSpuren(gfx.sim); gfx.snap = null; latest = null;
        clocks.current = { fig: -Infinity, desc: -Infinity };
        return s;
      },
    };
    const zeigeStart = () => {                                         // instabil schon am Start: das Startbild (falls endlich) stehen lassen
      const s = gfx.sim;
      if (!s || gfx.snap || !eigenEndlich(s.startBild)) return;
      gfx.snap = s.startBild; latest = s.startBild;
      if (!paintAll(gfx)) fail();
    };
    loop = createSimLoop({
      input: eff, scheduler, engine,
      isHidden: () => document.hidden || !inView,
      onFrame: (raw) => {
        if (dead) return;
        try {
          const snap = raw as unknown as EigenSnapshot;
          latest = snap; gfx.snap = snap;
          if (gfx.sp) addEigenSpuren(gfx.sp, snap);
          if (!paintAll(gfx)) { fail(); return; }
          const now = performance.now(), c = clocks.current;
          if (now - c.fig >= FIG_MS) { c.fig = now; setFig(figOf(snap)); }
          if (now - c.desc >= DESC_MS) { c.desc = now; setDesc(descOf(figOf(snap))); }
        } catch { fail(); }
      },
      onState: (st: LoopState) => {
        if (dead) return;
        try {
          if (st.status === "instabil") zeigeStart();
          setStatus({ status: st.status, wort: st.wort, grund: st.status === "instabil" ? gfx.sim?.grund ?? null : null });
          if (!running(st.status)) flush();                           // Stopp, Pause, instabil: die letzten Zahlen zeigen
        } catch { fail(); }
      },
    });
    if (dead) { loop.dispose(); return; }
    const meine = loop;
    loopRef.current = meine;
    meine.setTempoFaktor?.(tempoRef.current);                          // Neustart durch einen Regler behält das Tempo
    setCanTempo(typeof meine.setTempoFaktor === "function");
    const st = meine.getState();
    if (st.status === "instabil") zeigeStart();
    const s = meine.getSim() as unknown as EigenState;                   // der Zustand, den `engine.create` angelegt hat
    setStatus({ status: st.status, wort: st.wort, grund: st.status === "instabil" ? s.grund ?? null : null });
    flush();
    return () => { dead = true; meine.dispose(); io?.disconnect(); if (loopRef.current === meine) loopRef.current = null; };
  }, [b, eff, sim0, plots, still, broken, ungueltig, gfx]);

  useEffect(() => { if (forced) pauseBtn.current?.focus(); }, [forced]);

  const sync = (l: SimLoop) => { const st = l.getState(); setStatus((s) => ({ ...s, status: st.status, wort: st.wort })); };
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
    l.restart();
    const st = l.getState();
    setStatus({ status: st.status, wort: st.wort, grund: st.status === "instabil" ? gfx.sim?.grund ?? null : null });
  };
  const setzeTempo = (f: TempoFaktor) => {
    const l = loopRef.current;
    if (!l || typeof l.setTempoFaktor !== "function") return;
    l.setTempoFaktor(f);
    setTempoFor({ for: b, f: l.getTempoFaktor?.() ?? f });
  };

  const uebernimm = (werte: Record<string, number>) => {
    let next = effRef.current;
    for (const [name, wert] of Object.entries(werte)) next = mitParameter(next, name, wert);
    effRef.current = next;
    setEdit({ for: b, input: next });
  };
  const takt = () => {
    const t = thr.current;
    t.timer = null;
    const p = t.pending;
    if (!p) { setShown(null); return; }
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
  const loslassen = () => { if (thr.current.timer === null) setShown(null); };
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
    if (t.timer !== null) window.clearTimeout(t.timer);
    t.timer = null; t.pending = null;
    effRef.current = b;
    setShown(null);
    setEdit(null);
  };

  const kopf = (
    <div className="s-head">
      <p className="e-badge">{BADGE}</p>
      {!ungueltig && sim0.config.name && <span className="label e-name">{sim0.config.name}</span>}
    </div>
  );
  const hinweis = <p className="v-note e-hinweis" role="note">{`${EIGEN_HINWEIS}.`}</p>;
  if (ungueltig || broken) {
    return (
      <section className="v-sim v-eigen" aria-label="Eigene Simulation">
        {kopf}
        {hinweis}
        <p className="v-note" role="note">Diese eigene Simulation kann nicht gezeigt werden. Die gelieferten Angaben lassen sich nicht rechnen.</p>
      </section>
    );
  }

  const cfg = sim0.config;
  const canPause = running(status.status) || status.status === "pausiert";
  const playing = !still && !noCtx;
  const wertVon = (name: string) => cfg.parameter.find((p) => p.name === name)?.wert ?? null;
  const origWerte = paramListe(b);
  const reglerSatz = (werte: (n: string) => number | null) =>
    regler.map((g) => { const v = werte(g.feld); return `${g.name} ${v === null ? "unbekannt" : reglerText(g, v)}`; }).join(", ");
  const reihe = namen.reihe;
  const phasen = namen.phasen;
  const feder = sim0.form === "teilchen" ? federSatz(eff) : "";
  const zeigeAend = aendSichtbar && (aend.parameter.length > 0 || aend.sonst);
  return (
    <section ref={wrap} className="v-sim v-eigen" aria-label="Eigene Simulation">
      {kopf}
      {hinweis}
      {zeigeAend && (
        <p className="e-aenderung" role="status">
          {aend.parameter.length ? `Geändert: ${aend.parameter.join("; ")}.` : ""}
          {aend.sonst ? `${aend.parameter.length ? " " : ""}Weitere Angaben wurden geändert.` : ""}
        </p>
      )}
      {cfg.angepasst.length > 0 && <p className="v-note">Einige Angaben fehlten oder lagen außerhalb der Grenzen und wurden angepasst.</p>}
      {noCtx && <p className="v-note" role="note">Das Bild kann hier nicht gezeichnet werden. Die Werte und die Beschreibung stehen darunter.</p>}
      <div ref={plotWrap} className="e-plots" hidden={noCtx}>
        {plots.map((art, i) => (
          <div key={`${art}-${i}`} className="s-frame">
            <canvas ref={i === 0 ? c0 : c1} className="s-canvas" style={{ height: heights[i] }} role="img"
              aria-label={`${labels[i] ?? ""}. ${still ? "Standbild. " : ""}${desc}`} />
          </div>
        ))}
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
      {status.grund && (status.status === "instabil" || !playing) && <p className="v-note e-warn" role="note">{GRUND_SATZ[status.grund]}</p>}
      {fig?.hinweis && <p className="v-note e-warn" role="note">{`Rechenfehler wächst. ${fig.hinweis}`}</p>}
      {playing && canTempo && (
        <div className="m-row s-tempo" role="group" aria-label="Tempo">
          {TEMPO_FAKTOREN.map((f) => (
            <button key={f} type="button" aria-pressed={tempo === f} onClick={() => setzeTempo(f)}>{TEMPO_WORT[f]}</button>
          ))}
          <p className="s-tempo-wort" aria-live="polite">Tempo: {TEMPO_WORT[tempo]}</p>
          {status.status === "zeitlupe" && <p className="v-note">Tempo wirkt erst, wenn die Rechengrenze nicht erreicht ist.</p>}
        </div>
      )}
      {still && !noCtx && (
        <p className="v-note">{`Standbild: der Verlauf über die ersten ${formatZahl(Math.round(stillDauer * 10) / 10)} s, vorausgerechnet; die Körper in der Lage am Ende.`}</p>
      )}
      {plots.includes("zeitreihe") && reihe.length > 0 && (
        <ul className="s-legend" aria-label="Zeitreihe">
          {reihe.map((name, j) => <li key={j}><span className="s-name">{name}</span>: {REIHE_WORT[j] ?? "Weiß"}</li>)}
          <li>{still ? "Waagerecht die Zeit ab 0 s." : "Waagerecht die Zeit, die jüngsten Werte rechts."}</li>
        </ul>
      )}
      {plots.includes("phasenraum") && phasen && (
        <p className="v-note">{`Phasenraum: waagerecht ${phasen[0]}, senkrecht ${phasen[1]}. Die Linie ist der bisherige Weg, der Punkt (Bernstein) der Zustand jetzt.`}</p>
      )}
      {sim0.form === "teilchen" && (
        <p className="v-note">
          {`Feste Teilchen: Quadrat in Bernstein. Bewegliche Teilchen: Punkte in Cyan.${feder ? " Federn: graue Linien." : ""}`}
          {plots.includes("pfeile") ? " Pfeile zeigen Richtung und Geschwindigkeit; der längste Pfeil gehört zum schnellsten Teilchen." : ""}
        </p>
      )}
      {regler.length > 0 && (
        <div className="m-row s-regler" role="group" aria-label="Parameter">
          {regler.map((r, i) => {
            const id = `${uid}-param-${i}`;
            const gezogen = shown && shown.for === b ? shown.werte[r.feld] : undefined;
            const w = gezogen ?? wertVon(r.feld) ?? r.min;
            const txt = reglerText(r, w);
            return (
              <div key={r.feld} className="m-slider s-slider">
                <label htmlFor={id}>{r.einheit ? `${r.name} (${r.einheit})` : r.name}</label>
                <input id={id} type="range" min={0} max={stufen(r)} step={1} value={posAusWert(r, w)} aria-valuetext={txt}
                  onChange={(e) => ziehe(r, wertAusPos(r, Number(e.currentTarget.value)))} onKeyDown={taste(r, w)} onKeyUp={loslassen}
                  onPointerUp={loslassen} onMouseUp={loslassen} onTouchEnd={loslassen} onBlur={loslassen} />
                <span className="num" aria-hidden="true">{txt}</span>
              </div>
            );
          })}
          <button type="button" aria-disabled={edited ? undefined : "true"} onClick={zurueck}>Zurück auf die gelieferten Werte</button>
          <p className="v-note">Die Regler ändern nur diese Anzeige.</p>
        </div>
      )}
      {fig && (
        <div className="v-table-wrap">
          <table className="v-table s-figures">
            <caption className="label">{still ? "Werte am Ende des Standbilds" : noCtx ? "Werte am Start" : "Werte"}</caption>
            <tbody>
              {(playing || still) && <tr><th scope="row">Zeit in der Simulation</th><td className="num">{formatWert(fig.zeit)} s</td></tr>}
              {fig.werte.map((w, i) => <tr key={`w${i}`}><th scope="row">{w.name}</th><td className="num">{mitEinheit(w.wert, w.einheit)}</td></tr>)}
              {fig.kennwerte.map((k) => <tr key={k.id}><th scope="row">{k.name}</th><td className="num">{k.text}</td></tr>)}
            </tbody>
          </table>
        </div>
      )}
      {(gl.length > 0 || feder) && (
        <div className="e-gl">
          <span className="label">Gleichungen</span>
          <ul className="e-gl-list">
            {gl.map((g) => (
              <li key={g.key}>{g.label && <span className="e-gl-name">{g.label} </span>}<Tex tex={g.tex} /></li>
            ))}
            {feder && <li>{feder}</li>}
          </ul>
        </div>
      )}
      <div className="s-text">
        <span className="label">Beschreibung</span>
        <p>{sim0.text}</p>
        {regler.length > 0 && (
          <p>
            {`Parameter: ${reglerSatz(wertVon)}.`}
            {edited ? ` Mit den Reglern geändert; geliefert: ${reglerSatz((n) => origWerte.find((p) => p.name === n)?.wert ?? null)}.` : ""}
          </p>
        )}
        {cfg.beschreibung && <p>{cfg.beschreibung}</p>}
      </div>
    </section>
  );
}

