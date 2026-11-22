import { useEffect, useMemo, useRef, useState } from "react";
import {
  addToTrail, createSim, createTrail, FARBEN, formatWert, normalizeSim, standbild,
  type Ausschnitt, type Farbe, type Kennwert, type Pt, type SimModell, type SimSnapshot, type SimState, type Standbild, type Trail, type Verteilung,
} from "../../lib/physics";
import { PALETTE_VAR } from "../../lib/scene";
import { createSimLoop, type FrameScheduler, type LoopState, type LoopStatus, type SimLoop } from "../../lib/simLoop";
import type { SimBlock } from "../../lib/stage";
import { useBoxSize } from "../../lib/useBoxSize";

// Baustein `simulation` (Plan docs/ui-p5-plan.md, Abschnitte 3 bis 6, P5a). Gerechnet wird in lib/physics.ts, getaktet in
// lib/simLoop.ts (höchstens 30 Bilder je Sekunde, Stopp nach der Laufzeit, verdeckt oder außer Sicht kein Schritt). Hier wird nur
// gezeichnet (Canvas 2D, gleicher Maßstab auf beiden Achsen, y nach oben) und bedient. Texte aus den Daten (Namen, Beschreibung)
// stehen nur im DOM, nie im Bild. Der Satz „Simulation, keine Messung“ und die Hinweise kommen von der Oberfläche, nicht von Claude.
// Pause, Weiter und Neu starten ändern nur die Anzeige im Fenster: nichts wird gesendet, gespeichert oder abgespielt.
// Bei „weniger Bewegung“ gibt es keine Schleife, sondern ein Standbild mit Textfassung und den Knopf „Trotzdem abspielen“.

const FIG_MS = 500;              // Kennwerte höchstens zweimal je Sekunde neu (nicht jedes Bild, weniger React-Arbeit)
const DIST_MS = 1000;            // Verteilung beim Gas einmal je Sekunde neu
const DPR_MAX = 1.5;
const DEFAULT_W = 640, H_MIN = 180, H_MAX = 420, CURVE_H = 120, DIST_H = 72, PAD = 10;
const REDUCE = "(prefers-reduced-motion: reduce)";
const MODELL_LABEL: Record<SimModell, string> = { pendel: "Pendel", feder: "Federpendel", wurf: "Wurf", umlauf: "Umlaufbahnen", gas: "Gas im Kasten" };
const FARBE_WORT: Record<Farbe, string> = {
  arc: "Cyan", amber: "Bernstein", ok: "Grün", warn: "Warnfarbe (Bernstein)", alarm: "Rot", text: "Weiß", gedaempft: "Grau",
};
const STILL_WORT = "Standbild, weniger Bewegung ist eingestellt";

interface Pal { farbe: Record<Farbe, string>; line: string; strong: string; muted: string; amber: string }
interface Gfx {
  ctx: CanvasRenderingContext2D | null; w: number; h: number; dpr: number; pal: Pal | null;
  snap: SimSnapshot | null; trail: Trail | null; bild: Standbild | null;
}
interface Info { text: string; angepasst: number; ausschnitt: Ausschnitt; bild: Standbild | null; koerper: { name: string; farbe: Farbe }[] }
interface Figures { zeit: number; einheit: string; kennwerte: Kennwert[] }

const prefersReduced = (): boolean => {
  try { return typeof matchMedia === "function" && !!matchMedia(REDUCE).matches; } catch { return false; }
};
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const dprNow = () => Math.min(typeof window !== "undefined" && window.devicePixelRatio > 0 ? window.devicePixelRatio : 1, DPR_MAX);
const figOf = (s: SimSnapshot): Figures => ({ zeit: s.zeit, einheit: s.einheit, kennwerte: s.kennwerte });
const running = (s: LoopStatus | "") => s === "laeuft" || s === "zeitlupe";

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

function line(ctx: CanvasRenderingContext2D, pts: Pt[], m: Map2, close = false): void {
  if (pts.length < 2) return;
  ctx.beginPath();
  ctx.moveTo(m.X(pts[0][0]), m.Y(pts[0][1]));
  for (let i = 1; i < pts.length; i++) ctx.lineTo(m.X(pts[i][0]), m.Y(pts[i][1]));
  if (close) ctx.closePath();
  ctx.stroke();
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
    const m = mapper(snap.ausschnitt, g.w, g.h), a = snap.ausschnitt;
    const body = snap.koerper[0];
    ctx.strokeStyle = pal.strong; ctx.lineWidth = 2;
    if (snap.modell === "wurf") line(ctx, [[a.minX, 0], [a.maxX, 0]], m);                        // Boden
    if (snap.modell === "gas") { ctx.lineWidth = 1.5; ctx.strokeRect(m.X(a.minX), m.Y(a.maxY), m.aw * m.s, m.ah * m.s); }   // Kasten
    if (snap.modell === "pendel" && snap.anker) {                                                // Decke
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
    if (g.bild?.modell === "umlauf") {                                                           // alle Bahnen
      ctx.lineWidth = 1.5; ctx.globalAlpha = 0.6;
      for (const b of g.bild.bahnen) { ctx.strokeStyle = pal.farbe[b.farbe] ?? pal.farbe.arc; line(ctx, b.punkte, m, true); }
      ctx.globalAlpha = 1;
    }
    const t = g.trail;
    if (t) {                                                                                     // Spur (Ringpuffer, älteste zuerst)
      ctx.lineWidth = 1.5; ctx.globalAlpha = 0.45;
      for (let i = 0; i < t.xs.length; i++) {
        const n = t.laenge[i];
        if (n < 2) continue;
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
    if (snap.anker && body && snap.modell === "pendel") {                                        // Stange und Aufhängung
      ctx.strokeStyle = pal.strong; ctx.lineWidth = 2;
      line(ctx, [snap.anker, [body.x, body.y]], m);
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
      const r = snap.modell === "umlauf" ? 6 : 9;
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
  const cfg = useMemo(() => normalizeSim(b), [b]);                   // nur Begrenzen, keine Vorausrechnung
  const [reduced, setReduced] = useState(prefersReduced);
  const [forcedFor, setForcedFor] = useState<SimBlock | null>(null);  // „Trotzdem abspielen“ gilt für genau diese Daten
  const forced = forcedFor === b;
  const still = reduced && !forced;
  const [info, setInfo] = useState<Info | null>(null);
  const [status, setStatus] = useState<{ status: LoopStatus | ""; wort: string }>({ status: "", wort: "" });
  const [fig, setFig] = useState<Figures | null>(null);
  const [dist, setDist] = useState<Verteilung | null>(null);
  const [noCtx, setNoCtx] = useState(false);
  const [brokenFor, setBrokenFor] = useState<SimBlock | null>(null);  // Zeichenfehler: angehalten, gilt für genau diese Daten
  const broken = brokenFor === b;

  const wrap = useRef<HTMLElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const curve = useRef<HTMLCanvasElement>(null);
  const distCanvas = useRef<HTMLCanvasElement>(null);
  const pauseBtn = useRef<HTMLButtonElement>(null);
  const loopRef = useRef<SimLoop | null>(null);
  const clocks = useRef({ fig: -Infinity, dist: -Infinity });
  const gfx = useRef<Gfx>({ ctx: null, w: DEFAULT_W, h: H_MIN, dpr: 1, pal: null, snap: null, trail: null, bild: null }).current;

  const box = useBoxSize(frame);
  const cssW = Math.max(120, box?.width ?? DEFAULT_W);
  const a = info?.ausschnitt;
  const ratio = a && a.maxX > a.minX && a.maxY > a.minY ? (a.maxY - a.minY) / (a.maxX - a.minX) : 0.5;
  const cssH = Math.round(clamp(cssW * ratio, H_MIN, H_MAX));

  useEffect(() => {                                                    // „weniger Bewegung“ kann sich ändern; Listener räumt auf
    let mq: MediaQueryList | null = null;
    try { mq = typeof matchMedia === "function" ? matchMedia(REDUCE) : null; } catch { mq = null; }
    if (!mq || typeof mq.addEventListener !== "function") return;
    const on = () => setReduced(!!mq?.matches);
    mq.addEventListener("change", on);
    return () => mq?.removeEventListener("change", on);
  }, []);

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
      const sim = createSim(b);
      const bild = still ? standbild(sim) : null;
      gfx.bild = bild; gfx.snap = sim.startBild;
      setInfo(infoOf(sim, bild));
      setFig(figOf(sim.startBild));
      setDist(bild?.modell === "gas" ? bild.verteilung : sim.startBild.verteilung);
      setStatus({ status: "", wort: still ? STILL_WORT : "" });
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
    const trails = cfg.spur && cfg.modell !== "gas";                  // Gas: keine Spur (der Helfer kennt nur die ersten 8 Körper)
    loop = createSimLoop({
      input: b, scheduler,
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
    const st = own.getState();
    setStatus({ status: st.status, wort: st.wort });
    setInfo(infoOf(own.getSim(), null));
    return () => { dead = true; own.dispose(); io?.disconnect(); if (loopRef.current === own) loopRef.current = null; };
  }, [b, cfg, still, broken, gfx]);

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
  return (
    <section ref={wrap} className="v-sim" aria-label={`Simulation: ${label}`}>
      <div className="s-head">
        <p className="s-flag">Simulation, keine Messung</p>
        <span className="label">{label}</span>
      </div>
      {cfg.modell === "umlauf" && <p className="v-note">Die Körper ziehen sich gegenseitig nicht an.</p>}
      {info && info.angepasst > 0 && <p className="v-note">Einige Angaben fehlten oder lagen außerhalb der Grenzen und wurden angepasst.</p>}
      {noCtx && <p className="v-note" role="note">Das Bild kann hier nicht gezeichnet werden. Die Beschreibung steht darunter.</p>}
      <div ref={frame} className="s-frame" hidden={noCtx}>
        <canvas ref={canvas} className="s-canvas" style={{ height: cssH }} role="img"
          aria-label={still ? "Standbild der Simulation; die Beschreibung steht darunter als Text" : "Bild der Simulation; die Beschreibung steht darunter als Text"} />
      </div>
      <div className="m-row s-controls" role="group" aria-label="Simulation steuern">
        {still && !noCtx && <button type="button" onClick={() => setForcedFor(b)}>Trotzdem abspielen</button>}
        {!still && !noCtx && (
          <>
            <button ref={pauseBtn} type="button" aria-disabled={canPause ? undefined : "true"} onClick={toggle}>
              {status.status === "pausiert" ? "Weiter" : "Pause"}
            </button>
            <button type="button" onClick={restart}>Neu starten</button>
          </>
        )}
        <p className="s-state" aria-live="polite">{status.wort}</p>
      </div>
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
      {bild?.modell === "umlauf" && <p className="v-note">Alle Bahnen als Linien, die Körper in ihrer Startlage.</p>}
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
              {!still && !noCtx && <tr><th scope="row">Zeit in der Simulation</th><td className="num">{formatWert(fig.zeit)} {fig.einheit}</td></tr>}
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
        {cfg.beschreibung && <p>{cfg.beschreibung}</p>}
      </div>
    </section>
  );
}
