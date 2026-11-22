import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { ViewCard } from "./components/stage/ViewCard";
import { ApiClient } from "./lib/api";
import { STATE_VIEW } from "./lib/avatarState";
import { DEMO_VIEWS, MockSocket } from "./lib/mock";
import { createSim, formatFest, MODELLE, normalizeSim, snapshot, standbild, type SimModell, type SimSnapshot } from "./lib/physics";
import { ART_LABEL, parseItem, type Block, type SimBlock, type View } from "./lib/stage";

// P5a (docs/ui-p5-plan.md, Abschnitte 3 bis 6 und 10): Baustein `simulation` mit falschem requestAnimationFrame und falscher Uhr.
// Kernregeln: der feste Satz „Simulation, keine Messung“ ist immer da; Bedienen ändert nur die Anzeige und sendet nie etwas;
// bei „weniger Bewegung“ läuft keine Schleife; Texte aus den Daten stehen nur im DOM, nie im Bild.

vi.mock("./lib/physics", async (orig) => {
  const m = await orig<typeof import("./lib/physics")>();
  return { ...m, snapshot: vi.fn(m.snapshot), standbild: vi.fn(m.standbild) };
});

const TOKEN = "t".repeat(43);
const REDUCE = "(prefers-reduced-motion: reduce)";
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.mocked(standbild).mockClear(); vi.mocked(snapshot).mockClear(); });

type Call = { name: string; args: unknown[] };
/** Zeichenfläche, die jeden Aufruf und jede gesetzte Eigenschaft mitschreibt. `fail` wirft bei diesem Aufruf. */
function recordingCtx(fail?: string) {
  const calls: Call[] = [];
  const ctx = new Proxy({}, {
    get: (_t, k) => (k === "canvas" ? null : (...args: unknown[]) => {
      if (k === fail) throw new Error("kaputt");
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
    const raw = DEMO_VIEWS.slice(17);
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
