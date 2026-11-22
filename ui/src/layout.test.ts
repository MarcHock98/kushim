import { describe, expect, it } from "vitest";
import { layoutNet, wrapText, type NetBox, type NetEdge, type NetForm, type NetLayout, type NetNode, type Pt } from "./lib/layout";

// Anordnung für Diagramme `netz` (Plan docs/ui-p6-plan.md, Abschnitt 4, P6b): reine Zahlen, kein DOM.

const node = (id: string, text = id, art?: NetNode["art"]): NetNode => (art ? { id, text, art } : { id, text });
const edge = (von: string, bis: string, text?: string): NetEdge => (text ? { von, bis, text } : { von, bis });

/** Fester Zufall (LCG), damit die großen Fälle in jedem Lauf gleich sind. */
function rng(seed: number) {
  let s = seed >>> 0;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 2 ** 32; };
}

function bigTree(n = 60, seed = 7): { knoten: NetNode[]; kanten: NetEdge[] } {
  const r = rng(seed), knoten = [node("n0", "Wurzel")], kanten: NetEdge[] = [];
  for (let i = 1; i < n; i++) {
    knoten.push(node(`n${i}`, `Knoten ${i}${i % 5 === 0 ? " mit etwas längerem Text" : ""}`));
    kanten.push(edge(`n${Math.floor(r() * i)}`, `n${i}`));
  }
  return { knoten, kanten };
}

function bigDag(n = 60, m = 120, seed = 3): { knoten: NetNode[]; kanten: NetEdge[] } {
  const r = rng(seed), knoten = Array.from({ length: n }, (_, i) => node(`a${i}`, `Schritt ${i}`, i === 0 ? "start" : i % 7 === 0 ? "entscheidung" : undefined));
  const kanten: NetEdge[] = [];
  for (let i = 1; i < n; i++) kanten.push(edge(`a${Math.floor(r() * i)}`, `a${i}`));
  while (kanten.length < m) {
    const a = Math.floor(r() * n), b = Math.floor(r() * n);
    if (a < b) kanten.push(edge(`a${a}`, `a${b}`, kanten.length % 9 === 0 ? "ja" : undefined));
  }
  return { knoten, kanten };
}

function overlaps(a: NetBox, b: NetBox): boolean {
  const e = 0.01;
  return a.x < b.x + b.w - e && b.x < a.x + a.w - e && a.y < b.y + b.h - e && b.y < a.y + a.h - e;
}

function onBorder([x, y]: Pt, b: NetBox): boolean {
  const inside = x >= b.x - 1 && x <= b.x + b.w + 1 && y >= b.y - 1 && y <= b.y + b.h + 1;
  const d = Math.min(Math.abs(x - b.x), Math.abs(x - b.x - b.w), Math.abs(y - b.y), Math.abs(y - b.y - b.h));
  return inside && d <= 1;
}

const byId = (l: NetLayout) => new Map(l.boxes.map((b) => [b.id, b]));

function checkLayout(l: NetLayout): void {
  expect(Number.isFinite(l.width) && Number.isFinite(l.height)).toBe(true);
  for (let i = 0; i < l.boxes.length; i++) {
    const b = l.boxes[i];
    expect([b.x, b.y, b.w, b.h].every(Number.isFinite)).toBe(true);
    expect(b.x).toBeGreaterThanOrEqual(0);
    expect(b.y).toBeGreaterThanOrEqual(0);
    expect(b.x + b.w).toBeLessThanOrEqual(l.width);
    expect(b.y + b.h).toBeLessThanOrEqual(l.height);
    for (let j = i + 1; j < l.boxes.length; j++) expect(overlaps(b, l.boxes[j]), `${b.id} / ${l.boxes[j].id}`).toBe(false);
  }
  const m = byId(l);
  for (const e of l.edges) {
    expect(e.points.length).toBeGreaterThanOrEqual(2);
    expect(e.points.every((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]))).toBe(true);
    expect(onBorder(e.points[0], m.get(e.von)!), `start ${e.von}->${e.bis}`).toBe(true);
    expect(onBorder(e.points[e.points.length - 1], m.get(e.bis)!), `end ${e.von}->${e.bis}`).toBe(true);
    if (e.label) expect(Number.isFinite(e.label.x) && Number.isFinite(e.label.y)).toBe(true);
  }
}

describe("wrapText", () => {
  it("wraps at spaces, breaks long words and caps the line count", () => {
    expect(wrapText("eins zwei drei", 9)).toEqual(["eins zwei", "drei"]);
    expect(wrapText("a".repeat(10), 4)).toEqual(["aaaa", "aaaa", "aa"]);
    expect(wrapText("", 10)).toEqual([""]);
    const many = wrapText("wort ".repeat(100), 10, 3);
    expect(many).toHaveLength(3);
    expect(many[2].endsWith("…")).toBe(true);
  });
});

describe("layoutNet ablauf", () => {
  const small = [node("s", "Start", "start"), node("p", "Prüfen", "entscheidung"), node("j", "Ja"), node("n", "Nein"), node("e", "Ende", "ende")];
  const smallE = [edge("s", "p"), edge("p", "j", "ja"), edge("p", "n", "nein"), edge("j", "e"), edge("n", "e")];

  it("lays out a small flow with targets below their sources", () => {
    const l = layoutNet("ablauf", small, smallE);
    checkLayout(l);
    expect(l.boxes).toHaveLength(5);
    expect(l.edges).toHaveLength(5);
    const m = byId(l);
    for (const e of l.edges) expect(m.get(e.bis)!.y).toBeGreaterThan(m.get(e.von)!.y + m.get(e.von)!.h);
    expect(l.edges.find((e) => e.bis === "j")!.label!.text).toBe("ja");
    expect(l.edges.every((e) => !e.back)).toBe(true);
  });

  it("keeps layers monotonic for an acyclic 60-node, 120-edge flow", () => {
    const { knoten, kanten } = bigDag();
    const l = layoutNet("ablauf", knoten, kanten);
    checkLayout(l);
    expect(l.boxes).toHaveLength(60);
    expect(l.edges).toHaveLength(120);
    const m = byId(l);
    for (const e of l.edges) expect(m.get(e.bis)!.y).toBeGreaterThan(m.get(e.von)!.y);
  });

  it("terminates on cycles, marks back edges and still lays out", () => {
    const l = layoutNet("ablauf", [node("a"), node("b"), node("c"), node("d")], [edge("a", "b"), edge("b", "c"), edge("c", "a"), edge("c", "d"), edge("d", "b")]);
    checkLayout(l);
    expect(l.boxes).toHaveLength(4);
    expect(l.edges.filter((e) => e.back).length).toBeGreaterThanOrEqual(1);
    const pure = layoutNet("ablauf", [node("x"), node("y")], [edge("x", "y"), edge("y", "x")]);
    checkLayout(pure);
    expect(pure.edges.filter((e) => e.back)).toHaveLength(1);
  });

  it("handles several start nodes", () => {
    const l = layoutNet("ablauf", [node("a", "A", "start"), node("b", "B", "start"), node("c")], [edge("a", "c"), edge("b", "c")]);
    checkLayout(l);
    const m = byId(l);
    expect(m.get("a")!.y).toBe(m.get("b")!.y);
  });

  it("finishes 60 nodes and 120 edges fast", () => {
    const { knoten, kanten } = bigDag(60, 120, 11);
    const t = performance.now();
    for (const form of ["ablauf", "baum", "mindmap"] as NetForm[]) layoutNet(form, knoten, kanten);
    expect(performance.now() - t).toBeLessThan(200);
  });
});

describe("layoutNet baum", () => {
  it("centres parents over their children in a small tree", () => {
    const l = layoutNet("baum", [node("r", "Chefin"), node("a", "Abteilung A"), node("b", "B"), node("c", "Abteilung C mit langem Namen"), node("a1", "Team 1")],
      [edge("r", "a"), edge("r", "b"), edge("r", "c"), edge("a", "a1")]);
    checkLayout(l);
    const m = byId(l), cx = (id: string) => m.get(id)!.x + m.get(id)!.w / 2;
    expect(cx("r")).toBeCloseTo((cx("a") + cx("c")) / 2, 6);
    expect(cx("a")).toBeCloseTo(cx("a1"), 6);
    expect(m.get("a")!.y).toBe(m.get("c")!.y);
    expect(m.get("a1")!.y).toBeGreaterThan(m.get("a")!.y + m.get("a")!.h);
    expect(l.edges[0].points).toHaveLength(4);
  });

  it("lays out a 60-node tree without overlap, parents centred", () => {
    const { knoten, kanten } = bigTree();
    const l = layoutNet("baum", knoten, kanten);
    checkLayout(l);
    expect(l.boxes).toHaveLength(60);
    const m = byId(l), cx = (id: string) => m.get(id)!.x + m.get(id)!.w / 2;
    const kids = new Map<string, string[]>();
    for (const e of kanten) kids.set(e.von, [...(kids.get(e.von) ?? []), e.bis]);
    for (const [p, ks] of kids) expect(cx(p)).toBeCloseTo((cx(ks[0]) + cx(ks[ks.length - 1])) / 2, 6);
  });
});

describe("layoutNet mindmap", () => {
  it("puts the root in the middle of a small map", () => {
    const l = layoutNet("mindmap", [node("m", "Thema"), node("a"), node("b"), node("c"), node("d"), node("a1")],
      [edge("m", "a"), edge("m", "b"), edge("m", "c"), edge("m", "d"), edge("a", "a1")]);
    checkLayout(l);
    const m = byId(l), c = (id: string): Pt => [m.get(id)!.x + m.get(id)!.w / 2, m.get(id)!.y + m.get(id)!.h / 2];
    const others = ["a", "b", "c", "d"].map(c), root = c("m");
    const xs = others.map((p) => p[0]), ys = others.map((p) => p[1]);
    expect(Math.min(...xs)).toBeLessThan(root[0]);
    expect(Math.max(...xs)).toBeGreaterThan(root[0]);
    expect(Math.min(...ys)).toBeLessThan(root[1]);
    expect(Math.max(...ys)).toBeGreaterThan(root[1]);
    const dist = (p: Pt) => Math.hypot(p[0] - root[0], p[1] - root[1]);
    expect(dist(c("a1"))).toBeGreaterThan(dist(c("a")));
  });

  it("lays out a 60-node map without overlap", () => {
    for (const seed of [1, 7, 42]) {
      const { knoten, kanten } = bigTree(60, seed);
      const l = layoutNet("mindmap", knoten, kanten);
      checkLayout(l);
      expect(l.boxes).toHaveLength(60);
    }
  });
});

describe("layoutNet robustness", () => {
  it("is deterministic", () => {
    for (const form of ["ablauf", "baum", "mindmap"] as NetForm[]) {
      const { knoten, kanten } = form === "ablauf" ? bigDag() : bigTree();
      expect(layoutNet(form, knoten, kanten)).toEqual(layoutNet(form, knoten.map((k) => ({ ...k })), kanten.map((e) => ({ ...e }))));
    }
  });

  it("returns a safe empty layout for empty or odd input", () => {
    for (const form of ["ablauf", "baum", "mindmap", "quatsch"] as NetForm[]) {
      const l = layoutNet(form, [], []);
      expect(l.boxes).toEqual([]);
      expect(l.width).toBeGreaterThan(0);
      expect(() => layoutNet(form, null as unknown as NetNode[], undefined as unknown as NetEdge[])).not.toThrow();
      expect(() => layoutNet(form, [null, { id: 3 }] as unknown as NetNode[], [null] as unknown as NetEdge[])).not.toThrow();
    }
  });

  it("drops unknown edge ids and duplicate ids, keeps self loops on the border", () => {
    for (const form of ["ablauf", "baum", "mindmap"] as NetForm[]) {
      const l = layoutNet(form, [node("a"), node("a", "doppelt"), node("b")], [edge("a", "zz"), edge("a", "b"), edge("b", "b", "nochmal")]);
      checkLayout(l);
      expect(l.boxes.map((b) => b.id)).toEqual(["a", "b"]);
      expect(l.boxes[0].lines).toEqual(["a"]);
      expect(l.edges.map((e) => e.index)).toEqual([1, 2]);
      expect(l.edges[1].label!.text).toBe("nochmal");
    }
  });

  it("lays out a tree form that has cycles or several roots", () => {
    for (const form of ["baum", "mindmap"] as NetForm[]) {
      checkLayout(layoutNet(form, [node("a"), node("b"), node("c")], [edge("a", "b"), edge("b", "c"), edge("c", "a")]));
      checkLayout(layoutNet(form, [node("a"), node("b"), node("c"), node("d")], [edge("a", "b"), edge("c", "d")]));
    }
  });

  it("wraps long texts into taller boxes", () => {
    const short = layoutNet("ablauf", [node("a", "kurz")], []).boxes[0];
    const long = layoutNet("ablauf", [node("a", "ein sehr langer Text, der über mehrere Zeilen umbrechen muss, damit er passt")], []).boxes[0];
    expect(long.lines.length).toBeGreaterThan(1);
    expect(long.h).toBeGreaterThan(short.h);
    expect(long.lines.every((s) => s.length <= 24)).toBe(true);
  });
});

const FORMS: NetForm[] = ["ablauf", "baum", "mindmap"];
const TEXT80 = "abcdefg ".repeat(10);
const star = (n: number, text: (i: number) => string, art?: (i: number) => NetNode["art"]) => ({
  knoten: Array.from({ length: n }, (_, i) => node(`s${i}`, text(i), art?.(i))),
  kanten: Array.from({ length: n - 1 }, (_, i) => edge("s0", `s${i + 1}`)),
});
const chain = (n: number) => ({
  knoten: Array.from({ length: n }, (_, i) => node(`c${i}`, `Glied ${i}`)),
  kanten: Array.from({ length: n - 1 }, (_, i) => edge(`c${i}`, `c${i + 1}`)),
});

describe("layoutNet extreme shapes", () => {
  it("lays out a star with 59 children in every form", () => {
    for (const form of FORMS) {
      const { knoten, kanten } = star(60, (i) => `Ast ${i}`);
      const l = layoutNet(form, knoten, kanten);
      checkLayout(l);
      expect(l.boxes).toHaveLength(60);
      expect(l.edges).toHaveLength(59);
    }
  });

  it("lays out a chain of depth 60 in every form", () => {
    for (const form of FORMS) {
      const { knoten, kanten } = chain(60);
      const l = layoutNet(form, knoten, kanten);
      checkLayout(l);
      expect(l.boxes).toHaveLength(60);
    }
  });

  it("lays out 80-character texts in every node (star, tree, flow)", () => {
    for (const form of FORMS) {
      checkLayout(layoutNet(form, star(60, () => TEXT80).knoten, star(60, () => TEXT80).kanten));
      const t = bigTree(60, 5), d = bigDag(60, 120, 5);
      checkLayout(layoutNet(form, t.knoten.map((k) => ({ ...k, text: TEXT80 })), t.kanten));
      checkLayout(layoutNet(form, d.knoten.map((k) => ({ ...k, text: TEXT80 })), d.kanten));
    }
  });

  it("lays out texts that fill all 8 lines", () => {
    const long = "Wort ".repeat(80);
    for (const form of FORMS) {
      const { knoten, kanten } = bigTree(60, 9);
      const l = layoutNet(form, knoten.map((k) => ({ ...k, text: long })), kanten);
      checkLayout(l);
      expect(l.boxes.every((b) => b.lines.length === 8 && b.lines[7].endsWith("…"))).toBe(true);
    }
  });

  it("keeps enlarged entscheidung boxes apart in baum and mindmap", () => {
    for (const form of ["baum", "mindmap"] as NetForm[]) {
      const s = star(60, (i) => (i % 2 ? TEXT80 : `E ${i}`), (i) => (i % 2 ? "schritt" : "entscheidung"));
      checkLayout(layoutNet(form, s.knoten, s.kanten));
      const t = bigTree(60, 13);
      const l = layoutNet(form, t.knoten.map((k, i) => ({ ...k, art: i % 3 === 0 ? "entscheidung" as const : undefined })), t.kanten);
      checkLayout(l);
      const dec = l.boxes.find((b) => b.art === "entscheidung" && b.lines.length === 1)!;
      expect(dec.h).toBeCloseTo((18 + 16) * 1.3, 6);
    }
  });

  // Gemessene Größe des breitesten Falls (60er-Stern, 80 Zeichen je Knoten), damit die Komponente weiß, dass sie auf die
  // Breite einpassen muss. Gemessen mit Standardmaßen: ablauf 12842 x 256, baum 12842 x 256, mindmap 4674 x 4570 Pixel.
  it("records the size of the widest case: a 60-star with 80-character texts (about 12842 x 256, mindmap 4674 x 4570) needs fit-to-width", () => {
    const s = star(60, () => TEXT80);
    for (const form of FORMS) {
      const l = layoutNet(form, s.knoten, s.kanten);
      expect(l.width).toBeGreaterThan(2000);
      expect(Math.max(l.width, l.height)).toBeLessThan(20000);
    }
  });
});

/** Eigene Prüfung (nicht die aus layout.ts): schneidet die Strecke das Innere des Kastens (1 px Rand zählt nicht)? */
function cuts([x1, y1]: Pt, [x2, y2]: Pt, b: NetBox): boolean {
  const x0 = b.x + 1, xa = b.x + b.w - 1, y0 = b.y + 1, ya = b.y + b.h - 1, dx = x2 - x1, dy = y2 - y1;
  let t0 = 0, t1 = 1;
  for (const [p, q] of [[-dx, x1 - x0], [dx, xa - x1], [-dy, y1 - y0], [dy, ya - y1]]) {
    if (p === 0) { if (q < 0) return false; continue; }
    const t = q / p;
    if (p < 0) { if (t > t1) return false; t0 = Math.max(t0, t); } else { if (t < t0) return false; t1 = Math.min(t1, t); }
  }
  return t0 < t1;
}
/** Zahl der Paare (Kante, fremder Kasten), bei denen die Linie durch den Kasten läuft. */
const crossingCount = (l: NetLayout) => l.edges.reduce((n, e) => n + l.boxes.filter((b) => b.id !== e.von && b.id !== e.bis
  && e.points.some((p, k) => k > 0 && cuts(e.points[k - 1], p, b))).length, 0);
/** Beschriftungen, die einen Kasten berühren; Größe selbst geschätzt wie in der Komponente (7,2 px je Zeichen + 8, 18 hoch). */
const labelOnBox = (l: NetLayout) => l.edges.flatMap((e) => {
  if (!e.label) return [];
  const w = e.label.text.length * 7.2 + 8, h = 18, r = { x: e.label.x - w / 2, y: e.label.y - h / 2, w, h };
  expect(e.label.w).toBeCloseTo(w, 6);
  expect(e.label.h).toBe(h);
  return l.boxes.filter((b) => overlaps(r as NetBox, b)).map((b) => `${e.von}->${e.bis} "${e.label!.text}" on ${b.id}`);
});
/** Zufälliger Ablauf mit Sprüngen über Schichten (bigDag) und Rückwärtskanten mit Beschriftung. */
function flowWithBack(seed: number, n = 60, m = 120) {
  const d = bigDag(n, m - 20, seed), r = rng(seed + 100);
  while (d.kanten.length < m) {
    const a = Math.floor(r() * n), b = Math.floor(r() * n);
    if (a > b) d.kanten.push(edge(`a${a}`, `a${b}`, d.kanten.length % 2 ? "zurück" : "noch einmal prüfen"));
  }
  return d;
}
const DEMO_FLOW = {
  knoten: [node("s", "Bestellung eingegangen", "start"), node("p", "Ware auf Lager?", "entscheidung"), node("v", "Ware versenden", "schritt"),
    node("n", "Ware nachbestellen", "schritt"), node("w", "Lieferung abwarten"), node("r", "Rechnung schicken", "schritt"), node("e", "Fertig", "ende")],
  kanten: [edge("s", "p"), edge("p", "v", "ja"), edge("p", "n", "nein"), edge("n", "w"), edge("w", "p", "erneut prüfen"), edge("v", "r"), edge("r", "e")],
};

describe("layoutNet routing and labels", () => {
  it("demo flow: the back edge goes around the reorder node, no edge crosses a third box, no label covers a box", () => {
    const l = layoutNet("ablauf", DEMO_FLOW.knoten, DEMO_FLOW.kanten);
    checkLayout(l);
    expect(crossingCount(l)).toBe(0);
    expect(labelOnBox(l)).toEqual([]);
    const backEdge = l.edges.find((e) => e.von === "w" && e.bis === "p")!;
    expect(backEdge.back).toBe(true);
    expect(backEdge.points.length).toBeGreaterThan(2);
    const n = byId(l).get("n")!;
    for (let k = 1; k < backEdge.points.length; k++) expect(cuts(backEdge.points[k - 1], backEdge.points[k], n)).toBe(false);
    const [p, q] = backEdge.points.slice(-2);                                               // letzter Abschnitt senkrecht in die Raute
    expect(p[0]).toBeCloseTo(q[0], 6);
    expect(q[1]).toBeCloseTo(byId(l).get("p")!.y + byId(l).get("p")!.h, 6);
  });

  it("random flows with back edges and layer-skipping edges: no label covers a box, crossings do not grow", () => {
    // Vor der Umleitung gemessen (Kante x fremder Kasten): bigDag 60/120 Seed 3: 169, Seed 11: 161; mit Rückwärtskanten Seed 1: 189, Seed 2: 295.
    const before: [string, NetLayout, number][] = [
      ["dag3", layoutNet("ablauf", bigDag().knoten, bigDag().kanten), 169],
      ["dag11", layoutNet("ablauf", bigDag(60, 120, 11).knoten, bigDag(60, 120, 11).kanten), 161],
      ["back1", layoutNet("ablauf", flowWithBack(1).knoten, flowWithBack(1).kanten), 189],
      ["back2", layoutNet("ablauf", flowWithBack(2).knoten, flowWithBack(2).kanten), 295]];
    for (const [name, l, old] of before) {
      checkLayout(l);
      expect(l.edges).toHaveLength(120);
      expect(crossingCount(l), name).toBeLessThanOrEqual(old);
      expect(labelOnBox(l), name).toEqual([]);
    }
    for (const seed of [4, 5, 6, 7, 8, 9]) {
      const d = flowWithBack(seed), l = layoutNet("ablauf", d.knoten, d.kanten);
      checkLayout(l);
      expect(labelOnBox(l), `seed ${seed}`).toEqual([]);
      expect(l.edges.some((e) => e.back)).toBe(true);
    }
  });

  it("labels avoid boxes in every form, also on self loops and with very long texts", () => {
    for (const form of FORMS) {
      const t = bigTree(60, 21);
      const l = layoutNet(form, t.knoten, t.kanten.map((e, i) => ({ ...e, text: i % 2 ? "Teil von" : "gehört zu Abteilung" })));
      checkLayout(l);
      expect(labelOnBox(l), form).toEqual([]);
      const self = layoutNet(form, [node("a", "Wiederholen"), node("b")], [edge("a", "a", "nochmal"), edge("a", "b", "x".repeat(400))]);
      checkLayout(self);
      expect(labelOnBox(self), form).toEqual([]);
    }
  });

  it("labels mostly avoid each other in the demo and a small flow", () => {
    for (const l of [layoutNet("ablauf", DEMO_FLOW.knoten, DEMO_FLOW.kanten),
      layoutNet("ablauf", [node("p", "Prüfen", "entscheidung"), node("a"), node("b"), node("c")], [edge("p", "a", "ja"), edge("p", "b", "nein"), edge("p", "c", "vielleicht")])]) {
      const rs = l.edges.filter((e) => e.label).map((e) => ({ x: e.label!.x - e.label!.w / 2, y: e.label!.y - e.label!.h / 2, w: e.label!.w, h: e.label!.h }) as NetBox);
      for (let i = 0; i < rs.length; i++) for (let j = i + 1; j < rs.length; j++) expect(overlaps(rs[i], rs[j])).toBe(false);
    }
  });
});

describe("layoutNet hostile input", () => {
  it("caps 5000 nodes and 20000 edges to 200 and 400 and returns fast", () => {
    const knoten = Array.from({ length: 5000 }, (_, i) => node(`h${i}`, `Knoten ${i}`));
    const kanten = Array.from({ length: 20000 }, (_, i) => edge(`h${i % 5000}`, `h${(i * 7 + 1) % 5000}`));
    for (const form of FORMS) {
      const t = performance.now();
      const l = layoutNet(form, knoten, kanten);
      expect(performance.now() - t).toBeLessThan(1000);
      expect(l.boxes).toHaveLength(200);
      expect(l.edges.length).toBeLessThanOrEqual(400);
      checkLayout(l);
    }
  });

  it("accepts non-string texts, prototype-like ids and broken opts", () => {
    const knoten = [
      { id: "__proto__", text: 42 }, { id: "constructor", text: null }, { id: "toString", text: { a: 1 } }, { id: "x" },
    ] as unknown as NetNode[];
    const kanten = [edge("__proto__", "constructor"), edge("constructor", "toString"), edge("__proto__", "x"), { von: "x", bis: "__proto__", text: 5 }] as unknown as NetEdge[];
    const bad = [{ charW: NaN, lineH: -5, maxChars: -1, maxLines: NaN }, { charW: -1, lineH: Infinity, maxChars: NaN, maxLines: -3 }];
    for (const form of FORMS) for (const opts of bad) {
      let l: NetLayout | undefined;
      expect(() => { l = layoutNet(form, knoten, kanten, opts); }).not.toThrow();
      checkLayout(l!);
      expect(l!.boxes.map((b) => b.id)).toEqual(["__proto__", "constructor", "toString", "x"]);
      expect(l!.boxes[0].lines).toEqual(["42"]);
      expect(l!.boxes.every((b) => b.w > 0 && b.h > 0)).toBe(true);
    }
  });
});
