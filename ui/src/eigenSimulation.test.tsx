import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import katex from "katex";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { ViewCard } from "./components/stage/ViewCard";
import { ApiClient } from "./lib/api";
import { STATE_VIEW } from "./lib/avatarState";
import {
  reglerBedienbar, VORAUS_KNOTEN_MAX, VORAUS_KOERPER_MAX, vorausBild, wertAusPos, wertFuerTaste, zahlText,
} from "./components/stage/EigenSimulation";
import { advanceEigen, createEigen, EIGEN_HINWEIS, eigenRegler, KNOTEN_BUDGET } from "./lib/eigenSim";
import { EIGEN_DEMOS, EIGEN_GEAENDERT, MockSocket } from "./lib/mock";
import type { GrenzFeld } from "./lib/physics";
import { createSimLoop, MAX_KOERPER_SCHRITTE } from "./lib/simLoop";
import { parseItem, type Block, type EigenBlock, type View } from "./lib/stage";

// P7 Stufe 1 (docs/ui-p7-plan.md, 2.6): Baustein `sim_eigen` mit falschem requestAnimationFrame und falscher Uhr. Kernregeln: Abzeichen
// und Hinweis kommen immer von der Oberfläche; Gleichungen nur als TeX ohne `trust`; Regler ändern nur die Anzeige und senden nie etwas;
// eine abgelehnte Ansicht zeigt einen neutralen Text ohne Rohdaten.

vi.mock("katex", async (orig) => {
  const m = await orig<{ default: typeof katex }>();
  return { ...m, default: { ...m.default, render: vi.fn(m.default.render) } };
});
vi.mock("./lib/simLoop", async (orig) => {
  const m = await orig<typeof import("./lib/simLoop")>();
  return { ...m, createSimLoop: vi.fn(m.createSimLoop) };
});
vi.mock("./lib/eigenSim", async (orig) => {                          // nur die Vorausrechnung des Standbilds ruft advanceEigen direkt
  const m = await orig<typeof import("./lib/eigenSim")>();
  return { ...m, advanceEigen: vi.fn(m.advanceEigen) };
});

const TOKEN = "t".repeat(43);
const REDUCE = "(prefers-reduced-motion: reduce)";
const BADGE = "Eigene Simulation · ungeprüft";
afterEach(() => {
  cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals();
  vi.mocked(katex.render).mockClear(); vi.mocked(createSimLoop).mockClear(); vi.mocked(advanceEigen).mockClear();
});

type Call = { name: string; args: unknown[] };
function recordingCtx() {
  const calls: Call[] = [];
  const ctx = new Proxy({}, {
    get: (_t, k) => (k === "canvas" ? null : (...args: unknown[]) => { calls.push({ name: String(k), args }); }),
    set: (_t, k, v) => { calls.push({ name: `set:${String(k)}`, args: [v] }); return true; },
  });
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation((() => ctx) as unknown as typeof HTMLCanvasElement.prototype.getContext);
  return { calls, count: (n: string) => calls.filter((c) => c.name === n).length };
}

function fakeFrames() {
  let t = performance.now(), id = 0;
  const q = new Map<number, FrameRequestCallback>();
  const raf = vi.fn((cb: FrameRequestCallback) => { q.set(++id, cb); return id; });
  const caf = vi.fn((i: number) => { q.delete(i); });
  vi.stubGlobal("requestAnimationFrame", raf);
  vi.stubGlobal("cancelAnimationFrame", caf);
  vi.spyOn(performance, "now").mockImplementation(() => t);
  const frame = (ms = 1000 / 60) => act(() => { t += ms; const cbs = [...q.values()]; q.clear(); for (const cb of cbs) cb(t); });
  const run = (sec: number, hz = 60) => { for (let i = 0, n = Math.round(sec * hz); i < n; i++) frame(1000 / hz); };
  return { raf, caf, frame, run, pending: () => q.size };
}

function reducedMotion() {
  const add = vi.fn(), rem = vi.fn();
  vi.spyOn(window, "matchMedia").mockImplementation(((q: string) =>
    ({ matches: q === REDUCE, media: q, addEventListener: add, removeEventListener: rem })) as unknown as typeof window.matchMedia);
  return { add, rem };
}

const demo = (i: number) => EIGEN_DEMOS[i] as unknown as Omit<View, "seq">;
const demoBlock = (i: number) => demo(i).bausteine[0] as EigenBlock;
const kopie = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
/** Zerfall u' = -u, genau wie das Backend ihn liefert (tests/test_stage.py, SE_FILLED_ODE). */
const ZERFALL = {
  typ: "sim_eigen", form: "ode", name: "Zerfall", beschreibung: "", parameter: [], dt: 0.01, laufzeit: 30, tempo: 1, spur: true,
  zustand: [{ name: "u", start: 1, einheit: "" }], hilf: [], ableitungen: { u: { rpn: [["v", 1], ["o", "neg"]], tex: "-u" } }, kennwerte: [],
  erhaltung: null, darstellung: [{ form: "zeitreihe", groessen: ["u"] }], env: { ode: ["t", "u"] }, integrator: "rk4", kosten: 8,
} as unknown as EigenBlock;
const zerfall = (extra: Record<string, unknown> = {}) => ({ ...kopie(ZERFALL), ...extra }) as EigenBlock;
const view = (b: Block | Block[], extra: Partial<View> = {}): View =>
  ({ seq: 1, id: "e1", art: "simulation", titel: "Titel", stand: "", bausteine: Array.isArray(b) ? b : [b], ...extra });
const cardEl = (v: View) => <ViewCard view={v} sys={null} sysNo={false} onClose={() => undefined} />;
const card = (b: Block | Block[], extra: Partial<View> = {}) => render(cardEl(view(b, extra)));
const btn = (name: string | RegExp) => screen.getByRole("button", { name });
const click = (name: string | RegExp) => fireEvent.click(btn(name));
const word = () => document.querySelector(".v-eigen .s-state")?.textContent ?? "";
const row = (name: string) => [...document.querySelectorAll(".s-figures tr")].find((tr) => tr.querySelector("th")?.textContent === name)?.querySelector("td")?.textContent ?? "";
const num = (s: string) => Number.parseFloat(s.replace(/ /g, "").replace("−", "-").replace(",", "."));
const canvases = () => [...document.querySelectorAll<HTMLCanvasElement>(".v-eigen canvas")];
const fixed = () => {
  expect(screen.getByText(BADGE)).toBeInTheDocument();
  expect(screen.getByText(`${EIGEN_HINWEIS}.`)).toBeInTheDocument();
};

describe("Vier Beispiele (aus der Python-Prüfung)", () => {
  it("sind vollständig wie vom Backend und rechnen ohne Anpassung", () => {
    expect(EIGEN_DEMOS.map((v) => v.id)).toEqual(["eigen-pendel", "eigen-raeuber", "eigen-lorenz", "eigen-kette"]);
    for (const raw of [...EIGEN_DEMOS, EIGEN_GEAENDERT]) {
      expect(Object.keys(raw).sort()).toEqual(["art", "bausteine", "id", "schliessen", "stand", "titel"]);
      const v = parseItem({ ...raw, seq: 1 }) as View;
      const b = v.bausteine[0] as EigenBlock;
      expect(b.typ).toBe("sim_eigen");
      expect(Object.keys(b)).toEqual(expect.arrayContaining(["name", "beschreibung", "form", "parameter", "darstellung", "dt", "laufzeit", "tempo", "spur",
        "kennwerte", "erhaltung", "env", "integrator", "kosten"]));
      expect(JSON.stringify(b)).not.toMatch(/sin\(phi\)|a\*B|s\*\(y-x\)|-c\*vx/);                     // kein Formeltext, nur RPN und TeX
      const s = createEigen(b);
      expect(s.config.angepasst).toEqual([]);
      expect(s.config.ungueltig).toBe(false);
      expect(s.phase).toBe("laeuft");
    }
  });

  it.each([0, 1, 2, 3])("Beispiel %i zeigt sich ohne Hinweis, mit Abzeichen, Bildern, Zustand und Gleichungen", async (i) => {
    const r = recordingCtx(), f = fakeFrames();
    const v = parseItem({ ...demo(i), seq: 1 }) as View;
    const b = v.bausteine[0] as EigenBlock;
    render(cardEl(v));
    fixed();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText(/angepasst|kann nicht gezeigt|nicht gezeichnet/)).toBeNull();
    expect(word()).toBe("läuft");
    expect(canvases()).toHaveLength(b.darstellung.length);
    expect(r.count("clearRect")).toBeGreaterThan(0);
    expect(screen.getByText(b.beschreibung)).toBeInTheDocument();
    expect(screen.getByText(createEigen(b).text)).toBeInTheDocument();
    f.run(1);
    click("Pause");                                                                    // Pause zeigt die letzten Zahlen sofort
    expect(num(row("Zeit in der Simulation"))).toBeGreaterThan(0.9);
    click("Weiter");
    await waitFor(() => expect(document.querySelectorAll(".v-eigen .e-gl .katex").length).toBeGreaterThan(0));
    expect(document.querySelector(".tex-bad")).toBeNull();
    for (const c of canvases()) expect(c.getAttribute("aria-label")).toMatch(/Zeit \d/);
  });
});

describe("Abzeichen und Hinweis", () => {
  it("sind in jedem Zustand da und lassen sich über die Ansicht nicht entfernen", () => {
    recordingCtx(); fakeFrames();
    const faelle: Block[] = [
      zerfall(), zerfall({ name: "", beschreibung: "" }), zerfall({ hinweis: false, abzeichen: "", badge: null } as Record<string, unknown>),
      zerfall({ ableitungen: { u: { rpn: [["v", 9]], tex: "x" } } }), zerfall({ ableitungen: { u: { rpn: [["c", 1], ["c", 0], ["o", "/"]], tex: "1/0" } } }),
      { typ: "sim_eigen" } as unknown as Block,
    ];
    for (const b of faelle) { const c = card(b); fixed(); c.unmount(); }
    reducedMotion();
    const c = card(demoBlock(0)); fixed(); c.unmount();
  });

  it("ohne 2D-Kontext: Hinweis, Abzeichen, Werte am Start, keine Schleife", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation((() => null) as unknown as typeof HTMLCanvasElement.prototype.getContext);
    const f = fakeFrames();
    card(demoBlock(0));
    fixed();
    expect(screen.getByText(/Das Bild kann hier nicht gezeichnet werden/)).toBeInTheDocument();
    expect(f.raf).not.toHaveBeenCalled();
    expect(screen.getByText("Werte am Start")).toBeInTheDocument();
    expect(row("phi")).toBe("1,2 rad");
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
  });
});

describe("Gleichungen als TeX", () => {
  /** Die von KaTeX gesetzten Formeln (die Quelle steht in der MathML-Annotation), erst wenn alle `n` gesetzt sind. */
  const gesetzt = async (n: number): Promise<string[]> => {
    await waitFor(() => expect(document.querySelectorAll(".e-gl .katex")).toHaveLength(n));
    return [...document.querySelectorAll(".e-gl annotation")].map((a) => a.textContent ?? "");
  };

  it("jede Ableitung als x' = …, Kennwert und Lage des Körpers, immer trust: false", async () => {
    recordingCtx(); fakeFrames();
    card(demoBlock(0));
    const texte = await gesetzt(5);
    expect(texte).toContain("\\phi' = w");
    expect(texte).toContain("w' = \\frac{-g}{l} \\cdot \\sin\\left(\\phi\\right) - d \\cdot w");
    expect(texte).toContain("0.5 \\cdot \\left(l \\cdot w\\right)^{2} + g \\cdot l \\cdot \\left(1 - \\cos\\left(\\phi\\right)\\right)");
    expect(vi.mocked(katex.render).mock.calls.length).toBeGreaterThan(0);
    for (const c of vi.mocked(katex.render).mock.calls) expect(c[2]).toMatchObject({ trust: false });
    expect(screen.getByText("Energie je Masse =")).toBeInTheDocument();
    expect(screen.getByText("Körper waagerecht =")).toBeInTheDocument();
    expect(document.querySelector(".tex-bad")).toBeNull();
  });

  it("ohne trust: ein \\href in der TeX-Fassung ergibt keinen Link", async () => {
    recordingCtx(); fakeFrames();
    card(zerfall({ ableitungen: { u: { rpn: [["v", 1], ["o", "neg"]], tex: "\\href{https://example.org}{u}" } } }));
    await waitFor(() => expect(document.querySelector(".e-gl .katex, .e-gl .tex-bad")).not.toBeNull());
    expect(document.querySelector("a, [href]")).toBeNull();
  });

  it("Teilchen: Kraft F_x und F_y, Federn als Satz; Räuber und Beute: Erhaltungsgröße; Namen mit Index", async () => {
    recordingCtx(); fakeFrames();
    const c = card(demoBlock(3));
    let texte = await gesetzt(2);
    expect(texte).toEqual(["F_x = -c \\cdot \\mathrm{vx}", "F_y = -m \\cdot g - c \\cdot \\mathrm{vy}"]);
    expect(screen.getByText(/Federn \(11\): Federkonstante 40, Ruhelänge 0,25, Dämpfung 0,05\./)).toBeInTheDocument();
    c.unmount();
    const c2 = card(demoBlock(1));
    texte = await gesetzt(3);
    expect(texte).toContain("R' = \\mathrm{dd} \\cdot B \\cdot R - c \\cdot R");
    expect(screen.getByText("Erhaltungsgröße =")).toBeInTheDocument();
    c2.unmount();
    card(zerfall({ zustand: [{ name: "x_1", start: 1, einheit: "" }], ableitungen: { x_1: { rpn: [["v", 1], ["o", "neg"]], tex: "-x_{\\mathrm{1}}" } },
      darstellung: [{ form: "zeitreihe", groessen: ["x_1"] }], env: { ode: ["t", "x_1"] } }));
    expect(await gesetzt(1)).toEqual(["x_{\\mathrm{1}}' = -x_{\\mathrm{1}}"]);
  });

  it("der Baustein liest nie Formeltext: eine Formel als Text statt RPN wird abgelehnt", () => {
    recordingCtx(); fakeFrames();
    card(zerfall({ ableitungen: { u: "-u" } }));
    expect(screen.getByText(/Diese eigene Simulation kann nicht gezeigt werden/)).toBeInTheDocument();
    expect(canvases()).toHaveLength(0);
  });
});

describe("Abgelehnte Ansicht: neutraler Text ohne Rohdaten", () => {
  const boese: [string, Record<string, unknown>][] = [
    ["Index außerhalb", { ableitungen: { u: { rpn: [["v", 99]], tex: "u" } } }],
    ["unbekannter Befehl", { ableitungen: { u: { rpn: [["x", "alert"]], tex: "u" } } }],
    ["Unterlauf", { ableitungen: { u: { rpn: [["o", "+"]], tex: "u" } } }],
    ["zwei Werte", { ableitungen: { u: { rpn: [["c", 1], ["c", 2]], tex: "u" } } }],
    ["env falsch", { env: { ode: ["t", "q"] } }],
    ["keine Form", { form: "skript" }],
  ];
  it.each(boese)("%s", (_n, extra) => {
    recordingCtx(); const f = fakeFrames();
    const b = zerfall({ name: "GeheimerName", beschreibung: "Rohtext der Beschreibung", ...extra });
    card(b);
    fixed();
    const sec = document.querySelector(".v-eigen")!;
    expect(sec.textContent).toMatch(/Diese eigene Simulation kann nicht gezeigt werden\./);
    for (const roh of ["GeheimerName", "Rohtext", "index", "unterlauf", "ableitungen", "env", "alert", "skript", "@"]) expect(sec.textContent).not.toContain(roh);
    expect(canvases()).toHaveLength(0);
    expect(f.raf).not.toHaveBeenCalled();
    expect(screen.queryByRole("slider")).toBeNull();
  });
});

describe("Zustand in Worten", () => {
  it("läuft, pausiert, weiter, angehalten nach der Laufzeit, neu starten", () => {
    recordingCtx(); const f = fakeFrames();
    card({ ...demoBlock(0), laufzeit: 5 } as EigenBlock);
    expect(word()).toBe("läuft");
    expect(document.querySelector(".v-eigen .s-state")).toHaveAttribute("aria-live", "polite");
    f.run(0.5);
    click("Pause");
    expect(word()).toBe("pausiert");
    const t = row("Zeit in der Simulation");
    f.run(1);
    expect(row("Zeit in der Simulation")).toBe(t);
    click("Weiter");
    expect(word()).toBe("läuft");
    f.run(6);
    expect(word()).toBe("angehalten nach 5 s");
    expect(f.pending()).toBe(0);
    click("Neu starten");
    expect(word()).toBe("läuft");
    expect(num(row("Zeit in der Simulation"))).toBeLessThan(0.1);
  });

  it("instabil bei 1/0: angehalten, Grund in Worten, Startbild bleibt", () => {
    const r = recordingCtx(); const f = fakeFrames();
    card(zerfall({ ableitungen: { u: { rpn: [["c", 1], ["c", 0], ["o", "/"]], tex: "\\frac{1}{0}" } } }));
    fixed();
    expect(word()).toBe("Simulation instabil, angehalten");
    expect(screen.getByText(/Eine Zahl ist nicht mehr endlich, etwa durch Teilen durch 0/)).toBeInTheDocument();
    expect(f.pending()).toBe(0);
    expect(r.count("clearRect")).toBeGreaterThan(0);
    expect(screen.queryByText(/kann nicht gezeigt werden/)).toBeNull();
  });

  it("instabil, wenn ein Wert über eine Milliarde wächst", () => {
    recordingCtx(); const f = fakeFrames();
    card(zerfall({ ableitungen: { u: { rpn: [["c", 50], ["v", 1], ["o", "*"]], tex: "50 u" } } }));
    expect(word()).toBe("läuft");
    f.run(2);
    expect(word()).toBe("Simulation instabil, angehalten");
    expect(screen.getByText(/über eine Milliarde gewachsen/)).toBeInTheDocument();
    expect(f.pending()).toBe(0);
  });

  it("Zeitlupe, wenn das Rechenbudget je Bild nicht reicht", () => {
    recordingCtx(); const f = fakeFrames();
    const rpn: unknown[] = [["v", 0]];
    for (let i = 0; i < 14; i++) rpn.push(["c", 1], ["o", "*"]);
    rpn.push(["c", 0.000001], ["o", "*"]);
    card({
      typ: "sim_eigen", form: "teilchen", name: "Viele", beschreibung: "", parameter: [], dt: 0.005, laufzeit: 30, tempo: 1, spur: false,
      anzahl: 100, start: "gitter", punkte: [], startwert: 1, masse: 1, kraft: null, paar: { f_r: { rpn, tex: "r" }, reichweite: 10, mindestabstand: 0.1 },
      federn: null, fest: [], waende: "reflektieren", kasten: [10, 10], kennwerte: [], erhaltung: null, darstellung: [{ form: "koerper" }],
      env: { kraft: ["t", "x", "y", "vx", "vy", "m"], paar: ["r"] }, integrator: "verlet", kosten: 4950 * 31,
    } as unknown as EigenBlock);
    f.run(0.2);
    expect(word()).toBe("Zeitlupe, Rechengrenze erreicht");
    expect(screen.getByText("Tempo wirkt erst, wenn die Rechengrenze nicht erreicht ist.")).toBeInTheDocument();
  });

  it("Rechenfehler wächst: Hinweis, wenn die Erhaltungsgröße abweicht", () => {
    recordingCtx(); const f = fakeFrames();
    card({ ...demoBlock(1), erhaltung: { rpn: [["v", 1]], tex: "B" } } as unknown as EigenBlock);
    expect(screen.queryByText(/Rechenfehler wächst/)).toBeNull();
    f.run(1.5);
    expect(screen.getByText(/^Rechenfehler wächst\. Die Erhaltungsgröße weicht um \d+,\d % vom Start ab\./)).toBeInTheDocument();
  });
});

describe("Regler", () => {
  it("ein Regler je Parameter mit Grenzen, Einheit und Beschriftung; Ziehen startet mit dem neuen Wert neu", () => {
    recordingCtx(); const f = fakeFrames();
    card(demoBlock(0));
    const d = screen.getByLabelText("d (1/s)") as HTMLInputElement;
    expect(screen.getAllByRole("slider")).toHaveLength(3);
    expect(d).toHaveAttribute("aria-valuetext", "0,2 1/s");
    const vorher = vi.mocked(createSimLoop).mock.calls.length;
    fireEvent.change(d, { target: { value: "50" } });
    fireEvent.pointerUp(d);
    expect(vi.mocked(createSimLoop).mock.calls.length).toBe(vorher + 1);
    const neu = vi.mocked(createSimLoop).mock.calls.at(-1)![0].input as EigenBlock;
    expect(neu.parameter.find((p) => p.name === "d")!.wert).toBe(0.5);
    expect(demoBlock(0).parameter.find((p) => p.name === "d")!.wert).toBe(0.2);          // die Ansicht selbst bleibt
    f.run(0.3);
    expect(d).toHaveAttribute("aria-valuetext", "0,5 1/s");
    expect(screen.getByText(/Parameter: g 9,81 m\/s², l 1 m, d 0,5 1\/s\. Mit den Reglern geändert; geliefert: .*d 0,2 1\/s\./)).toBeInTheDocument();
    click("Zurück auf die gelieferten Werte");
    expect(d).toHaveAttribute("aria-valuetext", "0,2 1/s");
  });

  it("Tasten: Pfeile, Bild auf/ab, Pos1/Ende; mit Strg, Alt oder Meta bleibt die Taste beim Browser", () => {
    recordingCtx(); const f = fakeFrames();
    card(demoBlock(0));
    const d = screen.getByLabelText("d (1/s)") as HTMLInputElement;
    d.focus();
    expect(fireEvent.keyDown(d, { key: "ArrowRight" })).toBe(false);                    // preventDefault: der Regler nimmt die Taste
    f.run(0.3);
    expect(d).toHaveAttribute("aria-valuetext", "0,21 1/s");
    for (const mod of [{ ctrlKey: true }, { altKey: true }, { metaKey: true }]) expect(fireEvent.keyDown(d, { key: "ArrowRight", ...mod })).toBe(true);
    f.run(0.3);
    expect(d).toHaveAttribute("aria-valuetext", "0,21 1/s");
    fireEvent.keyDown(d, { key: "End" }); f.run(0.3);
    expect(d).toHaveAttribute("aria-valuetext", "5 1/s");
    fireEvent.keyDown(d, { key: "Home" }); f.run(0.3);
    expect(d).toHaveAttribute("aria-valuetext", "0 1/s");
  });
});

describe("Last: verdeckt, weniger Bewegung, Aufräumen", () => {
  it("verdecktes Fenster rechnet und zeichnet nichts und holt danach nichts nach", () => {
    const r = recordingCtx(), f = fakeFrames();
    let hidden = false;
    Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
    try {
      card({ ...demoBlock(2), laufzeit: 60 } as EigenBlock);
      f.run(1);
      click("Pause");
      const t1 = num(row("Zeit in der Simulation"));
      click("Weiter");
      hidden = true;
      const n = r.count("clearRect");
      f.run(5);
      expect(r.count("clearRect")).toBe(n);
      hidden = false;
      f.run(0.2);
      expect(r.count("clearRect")).toBeGreaterThan(n);
      click("Pause");
      const t2 = num(row("Zeit in der Simulation"));
      expect(t2 - t1).toBeLessThan(0.3);
    } finally {
      delete (document as unknown as { hidden?: boolean }).hidden;
    }
  });

  it("weniger Bewegung: Standbild aus der Vorausrechnung, keine Schleife, „Trotzdem abspielen“ startet sie", () => {
    const r = recordingCtx(), f = fakeFrames();
    reducedMotion();
    card(demoBlock(1));
    expect(f.raf).not.toHaveBeenCalled();
    expect(word()).toBe("Standbild, weniger Bewegung ist eingestellt");
    expect(screen.getByText(/^Standbild: der Verlauf über die ersten 30 s/)).toBeInTheDocument();
    expect(r.count("lineTo")).toBeGreaterThan(100);                                    // Zeitreihe und Phasenraum vorausgerechnet
    expect(canvases()[0].getAttribute("aria-label")).toMatch(/Standbild/);
    click("Trotzdem abspielen");
    expect(word()).toBe("läuft");
    expect(f.pending()).toBe(1);
  });

  it("Abbau räumt Schleife, Zeitgeber und Listener ab", () => {
    recordingCtx(); const f = fakeFrames();
    const mq = reducedMotion();
    vi.mocked(window.matchMedia).mockImplementation(((q: string) =>
      ({ matches: false, media: q, addEventListener: mq.add, removeEventListener: mq.rem })) as unknown as typeof window.matchMedia);
    const clear = vi.spyOn(window, "clearTimeout");
    const v = card(demoBlock(0));
    f.run(0.2);
    fireEvent.change(screen.getByLabelText("d (1/s)"), { target: { value: "40" } });
    expect(f.pending()).toBe(1);
    v.unmount();
    expect(f.pending()).toBe(0);
    expect(mq.rem).toHaveBeenCalledTimes(mq.add.mock.calls.length);
    expect(clear).toHaveBeenCalled();
  });
});

describe("Nichts senden, speichern oder abspielen", () => {
  const bedieneAlles = (f: ReturnType<typeof fakeFrames>) => {
    for (const t of ["doppelt", "halb", "normal"]) { fireEvent.click(btn(t)); f.run(0.2); }
    for (const s of screen.getAllByRole("slider") as HTMLInputElement[]) {
      s.focus();
      fireEvent.change(s, { target: { value: String(Number(s.value) + 3) } });
      fireEvent.pointerUp(s);
      for (const key of ["ArrowRight", "ArrowLeft", "PageUp", "End", "Home", "Enter", " "]) { fireEvent.keyDown(s, { key }); fireEvent.keyUp(s, { key }); }
      fireEvent.blur(s);
      f.run(0.2);
    }
    fireEvent.click(btn("Zurück auf die gelieferten Werte")); f.run(0.2);
    click("Pause"); click("Weiter"); f.run(0.2); click("Neu starten"); f.run(0.2);
  };

  it("Speicher, Netz und Ton bleiben unberührt", () => {
    recordingCtx(); const f = fakeFrames();
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const fetchSpy = vi.fn(), idbOpen = vi.fn(), audio = vi.fn(), ctx = vi.fn(), speak = vi.fn(), ws = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    vi.stubGlobal("indexedDB", { open: idbOpen });
    vi.stubGlobal("Audio", audio);
    vi.stubGlobal("AudioContext", ctx);
    vi.stubGlobal("webkitAudioContext", ctx);
    vi.stubGlobal("WebSocket", ws);
    vi.stubGlobal("speechSynthesis", { speak, cancel: vi.fn() });
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
    for (let i = 0; i < 4; i++) { const v = card(demoBlock(i)); bedieneAlles(f); v.unmount(); }
    for (const spy of [setItem, fetchSpy, idbOpen, audio, ctx, speak, play, ws]) expect(spy).not.toHaveBeenCalled();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.querySelector("audio, video, iframe, object, embed, img, a")).toBeNull();
  });

  it("über die Vorführung: Bedienen lässt die gesendeten Nachrichten unverändert", async () => {
    recordingCtx(); const f = fakeFrames();
    const sock: { current?: MockSocket } = {};
    const loader = async () => ({ client: new ApiClient({ port: 5000, token: TOKEN }, (u) => (sock.current = new MockSocket(u, TOKEN))) });
    render(<App load={loader} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    sock.current!.show(EIGEN_DEMOS[0]);
    await waitFor(() => screen.getByRole("heading", { name: String(EIGEN_DEMOS[0].titel) }), { timeout: 3000 });
    await waitFor(() => expect(word()).toBe("läuft"));
    const pollTypes = new Set(["voice.state", ...sock.current!.sent.map((x) => (x as { type: string }).type)]);
    const before = JSON.stringify(sock.current!.sent);
    bedieneAlles(f);
    expect(JSON.stringify(sock.current!.sent)).toBe(before);
    await new Promise((res) => setTimeout(res, 1200));
    const later = sock.current!.sent.map((x) => (x as { type: string }).type);
    expect(later.filter((t) => !pollTypes.has(t))).toEqual([]);
  }, 15_000);
});

describe("Geänderte Parameter über einen neuen zeige-Aufruf", () => {
  it("dieselbe id mit neuem seq nennt kurz „d: 0,2 → 0,5 1/s“, danach verschwindet der Satz", () => {
    recordingCtx(); fakeFrames();
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const v1 = parseItem({ ...EIGEN_DEMOS[0], seq: 1 }) as View, v2 = parseItem({ ...EIGEN_GEAENDERT, seq: 2 }) as View;
    expect(v1.id).toBe(v2.id);
    const c = render(cardEl(v1));
    expect(screen.queryByText(/Geändert/)).toBeNull();
    c.rerender(cardEl(v1));
    expect(screen.queryByText(/Geändert/)).toBeNull();
    c.rerender(cardEl(v2));
    const satz = screen.getByText("Geändert: d: 0,2 → 0,5 1/s.");
    expect(satz).toHaveAttribute("role", "status");
    expect(screen.getByLabelText("d (1/s)")).toHaveAttribute("aria-valuetext", "0,5 1/s");
    act(() => { vi.advanceTimersByTime(13_000); });
    expect(screen.queryByText(/Geändert/)).toBeNull();
  });

  it("andere Gleichungen: ein Satz ohne Rohdaten; eine andere Ansicht: nichts", () => {
    recordingCtx(); fakeFrames();
    const b = demoBlock(0), b2 = kopie(b) as EigenBlock;
    (b2 as unknown as { dt: number }).dt = 0.005;
    const c = render(cardEl(view(b, { seq: 1 })));
    c.rerender(cardEl(view(b2, { seq: 2 })));
    expect(screen.getByText("Weitere Angaben wurden geändert.")).toBeInTheDocument();
    c.unmount();
    const c2 = render(cardEl(view(zerfall(), { seq: 1 })));
    c2.rerender(cardEl(view({ typ: "text", absaetze: ["x"] }, { seq: 2 })));
    c2.rerender(cardEl(view(b, { seq: 3 })));
    expect(screen.queryByText(/Geändert|Weitere Angaben/)).toBeNull();
  });

  it("über die Vorführung: zweimal dieselbe id zeigt die Änderung", async () => {
    recordingCtx(); fakeFrames();
    const sock: { current?: MockSocket } = {};
    const loader = async () => ({ client: new ApiClient({ port: 5000, token: TOKEN }, (u) => (sock.current = new MockSocket(u, TOKEN))) });
    render(<App load={loader} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    sock.current!.show(EIGEN_DEMOS[0]);
    await waitFor(() => screen.getByLabelText("d (1/s)"), { timeout: 3000 });
    sock.current!.show(EIGEN_GEAENDERT);
    await waitFor(() => screen.getByText("Geändert: d: 0,2 → 0,5 1/s."), { timeout: 3000 });
  }, 15_000);
});

describe("Bühne", () => {
  it("parseItem kennt sim_eigen; höchstens zwei Simulationen je Ansicht, eigene zählen mit", () => {
    recordingCtx(); fakeFrames();
    expect((parseItem({ seq: 1, id: "x", art: "simulation", titel: "t", bausteine: [ZERFALL] }) as View).bausteine).toHaveLength(1);
    card([zerfall(), { typ: "simulation", modell: "pendel", parameter: { laenge: 1, winkel: 30, anfangsgeschwindigkeit: 0, daempfung: 0, g: 9.81 },
      laufzeit: 30, tempo: 0, spur: true, beschreibung: "" } as unknown as Block, zerfall()]);
    expect(screen.getByText("Weitere Simulation nicht gezeigt: höchstens 2 je Ansicht.")).toBeInTheDocument();
    expect(document.querySelectorAll(".v-eigen")).toHaveLength(1);
  });

  it("Teilchen mit Körpern und Pfeilen: zwei Bilder, feste Teilchen als Quadrat, Pfeile für die Geschwindigkeit", () => {
    const r = recordingCtx(); const f = fakeFrames();
    card({
      typ: "sim_eigen", form: "teilchen", name: "Drei", beschreibung: "", parameter: [], dt: 0.001, laufzeit: 60, tempo: 1, spur: false,
      anzahl: 3, start: "liste", punkte: [[1, 1, 0, 0], [2, 2, 0.5, -0.5], [3, 1, 0, 0]], startwert: 7, masse: 2, kraft: null, paar: null,
      federn: { paare: [[0, 2]], k: 5, l0: 1, daempfung: 0 }, fest: [1], waende: "periodisch", kasten: [10, 5], kennwerte: [], erhaltung: null,
      darstellung: [{ form: "koerper" }, { form: "pfeile" }], env: { kraft: ["t", "x", "y", "vx", "vy", "m"], paar: ["r"] }, integrator: "verlet", kosten: 1,
    } as unknown as EigenBlock);
    expect(canvases()).toHaveLength(2);
    expect(canvases()[1].getAttribute("aria-label")).toMatch(/^Bild der Teilchen mit Pfeilen für die Geschwindigkeit\. Zeit 0 s\. 3 Teilchen, davon 1 fest\./);
    expect(r.count("fillRect")).toBeGreaterThanOrEqual(2);                              // das feste Teilchen in beiden Bildern
    f.run(0.5);
    expect(r.count("strokeRect")).toBeGreaterThan(0);                                   // Kasten
    expect(screen.getByText(/Pfeile zeigen Richtung und Geschwindigkeit/)).toBeInTheDocument();
    expect(screen.queryByRole("slider")).toBeNull();
  });

  it("Texte aus den Daten stehen nur im DOM, nie im Bild", () => {
    const r = recordingCtx(); fakeFrames();
    card(demoBlock(1));
    expect(r.count("fillText")).toBe(0);
    expect(r.count("strokeText")).toBe(0);
    expect(r.count("drawImage")).toBe(0);
  });
});

describe("Funde der Prüfung: Budget, Prototyp, kleine Bereiche, Endlosschleife", () => {
  /** 300 Teilchen ohne Formeln, dt 1e-5, Tempo 100: vorher etwa 45 Mio. Teilchenschritte je Bild. */
  const VIELE = {
    typ: "sim_eigen", form: "teilchen", name: "Staub", beschreibung: "", parameter: [], dt: 1e-5, laufzeit: 30, tempo: 100, spur: true,
    anzahl: 300, start: "gitter", punkte: [], startwert: 1, masse: 1, kraft: null, paar: null, federn: null, fest: [], waende: "reflektieren",
    kasten: [10, 10], kennwerte: [], erhaltung: null, darstellung: [{ form: "koerper" }], env: { kraft: ["t", "x", "y", "vx", "vy", "m"], paar: ["r"] },
    integrator: "verlet", kosten: 300,
  } as unknown as EigenBlock;
  const ode1 = (p: { name: string; wert: number; min: number; max: number; einheit?: string }[]) =>
    zerfall({ parameter: p.map((q) => ({ einheit: "", ...q })), env: { ode: ["t", "u", ...p.map((q) => q.name)] } });
  const grenze = (p: { name: string; wert: number; min: number; max: number }) => eigenRegler(ode1([p]))[0];

  it("die Ansicht aus dem Fund bleibt je Bild unter einem festen Rechenaufwand und sagt „Zeitlupe“", () => {
    recordingCtx(); const f = fakeFrames();
    expect(createEigen(VIELE).kostenJeSchritt).toBe(300);
    card(VIELE);
    const loop = vi.mocked(createSimLoop).mock.results.at(-1)!.value as ReturnType<typeof createSimLoop>;
    let maxK = 0;
    for (let i = 0; i < 30; i++) { f.frame(1000 / 30); maxK = Math.max(maxK, loop.getState().koerperSchritte); }
    expect(maxK).toBeGreaterThan(0);
    expect(maxK).toBeLessThanOrEqual(MAX_KOERPER_SCHRITTE);
    expect(word()).toBe("Zeitlupe, Rechengrenze erreicht");
  });

  it("das Standbild rechnet hart begrenzt voraus", () => {
    const t0 = Date.now();
    const v = vorausBild(VIELE);
    expect(v.koerperSchritte).toBeLessThanOrEqual(VORAUS_KOERPER_MAX);
    expect(v.knoten).toBeLessThanOrEqual(VORAUS_KNOTEN_MAX);
    expect(Date.now() - t0).toBeLessThan(2000);
    const schwer = vorausBild({ ...demoBlock(2), laufzeit: 60, tempo: 100 });
    expect(schwer.knoten).toBeLessThanOrEqual(VORAUS_KNOTEN_MAX);
    expect(schwer.knoten).toBeGreaterThan(VORAUS_KNOTEN_MAX - KNOTEN_BUDGET);
  });

  it("weniger Bewegung: das Standbild wird nach einer Reglerbewegung entprellt neu gerechnet", () => {
    recordingCtx(); fakeFrames(); reducedMotion();
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    card(demoBlock(0));
    expect(vi.mocked(advanceEigen).mock.calls.length).toBeGreaterThan(0);              // erstes Standbild sofort
    vi.mocked(advanceEigen).mockClear();
    const d = screen.getByLabelText("d (1/s)");
    for (const v of ["30", "40", "50"]) { fireEvent.change(d, { target: { value: v } }); act(() => { vi.advanceTimersByTime(100); }); }
    expect(vi.mocked(advanceEigen)).not.toHaveBeenCalled();                            // während des Ziehens nichts
    act(() => { vi.advanceTimersByTime(1000); });
    const n = vi.mocked(advanceEigen).mock.calls.length;
    expect(n).toBeGreaterThan(0);
    expect(n).toBeLessThanOrEqual(600);                                                 // genau ein Standbild, nicht eines je Bewegung
    expect(d).toHaveAttribute("aria-valuetext", "0,5 1/s");
  });

  it("Parameter „constructor“ und „toString“ lesen nie Object.prototype", () => {
    recordingCtx(); const f = fakeFrames();
    card(ode1([{ name: "constructor", wert: 1, min: 0, max: 2 }, { name: "toString", wert: 0.5, min: 0, max: 1 }]));
    const c = screen.getByLabelText("constructor"), t = screen.getByLabelText("toString");
    expect(c).toHaveAttribute("aria-valuetext", "1");
    expect(t).toHaveAttribute("aria-valuetext", "0,5");
    fireEvent.change(c, { target: { value: "150" } });                                  // nur constructor gezogen: toString bleibt
    expect(t).toHaveAttribute("aria-valuetext", "0,5");
    expect(c).toHaveAttribute("aria-valuetext", "1,5");
    f.run(0.3);
    expect(document.querySelector(".v-eigen")!.textContent).not.toMatch(/function|native code|\[object/);
    const neu = vi.mocked(createSimLoop).mock.calls.at(-1)![0].input as EigenBlock;
    expect(neu.parameter.map((p) => p.wert)).toEqual([1.5, 0.5]);
  });

  it("kleine Bereiche: Stellen aus dem Logarithmus, Pfeiltaste und Mitte ergeben sinnvolle Werte", () => {
    const G = grenze({ name: "G", wert: 6.674e-11, min: 0, max: 1e-10 });
    expect(G.schritt).toBe(1e-12);
    expect(wertAusPos(G, 50)).toBe(5e-11);
    expect(wertFuerTaste(G, 6.674e-11, "ArrowRight")).toBe(6.8e-11);
    expect(wertFuerTaste(G, 6.674e-11, "ArrowLeft")).toBe(6.6e-11);
    const L = grenze({ name: "k", wert: 1e-11, min: 1e-12, max: 1e-9 });
    expect(L.skala).toBe("log");
    expect(wertAusPos(L, 500)).toBe(3.16e-11);
    expect(wertAusPos(L, 0)).toBe(1e-12);
    expect(wertAusPos(L, 1000)).toBe(1e-9);
    const r = wertFuerTaste(L, 1e-11, "ArrowRight")!;
    expect(r).toBeGreaterThan(1e-11);
    expect(r).toBeLessThan(1.1e-11);
    const M = grenze({ name: "m", wert: 0, min: 0, max: 2e-6 });
    expect(wertAusPos(M, 100)).toBe(1e-6);
    expect(wertFuerTaste(M, 0, "ArrowRight")).toBe(1e-8);
    expect(wertFuerTaste(M, 1e-6, "PageUp")).toBe(1.1e-6);
    expect(zahlText(6.674e-11)).toBe("6,674 · 10^-11");
    expect(zahlText(0.5)).toBe("0,5");
  });

  it("kleiner Bereich in der Ansicht: Mitte ziehen und Taste, Wert mit Zehnerpotenz", async () => {
    recordingCtx(); const f = fakeFrames();
    card(ode1([{ name: "G", wert: 6.674e-11, min: 0, max: 1e-10, einheit: "m³/(kg s²)" }]));
    const g = screen.getByLabelText("G (m³/(kg s²))");
    expect(g).toHaveAttribute("aria-valuetext", "6,674 · 10^-11 m³/(kg s²)");
    fireEvent.change(g, { target: { value: "50" } });
    expect(g).toHaveAttribute("aria-valuetext", "5 · 10^-11 m³/(kg s²)");
    f.run(0.3);
    fireEvent.keyDown(g, { key: "ArrowRight" }); f.run(0.3);
    expect(g).toHaveAttribute("aria-valuetext", "5,1 · 10^-11 m³/(kg s²)");
    await act(() => new Promise((res) => setTimeout(res, 450)));                      // der Regler-Takt (200 ms) übernimmt den letzten Wert
    expect((vi.mocked(createSimLoop).mock.calls.at(-1)![0].input as EigenBlock).parameter[0].wert).toBe(5.1e-11);
  });

  it("verschwindender Bereich: keine Endlosschleife, kein Regler, nur eine feste Zahl", () => {
    const g: GrenzFeld = { feld: "p", name: "p", einheit: "", min: 0, max: 1e-323, schritt: 0, skala: "linear" };
    expect(reglerBedienbar(g)).toBe(false);
    for (const key of ["ArrowRight", "ArrowLeft", "PageUp", "PageDown"]) expect(wertFuerTaste(g, 0, key)).toBe(0);
    expect(wertFuerTaste({ ...g, schritt: NaN }, NaN, "ArrowRight")).toBe(0);
    expect(wertFuerTaste({ ...g, max: 1, schritt: 1e-300 }, 0.5, "ArrowRight")).toBe(0.5);   // zu viele Stufen: keine Suche
    recordingCtx(); fakeFrames();
    card(ode1([{ name: "p", wert: 0, min: 0, max: 1e-323 }, { name: "q", wert: 1, min: 0, max: 2 }]));
    expect(screen.getAllByRole("slider")).toHaveLength(1);
    expect(screen.getByText("Ohne Regler (der Bereich ist zu klein): p 0.")).toBeInTheDocument();
    const q = screen.getByLabelText("q");
    expect(fireEvent.keyDown(q, { key: "ArrowRight" })).toBe(false);
  });
});
