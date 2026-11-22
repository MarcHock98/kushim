import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import * as THREE from "three";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { AtomShells, dotRadius, electronPositions } from "./components/stage/AtomShells";
import { Molecule3D } from "./components/stage/Molecule3D";
import { ViewCard } from "./components/stage/ViewCard";
import { ApiClient } from "./lib/api";
import { STATE_VIEW } from "./lib/avatarState";
import { atomModell, molekuelGeometrie, normalizeTeilchen, orbitalPunkte, type OrbitalConfig } from "./lib/chem";
import { DEMO_VIEWS, MockSocket, TEILCHEN_DEMOS } from "./lib/mock";
import { ART_LABEL, parseItem, type Block, type TeilchenBlock, type View } from "./lib/stage";

// P5b (docs/ui-p5-plan.md, Abschnitt 7): Baustein `teilchen` mit Molekül, Schalenmodell und Orbital-Wolke. jsdom kennt kein WebGL:
// three.js bekommt hier einen falschen Renderer, der jedes Bild mitzählt (Zeichenaufrufe = sichtbare Netze, Punkte und Linien), sonst
// bleibt three.js echt. Kernregeln: ungültig heißt nur ein Hinweis und kein WebGL-Kontext; Texte aus den Daten bleiben DOM-Text;
// Bedienen sendet nichts; alles wird freigegeben.

interface Fake {
  canvas: HTMLCanvasElement; renders: number; calls: number; disposed: boolean; lost: boolean;
  objects: THREE.Object3D[]; geometries: Set<THREE.BufferGeometry>; materials: Set<THREE.Material>; eyes: number[][];
}
const R = vi.hoisted(() => ({ list: [] as unknown[] }));

vi.mock("three", async (orig) => {
  const T = await orig<typeof import("three")>();
  class FakeRenderer {
    canvas: HTMLCanvasElement; renders = 0; calls = 0; disposed = false; lost = false;
    objects: THREE.Object3D[] = []; geometries = new Set<THREE.BufferGeometry>(); materials = new Set<THREE.Material>(); eyes: number[][] = [];
    constructor(o: { canvas: HTMLCanvasElement }) { this.canvas = o.canvas; R.list.push(this); }
    setPixelRatio() {}
    setSize() {}
    render(scene: THREE.Scene, cam: THREE.Camera) {
      this.renders++;
      this.eyes.push(cam.position.toArray());
      let n = 0;
      this.objects = [];
      scene.traverseVisible((o) => {
        this.objects.push(o);
        const x = o as unknown as { isMesh?: boolean; isPoints?: boolean; isLine?: boolean; geometry?: THREE.BufferGeometry; material?: THREE.Material };
        if (x.isMesh || x.isPoints || x.isLine) {
          n++;
          if (x.geometry) this.geometries.add(x.geometry);
          if (x.material) this.materials.add(x.material);
        }
      });
      this.calls = n;
    }
    dispose() { this.disposed = true; }
    forceContextLoss() { this.lost = true; }
  }
  return { ...T, WebGLRenderer: FakeRenderer };
});

vi.mock("./lib/chem", async (orig) => {
  const m = await orig<typeof import("./lib/chem")>();
  return { ...m, orbitalPunkte: vi.fn(m.orbitalPunkte), atomModell: vi.fn(m.atomModell), molekuelGeometrie: vi.fn(m.molekuelGeometrie) };
});

const TOKEN = "t".repeat(43);
afterEach(() => {
  cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); R.list.length = 0;
  for (const f of [orbitalPunkte, atomModell, molekuelGeometrie]) vi.mocked(f).mockClear();
});

const fakes = () => (R.list as Fake[]).filter((r) => r.canvas.classList.contains("m-canvas"));
/** Falscher Bildtakt: `flush` gibt alle bestellten Bilder aus. */
function frames() {
  const q = new Map<number, FrameRequestCallback>();
  let id = 0;
  const raf = vi.fn((cb: FrameRequestCallback) => { q.set(++id, cb); return id; });
  vi.stubGlobal("requestAnimationFrame", raf);
  vi.stubGlobal("cancelAnimationFrame", vi.fn((i: number) => { q.delete(i); }));
  return { raf, pending: () => q.size, flush: () => act(() => { const cbs = [...q.values()]; q.clear(); for (const cb of cbs) cb(performance.now()); }) };
}
const withWebGL = () => vi.stubGlobal("WebGLRenderingContext", class {});

const view = (bausteine: Block[], extra: Partial<View> = {}): View => ({ seq: 1, id: "t1", art: "teilchen", titel: "Titel", stand: "", bausteine, ...extra });
const cardEl = (b: Block | Block[], extra: Partial<View> = {}) =>
  <ViewCard view={view(Array.isArray(b) ? b : [b], extra)} sys={null} sysNo={false} onClose={() => undefined} />;
const card = (b: Block | Block[], extra: Partial<View> = {}) => render(cardEl(b, extra));
const tb = (x: Record<string, unknown>) => ({ typ: "teilchen", ...x }) as unknown as TeilchenBlock;

const demo = (id: string) => TEILCHEN_DEMOS.find((v) => v.id === id)!;
const demoBlock = (id: string) => (demo(id).bausteine as Block[])[0];
const WATER = demoBlock("wasser"), ETHANOL = demoBlock("ethanol"), SODIUM = demoBlock("natrium"), ORBITAL = demoBlock("orbital-2pz");
const NOT_SHOWN = "Teilchen kann nicht gezeigt werden.";

async function mountGl(b: Block | Block[], n = 1) {
  const f = frames();
  withWebGL();
  const r = card(b);
  await waitFor(() => expect(fakes()).toHaveLength(n));
  f.flush();
  return { ...r, f };
}
const instanced = (fk: Fake, geo: string) => fk.objects.filter((o) => (o as THREE.InstancedMesh).isInstancedMesh
  && (o as THREE.InstancedMesh).geometry.type === geo) as THREE.InstancedMesh[];
const count = (ms: THREE.InstancedMesh[]) => ms.reduce((s, m) => s + m.count, 0);

/** 300 Atome in einem Gitter (Abstand 1,1 Å), vier Elemente; Bindungen aus Abständen (jedes Element hat welche). */
function bigMolecule(): TeilchenBlock {
  const els = ["C", "H", "O", "N"], atome = [];
  for (let i = 0; i < 300; i++) atome.push({ element: els[i % 4], position: [(i % 10) * 1.1, (Math.floor(i / 10) % 10) * 1.1, Math.floor(i / 100) * 1.1] });
  return tb({ form: "molekuel", name: "Gitter", atome, bindungen: [], beschriftungen: [], darstellung: "kugel-stab" });
}

describe("Molekül", () => {
  it("Wasser: Summenformel H2O, 3 Atome, 2 Bindungen, Beschreibung, Elemente als Text, Atomliste", async () => {
    const { f } = await mountGl(WATER);
    const s = screen.getByRole("region", { name: "Molekül" });
    expect(within(s).getByText("H2O")).toBeInTheDocument();
    expect(within(s).getByText("3 Atome")).toBeInTheDocument();
    expect(within(s).getByText("2 Bindungen")).toBeInTheDocument();
    expect(within(s).queryByText("Bindungen aus Abständen berechnet")).toBeNull();     // Bindungen sind angegeben
    expect(within(s).getByText("Molekül Wasser, Summenformel H2O, 3 Atome, 2 Bindungen.")).toBeInTheDocument();
    const legend = within(s).getByRole("list", { name: "Elemente" });                   // Symbol immer als Text, nie nur Farbe
    expect(legend.textContent).toMatch(/O Sauerstoff, 1×, Farbe Rot/);
    expect(legend.textContent).toMatch(/H Wasserstoff, 2×, Farbe Weiß/);
    expect(within(s).getByText("Sauerstoff, leicht negativ", { selector: ".t-labels *" })).toBeInTheDocument();
    expect(within(s).getAllByRole("row")).toHaveLength(4);                             // Kopf und drei Atome
    expect(within(s).getByText("Atomliste (3)")).toBeInTheDocument();
    expect(within(s).queryByText(/angepasst/)).toBeNull();
    const fk = fakes()[0];
    expect(fk.renders).toBe(1);
    expect(count(instanced(fk, "SphereGeometry"))).toBe(3);
    expect(count(instanced(fk, "CylinderGeometry"))).toBe(4);                          // 2 Bindungen, je zwei Hälften
    expect(fk.calls).toBe(4);                                                          // Kugeln Rot und Weiß, Stäbe Rot und Weiß
    f.flush();
    expect(fk.renders).toBe(1);                                                        // kein Dauertakt
    expect(f.pending()).toBe(0);
  });

  it("Ethanol ohne Bindungen: „Bindungen aus Abständen berechnet“ und 8 Bindungen", async () => {
    await mountGl(ETHANOL);
    expect(screen.getByText("Bindungen aus Abständen berechnet")).toBeInTheDocument();
    expect(screen.getByText("C2H6O")).toBeInTheDocument();
    expect(screen.getByText("9 Atome")).toBeInTheDocument();
    expect(screen.getByText("8 Bindungen")).toBeInTheDocument();
    expect(count(instanced(fakes()[0], "CylinderGeometry"))).toBe(16);
  });

  it("Doppel- und Dreifachbindungen: zwei bzw. drei parallele Zylinder je Hälfte und in Worten", async () => {
    await mountGl(tb({ form: "molekuel", name: "", darstellung: "kugel-stab", beschriftungen: [],
      atome: [{ element: "O", position: [-1.16, 0, 0] }, { element: "C", position: [0, 0, 0] }, { element: "O", position: [1.16, 0, 0] },
        { element: "N", position: [0, 3, 0] }, { element: "N", position: [1.1, 3, 0] }],
      bindungen: [{ von: 0, bis: 1, ordnung: 2 }, { von: 1, bis: 2, ordnung: 2 }, { von: 3, bis: 4, ordnung: 3 }] }));
    expect(screen.getByText(/3 Bindungen \(davon 2 Doppelbindungen, 1 Dreifachbindung\)/)).toBeInTheDocument();
    const rods = instanced(fakes()[0], "CylinderGeometry");
    expect(count(rods)).toBe(2 * 2 * 2 + 3 * 2);
    const m = new THREE.Matrix4(), p = new THREE.Vector3(), q = new THREE.Quaternion(), s = new THREE.Vector3();
    const red = rods.find((r) => r.count === 4)!;                                      // Hälften an den Sauerstoffen: parallel versetzt
    const ys = [0, 1, 2, 3].map((i) => { red.getMatrixAt(i, m); m.decompose(p, q, s); return Math.round(p.y * 1000); });
    expect(new Set(ys).size).toBe(2);
  });

  it("Kalotte: Kugeln in Van-der-Waals-Größe, keine Stäbe, ein Hinweis", async () => {
    await mountGl({ ...WATER, darstellung: "kalotte" } as Block);
    const fk = fakes()[0];
    expect(instanced(fk, "CylinderGeometry")).toHaveLength(0);
    expect(fk.calls).toBe(2);
    expect(screen.getByText(/Kalottenmodell/)).toBeInTheDocument();
  });

  it("300 Atome: höchstens zwei Zeichenaufrufe je Palettenfarbe (hier 8), alle Atome als Instanzen", async () => {
    await mountGl(bigMolecule());
    const fk = fakes()[0];
    expect(count(instanced(fk, "SphereGeometry"))).toBe(300);
    expect(instanced(fk, "SphereGeometry")).toHaveLength(4);
    expect(fk.calls).toBe(8);
    expect(fk.calls).toBeLessThanOrEqual(14);
    expect(screen.getByText("300 Atome")).toBeInTheDocument();
  });

  it("Drehen per Knopf, Taste, Ziehen und Rad zeichnet genau einmal neu; Tasten mit Strg, Alt oder Meta bleiben beim Browser", async () => {
    const { f } = await mountGl(WATER);
    const fk = fakes()[0], stage = document.querySelector(".m-stage")!;
    fireEvent.click(screen.getByRole("button", { name: "Links drehen" }));
    fireEvent.click(screen.getByRole("button", { name: "Näher" }));                   // zwei Klicks, ein Bild
    f.flush();
    expect(fk.renders).toBe(2);
    expect(fireEvent.keyDown(stage, { key: "ArrowRight" })).toBe(false);
    f.flush();
    expect(fk.renders).toBe(3);
    for (const [key, mod] of [["+", "ctrlKey"], ["-", "ctrlKey"], ["0", "ctrlKey"], ["ArrowLeft", "altKey"], ["ArrowUp", "metaKey"], ["Home", "altKey"]] as const) {
      expect(fireEvent.keyDown(stage, { key, [mod]: true }), `${mod}+${key}`).toBe(true);
    }
    expect(fireEvent.keyDown(stage, { key: "x" })).toBe(true);
    f.flush();
    expect(fk.renders).toBe(3);
    const c = fk.canvas;
    fireEvent.pointerDown(c, { clientX: 10, clientY: 10, pointerId: 1 });
    fireEvent.pointerMove(c, { clientX: 40, clientY: 20, pointerId: 1 });
    fireEvent.pointerUp(c, { pointerId: 1 });
    fireEvent.pointerMove(c, { clientX: 90, clientY: 90, pointerId: 1 });             // nach dem Loslassen: nichts
    f.flush();
    expect(fk.renders).toBe(4);
    fireEvent.wheel(c, { deltaY: -100 });
    f.flush();
    expect(fk.renders).toBe(5);
  });

  it("verdecktes Fenster: kein Bild, danach genau eins", async () => {
    let hidden = false;
    Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
    try {
      const { f } = await mountGl(WATER);
      const fk = fakes()[0];
      hidden = true;
      fireEvent.click(screen.getByRole("button", { name: "Rechts drehen" }));
      f.flush();
      expect(fk.renders).toBe(1);
      hidden = false;
      act(() => { document.dispatchEvent(new Event("visibilitychange")); });
      f.flush();
      expect(fk.renders).toBe(2);
    } finally {
      delete (document as unknown as { hidden?: boolean }).hidden;
    }
  });

  it("ohne WebGL: Hinweis, offene Atomliste, kein Canvas, kein Renderer", () => {
    frames();
    card(ETHANOL);
    expect(screen.getByText(/3D braucht WebGL/)).toBeInTheDocument();
    expect(document.querySelector(".v-teilchen canvas")).toBeNull();
    expect(document.querySelector("details.m-list")).toHaveAttribute("open");
    expect(screen.getAllByRole("row")).toHaveLength(10);
    expect(screen.getByText("8 Bindungen")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Links drehen" })).toBeNull();
    expect(R.list).toHaveLength(0);
  });
});

describe("Schalenmodell", () => {
  it("Natrium: Kern mit Na, 11 p, 12 n; Schalen 2, 8, 1 als 11 Punkte auf 3 Ringen; statisch; Ladung in Worten", () => {
    const raf = frames().raf;
    card(SODIUM);
    const s = screen.getByRole("region", { name: "Atom" });
    expect(within(s).getByText("Vereinfachtes Schalenmodell")).toBeInTheDocument();
    const svg = s.querySelector("svg")!;
    expect(svg.querySelectorAll(".a-shell")).toHaveLength(3);
    expect(svg.querySelectorAll(".a-electron")).toHaveLength(11);
    expect([...svg.querySelectorAll(".a-shell-group")].map((g) => g.querySelectorAll(".a-electron").length)).toEqual([2, 8, 1]);
    expect([...svg.querySelectorAll("text")].map((t) => t.textContent)).toEqual(["Na", "11 p", "12 n"]);
    expect(within(s).getByText("Ladung: elektrisch neutral")).toBeInTheDocument();
    expect(within(s).getByText("Massenzahl 23")).toBeInTheDocument();
    expect(within(s).getByText("Natrium, 11 Protonen, 12 Neutronen, 11 Elektronen in den Schalen 2, 8, 1. Vereinfachtes Schalenmodell.")).toBeInTheDocument();
    expect(svg.querySelector("animate, animateTransform, animateMotion")).toBeNull();
    expect(raf).not.toHaveBeenCalled();
    expect(svg.outerHTML).not.toMatch(/NaN|Infinity/);
    expect(R.list).toHaveLength(0);                                                    // kein WebGL für das Schalenmodell
  });

  it("Ion: Ladung in Worten, unbekannte Neutronen ehrlich als unbekannt", () => {
    card(tb({ form: "atom", element: "Cl", neutronen: -1, ladung: -1, schalen: [2, 8, 8] }));
    expect(screen.getByText("Ladung: einfach negativ geladen")).toBeInTheDocument();
    expect(screen.getByText("n ?")).toBeInTheDocument();
    expect(screen.getByText(/Neutronenzahl nicht angegeben/)).toBeInTheDocument();
    expect(screen.queryByText(/Massenzahl/)).toBeNull();
  });

  it("leere Schalen bleiben als Ring ohne Punkte; eine einzelne Schale geht auch", () => {
    const v = card(tb({ form: "atom", element: "Na", neutronen: 12, ladung: 0, schalen: [2, 0, 9] }));
    const groups = () => [...document.querySelectorAll(".a-shell-group")].map((g) => g.querySelectorAll(".a-electron").length);
    expect(groups()).toEqual([2, 0, 9]);
    expect(screen.getByText("Schale 2: 0 Elektronen")).toBeInTheDocument();
    v.rerender(cardEl(tb({ form: "atom", element: "Na", neutronen: 12, ladung: 0, schalen: [11] })));
    expect(groups()).toEqual([11]);
  });

  it("32 Elektronen auf einem Ring und 7 Ringe: Punkte berühren sich nicht, alles endlich", () => {
    const v = card(tb({ form: "atom", element: "Ge", neutronen: -1, ladung: 0, schalen: [32] }));
    const dots = [...document.querySelectorAll(".a-electron")].map((c) => ({ x: Number(c.getAttribute("cx")), y: Number(c.getAttribute("cy")), r: Number(c.getAttribute("r")) }));
    expect(dots).toHaveLength(32);
    for (let i = 0; i < dots.length; i++) {
      const a = dots[i], b = dots[(i + 1) % dots.length];
      expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThan(a.r + b.r);
    }
    v.rerender(cardEl(tb({ form: "atom", element: "Og", neutronen: 176, ladung: 0, schalen: [2, 8, 18, 32, 32, 18, 8] })));
    expect(document.querySelectorAll(".a-shell")).toHaveLength(7);
    expect(document.querySelectorAll(".a-electron")).toHaveLength(118);
    expect(document.querySelector("svg")!.outerHTML).not.toMatch(/NaN|Infinity/);
    for (const n of [1, 2, 8, 32]) for (const r of [56, 100, 188]) {
      const pts = electronPositions(n, r), dr = dotRadius(n, r);
      if (n > 1) expect(Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y)).toBeGreaterThan(2 * dr);
    }
  });
});

describe("Orbital", () => {
  it("2p_z: fester Satz, Legende in Worten mit Punktzahlen, Achsen x, y, z als Text, drei Zeichenaufrufe", async () => {
    const { f } = await mountGl(ORBITAL);
    const w = orbitalPunkte(normalizeTeilchen(ORBITAL) as OrbitalConfig);
    const s = screen.getByRole("region", { name: "Orbital" });
    expect(within(s).getByText("Wasserstoff-Orbital, Wahrscheinlichkeitswolke")).toBeInTheDocument();
    const legend = within(s).getByRole("list", { name: "Legende" }).textContent!;
    expect(legend).toContain(`Phase plus: ${w.plus} Punkte, Farbe Cyan`);
    expect(legend).toContain(`Phase minus: ${w.minus} Punkte, Farbe Bernstein`);
    expect(w.plus + w.minus).toBe(2500);
    expect(w.plus).toBeGreaterThan(0); expect(w.minus).toBeGreaterThan(0);
    expect(within(s).getByText(w.text)).toBeInTheDocument();
    expect(w.text).toContain("2500 Punkte");
    expect([...s.querySelectorAll(".t-axis")].map((e) => e.textContent)).toEqual(["x", "y", "z"]);
    const fk = fakes()[0];
    const points = fk.objects.filter((o) => (o as THREE.Points).isPoints) as THREE.Points[];
    expect(points.map((p) => p.geometry.getAttribute("position").count).sort((a, b) => a - b)).toEqual([w.plus, w.minus].sort((a, b) => a - b));
    expect(fk.calls).toBe(3);                                                          // zwei Punktwolken und die Achsen
    expect(fk.renders).toBe(1);
    f.flush();
    expect(fk.renders).toBe(1);
  });

  it("unvollständige Wolke: „x von y Punkten“", async () => {
    const real = vi.mocked(orbitalPunkte).getMockImplementation()!;
    vi.mocked(orbitalPunkte).mockImplementation((c) => {
      const w = real(c), n = 100, ph = w.phasen.slice(0, n), plus = ph.filter((p) => p > 0).length;
      return { ...w, anzahl: n, vollstaendig: false, positionen: w.positionen.slice(0, 3 * n), phasen: ph, plus, minus: n - plus,
        text: `Orbital 2p_z, ${n} von ${w.soll} Punkten, ${w.beschreibung}.` };
    });
    try {
      await mountGl(ORBITAL);
      expect(screen.getByText(/Nur 100 von 2500 Punkten gezogen/)).toBeInTheDocument();
      expect(screen.getByText(/100 von 2500 Punkten, zwei Lappen/)).toBeInTheDocument();
    } finally {
      vi.mocked(orbitalPunkte).mockImplementation(real);
    }
  });

  it("ohne WebGL: Hinweis, Legende und Beschreibung bleiben", () => {
    card(ORBITAL);
    expect(screen.getByText(/3D braucht WebGL/)).toBeInTheDocument();
    expect(screen.getByText(/Phase plus: \d+ Punkte/)).toBeInTheDocument();
    expect(screen.getByText(/Orbital 2p_z, 2500 Punkte/)).toBeInTheDocument();
    expect(document.querySelector(".v-teilchen canvas")).toBeNull();
  });
});

describe("Ungültig", () => {
  const cases: [string, Record<string, unknown>][] = [
    ["Molekül ohne gültiges Atom", { form: "molekuel", name: "x", atome: [{ element: "Xx", position: [0, 0, 0] }], bindungen: [], beschriftungen: [], darstellung: "kugel-stab" }],
    ["unbekanntes Orbital", { form: "orbital", orbital: "4f", punkte: 2500, startwert: 1 }],
    ["falsche Schalensumme", { form: "atom", element: "Na", neutronen: 12, ladung: 0, schalen: [2, 8, 2] }],
    ["über 20 Elektronen ohne Schalen", { form: "atom", element: "Fe", neutronen: -1, ladung: 0 }],
    ["unbekannte Form (Ersatz: Wasserstoff-Atom)", { form: "quatsch" }],
  ];
  it.each(cases)("%s: nur „Teilchen kann nicht gezeigt werden.“, keine Hilfsrechnung, kein WebGL-Kontext", (_n, x) => {
    withWebGL(); frames();
    const getContext = vi.spyOn(HTMLCanvasElement.prototype, "getContext");
    card(tb(x));
    expect(screen.getByText(NOT_SHOWN)).toBeInTheDocument();
    expect(screen.queryByText(/Wasserstoff|Schalenmodell|Protonen|Punkte|Summenformel/)).toBeNull();
    expect(document.querySelector(".v-teilchen canvas, .v-teilchen svg")).toBeNull();
    expect(getContext.mock.calls.filter((c) => String(c[0]).startsWith("webgl"))).toHaveLength(0);
    for (const f of [orbitalPunkte, atomModell, molekuelGeometrie]) expect(f).not.toHaveBeenCalled();
    expect(R.list).toHaveLength(0);
  });

  it("eine werfende Eingabe wird zum ungültigen Ersatz-Atom und zeigt nur den Hinweis", () => {
    withWebGL(); frames();
    const evil = { typ: "teilchen", get form(): string { throw new Error("kaputt"); } } as unknown as TeilchenBlock;
    for (const C of [AtomShells, Molecule3D]) {
      const v = render(<C b={evil} />);
      expect(screen.getByText(NOT_SHOWN)).toBeInTheDocument();
      expect(screen.queryByText(/Wasserstoff/)).toBeNull();
      v.unmount();
    }
    expect(atomModell).not.toHaveBeenCalled();
    expect(R.list).toHaveLength(0);
  });

  it("meldet eine Hilfsrechnung ungültig oder leer, gibt es nur den Hinweis und keinen Renderer", async () => {
    withWebGL(); frames();
    const g = vi.mocked(molekuelGeometrie).getMockImplementation()!, o = vi.mocked(orbitalPunkte).getMockImplementation()!;
    const a = vi.mocked(atomModell).getMockImplementation()!;
    vi.mocked(molekuelGeometrie).mockImplementation((c) => ({ ...g(c), ungueltig: true }));
    vi.mocked(orbitalPunkte).mockImplementation((c) => {
      const w = o(c);
      return { ...w, anzahl: 0, plus: 0, minus: 0, positionen: new Float32Array(0), phasen: new Int8Array(0) };
    });
    vi.mocked(atomModell).mockImplementation((c) => ({ ...a(c), ungueltig: true }));
    try {
      card([WATER, ORBITAL, SODIUM]);
      expect(screen.getAllByText(NOT_SHOWN)).toHaveLength(3);
      expect(screen.queryByText(/Summenformel|Phase plus|Schalenmodell/)).toBeNull();
      await new Promise((res) => setTimeout(res, 50));
      expect(R.list).toHaveLength(0);
      expect(document.querySelector(".v-teilchen canvas, .v-teilchen svg")).toBeNull();
    } finally {
      vi.mocked(molekuelGeometrie).mockImplementation(g); vi.mocked(orbitalPunkte).mockImplementation(o); vi.mocked(atomModell).mockImplementation(a);
    }
  });

  it("angepasste Werte: kurzer Hinweis, die Ansicht zeigt trotzdem", () => {
    card(tb({ form: "orbital", orbital: "1s", punkte: 99999, startwert: 1 }));
    expect(screen.getByText(/wurden angepasst/)).toBeInTheDocument();
    expect(screen.getByText(/Orbital 1s, 5000 Punkte/)).toBeInTheDocument();
  });
});

/** Merkt sich jeden Listener auf der Zeichenfläche und `visibilitychange` am Dokument. */
function listenerSpy() {
  const add = vi.spyOn(EventTarget.prototype, "addEventListener"), rem = vi.spyOn(EventTarget.prototype, "removeEventListener");
  const ours = (ctx: unknown, type: unknown) => ctx instanceof HTMLCanvasElement || (ctx === document && type === "visibilitychange");
  return () => {
    const added = add.mock.calls.map((c, i) => [add.mock.contexts[i], c[0], c[1]] as const).filter(([ctx, t]) => ours(ctx, t));
    const removed = rem.mock.calls.map((c, i) => [rem.mock.contexts[i], c[0], c[1]] as const);
    return { added, open: added.filter(([ctx, t, fn]) => !removed.some(([c2, t2, f2]) => c2 === ctx && t2 === t && f2 === fn)) };
  };
}

describe("Aufräumen", () => {

  it.each([["Molekül", WATER], ["Orbital", ORBITAL]] as const)("%s: Abbauen gibt Geometrien, Materialien, Renderer und Listener frei", async (_n, b) => {
    const geoDispose = vi.spyOn(THREE.BufferGeometry.prototype, "dispose");
    const matDispose = vi.spyOn(THREE.Material.prototype, "dispose");
    const spy = listenerSpy();
    const { unmount, f } = await mountGl(b);
    const fk = fakes()[0];
    expect(fk.geometries.size).toBeGreaterThan(0);
    expect(spy().added.length).toBeGreaterThanOrEqual(6);
    unmount();
    expect(fk.disposed).toBe(true);
    expect(fk.lost).toBe(true);
    for (const g of fk.geometries) expect(geoDispose.mock.contexts).toContain(g);
    for (const m of fk.materials) expect(matDispose.mock.contexts).toContain(m);
    expect(spy().open).toEqual([]);
    expect(f.pending()).toBe(0);
  });

  it("neue Daten bauen die alte Szene ab und eine neue auf", async () => {
    const geoDispose = vi.spyOn(THREE.BufferGeometry.prototype, "dispose");
    const { rerender, f } = await mountGl(WATER);
    const first = fakes()[0];
    rerender(cardEl(ETHANOL));
    await waitFor(() => expect(fakes()).toHaveLength(2));
    f.flush();
    expect(first.disposed).toBe(true);
    for (const g of first.geometries) expect(geoDispose.mock.contexts).toContain(g);
    const second = fakes()[1];
    expect(second.disposed).toBe(false);
    expect(count(instanced(second, "SphereGeometry"))).toBe(9);
    expect(screen.getByText("C2H6O")).toBeInTheDocument();
  });

  it("verlorener WebGL-Kontext: Hinweis und Atomliste statt Bild, alles freigegeben", async () => {
    await mountGl(WATER);
    const fk = fakes()[0];
    act(() => { fk.canvas.dispatchEvent(new Event("webglcontextlost", { cancelable: true })); });
    expect(screen.getByText(/Die 3D-Darstellung wurde vom Browser beendet\./)).toBeInTheDocument();
    expect(screen.queryByText(/3D braucht WebGL/)).toBeNull();
    expect(fk.disposed).toBe(true);
    expect(screen.getAllByRole("row")).toHaveLength(4);
  });
});

describe("Text bleibt Text", () => {
  it("Name und Beschriftungen mit <script> stehen nur als DOM-Text, nie in einem Attribut und nie im Bild", async () => {
    const name = "<script>alert(1)</script>", label = "<img src=x onerror=alert(1)>", other = "url(#evil)";
    await mountGl(tb({ form: "molekuel", name, darstellung: "kugel-stab", bindungen: [],
      atome: [{ element: "O", position: [0, 0, 0.1173] }, { element: "H", position: [0, 0.7572, -0.4692] }, { element: "H", position: [0, -0.7572, -0.4692] }],
      beschriftungen: [{ atom: 0, text: label }, { atom: 1, text: other }] }));
    expect(screen.getByText(name)).toBeInTheDocument();
    expect(screen.getAllByText(label).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(other).length).toBeGreaterThanOrEqual(1);
    const root = document.querySelector(".v-teilchen")!;
    expect(root.querySelector("script, img, b, a, [href], foreignObject")).toBeNull();
    for (const el of document.querySelectorAll("*")) {
      for (const at of el.attributes) expect([name, label, other, "evil"].some((s) => at.value.includes(s)), `${el.tagName} ${at.name}`).toBe(false);
    }
    const fk = fakes()[0];                                                             // im Bild nur Netze, Linien, Lichter und Gruppen, keine Texturen
    for (const o of fk.objects) expect(["Scene", "Group", "Mesh", "AmbientLight", "DirectionalLight", "LineSegments", "Points"]).toContain(o.type);
    for (const m of fk.materials) expect((m as THREE.MeshStandardMaterial).map ?? null).toBeNull();
    for (const o of fk.objects) expect(o.name).toBe("");
  });

  it("Beschriftungen folgen ihrem Atom als Text über dem Bild (Lage nur aus Zahlen)", async () => {
    await mountGl(WATER);
    const tag = document.querySelector(".t-overlay .t-tag") as HTMLElement;
    expect(tag.textContent).toBe("Sauerstoff, leicht negativ");
    expect(tag.hidden).toBe(false);
    expect(tag.style.transform).toMatch(/^translate\(-?\d+px, -?\d+px\)$/);
  });
});

describe("Kein Klick sendet etwas", () => {
  it("Drehen, Ziehen, Zoomen, Tasten und Atomliste in der echten App lassen die gesendeten Nachrichten unverändert", async () => {
    withWebGL(); const f = frames();
    const xhr = vi.fn(), beacon = vi.fn(), ws = vi.fn();
    vi.stubGlobal("XMLHttpRequest", xhr);
    vi.stubGlobal("WebSocket", ws);                                                    // die App spricht nur über die Mock-Fabrik
    Object.defineProperty(navigator, "sendBeacon", { configurable: true, writable: true, value: beacon });
    const sock: { current?: MockSocket } = {};
    const loader = async () => ({ client: new ApiClient({ port: 5000, token: TOKEN }, (u) => (sock.current = new MockSocket(u, TOKEN))) });
    render(<App load={loader} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    for (const id of ["wasser", "orbital-2pz"]) {
      sock.current!.show(demo(id));
      await waitFor(() => screen.getByRole("heading", { name: String(demo(id).titel) }), { timeout: 3000 });
      await waitFor(() => expect(fakes().some((x) => !x.disposed)).toBe(true));
      f.flush();
      const pollTypes = new Set(["voice.state", ...sock.current!.sent.map((m) => (m as { type: string }).type)]);
      const before = JSON.stringify(sock.current!.sent);
      const buttons = [...document.querySelectorAll<HTMLButtonElement>(".v-teilchen button")];
      expect(buttons).toHaveLength(7);
      for (const b of buttons) {
        expect(b.type).toBe("button");
        b.focus();
        expect(document.activeElement).toBe(b);
        fireEvent.click(b);
        f.flush();
      }
      const stage = document.querySelector(".v-teilchen .m-stage")!;
      for (const key of ["ArrowLeft", "ArrowUp", "+", "-", "0", "Enter", " "]) fireEvent.keyDown(stage, { key });
      const live = fakes().find((x) => !x.disposed)!;
      fireEvent.wheel(live.canvas, { deltaY: 50 });
      const r0 = live.renders;
      fireEvent.pointerDown(live.canvas, { clientX: 5, clientY: 5, pointerId: 2 });
      fireEvent.pointerMove(live.canvas, { clientX: 60, clientY: 30, pointerId: 2 });
      fireEvent.pointerUp(live.canvas, { pointerId: 2 });
      f.flush();
      expect(live.renders).toBe(r0 + 1);                                               // Rad und Ziehen: ein Bild
      const summary = document.querySelector(".v-teilchen summary");
      if (summary) fireEvent.click(summary);
      fireEvent.click(screen.getByText("Beschreibung"));
      expect(JSON.stringify(sock.current!.sent)).toBe(before);
      await new Promise((res) => setTimeout(res, 1200));
      const later = sock.current!.sent.map((m) => (m as { type: string }).type);
      expect(later.filter((t) => !pollTypes.has(t))).toEqual([]);
    }
    for (const spy of [xhr, beacon, ws]) expect(spy).not.toHaveBeenCalled();
    delete (navigator as unknown as { sendBeacon?: unknown }).sendBeacon;
  }, 20_000);

  it("nichts wird gespeichert, geladen oder abgespielt", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const fetchSpy = vi.fn(), idbOpen = vi.fn(), audio = vi.fn(), ctx = vi.fn(), speak = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    vi.stubGlobal("indexedDB", { open: idbOpen });
    vi.stubGlobal("Audio", audio);
    vi.stubGlobal("AudioContext", ctx);
    vi.stubGlobal("webkitAudioContext", ctx);
    vi.stubGlobal("speechSynthesis", { speak, cancel: vi.fn() });
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
    const { f } = await mountGl([WATER, SODIUM, ORBITAL], 2);
    for (const b of document.querySelectorAll<HTMLButtonElement>(".v-teilchen button")) { fireEvent.click(b); f.flush(); }
    for (const s of document.querySelectorAll<HTMLElement>(".v-teilchen .m-stage")) fireEvent.keyDown(s, { key: "ArrowRight" });
    f.flush();
    fireEvent.click(document.querySelector(".v-teilchen summary")!);
    for (const spy of [setItem, fetchSpy, idbOpen, audio, ctx, speak, play]) expect(spy).not.toHaveBeenCalled();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.querySelector("audio, video, iframe, object, embed")).toBeNull();
  });
});

describe("Grenze je Ansicht (zweite Sicherung neben dem Backend)", () => {
  const MOL = WATER;
  const SCENE = { typ: "szene3d", einheit: "cm", hervorheben: [], beschriftungen: [], szenen: [{ name: "s", objekte: [
    { form: "box", name: "A", farbe: "arc", masse: [1, 1, 1], position: [0, 0, 0], drehung: [0, 0, 0] }] }] } as unknown as Block;
  const SIM = { typ: "simulation", modell: "pendel", parameter: { laenge: 1, winkel: 30, anfangsgeschwindigkeit: 0, daempfung: 0, g: 9.81 },
    laufzeit: 30, tempo: 0, spur: true, beschreibung: "" } as unknown as Block;
  const notes = (re: RegExp) => screen.queryAllByText(re);

  it("drei Moleküle oder Orbitale: das dritte zeigt nur einen Hinweis und legt keinen Renderer an", async () => {
    await mountGl([MOL, ORBITAL, MOL], 2);
    expect(notes(/Weitere 3D-Ansicht nicht gezeigt: höchstens 2 je Ansicht/)).toHaveLength(1);
    expect(document.querySelectorAll(".v-teilchen")).toHaveLength(2);
    await new Promise((res) => setTimeout(res, 50));
    expect(fakes()).toHaveLength(2);
  });

  it("zwei 3D-Szenen und ein Molekül: das Molekül zeigt den Hinweis (gemeinsame Grenze für WebGL)", () => {
    frames();
    card([SCENE, SCENE, MOL]);
    expect(notes(/Weitere 3D-Ansicht nicht gezeigt/)).toHaveLength(1);
    expect(document.querySelectorAll(".v-model")).toHaveLength(2);
    expect(document.querySelectorAll(".v-teilchen")).toHaveLength(0);
  });

  it("Schalenmodelle zählen nicht mit; drei Simulationen: die dritte zeigt den Hinweis, getrennt von WebGL", () => {
    frames();
    card([MOL, ORBITAL, SODIUM, SODIUM, SIM, SIM, SIM]);
    expect(notes(/Weitere 3D-Ansicht/)).toHaveLength(0);
    expect(document.querySelectorAll(".v-teilchen")).toHaveLength(4);
    expect(notes(/Weitere Simulation nicht gezeigt: höchstens 2 je Ansicht/)).toHaveLength(1);
    expect(document.querySelectorAll(".v-sim")).toHaveLength(2);
  });
});

describe("Bühne und Vorführung", () => {
  it("parseItem kennt Art und Baustein teilchen, Beschriftung „Teilchen“", () => {
    const v = parseItem({ seq: 1, id: "t", art: "teilchen", titel: "T", bausteine: [{ typ: "teilchen", form: "atom" }, { typ: "film" }] }) as View;
    expect(v.art).toBe("teilchen");
    expect(v.bausteine.map((b) => b.typ)).toEqual(["teilchen"]);
    expect(ART_LABEL.teilchen).toBe("Teilchen");
  });

  it("die vier Beispiele sind vollständig wie vom Backend und zeigen sich ohne Hinweis; die übrigen Beispiele bleiben unverändert", () => {
    frames();
    expect(DEMO_VIEWS.slice(17).map((v) => v.id)).toEqual(["pendel", "wurf", "gas", "doppelpendel", "welle", "anziehung"]);
    expect(TEILCHEN_DEMOS.map((v) => v.id)).toEqual(["wasser", "ethanol", "natrium", "orbital-2pz"]);
    const KEYS: Record<string, string[]> = {
      molekuel: ["atome", "beschriftungen", "bindungen", "darstellung", "form", "name", "typ"],
      atom: ["element", "form", "ladung", "neutronen", "schalen", "typ"],
      orbital: ["form", "orbital", "punkte", "startwert", "typ"],
    };
    TEILCHEN_DEMOS.forEach((r, i) => {
      expect(Object.keys(r).sort()).toEqual(["art", "bausteine", "id", "schliessen", "stand", "titel"]);
      expect(r.stand).toBe("");
      expect(r.schliessen).toBe(false);
      const v = parseItem({ ...r, seq: i + 1 }) as View;
      expect(v.art).toBe("teilchen");
      expect(v.bausteine).toHaveLength(1);
      const b = v.bausteine[0] as TeilchenBlock;
      expect(Object.keys(b).sort()).toEqual(KEYS[b.form]);
      const cfg = normalizeTeilchen(b);
      expect(cfg.angepasst).toEqual([]);
      expect(cfg.ungueltig).toBe(false);
      const c = render(<ViewCard view={v} sys={null} sysNo={false} onClose={() => undefined} />);
      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.queryByText(/angepasst|kann nicht gezeigt|nicht gezeigt/)).toBeNull();
      expect(screen.getByRole("heading", { name: String(r.titel) })).toBeInTheDocument();
      c.unmount();
    });
    const water = (TEILCHEN_DEMOS[0].bausteine as TeilchenBlock[])[0] as Extract<TeilchenBlock, { form: "molekuel" }>;
    const ethanol = (TEILCHEN_DEMOS[1].bausteine as TeilchenBlock[])[0] as Extract<TeilchenBlock, { form: "molekuel" }>;
    expect(water.bindungen).toHaveLength(2);
    expect(ethanol.bindungen).toEqual([]);
    expect(JSON.parse(JSON.stringify(TEILCHEN_DEMOS))).toEqual(TEILCHEN_DEMOS);       // reines JSON
  });

  it("die Vorführung zeigt die vier Teilchen nach den übrigen Beispielen", () => {
    vi.useFakeTimers();
    try {
      const m = new MockSocket("ws://127.0.0.1:1", TOKEN);
      m.demo();
      vi.advanceTimersByTime(280_000);
      expect(m.stage.map((v) => v.id).slice(-4)).toEqual(["wasser", "ethanol", "natrium", "orbital-2pz"]);
    } finally {
      vi.useRealTimers();
    }
  });
});

// Nachträge aus der Testprüfung: P4a-Betrachter mit WebGL über den falschen Renderer, frühes Abbauen, Kontextverlust, Größenänderung,
// Atom ohne Elektronen, leere Geometrie, 1s-Orbital, Fokus und globale Listener, Freigabe des Probe-Kontexts, abgesicherte Grenze.

const SCENE3D = { typ: "szene3d", einheit: "cm", hervorheben: [], beschriftungen: [], szenen: [{ name: "s", objekte: [
  { form: "box", name: "A", farbe: "arc", masse: [10, 20, 30], position: [0, 10, 0], drehung: [0, 0, 0] },
  { form: "kugel", name: "B", farbe: "amber", masse: [5], position: [20, 5, 0], drehung: [0, 0, 0] }] }] } as unknown as Block;
const press = (name: string) => fireEvent.click(screen.getByRole("button", { name }));

/** Falscher ResizeObserver, der Beobachtung und Trennung mitschreibt; `fire` meldet eine neue Größe. */
function fakeRO() {
  const list: { cb: () => void; observed: Element[]; disconnected: boolean }[] = [];
  vi.stubGlobal("ResizeObserver", class {
    rec: (typeof list)[number];
    constructor(cb: () => void) { this.rec = { cb, observed: [], disconnected: false }; list.push(this.rec); }
    observe(el: Element) { this.rec.observed.push(el); }
    unobserve() {}
    disconnect() { this.rec.disconnected = true; }
  });
  return list;
}

describe("P4a-Betrachter (Model3D) mit WebGL über die gemeinsame Kamerabahn", () => {
  it("Knopf, Pfeil, Ziehen und Rad je ein Bild; 80 × näher, 80 × weiter, zurück: nie NaN; Strg, Alt, Meta bleiben beim Browser; Abbauen gibt frei", async () => {
    const spy = listenerSpy();
    const { f, unmount } = await mountGl(SCENE3D);
    const fk = fakes()[0], stage = document.querySelector(".v-model .m-stage")!;
    expect(fk.renders).toBe(1);
    const step = (fn: () => void, handled = true) => { const n = fk.renders; fn(); f.flush(); expect(fk.renders).toBe(n + (handled ? 1 : 0)); };
    step(() => press("Links drehen"));
    step(() => expect(fireEvent.keyDown(stage, { key: "ArrowUp" })).toBe(false));
    step(() => {
      fireEvent.pointerDown(fk.canvas, { clientX: 0, clientY: 0, pointerId: 1 });
      fireEvent.pointerMove(fk.canvas, { clientX: 25, clientY: 15, pointerId: 1 });
      fireEvent.pointerUp(fk.canvas, { pointerId: 1 });
    });
    step(() => fireEvent.wheel(fk.canvas, { deltaY: -120 }));
    step(() => press("Ansicht zurücksetzen"));
    const home = fk.eyes[fk.eyes.length - 1];
    expect(home).toEqual(fk.eyes[0]);
    for (let i = 0; i < 80; i++) step(() => press("Näher"));
    const near = fk.eyes[fk.eyes.length - 1];
    for (let i = 0; i < 80; i++) step(() => press("Weiter weg"));
    const far = fk.eyes[fk.eyes.length - 1];
    const dist = (e: number[]) => Math.hypot(e[0] - 10, e[1] - 10, e[2]);               // Mitte der Hüllbox: (10, 10, 0)
    expect(dist(near)).toBeLessThan(dist(home));
    expect(dist(far)).toBeGreaterThan(dist(home));
    expect(dist(far) / dist(near)).toBeCloseTo(50, 5);                                  // Grenzen 0,2 und 10 × Größe
    step(() => press("Ansicht zurücksetzen"));
    expect(fk.eyes[fk.eyes.length - 1]).toEqual(home);
    expect(fk.eyes.flat().every(Number.isFinite)).toBe(true);
    for (const [key, mod] of [["+", "ctrlKey"], ["0", "ctrlKey"], ["ArrowLeft", "altKey"], ["+", "altKey"], ["ArrowRight", "metaKey"], ["0", "metaKey"]] as const) {
      step(() => expect(fireEvent.keyDown(stage, { key, [mod]: true }), `${mod}+${key}`).toBe(true), false);
    }
    step(() => expect(fireEvent.keyDown(stage, { key: "+" })).toBe(false));
    step(() => expect(fireEvent.keyDown(stage, { key: "0" })).toBe(false));
    expect(spy().added.length).toBeGreaterThanOrEqual(6);
    unmount();
    expect(fk.disposed).toBe(true);
    expect(fk.lost).toBe(true);
    expect(spy().open).toEqual([]);
    expect(f.pending()).toBe(0);
  });
});

describe("Lebenszyklus der Teilchen-Betrachter", () => {
  it("abgebaut, bevor three.js geladen ist: kein Renderer, keine offenen Listener, kein Fehlerhinweis", async () => {
    withWebGL(); const f = frames(); const spy = listenerSpy();
    const v = card([WATER, ETHANOL]);
    v.rerender(cardEl([WATER]));                                                       // Ethanol verschwindet sofort wieder
    const other = card(ORBITAL);
    other.unmount();                                                                   // die ganze Karte geht, bevor three.js da ist
    await waitFor(() => expect(fakes()).toHaveLength(1));
    await new Promise((res) => setTimeout(res, 50));
    expect(fakes()).toHaveLength(1);
    f.flush();
    expect(count(instanced(fakes()[0], "SphereGeometry"))).toBe(3);                   // nur Wasser
    expect(screen.queryByText(/3D braucht WebGL|beendet|kann nicht gezeigt/)).toBeNull();
    v.unmount();
    expect(spy().open).toEqual([]);
    expect(f.pending()).toBe(0);
  });

  it("Kontextverlust: Hinweis „vom Browser beendet“, Renderer freigegeben, Listener und ResizeObserver getrennt", async () => {
    const ros = fakeRO(); const spy = listenerSpy();
    await mountGl(WATER);
    const fk = fakes()[0];
    act(() => { fk.canvas.dispatchEvent(new Event("webglcontextlost", { cancelable: true })); });
    expect(screen.getByText(/Die 3D-Darstellung wurde vom Browser beendet\. Die Atomliste unten zeigt den Inhalt\./)).toBeInTheDocument();
    expect(fk.disposed).toBe(true);
    expect(ros.filter((r) => r.observed.includes(fk.canvas))).toHaveLength(1);
    expect(ros.every((r) => r.disconnected)).toBe(true);
    expect(spy().open).toEqual([]);
    expect(screen.getAllByRole("row")).toHaveLength(4);
  });

  it("ResizeObserver: beobachtet die Zeichenfläche, eine Meldung gibt ein Bild, zwei im selben Takt auch nur eins, getrennt beim Abbauen", async () => {
    const ros = fakeRO();
    const { f, unmount } = await mountGl(ORBITAL);
    const fk = fakes()[0];
    const ro = ros.find((r) => r.observed.includes(fk.canvas))!;
    expect(ro).toBeDefined();
    expect(fk.renders).toBe(1);
    act(() => ro.cb());
    f.flush();
    expect(fk.renders).toBe(2);
    act(() => { ro.cb(); ro.cb(); });
    f.flush();
    expect(fk.renders).toBe(3);
    unmount();
    expect(ro.disconnected).toBe(true);
    expect(f.pending()).toBe(0);
  });
});

describe("Randfälle der Formen", () => {
  it.each([["H", 1, "einfach positiv geladen", "Wasserstoff"], ["He", 2, "zweifach positiv geladen", "Helium"]] as const)(
    "%s mit Ladung +%i und ohne Elektronen: kein Ring, kein NaN, Ladung in Worten, keine leere Liste", (element, ladung, wort, name) => {
      card(tb({ form: "atom", element, neutronen: -1, ladung, schalen: [] }));
      const s = screen.getByRole("region", { name: "Atom" });
      expect(within(s).getByText(`Ladung: ${wort}`)).toBeInTheDocument();
      expect(within(s).getByText(new RegExp(`^${name}, ${wort}, .*keine Elektronen\\.`))).toBeInTheDocument();
      expect(within(s).getByText("Keine Elektronen in der Hülle, nur der Kern.")).toBeInTheDocument();
      const svg = s.querySelector("svg")!;
      expect(svg.querySelectorAll(".a-shell, .a-electron")).toHaveLength(0);
      expect(svg.querySelector(".a-core")).not.toBeNull();
      expect(svg.outerHTML).not.toMatch(/NaN|Infinity/);
      expect(s.querySelector("ol, ul")).toBeNull();
      for (const li of s.querySelectorAll("li")) expect(li.textContent?.trim()).not.toBe("");
      expect(screen.queryByText(NOT_SHOWN)).toBeNull();
    });

  it("Geometrie mit 0 Atomen, aber nicht als ungültig gemeldet: nur der Hinweis, kein Renderer", async () => {
    withWebGL(); frames();
    const g = vi.mocked(molekuelGeometrie).getMockImplementation()!;
    vi.mocked(molekuelGeometrie).mockImplementation((c) => ({ ...g(c), atome: [], bindungen: [], zeilen: [], atomzahl: 0, bindungszahl: 0, ungueltig: false }));
    try {
      card(WATER);
      expect(screen.getByText(NOT_SHOWN)).toBeInTheDocument();
      expect(screen.queryByText(/Summenformel|Atomliste/)).toBeNull();
      await new Promise((res) => setTimeout(res, 50));
      expect(R.list).toHaveLength(0);
    } finally {
      vi.mocked(molekuelGeometrie).mockImplementation(g);
    }
  });

  it("1s-Orbital: eine Punktwolke, zwei Zeichenaufrufe, „Phase minus: 0 Punkte“", async () => {
    await mountGl(tb({ form: "orbital", orbital: "1s", punkte: 2500, startwert: 1 }));
    const fk = fakes()[0];
    expect(fk.objects.filter((o) => (o as THREE.Points).isPoints)).toHaveLength(1);
    expect(fk.calls).toBe(2);
    expect(screen.getByRole("list", { name: "Legende" }).textContent).toContain("Phase minus: 0 Punkte");
    expect(screen.getByRole("list", { name: "Legende" }).textContent).toContain("Phase plus: 2500 Punkte");
  });
});

describe("Fokus, globale Listener und Probe-Kontext", () => {
  it("nach dem Zeigen in der App liegt der Fokus nicht in der Ansicht", async () => {
    withWebGL(); const f = frames();
    const sock: { current?: MockSocket } = {};
    const loader = async () => ({ client: new ApiClient({ port: 5000, token: TOKEN }, (u) => (sock.current = new MockSocket(u, TOKEN))) });
    render(<App load={loader} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    sock.current!.show(demo("wasser"));
    await waitFor(() => screen.getByRole("heading", { name: "Wasser (Beispiel)" }), { timeout: 3000 });
    await waitFor(() => expect(fakes().some((x) => !x.disposed)).toBe(true));
    f.flush();
    expect(document.activeElement?.closest(".v-teilchen") ?? null).toBeNull();
  });

  it("die Betrachter melden keine Tasten-, Größen- oder Zeiger-Listener an Fenster oder Dokument an", async () => {
    const add = vi.spyOn(EventTarget.prototype, "addEventListener");
    const { unmount } = await mountGl([WATER, ORBITAL, SODIUM], 2);
    const global = add.mock.calls.map((c, i) => [add.mock.contexts[i], String(c[0])] as const)
      .filter(([ctx]) => ctx === window || ctx === document).map(([, t]) => t);
    expect(global.filter((t) => /^(keydown|keyup|keypress|resize|pointer|mouse|touch|wheel)/.test(t))).toEqual([]);
    expect(global.filter((t) => t !== "visibilitychange" && !/^(focus|blur|selectionchange)/.test(t))).toEqual([]);
    unmount();
  });

  it("der Probe-Kontext von hasWebGL wird sofort freigegeben (Molekül, Orbital, P4a-Szene)", async () => {
    withWebGL(); const f = frames();
    const loseContext = vi.fn();
    const probe = { getExtension: (n: string) => (n === "WEBGL_lose_context" ? { loseContext } : null) };
    const getContext = vi.spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockImplementation(((t: string) => (t.startsWith("webgl") ? probe : null)) as unknown as typeof HTMLCanvasElement.prototype.getContext);
    const a = card([WATER, ORBITAL]);
    await waitFor(() => expect(fakes()).toHaveLength(2));
    a.unmount();
    const b = card(SCENE3D);
    await waitFor(() => expect(fakes()).toHaveLength(3));
    f.flush();
    b.unmount();
    const probes = getContext.mock.calls.filter((c) => String(c[0]).startsWith("webgl")).length;
    expect(probes).toBe(3);
    expect(loseContext).toHaveBeenCalledTimes(probes);
  });
});

describe("Grenze je Ansicht: abgesichertes Lesen", () => {
  it("ein werfendes `form` leert die Karte nicht; nur dieser Baustein zeigt den Hinweis", () => {
    frames();
    const evil = { typ: "teilchen", get form(): string { throw new Error("kaputt"); } } as unknown as Block;
    const log = console.error;
    console.error = () => undefined;                                                   // React meldet den abgefangenen Fehler laut
    try {
      card([{ typ: "hinweis", text: "Bleibt sichtbar." }, evil, { typ: "hinweis", text: "Auch das." }]);
    } finally { console.error = log; }
    expect(screen.getByText("Bleibt sichtbar.")).toBeInTheDocument();
    expect(screen.getByText("Auch das.")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("konnte nicht angezeigt werden");
    expect(screen.getByRole("heading", { name: "Titel" })).toBeInTheDocument();
  });
});
