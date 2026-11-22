import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { layoutNet, type NetArt, type NetBox, type NetLayout, type NetLine, type NetNode } from "../../lib/layout";
import type { NetBlock } from "../../lib/stage";
import { useBoxSize } from "../../lib/useBoxSize";

// Diagramm `netz` (Plan docs/ui-p6-plan.md, Abschnitt 4, P6b): Ablauf, Baum, Mindmap. Die Anordnung rechnet lib/layout.ts,
// gezeichnet wird ein eigenes SVG aus Zahlen; Texte stehen als Textknoten, nie als HTML. Die Art eines Knotens zeigt die Form
// (Kapsel = Start, doppelte Kapsel = Ende, Raute = Entscheidung, Kasten = Schritt) und das Wort in der Liste, nicht nur die Farbe.
// Vergrößern, Verkleinern, Einpassen und Verschieben ändern nur die Anzeige im Fenster: nichts wird gesendet oder gespeichert.
// Für Vorleser steht der Aufbau zusätzlich als Liste da (Ablauf: jeder Knoten einmal mit seinen Zielen; Baum: verschachtelt).

const LINE_H = 18, CHAR_W = 7.2;
const FIT_MIN = 0.75, ZOOM_FLOOR = 0.02, ZOOM_MAX = 3, STEP = 1.25, PAN = 0.2;
const DEFAULT_W = 720, MIN_H = 120;
const FORM_LABEL = { ablauf: "Ablauf", baum: "Baum", mindmap: "Mindmap" } as const;
const ART_WORD: Record<NetArt, string> = { start: "Start", ende: "Ende", entscheidung: "Entscheidung", schritt: "Schritt" };
const ARTS: readonly string[] = ["start", "ende", "entscheidung", "schritt"];

interface Cam { s: number; tx: number; ty: number }
type Act = "in" | "out" | "fit" | "left" | "right" | "up" | "down";

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const r1 = (v: number) => Math.round(v * 10) / 10;
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
/** „a“, „a und b“, „a, b und c“ */
const joinDe = (xs: string[]) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} und ${xs[xs.length - 1]}`);
/** Höchste Höhe der Zeichenfläche: 60 % des Fensters, zwischen 240 und 640 px. */
const maxFrameH = () => Math.round(clamp((typeof window !== "undefined" ? window.innerHeight : 800) * 0.6, 240, 640));

export function Net({ b }: { b: NetBlock }) {
  const knoten = Array.isArray(b.knoten) ? b.knoten : [];
  const kanten = Array.isArray(b.kanten) ? b.kanten : [];
  const form = b.form === "baum" || b.form === "mindmap" ? b.form : "ablauf";
  const layout = useMemo(() => layoutNet(form,
    knoten.map((k) => ({ id: k?.id, text: k?.text, art: ARTS.includes(k?.art as string) ? k.art : undefined }) as NetNode),   // "" = Schritt
    kanten.map((e) => ({ von: e?.von, bis: e?.bis, text: e?.text ?? "" }))),
  [form, b.knoten, b.kanten]);                                           // einmal je Datenstand, nicht bei jedem Zoom

  const wrap = useRef<HTMLElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number } | null>(null);
  const [cam, setCam] = useState<{ for: NetLayout; c: Cam } | null>(null);
  const marker = `n-arrow-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const box = useBoxSize(wrap);

  // Maße: Start eingepasst in die Breite (und die Höchsthöhe), aber nie kleiner als FIT_MIN, damit der Text lesbar bleibt.
  // „Einpassen“ zeigt dagegen alles, auch wenn es dann klein wird. Die Fläche behält ihre Höhe beim Zoomen (nichts springt).
  const W = layout.width, H = layout.height;
  const fw = Math.max(120, (box?.width ?? DEFAULT_W) - 2);
  const hMax = maxFrameH();
  const s0 = Math.min(1, Math.max(FIT_MIN, Math.min(fw / W, hMax / H)));
  const fh = Math.round(clamp(H * s0, MIN_H, hMax));
  const sFit = Math.min(1, fw / W, fh / H);
  const zMin = Math.max(ZOOM_FLOOR, Math.min(sFit, 0.5));
  /** Hält den Ausschnitt im Diagramm: Was kleiner als die Fläche ist, steht mittig, sonst bleibt kein leerer Rand. */
  const fix = (k: Cam): Cam => {
    const fin = (v: number) => (Number.isFinite(v) ? v : 0);
    const s = clamp(Number.isFinite(k.s) ? k.s : 1, zMin, ZOOM_MAX), cw = W * s, ch = H * s;
    return { s, tx: cw <= fw ? (fw - cw) / 2 : clamp(fin(k.tx), fw - cw, 0), ty: ch <= fh ? (fh - ch) / 2 : clamp(fin(k.ty), fh - ch, 0) };
  };
  const start = fix({ s: s0, tx: (fw - W * s0) / 2, ty: form === "mindmap" ? (fh - H * s0) / 2 : 0 });
  const cur = (p: typeof cam) => (p && p.for === layout ? fix(p.c) : start);
  const c = cur(cam);

  const zoomTo = (k: Cam, s: number): Cam => {
    const ns = clamp(s, zMin, ZOOM_MAX), cx = fw / 2, cy = fh / 2;
    return { s: ns, tx: cx - ((cx - k.tx) * ns) / k.s, ty: cy - ((cy - k.ty) * ns) / k.s };
  };
  const move = (f: (k: Cam) => Cam) => setCam((p) => ({ for: layout, c: fix(f(cur(p))) }));
  const act = (a: Act) => move((k) => {
    switch (a) {
      case "in": return zoomTo(k, k.s * STEP);
      case "out": return zoomTo(k, k.s / STEP);
      case "fit": return { s: sFit, tx: (fw - W * sFit) / 2, ty: (fh - H * sFit) / 2 };
      case "left": return { ...k, tx: k.tx + fw * PAN };
      case "right": return { ...k, tx: k.tx - fw * PAN };
      case "up": return { ...k, ty: k.ty + fh * PAN };
      case "down": return { ...k, ty: k.ty - fh * PAN };
    }
  });

  useEffect(() => {                                                      // Strg + Mausrad (auch Zwei-Finger-Zoom) zoomt; sonst scrollt die Seite
    const el = frame.current;
    if (!el) return;
    const wheel = (e: WheelEvent) => { if (!e.ctrlKey) return; e.preventDefault(); act(e.deltaY < 0 ? "in" : "out"); };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  });

  if (!layout.boxes.length) {
    return <section ref={wrap} className="v-net" aria-label="Diagramm"><p className="v-note">Diagramm kann nicht gezeigt werden.</p></section>;
  }

  const key = (e: React.KeyboardEvent) => {
    const map: Record<string, Act> = { ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down", "+": "in", "=": "in", "-": "out", "0": "fit", Home: "fit" };
    if (map[e.key]) { e.preventDefault(); act(map[e.key]); }
  };
  const down = (e: React.PointerEvent) => { drag.current = { x: e.clientX, y: e.clientY }; frame.current?.setPointerCapture?.(e.pointerId); };
  const pointerMove = (e: React.PointerEvent) => {
    if (!drag.current) return;
    const dx = e.clientX - drag.current.x, dy = e.clientY - drag.current.y;
    if (!Number.isFinite(dx) || !Number.isFinite(dy)) return;
    drag.current = { x: e.clientX, y: e.clientY };
    move((k) => ({ ...k, tx: k.tx + dx, ty: k.ty + dy }));
  };
  const up = () => { drag.current = null; };

  const cw = W * c.s, ch = H * c.s;
  const can: Record<Act, boolean> = {
    in: c.s < ZOOM_MAX - 1e-9, out: c.s > zMin + 1e-9, fit: true,
    left: cw > fw && c.tx < -0.5, right: cw > fw && c.tx > fw - cw + 0.5,
    up: ch > fh && c.ty < -0.5, down: ch > fh && c.ty > fh - ch + 0.5,
  };
  const bigger = cw > fw + 1 || ch > fh + 1;

  const textOf = new Map<string, string>();
  for (const k of knoten) if (k && typeof k.id === "string" && !textOf.has(k.id)) textOf.set(k.id, typeof k.text === "string" ? k.text : "");
  const nameOf = (id: string) => textOf.get(id) || "(ohne Text)";
  const labelOf = (e: NetLine) => { const t = kanten[e.index]?.text; return typeof t === "string" ? t : e.label?.text ?? ""; };
  const hasIn = new Set(layout.edges.filter((e) => e.von !== e.bis).map((e) => e.bis));
  const root = form === "ablauf" ? null : layout.boxes.find((x) => !hasIn.has(x.id))?.id ?? layout.boxes[0].id;
  const missingNodes = knoten.length - layout.boxes.length, missingEdges = kanten.length - layout.edges.length;
  const summary = `${FORM_LABEL[form]} mit ${plural(layout.boxes.length, "Knoten", "Knoten")} und ${plural(layout.edges.length, "Verbindung", "Verbindungen")}`;

  return (
    <section ref={wrap} className={`v-net n-${form}`} aria-label={`Diagramm: ${FORM_LABEL[form]}`}>
      <p className="d-name"><span className="label">Diagramm</span> {summary}</p>
      <div ref={frame} className="n-frame" style={{ height: fh + 2 }} tabIndex={0} role="group" onKeyDown={key}
        aria-label="Diagramm-Fläche. Pfeiltasten verschieben, Plus und Minus zoomen, Null passt ein. Den Aufbau gibt es als Liste darunter."
        onPointerDown={down} onPointerMove={pointerMove} onPointerUp={up} onPointerCancel={up}>
        <svg className="n-svg" viewBox={`0 0 ${r1(W)} ${r1(H)}`} width={r1(cw)} height={r1(ch)} aria-hidden="true" focusable="false"
          style={{ transform: `translate(${r1(c.tx)}px, ${r1(c.ty)}px)` }}>
          <defs>
            <marker id={marker} viewBox="0 0 10 10" refX={10} refY={5} markerWidth={10} markerHeight={10} markerUnits="userSpaceOnUse" orient="auto">
              <path className="n-arrow" d="M 0 0 L 10 5 L 0 10 z" />
            </marker>
          </defs>
          <g className="n-edges">
            {layout.edges.map((e) => (
              <polyline key={e.index} className={e.back ? "n-edge n-back" : "n-edge"} points={e.points.map(([x, y]) => `${r1(x)},${r1(y)}`).join(" ")}
                markerEnd={`url(#${marker})`} />
            ))}
          </g>
          <g className="n-nodes">{layout.boxes.map((x) => <NodeShape key={x.id} b={x} root={x.id === root} />)}</g>
          <g className="n-labels">
            {layout.edges.map((e) => e.label && (
              <g key={e.index} className="n-elabel">
                <rect className="n-label-bg" x={r1(e.label.x - (e.label.text.length * CHAR_W + 8) / 2)} y={r1(e.label.y - LINE_H / 2)}
                  width={r1(e.label.text.length * CHAR_W + 8)} height={LINE_H} rx={3} />
                <text className="n-label" x={r1(e.label.x)} y={r1(e.label.y)} dy="0.35em" textAnchor="middle">{e.label.text}</text>
              </g>
            ))}
          </g>
        </svg>
      </div>
      <div className="m-controls">
        <div className="m-row n-row" role="group" aria-label="Ansicht des Diagramms">
          {([["in", "Vergrößern"], ["out", "Verkleinern"], ["fit", "Einpassen"], ["left", "Nach links"], ["right", "Nach rechts"], ["up", "Nach oben"], ["down", "Nach unten"]] as const)
            .map(([a, t]) => <button key={a} type="button" aria-disabled={can[a] ? undefined : "true"} onClick={() => act(a)}>{t}</button>)}
          <span className="label n-scale" aria-live="polite">Maßstab {Math.round(c.s * 100)} %</span>
        </div>
        {bigger && <p className="v-note">Größer als die Fläche: verschieben mit den Pfeilknöpfen, den Pfeiltasten oder durch Ziehen; Einpassen zeigt alles.</p>}
        {(missingNodes > 0 || missingEdges > 0) && (
          <p className="v-note">Nicht gezeigt: {joinDe([
            ...(missingNodes > 0 ? [`${plural(missingNodes, "Knoten", "Knoten")} ohne eindeutige id`] : []),
            ...(missingEdges > 0 ? [`${plural(missingEdges, "Verbindung", "Verbindungen")} zu unbekannten Knoten`] : [])])}.</p>
        )}
      </div>
      <details className="n-list m-list">
        <summary>Als Liste zeigen ({summary})</summary>
        {form === "ablauf" ? <FlowList layout={layout} nameOf={nameOf} labelOf={labelOf} /> : <TreeList layout={layout} nameOf={nameOf} labelOf={labelOf} />}
      </details>
    </section>
  );
}

/** Ein Knoten: Form je Art, Text als Zeilen aus der Anordnung (Zeile k mittig gestapelt, bei Kästen bei y + 8 + (k + 0.5) · 18). */
function NodeShape({ b, root }: { b: NetBox; root: boolean }) {
  const { x, y, w, h, art } = b;
  const top = y + (h - b.lines.length * LINE_H) / 2;
  let shape: ReactNode;
  if (art === "entscheidung") {
    shape = <polygon className="n-shape" points={`${r1(x + w / 2)},${r1(y)} ${r1(x + w)},${r1(y + h / 2)} ${r1(x + w / 2)},${r1(y + h)} ${r1(x)},${r1(y + h / 2)}`} />;
  } else if (art === "start" || art === "ende") {
    shape = (
      <>
        <rect className="n-shape" x={r1(x)} y={r1(y)} width={r1(w)} height={r1(h)} rx={r1(h / 2)} />
        {art === "ende" && <rect className="n-inner" x={r1(x + 4)} y={r1(y + 4)} width={r1(w - 8)} height={r1(h - 8)} rx={r1((h - 8) / 2)} />}
      </>
    );
  } else {
    shape = <rect className="n-shape" x={r1(x)} y={r1(y)} width={r1(w)} height={r1(h)} rx={4} />;
  }
  return (
    <g className={`n-node n-${art}${root ? " n-root" : ""}`} data-id={b.id}>
      {shape}
      <text className="n-text" textAnchor="middle">
        {b.lines.map((l, k) => <tspan key={k} x={r1(x + w / 2)} y={r1(top + (k + 0.5) * LINE_H)} dy="0.35em">{l}</tspan>)}
      </text>
    </g>
  );
}

interface ListProps { layout: NetLayout; nameOf: (id: string) => string; labelOf: (e: NetLine) => string }

const artWord = (art: NetArt) => (art === "schritt" ? null : <span className="n-art"> ({ART_WORD[art]})</span>);
const target = (e: NetLine, nameOf: ListProps["nameOf"], labelOf: ListProps["labelOf"]) => {
  const l = labelOf(e);
  return `${e.von === e.bis ? "sich selbst" : nameOf(e.bis)}${l ? ` (Beschriftung: ${l})` : ""}`;
};
const outgoing = (layout: NetLayout) => {
  const out = new Map<string, NetLine[]>();
  for (const e of layout.edges) out.set(e.von, [...(out.get(e.von) ?? []), e]);
  return out;
};

/** Ablauf: jeder Knoten genau einmal (in Lesereihenfolge oben nach unten) mit seinen Zielen. Rückwärtskanten heißen
 *  „zurück zu …“, so endet die Liste auch bei Schleifen. */
function FlowList({ layout, nameOf, labelOf }: ListProps) {
  const out = outgoing(layout);
  const order = [...layout.boxes].sort((p, q) => p.y - q.y || p.x - q.x);
  return (
    <ul className="n-flat">
      {order.map((x) => {
        const es = out.get(x.id) ?? [];
        const fwd = es.filter((e) => !e.back && e.von !== e.bis).map((e) => target(e, nameOf, labelOf));
        const back = es.filter((e) => e.back || e.von === e.bis).map((e) => `zurück zu ${target(e, nameOf, labelOf)}`);
        const phrase = !es.length ? "führt nicht weiter" : fwd.length ? `führt zu ${joinDe([...fwd, ...back])}` : `führt ${joinDe(back)}`;
        return <li key={x.id}><span className="n-name">{nameOf(x.id)}</span>{artWord(x.art)} {phrase}</li>;
      })}
    </ul>
  );
}

/** Baum und Mindmap: verschachtelte Liste ab der Wurzel. Jeder Knoten erscheint einmal; eine Kante zu einem schon genannten
 *  Knoten steht als „führt auch zu …“ beim Ausgangsknoten. */
function TreeList({ layout, nameOf, labelOf }: ListProps) {
  const out = outgoing(layout);
  const hasIn = new Set(layout.edges.filter((e) => e.von !== e.bis).map((e) => e.bis));
  const seen = new Set<string>(), kids = new Map<string, NetLine[]>(), extra = new Map<string, NetLine[]>(), roots: string[] = [];
  for (const r of [...layout.boxes.filter((x) => !hasIn.has(x.id)), ...layout.boxes].map((x) => x.id)) {
    if (seen.has(r)) continue;
    seen.add(r); roots.push(r);
    const queue = [r];
    for (let q = 0; q < queue.length; q++) {
      const v = queue[q];
      for (const e of out.get(v) ?? []) {
        if (e.von !== e.bis && !seen.has(e.bis)) { seen.add(e.bis); queue.push(e.bis); kids.set(v, [...(kids.get(v) ?? []), e]); }
        else extra.set(v, [...(extra.get(v) ?? []), e]);
      }
    }
  }
  const art = new Map(layout.boxes.map((x) => [x.id, x.art]));
  const item = (id: string, via: NetLine | null): ReactNode => {
    const ks = kids.get(id) ?? [], more = extra.get(id) ?? [];
    const l = via ? labelOf(via) : "";
    return (
      <li key={id}>
        <span className="n-name">{nameOf(id)}</span>{artWord(art.get(id) ?? "schritt")}{l && <span className="n-art"> (Beschriftung: {l})</span>}
        {more.length > 0 && <span className="n-art">, führt auch zu {joinDe(more.map((e) => target(e, nameOf, labelOf)))}</span>}
        {ks.length > 0 && <ul>{ks.map((e) => item(e.bis, e))}</ul>}
      </li>
    );
  };
  return <ul className="n-tree">{roots.map((r) => item(r, null))}</ul>;
}
