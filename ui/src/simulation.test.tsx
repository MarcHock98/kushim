import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Profiler } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { ViewCard } from "./components/stage/ViewCard";
import { ApiClient } from "./lib/api";
import { STATE_VIEW } from "./lib/avatarState";
import { DEMO_VIEWS, MockSocket } from "./lib/mock";
import {
  createSim, formatFest, formatZahl, GRENZEN, mitWert, MODELLE, normalizeSim, snapshot, standbild, type NKoerperKern, type SimModell, type SimSnapshot,
} from "./lib/physics";
import { createSimLoop } from "./lib/simLoop";
import { ART_LABEL, parseItem, type Block, type SimBlock, type View } from "./lib/stage";

// P5a (docs/ui-p5-plan.md, Abschnitte 3 bis 6 und 10): Baustein `simulation` mit falschem requestAnimationFrame und falscher Uhr.
// Kernregeln: der feste Satz „Simulation, keine Messung“ ist immer da; Bedienen ändert nur die Anzeige und sendet nie etwas;
// bei „weniger Bewegung“ läuft keine Schleife; Texte aus den Daten stehen nur im DOM, nie im Bild.

vi.mock("./lib/physics", async (orig) => {
  const m = await orig<typeof import("./lib/physics")>();
  return { ...m, snapshot: vi.fn(m.snapshot), standbild: vi.fn(m.standbild), mitWert: vi.fn(m.mitWert) };
});
vi.mock("./lib/simLoop", async (orig) => {
  const m = await orig<typeof import("./lib/simLoop")>();
  return { ...m, createSimLoop: vi.fn(m.createSimLoop) };
});

const TOKEN = "t".repeat(43);
const REDUCE = "(prefers-reduced-motion: reduce)";
afterEach(() => {
  cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals();
  vi.mocked(standbild).mockClear(); vi.mocked(snapshot).mockClear(); vi.mocked(mitWert).mockClear();
});

type Call = { name: string; args: unknown[] };
/** Zeichenfläche, die jeden Aufruf und jede gesetzte Eigenschaft mitschreibt. `fail` wirft bei diesem Aufruf. */
function recordingCtx(fail?: string, failWhen?: () => boolean) {
  const calls: Call[] = [];
  const ctx = new Proxy({}, {
    get: (_t, k) => (k === "canvas" ? null : (...args: unknown[]) => {
      if (k === fail && (!failWhen || failWhen())) throw new Error("kaputt");
      calls.push({ name: String(k), args });
    }),
    set: (_t, k, v) => { calls.push({ name: `set:${String(k)}`, args: [v] }); return true; },
  });
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation((() => ctx) as unknown as typeof HTMLCanvasElement.prototype.getContext);
  return { calls, count: (n: string) => calls.filter((c) => c.name === n).length };
}

/** Falscher Bildtakt und falsche Uhr: `frame` bietet ein Bild nach `ms` an, `run` viele Bilder mit `hz`. */
function fakeFrames() {
  let t = performance.now(), id = 0;
  const q = new Map<number, FrameRequestCallback>();
  const raf = vi.fn((cb: FrameRequestCallback) => { q.set(++id, cb); return id; });
  const caf = vi.fn((i: number) => { q.delete(i); });
  vi.stubGlobal("requestAnimationFrame", raf);
  vi.stubGlobal("cancelAnimationFrame", caf);
  vi.spyOn(performance, "now").mockImplementation(() => t);
  const frame = (ms = 1000 / 60) => act(() => { t += ms; const cbs = [...q.values()]; q.clear(); for (const cb of cbs) cb(t); });
  const run = (sec: number, hz = 60, each?: () => void) => { for (let i = 0, n = Math.round(sec * hz); i < n; i++) { frame(1000 / hz); each?.(); } };
  return { raf, caf, frame, run, pending: () => q.size };
}

function fakeObserver() {
  const ios: { cb: (e: { isIntersecting: boolean }[]) => void; observed: Element[]; disconnected: boolean }[] = [];
  vi.stubGlobal("IntersectionObserver", class {
    rec: (typeof ios)[number];
    constructor(cb: (e: { isIntersecting: boolean }[]) => void) { this.rec = { cb, observed: [], disconnected: false }; ios.push(this.rec); }
    observe(el: Element) { this.rec.observed.push(el); }
    unobserve() {}
    disconnect() { this.rec.disconnected = true; }
    takeRecords() { return []; }
  });
  return ios;
}

function reducedMotion() {
  vi.spyOn(window, "matchMedia").mockImplementation(((q: string) =>
    ({ matches: q === REDUCE, media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() })) as unknown as typeof window.matchMedia);
}

/** „Weniger Bewegung“ zum Umschalten: `set` ändert die Abfrage und ruft alle angemeldeten Rückrufe (wie das Ereignis `change`). */
function mediaControl(initial: boolean) {
  let matches = initial;
  const listeners = new Set<() => void>();
  const add = vi.fn((_type: string, h: () => void) => { listeners.add(h); });
  const rem = vi.fn((_type: string, h: () => void) => { listeners.delete(h); });
  vi.spyOn(window, "matchMedia").mockImplementation(((q: string) =>
    ({ get matches() { return q === REDUCE && matches; }, media: q, addEventListener: add, removeEventListener: rem })) as unknown as typeof window.matchMedia);
  return { add, rem, listeners, set: (v: boolean) => { matches = v; act(() => { for (const h of [...listeners]) h(); }); } };
}

/** Falscher ResizeObserver: `fire` meldet allen Beobachtern eine neue Größe. */
function fakeResize() {
  const ros: { cb: (e: { contentRect: { width: number; height: number } }[]) => void }[] = [];
  vi.stubGlobal("ResizeObserver", class {
    constructor(cb: (e: { contentRect: { width: number; height: number } }[]) => void) { ros.push({ cb }); }
    observe() {}
    unobserve() {}
    disconnect() {}
  });
  return { fire: (width: number, height: number) => act(() => { for (const r of ros) r.cb([{ contentRect: { width, height } }]); }) };
}

const base = { laufzeit: 30, tempo: 0, spur: true, beschreibung: "" };
const BLOCKS: Record<SimModell, Record<string, unknown>> = {
  pendel: { modell: "pendel", parameter: { laenge: 1, winkel: 30, anfangsgeschwindigkeit: 0, daempfung: 0, g: 9.81 } },
  feder: { modell: "feder", parameter: { masse: 1, federkonstante: 10, auslenkung: 0.5, daempfung: 0 } },
  wurf: { modell: "wurf", parameter: { geschwindigkeit: 20, winkel: 45, hoehe: 0, g: 9.81, luftwiderstand: 0 } },
  umlauf: { modell: "umlauf", parameter: { zentralmasse: 1, koerper: [
    { name: "Erde", abstand: 1, exzentrizitaet: 0.0167, phase: 0, farbe: "arc" },
    { name: "Mars", abstand: 1.52, exzentrizitaet: 0.093, phase: 90, farbe: "alarm" }] } },
  gas: { modell: "gas", parameter: { anzahl: 40, kasten: [100, 60], radius: 1.5, geschwindigkeit: 0.5, schwerkraft: 0, stoesse: true, startwert: 3 } },
};
const sim = (m: SimModell, extra: Record<string, unknown> = {}) => ({ typ: "simulation", ...base, ...BLOCKS[m], ...extra }) as SimBlock;
const view = (b: Block, extra: Partial<View> = {}): View => ({ seq: 1, id: "s1", art: "simulation", titel: "Titel", stand: "", bausteine: [b], ...extra });
const cardEl = (b: Block, extra: Partial<View> = {}) => <ViewCard view={view(b, extra)} sys={null} sysNo={false} onClose={() => undefined} />;
const card = (b: Block, extra: Partial<View> = {}) => render(cardEl(b, extra));
const btn = (name: string | RegExp) => screen.getByRole("button", { name });
const click = (name: string | RegExp) => fireEvent.click(btn(name));
const word = () => document.querySelector(".s-state")!.textContent;
const row = (name: string) => [...document.querySelectorAll(".s-figures tr")].find((tr) => tr.querySelector("th")?.textContent === name)?.querySelector("td")?.textContent ?? "";
const num = (s: string) => Number.parseFloat(s.replace(/ /g, "").replace(",", "."));
const canvases = () => [...document.querySelectorAll(".v-sim canvas")];
const FIXED = "Simulation, keine Messung";

describe("Zeichnen und fester Satz", () => {
  it.each(MODELLE)("%s: fester Satz, Startbild gezeichnet, Zustand in Worten, Textfassung da", (m) => {
    const r = recordingCtx(), f = fakeFrames();
    card(sim(m));
    expect(screen.getByText(FIXED)).toBeInTheDocument();
    expect(r.count("clearRect")).toBeGreaterThan(0);                                    // Startbild sofort
    expect(r.count("arc")).toBeGreaterThan(0);                                          // Körper
    expect(word()).toBe("läuft");
    expect(document.querySelector(".s-state")).toHaveAttribute("aria-live", "polite");
    expect(f.pending()).toBe(1);
    expect(screen.getByText(createSim(sim(m)).text)).toBeInTheDocument();
    expect(!!screen.queryByText("Die Körper ziehen sich gegenseitig nicht an.")).toBe(m === "umlauf");
    expect(screen.queryByText(/angepasst/)).toBeNull();
    expect(screen.getByRole("img")).toHaveAttribute("aria-label", expect.stringMatching(/Beschreibung steht darunter/));
    const n = r.count("clearRect");
    f.run(1);
    expect(r.count("clearRect")).toBeGreaterThan(n + 20);                               // läuft wirklich, höchstens 30 Bilder je Sekunde
    expect(r.count("clearRect")).toBeLessThanOrEqual(n + 31 + (m === "gas" ? 2 : 0));  // Gas: dazu einmal je Sekunde die Balken
    const nums = r.calls.filter((c) => ["arc", "moveTo", "lineTo", "fillRect", "strokeRect"].includes(c.name)).flatMap((c) => c.args);
    expect(nums.every((v) => typeof v === "number" && Number.isFinite(v))).toBe(true);
  });

  it("Spur: Pendel mit spur zeichnet sie, ohne spur nicht, Gas nie", () => {
    const alpha = (r: ReturnType<typeof recordingCtx>) => r.calls.filter((c) => c.name === "set:globalAlpha" && c.args[0] === 0.45).length;
    for (const [b, expected] of [[sim("pendel"), true], [sim("pendel", { spur: false }), false], [sim("gas"), false]] as const) {
      const r = recordingCtx(), f = fakeFrames();
      const v = card(b);
      f.run(1);
      expect(alpha(r) > 0, (b as { modell: string }).modell).toBe(expected);
      v.unmount();
      vi.restoreAllMocks(); vi.unstubAllGlobals();
    }
  });

  it("die Zeichenfläche folgt dem Ausschnitt mit Pixeldichte höchstens 1,5", () => {
    recordingCtx(); fakeFrames();
    vi.stubGlobal("devicePixelRatio", 3);
    card(sim("gas"));
    const c = canvases()[0] as HTMLCanvasElement;
    const cssH = Number.parseFloat(c.style.height);
    expect(cssH).toBeGreaterThanOrEqual(180);
    expect(cssH).toBeLessThanOrEqual(420);
    expect(c.width).toBe(Math.round(640 * 1.5));                                         // ohne Messung 640 px breit
    expect(c.height).toBe(Math.round(cssH * 1.5));
  });
});

describe("Bedienen", () => {
  it("Pause und Weiter wechseln das Wort und halten oder starten die Bilder; derselbe Knopf behält den Fokus", () => {
    const r = recordingCtx(), f = fakeFrames();
    card(sim("pendel", { laufzeit: 60 }));
    f.run(1);
    const b = btn("Pause");
    expect(b.tagName).toBe("BUTTON");
    expect(b).toHaveAttribute("type", "button");
    b.focus();
    click("Pause");
    expect(word()).toBe("pausiert");
    expect(f.pending()).toBe(0);
    expect(btn("Weiter")).toBe(b);
    expect(document.activeElement).toBe(b);
    const n = r.count("clearRect");
    f.run(2);
    expect(r.count("clearRect")).toBe(n);
    click("Weiter");
    expect(word()).toBe("läuft");
    expect(f.pending()).toBe(1);
    f.run(0.5);
    expect(r.count("clearRect")).toBeGreaterThan(n);
  });

  it("Neu starten setzt auf Zeit 0 zurück, auch nach dem Stopp", () => {
    recordingCtx(); const f = fakeFrames();
    card(sim("pendel", { laufzeit: 5 }));
    f.run(2);
    click("Pause");
    expect(num(row("Zeit in der Simulation"))).toBeGreaterThan(0);
    click("Neu starten");
    expect(word()).toBe("läuft");
    expect(row("Zeit in der Simulation")).toBe("0 s");
    f.run(6);
    expect(word()).toBe("angehalten nach 5 s");
    click("Neu starten");
    expect(word()).toBe("läuft");
    expect(row("Zeit in der Simulation")).toBe("0 s");
    expect(f.pending()).toBe(1);
  });

  it("hält nach der Laufzeit an: Wort, kein Bild mehr bestellt, Pause ist gesperrt", () => {
    const r = recordingCtx(), f = fakeFrames();
    card(sim("pendel", { laufzeit: 5 }));
    f.run(6);
    expect(word()).toBe("angehalten nach 5 s");
    expect(f.pending()).toBe(0);
    expect(btn("Pause")).toHaveAttribute("aria-disabled", "true");
    click("Pause");
    expect(word()).toBe("angehalten nach 5 s");
    const n = r.count("clearRect");
    f.run(1);
    expect(r.count("clearRect")).toBe(n);
    expect(f.pending()).toBe(0);
  });

  it("ein Wurf endet mit „gelandet nach … s“ und bestellt nichts mehr", () => {
    recordingCtx(); const f = fakeFrames();
    const b = sim("wurf", { laufzeit: 60 });
    card(b);
    for (let i = 0; i < 20 * 60 && word() === "läuft"; i++) f.frame();
    expect(word()).toBe(`gelandet nach ${formatFest(createSim(b).periode, 1)} s`);
    expect(word()).toMatch(/^gelandet nach \d+,\d s$/);
    expect(f.pending()).toBe(0);
    expect(num(row("Höhe jetzt"))).toBe(0);
  });
});

describe("Last: verdeckt, außer Sicht, instabil", () => {
  it("verdecktes Fenster rechnet nichts und holt danach nichts nach", () => {
    const r = recordingCtx(), f = fakeFrames();
    let hidden = false;
    Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
    try {
      const b = sim("pendel", { laufzeit: 60 });
      card(b);
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
      expect(t2).toBeGreaterThan(t1);
      expect(t2 - t1).toBeLessThan(0.2 * createSim(b).tempo + 0.06);                   // die 5 verdeckten Sekunden fehlen
    } finally {
      delete (document as unknown as { hidden?: boolean }).hidden;
    }
  });

  it("außer Sicht gescrollt (IntersectionObserver): kein Bild, danach weiter", () => {
    const ios = fakeObserver(), r = recordingCtx(), f = fakeFrames();
    card(sim("pendel", { laufzeit: 60 }));
    expect(ios).toHaveLength(1);
    expect(ios[0].observed[0]).toBe(document.querySelector(".v-sim"));
    f.run(1);
    act(() => ios[0].cb([{ isIntersecting: false }]));
    const n = r.count("clearRect");
    f.run(3);
    expect(r.count("clearRect")).toBe(n);
    act(() => ios[0].cb([{ isIntersecting: true }]));
    f.run(0.3);
    expect(r.count("clearRect")).toBeGreaterThan(n);
  });

  it("ein nicht endliches Ergebnis hält mit „Simulation instabil, angehalten“ an, nie ein Bild mit NaN", () => {
    const r = recordingCtx(), f = fakeFrames();
    const real = vi.mocked(snapshot).getMockImplementation()!;
    let calls = 0;
    vi.mocked(snapshot).mockImplementation((st) => {
      const s = real(st);
      return ++calls > 5 ? { ...s, koerper: [{ ...s.koerper[0], x: Number.NaN }] } : s;
    });
    try {
      card(sim("pendel"));
      f.run(2);
      expect(word()).toBe("Simulation instabil, angehalten");
      expect(f.pending()).toBe(0);
      expect(btn("Pause")).toHaveAttribute("aria-disabled", "true");
      const nums = r.calls.filter((c) => ["arc", "moveTo", "lineTo"].includes(c.name)).flatMap((c) => c.args);
      expect(nums.every((v) => typeof v === "number" && Number.isFinite(v))).toBe(true);
    } finally {
      vi.mocked(snapshot).mockImplementation(real);
    }
  });

  it("ein Zeichenfehler hält die Schleife an und sagt „Simulation kann nicht gezeigt werden.“", () => {
    recordingCtx("arc"); const f = fakeFrames();
    card(sim("pendel"));
    expect(screen.getByText("Simulation kann nicht gezeigt werden.")).toBeInTheDocument();
    expect(screen.getByText(FIXED)).toBeInTheDocument();
    expect(f.pending()).toBe(0);
    f.run(1);
    expect(f.pending()).toBe(0);
  });
});

describe("Weniger Bewegung", () => {
  it.each(MODELLE)("%s: keine Schleife, Standbild und Textfassung, Knopf „Trotzdem abspielen“", (m) => {
    reducedMotion();
    const r = recordingCtx(), f = fakeFrames();
    const b = sim(m);
    const v = card(b);
    expect(f.raf).not.toHaveBeenCalled();
    expect(word()).toBe("Standbild, weniger Bewegung ist eingestellt");
    expect(screen.getByText(FIXED)).toBeInTheDocument();
    expect(screen.getByText(createSim(b).text)).toBeInTheDocument();
    expect(r.count("clearRect")).toBeGreaterThan(0);
    expect(btn("Trotzdem abspielen")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
    expect(screen.getByText("Kennwerte am Start")).toBeInTheDocument();
    if (m === "pendel" || m === "feder") {
      expect(canvases()).toHaveLength(2);                                                // Ausgangslage und Lage-Zeit-Kurve
      expect(screen.getByText(/etwa drei Schwingungen/)).toBeInTheDocument();
      expect(r.count("lineTo")).toBeGreaterThan(100);
    }
    if (m === "wurf") {
      expect(screen.getByText(/Gipfel \(Dreieck\): [\d,]+ m hoch/)).toBeInTheDocument();
      expect(screen.getByText(/Aufprall \(Kreuz\): bei [\d,]+ m Weite nach 2,9 s/)).toBeInTheDocument();
      expect(r.count("lineTo")).toBeGreaterThan(100);                                    // ganze Bahn
    }
    if (m === "umlauf") {
      expect(screen.getByText("Alle Bahnen als Linien, die Körper in ihrer Startlage.")).toBeInTheDocument();
      expect(r.count("closePath")).toBeGreaterThanOrEqual(2);
    }
    if (m === "gas") {
      expect(screen.getByText(/Verteilung der Geschwindigkeiten nach [\d,]+ s gerechneter Zeit/)).toBeInTheDocument();
      expect(r.count("fillRect")).toBeGreaterThanOrEqual(1);
    }
    expect(standbild).toHaveBeenCalledTimes(1);
    v.rerender(cardEl(b));                                                               // neu zeichnen der Seite rechnet nicht neu
    expect(standbild).toHaveBeenCalledTimes(1);
    f.run(1);
    expect(f.raf).not.toHaveBeenCalled();
  });

  it("„Trotzdem abspielen“ startet die Animation für diese Ansicht und gibt den Fokus an Pause", () => {
    reducedMotion();
    recordingCtx(); const f = fakeFrames();
    card(sim("pendel"));
    click("Trotzdem abspielen");
    expect(f.raf).toHaveBeenCalled();
    expect(word()).toBe("läuft");
    expect(document.activeElement).toBe(btn("Pause"));
    expect(screen.queryByRole("button", { name: "Trotzdem abspielen" })).toBeNull();
    f.run(1);
    expect(num(row("Zeit in der Simulation"))).toBeGreaterThan(0);
  });
});

describe("Aufräumen", () => {
  it("Abbauen und neue Daten bauen die Schleife ab: kein Bild bestellt, kein Beobachter übrig", () => {
    const ios = fakeObserver(); recordingCtx(); const f = fakeFrames();
    const v = card(sim("pendel"));
    f.run(0.5);
    expect(f.pending()).toBe(1);
    v.rerender(cardEl(sim("feder")));                                                   // gleiche seq, neue Daten
    expect(ios).toHaveLength(2);
    expect(ios[0].disconnected).toBe(true);
    expect(f.caf).toHaveBeenCalled();
    expect(f.pending()).toBe(1);
    expect(screen.getByText(createSim(sim("feder")).text)).toBeInTheDocument();
    v.rerender(cardEl(sim("pendel"), { seq: 2 }));                                      // neue Ansicht mit derselben id: von vorn
    expect(ios).toHaveLength(3);
    expect(ios[1].disconnected).toBe(true);
    expect(f.pending()).toBe(1);
    expect(row("Zeit in der Simulation")).toBe("0 s");
    v.unmount();
    expect(f.pending()).toBe(0);
    expect(ios.every((o) => o.disconnected)).toBe(true);
    f.run(1);
    expect(f.pending()).toBe(0);
  });
});

describe("Text bleibt Text", () => {
  it("Beschreibung und Körpernamen stehen nur als Text im DOM, nie im Bild, in keinem Attribut", () => {
    const r = recordingCtx(), f = fakeFrames();
    const evil = "<script>alert(1)</script><b>x</b>", name = "<img src=x onerror=alert(1)>", other = "url(#evil)";
    const b = sim("umlauf", { beschreibung: evil, parameter: { zentralmasse: 1, koerper: [
      { name, abstand: 1, exzentrizitaet: 0, phase: 0, farbe: "arc" }, { name: other, abstand: 2, exzentrizitaet: 0.1, phase: 10, farbe: "ok" }] } });
    const { container } = card(b);
    f.run(1);
    expect(screen.getByText(evil)).toBeInTheDocument();
    expect(screen.getByText(name)).toBeInTheDocument();
    expect(screen.getByText(other)).toBeInTheDocument();
    expect(r.count("fillText") + r.count("strokeText")).toBe(0);
    const strings = r.calls.flatMap((c) => c.args).filter((a) => typeof a === "string") as string[];
    expect(strings.some((s) => s.includes("img") || s.includes("script") || s.includes("evil"))).toBe(false);
    expect(container.querySelector(".v-sim script, .v-sim img, .v-sim b, .v-sim a, .v-sim [href]")).toBeNull();
    for (const el of container.querySelectorAll("*")) {
      for (const at of el.attributes) expect([evil, name, other].some((s) => at.value.includes(s)), at.name).toBe(false);
    }
  });
});

describe("Hinweise", () => {
  it("ungültige Eingabe: „Simulation kann nicht gezeigt werden.“ statt Bild, keine Schleife, kein Standbild", () => {
    recordingCtx(); const f = fakeFrames();
    card({ typ: "simulation", modell: "quatsch", parameter: {} } as unknown as Block);
    expect(screen.getByText("Simulation kann nicht gezeigt werden.")).toBeInTheDocument();
    expect(screen.getByText(FIXED)).toBeInTheDocument();
    expect(canvases()).toHaveLength(0);
    expect(f.raf).not.toHaveBeenCalled();
    expect(standbild).not.toHaveBeenCalled();
  });

  it("angepasste Werte: kurzer Hinweis, die Simulation läuft trotzdem", () => {
    recordingCtx(); const f = fakeFrames();
    card(sim("pendel", { parameter: { laenge: 500, winkel: 30, anfangsgeschwindigkeit: 0, daempfung: 0, g: 9.81 } }));
    expect(screen.getByText(/wurden angepasst/)).toBeInTheDocument();
    expect(word()).toBe("läuft");
    expect(f.pending()).toBe(1);
  });

  it("ohne Canvas-Kontext: Hinweistext statt Absturz, keine Schleife, Textfassung bleibt", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation((() => null) as unknown as typeof HTMLCanvasElement.prototype.getContext);
    const f = fakeFrames();
    const b = sim("gas");
    card(b);
    expect(screen.getByText(/Das Bild kann hier nicht gezeichnet werden/)).toBeInTheDocument();
    expect(f.raf).not.toHaveBeenCalled();
    expect(screen.getByText(createSim(b).text)).toBeInTheDocument();
    expect(screen.getByText("Kennwerte am Start")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
    expect(screen.getByText(FIXED)).toBeInTheDocument();
  });
});

describe("Kennwerte", () => {
  it("werden höchstens etwa zweimal je Sekunde neu gesetzt, nicht jedes Bild; die Zahlen sind nicht live angesagt", () => {
    const r = recordingCtx(), f = fakeFrames();
    card(sim("pendel", { laufzeit: 60 }));
    let last = row("Winkel jetzt"), changes = 0;
    const n0 = r.count("clearRect");
    f.run(3, 60, () => { const now = row("Winkel jetzt"); if (now !== last) { changes++; last = now; } });
    expect(r.count("clearRect") - n0).toBeGreaterThan(80);                              // etwa 90 Bilder
    expect(changes).toBeGreaterThanOrEqual(4);
    expect(changes).toBeLessThanOrEqual(7);
    expect(document.querySelector(".s-figures")!.closest("[aria-live]")).toBeNull();
  });

  it("Gas: Verteilung als Balken und als Zahlen", () => {
    recordingCtx(); fakeFrames();
    card(sim("gas"));
    const rows = document.querySelectorAll(".s-dist tbody tr");
    expect(rows).toHaveLength(10);
    expect([...rows].reduce((s, tr) => s + Number(tr.querySelector("td.num")!.textContent), 0)).toBe(40);
    expect(rows[9].textContent).toMatch(/^ab /);
    expect(document.querySelector(".s-dist canvas")).toHaveAttribute("aria-hidden", "true");
  });
});

describe("Kein Klick sendet etwas", () => {
  it("Pause, Weiter, Neu starten und Tasten lassen die gesendeten Nachrichten unverändert, während die Bilder laufen", async () => {
    recordingCtx(); const f = fakeFrames();
    const sock: { current?: MockSocket } = {};
    const loader = async () => ({ client: new ApiClient({ port: 5000, token: TOKEN }, (u) => (sock.current = new MockSocket(u, TOKEN))) });
    render(<App load={loader} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    sock.current!.show(DEMO_VIEWS.find((v) => v.id === "pendel")!);
    await waitFor(() => screen.getByRole("heading", { name: "Pendel, 1 m (Beispiel)" }), { timeout: 3000 });
    const pollTypes = new Set(sock.current!.sent.map((m) => (m as { type: string }).type));
    const before = JSON.stringify(sock.current!.sent);

    const t0 = row("Zeit in der Simulation");
    f.run(1);
    expect(row("Zeit in der Simulation")).not.toBe(t0);                                 // die Bilder laufen wirklich
    click("Pause"); f.run(0.5);
    click("Weiter"); f.run(0.5);
    click("Neu starten"); f.run(0.5);
    for (const key of ["Enter", " ", "ArrowRight", "Tab"]) fireEvent.keyDown(btn(/Pause|Weiter/), { key });   // Esc schließt die Ansicht (App)
    click("Pause"); click("Neu starten"); f.run(0.5);
    fireEvent.click(screen.getByText("Beschreibung"));
    expect(JSON.stringify(sock.current!.sent)).toBe(before);

    await new Promise((res) => setTimeout(res, 1200));                                   // auch später nur die üblichen Abfragen
    const later = sock.current!.sent.map((m) => (m as { type: string }).type);
    expect(later.filter((t) => !pollTypes.has(t))).toEqual([]);
  }, 15_000);

  it("nichts wird gespeichert, geladen oder abgespielt", () => {
    recordingCtx(); const f = fakeFrames();
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const fetchSpy = vi.fn(), idbOpen = vi.fn(), audio = vi.fn(), ctx = vi.fn(), speak = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    vi.stubGlobal("indexedDB", { open: idbOpen });
    vi.stubGlobal("Audio", audio);
    vi.stubGlobal("AudioContext", ctx);
    vi.stubGlobal("webkitAudioContext", ctx);
    vi.stubGlobal("speechSynthesis", { speak, cancel: vi.fn() });
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());

    card(sim("gas", { laufzeit: 5 }));
    f.run(1); click("Pause"); click("Weiter"); f.run(1); click("Neu starten"); f.run(6); click("Neu starten"); f.run(0.5);
    fireEvent.click(screen.getByText("Verteilung als Zahlen"));

    for (const spy of [setItem, fetchSpy, idbOpen, audio, ctx, speak, play]) expect(spy).not.toHaveBeenCalled();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.querySelector("audio, video, iframe, object, embed")).toBeNull();
  });
});

describe("Bühne und Vorführung", () => {
  it("parseItem kennt Art und Baustein simulation, Beschriftung „Simulation“", () => {
    const v = parseItem({ seq: 1, id: "s", art: "simulation", titel: "T", bausteine: [{ typ: "simulation" }, { typ: "film" }] }) as View;
    expect(v.art).toBe("simulation");
    expect(v.bausteine.map((b) => b.typ)).toEqual(["simulation"]);
    expect(ART_LABEL.simulation).toBe("Simulation");
  });

  it("die drei Beispiele (Pendel, Wurf, Gas mit etwa 60 Teilchen) sind vollständig wie vom Backend und zeigen sich ohne Hinweis", () => {
    recordingCtx(); fakeFrames();
    const raw = DEMO_VIEWS.slice(17, 20);
    expect(raw.map((v) => v.id)).toEqual(["pendel", "wurf", "gas"]);
    const KEYS: Record<string, string[]> = {
      pendel: ["anfangsgeschwindigkeit", "daempfung", "g", "laenge", "winkel"],
      wurf: ["g", "geschwindigkeit", "hoehe", "luftwiderstand", "winkel"],
      gas: ["anzahl", "geschwindigkeit", "kasten", "radius", "schwerkraft", "startwert", "stoesse"],
    };
    raw.forEach((r, i) => {
      expect(Object.keys(r).sort()).toEqual(["art", "bausteine", "id", "schliessen", "stand", "titel"]);
      const v = parseItem({ ...r, seq: i + 1 }) as View;
      expect(v.art).toBe("simulation");
      const b = v.bausteine[0] as SimBlock;
      expect(Object.keys(b).sort()).toEqual(["beschreibung", "laufzeit", "modell", "parameter", "spur", "tempo", "typ"]);
      expect(Object.keys(b.parameter).sort()).toEqual(KEYS[b.modell]);
      const cfg = normalizeSim(b);
      expect(cfg.angepasst).toEqual([]);
      expect(cfg.ungueltig).toBe(false);
      if (b.modell === "gas") { expect(b.parameter.anzahl).toBeGreaterThanOrEqual(50); expect(b.parameter.anzahl).toBeLessThanOrEqual(70); }
      const c = render(<ViewCard view={v} sys={null} sysNo={false} onClose={() => undefined} />);
      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.queryByText(/angepasst|kann nicht gezeigt|nicht gezeichnet/)).toBeNull();
      expect(screen.getByText(FIXED)).toBeInTheDocument();
      expect(screen.getByText(b.beschreibung)).toBeInTheDocument();
      c.unmount();
    });
  });

  it("der Startwert im Gas ist fest: gleiche Daten, gleiches Startbild", () => {
    const a: SimSnapshot = createSim(sim("gas")).startBild, b2: SimSnapshot = createSim(sim("gas")).startBild;
    expect(a.koerper).toEqual(b2.koerper);
  });
});

const STILL = "Standbild, weniger Bewegung ist eingestellt";

describe("Weniger Bewegung ohne Kontext und im Betrieb", () => {
  it("ohne Zeichenkontext gibt es keinen Knopf „Trotzdem abspielen“; Standbildtext und Hinweis bleiben", () => {
    reducedMotion();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation((() => null) as unknown as typeof HTMLCanvasElement.prototype.getContext);
    const f = fakeFrames();
    card(sim("pendel"));
    expect(screen.queryByRole("button", { name: "Trotzdem abspielen" })).toBeNull();
    expect(document.querySelectorAll(".s-controls button")).toHaveLength(0);
    expect(screen.getByText(/Das Bild kann hier nicht gezeichnet werden/)).toBeInTheDocument();
    expect(word()).toBe(STILL);
    expect(screen.getByText(/etwa drei Schwingungen/)).toBeInTheDocument();
    expect(screen.getByText("Kennwerte am Start")).toBeInTheDocument();
    expect(screen.getByText(createSim(sim("pendel")).text)).toBeInTheDocument();
    expect(f.raf).not.toHaveBeenCalled();
  });

  it("der Wechsel zu „weniger Bewegung“ im Betrieb baut die Schleife ab und zeigt das Standbild; beim Abbauen wird der Rückruf entfernt", () => {
    const mc = mediaControl(false); recordingCtx(); const f = fakeFrames();
    const v = card(sim("pendel", { laufzeit: 60 }));
    f.run(0.5);
    expect(f.pending()).toBe(1);
    expect(mc.add).toHaveBeenCalledWith("change", expect.any(Function));
    const handler = mc.add.mock.calls[0][1];
    mc.set(true);
    expect(f.pending()).toBe(0);
    expect(word()).toBe(STILL);
    expect(btn("Trotzdem abspielen")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
    expect(screen.getByText(/etwa drei Schwingungen/)).toBeInTheDocument();
    const n = f.raf.mock.calls.length;
    f.run(1);
    expect(f.raf.mock.calls.length).toBe(n);
    mc.set(false);                                                                      // und zurück: die Schleife läuft wieder
    expect(word()).toBe("läuft");
    expect(f.pending()).toBe(1);
    v.unmount();
    expect(mc.rem).toHaveBeenCalledWith("change", handler);
    expect(mc.listeners.size).toBe(0);
    expect(f.pending()).toBe(0);
  });

  it("neue Daten nach „Trotzdem abspielen“ zeigen wieder das Standbild und den Knopf", () => {
    reducedMotion(); recordingCtx(); const f = fakeFrames();
    const v = card(sim("pendel"));
    click("Trotzdem abspielen");
    f.run(0.5);
    expect(word()).toBe("läuft");
    v.rerender(cardEl(sim("feder")));
    expect(word()).toBe(STILL);
    expect(f.pending()).toBe(0);
    expect(btn("Trotzdem abspielen")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
    expect(screen.getByText(/etwa drei Schwingungen/)).toBeInTheDocument();
    click("Trotzdem abspielen");                                                        // und für die neuen Daten wieder möglich
    expect(word()).toBe("läuft");
    expect(f.pending()).toBe(1);
  });
});

describe("Zeitlupe, Neu starten, Last, Fehler", () => {
  it("Gas mit 300 Teilchen und hohem Tempo sagt „Zeitlupe, Rechengrenze erreicht“, ohne dass etwas wirft", () => {
    recordingCtx(); const f = fakeFrames();
    card(sim("gas", { tempo: 100, laufzeit: 60, parameter: { ...(BLOCKS.gas.parameter as object), anzahl: 300 } }));
    const seen = new Set<string>();
    expect(() => f.run(3, 60, () => seen.add(word() ?? ""))).not.toThrow();
    expect(seen.has("Zeitlupe, Rechengrenze erreicht")).toBe(true);
  });

  it("Neu starten nach der Landung: „läuft“, Zeit 0, ein Bild bestellt", () => {
    recordingCtx(); const f = fakeFrames();
    card(sim("wurf", { laufzeit: 60 }));
    for (let i = 0; i < 20 * 60 && word() === "läuft"; i++) f.frame();
    expect(word()).toMatch(/^gelandet nach /);
    expect(f.pending()).toBe(0);
    click("Neu starten");
    expect(word()).toBe("läuft");
    expect(row("Zeit in der Simulation")).toBe("0 s");
    expect(f.pending()).toBe(1);
  });

  it("Neu starten nach „Simulation instabil, angehalten“: „läuft“, Zeit 0, ein Bild bestellt", () => {
    recordingCtx(); const f = fakeFrames();
    const real = vi.mocked(snapshot).getMockImplementation()!;
    let kaputt = false;
    vi.mocked(snapshot).mockImplementation((st) => {
      const s = real(st);
      return kaputt ? { ...s, koerper: [{ ...s.koerper[0], x: Number.NaN }] } : s;
    });
    try {
      card(sim("pendel"));
      f.run(0.5);
      kaputt = true;
      f.run(0.5);
      expect(word()).toBe("Simulation instabil, angehalten");
      expect(f.pending()).toBe(0);
      kaputt = false;
      click("Neu starten");
      expect(word()).toBe("läuft");
      expect(row("Zeit in der Simulation")).toBe("0 s");
      expect(f.pending()).toBe(1);
      f.run(1);
      expect(num(row("Zeit in der Simulation"))).toBeGreaterThan(0);
    } finally {
      vi.mocked(snapshot).mockImplementation(real);
    }
  });

  it("React-Arbeit: in 10 s bei 60 Hz höchstens 25 Aufbauten der Ansicht (Pendel), nicht ein Aufbau je Bild", () => {
    recordingCtx(); const f = fakeFrames();
    let commits = 0;
    render(<Profiler id="sim" onRender={() => { commits++; }}>{cardEl(sim("pendel", { laufzeit: 60 }))}</Profiler>);
    const c0 = commits;
    f.run(10);
    expect(word()).toBe("läuft");
    expect(commits - c0).toBeGreaterThan(5);                                            // die Kennwerte laufen wirklich weiter
    expect(commits - c0).toBeLessThanOrEqual(25);
  });

  it("ein Zeichenfehler beim Start trennt den Beobachter (IntersectionObserver)", () => {
    const ios = fakeObserver(); recordingCtx("arc"); const f = fakeFrames();
    card(sim("pendel"));
    expect(screen.getByText("Simulation kann nicht gezeigt werden.")).toBeInTheDocument();
    expect(ios.length).toBeGreaterThan(0);
    expect(ios.every((o) => o.disconnected)).toBe(true);
    expect(f.pending()).toBe(0);
  });

  it("ein Zeichenfehler mitten im Lauf trennt den Beobachter und hält die Schleife an", () => {
    let kaputt = false;
    const ios = fakeObserver(); recordingCtx("arc", () => kaputt); const f = fakeFrames();
    card(sim("pendel", { laufzeit: 60 }));
    f.run(0.5);
    expect(ios).toHaveLength(1);
    expect(ios[0].disconnected).toBe(false);
    kaputt = true;
    f.run(0.3);
    expect(screen.getByText("Simulation kann nicht gezeigt werden.")).toBeInTheDocument();
    expect(ios.every((o) => o.disconnected)).toBe(true);
    expect(f.pending()).toBe(0);
    f.run(1);
    expect(f.pending()).toBe(0);
  });
});

describe("Kein Klick sendet etwas, auch bei „weniger Bewegung“", () => {
  const raw = (m: string): Record<string, unknown> => m === "umlauf"
    ? { id: "umlauf", art: "simulation", titel: "Umlaufbahnen (Beispiel)", stand: "", schliessen: false, bausteine: [sim("umlauf")] }
    : DEMO_VIEWS.find((v) => v.id === m)!;

  it.each(["pendel", "gas", "umlauf"])("%s: „Trotzdem abspielen“, Pause, Weiter, Neu starten und „Verteilung als Zahlen“ sind echte Knöpfe und senden nichts", async (m) => {
    reducedMotion(); recordingCtx(); const f = fakeFrames();
    const sock: { current?: MockSocket } = {};
    const loader = async () => ({ client: new ApiClient({ port: 5000, token: TOKEN }, (u) => (sock.current = new MockSocket(u, TOKEN))) });
    render(<App load={loader} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    const v = raw(m);
    sock.current!.show(v);
    await waitFor(() => screen.getByRole("heading", { name: String(v.titel) }), { timeout: 3000 });
    await waitFor(() => expect(word()).toBe(STILL));
    const pollTypes = new Set(["voice.state", ...sock.current!.sent.map((x) => (x as { type: string }).type)]);   // voice.state ist eine übliche Abfrage der App
    const before = JSON.stringify(sock.current!.sent);

    /** Jeden Knopf prüfen (echter Knopf, bedienbar, fokussierbar) und dann nach dem Fokus anklicken. */
    const pressAll = () => {
      const bs = [...document.querySelectorAll<HTMLButtonElement>(".s-controls button, .s-regler button")];
      expect(bs.length).toBeGreaterThan(1);
      expect(bs.at(-1)!.textContent).toBe("Zurück auf die Werte von Claude");
      for (const b of bs) {
        expect(b.tagName).toBe("BUTTON");
        expect(b.type).toBe("button");
        expect(b.disabled).toBe(false);
        expect(b.tabIndex).toBeGreaterThanOrEqual(0);
        b.focus();
        expect(document.activeElement).toBe(b);
        fireEvent.click(b);
      }
    };
    /** Jeden Regler ziehen und mit Tasten bedienen (beim Standbild rechnet das nur das Standbild neu). */
    const regler = () => {
      for (const s of screen.getAllByRole("slider") as HTMLInputElement[]) {
        s.focus();
        fireEvent.change(s, { target: { value: String(Number(s.value) + 2) } });
        for (const key of ["ArrowRight", "ArrowLeft", "End", "Home"]) tippe(s, key);
        fireEvent.pointerUp(s);
        fireEvent.blur(s);
      }
    };
    regler();
    expect(word()).toBe(STILL);
    fireEvent.click(btn("Zurück auf die Werte von Claude"));
    regler();
    pressAll();                                                                          // „Trotzdem abspielen“, „Zurück“
    expect(word()).toBe("läuft");
    regler();
    f.run(0.5);
    pressAll(); f.run(0.5);                                                              // Pause, dann Neu starten (läuft wieder)
    pressAll(); f.run(0.5);
    for (const key of ["Enter", " ", "ArrowRight", "Tab"]) fireEvent.keyDown(btn(/Pause|Weiter/), { key });
    if (m === "gas") fireEvent.click(screen.getByText("Verteilung als Zahlen"));
    fireEvent.click(screen.getByText("Beschreibung"));
    expect(JSON.stringify(sock.current!.sent)).toBe(before);

    await new Promise((res) => setTimeout(res, 1200));
    const later = sock.current!.sent.map((x) => (x as { type: string }).type);
    expect(later.filter((t) => !pollTypes.has(t))).toEqual([]);
  }, 15_000);
});

describe("Zeichenfläche: Größe", () => {
  it.each(["pendel", "gas"] as const)("%s: Größe 0 und Verkleinern von 800 auf 375 px: nie NaN oder Infinity, Pixelgröße höchstens 1,5 mal CSS-Größe", (m) => {
    const r = recordingCtx(), f = fakeFrames(), rz = fakeResize();
    vi.stubGlobal("devicePixelRatio", 3);
    card(sim(m, { laufzeit: 60 }));
    const c = canvases()[0] as HTMLCanvasElement;
    const within = (cssW: number) => {
      const cssH = Number.parseFloat(c.style.height);
      expect(Number.isFinite(cssH) && cssH > 0).toBe(true);
      expect(c.width).toBeGreaterThanOrEqual(1);
      expect(c.height).toBeGreaterThanOrEqual(1);
      expect(c.width).toBeLessThanOrEqual(1.5 * cssW + 0.5);                             // Runden darf höchstens ein halbes Pixel zugeben
      expect(c.height).toBeLessThanOrEqual(1.5 * cssH + 0.5);
    };
    rz.fire(0, 0); f.run(0.2); within(640);                                              // Größe 0 wird ignoriert: Standardbreite
    rz.fire(800, 500); f.run(0.2); within(800);
    rz.fire(375, 300); f.run(0.2); within(375);
    rz.fire(50, 40); f.run(0.2); within(120);                                            // untere Grenze der Breite
    expect(r.count("clearRect")).toBeGreaterThan(0);
    const nums = r.calls.flatMap((x) => x.args).filter((a) => typeof a === "number");
    expect(nums.length).toBeGreaterThan(0);
    expect(nums.every((v) => Number.isFinite(v))).toBe(true);
  });
});

// --- P5b (docs/ui-p5-plan.md, Abschnitt 7): Doppelpendel, Welle, Umlauf mit Anziehung, Regler und Tempo ---------------

const P5B: Record<"doppelpendel" | "welle" | "anziehung", Record<string, unknown>> = {
  doppelpendel: { modell: "doppelpendel", parameter: { laenge1: 1, laenge2: 1, masse1: 1, masse2: 1, winkel1: 120, winkel2: -10, g: 9.81, daempfung: 0 } },
  welle: { modell: "welle", parameter: { bereich: 0, wellen: [
    { amplitude: 1, wellenlaenge: 2, frequenz: 0.5, phase: 0, richtung: "rechts" },
    { amplitude: 1, wellenlaenge: 2, frequenz: 0.5, phase: 0, richtung: "links" }] } },
  anziehung: { modell: "umlauf", parameter: { zentralmasse: 1, anziehung: true, koerper: [
    { name: "Innen", abstand: 1, exzentrizitaet: 0, phase: 0, masse: 0.001, farbe: "arc" },
    { name: "Mitte", abstand: 1.6, exzentrizitaet: 0.05, phase: 120, masse: 0.003, farbe: "amber" },
    { name: "Außen", abstand: 2.5, exzentrizitaet: 0.1, phase: 240, masse: 0.001, farbe: "ok" }] } },
};
type P5bName = keyof typeof P5B;
const P5B_NAMEN = Object.keys(P5B) as P5bName[];
const simB = (n: P5bName, extra: Record<string, unknown> = {}) => ({ typ: "simulation", ...base, ...P5B[n], ...extra }) as unknown as SimBlock;
const slider = (name: string) => screen.getByRole("slider", { name }) as HTMLInputElement;
const realMitWert = vi.mocked(mitWert).getMockImplementation()!;
/** Nur setTimeout und clearTimeout falsch (der Regler-Takt); Bildtakt und Uhr kommen aus fakeFrames. */
const fakeTimers = () => vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
const warte = (ms: number) => act(() => { vi.advanceTimersByTime(ms); });
const tippe = (s: HTMLElement, key: string) => { fireEvent.keyDown(s, { key }); fireEvent.keyUp(s, { key }); };
const lastCall = () => vi.mocked(mitWert).mock.calls.at(-1)?.slice(1);
const lastInput = () => vi.mocked(mitWert).mock.results.at(-1)?.value as SimBlock;
const NOTE: Record<P5bName, RegExp | string> = {
  doppelpendel: /^Das Doppelpendel ist chaotisch: Schon eine winzige Änderung am Start ergibt eine ganz andere Bahn\./,
  welle: "Waagerecht der Ort, senkrecht die Auslenkung. Die beiden Achsen haben verschiedene Maßstäbe.",
  anziehung: "Die Körper ziehen sich gegenseitig an.",
};

/** Pfade im letzten Bild der Hauptfläche (ab dem letzten clearRect): Linienbreite und Zahl der lineTo je beginPath. */
function framePaths(calls: Call[]) {
  const start = calls.map((c) => c.name).lastIndexOf("clearRect");
  const out: { width: number; lineTo: number }[] = [];
  let width = 0;
  for (const c of calls.slice(start)) {
    if (c.name === "set:lineWidth") width = c.args[0] as number;
    else if (c.name === "beginPath") out.push({ width, lineTo: 0 });
    else if (c.name === "lineTo" && out.length) out[out.length - 1].lineTo++;
  }
  return out;
}

describe("P5b: neue Modelle zeichnen", () => {
  it.each(P5B_NAMEN)("%s: fester Satz der Oberfläche, Bild, Zustand in Worten, Textfassung", (n) => {
    const r = recordingCtx(), f = fakeFrames();
    const b = simB(n);
    card(b);
    expect(screen.getByText(FIXED)).toBeInTheDocument();
    expect(screen.getByText(NOTE[n])).toBeInTheDocument();
    expect(screen.queryByText(/nicht an\./)).toBeNull();
    expect(screen.getByText(createSim(b).text)).toBeInTheDocument();
    expect(screen.queryByText(/angepasst/)).toBeNull();
    expect(word()).toBe("läuft");
    expect(f.pending()).toBe(1);
    expect(screen.getByRole("group", { name: "Simulation steuern" })).toBeInTheDocument();
    if (n === "welle") expect(screen.getByText(/^Waagerecht: Ort von 0 bis 4 m\. Senkrecht: Auslenkung bis 2 m nach oben und unten/)).toBeInTheDocument();
    if (n === "anziehung") for (const k of ["Innen", "Mitte", "Außen"]) expect(screen.getByText(k)).toBeInTheDocument();
    f.run(1);
    expect(r.count("clearRect")).toBeGreaterThan(20);
    expect(r.count("fillText") + r.count("strokeText")).toBe(0);
    const nums = r.calls.filter((c) => ["arc", "moveTo", "lineTo", "fillRect", "strokeRect"].includes(c.name)).flatMap((c) => c.args);
    expect(nums.length).toBeGreaterThan(0);
    expect(nums.every((v) => typeof v === "number" && Number.isFinite(v))).toBe(true);
  });

  it("Doppelpendel: zwei Arme an der Aufhängung, Spur nur für den unteren Körper; ohne spur keine", () => {
    for (const spur of [true, false]) {
      const r = recordingCtx(), f = fakeFrames();
      const v = card(simB("doppelpendel", { spur }));
      f.run(1);
      const frame = r.calls.slice(r.calls.map((c) => c.name).lastIndexOf("clearRect"));
      const i0 = frame.findIndex((c) => c.name === "set:globalAlpha" && c.args[0] === 0.45);
      if (spur) {
        expect(i0).toBeGreaterThan(0);
        const i1 = frame.findIndex((c, i) => i > i0 && c.name === "set:globalAlpha" && c.args[0] === 1);
        expect(frame.slice(i0, i1).filter((c) => c.name === "stroke")).toHaveLength(1);   // eine Spur: nur der untere Körper
      } else expect(i0).toBe(-1);
      expect(framePaths(r.calls).some((p) => p.lineTo === 2)).toBe(true);                // Aufhängung → oben → unten
      expect(frame.filter((c) => c.name === "arc").length).toBeGreaterThanOrEqual(3);      // zwei Körper und die Aufhängung
      v.unmount();
      vi.restoreAllMocks(); vi.unstubAllGlobals();
    }
  });

  it("Welle: die Summe mit 400 Punkten dick, zwei einzelne Wellen dünn; eine einzelne Welle ohne Teilkurven", () => {
    const r = recordingCtx(), f = fakeFrames();
    const v = card(simB("welle"));
    f.run(0.5);
    const full = framePaths(r.calls).filter((p) => p.lineTo === 399);
    expect(full).toHaveLength(3);
    expect(full.filter((p) => p.width === 2.5)).toHaveLength(1);
    expect(full.filter((p) => p.width === 1)).toHaveLength(2);
    expect(screen.getByText(/Dicke Linie: die Summe\. Dünne Linien: die einzelnen Wellen\./)).toBeInTheDocument();
    v.unmount();
    const eine = simB("welle", { parameter: { bereich: 0, wellen: [{ amplitude: 1, wellenlaenge: 2, frequenz: 0.5, phase: 0, richtung: "rechts" }] } });
    card(eine);
    f.run(0.5);
    expect(framePaths(r.calls).filter((p) => p.lineTo === 399)).toHaveLength(1);
    expect(screen.queryByText(/Dünne Linien/)).toBeNull();
  });

  it("Text bleibt Text auch mit anziehung: Namen und Beschreibung nur im DOM, nie im Bild oder in Attributen", () => {
    const r = recordingCtx(), f = fakeFrames();
    const evil = "<script>alert(1)</script><b>x</b>", name = "<img src=x onerror=alert(1)>", other = "url(#evil)";
    const b = simB("anziehung", { beschreibung: evil, parameter: { zentralmasse: 1, anziehung: true, koerper: [
      { name, abstand: 1, exzentrizitaet: 0, phase: 0, masse: 0.001, farbe: "arc" },
      { name: other, abstand: 2, exzentrizitaet: 0.1, phase: 10, masse: 0.002, farbe: "ok" }] } });
    const { container } = card(b);
    f.run(1);
    fireEvent.change(slider("Zentralmasse"), { target: { value: "600" } });              // auch nach einem Neustart durch den Regler
    f.run(0.5);
    for (const s of [evil, name, other]) expect(screen.getByText(s)).toBeInTheDocument();
    expect(r.count("fillText") + r.count("strokeText")).toBe(0);
    const strings = r.calls.flatMap((c) => c.args).filter((a) => typeof a === "string") as string[];
    expect(strings.some((s) => s.includes("img") || s.includes("script") || s.includes("evil"))).toBe(false);
    expect(container.querySelector(".v-sim script, .v-sim img, .v-sim b, .v-sim a, .v-sim [href]")).toBeNull();
    for (const el of container.querySelectorAll("*")) {
      for (const at of el.attributes) expect([evil, name, other].some((s) => at.value.includes(s)), at.name).toBe(false);
    }
  });

  it("Umlauf ohne anziehung behält den Satz „… nicht an.“", () => {
    recordingCtx(); fakeFrames();
    card(simB("anziehung", { parameter: { ...(P5B.anziehung.parameter as object), anziehung: false } }));
    expect(screen.getByText("Die Körper ziehen sich gegenseitig nicht an.")).toBeInTheDocument();
    expect(screen.queryByText("Die Körper ziehen sich gegenseitig an.")).toBeNull();
  });

  it("Körper außerhalb des Bildausschnitts (Rechenkern zählt) stehen in Worten da", () => {
    recordingCtx(); const f = fakeFrames();
    card(simB("anziehung", { laufzeit: 60 }));
    f.run(0.6);
    expect(screen.queryByText(/außerhalb des Bildausschnitts/)).toBeNull();
    const loop = vi.mocked(createSimLoop).mock.results.at(-1)!.value as ReturnType<typeof createSimLoop>;
    const s = loop.getSim(), k = s.kern as NKoerperKern;
    k.x[0] = s.ausschnitt.maxX + 5; k.y[2] = s.ausschnitt.minY - 5;                     // zwei Körper weit draußen (wie nach einer Streuung)
    expect(snapshot(s).ausserhalb).toBe(2);
    f.frame(); f.frame();
    click("Pause");                                                                       // beim Anhalten stehen die letzten Zahlen da
    expect(screen.getByText("2 Körper außerhalb des Bildausschnitts.")).toBeInTheDocument();
    expect(screen.getAllByText(/außerhalb des Bildausschnitts/)).toHaveLength(1);
  });

  it("Energie: mit Anziehung die Energieabweichung, beim Doppelpendel Prozent des Starts, ohne Anziehung keine", () => {
    recordingCtx(); const f = fakeFrames();
    const has = (name: string) => [...document.querySelectorAll(".s-figures th")].some((th) => th.textContent === name);
    let v = card(simB("anziehung", { laufzeit: 60 }));
    f.run(1); click("Pause");
    expect(row("Energieabweichung")).toMatch(/^-?\d+,\d+ %$/);
    expect(Math.abs(num(row("Energieabweichung")))).toBeLessThan(1);
    expect(has("Gesamtenergie in Prozent des Starts")).toBe(false);
    expect(has("Energie in Prozent des Starts")).toBe(false);
    v.unmount();
    v = card(simB("anziehung", { parameter: { ...(P5B.anziehung.parameter as object), anziehung: false } }));
    expect(has("Energieabweichung")).toBe(false);
    v.unmount();
    card(simB("doppelpendel"));
    expect(has("Energie in Prozent des Starts")).toBe(true);
    expect(has("Energieabweichung")).toBe(false);
  });

  it("Welle über mehr als 50 kürzeste Wellenlängen: der Bereich wird gekürzt, Hinweis, Satz in der Textfassung und Achse in Worten", () => {
    recordingCtx(); fakeFrames();
    const b = simB("welle", { parameter: { bereich: 10000, wellen: [{ amplitude: 1, wellenlaenge: 0.01, frequenz: 0.5, phase: 0, richtung: "rechts" }] } });
    expect(normalizeSim(b).angepasst).toContain("parameter.bereich");
    card(b);
    expect(screen.getByText("Einige Angaben fehlten oder lagen außerhalb der Grenzen und wurden angepasst.")).toBeInTheDocument();
    expect(screen.getByText(/Der gezeigte Bereich wurde auf 0,5 m gekürzt \(50 kürzeste Wellenlängen\), damit die Welle richtig dargestellt wird\./)).toBeInTheDocument();
    expect(screen.getByText(/^Waagerecht: Ort von 0 bis 0,5 m\./)).toBeInTheDocument();
    expect(word()).toBe("läuft");
  });
});

describe("P5b: Regler", () => {
  const ALLE = [...MODELLE.map((m) => [m, sim(m)] as const), ...(["doppelpendel", "welle"] as const).map((n) => [n, simB(n)] as const)];

  it.each(ALLE)("%s: ein beschrifteter Regler je Eintrag in GRENZEN, Wert mit Komma und Einheit", (m, b) => {
    recordingCtx(); fakeFrames();
    card(b);
    const liste = GRENZEN[m];
    expect(screen.getAllByRole("slider")).toHaveLength(liste.length);
    const cfg = normalizeSim(b) as unknown as { parameter: Record<string, unknown> };
    for (const g of liste) {
      const s = slider(g.name);
      expect(s.type).toBe("range");
      expect(s.tabIndex).toBeGreaterThanOrEqual(0);
      const roh = g.feld.split(".").reduce<unknown>((o, k) => (o as Record<string, unknown>)[k], cfg.parameter) as number;
      const txt = `${formatZahl(roh)} ${g.einheit}`;
      expect(s).toHaveAttribute("aria-valuetext", txt);
      expect(s.closest(".s-slider")!.textContent).toContain(txt);                         // sichtbar neben dem Regler
      expect(s.id).toMatch(new RegExp(`^[_:a-z0-9]+-regler-${liste.indexOf(g)}$`, "i"));   // React-id und Nummer, keine Daten
    }
    expect(btn("Zurück auf die Werte von Claude")).toHaveAttribute("aria-disabled", "true");
  });

  it("logarithmische und lineare Skala bilden die Stellung richtig ab", () => {
    fakeTimers(); recordingCtx(); fakeFrames();
    card(sim("pendel"));
    const s = slider("Länge");
    expect(s.max).toBe("1000");
    expect(s.value).toBe("394");                                                          // 1 m auf 0,05 bis 100 m logarithmisch
    fireEvent.change(s, { target: { value: "500" } });                                    // Mitte: √(0,05 · 100) = 2,236 → 2,25 (Schritt 0,05)
    expect(lastCall()).toEqual(["laenge", 2.25]);
    expect(slider("Länge")).toHaveAttribute("aria-valuetext", "2,25 m");
    fireEvent.pointerUp(s); warte(400);
    fireEvent.change(s, { target: { value: "0" } }); fireEvent.pointerUp(s); warte(400);
    expect(lastCall()).toEqual(["laenge", 0.05]);
    fireEvent.change(s, { target: { value: "1000" } }); fireEvent.pointerUp(s); warte(400);
    expect(lastCall()).toEqual(["laenge", 100]);
    const w = slider("Startwinkel");
    expect(w.max).toBe("340");
    expect(w.value).toBe("200");                                                          // 30 Grad auf -170 bis 170, Schritt 1
    fireEvent.change(w, { target: { value: "250" } }); fireEvent.pointerUp(w); warte(400);
    expect(lastCall()).toEqual(["winkel", 80]);
    expect(screen.getByText(/^Regler: Länge 100 m, Startwinkel 80 Grad\./)).toBeInTheDocument();
  });

  it("Tastatur: Pfeil, Ende und Pos1 starten neu mit begrenztem Wert über mitWert; Tasten mit Strg, Alt oder Meta bleiben dem Browser", () => {
    fakeTimers(); recordingCtx(); const f = fakeFrames();
    card(sim("pendel", { laufzeit: 60 }));
    f.run(1);
    const s = slider("Länge");
    s.focus();
    expect(fireEvent.keyDown(s, { key: "ArrowRight" })).toBe(false);                    // vom Regler übernommen
    fireEvent.keyUp(s, { key: "ArrowRight" });
    const [feld, wert] = lastCall() as [string, number];
    expect(feld).toBe("laenge");
    expect(wert).toBeGreaterThan(1);
    expect(wert).toBeLessThan(1.1);
    expect(screen.getByText(createSim(lastInput()).text)).toBeInTheDocument();           // neu gestartet mit der neuen Eingabe
    expect(word()).toBe("läuft");
    expect(row("Zeit in der Simulation")).toBe("0 s");
    expect(f.pending()).toBe(1);
    warte(400);
    tippe(s, "End"); warte(400);
    expect(lastCall()).toEqual(["laenge", 100]);
    expect(slider("Länge")).toHaveAttribute("aria-valuetext", "100 m");
    const n = vi.mocked(mitWert).mock.calls.length;
    for (const key of ["ArrowRight", "ArrowUp", "PageUp", "End"]) { tippe(s, key); warte(400); }
    expect(vi.mocked(mitWert).mock.calls.length).toBe(n);                                 // am Rand: nichts weiter
    for (const mod of [{ ctrlKey: true }, { altKey: true }, { metaKey: true }]) {
      expect(fireEvent.keyDown(s, { key: "Home", ...mod })).toBe(true);
    }
    warte(400);
    expect(vi.mocked(mitWert).mock.calls.length).toBe(n);
    tippe(s, "Home"); warte(400);
    expect(lastCall()).toEqual(["laenge", 0.05]);
    expect(document.activeElement).toBe(s);                                               // der Fokus bleibt auf dem Regler
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([["ArrowLeft", -1], ["ArrowDown", -1], ["PageDown", -1], ["ArrowRight", 1], ["ArrowUp", 1], ["PageUp", 1]] as const)(
    "F1: %s bei 1,234 m geht in Tastenrichtung (logarithmisch, zwischen zwei Stellungen)", (key, dir) => {
      fakeTimers(); recordingCtx(); fakeFrames();
      card(sim("pendel", { parameter: { laenge: 1.234, winkel: 30, anfangsgeschwindigkeit: 0, daempfung: 0, g: 9.81 } }));
      tippe(slider("Länge"), key);
      const [feld, wert] = lastCall() as [string, number];
      expect(feld).toBe("laenge");
      expect(Math.sign(wert - 1.234)).toBe(dir);
      if (key === "ArrowLeft") expect(wert).toBe(1.2);
      if (key === "ArrowRight") expect(wert).toBe(1.25);
    });

  it("F1: jede Pfeiltaste ändert jeden Regler aller Modelle streng in ihrer Richtung, auch von krummen Werten aus", () => {
    fakeTimers(); recordingCtx(); fakeFrames();
    const krumm = [1.234, 0.0777, 3.3333, 17.01, 0.51];
    for (const [m, b] of [...MODELLE.map((x) => [x, sim(x)] as const), ...(["doppelpendel", "welle"] as const).map((n) => [n, simB(n)] as const)]) {
      for (const g of GRENZEN[m]) {
        for (const k of krumm) {
          const roh = g.min + (g.max - g.min) * (k / 20);                                 // innen, nicht auf einer Stellung
          const start = mitWert(b, g.feld, roh);
          for (const [key, dir] of [["ArrowLeft", -1], ["ArrowRight", 1]] as const) {
            const v = card(start);
            vi.mocked(mitWert).mockClear();
            const vor = start.parameter as unknown as Record<string, unknown>;
            const alt = g.feld.split(".").reduce<unknown>((o, t) => (o as Record<string, unknown>)[t], vor) as number;
            tippe(slider(g.name), key);
            const call = lastCall() as [string, number] | undefined;
            if (call) expect(Math.sign(call[1] - alt), `${m} ${g.feld} ${alt} ${key}`).toBe(dir);
            else expect(dir < 0 ? alt <= g.min : alt >= g.max, `${m} ${g.feld} ${alt} ${key} ohne Wert`).toBe(true);
            v.unmount();
            warte(400);
          }
        }
      }
    }
  });

  it("die abgeleitete Grenze der Feder begrenzt den Wert (mitWert), die Anzeige zeigt den begrenzten Wert", () => {
    fakeTimers(); recordingCtx(); fakeFrames();
    card(sim("feder"));
    const s = slider("Federkonstante");
    tippe(s, "End"); warte(400);
    expect(lastCall()).toEqual(["federkonstante", 1e6]);
    const k = (lastInput().parameter as { federkonstante: number }).federkonstante;
    expect(k).toBeLessThan(1e6);                                                          // Schwingungsdauer ≥ 0,05 s bei 1 kg
    expect(2 * Math.PI * Math.sqrt(1 / k)).toBeGreaterThanOrEqual(0.05);
    expect(slider("Federkonstante")).toHaveAttribute("aria-valuetext", `${formatZahl(k)} N/m`);
    expect(screen.queryByText(/wurden angepasst/)).toBeNull();
  });

  it("beim Ziehen höchstens ein Neustart je 200 ms, nach dem Loslassen einmal mit dem letzten Wert", () => {
    fakeTimers(); recordingCtx(); fakeFrames();
    card(simB("doppelpendel"));
    const s = slider("Startwinkel oben");
    expect(s.value).toBe("300");                                                          // 120 Grad auf -180 bis 180
    for (let i = 1; i <= 20; i++) {                                                       // 400 ms ziehen, alle 20 ms ein Schritt
      fireEvent.change(s, { target: { value: String(300 + i) } });
      act(() => { vi.advanceTimersByTime(20); });
    }
    expect(vi.mocked(mitWert)).toHaveBeenCalledTimes(3);                                  // bei 0, 200 und 400 ms
    expect(lastCall()).toEqual(["winkel1", 140]);
    fireEvent.change(s, { target: { value: "321" } });
    expect(vi.mocked(mitWert)).toHaveBeenCalledTimes(3);
    expect(slider("Startwinkel oben")).toHaveAttribute("aria-valuetext", "141 Grad");      // die Anzeige folgt sofort
    fireEvent.pointerUp(s);
    expect(vi.mocked(mitWert)).toHaveBeenCalledTimes(3);                                  // Loslassen wartet den Takt ab
    warte(200);                                                                           // der Takt bei 600 ms bringt den letzten Wert
    expect(vi.mocked(mitWert)).toHaveBeenCalledTimes(4);
    expect(lastCall()).toEqual(["winkel1", 141]);
    expect(screen.getByText(createSim(lastInput()).text)).toBeInTheDocument();
    expect(screen.getByText(/Start bei 141 Grad und -10 Grad/)).toBeInTheDocument();
    warte(1000);
    expect(vi.mocked(mitWert)).toHaveBeenCalledTimes(4);                                  // nichts kommt nach
    expect(vi.getTimerCount()).toBe(0);
  });

  it("30 Neustarts durch Ziehen: immer genau ein Bild bestellt, nach dem Abbau keins und kein Zeitgeber", () => {
    fakeTimers(); recordingCtx(); const f = fakeFrames();
    const v = card(simB("doppelpendel", { laufzeit: 60 }));
    const s = slider("Startwinkel oben");
    for (let i = 1; i <= 30; i++) {
      fireEvent.change(s, { target: { value: String(300 - i) } });
      warte(200);
      f.frame();
      expect(f.pending()).toBe(1);
    }
    expect(vi.mocked(mitWert)).toHaveBeenCalledTimes(30);
    expect(slider("Startwinkel oben")).toHaveAttribute("aria-valuetext", "90 Grad");
    v.unmount();
    expect(f.pending()).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("Abbau mitten im Ziehen: kein Zeitgeber übrig, danach kommt kein Wert mehr", () => {
    fakeTimers(); recordingCtx(); const f = fakeFrames();
    const v = card(sim("pendel"));
    const s = slider("Startwinkel");
    fireEvent.change(s, { target: { value: "210" } });
    fireEvent.change(s, { target: { value: "220" } });                                    // wartet auf den Takt
    expect(vi.mocked(mitWert)).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(1);
    v.unmount();
    expect(vi.getTimerCount()).toBe(0);
    warte(1000);
    expect(vi.mocked(mitWert)).toHaveBeenCalledTimes(1);
    expect(f.pending()).toBe(0);
  });

  it("neue Daten mitten im Ziehen: kein Zeitgeber, kein alter Wert, Tempo wieder „normal“", () => {
    fakeTimers(); recordingCtx(); fakeFrames();
    const v = card(sim("pendel", { laufzeit: 60 }));
    click("doppelt");
    expect(screen.getByText("Tempo: doppelt")).toBeInTheDocument();
    const s = slider("Startwinkel");
    fireEvent.change(s, { target: { value: "210" } });
    fireEvent.change(s, { target: { value: "260" } });
    expect(vi.getTimerCount()).toBe(1);
    v.rerender(cardEl(sim("pendel", { laufzeit: 60, beschreibung: "neu" })));
    expect(vi.getTimerCount()).toBe(0);
    warte(1000);
    expect(vi.mocked(mitWert)).toHaveBeenCalledTimes(1);                                  // der Wert 90 Grad kommt nie an
    expect(slider("Startwinkel")).toHaveAttribute("aria-valuetext", "30 Grad");
    expect(screen.getByText(createSim(sim("pendel")).text)).toBeInTheDocument();
    expect(screen.getByText("Tempo: normal")).toBeInTheDocument();
    expect(btn("normal")).toHaveAttribute("aria-pressed", "true");
    expect(btn("doppelt")).toHaveAttribute("aria-pressed", "false");
    expect(btn("Zurück auf die Werte von Claude")).toHaveAttribute("aria-disabled", "true");
  });

  it.each(["ohne Ereignis", "keyUp", "blur", "touchEnd", "mouseUp", "pointerUp"] as const)(
    "Ende des Ziehens %s: der letzte Wert kommt spätestens nach 200 ms, danach kein Zeitgeber", (ende) => {
      fakeTimers(); recordingCtx(); fakeFrames();
      card(sim("pendel"));
      const s = slider("Startwinkel");
      s.focus();
      fireEvent.change(s, { target: { value: "210" } });
      warte(50);
      fireEvent.change(s, { target: { value: "230" } });
      if (ende !== "ohne Ereignis") fireEvent[ende](s);
      expect(vi.mocked(mitWert)).toHaveBeenCalledTimes(1);
      warte(150);
      expect(vi.mocked(mitWert)).toHaveBeenCalledTimes(2);
      expect(lastCall()).toEqual(["winkel", 60]);
      expect(slider("Startwinkel")).toHaveAttribute("aria-valuetext", "60 Grad");
      warte(200);
      expect(vi.getTimerCount()).toBe(0);
      expect(vi.mocked(mitWert)).toHaveBeenCalledTimes(2);
      expect(screen.getByText(/^Regler: Länge 1 m, Startwinkel 60 Grad\./)).toBeInTheDocument();
    });

  it("Tippen wird gedrosselt wie Ziehen: höchstens ein Neustart je 200 ms und danach einer mit dem letzten Wert", () => {
    fakeTimers(); recordingCtx(); fakeFrames();
    card(sim("pendel"));
    const s = slider("Startwinkel");
    s.focus();
    const zeiten: number[] = [];
    let jetzt = 0;
    vi.mocked(mitWert).mockImplementation((...a) => { zeiten.push(jetzt); return realMitWert(...a); });
    try {
      for (let i = 0; i < 10; i++) { tippe(s, "ArrowRight"); jetzt += 50; warte(50); }     // zehn Tipps in 500 ms
      for (let i = 0; i < 10; i++) { jetzt += 50; warte(50); }
    } finally {
      vi.mocked(mitWert).mockImplementation(realMitWert);
    }
    expect(zeiten).toEqual([0, 200, 400, 600]);                                           // sofort, je 200 ms, dann der letzte
    for (let i = 1; i < zeiten.length; i++) expect(zeiten[i] - zeiten[i - 1]).toBeGreaterThanOrEqual(200);
    expect(lastCall()).toEqual(["winkel", 40]);                                           // 30 Grad plus zehn Schritte
    expect(slider("Startwinkel")).toHaveAttribute("aria-valuetext", "40 Grad");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("„Zurück“ mitten im Ziehen: kein alter Wert kommt später an", () => {
    fakeTimers(); recordingCtx(); fakeFrames();
    card(sim("pendel"));
    const s = slider("Startwinkel");
    fireEvent.change(s, { target: { value: "210" } });
    fireEvent.change(s, { target: { value: "300" } });
    click("Zurück auf die Werte von Claude");
    expect(vi.getTimerCount()).toBe(0);
    warte(1000);
    expect(vi.mocked(mitWert)).toHaveBeenCalledTimes(1);
    expect(slider("Startwinkel")).toHaveAttribute("aria-valuetext", "30 Grad");
    expect(screen.getByText(createSim(sim("pendel")).text)).toBeInTheDocument();
    expect(btn("Zurück auf die Werte von Claude")).toHaveAttribute("aria-disabled", "true");
  });

  it("der Hinweis zur Beschreibung von Claude erscheint nach einer Änderung und geht mit „Zurück“", () => {
    fakeTimers(); recordingCtx(); fakeFrames();
    const HINWEIS = "Die Beschreibung von Claude gilt für die ursprünglichen Werte.";
    card(sim("pendel", { beschreibung: "Ein Pendel bei 30 Grad." }));
    expect(screen.queryByText(HINWEIS)).toBeNull();
    fireEvent.change(slider("Startwinkel"), { target: { value: "250" } });
    expect(screen.getByText(HINWEIS)).toBeInTheDocument();
    expect(screen.getByText("Ein Pendel bei 30 Grad.")).toBeInTheDocument();
    warte(400);
    click("Zurück auf die Werte von Claude");
    expect(screen.queryByText(HINWEIS)).toBeNull();
  });

  it("„Zurück auf die Werte von Claude“ stellt die gelieferten Daten wieder her; die Textfassung nennt beide", () => {
    recordingCtx(); const f = fakeFrames();
    const b = sim("pendel");
    card(b);
    const s = slider("Länge");
    fireEvent.change(s, { target: { value: "500" } }); fireEvent.pointerUp(s);
    expect(screen.getByText(createSim(lastInput()).text)).toBeInTheDocument();
    expect(screen.queryByText(createSim(b).text)).toBeNull();
    expect(screen.getByText(/^Regler: Länge 2,25 m, Startwinkel 30 Grad\. Mit den Reglern geändert; die Werte von Claude: Länge 1 m, Startwinkel 30 Grad\.$/)).toBeInTheDocument();
    const reset = btn("Zurück auf die Werte von Claude");
    expect(reset).not.toHaveAttribute("aria-disabled");
    reset.focus();
    click("Zurück auf die Werte von Claude");
    expect(screen.getByText(createSim(b).text)).toBeInTheDocument();
    expect(slider("Länge")).toHaveAttribute("aria-valuetext", "1 m");
    expect(screen.getByText("Regler: Länge 1 m, Startwinkel 30 Grad.")).toBeInTheDocument();
    expect(btn("Zurück auf die Werte von Claude")).toHaveAttribute("aria-disabled", "true");
    expect(document.activeElement).toBe(reset);
    expect(word()).toBe("läuft");
    expect(f.pending()).toBe(1);
  });

  it("neue Daten verwerfen die Reglerwerte", () => {
    recordingCtx(); fakeFrames();
    const v = card(sim("pendel"));
    const s = slider("Länge");
    fireEvent.change(s, { target: { value: "500" } }); fireEvent.pointerUp(s);
    v.rerender(cardEl(sim("pendel", { beschreibung: "neu" })));
    expect(slider("Länge")).toHaveAttribute("aria-valuetext", "1 m");
    expect(btn("Zurück auf die Werte von Claude")).toHaveAttribute("aria-disabled", "true");
  });
});

describe("P5b: Tempo", () => {
  it("halb, normal, doppelt ändern den Faktor der Schleife und das Wort; Neu starten und Regler behalten ihn", () => {
    recordingCtx(); const f = fakeFrames();
    card(sim("pendel", { tempo: 1, laufzeit: 60 }));
    const group = screen.getByRole("group", { name: "Tempo" });
    expect([...group.querySelectorAll("button")].map((x) => x.textContent)).toEqual(["halb", "normal", "doppelt"]);
    expect(btn("normal")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Tempo: normal")).toBeInTheDocument();
    const lauf = () => { f.run(1); click("Pause"); const t = num(row("Zeit in der Simulation")); return t; };
    const t1 = lauf();
    expect(t1).toBeGreaterThan(0.85); expect(t1).toBeLessThan(1.05);
    click("doppelt");
    expect(btn("doppelt")).toHaveAttribute("aria-pressed", "true");
    expect(btn("normal")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("Tempo: doppelt")).toBeInTheDocument();
    click("Weiter");
    const t2 = lauf() - t1;
    expect(t2).toBeGreaterThan(1.7); expect(t2).toBeLessThan(2.1);
    click("Neu starten");
    expect(screen.getByText("Tempo: doppelt")).toBeInTheDocument();
    const t3 = lauf();
    expect(t3).toBeGreaterThan(1.7); expect(t3).toBeLessThan(2.1);
    const w = slider("Startwinkel");
    fireEvent.change(w, { target: { value: "210" } }); fireEvent.pointerUp(w);             // neuer Lauf mit 40 Grad
    expect(word()).toBe("läuft");
    expect(screen.getByText("Tempo: doppelt")).toBeInTheDocument();
    const t4 = lauf();
    expect(t4).toBeGreaterThan(1.7); expect(t4).toBeLessThan(2.1);
    click("halb"); click("Neu starten");
    expect(screen.getByText("Tempo: halb")).toBeInTheDocument();
    const t5 = lauf();
    expect(t5).toBeGreaterThan(0.4); expect(t5).toBeLessThan(0.55);
  });

  it("in der Zeitlupe sagt die Ansicht, dass das Tempo erst ohne Rechengrenze wirkt", () => {
    recordingCtx(); const f = fakeFrames();
    card(sim("gas", { tempo: 100, laufzeit: 60, parameter: { ...(BLOCKS.gas.parameter as object), anzahl: 300 } }));
    const SATZ = "Tempo wirkt erst, wenn die Rechengrenze nicht erreicht ist.";
    expect(screen.queryByText(SATZ)).toBeNull();
    for (let i = 0; i < 180 && word() !== "Zeitlupe, Rechengrenze erreicht"; i++) f.frame();
    expect(word()).toBe("Zeitlupe, Rechengrenze erreicht");
    expect(screen.getByText(SATZ)).toBeInTheDocument();
    expect(screen.getByText(SATZ).closest(".s-tempo")).not.toBeNull();
  });

  it("eine Schleife ohne setTempoFaktor: keine Tempo-Gruppe, alles andere bleibt", () => {
    recordingCtx(); const f = fakeFrames();
    const real = vi.mocked(createSimLoop).getMockImplementation()!;
    vi.mocked(createSimLoop).mockImplementation((o) => {
      const l = real(o);
      delete l.setTempoFaktor; delete l.getTempoFaktor;
      return l;
    });
    try {
      card(sim("pendel"));
      expect(word()).toBe("läuft");
      expect(screen.queryByRole("group", { name: "Tempo" })).toBeNull();
      expect(screen.queryByRole("button", { name: "doppelt" })).toBeNull();
      expect(btn("Pause")).toBeInTheDocument();
      expect(screen.getAllByRole("slider")).toHaveLength(2);
      f.run(0.5);
      expect(f.pending()).toBe(1);
    } finally {
      vi.mocked(createSimLoop).mockImplementation(real);
    }
  });

  it("bei „weniger Bewegung“ kein Tempo (keine Schleife), nach „Trotzdem abspielen“ schon", () => {
    reducedMotion(); recordingCtx(); fakeFrames();
    card(simB("doppelpendel"));
    expect(screen.queryByRole("group", { name: "Tempo" })).toBeNull();
    expect(screen.getAllByRole("slider")).toHaveLength(2);
    click("Trotzdem abspielen");
    expect(screen.getByRole("group", { name: "Tempo" })).toBeInTheDocument();
    expect(btn("normal")).toHaveAttribute("aria-pressed", "true");
  });
});

describe("P5b: weniger Bewegung", () => {
  it.each(P5B_NAMEN)("%s: keine Schleife, das neue Standbild mit Erklärung, Regler rechnen nur das Standbild neu", (n) => {
    reducedMotion();
    const r = recordingCtx(), f = fakeFrames();
    const b = simB(n);
    card(b);
    expect(f.raf).not.toHaveBeenCalled();
    expect(word()).toBe(STILL);
    expect(screen.getByText(FIXED)).toBeInTheDocument();
    expect(screen.getByText(NOTE[n])).toBeInTheDocument();
    expect(screen.getByText(createSim(b).text)).toBeInTheDocument();
    expect(btn("Trotzdem abspielen")).toBeInTheDocument();
    expect(standbild).toHaveBeenCalledTimes(1);
    const dashes = r.calls.filter((c) => c.name === "setLineDash" && (c.args[0] as number[]).length > 0).length;
    if (n === "doppelpendel") {
      expect(screen.getByText(/^Gestrichelt: der Weg des unteren Körpers in den ersten [\d,]+ s\. Die Arme stehen in der Startlage\.$/)).toBeInTheDocument();
      expect(dashes).toBeGreaterThanOrEqual(1);
      expect(r.count("lineTo")).toBeGreaterThan(100);
    }
    if (n === "welle") {
      expect(screen.getByText(/Gestrichelt: die Hülle, .* über [\d,]+ s\. Die Hülle ist genau gerechnet\./)).toBeInTheDocument();
      expect(framePaths(r.calls).filter((p) => p.lineTo === 399)).toHaveLength(5);       // Summe, zwei Wellen, Hülle unten und oben
      expect(dashes).toBeGreaterThanOrEqual(1);
    }
    if (n === "anziehung") {
      expect(screen.getByText(/^Die gerechneten Wege über [\d,]+ Jahre als offene Linien, die Körper in ihrer Startlage\.$/)).toBeInTheDocument();
      expect(r.count("closePath")).toBe(0);                                               // offen, keine geschlossenen Ellipsen
      expect(r.count("lineTo")).toBeGreaterThan(100);
    }
    const s = screen.getAllByRole("slider")[0];
    fireEvent.change(s, { target: { value: String(Number(s.getAttribute("value")) + 5) } }); fireEvent.pointerUp(s);
    expect(standbild).toHaveBeenCalledTimes(2);
    expect(word()).toBe(STILL);
    f.run(1);
    expect(f.raf).not.toHaveBeenCalled();
  });

  it("Welle mit verschiedenen Frequenzen: die Hülle ist abgetastet und die Ansicht sagt es", () => {
    reducedMotion(); recordingCtx(); fakeFrames();
    card(simB("welle", { parameter: { bereich: 0, wellen: [
      { amplitude: 1, wellenlaenge: 2, frequenz: 0.5, phase: 0, richtung: "rechts" },
      { amplitude: 0.5, wellenlaenge: 1, frequenz: 1.5, phase: 90, richtung: "links" }] } }));
    expect(screen.getByText(/Die Hülle ist nur abgetastet und kann etwas zu eng sein\./)).toBeInTheDocument();
  });
});

describe("P5b: Bedienen sendet, speichert und spielt nichts", () => {
  /** Alle neuen Bedienelemente einmal: Tempo, jeder Regler mit Ziehen und Tasten, Zurück, dazu Pause, Weiter, Neu starten. */
  const bedieneAlles = (f: ReturnType<typeof fakeFrames>) => {
    for (const t of ["doppelt", "halb", "normal"]) { const b = btn(t) as HTMLButtonElement; expect(b.type).toBe("button"); b.focus(); fireEvent.click(b); f.run(0.2); }
    for (const s of screen.getAllByRole("slider") as HTMLInputElement[]) {
      expect(s.tagName).toBe("INPUT");
      s.focus();
      expect(document.activeElement).toBe(s);
      fireEvent.change(s, { target: { value: String(Number(s.value) + 3) } });
      fireEvent.pointerUp(s);
      for (const key of ["ArrowRight", "ArrowLeft", "PageUp", "End", "Home", "Enter", " "]) { fireEvent.keyDown(s, { key }); fireEvent.keyUp(s, { key }); }
      fireEvent.keyDown(s, { key: "ArrowRight", ctrlKey: true });
      fireEvent.blur(s);
      f.run(0.2);
    }
    const reset = btn("Zurück auf die Werte von Claude") as HTMLButtonElement;
    expect(reset.type).toBe("button");
    fireEvent.click(reset); f.run(0.2);
    click("Pause"); click("Weiter"); f.run(0.2); click("Neu starten"); f.run(0.2);
  };

  it.each([...P5B_NAMEN, "pendel", "wurf", "gas"])("%s (Vorführung): Tempo, Regler, Zurück und Tasten lassen die gesendeten Nachrichten unverändert", async (n) => {
    recordingCtx(); const f = fakeFrames();
    const sock: { current?: MockSocket } = {};
    const loader = async () => ({ client: new ApiClient({ port: 5000, token: TOKEN }, (u) => (sock.current = new MockSocket(u, TOKEN))) });
    render(<App load={loader} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    const v = DEMO_VIEWS.find((x) => x.id === n)!;
    sock.current!.show(v);
    await waitFor(() => screen.getByRole("heading", { name: String(v.titel) }), { timeout: 3000 });
    await waitFor(() => expect(word()).toBe("läuft"));
    const pollTypes = new Set(["voice.state", ...sock.current!.sent.map((x) => (x as { type: string }).type)]);
    const before = JSON.stringify(sock.current!.sent);
    bedieneAlles(f);
    fireEvent.click(screen.getByText("Beschreibung"));
    expect(JSON.stringify(sock.current!.sent)).toBe(before);
    await new Promise((res) => setTimeout(res, 1200));
    const later = sock.current!.sent.map((x) => (x as { type: string }).type);
    expect(later.filter((t) => !pollTypes.has(t))).toEqual([]);
  }, 15_000);

  it("nichts wird gespeichert, geladen oder abgespielt", () => {
    recordingCtx(); const f = fakeFrames();
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const fetchSpy = vi.fn(), idbOpen = vi.fn(), audio = vi.fn(), ctx = vi.fn(), speak = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    vi.stubGlobal("indexedDB", { open: idbOpen });
    vi.stubGlobal("Audio", audio);
    vi.stubGlobal("AudioContext", ctx);
    vi.stubGlobal("webkitAudioContext", ctx);
    vi.stubGlobal("speechSynthesis", { speak, cancel: vi.fn() });
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
    for (const n of P5B_NAMEN) {
      const v = card(simB(n, { laufzeit: 60 }));
      bedieneAlles(f);
      v.unmount();
    }
    for (const spy of [setItem, fetchSpy, idbOpen, audio, ctx, speak, play]) expect(spy).not.toHaveBeenCalled();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.querySelector("audio, video, iframe, object, embed")).toBeNull();
  });
});

describe("P5b: Vorführung", () => {
  it("die drei neuen Beispiele sind vollständig wie vom Backend und zeigen sich ohne Hinweis", () => {
    recordingCtx(); fakeFrames();
    const raw = P5B_NAMEN.map((n) => DEMO_VIEWS.find((v) => v.id === n)!);
    expect(raw.every(Boolean)).toBe(true);
    const KEYS: Record<string, string[]> = {
      doppelpendel: ["daempfung", "g", "laenge1", "laenge2", "masse1", "masse2", "winkel1", "winkel2"],
      welle: ["bereich", "wellen"],
      umlauf: ["anziehung", "koerper", "zentralmasse"],
    };
    raw.forEach((r, i) => {
      expect(Object.keys(r).sort()).toEqual(["art", "bausteine", "id", "schliessen", "stand", "titel"]);
      const v = parseItem({ ...r, seq: i + 1 }) as View;
      const b = v.bausteine[0] as SimBlock;
      expect(Object.keys(b).sort()).toEqual(["beschreibung", "laufzeit", "modell", "parameter", "spur", "tempo", "typ"]);
      expect(Object.keys(b.parameter).sort()).toEqual(KEYS[b.modell]);
      if (b.modell === "welle") {
        expect(b.parameter.wellen).toHaveLength(2);
        for (const w of b.parameter.wellen) expect(Object.keys(w).sort()).toEqual(["amplitude", "frequenz", "phase", "richtung", "wellenlaenge"]);
        expect(b.parameter.wellen.map((w) => w.richtung).sort()).toEqual(["links", "rechts"]);
        expect(new Set(b.parameter.wellen.map((w) => w.frequenz)).size).toBe(1);
      }
      if (b.modell === "umlauf") {
        expect(b.parameter.anziehung).toBe(true);
        expect(b.parameter.koerper).toHaveLength(3);
        for (const k of b.parameter.koerper) expect(Object.keys(k).sort()).toEqual(["abstand", "exzentrizitaet", "farbe", "masse", "name", "phase"]);
      }
      if (b.modell === "doppelpendel") { expect(b.parameter.winkel1).toBe(120); expect(b.parameter.winkel2).toBe(-10); }
      const cfg = normalizeSim(b);
      expect(cfg.angepasst).toEqual([]);
      expect(cfg.ungueltig).toBe(false);
      const c = render(<ViewCard view={v} sys={null} sysNo={false} onClose={() => undefined} />);
      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.queryByText(/angepasst|kann nicht gezeigt|nicht gezeichnet/)).toBeNull();
      expect(screen.getByText(FIXED)).toBeInTheDocument();
      expect(screen.getByText(b.beschreibung)).toBeInTheDocument();
      if (b.modell === "welle") expect(screen.getByText(/stehende Welle mit festen Knoten/)).toBeInTheDocument();
      c.unmount();
    });
  });
});
