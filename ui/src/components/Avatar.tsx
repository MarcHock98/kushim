import { useEffect, useRef } from "react";
import { STATE_VIEW, type AvatarState } from "../lib/avatarState";

// 2D-Orb im Stil „Jarvin Cockpit“ (Ersatz, wenn es kein WebGL gibt; sonst zeichnet Core3D): Haarlinien-Ring, Skalenring aus Strichen, 72 Strahlen um einen ruhigen Kern (ohne K).
// Die Strahlen tragen die Information (Pegel vom Backend), der Kern bleibt ruhig. Entwurfsmaß 340 px, skaliert mit `size`.
const BARS = 72;
const BASE = 340;
const reduced = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

// Feste Form je Strahl (Länge, Tempo, Versatz), einmal berechnet: pro Frame wird nichts angelegt.
const SHAPE = Array.from({ length: BARS }, (_, i) => ({
  len: 12 + 44 * (0.35 + 0.65 * Math.abs(Math.sin(i * 2.3) * Math.cos(i * 0.7))),
  dur: 0.6 + ((i * 7) % 11) / 14,
  delay: ((i * 13) % 17) / 10,
}));

interface Palette { bar: string; core: string; ring: string; ticks: string; line: string; fill: string; glow: string }
function palette(state: AvatarState): Palette {
  const css = getComputedStyle(document.documentElement);
  const v = (n: string) => css.getPropertyValue(n).trim() || "#888";
  const base = { ticks: v("--line-strong"), line: v("--line"), fill: v("--bg-2"), glow: "" };
  switch (state) {
    case "listening": return { ...base, bar: v("--amber"), core: v("--amber"), ring: v("--amber") };
    case "asking": return { ...base, bar: v("--amber"), core: v("--amber"), ring: v("--amber") };
    case "alarm": return { ...base, bar: v("--alarm"), core: v("--alarm"), ring: v("--alarm") };
    case "halted": return { ...base, bar: v("--text-faint"), core: v("--text-faint"), ring: v("--alarm") };
    case "offline": return { ...base, bar: v("--text-faint"), core: v("--text-faint"), ring: v("--text-faint") };
    case "idle": return { ...base, bar: v("--arc"), core: v("--arc"), ring: v("--line-strong") };
    default: return { ...base, bar: v("--arc"), core: v("--arc"), ring: v("--arc"), glow: v("--arc") };   // thinking, speaking
  }
}

const ARCS = [[100, 180, 2.4, 1], [120, 220, 3.6, -1], [140, 150, 5.2, 1]] as const;   // Radius, Bogenlänge, Umlauf (s), Richtung

const wave = (t: number, i: number) => 0.5 + 0.5 * Math.sin(((t + SHAPE[i].delay) / SHAPE[i].dur) * Math.PI * 2);

/** Zeichnet den Avatar. Zeit `t` in Sekunden, `level` 0..1 (Pegel, geglättet vom Aufrufer). */
export function draw(ctx: CanvasRenderingContext2D, size: number, state: AvatarState, t: number, level: number, c: Palette = palette(state)): void {
  const k = size / BASE, cx = size / 2, cy = size / 2;
  ctx.clearRect(0, 0, size, size);
  ctx.globalAlpha = 1;
  ctx.shadowBlur = 0;
  ctx.setLineDash([]);

  ctx.strokeStyle = c.line;                             // äußere Haarlinie
  ctx.lineWidth = 1;
  ctx.beginPath(); ctx.arc(cx, cy, 166 * k, 0, Math.PI * 2); ctx.stroke();

  ctx.strokeStyle = state === "halted" ? c.ring : c.ticks;   // Skalenring aus Strichen
  ctx.globalAlpha = state === "offline" ? 0.5 : 1;
  ctx.lineWidth = 6 * k;
  ctx.setLineDash([2 * k, 8.05 * k]);
  ctx.beginPath(); ctx.arc(cx, cy, 160 * k, 0, Math.PI * 2); ctx.stroke();
  ctx.setLineDash([]);

  const thinking = state === "thinking";
  ctx.strokeStyle = c.bar;                              // 72 Strahlen
  ctx.lineWidth = Math.max(2, 3 * k);
  ctx.lineCap = "round";
  for (let i = 0; i < BARS; i++) {
    let s: number, alpha = 1;
    switch (state) {
      case "idle": s = 0.35 + 0.25 * (0.5 + 0.5 * Math.sin((t / 4) * Math.PI * 2)); alpha = 0.55; break;   // atmet, 4 s
      case "listening": case "speaking": s = 0.2 + 0.8 * level * (0.3 + 0.7 * wave(t, i)); break;          // folgt dem Pegel
      case "thinking": s = 0.18; alpha = 0.35; break;
      case "offline": s = 0.3; alpha = i % 2 ? 0 : 0.6; break;                                              // gestrichelt
      case "halted": s = 0.3; alpha = i >= BARS * 0.75 ? 0 : 0.6; break;                                    // offen
      default: s = 0.5;                                                                                     // asking, alarm: ruhig
    }
    if (alpha === 0) continue;
    const a = (i / BARS) * Math.PI * 2 - Math.PI / 2;
    const r0 = 84 * k, r1 = r0 + SHAPE[i].len * k * s;
    const cos = Math.cos(a), sin = Math.sin(a);
    ctx.globalAlpha = alpha;
    ctx.beginPath(); ctx.moveTo(cx + cos * r0, cy + sin * r0); ctx.lineTo(cx + cos * r1, cy + sin * r1); ctx.stroke();
  }
  ctx.globalAlpha = 1;

  if (thinking) {                                       // drei Bögen kreisen (2,4 s, 3,6 s rückwärts, 5,2 s)
    ctx.strokeStyle = c.ring;
    ctx.lineWidth = Math.max(1.5, 2 * k);
    for (const [r, len, period, dir] of ARCS) {
      const start = dir * (t / period) * Math.PI * 2;
      ctx.beginPath(); ctx.arc(cx, cy, r * k, start, start + len / r); ctx.stroke();
    }
  }

  ctx.fillStyle = c.fill;                               // Kern
  ctx.strokeStyle = c.ring;
  ctx.lineWidth = 1;
  if (c.glow) { ctx.shadowColor = c.glow; ctx.shadowBlur = 28 * k; }
  ctx.beginPath(); ctx.arc(cx, cy, 64 * k, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
  ctx.shadowBlur = 0;

  ctx.globalAlpha = state === "idle" || state === "offline" ? 0.5 : 0.9;   // ruhiger Lichtpunkt statt K (K nur im Logo)
  ctx.fillStyle = c.core;
  ctx.beginPath(); ctx.arc(cx, cy, 10 * k, 0, Math.PI * 2); ctx.fill();
  if (state === "halted" || state === "offline") {      // durchgestrichen: Form, nicht nur Farbe
    ctx.globalAlpha = 1;
    ctx.strokeStyle = state === "halted" ? c.ring : c.core;
    ctx.lineWidth = Math.max(2.5, 5 * k);
    ctx.beginPath();
    ctx.moveTo(cx - 45 * k, cy + 45 * k); ctx.lineTo(cx + 45 * k, cy - 45 * k);
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

export function Avatar({ state, size = 160, level = 0 }: { state: AvatarState; size?: number; level?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const levelRef = useRef(level);
  levelRef.current = level;
  const label = STATE_VIEW[state].label;

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = size * dpr; canvas.height = size * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const pal = palette(state);                         // Farben einmal je Zustand lesen, nicht pro Frame

    if (reduced()) {                                    // statisches Bild je Zustand, keine Schleife
      draw(ctx, size, state, 0, state === "listening" || state === "speaking" ? 0.7 : 0, pal);
      return;
    }
    let raf = 0, last = 0, smooth = 0;
    const still = state === "halted" || state === "offline" || state === "asking" || state === "alarm";
    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      if (document.hidden) return;                      // verdeckt: nichts zeichnen
      const gap = state === "idle" ? 33 : 16;           // im Ruhezustand 30 fps
      if (now - last < gap) return;
      last = now;
      const target = levelRef.current;
      smooth += (target - smooth) * (target > smooth ? 0.5 : 0.1);   // schnell hoch, langsam runter
      draw(ctx, size, state, now / 1000, smooth, pal);
    };
    if (still) draw(ctx, size, state, 0, 0, pal);
    else raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [state, size]);

  return <canvas ref={ref} className="orb" role="img" aria-label={label} style={{ width: size, height: size }} />;
}
