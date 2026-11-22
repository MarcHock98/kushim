import { useCallback, useMemo, useRef } from "react";
import { molekuelGeometrie, normalizeTeilchen, type GeoAtom, type MolekuelConfig, type MolekuelGeometrie } from "../../lib/chem";
import { ORBIT_BUTTONS, ORBIT_HINT } from "../../lib/orbitCamera";
import type { Farbe } from "../../lib/physics";
import type { TeilchenBlock } from "../../lib/stage";
import { useOrbitViewer, type Builder } from "./useOrbitViewer";

// Baustein `teilchen`, Form `molekuel` (Plan docs/ui-p5-plan.md, Abschnitt 7, P5b). Kugeln je Palettenfarbe als ein gebündeltes
// Netz (InstancedMesh), Bindungen als Zylinder (Doppel- und Dreifachbindung als zwei oder drei dünne parallele Zylinder, jede Hälfte
// in der Farbe ihres Atoms), also wenige Zeichenaufrufe, auch bei 300 Atomen. Gezeichnet wird nur bei einer Änderung. Elementsymbole,
// Beschriftungen und der Name stehen nur als Text im DOM, nie im Bild. Die Atomliste ersetzt das Bild für Vorleser und ohne WebGL.

export const FARBE_WORT: Readonly<Record<Farbe, string>> = {
  arc: "Cyan", amber: "Bernstein", ok: "Grün", warn: "Warnfarbe (Bernstein)", alarm: "Rot", text: "Weiß", gedaempft: "Grau",
};
const NOT_SHOWN = "Teilchen kann nicht gezeigt werden.";
const ADJUSTED = "Einige Angaben fehlten oder lagen außerhalb der Grenzen und wurden angepasst.";
const BOND_R: Record<1 | 2 | 3, number> = { 1: 0.08, 2: 0.05, 3: 0.04 };

type V = [number, number, number];
const sub = (a: V, b: V): V => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const len = (a: V) => Math.hypot(a[0], a[1], a[2]);
const cross = (a: V, b: V): V => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];

/** Ein Einheitsvektor senkrecht zu `d` (für den Abstand paralleler Zylinder). */
function perpendicular(d: V): V {
  const ref: V = Math.abs(d[2]) < 0.9 * len(d) ? [0, 0, 1] : [1, 0, 0];
  const p = cross(d, ref), l = len(p);
  return l > 1e-9 ? [p[0] / l, p[1] / l, p[2] / l] : [1, 0, 0];
}

/** Bauplan der Szene aus der fertigen Geometrie: ein InstancedMesh je Farbe für Kugeln, eins je Farbe für Bindungshälften. */
function molekuelBuilder(geo: MolekuelGeometrie): Builder {
  return (T, scene, color) => {
    const disposables: { dispose(): void }[] = [];
    const group = new T.Group();
    scene.add(group);
    const sphere = new T.SphereGeometry(1, 24, 16);
    const rod = new T.CylinderGeometry(1, 1, 1, 12, 1);
    disposables.push(sphere, rod);
    const materials = new Map<Farbe, InstanceType<typeof T.MeshStandardMaterial>>();
    const material = (f: Farbe) => {
      let m = materials.get(f);
      if (!m) {
        m = new T.MeshStandardMaterial({ color: new T.Color(color(f)), roughness: 0.55, metalness: 0.05 });
        materials.set(f, m);
        disposables.push(m);
      }
      return m;
    };
    const m4 = new T.Matrix4(), q = new T.Quaternion(), s = new T.Vector3(), p = new T.Vector3(), up = new T.Vector3(0, 1, 0), dir = new T.Vector3();

    const byColor = new Map<Farbe, GeoAtom[]>();
    for (const a of geo.atome) byColor.set(a.farbe, [...(byColor.get(a.farbe) ?? []), a]);
    for (const [f, list] of byColor) {
      const mesh = new T.InstancedMesh(sphere, material(f), list.length);
      list.forEach((a, i) => {
        m4.compose(p.set(a.position[0], a.position[1], a.position[2]), q.identity(), s.set(a.radius, a.radius, a.radius));
        mesh.setMatrixAt(i, m4);
      });
      mesh.instanceMatrix.needsUpdate = true;
      disposables.push(mesh);
      group.add(mesh);
    }

    if (geo.darstellung === "kugel-stab") {                             // im Kalottenmodell verdecken die Kugeln die Bindungen
      const halves = new Map<Farbe, { from: V; to: V; r: number }[]>();
      const push = (f: Farbe, from: V, to: V, r: number) => halves.set(f, [...(halves.get(f) ?? []), { from, to, r }]);
      for (const b of geo.bindungen) {
        const A = geo.atome[b.von], B = geo.atome[b.bis];
        if (!A || !B) continue;
        const d = sub(B.position, A.position);
        if (!(len(d) > 1e-6)) continue;
        const r = BOND_R[b.ordnung] ?? BOND_R[1], gap = 2.6 * r, n = b.ordnung, off = perpendicular(d);
        for (let k = 0; k < n; k++) {
          const t = (k - (n - 1) / 2) * gap;
          const a: V = [A.position[0] + off[0] * t, A.position[1] + off[1] * t, A.position[2] + off[2] * t];
          const c: V = [B.position[0] + off[0] * t, B.position[1] + off[1] * t, B.position[2] + off[2] * t];
          const mid: V = [(a[0] + c[0]) / 2, (a[1] + c[1]) / 2, (a[2] + c[2]) / 2];
          push(A.farbe, a, mid, r);
          push(B.farbe, mid, c, r);
        }
      }
      for (const [f, list] of halves) {
        const mesh = new T.InstancedMesh(rod, material(f), list.length);
        list.forEach((h, i) => {
          const d = sub(h.to, h.from), l = len(d);
          dir.set(d[0] / l, d[1] / l, d[2] / l);
          q.setFromUnitVectors(up, dir);
          m4.compose(p.set((h.from[0] + h.to[0]) / 2, (h.from[1] + h.to[1]) / 2, (h.from[2] + h.to[2]) / 2), q, s.set(h.r, l, h.r));
          mesh.setMatrixAt(i, m4);
        });
        mesh.instanceMatrix.needsUpdate = true;
        disposables.push(mesh);
        group.add(mesh);
      }
    }
    return { size: 2 * geo.radius, center: [0, 0, 0], disposables };
  };
}

export function Molecule3D({ b }: { b: TeilchenBlock }) {
  const cfg = useMemo(() => normalizeTeilchen(b), [b]);
  const mol = cfg.form === "molekuel" && !cfg.ungueltig ? (cfg as MolekuelConfig) : null;
  const geo = useMemo(() => (mol ? molekuelGeometrie(mol) : null), [mol]);
  const canvas = useRef<HTMLCanvasElement>(null);
  const labels = useRef<(HTMLSpanElement | null)[]>([]);
  const build = useMemo<Builder | null>(() => {
    if (!geo || geo.ungueltig || geo.atomzahl === 0) return null;
    const inner = molekuelBuilder(geo);
    return (T, scene, color) => {
      const built = inner(T, scene, color);
      built.onPaint = (project) => {                                    // Beschriftungen als DOM-Text neben ihrem Atom
        geo.beschriftungen.forEach((l, i) => {
          const el = labels.current[i], a = geo.atome[l.atom];
          if (!el || !a) return;
          const at = project(a.position);
          el.hidden = !at;
          if (at) el.style.transform = `translate(${Math.round(at.x)}px, ${Math.round(at.y)}px)`;
        });
      };
      return built;
    };
  }, [geo]);
  const { gl, view, onKeyDown } = useOrbitViewer(canvas, build);
  const setLabel = useCallback((i: number) => (el: HTMLSpanElement | null) => { labels.current[i] = el; }, []);

  if (!mol || !geo || geo.ungueltig || geo.atomzahl === 0) {          // ungültig oder leer: nie ein leeres Bild, kein Renderer
    return (
      <section className="v-teilchen" aria-label="Molekül">
        <p className="v-note" role="note">{NOT_SHOWN}</p>
      </section>
    );
  }

  const elements = new Map<string, { name: string; farbe: Farbe; n: number }>();
  for (const a of geo.atome) {
    const e = elements.get(a.element);
    if (e) e.n++; else elements.set(a.element, { name: a.name, farbe: a.farbe, n: 1 });
  }
  const doppelt = geo.bindungen.filter((x) => x.ordnung === 2).length, dreifach = geo.bindungen.filter((x) => x.ordnung === 3).length;
  const multiple = [
    doppelt ? (doppelt === 1 ? "1 Doppelbindung" : `${doppelt} Doppelbindungen`) : "",
    dreifach ? (dreifach === 1 ? "1 Dreifachbindung" : `${dreifach} Dreifachbindungen`) : "",
  ].filter(Boolean).join(", ");
  return (
    <section className="v-teilchen" aria-label="Molekül">
      <div className="t-head">
        <span className="label">Molekül</span>
        {mol.name && <span className="t-name">{mol.name}</span>}
      </div>
      <p className="t-facts">
        <span>Summenformel <strong className="t-formula">{geo.summenformel}</strong></span>
        <span>{geo.atomzahl === 1 ? "1 Atom" : `${geo.atomzahl} Atome`}</span>
        <span>{geo.bindungszahl === 1 ? "1 Bindung" : `${geo.bindungszahl} Bindungen`}{multiple && ` (davon ${multiple})`}</span>
      </p>
      {mol.angepasst.length > 0 && <p className="v-note">{ADJUSTED}</p>}
      {geo.bindungenAbgeleitet && <p className="v-note">Bindungen aus Abständen berechnet</p>}
      {geo.darstellung === "kalotte" && <p className="v-note">Kalottenmodell: Atome in ihrer Van-der-Waals-Größe, Bindungen nicht einzeln gezeichnet.</p>}
      {gl ? (
        <div className="m-stage" tabIndex={0} onKeyDown={onKeyDown} aria-label={ORBIT_HINT}>
          <canvas ref={canvas} className="m-canvas" role="img" aria-label="Bild des Moleküls; die Beschreibung und die Atomliste stehen darunter als Text" />
          {geo.beschriftungen.length > 0 && (
            <div className="t-overlay" aria-hidden="true">
              {geo.beschriftungen.map((l, i) => <span key={i} ref={setLabel(i)} className="t-tag" hidden>{l.text}</span>)}
            </div>
          )}
        </div>
      ) : <p className="v-note" role="note">3D braucht WebGL, das hier nicht verfügbar ist. Die Atomliste unten zeigt den Inhalt.</p>}
      {gl && (
        <div className="m-row" role="group" aria-label="Ansicht">
          {ORBIT_BUTTONS.map(([a, t]) => <button key={a} type="button" onClick={() => view(a)}>{t}</button>)}
        </div>
      )}
      <ul className="t-legend" aria-label="Elemente">
        {[...elements].map(([sym, e]) => (
          <li key={sym}><span className="t-sym">{sym}</span> {e.name}, {e.n}×, Farbe {FARBE_WORT[e.farbe] ?? "Bernstein"}</li>
        ))}
      </ul>
      {geo.beschriftungen.length > 0 && (
        <ul className="t-labels" aria-label="Beschriftungen">
          {geo.beschriftungen.map((l, i) => (
            <li key={i}>Atom {l.atom + 1} ({geo.atome[l.atom]?.element ?? "–"}): <span className="t-name">{l.text}</span></li>
          ))}
        </ul>
      )}
      <div className="s-text">
        <span className="label">Beschreibung</span>
        <p>{geo.text}</p>
      </div>
      <details className="m-list" open={!gl}>
        <summary>Atomliste ({geo.atomzahl})</summary>
        <div className="v-table-wrap">
          <table className="v-table">
            <thead><tr><th scope="col">Nr.</th><th scope="col">Symbol</th><th scope="col">Element</th><th scope="col">x in Å</th><th scope="col">y in Å</th><th scope="col">z in Å</th></tr></thead>
            <tbody>
              {geo.zeilen.map((z) => (
                <tr key={z.index}>
                  <td className="num">{z.index + 1}</td><td>{z.symbol}</td><td>{z.name}</td>
                  <td className="num">{z.koordinaten[0]}</td><td className="num">{z.koordinaten[1]}</td><td className="num">{z.koordinaten[2]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}
