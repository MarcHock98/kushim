import { useMemo } from "react";
import { atomModell, normalizeTeilchen, type AtomConfig } from "../../lib/chem";
import type { TeilchenBlock } from "../../lib/stage";

// Baustein `teilchen`, Form `atom` (Plan docs/ui-p5-plan.md, Abschnitt 7, P5b): vereinfachtes Schalenmodell als eigenes, statisches
// SVG. Keine Animation: kreisende Elektronen würden eine falsche Vorstellung zeigen. Kern mit Symbol und den Zahlen der Protonen (p)
// und Neutronen (n) als Text, Schalen als Ringe, Elektronen als gleichmäßig verteilte Punkte. Leere Schalen bleiben als Ring ohne
// Punkte stehen; bis zu 32 Elektronen auf einem Ring und bis zu 7 Ringe passen, die Punkte werden dafür kleiner. Ladung in Worten.

const NOT_SHOWN = "Teilchen kann nicht gezeigt werden.";
const ADJUSTED = "Einige Angaben fehlten oder lagen außerhalb der Grenzen und wurden angepasst.";
const CORE_R = 34, STEP = 22, DOT_R = 4.5, PAD = 10;

/** Lagen der Elektronen: n Punkte gleichmäßig auf dem Ring mit Radius r, der erste oben. */
export function electronPositions(n: number, r: number): { x: number; y: number }[] {
  const out: { x: number; y: number }[] = [];
  for (let i = 0; i < n; i++) {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / n;
    out.push({ x: r * Math.cos(a), y: r * Math.sin(a) });
  }
  return out;
}

/** Punktgröße, damit sich die Punkte nicht berühren: höchstens 35 % des Abstands zweier Nachbarn auf dem Ring. */
export function dotRadius(n: number, r: number): number {
  if (n < 2) return DOT_R;
  return Math.max(1, Math.min(DOT_R, 0.35 * 2 * r * Math.sin(Math.PI / n)));
}

export function AtomShells({ b }: { b: TeilchenBlock }) {
  const cfg = useMemo(() => normalizeTeilchen(b), [b]);
  const at = cfg.form === "atom" && !cfg.ungueltig ? (cfg as AtomConfig) : null;
  const m = useMemo(() => (at ? atomModell(at) : null), [at]);

  if (!at || !m || m.ungueltig) {
    return (
      <section className="v-teilchen" aria-label="Atom">
        <p className="v-note" role="note">{NOT_SHOWN}</p>
      </section>
    );
  }
  const shells = m.schalen.slice(0, 7);
  const R = CORE_R + STEP * Math.max(1, shells.length) + PAD;
  const charge = m.ladungText || "elektrisch neutral";
  return (
    <section className="v-teilchen" aria-label="Atom">
      <div className="t-head">
        <span className="label">Atom</span>
        <span className="t-name">{m.name}</span>
      </div>
      <p className="t-flag">Vereinfachtes Schalenmodell</p>
      {at.angepasst.length > 0 && <p className="v-note">{ADJUSTED}</p>}
      <p className="t-facts">
        <span>Ordnungszahl {m.z}</span>
        {m.massenzahl !== null && <span>Massenzahl {m.massenzahl}</span>}
        <span>Ladung: {charge}</span>
      </p>
      <figure className="t-shells">
        <svg viewBox={`${-R} ${-R} ${2 * R} ${2 * R}`} role="img" aria-label="Schalenmodell; die Beschreibung steht darunter als Text">
          {shells.map((n, k) => {
            const r = CORE_R + STEP * (k + 1), dr = dotRadius(n, r);
            return (
              <g key={k} className="a-shell-group">
                <circle className="a-shell" cx={0} cy={0} r={r} />
                {electronPositions(n, r).map((p, i) => (
                  <circle key={i} className="a-electron" cx={Number(p.x.toFixed(2))} cy={Number(p.y.toFixed(2))} r={Number(dr.toFixed(2))} />
                ))}
              </g>
            );
          })}
          <circle className="a-core" cx={0} cy={0} r={CORE_R} />
          <text className="a-sym" x={0} y={-6} textAnchor="middle">{m.symbol}</text>
          <text className="a-count" x={0} y={10} textAnchor="middle">{m.protonen} p</text>
          <text className="a-count" x={0} y={24} textAnchor="middle">{m.neutronen !== null ? `${m.neutronen} n` : "n ?"}</text>
        </svg>
        <figcaption className="v-note">
          Kern: {m.protonen} {m.protonen === 1 ? "Proton" : "Protonen"} (p),{" "}
          {m.neutronen !== null ? `${m.neutronen} ${m.neutronen === 1 ? "Neutron" : "Neutronen"} (n)` : "Neutronenzahl nicht angegeben"}.
          {shells.length > 0 && " Punkte: Elektronen, Ringe: Schalen von innen nach außen."}
        </figcaption>
      </figure>
      {shells.length > 0 ? (
        <ol className="t-legend" aria-label="Schalen">
          {shells.map((n, k) => <li key={k}>Schale {k + 1}: {n === 1 ? "1 Elektron" : `${n} Elektronen`}</li>)}
        </ol>
      ) : <p className="v-note">Keine Elektronen in der Hülle, nur der Kern.</p>}
      <div className="s-text">
        <span className="label">Beschreibung</span>
        <p>{m.text}</p>
      </div>
    </section>
  );
}
