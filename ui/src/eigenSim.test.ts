import { describe, expect, it } from "vitest";
import {
  addEigenSpuren, advanceEigen, createEigen, createEigenSpuren, EIGEN, eigenEndlich, eigenRegler, KNOTEN_BUDGET, mitParameter, snapshotEigen,
  type EigenSnapshot, type EigenState,
} from "./lib/eigenSim";
import { isFiniteSnapshot, trailPoints, type SimSnapshot } from "./lib/physics";
import { createSimLoop, type LoopState, type SimEngine } from "./lib/simLoop";

// Rechenkern `sim_eigen` (Plan P7 Stufe 1). Die vier Beispiele des Plans liegen von Hand übersetzt in src/fixtures/eigen_beispiele.json.

const nodeFs = "node:fs";
const { readFileSync } = (await import(/* @vite-ignore */ nodeFs)) as { readFileSync(p: string, enc: string): string };
const B = JSON.parse(readFileSync("src/fixtures/eigen_beispiele.json", "utf-8")) as Record<"pendel" | "raeuber_beute" | "lorenz" | "federkette", Record<string, unknown>>;
const kopie = <T>(x: T): T => JSON.parse(JSON.stringify(x)) as T;

type R = [string, number | string][];
const F = (rpn: R, tex = "") => ({ rpn, tex });
/** Eine ODE mit Standardwerten; `ab` in der Reihenfolge des Zustands. */
function ode(zustand: [string, number][], parameter: [string, number][], ab: R[], extra: Record<string, unknown> = {}) {
  return {
    typ: "sim_eigen", name: "Test", beschreibung: "", form: "ode",
    parameter: parameter.map(([name, wert]) => ({ name, wert, min: Math.min(0, wert), max: Math.max(100, wert), einheit: "" })),
    zustand: zustand.map(([name, start]) => ({ name, start, einheit: "" })), hilf: [],
    ableitungen: Object.fromEntries(zustand.map(([n], i) => [n, F(ab[i])])),
    darstellung: [{ form: "zeitreihe", groessen: zustand.map(([n]) => n) }], kennwerte: [], erhaltung: null,
    dt: 0.01, laufzeit: 30, tempo: 0, spur: true, ...extra,
  };
}
/** Teilchen mit Standardwerten. */
function teilchen(extra: Record<string, unknown> = {}) {
  return {
    typ: "sim_eigen", name: "Teilchen", beschreibung: "", form: "teilchen", parameter: [], anzahl: 10, start: "linie", punkte: [], startwert: 1,
    masse: 1, kasten: [10, 10], waende: "reflektieren", kraft: null, paar: null, federn: null, fest: [], darstellung: [{ form: "koerper" }],
    kennwerte: [], erhaltung: null, dt: 0.01, laufzeit: 30, tempo: 0, spur: true, ...extra,
  };
}
/** Weiterrechnen wie die Taktschleife: Bilder zu 1/30 s. */
function lauf(s: EigenState, sekunden: number, jedes?: (b: EigenSnapshot) => void): void {
  for (let i = 0, n = Math.round(sekunden * 30); i < n; i++) { advanceEigen(s, 1 / 30); jedes?.(snapshotEigen(s)); }
}
const TAU = 2 * Math.PI;
// Harmonischer Schwinger x'' = −ω²·x mit ω = 2π (Periode 1 s); Energie ½v² + ½ω²x² als Erhaltungsgröße.
const OSZ_E = F([["c", 0.5], ["v", 2], ["c", 2], ["o", "^"], ["o", "*"], ["c", 0.5], ["v", 3], ["o", "*"], ["v", 1], ["c", 2], ["o", "^"], ["o", "*"], ["o", "+"]]);
const oszillator = (extra: Record<string, unknown> = {}) =>
  ode([["x", 1], ["v", 0]], [["w2", TAU * TAU]], [[["v", 2]], [["v", 3], ["o", "neg"], ["v", 1], ["o", "*"]]], { erhaltung: OSZ_E, ...extra });

/** Taktschleife mit falscher Uhr (wie in simLoop.test.ts). */
function aufbau(input: unknown, engine: SimEngine = EIGEN) {
  let t = 0, id = 0, hidden = false;
  const queue = new Map<number, (ts: number) => void>();
  const frames: SimSnapshot[] = [], states: LoopState[] = [];
  const loop = createSimLoop({
    input, engine, isHidden: () => hidden,
    scheduler: { now: () => t, requestFrame: (cb) => { queue.set(++id, cb); return id; }, cancelFrame: (i) => { queue.delete(i); } },
    onFrame: (s) => frames.push(s), onState: (s) => states.push(s),
  });
  const bild = (ms: number) => { t += ms; const cbs = [...queue.values()]; queue.clear(); for (const cb of cbs) cb(t); };
  const sekunden = (s: number, hz = 60) => { for (let i = 0, n = Math.round(s * hz); i < n; i++) bild(1000 / hz); };
  return { loop, frames, states, sekunden, verstecke: (v: boolean) => { hidden = v; } };
}
const INSTABIL = "Simulation instabil, angehalten", ZEITLUPE = "Zeitlupe, Rechengrenze erreicht";

describe("eigenSim: ODE", () => {
  it("harmonic oscillator keeps its energy within 0.1 % over 10 periods (RK4)", () => {
    const s = createEigen(oszillator());
    expect(s.phase).toBe("laeuft");
    expect(s.integrator).toBe("rk4");
    let maxDrift = 0;
    lauf(s, 10, (b) => { maxDrift = Math.max(maxDrift, b.drift ?? Infinity); });
    expect(s.zeit).toBeCloseTo(10, 9);
    expect(maxDrift).toBeLessThan(0.1);
    const b = snapshotEigen(s);
    expect(b.werte[0].wert).toBeCloseTo(1, 4);                      // nach 10 Perioden wieder am Start
    expect(b.hinweis).toBeNull();
  });

  it("Lotka-Volterra example: the conserved quantity drifts under 1 %", () => {
    const s = createEigen(B.raeuber_beute);
    expect(s.phase).toBe("laeuft");
    expect(s.config.angepasst).toEqual([]);
    let maxDrift = 0, minB = Infinity;
    lauf(s, 30, (b) => { maxDrift = Math.max(maxDrift, b.drift ?? Infinity); minB = Math.min(minB, b.werte[0].wert); });
    expect(maxDrift).toBeLessThan(1);
    expect(minB).toBeGreaterThan(0);
    const b = snapshotEigen(s);
    expect(b.hinweis).toBeNull();
    expect(b.zeitreihe.map((q) => q.name)).toEqual(["B", "R"]);
    expect(b.phasen?.x).toBe("B");
    expect(b.kennwerte.find((k) => k.id === "erhaltung")?.einheit).toBe("%");
  });

  it("Lorenz example stays bounded (|x| < 30)", () => {
    const s = createEigen(B.lorenz);
    expect(s.phase).toBe("laeuft");
    expect(s.dt).toBe(0.005);
    let maxX = 0;
    lauf(s, 30, (b) => { maxX = Math.max(maxX, Math.abs(b.werte[0].wert)); });
    expect(s.phase).toBe("laeuft");
    expect(maxX).toBeGreaterThan(5);                                  // es passiert etwas
    expect(maxX).toBeLessThan(30);
    const x = s.bereiche[0];
    expect(x.name).toBe("x");
    expect(x.min).toBeLessThan(-5);
    expect(x.max).toBeGreaterThan(5);
  });

  it("pendulum example: body on the circle around the anchor, energy falls with damping", () => {
    const s = createEigen(B.pendel);
    expect(s.phase).toBe("laeuft");
    const b0 = snapshotEigen(s);
    expect(b0.anker).toEqual([0, 0]);
    expect(Math.hypot(b0.koerper[0].x, b0.koerper[0].y)).toBeCloseTo(1, 12);
    const e0 = b0.kennwerte[0].wert;
    expect(e0).toBeCloseTo(9.81 * (1 - Math.cos(1.2)), 12);
    lauf(s, 10);
    const b = snapshotEigen(s);
    expect(Math.hypot(b.koerper[0].x, b.koerper[0].y)).toBeCloseTo(1, 12);
    expect(b.kennwerte[0].wert).toBeLessThan(e0);
    const a = s.ausschnitt;
    expect(a.minX).toBeLessThan(-Math.sin(1.2) + 1e-9);
    expect(a.maxX).toBeGreaterThan(Math.sin(1.2) - 1e-9);
    expect(a.maxY).toBeGreaterThan(0);                                // der Anker ist im Bild
    expect(isFiniteSnapshot(b as unknown as SimSnapshot)).toBe(true);
  });

  it("evaluates helper quantities in order and lets derivatives read them", () => {
    // h1 = 2·x, h2 = h1 + 1, x' = h2 − h1 (= 1): x wächst wie t
    const inp = { ...ode([["x", 0]], [], [[["v", 3], ["v", 2], ["o", "-"]]]),
      hilf: [{ name: "h1", formel: F([["c", 2], ["v", 1], ["o", "*"]]) }, { name: "h2", formel: F([["v", 2], ["c", 1], ["o", "+"]]) }] };
    const s = createEigen(inp);
    expect(s.phase).toBe("laeuft");
    lauf(s, 2);
    expect(snapshotEigen(s).werte[0].wert).toBeCloseTo(2, 9);
    // eine Hilfsgröße darf nicht sich selbst oder spätere lesen
    const zirkel = { ...inp, hilf: [{ name: "h1", formel: F([["v", 3]]) }, inp.hilf[1]] };
    expect(createEigen(zirkel).config.fehler).toEqual(["hilf.0:index@0"]);
  });

  it("1/0 gives „instabil“ at once; a blow-up stops later", () => {
    const s = createEigen(ode([["x", 0]], [], [[["c", 1], ["c", 0], ["o", "/"]]]));
    expect(s.phase).toBe("instabil");
    expect(s.grund).toBe("nicht_endlich");
    const a = aufbau(ode([["x", 0]], [], [[["c", 1], ["c", 0], ["o", "/"]]]));
    expect(a.states.at(-1)?.wort).toBe(INSTABIL);
    expect(a.frames).toHaveLength(0);
    // x' = x² mit x(0) = 1 läuft bei t = 1 davon
    const w = createEigen(ode([["x", 1]], [], [[["v", 1], ["c", 2], ["o", "^"]]]));
    lauf(w, 3);
    expect(w.phase).toBe("instabil");
    expect(["nicht_endlich", "zu_gross"]).toContain(w.grund);
    expect(w.zeit).toBeLessThan(1.05);
    expect(advanceEigen(w, 1).schritte).toBe(0);                     // angehalten bleibt angehalten
  });

  it("a conserved quantity drifting over 1 % gives a lasting hint", () => {
    // Euler-artige Störung: x' = v, v' = −ω²x + 0,5·v (Energie wächst)
    const inp = oszillator();
    (inp.ableitungen as Record<string, unknown>).v = F([["v", 3], ["o", "neg"], ["v", 1], ["o", "*"], ["c", 0.5], ["v", 2], ["o", "*"], ["o", "+"]]);
    const s = createEigen(inp);
    lauf(s, 3);
    const b = snapshotEigen(s);
    expect(b.drift).toBeGreaterThan(1);
    expect(b.hinweis).toMatch(/^Die Erhaltungsgröße weicht um \d+,\d % vom Start ab\./);
    expect(s.phase).toBe("laeuft");                                  // nur ein Hinweis, kein Stopp
  });
});

describe("eigenSim: Teilchen", () => {
  it("spring chain example sags under gravity and comes to rest; fixed ends never move", () => {
    const s = createEigen(B.federkette);
    expect(s.phase).toBe("laeuft");
    expect(s.config.angepasst).toEqual([]);
    expect(s.integrator).toBe("euler");                              // die Kraft liest vx/vy
    const b0 = snapshotEigen(s);
    const ende0 = [b0.koerper[0], b0.koerper[11]].map((p) => [p.x, p.y]);
    expect(b0.federn).toHaveLength(11);
    expect(b0.fest).toEqual([0, 11]);
    lauf(s, 20, (b) => {
      expect([b.koerper[0], b.koerper[11]].map((p) => [p.x, p.y])).toEqual(ende0);
    });
    const b = snapshotEigen(s);
    expect(b.koerper[5].y).toBeLessThan(b0.koerper[5].y - 0.3);      // hängt durch
    expect(b.koerper[6].y).toBeLessThan(b0.koerper[6].y - 0.3);
    expect(b.koerper.every((p) => p.y > 0 && p.y <= 3 && p.x >= 0 && p.x <= 4)).toBe(true);
    expect(b.koerper[5].y).toBeCloseTo(b.koerper[6].y, 6);          // symmetrisch
    const vmax = b.kennwerte.find((k) => k.id === "geschwindigkeit")!.wert;
    expect(vmax).toBeLessThan(0.01);                                 // ruhig
    expect(b.koerper[0].farbe).toBe("amber");
    expect(b.koerper[1].farbe).toBe("arc");
  });

  it("uses Verlet when no force reads the velocity, otherwise semi-implicit Euler", () => {
    const fy = F([["v", 5], ["o", "neg"], ["c", 9.81], ["o", "*"]]);
    expect(createEigen(teilchen({ kraft: { fx: F([["c", 0]]), fy } })).integrator).toBe("verlet");
    expect(createEigen(teilchen({ kraft: { fx: F([["v", 3], ["o", "neg"]]), fy } })).integrator).toBe("euler");
    expect(createEigen(teilchen({ federn: { kette: true, paare: [], k: 1, l0: 1, daempfung: 0 } })).integrator).toBe("verlet");
    expect(createEigen(teilchen({ federn: { kette: true, paare: [], k: 1, l0: 1, daempfung: 0.1 } })).integrator).toBe("euler");
  });

  it("free fall with Verlet bounces off the floor and keeps its energy", () => {
    const s = createEigen(teilchen({ anzahl: 1, start: "liste", punkte: [[5, 8]], kraft: { fx: F([["c", 0]]), fy: F([["c", -10]]) }, dt: 0.001 }));
    expect(s.integrator).toBe("verlet");
    let minY = Infinity;
    lauf(s, 4, (b) => { minY = Math.min(minY, b.koerper[0].y); });
    expect(minY).toBeGreaterThanOrEqual(0);
    const b = snapshotEigen(s), k = s.kern as unknown as { vy: Float64Array };
    const e = 10 * b.koerper[0].y + 0.5 * k.vy[0] ** 2;
    expect(Math.abs(e - 80) / 80).toBeLessThan(0.01);
  });

  it("periodic walls wrap around, no walls let particles leave", () => {
    const p = createEigen(teilchen({ anzahl: 1, start: "liste", punkte: [[9.5, 5, 3, 0]], waende: "periodisch" }));
    lauf(p, 1);
    expect(snapshotEigen(p).koerper[0].x).toBeCloseTo(2.5, 6);
    const k = createEigen(teilchen({ anzahl: 1, start: "liste", punkte: [[9.5, 5, 3, 0]], waende: "keine" }));
    lauf(k, 1);
    expect(snapshotEigen(k).koerper[0].x).toBeCloseTo(12.5, 6);
    const r = createEigen(teilchen({ anzahl: 1, start: "liste", punkte: [[9.5, 5, 3, 0]] }));
    lauf(r, 1);
    expect(snapshotEigen(r).koerper[0].x).toBeCloseTo(7.5, 6);
  });

  it("pair force pushes apart, respects range and minimum distance, and conserves momentum", () => {
    // f(r) = a / r², abstoßend
    const paar = { f_r: F([["v", 1], ["v", 0], ["c", 2], ["o", "^"], ["o", "/"]]), reichweite: 3, mindestabstand: 0.5 };
    const s = createEigen(teilchen({ parameter: [{ name: "a", wert: 1, min: 0, max: 10, einheit: "" }], anzahl: 2, start: "liste",
      punkte: [[4, 5], [6, 5]], paar, waende: "keine" }));
    lauf(s, 1);
    const b = snapshotEigen(s), k = s.kern as unknown as { vx: Float64Array };
    expect(b.koerper[0].x).toBeLessThan(4);
    expect(b.koerper[1].x).toBeGreaterThan(6);
    expect(k.vx[0] + k.vx[1]).toBeCloseTo(0, 12);
    const fern = createEigen(teilchen({ parameter: [{ name: "a", wert: 1, min: 0, max: 10, einheit: "" }], anzahl: 2, start: "liste",
      punkte: [[1, 5], [9, 5]], paar, waende: "keine" }));
    lauf(fern, 1);
    expect(snapshotEigen(fern).koerper[0].x).toBe(1);                 // außer Reichweite: keine Kraft
  });

  it("random start depends only on the seed", () => {
    const a = snapshotEigen(createEigen(teilchen({ start: "zufall", startwert: 7 }))).koerper.map((p) => [p.x, p.y]);
    const b = snapshotEigen(createEigen(teilchen({ start: "zufall", startwert: 7 }))).koerper.map((p) => [p.x, p.y]);
    const c = snapshotEigen(createEigen(teilchen({ start: "zufall", startwert: 8 }))).koerper.map((p) => [p.x, p.y]);
    expect(a).toEqual(b);
    expect(a).not.toEqual(c);
    expect(a.every(([x, y]) => x >= 0 && x <= 10 && y >= 0 && y <= 10)).toBe(true);
  });

  it("grid start fills the box and arrows show velocities", () => {
    const s = createEigen(teilchen({ anzahl: 9, start: "gitter", darstellung: [{ form: "koerper" }, { form: "pfeile" }] }));
    const b = snapshotEigen(s);
    expect(new Set(b.koerper.map((p) => p.x)).size).toBe(3);
    expect(b.pfeile).toHaveLength(9);
    expect(b.pfeile![0]).toEqual([b.koerper[0].x, b.koerper[0].y, 0, 0]);
  });
});

describe("eigenSim: Grenzen und Taktschleife", () => {
  const gas100 = () => teilchen({
    parameter: [{ name: "a", wert: 0.01, min: 0, max: 1, einheit: "" }], anzahl: 100, start: "gitter", dt: 0.001,
    paar: { f_r: F([["v", 1], ["v", 0], ["c", 2], ["o", "^"], ["o", "/"]]), reichweite: 100, mindestabstand: 0.1 },
  });

  it("100 particles with a pair force: „Zeitlupe“ instead of freezing", () => {
    const s = createEigen(gas100());
    expect(s.kostenJeSchritt).toBe(4950 * 5);
    const r = advanceEigen(s, 1 / 30);
    expect(r.begrenzt).toBe(true);
    expect(r.knoten).toBeLessThanOrEqual(KNOTEN_BUDGET);
    expect(r.schritte).toBeGreaterThan(0);
    const a = aufbau(gas100());
    a.sekunden(2);
    expect(a.states.map((q) => q.wort)).toContain(ZEITLUPE);
    expect(a.frames.length).toBeGreaterThan(50);                       // es kommen weiter Bilder
    expect(a.loop.getState().simZeit).toBeGreaterThan(0.1);
    expect(a.loop.getState().simZeit).toBeLessThan(1);
  });

  it("at least one step per frame even if a single step is over budget", () => {
    const s = createEigen(gas100());
    (s as { kostenJeSchritt: number }).kostenJeSchritt = KNOTEN_BUDGET * 2;
    expect(advanceEigen(s, 1).schritte).toBe(1);
  });

  it("hidden means zero steps (through simLoop)", () => {
    let schritte = 0;
    const zaehler: SimEngine = { ...EIGEN, advance: (st, sec, m) => { const r = EIGEN.advance(st, sec, m); schritte += r.schritte; return r; } };
    const a = aufbau(B.lorenz, zaehler);
    a.sekunden(0.5);
    expect(schritte).toBeGreaterThan(0);
    const vorher = schritte, bilder = a.frames.length, zeit = a.loop.getState().simZeit;
    a.verstecke(true);
    a.sekunden(2);
    expect(schritte).toBe(vorher);
    expect(a.frames.length).toBe(bilder);
    expect(a.loop.getState().simZeit).toBe(zeit);
    a.verstecke(false);
    a.sekunden(0.5);
    expect(schritte).toBeGreaterThan(vorher);
  });

  it("stops after the run time", () => {
    const a = aufbau({ ...kopie(B.lorenz), laufzeit: 5 });
    a.sekunden(7);
    expect(a.loop.getState().status).toBe("angehalten");
    expect(a.loop.getState().wort).toBe("angehalten nach 5 s");
    expect(a.loop.pending()).toBe(0);
    expect(a.loop.getState().simZeit).toBeCloseTo(5, 1);
    expect(a.frames.every((f) => (f as unknown as EigenSnapshot).modell === "eigen" && isFiniteSnapshot(f))).toBe(true);
  });

  it("each of the four examples is valid and starts without adjustments", () => {
    for (const k of ["pendel", "raeuber_beute", "lorenz", "federkette"] as const) {
      const s = createEigen(B[k]);
      expect([k, s.phase, s.config.fehler, s.config.angepasst]).toEqual([k, "laeuft", [], []]);
      expect(eigenEndlich(s.startBild)).toBe(true);
      expect(s.text).toMatch(/^Eigene Simulation „.+“, nicht geprüft/);
    }
  });
});

describe("eigenSim: Eingabe", () => {
  it("rejects missing or broken derivatives, bad env order and too many nodes", () => {
    const ohne = kopie(B.pendel) as Record<string, unknown>;
    delete (ohne.ableitungen as Record<string, unknown>).w;
    const s = createEigen(ohne);
    expect([s.phase, s.grund, s.config.fehler]).toEqual(["instabil", "eingabe", ["ableitungen.1:keine_liste"]]);
    const kaputt = kopie(B.pendel) as Record<string, unknown>;
    (kaputt.ableitungen as Record<string, unknown>).phi = F([["v", 6]]);
    expect(createEigen(kaputt).config.fehler).toEqual(["ableitungen.0:index@0"]);
    const env = { ...kopie(B.pendel), env: { ode: ["t", "w", "phi", "g", "l", "d"] } };
    expect(createEigen(env).config.fehler).toEqual(["env.ode:reihenfolge"]);
    const lang: R = [["c", 1], ...Array.from({ length: 31 }, (): R => [["c", 1], ["o", "+"]]).flat()];
    const viele = ode(Array.from({ length: 10 }, (_, i): [string, number] => [`x${i}`, 0]), [], Array.from({ length: 10 }, () => lang));
    expect(createEigen(viele).config.fehler).toEqual(["knoten:zu_viele"]);
    expect(createEigen(null).phase).toBe("instabil");
    expect(createEigen({ form: "rakete" }).config.fehler).toContain("form:unbekannt");
  });

  it("invalid optional parts are dropped and named; numbers are limited", () => {
    const inp = { ...kopie(B.pendel), dt: 5, laufzeit: 1000, kennwerte: [{ name: "kaputt", formel: F([["o", "+"]]), einheit: "" }] };
    const s = createEigen(inp);
    expect(s.phase).toBe("laeuft");
    expect(s.dt).toBe(1);
    expect(s.config.laufzeit).toBe(60);
    expect(s.config.angepasst).toEqual(["laufzeit", "dt", "kennwerte.0:unterlauf@0"]);
    expect(snapshotEigen(s).kennwerte).toEqual([]);
  });

  it("never throws, also not on hostile input", () => {
    const boese = new Proxy({}, { get() { throw new Error("x"); }, has() { throw new Error("x"); }, getOwnPropertyDescriptor() { throw new Error("x"); } });
    expect(() => createEigen(boese)).not.toThrow();
    expect(createEigen(boese).phase).toBe("instabil");
    expect(() => createSimLoop({ input: boese, engine: EIGEN, scheduler: { now: () => 0, requestFrame: () => 1, cancelFrame: () => {} }, onFrame: () => {} })).not.toThrow();
  });
});

describe("eigenSim: Regler und Spuren", () => {
  it("mitParameter clamps to the limits and never changes the input", () => {
    const inp = kopie(B.pendel), vorher = JSON.stringify(inp);
    const neu = mitParameter(inp, "l", 50) as typeof inp;
    expect(JSON.stringify(inp)).toBe(vorher);
    expect((neu.parameter as { name: string; wert: number }[]).find((p) => p.name === "l")?.wert).toBe(10);
    expect(mitParameter(inp, "l", 0.5).parameter).not.toBe(inp.parameter);
    expect(JSON.stringify(mitParameter(inp, "gibtsnicht", 3))).toBe(vorher);
    expect(JSON.stringify(mitParameter(inp, "l", NaN))).toBe(vorher);
    const s = createEigen(mitParameter(inp, "l", 2));
    expect(Math.hypot(s.startBild.koerper[0].x, s.startBild.koerper[0].y)).toBeCloseTo(2, 12);
  });

  it("eigenRegler lists one slider per parameter with its limits", () => {
    const r = eigenRegler(B.pendel);
    expect(r.map((g) => [g.feld, g.min, g.max, g.skala])).toEqual([["g", 0.1, 30, "linear"], ["l", 0.1, 10, "linear"], ["d", 0, 5, "linear"]]);
    expect(r[0].schritt).toBeCloseTo(0.1, 12);
    expect(eigenRegler(null)).toEqual([]);
  });

  it("trails use the helpers from physics.ts: body, time series and phase plane", () => {
    const s = createEigen(B.pendel), sp = createEigenSpuren(s);
    expect([sp.koerper.xs.length, sp.zeitreihe.xs.length, sp.phasen.xs.length]).toEqual([1, 1, 0]);
    lauf(s, 1, (b) => addEigenSpuren(sp, b));
    expect(trailPoints(sp.koerper, 0)).toHaveLength(30);
    const reihe = trailPoints(sp.zeitreihe, 0);
    expect(reihe.at(-1)![0]).toBeCloseTo(1, 9);                         // x ist die Zeit
    const l = createEigen(B.raeuber_beute), sl = createEigenSpuren(l);
    lauf(l, 1, (b) => addEigenSpuren(sl, b));
    expect(sl.zeitreihe.xs.length).toBe(2);
    expect(trailPoints(sl.phasen, 0)).toHaveLength(30);
  });
});
