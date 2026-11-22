// Anordnung für Diagramme `netz` (Plan docs/ui-p6-plan.md, Abschnitt 4, P6b): Ablauf in Schichten, sauberer Baum, Mindmap mit
// Strahlen um die Mitte. Reine Funktionen ohne DOM und ohne Paket. Textbreite mit festen Zeichenmaßen geschätzt.
// Die Daten prüft das Backend; trotzdem wirft hier nichts und keine Schleife läuft endlos, auch bei Zyklen, doppelten ids oder Kanten ins Leere.

export type NetForm = "ablauf" | "baum" | "mindmap";
export type NetArt = "start" | "ende" | "entscheidung" | "schritt";
export interface NetNode { id: string; text: string; art?: NetArt }
export interface NetEdge { von: string; bis: string; text?: string }
export type Pt = [number, number];
/** Kasten mit linker oberer Ecke (x, y), Breite w, Höhe h und den umbrochenen Zeilen. */
export interface NetBox { id: string; x: number; y: number; w: number; h: number; lines: string[]; art: NetArt }
/** Kante als Linienzug; erster und letzter Punkt liegen auf dem Rand der Kästen. `index` ist die Stelle in `kanten`. */
export interface NetLine {
  index: number; von: string; bis: string; points: Pt[];
  label: { x: number; y: number; text: string } | null;
  /** Ablauf: Rückwärtskante eines Zyklus (für die Schichten umgedreht, gezeichnet wie jede andere Linie). */
  back: boolean;
}
export interface NetLayout { boxes: NetBox[]; edges: NetLine[]; width: number; height: number }
export interface LayoutOpts { charW?: number; lineH?: number; maxChars?: number; maxLines?: number }

const PAD_X = 12, PAD_Y = 8, MIN_W = 56, GAP_X = 28, GAP_Y = 48, MARGIN = 16, SWEEPS = 6;
const MAX_NODES = 200, MAX_EDGES = 400, MAX_TEXT = 400, MAX_R = 1e5;
const ARTS: readonly NetArt[] = ["start", "ende", "entscheidung", "schritt"];

const num = (v: unknown, def: number, lo: number, hi: number): number =>
  typeof v === "number" && Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : def;

/** Bricht Text an Leerzeichen um, zu lange Wörter hart; höchstens `maxLines` Zeilen, sonst endet die letzte mit „…“. */
export function wrapText(text: unknown, maxChars = 24, maxLines = 8): string[] {
  const words = String(text ?? "").slice(0, MAX_TEXT).split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let cur = "";
  for (let w of words) {
    while (w.length > maxChars) {
      if (cur) { lines.push(cur); cur = ""; }
      lines.push(w.slice(0, maxChars));
      w = w.slice(maxChars);
    }
    if (!w) continue;
    if (!cur) cur = w;
    else if (cur.length + 1 + w.length <= maxChars) cur += " " + w;
    else { lines.push(cur); cur = w; }
  }
  if (cur) lines.push(cur);
  if (!lines.length) lines.push("");
  if (lines.length > maxLines) {
    lines.length = maxLines;
    lines[maxLines - 1] = lines[maxLines - 1].slice(0, maxChars - 1) + "…";
  }
  return lines;
}

interface E { i: number; a: number; b: number; text: string }

/** Punkt auf dem Rand von `b` in Richtung (tx, ty), gesehen von der Mitte des Kastens. */
function borderPoint(b: NetBox, tx: number, ty: number): Pt {
  const cx = b.x + b.w / 2, cy = b.y + b.h / 2, dx = tx - cx, dy = ty - cy;
  if (Math.abs(dx) < 1e-9 && Math.abs(dy) < 1e-9) return [cx, b.y];
  const t = Math.min(Math.abs(dx) > 1e-9 ? b.w / 2 / Math.abs(dx) : Infinity, Math.abs(dy) > 1e-9 ? b.h / 2 / Math.abs(dy) : Infinity);
  return [cx + dx * t, cy + dy * t];
}

/** Mitte eines Linienzugs, gemessen an seiner Länge. */
function polyMid(pts: Pt[]): Pt {
  let total = 0;
  for (let k = 1; k < pts.length; k++) total += Math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1]);
  let rest = total / 2;
  for (let k = 1; k < pts.length; k++) {
    const len = Math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1]);
    if (len >= rest && len > 0) {
      const f = rest / len;
      return [pts[k - 1][0] + (pts[k][0] - pts[k - 1][0]) * f, pts[k - 1][1] + (pts[k][1] - pts[k - 1][1]) * f];
    }
    rest -= len;
  }
  return pts[0];
}

/** Schichten von oben nach unten: Zyklen per Tiefensuche brechen, längster Weg, Baryzentren, Reihen mittig. */
function layoutAblauf(boxes: NetBox[], edges: E[], back: boolean[]): void {
  const n = boxes.length;
  const outE: number[][] = boxes.map(() => []);
  const hasIn = new Array<boolean>(n).fill(false);
  edges.forEach((e, j) => { if (e.a !== e.b) { outE[e.a].push(j); hasIn[e.b] = true; } });
  const idx = boxes.map((_, v) => v);
  const starts = [...idx.filter((v) => boxes[v].art === "start"), ...idx.filter((v) => !hasIn[v]), ...idx];
  const state = new Uint8Array(n);
  for (const s of starts) {
    if (state[s]) continue;
    state[s] = 1;
    const stack: [number, number][] = [[s, 0]];
    while (stack.length) {
      const top = stack[stack.length - 1];
      const v = top[0];
      if (top[1] >= outE[v].length) { state[v] = 2; stack.pop(); continue; }
      const j = outE[v][top[1]++], w = edges[j].b;
      if (state[w] === 1) back[j] = true;
      else if (state[w] === 0) { state[w] = 1; stack.push([w, 0]); }
    }
  }
  const preds: number[][] = boxes.map(() => []), succs: number[][] = boxes.map(() => []);
  const indeg = new Array<number>(n).fill(0);
  edges.forEach((e, j) => {
    if (e.a === e.b) return;
    const [u, v] = back[j] ? [e.b, e.a] : [e.a, e.b];
    succs[u].push(v); preds[v].push(u); indeg[v]++;
  });
  const layer = new Array<number>(n).fill(0);
  const queue = idx.filter((v) => indeg[v] === 0);
  for (let q = 0; q < queue.length; q++) {
    const u = queue[q];
    for (const v of succs[u]) {
      layer[v] = Math.max(layer[v], layer[u] + 1);
      if (--indeg[v] === 0) queue.push(v);
    }
  }
  const depth = Math.max(0, ...layer);
  const layers: number[][] = Array.from({ length: depth + 1 }, () => []);
  for (const v of idx) layers[layer[v]].push(v);
  const pos = new Array<number>(n).fill(0);
  const setPos = (row: number[]) => row.forEach((v, k) => { pos[v] = (k + 0.5) / row.length; });
  layers.forEach(setPos);
  const sweep = (row: number[], nb: number[][]) => {
    const key = new Map<number, number>();
    for (const v of row) key.set(v, nb[v].length ? nb[v].reduce((s, u) => s + pos[u], 0) / nb[v].length : pos[v]);
    row.sort((p, q) => (key.get(p)! - key.get(q)!) || pos[p] - pos[q]);
    setPos(row);
  };
  for (let it = 0; it < SWEEPS; it++) {
    for (let l = 1; l <= depth; l++) sweep(layers[l], preds);
    for (let l = depth - 1; l >= 0; l--) sweep(layers[l], succs);
  }
  const rowW = layers.map((row) => row.reduce((s, v) => s + boxes[v].w, 0) + GAP_X * Math.max(0, row.length - 1));
  const maxW = Math.max(0, ...rowW);
  let y = 0;
  layers.forEach((row, l) => {
    let x = (maxW - rowW[l]) / 2, rowH = 0;
    for (const v of row) { boxes[v].x = x; boxes[v].y = y; x += boxes[v].w + GAP_X; rowH = Math.max(rowH, boxes[v].h); }
    y += rowH + GAP_Y;
  });
}

/** Wald über die Kanten in Breitensuche: Wurzeln zuerst ohne eingehende Kante, jeder Knoten genau einmal. */
function forest(n: number, edges: E[]): { roots: number[]; kids: number[][]; parent: number[]; order: number[] } {
  const out: number[][] = Array.from({ length: n }, () => []);
  const hasIn = new Array<boolean>(n).fill(false);
  for (const e of edges) if (e.a !== e.b) { out[e.a].push(e.b); hasIn[e.b] = true; }
  const kids: number[][] = Array.from({ length: n }, () => []), parent = new Array<number>(n).fill(-1);
  const seen = new Array<boolean>(n).fill(false), roots: number[] = [], order: number[] = [];
  const idx = Array.from({ length: n }, (_, v) => v);
  for (const r of [...idx.filter((v) => !hasIn[v]), ...idx]) {
    if (seen[r]) continue;
    seen[r] = true; roots.push(r); order.push(r);
    for (let q = order.length - 1; q < order.length; q++) {
      const v = order[q];
      for (const w of out[v]) if (!seen[w]) { seen[w] = true; parent[w] = v; kids[v].push(w); order.push(w); }
    }
  }
  return { roots, kids, parent, order };
}

/** Sauberer Baum: Ausdehnung links/rechts je Teilbaum, Eltern mittig über erstem und letztem Kind, Reihen je Tiefe. */
function layoutBaum(boxes: NetBox[], f: ReturnType<typeof forest>): void {
  const n = boxes.length, L = new Array<number>(n).fill(0), R = new Array<number>(n).fill(0);
  const off = new Array<number>(n).fill(0), depth = new Array<number>(n).fill(0), cx = new Array<number>(n).fill(0);
  for (const v of f.order) if (f.parent[v] >= 0) depth[v] = depth[f.parent[v]] + 1;
  for (let q = f.order.length - 1; q >= 0; q--) {
    const v = f.order[q], ks = f.kids[v];
    L[v] = R[v] = boxes[v].w / 2;
    if (!ks.length) continue;
    let c = 0;
    const cs = ks.map((k, i) => (i === 0 ? 0 : (c += R[ks[i - 1]] + GAP_X + L[k])));
    ks.forEach((k, i) => {
      off[k] = cs[i] - c / 2;
      L[v] = Math.max(L[v], L[k] - off[k]);
      R[v] = Math.max(R[v], off[k] + R[k]);
    });
  }
  let cursor = 0;
  for (const r of f.roots) { cx[r] = cursor + L[r]; cursor += L[r] + R[r] + GAP_X; }
  for (const v of f.order) if (f.parent[v] >= 0) cx[v] = cx[f.parent[v]] + off[v];
  const rowH: number[] = [];
  for (const v of f.order) rowH[depth[v]] = Math.max(rowH[depth[v]] ?? 0, boxes[v].h);
  const rowY: number[] = [0];
  for (let d = 1; d < rowH.length; d++) rowY[d] = rowY[d - 1] + rowH[d - 1] + GAP_Y;
  for (const v of f.order) { boxes[v].x = cx[v] - boxes[v].w / 2; boxes[v].y = rowY[depth[v]]; }
}

/** Mindmap: Wurzel in der Mitte, Sektoren nach Blattzahl, Radius je Tiefe so groß, dass sich ein Ring nicht überlappt. */
function layoutMindmap(boxes: NetBox[], f: ReturnType<typeof forest>): void {
  const n = boxes.length;
  if (!n) return;
  const root = f.roots[0];
  const kids = f.kids.map((k, v) => (v === root ? [...k, ...f.roots.slice(1)] : k));
  const leaves = new Array<number>(n).fill(1), depth = new Array<number>(n).fill(0), ang = new Array<number>(n).fill(0);
  const order: number[] = [root];
  for (let q = 0; q < order.length; q++) for (const k of kids[order[q]]) { depth[k] = depth[order[q]] + 1; order.push(k); }
  for (let q = order.length - 1; q >= 0; q--) { const ks = kids[order[q]]; if (ks.length) leaves[order[q]] = ks.reduce((s, k) => s + leaves[k], 0); }
  const span = new Array<number>(n).fill(2 * Math.PI), start = new Array<number>(n).fill(-Math.PI / 2);
  for (const v of order) {
    let a = start[v];
    for (const k of kids[v]) {
      start[k] = a; span[k] = (span[v] * leaves[k]) / leaves[v]; ang[k] = a + span[k] / 2; a += span[k];
    }
  }
  const maxD = Math.max(...depth), diag: number[] = new Array<number>(maxD + 1).fill(0), rings: number[][] = Array.from({ length: maxD + 1 }, () => []);
  for (const v of order) { diag[depth[v]] = Math.max(diag[depth[v]], Math.hypot(boxes[v].w, boxes[v].h)); rings[depth[v]].push(ang[v]); }
  const rad: number[] = [0];
  for (let d = 1; d <= maxD; d++) {
    let r = rad[d - 1] + (diag[d - 1] + diag[d]) / 2 + GAP_X;
    const a = rings[d].sort((p, q) => p - q);
    if (a.length > 1) {
      let dmin = 2 * Math.PI - a[a.length - 1] + a[0];
      for (let k = 1; k < a.length; k++) dmin = Math.min(dmin, a[k] - a[k - 1]);
      r = Math.max(r, (diag[d] + GAP_X) / (2 * Math.sin(Math.max(1e-6, Math.min(dmin, Math.PI)) / 2)));
    }
    rad[d] = Math.min(MAX_R, r);
  }
  for (const v of order) {
    const r = rad[depth[v]];
    boxes[v].x = r * Math.cos(ang[v]) - boxes[v].w / 2;
    boxes[v].y = r * Math.sin(ang[v]) - boxes[v].h / 2;
  }
}

/** Ordnet ein Netz an. Wirft nie; unbrauchbare Knoten (ohne id, doppelte id) und Kanten ins Leere fallen weg. */
export function layoutNet(form: NetForm, knoten: readonly NetNode[], kanten: readonly NetEdge[], opts: LayoutOpts = {}): NetLayout {
  try {
    const charW = num(opts.charW, 7.2, 1, 100), lineH = num(opts.lineH, 18, 1, 200);
    const maxChars = Math.round(num(opts.maxChars, 24, 4, 200)), maxLines = Math.round(num(opts.maxLines, 8, 1, 50));
    const boxes: NetBox[] = [], ids = new Map<string, number>();
    for (const k of Array.isArray(knoten) ? knoten.slice(0, MAX_NODES) : []) {
      if (!k || typeof k.id !== "string" || ids.has(k.id)) continue;
      const lines = wrapText(k.text, maxChars, maxLines);
      const art: NetArt = ARTS.includes(k.art as NetArt) ? (k.art as NetArt) : "schritt";
      const wide = art === "entscheidung" ? 1.3 : 1;
      const w = Math.max(MIN_W, Math.max(...lines.map((l) => l.length)) * charW + 2 * PAD_X) * wide;
      ids.set(k.id, boxes.length);
      boxes.push({ id: k.id, x: 0, y: 0, w, h: (lines.length * lineH + 2 * PAD_Y) * wide, lines, art });
    }
    const edges: E[] = [];
    (Array.isArray(kanten) ? kanten.slice(0, MAX_EDGES) : []).forEach((e, i) => {
      const a = e ? ids.get(e.von) : undefined, b = e ? ids.get(e.bis) : undefined;
      if (a !== undefined && b !== undefined) edges.push({ i, a, b, text: typeof e.text === "string" ? e.text.slice(0, MAX_TEXT) : "" });
    });
    const back = new Array<boolean>(edges.length).fill(false);
    const f = forest(boxes.length, edges);
    if (form === "baum") layoutBaum(boxes, f);
    else if (form === "mindmap") layoutMindmap(boxes, f);
    else layoutAblauf(boxes, edges, back);
    const tree = new Set<number>();
    const lines: NetLine[] = edges.map((e, j) => {
      const A = boxes[e.a], B = boxes[e.b];
      let pts: Pt[];
      if (e.a === e.b) {
        const x = A.x + A.w, y1 = A.y + A.h * 0.3, y2 = A.y + A.h * 0.7;
        pts = [[x, y1], [x + 20, y1], [x + 20, y2], [x, y2]];
      } else if (form === "baum" && f.parent[e.b] === e.a && !tree.has(e.b)) {
        tree.add(e.b);
        const px = A.x + A.w / 2, qx = B.x + B.w / 2, mid = (A.y + A.h + B.y) / 2;
        pts = [[px, A.y + A.h], [px, mid], [qx, mid], [qx, B.y]];
      } else {
        pts = [borderPoint(A, B.x + B.w / 2, B.y + B.h / 2), borderPoint(B, A.x + A.w / 2, A.y + A.h / 2)];
      }
      const m = e.a === e.b ? ([A.x + A.w + 24, A.y + A.h / 2] as Pt) : polyMid(pts);
      return { index: e.i, von: A.id, bis: B.id, points: pts, label: e.text ? { x: m[0], y: m[1], text: e.text } : null, back: back[j] };
    });
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    const grow = (x: number, y: number) => { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); };
    for (const b of boxes) { grow(b.x, b.y); grow(b.x + b.w, b.y + b.h); }
    for (const l of lines) for (const p of l.points) grow(p[0], p[1]);
    if (!boxes.length) return empty();
    const dx = MARGIN - x0, dy = MARGIN - y0;
    for (const b of boxes) { b.x += dx; b.y += dy; }
    for (const l of lines) {
      l.points = l.points.map(([x, y]) => [x + dx, y + dy] as Pt);
      if (l.label) { l.label.x += dx; l.label.y += dy; }
    }
    const out: NetLayout = { boxes, edges: lines, width: x1 - x0 + 2 * MARGIN, height: y1 - y0 + 2 * MARGIN };
    const finite = (v: number) => Number.isFinite(v);
    const ok = finite(out.width) && finite(out.height) && boxes.every((b) => [b.x, b.y, b.w, b.h].every(finite))
      && lines.every((l) => l.points.every((p) => finite(p[0]) && finite(p[1])) && (!l.label || (finite(l.label.x) && finite(l.label.y))));
    return ok ? out : empty();
  } catch {
    return empty();
  }
}

const empty = (): NetLayout => ({ boxes: [], edges: [], width: 2 * MARGIN, height: 2 * MARGIN });
