import { useEffect, useRef } from "react";
import { STATE_VIEW, type AvatarState } from "../lib/avatarState";

const MARKS = 24;
const reduced = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

interface Colors { core: string; ring: string }
function colors(state: AvatarState): Colors {
  const css = getComputedStyle(document.documentElement);
  const v = (n: string) => css.getPropertyValue(n).trim() || "#888";
  switch (state) {
    case "listening": return { core: v("--cyan"), ring: v("--cyan") };
    case "alarm": return { core: v("--alarm"), ring: v("--alarm") };
    case "halted": return { core: v("--text-faint"), ring: v("--alarm") };
    case "offline": return { core: v("--text-faint"), ring: v("--text-faint") };
    default: return { core: v("--amber"), ring: v("--amber") };
  }
}

/** Zeichnet den Avatar. Zeit `t` in Sekunden, `level` 0..1 (Pegel/Wellenform, geglättet vom Aufrufer). */
export function draw(ctx: CanvasRenderingContext2D, size: number, state: AvatarState, t: number, level: number): void {
  const c = colors(state);
  const cx = size / 2, cy = size / 2, R = size * 0.42;
  ctx.clearRect(0, 0, size, size);
  const idle = state === "idle";
  const breathe = idle ? 1 + 0.015 * (1 + Math.sin((t / 4) * 2 * Math.PI)) : 1;
  const dim = idle || state === "offline" ? 0.55 : 1;

  for (let i = 0; i < MARKS; i++) {                     // Ring aus Zählmarken
    const a = (i / MARKS) * Math.PI * 2 - Math.PI / 2;
    let r = R, alpha = idle ? 0.2 : 0.9, rad = Math.max(3, size * 0.017);
    if (state === "listening") rad += level * size * 0.03 * (0.6 + 0.4 * Math.sin(t * 6 + i));
    if (state === "speaking") r += Math.sin(t * 8 + i * 0.9) * level * size * 0.04;
    if (state === "thinking") alpha = 0.25 + 0.75 * Math.max(0, Math.cos(((t / 2) * Math.PI * 2) - a));
    if (state === "offline" && i % 2) alpha = 0;        // gestrichelt
    if (state === "halted" && i > MARKS * 0.75) alpha = 0; // offen
    ctx.globalAlpha = alpha;
    ctx.fillStyle = c.ring;
    ctx.beginPath();
    ctx.arc(cx + Math.cos(a) * r, cy + Math.sin(a) * r, rad, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.globalAlpha = dim;                                // Kern: Keil-K, vereinfacht
  ctx.strokeStyle = c.core;
  ctx.lineWidth = Math.max(4, size * 0.04);
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  const k = size * 0.16 * breathe;
  ctx.beginPath();
  ctx.moveTo(cx - k * 0.6, cy - k); ctx.lineTo(cx - k * 0.6, cy + k);
  ctx.moveTo(cx + k * 0.8, cy - k); ctx.lineTo(cx - k * 0.6, cy + k * 0.05); ctx.lineTo(cx + k * 0.8, cy + k);
  ctx.stroke();
  if (state === "halted" || state === "offline") {      // durchgestrichen: Form, nicht nur Farbe
    ctx.globalAlpha = 1;
    ctx.beginPath();
    ctx.moveTo(cx - R * 0.5, cy + R * 0.5); ctx.lineTo(cx + R * 0.5, cy - R * 0.5);
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

    if (reduced()) {                                    // statisches Bild je Zustand, keine Schleife
      draw(ctx, size, state, 0, 0);
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
      draw(ctx, size, state, now / 1000, smooth);
    };
    if (still) draw(ctx, size, state, 0, 0);
    else raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [state, size]);

  return <canvas ref={ref} role="img" aria-label={label} style={{ width: size, height: size }} />;
}
