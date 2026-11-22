import { useEffect, useRef, useState } from "react";
import { ORBIT_BUTTONS, ORBIT_HINT, orbitDrag, orbitEye, orbitHome, orbitKey, orbitStep, orbitWheel, type OrbitAction, type V3 } from "../../lib/orbitCamera";
import { allBounds, describeObject, describeSize, diffScenes, diffText, PALETTE_VAR, type Box3, type SceneBlock } from "../../lib/scene";
import { hasWebGL } from "../Core3D";

// 3D-Szene aus einfachen Körpern (Plan docs/ui-p4-plan.md, P4a). Gezeichnet mit three.js (lazy geladen, lokal gebündelt).
// Last: gerendert wird nur bei Änderung (Drehen, Regler), nie im Dauertakt; nichts bei verdecktem Fenster; beim Schließen
// wird alles freigegeben. Bedienbar mit Maus, Touch, Tasten UND Knöpfen. Die Objektliste ersetzt das Bild für Vorleser.
// Texte von Claude erscheinen nur als Text im DOM, nie im 3D-Bild.

type Axis = "x" | "y" | "z";
interface Ctl { update(mix: number, cut: boolean, axis: Axis, pos: number): void; view(action: OrbitAction): void }

const AXIS_LABEL: Record<Axis, string> = { x: "Breite (x)", y: "Höhe (y)", z: "Tiefe (z)" };
const IDX: Record<Axis, number> = { x: 0, y: 1, z: 2 };

export function Model3D({ b }: { b: SceneBlock }) {
  const n = b.szenen.length;
  const [mix, setMix] = useState(n - 1);
  const [cut, setCut] = useState(false);
  const [axis, setAxis] = useState<Axis>("y");
  const [pos, setPos] = useState(0.5);
  const [gl, setGl] = useState(() => hasWebGL());
  const canvas = useRef<HTMLCanvasElement>(null);
  const ctl = useRef<Ctl | null>(null);
  const state = useRef({ mix, cut, axis, pos });
  state.current = { mix, cut, axis, pos };

  useEffect(() => {
    const el = canvas.current;
    if (!el || !gl) return;
    let dead = false, cleanup = () => {};
    void import("three").then((T) => {
      if (dead) return;
      let renderer: InstanceType<typeof T.WebGLRenderer>;
      try {
        renderer = new T.WebGLRenderer({ canvas: el, antialias: true, alpha: true, powerPreference: "low-power" });
      } catch { setGl(false); return; }
      renderer.localClippingEnabled = true;
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
      const css = getComputedStyle(document.documentElement);
      const color = (name: string) => css.getPropertyValue(PALETTE_VAR[name] ?? "--arc").trim() || "#888";
      const rad = Math.PI / 180;
      const scene = new T.Scene();
      scene.add(new T.AmbientLight(0xffffff, 0.9));
      const sun = new T.DirectionalLight(0xffffff, 1.4);
      sun.position.set(3, 5, 4);
      scene.add(sun);
      const plane = new T.Plane(new T.Vector3(0, -1, 0), 1e9);          // schneidet nichts, bis der Schnitt eingeschaltet wird
      const hot = new Set(b.hervorheben);
      const disposables: { dispose(): void }[] = [];
      const groups = b.szenen.map((sz) => {
        const g = new T.Group();
        const mats: { m: { opacity: number; depthWrite: boolean }; hi: boolean }[] = [];
        for (const o of sz.objekte) {
          const hi = !!o.name && hot.has(o.name);
          const col = new T.Color(color(o.farbe));
          if (o.form === "linie") {
            const geo = new T.BufferGeometry().setFromPoints(o.punkte.map((p) => new T.Vector3(p[0], p[1], p[2])));
            const mat = new T.LineBasicMaterial({ color: col, transparent: true, clippingPlanes: [plane] });
            disposables.push(geo, mat);
            g.add(new T.Line(geo, mat));
            mats.push({ m: mat, hi: false });
            continue;
          }
          const m = o.masse;
          const geo = o.form === "box" ? new T.BoxGeometry(m[0], m[1], m[2])
            : o.form === "kugel" ? new T.SphereGeometry(m[0], 28, 18)
            : o.form === "zylinder" ? new T.CylinderGeometry(m[0], m[0], m[1], 32)
            : o.form === "kegel" ? new T.ConeGeometry(m[0], m[1], 32)
            : o.form === "torus" ? new T.TorusGeometry(m[0], m[1], 14, 40)
            : new T.PlaneGeometry(m[0], m[1]);
          const mat = new T.MeshStandardMaterial({ color: col, roughness: 0.6, metalness: 0.1, transparent: true, side: T.DoubleSide,
            clippingPlanes: [plane], emissive: hi ? new T.Color(color("amber")) : new T.Color(0x000000), emissiveIntensity: hi ? 0.55 : 0 });
          const mesh = new T.Mesh(geo, mat);
          mesh.position.set(o.position[0], o.position[1], o.position[2]);
          mesh.rotation.set(o.drehung[0] * rad, o.drehung[1] * rad, o.drehung[2] * rad);
          const edgeGeo = new T.EdgesGeometry(geo);
          const edgeMat = new T.LineBasicMaterial({ color: new T.Color(color(hi ? "amber" : "text")), transparent: true, clippingPlanes: [plane] });
          mesh.add(new T.LineSegments(edgeGeo, edgeMat));
          disposables.push(geo, mat, edgeGeo, edgeMat);
          g.add(mesh);
          mats.push({ m: mat, hi }, { m: edgeMat, hi });
        }
        scene.add(g);
        return { g, mats };
      });

      const box: Box3 = allBounds(b);
      const center = [0, 1, 2].map((i) => (box.min[i] + box.max[i]) / 2) as V3;
      const diag = Math.max(1e-6, Math.hypot(box.max[0] - box.min[0], box.max[1] - box.min[1], box.max[2] - box.min[2]));
      const cam = new T.PerspectiveCamera(45, 1, diag / 1000, diag * 100);
      let v = orbitHome(diag);
      let raf = 0, queued = false, pending = false;

      const paint = () => {
        const eye = orbitEye(v, center, diag);
        cam.position.set(eye[0], eye[1], eye[2]);
        cam.lookAt(center[0], center[1], center[2]);
        renderer.render(scene, cam);
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
        const w = Math.max(1, el.clientWidth), h = Math.max(1, el.clientHeight);
        renderer.setSize(w, h, false);
        cam.aspect = w / h;
        cam.updateProjectionMatrix();
        draw();
      };

      const api: Ctl = {
        update(mixV, cutOn, ax, p) {
          groups.forEach((grp, i) => {
            const op = Math.max(0, 1 - Math.abs(mixV - i));
            grp.g.visible = op > 0.01;
            for (const e of grp.mats) { e.m.opacity = op; e.m.depthWrite = op > 0.99; }
          });
          if (cutOn) {
            const k = IDX[ax];
            plane.normal.set(k === 0 ? -1 : 0, k === 1 ? -1 : 0, k === 2 ? -1 : 0);
            plane.constant = box.min[k] + (box.max[k] - box.min[k]) * p;
          } else { plane.normal.set(0, -1, 0); plane.constant = 1e9; }
          draw();
        },
        view(action) {
          v = orbitStep(v, action, diag);
          draw();
        },
      };

      let drag: { x: number; y: number } | null = null;
      const down = (e: PointerEvent) => { drag = { x: e.clientX, y: e.clientY }; el.setPointerCapture?.(e.pointerId); };
      const move = (e: PointerEvent) => {
        if (!drag) return;
        v = orbitDrag(v, e.clientX - drag.x, e.clientY - drag.y, diag);
        drag = { x: e.clientX, y: e.clientY };
        draw();
      };
      const up = () => { drag = null; };
      const wheel = (e: WheelEvent) => { e.preventDefault(); api.view(orbitWheel(e.deltaY)); };
      const visible = () => { if (!document.hidden && pending) { pending = false; draw(); } };
      el.addEventListener("pointerdown", down); el.addEventListener("pointermove", move);
      el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up);
      el.addEventListener("wheel", wheel, { passive: false });
      document.addEventListener("visibilitychange", visible);
      const ro = typeof ResizeObserver === "function" ? new ResizeObserver(resize) : null;
      ro?.observe(el);
      const lost = (e: Event) => { e.preventDefault(); setGl(false); };
      el.addEventListener("webglcontextlost", lost);

      ctl.current = api;
      resize();
      const s = state.current;
      api.update(s.mix, s.cut, s.axis, s.pos);
      cleanup = () => {
        cancelAnimationFrame(raf);
        ro?.disconnect();
        el.removeEventListener("pointerdown", down); el.removeEventListener("pointermove", move);
        el.removeEventListener("pointerup", up); el.removeEventListener("pointercancel", up);
        el.removeEventListener("wheel", wheel);
        el.removeEventListener("webglcontextlost", lost);
        document.removeEventListener("visibilitychange", visible);
        disposables.forEach((d) => d.dispose());
        renderer.dispose();
        renderer.forceContextLoss();
        ctl.current = null;
      };
    }).catch(() => { if (!dead) setGl(false); });
    return () => { dead = true; cleanup(); };
  }, [b, gl]);

  useEffect(() => { ctl.current?.update(mix, cut, axis, pos); }, [mix, cut, axis, pos]);

  const box = allBounds(b);
  const size = describeSize(box, b.einheit);
  const names = b.szenen.map((s) => s.name).join(", ");
  const label = `3D-Szene: ${names}. ${size}. ${b.szenen.reduce((a, s) => a + s.objekte.length, 0)} Objekte.`;
  const labelOf = (name: string) => b.beschriftungen.filter((l) => l.objekt === name).map((l) => l.text).join("; ");
  const key = (e: React.KeyboardEvent) => {
    const a = orbitKey(e);                                               // mit Strg, Alt oder Meta: null, die Taste gehört dem Browser
    if (a) { e.preventDefault(); ctl.current?.view(a); }
  };

  return (
    <section className="v-model" aria-label={label}>
      <p className="d-name"><span className="label">Maße</span> {size}</p>
      {gl ? (
        <div className="m-stage" tabIndex={0} onKeyDown={key} aria-label={ORBIT_HINT}>
          <canvas ref={canvas} className="m-canvas" role="img" aria-label={label} />
        </div>
      ) : <p className="v-note">3D braucht WebGL, das hier nicht verfügbar ist. Die Objektliste unten zeigt den Inhalt.</p>}
      <div className="m-controls">
        {gl && (
          <div className="m-row" role="group" aria-label="Ansicht">
            {ORBIT_BUTTONS.map(([a, t]) => (
              <button key={a} type="button" onClick={() => ctl.current?.view(a)}>{t}</button>
            ))}
          </div>
        )}
        {n > 1 && (
          <fieldset className="m-scenes">
            <legend>Szene</legend>
            {b.szenen.map((s, i) => (
              <label key={i} className="m-radio">
                <input type="radio" name="szene" checked={Math.round(mix) === i} onChange={() => setMix(i)} /> {s.name}
              </label>
            ))}
            <label className="m-slider">Überblenden
              <input type="range" min={0} max={n - 1} step={0.05} value={mix} aria-label="Überblenden zwischen den Szenen"
                onChange={(e) => setMix(Number(e.target.value))} />
            </label>
          </fieldset>
        )}
        {gl && (
          <fieldset className="m-cut">
            <legend>Schnitt</legend>
            <label className="m-radio"><input type="checkbox" checked={cut} onChange={(e) => setCut(e.target.checked)} /> Schnitt zeigen</label>
            <label className="m-slider">Achse
              <select value={axis} onChange={(e) => setAxis(e.target.value as Axis)} disabled={!cut}>
                {(["x", "y", "z"] as const).map((a) => <option key={a} value={a}>{AXIS_LABEL[a]}</option>)}
              </select>
            </label>
            <label className="m-slider">Lage
              <input type="range" min={0} max={1} step={0.01} value={pos} disabled={!cut} aria-label="Lage des Schnitts"
                onChange={(e) => setPos(Number(e.target.value))} />
            </label>
          </fieldset>
        )}
      </div>
      {n > 1 && (
        <ul className="m-diff" aria-label="Unterschiede zwischen den Szenen">
          {b.szenen.slice(1).map((s, i) => (
            <li key={i}><strong>{b.szenen[i].name} zu {s.name}:</strong> {diffText(diffScenes(b.szenen[i].objekte, s.objekte))}</li>
          ))}
        </ul>
      )}
      <details className="m-list">
        <summary>Objektliste ({b.szenen.reduce((a, s) => a + s.objekte.length, 0)})</summary>
        <div className="v-table-wrap">
          <table className="v-table">
            <thead><tr><th scope="col">Szene</th><th scope="col">Name</th><th scope="col">Körper</th><th scope="col">Beschriftung</th></tr></thead>
            <tbody>
              {b.szenen.flatMap((s, i) => s.objekte.map((o, j) => (
                <tr key={`${i}-${j}`}><td>{s.name}</td><td>{o.name || "–"}</td><td>{describeObject(o)}</td><td>{o.name ? labelOf(o.name) : ""}</td></tr>
              )))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}
