import { useMemo, useRef } from "react";
import { normalizeTeilchen, orbitalPunkte, PHASEN_FARBE, phaseWort, type OrbitalConfig, type OrbitalWolke } from "../../lib/chem";
import { ORBIT_BUTTONS, ORBIT_HINT, type V3 } from "../../lib/orbitCamera";
import type { TeilchenBlock } from "../../lib/stage";
import { FARBE_WORT, LOST } from "./Molecule3D";
import { useOrbitViewer, type Builder } from "./useOrbitViewer";

// Baustein `teilchen`, Form `orbital` (Plan docs/ui-p5-plan.md, Abschnitt 7, P5b): Punktwolke aus der fest eingebauten
// Wasserstoff-Formel (lib/chem.ts, mit Startwert gezogen). Zwei Punktnetze, eins je Phase, in zwei Palettenfarben und immer mit dem
// Wort („Phase plus“, „Phase minus“). Die Achsen tragen x, y und z als DOM-Text. Wie in der Chemie üblich zeigt z nach oben.
// Gezeichnet wird nur bei einer Änderung; es gibt keine Animation.

const NOT_SHOWN = "Teilchen kann nicht gezeigt werden.";
const ADJUSTED = "Einige Angaben fehlten oder lagen außerhalb der Grenzen und wurden angepasst.";
const AXES = ["x", "y", "z"] as const;

/** Chemie-Lage (z nach oben) in die Lage der Szene (y nach oben): (x, y, z) wird (x, z, −y). */
const toScene = (x: number, y: number, z: number): V3 => [x, z, -y];

function orbitalBuilder(w: OrbitalWolke, axisEls: { current: (HTMLSpanElement | null)[] }): Builder {
  return (T, scene, color) => {
    const disposables: { dispose(): void }[] = [];
    const n = w.anzahl;
    const plus = new Float32Array(3 * w.plus), minus = new Float32Array(3 * w.minus);
    let ip = 0, im = 0;
    for (let i = 0; i < n; i++) {
      const p = toScene(w.positionen[3 * i], w.positionen[3 * i + 1], w.positionen[3 * i + 2]);
      const target = w.phasen[i] < 0 ? minus : plus;
      const k = w.phasen[i] < 0 ? im++ : ip++;
      target[3 * k] = p[0]; target[3 * k + 1] = p[1]; target[3 * k + 2] = p[2];
    }
    for (const [arr, farbe] of [[plus, PHASEN_FARBE.plus], [minus, PHASEN_FARBE.minus]] as const) {
      if (!arr.length) continue;
      const geo = new T.BufferGeometry();
      geo.setAttribute("position", new T.BufferAttribute(arr, 3));
      const mat = new T.PointsMaterial({ color: new T.Color(color(farbe)), size: 3, sizeAttenuation: false, transparent: true, opacity: 0.85, depthWrite: false });
      disposables.push(geo, mat);
      scene.add(new T.Points(geo, mat));
    }
    const L = Math.max(1, w.ausdehnung) * 1.1;
    const ends: V3[] = [toScene(L, 0, 0), toScene(0, L, 0), toScene(0, 0, L)];
    const pts: number[] = [];
    for (const e of ends) pts.push(-e[0], -e[1], -e[2], e[0], e[1], e[2]);
    const axGeo = new T.BufferGeometry();
    axGeo.setAttribute("position", new T.BufferAttribute(new Float32Array(pts), 3));
    const axMat = new T.LineBasicMaterial({ color: new T.Color(color("gedaempft")) });
    disposables.push(axGeo, axMat);
    scene.add(new T.LineSegments(axGeo, axMat));
    return {
      size: 2 * L, center: [0, 0, 0], disposables,
      onPaint: (project) => {                                            // Achsennamen als DOM-Text am Ende jeder Achse
        ends.forEach((e, i) => {
          const el = axisEls.current[i];
          if (!el) return;
          const at = project(e);
          el.hidden = !at;
          if (at) el.style.transform = `translate(${Math.round(at.x)}px, ${Math.round(at.y)}px)`;
        });
      },
    };
  };
}

export function Orbital3D({ b }: { b: TeilchenBlock }) {
  const cfg = useMemo(() => normalizeTeilchen(b), [b]);
  const orb = cfg.form === "orbital" && !cfg.ungueltig ? (cfg as OrbitalConfig) : null;
  const wolke = useMemo(() => (orb ? orbitalPunkte(orb) : null), [orb]);
  const canvas = useRef<HTMLCanvasElement>(null);
  const axisEls = useRef<(HTMLSpanElement | null)[]>([]);
  const build = useMemo<Builder | null>(() => (wolke && !wolke.ungueltig && wolke.anzahl > 0 ? orbitalBuilder(wolke, axisEls) : null), [wolke]);
  const { gl, lost, view, onKeyDown } = useOrbitViewer(canvas, build);

  if (!orb || !wolke || wolke.ungueltig || wolke.anzahl === 0) {     // ungültig oder keine Punkte: nie ein leeres Bild, kein Renderer
    return (
      <section className="v-teilchen" aria-label="Orbital">
        <p className="v-note" role="note">{NOT_SHOWN}</p>
      </section>
    );
  }
  return (
    <section className="v-teilchen" aria-label="Orbital">
      <div className="t-head">
        <span className="label">Orbital</span>
        <span className="t-name">{wolke.orbital}</span>
      </div>
      <p className="t-flag">Wasserstoff-Orbital, Wahrscheinlichkeitswolke</p>
      <p className="v-note">Jeder Punkt ist ein möglicher Ort des Elektrons. Wo viele Punkte liegen, ist das Elektron wahrscheinlicher. Die Farben zeigen nur das Vorzeichen der Wellenfunktion, keine Ladung.</p>
      {orb.angepasst.length > 0 && <p className="v-note">{ADJUSTED}</p>}
      {!wolke.vollstaendig && <p className="v-note">Nur {wolke.anzahl} von {wolke.soll} Punkten gezogen (Rechengrenze erreicht).</p>}
      {gl ? (
        <div className="m-stage" tabIndex={0} onKeyDown={onKeyDown} aria-label={ORBIT_HINT}>
          <canvas ref={canvas} className="m-canvas" role="img" aria-label="Bild der Punktwolke; die Beschreibung steht darunter als Text" />
          <div className="t-overlay" aria-hidden="true">
            {AXES.map((a, i) => <span key={a} ref={(el) => { axisEls.current[i] = el; }} className="t-tag t-axis" hidden>{a}</span>)}
          </div>
        </div>
      ) : <p className="v-note" role="note">{lost ? LOST : "3D braucht WebGL, das hier nicht verfügbar ist."} Die Beschreibung unten zeigt den Inhalt.</p>}
      {gl && (
        <div className="m-row" role="group" aria-label="Ansicht">
          {ORBIT_BUTTONS.map(([a, t]) => <button key={a} type="button" onClick={() => view(a)}>{t}</button>)}
        </div>
      )}
      <ul className="t-legend" aria-label="Legende">
        <li><span className={`t-dot t-dot-${PHASEN_FARBE.plus}`} aria-hidden="true" /> {phaseWort(1)}: {wolke.plus} Punkte, Farbe {FARBE_WORT[PHASEN_FARBE.plus]}</li>
        <li><span className={`t-dot t-dot-${PHASEN_FARBE.minus}`} aria-hidden="true" /> {phaseWort(-1)}: {wolke.minus} Punkte, Farbe {FARBE_WORT[PHASEN_FARBE.minus]}</li>
        <li>Kern: im Zentrum, im Bild nicht eingezeichnet, in Wirklichkeit viel kleiner als die Wolke</li>
        <li>Achsen x, y und z durch den Kern, z zeigt nach oben; Längen in Bohr-Radien</li>
      </ul>
      <div className="s-text">
        <span className="label">Beschreibung</span>
        <p>{wolke.text}</p>
      </div>
    </section>
  );
}
