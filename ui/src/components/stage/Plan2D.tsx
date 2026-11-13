import { useEffect, useRef, useState, type ReactNode } from "react";
import { arcEnds, fmt, lengthOf, measureText, planBounds, type PlanBlock, type PlanEl } from "../../lib/scene";

// 2D-Plan aus Linien, Kreisen, Bögen, Texten und Maßen (Plan docs/ui-p4-plan.md, P4a). Gezeichnet als eigenes SVG aus Zahlen:
// SVG-Text von Claude wird nie übernommen. Texte stehen als Textknoten. Striche behalten beim Zoomen ihre Dicke. Ebenen
// unterscheiden sich in Farbe UND Strichart. Bedienbar mit Maus, Touch, Tasten und Knöpfen.

const LAYER_VAR = ["--arc", "--amber", "--text", "--ok", "--warn", "--text-muted"];
const LAYER_DASH = ["", "8 4", "2 4", "10 4 2 4", "", "8 4"];
const NONE = "(ohne Ebene)";

export function Plan2D({ b }: { b: PlanBlock }) {
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());
  const [zoom, setZoom] = useState(1);
  const [off, setOff] = useState<[number, number]>([0, 0]);
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<{ x: number; y: number } | null>(null);

  const bb = planBounds(b.elemente);
  const span = Math.max(bb.maxX - bb.minX, bb.maxY - bb.minY, 1e-6);
  const pad = span * 0.08;
  const w0 = bb.maxX - bb.minX + 2 * pad, h0 = bb.maxY - bb.minY + 2 * pad;
  const cx = (bb.minX + bb.maxX) / 2 + off[0], cy = -((bb.minY + bb.maxY) / 2) + off[1];          // y zeigt im Plan nach oben, im SVG nach unten
  const vw = w0 / zoom, vh = h0 / zoom;
  const fontSize = span * 0.03;
  const layerIdx = (name: string) => Math.max(0, b.ebenen.indexOf(name));

  const act = (a: string) => {
    const step = span * 0.1 / zoom;
    if (a === "in") setZoom((z) => Math.min(40, z * 1.25));
    else if (a === "out") setZoom((z) => Math.max(0.5, z / 1.25));
    else if (a === "reset") { setZoom(1); setOff([0, 0]); }
    else setOff(([x, y]) => (a === "left" ? [x - step, y] : a === "right" ? [x + step, y] : a === "up" ? [x, y - step] : [x, y + step]));
  };

  useEffect(() => {
    const el = svg.current;
    if (!el) return;
    const wheel = (e: WheelEvent) => { e.preventDefault(); act(e.deltaY < 0 ? "in" : "out"); };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  });

  const down = (e: React.PointerEvent) => { drag.current = { x: e.clientX, y: e.clientY }; svg.current?.setPointerCapture?.(e.pointerId); };
  const move = (e: React.PointerEvent) => {
    if (!drag.current || !svg.current) return;
    const k = vw / Math.max(1, svg.current.clientWidth);
    const dx = (e.clientX - drag.current.x) * k, dy = (e.clientY - drag.current.y) * k;
    drag.current = { x: e.clientX, y: e.clientY };
    setOff(([x, y]) => [x - dx, y - dy]);
  };
  const key = (e: React.KeyboardEvent) => {
    const map: Record<string, string> = { ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down", "+": "in", "-": "out", "0": "reset", Home: "reset" };
    if (map[e.key]) { e.preventDefault(); act(map[e.key]); }
  };

  const shown = b.elemente.filter((e) => !hidden.has(e.ebene || NONE));
  const draw = (e: PlanEl, i: number): ReactNode => {
    const li = e.ebene ? layerIdx(e.ebene) : -1;
    const stroke = li >= 0 ? `var(${LAYER_VAR[li % LAYER_VAR.length]})` : "var(--text)";
    const dash = li >= 0 ? LAYER_DASH[li % LAYER_DASH.length] : "";
    const common = { stroke, strokeDasharray: dash || undefined, strokeWidth: 1.5, fill: "none", vectorEffect: "non-scaling-stroke" as const };
    switch (e.art) {
      case "linie": return <line key={i} x1={e.von[0]} y1={-e.von[1]} x2={e.bis[0]} y2={-e.bis[1]} {...common} />;
      case "polylinie": {
        const pts = e.punkte.map((p) => `${p[0]},${-p[1]}`).join(" ");
        return e.geschlossen ? <polygon key={i} points={pts} {...common} /> : <polyline key={i} points={pts} {...common} />;
      }
      case "rechteck": return <rect key={i} x={e.x} y={-(e.y + e.h)} width={e.b} height={e.h} {...common} />;
      case "kreis": return <circle key={i} cx={e.x} cy={-e.y} r={e.r} {...common} />;
      case "bogen": {
        const a = arcEnds(e.x, e.y, e.r, e.von, e.bis);
        return <path key={i} d={`M ${a.start[0]} ${-a.start[1]} A ${e.r} ${e.r} 0 ${a.large ? 1 : 0} 0 ${a.end[0]} ${-a.end[1]}`} {...common} />;
      }
      case "text": return <text key={i} x={e.x} y={-e.y} fontSize={e.groesse || fontSize} fill={stroke} className="p-text">{e.text}</text>;
      case "mass": {
        const mx = (e.von[0] + e.bis[0]) / 2, my = (e.von[1] + e.bis[1]) / 2, len = lengthOf(e.von, e.bis) || 1;
        const nx = -(e.bis[1] - e.von[1]) / len, ny = (e.bis[0] - e.von[0]) / len, t = span * 0.012;       // Normale für die Endstriche
        const tick = (p: [number, number]) => <line key={`${i}${p}`} x1={p[0] - nx * t} y1={-(p[1] - ny * t)} x2={p[0] + nx * t} y2={-(p[1] + ny * t)} {...common} stroke="var(--text-muted)" />;
        return (
          <g key={i}>
            <line x1={e.von[0]} y1={-e.von[1]} x2={e.bis[0]} y2={-e.bis[1]} {...common} stroke="var(--text-muted)" />
            {tick(e.von)}{tick(e.bis)}
            <text x={mx} y={-my - fontSize * 0.5} fontSize={fontSize} fill="var(--text-muted)" textAnchor="middle" className="p-text">{measureText(e, b.einheit)}</text>
          </g>
        );
      }
    }
  };

  const counts = new Map<string, number>();
  for (const e of b.elemente) counts.set(e.ebene || NONE, (counts.get(e.ebene || NONE) ?? 0) + 1);
  const names = [...b.ebenen, ...(counts.has(NONE) ? [NONE] : [])];
  const label = `Plan: ${b.elemente.length} Elemente in ${names.length} Ebenen, Breite ${fmt(bb.maxX - bb.minX)}, Höhe ${fmt(bb.maxY - bb.minY)} ${b.einheit || "(Einheit unbekannt)"}`;

  return (
    <section className="v-plan" aria-label="Plan">
      <p className="d-name"><span className="label">Plan</span> {label.replace(/^Plan: /, "")}</p>
      <div className="p-frame" tabIndex={0} onKeyDown={key} aria-label="Plan-Ansicht. Pfeiltasten verschieben, Plus und Minus zoomen, Null setzt zurück.">
        <svg ref={svg} className="p-svg" viewBox={`${cx - vw / 2} ${cy - vh / 2} ${vw} ${vh}`} role="img" aria-label={label}
          onPointerDown={down} onPointerMove={move} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
          {shown.map(draw)}
        </svg>
      </div>
      <div className="m-controls">
        <div className="m-row" role="group" aria-label="Ansicht">
          {([["left", "Nach links"], ["right", "Nach rechts"], ["up", "Nach oben"], ["down", "Nach unten"], ["in", "Näher"], ["out", "Weiter weg"], ["reset", "Ansicht zurücksetzen"]] as const)
            .map(([a, t]) => <button key={a} type="button" onClick={() => act(a)}>{t}</button>)}
        </div>
        {names.length > 0 && (
          <fieldset className="m-scenes">
            <legend>Ebenen</legend>
            {names.map((n) => (
              <label key={n} className="m-radio">
                <input type="checkbox" checked={!hidden.has(n)} onChange={(e) => setHidden((h) => { const s = new Set(h); if (e.target.checked) s.delete(n); else s.add(n); return s; })} />
                {" "}{n} <small>({counts.get(n) ?? 0})</small>
              </label>
            ))}
          </fieldset>
        )}
      </div>
    </section>
  );
}
