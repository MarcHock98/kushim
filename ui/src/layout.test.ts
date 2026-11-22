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
