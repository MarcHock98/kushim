import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type RefObject } from "react";
import { orbitDrag, orbitEye, orbitHome, orbitKey, orbitStep, orbitWheel, type OrbitAction, type V3 } from "../../lib/orbitCamera";
import { PALETTE_VAR } from "../../lib/scene";
import { hasWebGL } from "../Core3D";

// Gemeinsamer three.js-Rahmen der Teilchen-Betrachter (Molecule3D, Orbital3D; Plan docs/ui-p5-plan.md, Abschnitt 7). Wie P4a:
// three.js wird erst bei Bedarf geladen (lokal gebündelt), gezeichnet wird nur bei einer Änderung (Drehen, Zoomen, Größe), nie im
// Dauertakt, und nichts bei verdecktem Fenster. Beim Abbauen und bei neuen Daten wird alles freigegeben: Geometrien, Materialien,
// Renderer und Listener. Ohne Bauplan (`build` null, zum Beispiel bei ungültigen Daten) wird kein WebGL-Kontext angelegt, auch kein
// Probe-Kontext. Texte aus den Daten kommen nie in das Bild; Beschriftungen stehen als DOM-Text darüber (`onPaint`).

export type Three = typeof import("three");
type Scene = InstanceType<Three["Scene"]>;
/** Projiziert einen Punkt der Szene auf die Zeichenfläche (CSS-Pixel von links oben); null, wenn er hinter der Kamera liegt. */
export type Project = (p: V3) => { x: number; y: number } | null;
export interface Built {
  /** Durchmesser der Szene um `center`; die Kamera wird daran angepasst. */
  size: number;
  center?: V3;
  /** Alles, was die Szene angelegt hat (Geometrien, Materialien, Netze). */
  disposables: { dispose(): void }[];
  /** Nach jedem Bild: Beschriftungen im DOM nachführen. */
  onPaint?: (project: Project) => void;
}
/** Baut die Szene. Farben nur aus der Palette (CSS-Variablen), nie aus den Daten. */
export type Builder = (T: Three, scene: Scene, color: (farbe: string) => string) => Built;

/** three.js genau einmal laden, auch wenn mehrere Betrachter gleichzeitig aufgebaut werden; ein Fehlschlag darf es später neu versuchen. */
let three: Promise<Three> | null = null;
function loadThree(): Promise<Three> {
  three ??= import("three").catch((e: unknown) => { three = null; throw e; });
  return three;
}

/** Farbe einer Palettenfarbe aus den CSS-Variablen; ohne Stylesheet (Tests) ein neutraler Farbname. */
function paletteColor(css: CSSStyleDeclaration | null, farbe: string): string {
  const name = Object.prototype.hasOwnProperty.call(PALETTE_VAR, farbe) ? PALETTE_VAR[farbe] : "--arc";
  return css?.getPropertyValue(name).trim() || "gray";
}

export function useOrbitViewer(canvas: RefObject<HTMLCanvasElement | null>, build: Builder | null) {
  const active = build !== null;
  const supported = useMemo(() => active && hasWebGL(), [active]);   // nur prüfen, wenn es etwas zu zeigen gibt
  const [failed, setFailed] = useState(false);
  const [lostCtx, setLostCtx] = useState(false);                     // der Browser hat den Kontext beendet (nicht: WebGL fehlt)
  const gl = supported && !failed;
  const ctl = useRef<{ view(a: OrbitAction): void } | null>(null);

  useEffect(() => {
    const el = canvas.current;
    if (!el || !gl || !build) return;
    let dead = false, cleanup = () => {};
    void loadThree().then((T) => {
      if (dead) return;
      let renderer: InstanceType<Three["WebGLRenderer"]>;
      try {
        renderer = new T.WebGLRenderer({ canvas: el, antialias: true, alpha: true, powerPreference: "low-power" });
      } catch { setFailed(true); return; }
      let built: Built;
      const scene = new T.Scene();
      const disposables: { dispose(): void }[] = [];
      try {
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
        let css: CSSStyleDeclaration | null = null;
        try { css = getComputedStyle(document.documentElement); } catch { css = null; }
        scene.add(new T.AmbientLight(0xffffff, 0.9));
        const sun = new T.DirectionalLight(0xffffff, 1.4);
        sun.position.set(3, 5, 4);
        scene.add(sun);
        built = build(T, scene, (f) => paletteColor(css, f));
        disposables.push(...built.disposables);
      } catch {
        disposables.forEach((d) => d.dispose());
        renderer.dispose();
        renderer.forceContextLoss();
        setFailed(true);
        return;
      }
      const size = Number.isFinite(built.size) && built.size > 0 ? built.size : 1;
      const center: V3 = built.center ?? [0, 0, 0];
      const cam = new T.PerspectiveCamera(45, 1, size / 1000, size * 100);
      let v = orbitHome(size);
      let raf = 0, queued = false, pending = false, w = 1, h = 1;
      const tmp = new T.Vector3();
      const project: Project = (p) => {
        tmp.set(p[0], p[1], p[2]).project(cam);
        if (!Number.isFinite(tmp.x) || !Number.isFinite(tmp.y) || tmp.z > 1) return null;
        return { x: ((tmp.x + 1) / 2) * w, y: ((1 - tmp.y) / 2) * h };
      };

      const paint = () => {
        const eye = orbitEye(v, center, size);
        cam.position.set(eye[0], eye[1], eye[2]);
        cam.lookAt(center[0], center[1], center[2]);
        cam.updateMatrixWorld();
        renderer.render(scene, cam);
        built.onPaint?.(project);
      };
      const draw = () => {
        if (queued) return;
        queued = true;
        raf = requestAnimationFrame(() => {
          queued = false;
          if (document.hidden) { pending = true; return; }
          paint();
        });
      };
      const resize = () => {
        w = Math.max(1, el.clientWidth); h = Math.max(1, el.clientHeight);
        renderer.setSize(w, h, false);
        cam.aspect = w / h;
        cam.updateProjectionMatrix();
        draw();
      };
      const view = (a: OrbitAction) => { v = orbitStep(v, a, size); draw(); };

      let drag: { x: number; y: number } | null = null;
      const down = (e: PointerEvent) => { drag = { x: e.clientX, y: e.clientY }; el.setPointerCapture?.(e.pointerId); };
      const move = (e: PointerEvent) => {
        if (!drag) return;
        v = orbitDrag(v, e.clientX - drag.x, e.clientY - drag.y, size);
        drag = { x: e.clientX, y: e.clientY };
        draw();
      };
      const up = () => { drag = null; };
      const wheel = (e: WheelEvent) => { e.preventDefault(); view(orbitWheel(e.deltaY)); };
      const visible = () => { if (!document.hidden && pending) { pending = false; draw(); } };
      const lost = (e: Event) => { e.preventDefault(); setLostCtx(true); setFailed(true); };
      el.addEventListener("pointerdown", down); el.addEventListener("pointermove", move);
      el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up);
      el.addEventListener("wheel", wheel, { passive: false });
      el.addEventListener("webglcontextlost", lost);
      document.addEventListener("visibilitychange", visible);
      const ro = typeof ResizeObserver === "function" ? new ResizeObserver(resize) : null;
      ro?.observe(el);

      const own = { view };
      ctl.current = own;
      resize();
      cleanup = () => {
        cancelAnimationFrame(raf);
        ro?.disconnect();
        el.removeEventListener("pointerdown", down); el.removeEventListener("pointermove", move);
        el.removeEventListener("pointerup", up); el.removeEventListener("pointercancel", up);
        el.removeEventListener("wheel", wheel);
        el.removeEventListener("webglcontextlost", lost);
        document.removeEventListener("visibilitychange", visible);
        disposables.forEach((d) => d.dispose());
        scene.clear();
        renderer.dispose();
        renderer.forceContextLoss();
        if (ctl.current === own) ctl.current = null;
      };
    }).catch(() => { if (!dead) setFailed(true); });
    return () => { dead = true; cleanup(); };
  }, [canvas, build, gl]);

  const view = (a: OrbitAction) => ctl.current?.view(a);
  const onKeyDown = (e: KeyboardEvent) => {
    const a = orbitKey(e);                                               // mit Strg, Alt oder Meta: null, die Taste gehört dem Browser
    if (a) { e.preventDefault(); view(a); }
  };
  return { gl, lost: lostCtx, view, onKeyDown };
}
