import { afterEach, describe, expect, it, vi } from "vitest";
import {
  addToTrail, advance, createSim, createTrail, doppelpendelEigen, formatFest, formatWert, formatZahl, GRENZEN, isFiniteSnapshot, mitWert, MODELLE,
  MODELLE_ALLE, mulberry32, normalizeSim, snapshot, solveKepler, standbild, trailPoints, VORAUS_BUDGET, WELLE_PUNKTE, type DoppelpendelKern,
  type FederKern, type GasKern, type NKoerperKern, type SimSnapshot, type SimState, type Standbild, type WelleKern,
} from "./lib/physics";

// Rechenkern für `simulation` (Plan docs/ui-p5-plan.md, Abschnitt 10): reine Zahlen, kein DOM, keine Uhr.

const basis = { laufzeit: 30, tempo: 0, spur: true, beschreibung: "" };
const pendel = (p: object = {}, extra: object = {}) =>
  ({ ...basis, modell: "pendel", parameter: { laenge: 1, winkel: 30, anfangsgeschwindigkeit: 0, daempfung: 0, g: 9.81, ...p }, ...extra });
const feder = (p: object = {}, extra: object = {}) =>
  ({ ...basis, modell: "feder", parameter: { masse: 1, federkonstante: 10, auslenkung: 0.5, daempfung: 0, ...p }, ...extra });
const wurf = (p: object = {}, extra: object = {}) =>
  ({ ...basis, modell: "wurf", parameter: { geschwindigkeit: 20, winkel: 45, hoehe: 0, g: 9.81, luftwiderstand: 0, ...p }, ...extra });
const koerper = (abstand: number, exzentrizitaet = 0, phase = 0, name = "Erde") => ({ name, abstand, exzentrizitaet, phase, farbe: "arc" });
const umlauf = (p: object = {}, extra: object = {}) =>
  ({ ...basis, modell: "umlauf", parameter: { zentralmasse: 1, koerper: [koerper(1, 0.0167)], ...p }, ...extra });
const gas = (p: object = {}, extra: object = {}) =>
  ({ ...basis, modell: "gas", parameter: { anzahl: 100, kasten: [100, 100], radius: 1, geschwindigkeit: 1, schwerkraft: 0, stoesse: true, startwert: 1, ...p }, ...extra });

const wert = (s: SimState | SimSnapshot, id: string): number => {
  const snap = "kennwerte" in s ? s : snapshot(s);
  const k = snap.kennwerte.find((x) => x.id === id);
  if (!k) throw new Error(`Kennwert ${id} fehlt`);
  return k.wert;
};
/** Genau n weitere Teilschritte (Raster t = n·dt), unabhängig von angesammelten Rundungen. */
const schritte = (s: SimState, n: number) => advance(s, (s.schritt + n) * s.dt - s.soll);
const relativ = (a: number, b: number) => Math.abs(a - b) / Math.abs(b);
const TAU = 2 * Math.PI;

function bildEndlich(b: Standbild): boolean {
  const pts: number[] = [];
  if (b.modell === "pendel" || b.modell === "feder") b.kurve.forEach((p) => pts.push(...p));
  if (b.modell === "wurf") { b.bahn.forEach((p) => pts.push(...p)); pts.push(...b.gipfel, ...b.aufprall, b.flugzeit); }
  if (b.modell === "umlauf") b.bahnen.forEach((q) => q.punkte.forEach((p) => pts.push(...p)));
  if (b.modell === "gas") pts.push(...b.verteilung.grenzen, ...b.verteilung.anzahl, b.zeit);
  if (b.modell === "doppelpendel") { b.bahn.forEach((p) => pts.push(...p)); pts.push(b.dauer); }
  if (b.modell === "welle") [b.kurve, ...b.teilkurven, b.huelleMin, b.huelleMax].forEach((q) => q.forEach((p) => pts.push(...p)));
  return isFiniteSnapshot(b.start) && pts.every(Number.isFinite);
}

/** Zeitpunkte, an denen ein Wert aufwärts durch null geht (linear eingepasst). */
function nulldurchgaenge(s: SimState, get: () => number, n: number): number[] {
  const out: number[] = [];
  let prev = get(), t = s.zeit;
  for (let i = 0; i < n; i++) {
    schritte(s, 1);
    const v = get();
    if (prev < 0 && v >= 0) out.push(t + (s.zeit - t) * (-prev / (v - prev)));
    prev = v; t = s.zeit;
  }
  return out;
}

afterEach(() => vi.restoreAllMocks());

describe("Zahlen und Text auf Deutsch", () => {
  it("formats numbers with a decimal comma", () => {
    expect(formatZahl(1)).toBe("1");
    expect(formatZahl(9.81)).toBe("9,81");
    expect(formatZahl(0.017)).toBe("0,017");
    expect(formatZahl(-30)).toBe("-30");
    expect(formatWert(2.006)).toBe("2,0");
    expect(formatWert(0.14)).toBe("0,14");
    expect(formatWert(40.77)).toBe("40,8");
    expect(formatWert(316228)).toBe("316\u00a0228");
    expect(formatFest(4.23, 1)).toBe("4,2");
    expect(formatWert(NaN)).toBe("–");
  });

  it("writes the text alternative from the plan for the default pendulum", () => {
    expect(createSim(pendel()).text).toBe("Pendel, Länge 1 m, Start bei 30 Grad, ohne Dämpfung. Schwingungsdauer etwa 2,0 s.");
    expect(createSim(feder({ daempfung: 0.5 })).text).toContain("Dämpfung 0,5 kg/s");
    expect(createSim(wurf()).text).toBe("Wurf mit 20 m/s unter 45 Grad aus 0 m Höhe, ohne Luftwiderstand. "
      + "Reichweite etwa 40,8 m, Gipfelhöhe etwa 10,2 m, Flugzeit etwa 2,9 s.");
    expect(createSim(umlauf()).text).toContain("ohne gegenseitige Anziehung");
    expect(createSim(gas()).text).toContain("100 Teilchen");
  });
});

describe("Determinismus", () => {
  const faelle = [pendel({ winkel: 120, daempfung: 0.1 }), feder({ daempfung: 0.3 }), wurf({ luftwiderstand: 0.01 }), umlauf({ koerper: [koerper(1, 0.5, 30), koerper(3, 0.2, 200, "Mars")] }), gas({ anzahl: 40 })];

  it("gives exactly the same numbers after 10000 steps, also when the time arrives in uneven pieces", () => {
    for (const input of faelle) {
      const a = createSim(input), b = createSim(input), c = createSim(input);
      schritte(a, 10000); schritte(b, 10000);
      expect(snapshot(a)).toEqual(snapshot(b));
      const r = mulberry32(99);
      while (c.schritt < 10000 && c.phase === "laeuft" && c.soll < 10000 * c.dt) advance(c, Math.min(r() * 37, 10000 - c.schritt) * c.dt);
      advance(c, 10000 * c.dt - c.soll);
      expect(snapshot(c), input.modell).toEqual(snapshot(a));
      if (a.phase === "laeuft") expect(a.schritt).toBe(10000);
    }
  });

  it("gas: same seed gives the same start and run, another seed a different one", () => {
    const a = createSim(gas({ startwert: 7 })), b = createSim(gas({ startwert: 7 })), c = createSim(gas({ startwert: 8 }));
    expect(snapshot(a)).toEqual(snapshot(b));
    expect(snapshot(a).koerper).not.toEqual(snapshot(c).koerper);
    schritte(a, 500); schritte(b, 500); schritte(c, 500);
    expect(snapshot(a)).toEqual(snapshot(b));
    expect(snapshot(a).koerper).not.toEqual(snapshot(c).koerper);
  });

  it("never calls Math.random", () => {
    const spy = vi.spyOn(Math, "random");
    for (const input of [...faelle, gas({ anzahl: 300, radius: 1.7, schwerkraft: 50 })]) {
      const s = createSim(input);
      advance(s, s.tempo, 4000);
      standbild(s);
    }
    expect(mulberry32(1)()).toBe(mulberry32(1)());
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("Energie", () => {
  it("pendulum and spring without damping keep their energy within 0.1 % over 60 s", () => {
    const echt = {
      pendel: (s: SimState) => { const k = s.kern as { L: number; w2: number; th: number; om: number }; return 0.5 * k.om ** 2 + k.w2 * (1 - Math.cos(k.th)); },
      feder: (s: SimState) => { const k = s.kern as { m: number; k: number; x: number; v: number }; return 0.5 * k.m * k.v ** 2 + 0.5 * k.k * k.x ** 2; },
    };
    for (const input of [pendel(), pendel({ winkel: 160 }), pendel({ winkel: 10, anfangsgeschwindigkeit: 500 }), pendel({ laenge: 0.05, g: 100 }), feder(), feder({ masse: 0.001, federkonstante: 20 })]) {
      const s = createSim(input), e0 = echt[s.modell as "pendel" | "feder"](s);
      let maxAbw = 0;
      while (s.zeit < 60) {
        schritte(s, Math.max(1, Math.round(0.05 / s.dt)));
        maxAbw = Math.max(maxAbw, relativ(echt[s.modell as "pendel" | "feder"](s), e0));
      }
      expect(maxAbw, JSON.stringify(input.parameter)).toBeLessThan(0.001);
      expect(Math.abs(wert(s, "energie") - 100)).toBeLessThan(0.1);
    }
  });

  it("with damping the energy never rises", () => {
    for (const input of [pendel({ daempfung: 0.05 }), pendel({ daempfung: 5, winkel: 170 }), pendel({ daempfung: 0.001, anfangsgeschwindigkeit: 400 }),
      feder({ daempfung: 0.2 }), feder({ daempfung: 10000, masse: 0.001 }), feder({ daempfung: 50 })]) {
      const s = createSim(input);
      let prev = wert(s, "energie");
      for (let i = 0; i < 20000; i++) {
        schritte(s, 1);
        const e = wert(s, "energie");
        expect(e, `${JSON.stringify(input.parameter)} Schritt ${i}`).toBeLessThanOrEqual(prev + 1e-9);
        prev = e;
      }
      expect(prev).toBeLessThan(100);
    }
  });

  it("gas without gravity keeps its kinetic energy through collisions, nobody leaves the box or touches a wall", () => {
    const s = createSim(gas({ anzahl: 200, radius: 2 })), r = 2;
    const e0 = wert(s, "bewegungsenergie");
    for (let i = 0; i < 3000; i++) {
      schritte(s, 1);
      for (const p of snapshot(s).koerper) {
        expect(p.x >= r && p.x <= 100 - r && p.y >= r && p.y <= 100 - r).toBe(true);
      }
    }
    expect(relativ(wert(s, "bewegungsenergie"), e0)).toBeLessThan(1e-9);
    const v = snapshot(s).verteilung!;
    expect(v.anzahl.reduce((a, b) => a + b, 0)).toBe(200);
    expect(v.anzahl.filter((n) => n > 0).length).toBeGreaterThan(3);   // Stöße haben die Geschwindigkeiten verteilt
  });
});

describe("Vergleich mit Lehrbuchformeln (0,5 %)", () => {
  it("pendulum at a small angle: 2π√(L/g)", () => {
    for (const [L, g] of [[1, 9.81], [2.5, 1.62], [0.3, 25]]) {
      const s = createSim(pendel({ laenge: L, g, winkel: 2 })), soll = TAU * Math.sqrt(L / g);
      expect(relativ(wert(s, "schwingungsdauer"), soll)).toBeLessThan(1e-12);
      const z = nulldurchgaenge(s, () => (s.kern as { th: number }).th, Math.ceil((3.2 * soll) / s.dt));
      expect(z.length).toBeGreaterThanOrEqual(3);
      expect(relativ((z[z.length - 1] - z[0]) / (z.length - 1), soll)).toBeLessThan(0.005);
    }
  });

  it("spring: 2π√(m/k)", () => {
    for (const [m, k] of [[1, 10], [0.2, 300], [50, 2]]) {
      const s = createSim(feder({ masse: m, federkonstante: k })), soll = TAU * Math.sqrt(m / k);
      expect(relativ(wert(s, "schwingungsdauer"), soll)).toBeLessThan(1e-12);
      const z = nulldurchgaenge(s, () => (s.kern as { x: number }).x, Math.ceil((3.2 * soll) / s.dt));
      expect(relativ((z[z.length - 1] - z[0]) / (z.length - 1), soll)).toBeLessThan(0.005);
    }
  });

  it("throw without drag: range, peak and flight time, also from a height", () => {
    for (const [v, a, h, g] of [[20, 45, 0, 9.81], [12, 30, 10, 9.81], [5, -20, 50, 1.62], [100, 80, 0, 9.81]]) {
      const s = createSim(wurf({ geschwindigkeit: v, winkel: a, hoehe: h, g })), r = (a * Math.PI) / 180;
      const vx = v * Math.cos(r), vy = v * Math.sin(r), T = (vy + Math.sqrt(vy * vy + 2 * g * h)) / g;
      expect(relativ(wert(s, "flugzeit"), T)).toBeLessThan(0.005);
      expect(relativ(wert(s, "reichweite"), vx * T)).toBeLessThan(0.005);
      expect(relativ(wert(s, "gipfelhoehe"), h + Math.max(0, vy) ** 2 / (2 * g))).toBeLessThan(0.005);
      if (h === 0) expect(relativ(wert(s, "reichweite"), (v * v * Math.sin(2 * r)) / g)).toBeLessThan(0.005);
      advance(s, 2 * T);
      expect(s.phase).toBe("gelandet");
      expect(relativ(s.zeit, T)).toBeLessThan(0.005);
      expect(relativ(snapshot(s).koerper[0].x, vx * T)).toBeLessThan(0.005);
      expect(snapshot(s).koerper[0].y).toBe(0);
    }
  });

  it("orbit: period √(a³/M), perihelion a(1−e), aphelion a(1+e), back at the start after one period", () => {
    for (const [M, a, e] of [[1, 1, 0.0167], [1, 5.2, 0.048], [2.5, 0.4, 0.6], [0.3, 30, 0.95]]) {
      const P = Math.sqrt((a * a * a) / M);
      const s = createSim(umlauf({ zentralmasse: M, koerper: [koerper(a, e)] }));
      expect(relativ(wert(s, "umlaufzeit.0"), P)).toBeLessThan(1e-12);
      expect(relativ(wert(s, "abstand.0"), a * (1 - e))).toBeLessThan(1e-9);
      const start = snapshot(s).koerper[0];
      schritte(s, 500);
      expect(relativ(wert(s, "abstand.0"), a * (1 + e))).toBeLessThan(0.005);
      schritte(s, 500);
      expect(relativ(s.zeit, P)).toBeLessThan(1e-9);
      expect(snapshot(s).koerper[0].x).toBeCloseTo(start.x, 6);
      expect(snapshot(s).koerper[0].y).toBeCloseTo(start.y, 6);
      // Perihel im Lauf gefunden (Raster P/1000; bei e = 0,95 fliegt der Körper am Perihel zwischen zwei Rasterpunkten weit,
      // darum dort nur über die Zeitpunkte genau 0 und P geprüft).
      if (e > 0.9) continue;
      const q = createSim(umlauf({ zentralmasse: M, koerper: [koerper(a, e, 90)] }));
      let rmin = Infinity;
      for (let i = 0; i < 1000; i++) { schritte(q, 1); rmin = Math.min(rmin, wert(q, "abstand.0")); }
      expect(relativ(rmin, a * (1 - e))).toBeLessThan(0.005);
    }
  });

  it("throw with drag lands earlier and shorter than without, and the run lands where the precomputation said", () => {
    for (const [v, a, h, k] of [[20, 45, 0, 0.01], [300, 30, 0, 0.001], [50, 70, 100, 0.2], [1000, 90, 10000, 1]]) {
      const frei = createSim(wurf({ geschwindigkeit: v, winkel: a, hoehe: h })), zaeh = createSim(wurf({ geschwindigkeit: v, winkel: a, hoehe: h, luftwiderstand: k }));
      expect(wert(zaeh, "flugzeit") < wert(frei, "flugzeit") || h > 0).toBe(true);
      expect(wert(zaeh, "reichweite")).toBeLessThan(wert(frei, "reichweite") + 1e-9);
      expect(wert(zaeh, "gipfelhoehe")).toBeLessThan(wert(frei, "gipfelhoehe"));
      const T = wert(zaeh, "flugzeit");
      for (let i = 0; i < 200 && zaeh.phase === "laeuft"; i++) advance(zaeh, T);
      expect(zaeh.phase).toBe("gelandet");
      expect(zaeh.zeit).toBe(T);
      expect(snapshot(zaeh).koerper[0].x).toBe(wert(zaeh, "reichweite"));
    }
    const lang = createSim(wurf({ geschwindigkeit: 1, winkel: 0, hoehe: 1000, luftwiderstand: 1 }));
    expect(wert(lang, "flugzeit")).toBeGreaterThan(wert(createSim(wurf({ geschwindigkeit: 1, winkel: 0, hoehe: 1000 })), "flugzeit"));  // fällt langsamer
  });

  it("solves Kepler's equation for e = 0.95 and every mean anomaly", () => {
    for (const e of [0, 0.3, 0.9, 0.95]) {
      for (let i = 0; i <= 4000; i++) {
        const M = -20 + (40 * i) / 4000, E = solveKepler(M, e);
        expect(Number.isFinite(E)).toBe(true);
        expect(Math.abs(Math.sin((E - e * Math.sin(E) - M) / 2))).toBeLessThan(1e-12);
      }
    }
    expect(solveKepler(NaN, 0.5)).toBe(0);
  });
});

describe("Grenzen und feindliche Eingaben", () => {
  const ecken = <T extends Record<string, [number, number]>>(g: T): Record<keyof T, number>[] => {
    const keys = Object.keys(g);
    return Array.from({ length: 2 ** keys.length }, (_, m) => Object.fromEntries(keys.map((k, i) => [k, g[k][(m >> i) & 1]])) as Record<keyof T, number>);
  };
  function pruefe(input: object, darfLanden = false): SimState {
    const s = createSim(input);
    expect(s.phase === "laeuft" || (darfLanden && s.phase === "gelandet"), JSON.stringify(input)).toBe(true);
    for (let i = 0; i < 20; i++) advance(s, s.tempo / 30, 4000);
    expect(s.phase === "laeuft" || (darfLanden && s.phase === "gelandet"), JSON.stringify(input)).toBe(true);
    expect(isFiniteSnapshot(snapshot(s)), JSON.stringify(input)).toBe(true);
    expect([s.dt, s.tempo, s.periode, ...Object.values(s.ausschnitt)].every(Number.isFinite)).toBe(true);
    expect(s.ausschnitt.maxX > s.ausschnitt.minX && s.ausschnitt.maxY > s.ausschnitt.minY).toBe(true);
    expect(s.text).not.toMatch(/NaN|Infinity|–/);
    return s;
  }

  it("keeps the corners of every limit finite", () => {
    for (const p of ecken({ laenge: [0.05, 100], winkel: [-170, 170], anfangsgeschwindigkeit: [-720, 720], daempfung: [0, 5], g: [0.1, 100] })) {
      expect(bildEndlich(standbild(pruefe(pendel(p))))).toBe(true);
    }
    for (const p of ecken({ masse: [0.001, 1000], federkonstante: [0.001, 1e6], auslenkung: [-10, 10], daempfung: [0, 10000] })) {
      expect(bildEndlich(standbild(pruefe(feder(p))))).toBe(true);
    }
    for (const p of ecken({ geschwindigkeit: [0.1, 1000], winkel: [-90, 90], hoehe: [0, 10000], g: [0.1, 100], luftwiderstand: [0, 1] })) {
      if (p.hoehe === 0 && p.winkel <= 0) {                   // wie im Schema abgelehnt: ungültig, läuft nicht, Bild trotzdem endlich
        const u = createSim(wurf(p));
        expect(u.config.ungueltig && u.phase === "instabil", JSON.stringify(p)).toBe(true);
        expect(bildEndlich(standbild(u))).toBe(true);
        continue;
      }
      const s = pruefe(wurf(p), true);
      expect(bildEndlich(standbild(s))).toBe(true);
      expect(s.vorausSchritte).toBeLessThanOrEqual(VORAUS_BUDGET);
    }
    for (const p of ecken({ zentralmasse: [0.01, 100], abstand: [0.01, 1000], exzentrizitaet: [0, 0.95], phase: [0, 360] })) {
      const many = Array.from({ length: 8 }, (_, i) => koerper(p.abstand * (i % 2 ? 1 : 0.01 / p.abstand + 1), p.exzentrizitaet, p.phase, `K${i}`));
      expect(bildEndlich(standbild(pruefe(umlauf({ zentralmasse: p.zentralmasse, koerper: [koerper(p.abstand, p.exzentrizitaet, p.phase)] }))))).toBe(true);
      expect(bildEndlich(standbild(pruefe(umlauf({ zentralmasse: p.zentralmasse, koerper: many }))))).toBe(true);
    }
    for (const p of ecken({ anzahl: [2, 300], b: [1, 1000], h: [1, 1000], geschwindigkeit: [1e-3, 10], schwerkraft: [0, 100] })) {
      for (const radius of [1e-6, 1000]) {
        const s = pruefe(gas({ anzahl: p.anzahl, kasten: [p.b, p.h], radius, geschwindigkeit: p.geschwindigkeit, schwerkraft: p.schwerkraft, stoesse: p.anzahl === 300 }));
        if (p.anzahl === 300 || p.b === 1) { const b = standbild(s); expect(bildEndlich(b)).toBe(true); }
        expect(s.vorausSchritte).toBeLessThanOrEqual(VORAUS_BUDGET);
      }
    }
  });

  it("never throws on hostile input; clamps it or reports it as unstable", () => {
    const boese: unknown[] = [
      undefined, null, 42, "pendel", [], { modell: "quatsch" }, { modell: "pendel" }, { modell: "pendel", parameter: null },
      { modell: "pendel", parameter: { laenge: NaN, winkel: "30", g: Infinity, daempfung: -1 } },
      { modell: "feder", parameter: { masse: -5, federkonstante: 0, auslenkung: true } },
      { modell: "wurf", parameter: { geschwindigkeit: "schnell", winkel: 1e9, hoehe: -1 }, laufzeit: 1e9, tempo: -3 },
      { modell: "umlauf", parameter: { zentralmasse: 0, koerper: Array.from({ length: 50 }, () => ({ abstand: -1, exzentrizitaet: 1.5, phase: NaN, farbe: "#ff0000", name: 5 })) } },
      { modell: "umlauf", parameter: { koerper: "viele" } },
      { modell: "gas", parameter: { anzahl: 10000, kasten: [1e9, -4], radius: -3, geschwindigkeit: NaN, startwert: -1 } },
      { modell: "gas", parameter: { anzahl: 300, kasten: [1, 1], radius: 0.5, geschwindigkeit: 10, stoesse: "ja" } },
      { modell: "gas", parameter: { kasten: [1, 2, 3], anzahl: 2.7 } },
      { modell: "pendel", parameter: { laenge: 1 }, beschreibung: "a\u202eb\u0000c".repeat(500) },
      new Proxy({}, { get() { throw new Error("böse"); }, has() { throw new Error("böse"); }, getOwnPropertyDescriptor() { throw new Error("böse"); } }),
    ];
    for (const input of boese) {
      let s: SimState | undefined;
      expect(() => { s = createSim(input); }).not.toThrow();
      expect(() => advance(s!, 1, 4000)).not.toThrow();
      expect(() => standbild(s!)).not.toThrow();
      const snap = snapshot(s!);
      expect(s!.phase === "instabil" || isFiniteSnapshot(snap), `Eingabe ${boese.indexOf(input)}`).toBe(true);
      expect(s!.phase === "instabil" || s!.config.angepasst.length > 0).toBe(true);
      expect(s!.config.beschreibung.length).toBeLessThanOrEqual(400);
      expect(s!.config.beschreibung).not.toMatch(/[\u0000\u202e]/);
    }
    expect(createSim({ modell: "quatsch" }).phase).toBe("instabil");
    const g = createSim(boese[13]);
    expect(g.koerper).toBe(300);
    expect((g.kern as { r: number }).r).toBeGreaterThan(0);
    expect(g.config.angepasst).toEqual(expect.arrayContaining(["parameter.anzahl", "parameter.kasten", "parameter.radius", "parameter.geschwindigkeit"]));
    const voll = createSim(boese[14]);                       // 300 Teilchen in 1 x 1: Radius auf 30 % Fläche begrenzt, kein Überlappen
    const k = voll.kern as { r: number; N: number; px: Float64Array; py: Float64Array };
    for (let i = 0; i < k.N; i++) for (let j = i + 1; j < k.N; j++) expect(Math.hypot(k.px[i] - k.px[j], k.py[i] - k.py[j])).toBeGreaterThanOrEqual(2 * k.r * (1 - 1e-9));
    const s = createSim(pendel());
    expect(() => advance(s, NaN)).not.toThrow();
    expect(advance(s, -5).schritte).toBe(0);
    expect(advance(s, 1e300, NaN).begrenzt).toBe(true);
    expect(isFiniteSnapshot(snapshot(s))).toBe(true);
  });

  it("reports a broken state as unstable and keeps it there", () => {
    const s = createSim(pendel());
    (s.kern as { om: number }).om = NaN;
    advance(s, 0.1);
    expect(s.phase).toBe("instabil");
    expect(advance(s, 1).schritte).toBe(0);
    expect(isFiniteSnapshot(snapshot(s))).toBe(false);
  });

  it("gas with tiny positive radius and speed (1e-320, 5e-324) stays finite and does not hang", () => {
    const t = performance.now();
    for (const p of [{ radius: 1e-320, geschwindigkeit: 5e-324 }, { radius: 1e-320, geschwindigkeit: 10 }, { radius: 5e-324, geschwindigkeit: 1, schwerkraft: 100 },
      { radius: 1, geschwindigkeit: 5e-324 }]) {
      const s = createSim(gas({ anzahl: 300, ...p }));
      expect(s.phase).toBe("laeuft");
      expect(s.dt).toBeGreaterThan(0);
      for (let i = 0; i < 30; i++) advance(s, 1 / 30, 4000);
      expect(s.phase).toBe("laeuft");
      expect(isFiniteSnapshot(snapshot(s))).toBe(true);
      expect(bildEndlich(standbild(s))).toBe(true);
    }
    expect(performance.now() - t).toBeLessThan(5000);
    const still = createSim(gas({ geschwindigkeit: 5e-324 }));
    expect(still.config.angepasst).not.toContain("parameter.geschwindigkeit");
  });

  it("gas sub-step moves at most half a radius; when the frame limit cannot keep up, time runs slower instead of losing collisions", () => {
    const s = createSim(gas({ anzahl: 300, kasten: [1000, 100], radius: 5, geschwindigkeit: 10 }));  // 10000 Einheiten/s = 2000 Radien/s
    const k = s.kern as { r: number; v0: number; b: number; h: number };
    expect(k.v0 * s.dt).toBeLessThanOrEqual(0.5 * k.r + 1e-12);
    const e0 = wert(s, "bewegungsenergie");
    for (let i = 0; i < 60; i++) {
      const res = advance(s, s.tempo / 30, 4000);
      expect(res.begrenzt).toBe(true);
      expect(res.koerperSchritte).toBeLessThanOrEqual(4000);
      for (const p of snapshot(s).koerper) expect(p.x >= 5 && p.x <= 995 && p.y >= 5 && p.y <= 95).toBe(true);
    }
    expect(s.zeit).toBeLessThan(60 / 30);                    // Zeitlupe: weniger Modellzeit als verlangt
    expect(relativ(wert(s, "bewegungsenergie"), e0)).toBeLessThan(1e-9);
  });

  it("a straight drop from a tiny height (1e-320) lands at once and stays finite", () => {
    for (const luftwiderstand of [0, 0.5]) {
      const s = createSim(wurf({ winkel: -90, hoehe: 1e-320, luftwiderstand }));
      advance(s, 1);
      expect(s.phase).toBe("gelandet");
      expect(isFiniteSnapshot(snapshot(s))).toBe(true);
      expect(bildEndlich(standbild(s))).toBe(true);
      expect(s.text).not.toMatch(/NaN|Infinity/);
    }
  });
});

describe("Vorausrechnung, Standbild, Tempo und Spur", () => {
  it("respects the precomputation budget of 200000 body-steps", () => {
    for (const input of [wurf({ geschwindigkeit: 1000, winkel: 90, hoehe: 10000, luftwiderstand: 1 }), wurf({ geschwindigkeit: 1000, winkel: 0, hoehe: 10000, luftwiderstand: 1, g: 0.1 }),
      gas({ anzahl: 300, radius: 1.7, geschwindigkeit: 10 }), pendel({ laenge: 100, g: 0.1, anfangsgeschwindigkeit: 720, daempfung: 5 }),
      feder({ masse: 0.001, federkonstante: 1, daempfung: 10000 }), umlauf({ koerper: Array.from({ length: 8 }, (_, i) => koerper(1 + i, 0.9, 0, `K${i}`)) })]) {
      const s = createSim(input);
      standbild(s);
      expect(s.vorausSchritte, input.modell).toBeLessThanOrEqual(VORAUS_BUDGET);
      expect(s.vorausSchritte, input.modell).toBeGreaterThan(0);
    }
    const tief = createSim(wurf({ geschwindigkeit: 1000, winkel: 90, hoehe: 10000, luftwiderstand: 1 }));
    expect((standbild(tief) as { vollstaendig: boolean }).vollstaendig).toBe(true);
  });

  it("builds still pictures: curve over three periods, whole throw with peak and impact, all orbits, gas distribution after 10 s", () => {
    const p = standbild(createSim(pendel()));
    if (p.modell !== "pendel") throw new Error();
    expect(p.dauer).toBeCloseTo(3 * createSim(pendel()).periode, 2);
    expect(p.kurve.length).toBeLessThanOrEqual(600);
    expect(p.kurve[0][0]).toBe(0);
    expect(p.kurve[0][1]).toBeCloseTo(30, 9);
    const w = standbild(createSim(wurf({ luftwiderstand: 0.02 })));
    if (w.modell !== "wurf") throw new Error();
    expect(w.bahn.length).toBeLessThanOrEqual(602);
    expect(w.bahn).toContainEqual(w.gipfel);
    expect(w.aufprall[1]).toBe(0);
    expect(Math.max(...w.bahn.map((q) => q[1]))).toBe(w.gipfel[1]);
    const u = standbild(createSim(umlauf({ koerper: [koerper(1), koerper(2, 0.5, 0, "Mars")] })));
    if (u.modell !== "umlauf") throw new Error();
    expect(u.bahnen.map((b) => b.name)).toEqual(["Erde", "Mars"]);
    expect(u.start.koerper).toHaveLength(2);
    const g = standbild(createSim(gas({ anzahl: 50 })));
    if (g.modell !== "gas") throw new Error();
    expect(g.zeit).toBeCloseTo(10, 9);
    expect(g.verteilung.anzahl.reduce((a, b) => a + b, 0)).toBe(50);
    expect(g.start.verteilung!.anzahl.filter((n) => n > 0)).toHaveLength(1);   // am Start haben alle dieselbe Geschwindigkeit
    const s = createSim(gas({ anzahl: 50 }));
    expect(standbild(s)).toBe(standbild(s));
  });

  it("chooses the tempo so one oscillation, the flight or the innermost orbit takes 3 to 6 real seconds; gas runs at 1", () => {
    for (const input of [pendel(), pendel({ laenge: 100, g: 0.1 }), feder({ masse: 1000, federkonstante: 0.05 }), wurf(), wurf({ luftwiderstand: 0.5, hoehe: 100 }),
      umlauf({ zentralmasse: 0.01, koerper: [koerper(1000)] })]) {
      const s = createSim(input), echt = s.periode / s.tempo;
      expect(echt).toBeGreaterThanOrEqual(3);
      expect(echt).toBeLessThanOrEqual(6);
    }
    expect(createSim(gas()).tempo).toBe(1);
    expect(createSim(pendel({}, { tempo: 2.5 })).tempo).toBe(2.5);
    expect(createSim(pendel({}, { tempo: 0.01 })).tempo).toBe(0.1);
  });

  it("computes the extent once and keeps every body inside it", () => {
    for (const input of [pendel({ winkel: 170 }), pendel({ winkel: 0, anfangsgeschwindigkeit: 700 }), pendel({ winkel: 40 }), feder({ auslenkung: -3 }), wurf({ hoehe: 50, winkel: -30 }),
      wurf({ luftwiderstand: 0.1 }), umlauf({ koerper: [koerper(1, 0.9, 10), koerper(2, 0.3, 270, "B")] })]) {
      const s = createSim(input), a = s.ausschnitt;
      for (let i = 0; i < 300 && s.phase === "laeuft"; i++) {
        advance(s, s.periode / 100);
        const snap = snapshot(s);
        expect(snap.ausschnitt).toBe(a);
        for (const p of snap.koerper) expect(p.x >= a.minX && p.x <= a.maxX && p.y >= a.minY && p.y <= a.maxY, JSON.stringify(input.parameter)).toBe(true);
      }
    }
  });

  it("caps the trail at 600 points per body and 8 bodies", () => {
    const s = createSim(pendel()), t = createTrail(1);
    let last: SimSnapshot = snapshot(s);
    for (let i = 0; i < 2000; i++) { advance(s, 0.01); last = snapshot(s); addToTrail(t, last); }
    const pts = trailPoints(t, 0);
    expect(pts).toHaveLength(600);
    expect(pts[599]).toEqual([last.koerper[0].x, last.koerper[0].y]);
    addToTrail(t, last);
    expect(trailPoints(t, 0)).toHaveLength(600);
    expect(createTrail(300, 5000).xs).toHaveLength(8);
    expect(createTrail(1, 5000).max).toBe(600);
    expect(createTrail(NaN, NaN).xs).toHaveLength(0);
    expect(trailPoints(t, 5)).toEqual([]);
  });

  it("computes a frame of the heaviest case (300 particles, 4000 body-steps) fast", () => {
    const s = createSim(gas({ anzahl: 300, radius: 1.78, geschwindigkeit: 10, schwerkraft: 20 }));
    advance(s, 1, 4000);                                   // Aufwärmen
    const t = performance.now();
    let n = 0;
    for (let i = 0; i < 30; i++) { n += advance(s, 1, 4000).koerperSchritte; snapshot(s); }
    const ms = (performance.now() - t) / 30;
    console.info(`[physics] heaviest frame: ${ms.toFixed(2)} ms for ${n / 30} body-steps incl. snapshot`);
    expect(n / 30).toBeLessThanOrEqual(4000);
    expect(ms).toBeLessThan(50);
  });

  it("normalizes valid input without changes", () => {
    for (const input of [pendel(), feder(), wurf(), umlauf(), gas()]) expect(normalizeSim(input).angepasst).toEqual([]);
  });
});

describe("Gas: Raster, Zeit und Energie", () => {
  it("gas with few particles and a tiny radius stays in the time budget; the grid grows with the particle count", () => {
    for (const anzahl of [2, 3, 5, 10, 300]) {
      const input = gas({ anzahl, kasten: [100, 100], radius: 0.01, geschwindigkeit: 10, schwerkraft: 100, stoesse: true });
      const s = createSim(input), k = s.kern as GasKern;
      advance(s, 1 / 30, 4000);                                    // Aufwärmen
      let t = performance.now();
      for (let i = 0; i < 30; i++) { advance(s, 1 / 30, 4000); snapshot(s); }
      const bild = (performance.now() - t) / 30;
      const frisch = createSim(input);
      t = performance.now();
      standbild(frisch);
      const still = performance.now() - t;
      console.info(`[physics] gas ${anzahl} particles, radius 0.01: frame ${bild.toFixed(3)} ms, standbild ${still.toFixed(1)} ms`);
      expect(k.nx * k.ny, `${anzahl} Teilchen`).toBeLessThanOrEqual(4 * k.N + 16);
      expect(k.b / k.nx).toBeGreaterThanOrEqual(2 * k.r);         // Zelle ≥ Durchmesser: kein Stoß geht verloren
      expect(k.h / k.ny).toBeGreaterThanOrEqual(2 * k.r);
      expect(bild, `${anzahl} Teilchen`).toBeLessThan(5);
      expect(still, `${anzahl} Teilchen`).toBeLessThan(200);
      expect(frisch.vorausSchritte).toBeLessThanOrEqual(VORAUS_BUDGET);
    }
  });

  /** Zwei Teilchen von Hand gesetzt (Lagen und Geschwindigkeiten), danach `sekunden` Modellzeit gerechnet. */
  function zwei(radius: number, a: [number, number, number, number], b: [number, number, number, number], sekunden: number, stoesse = true) {
    const s = createSim(gas({ anzahl: 2, radius, geschwindigkeit: 0.1, stoesse }));
    const k = s.kern as GasKern;
    [k.px[0], k.py[0], k.vx[0], k.vy[0]] = a;
    [k.px[1], k.py[1], k.vx[1], k.vy[1]] = b;
    advance(s, sekunden);
    return k;
  }

  it("still finds collisions after the grid change: head-on and oblique, momentum and energy conserved", () => {
    for (const radius of [0.5, 0.01]) {
      // Frontal über eine Zellgrenze hinweg (Raster 4 x 4, Grenze bei 50): die Geschwindigkeiten tauschen sich.
      const d = 2 * radius;
      const k = zwei(radius, [45, 50, 10, 0], [55, 50, -10, 0], 0.7);
      expect(k.vx[0]).toBeCloseTo(-10, 9);
      expect(k.vx[1]).toBeCloseTo(10, 9);
      expect(k.vy[0]).toBeCloseTo(0, 12);
      expect(k.px[1] - k.px[0]).toBeGreaterThanOrEqual(d * (1 - 1e-9));
      // Schräg: Versatz 0,6 Durchmesser quer zur Bahn.
      const o = zwei(radius, [40, 50, 10, 0], [60, 50 + 0.6 * d, -10, 0], 1.5);
      expect(o.vx[0] + o.vx[1]).toBeCloseTo(0, 9);
      expect(o.vy[0] + o.vy[1]).toBeCloseTo(0, 9);
      expect(0.5 * (o.vx[0] ** 2 + o.vy[0] ** 2 + o.vx[1] ** 2 + o.vy[1] ** 2)).toBeCloseTo(100, 6);
      expect(Math.abs(o.vy[0])).toBeGreaterThan(1);                // abgelenkt, also wirklich gestoßen
      // Ohne Stöße fliegen sie durcheinander hindurch.
      const durch = zwei(radius, [45, 50, 10, 0], [55, 50, -10, 0], 0.7, false);
      expect(durch.vx[0]).toBe(10);
    }
  });

  it("without collisions all speeds stay in one histogram bin", () => {
    const s = createSim(gas({ anzahl: 300, radius: 1, geschwindigkeit: 3, stoesse: false }));
    for (let i = 0; i < 60; i++) advance(s, 1 / 30);
    expect(snapshot(s).verteilung!.anzahl.filter((n) => n > 0)).toHaveLength(1);
  });

  it("gas with gravity 100 keeps its total energy within 0.1 % and nobody leaves the box", () => {
    for (const p of [{ anzahl: 100, radius: 1, geschwindigkeit: 1 }, { anzahl: 2, radius: 0.5, geschwindigkeit: 0.3 }, { anzahl: 300, radius: 1.5, geschwindigkeit: 0.5 }]) {
      const s = createSim(gas({ ...p, schwerkraft: 100 })), k = s.kern as GasKern;
      const energie = () => { let e = 0; for (let i = 0; i < k.N; i++) e += 0.5 * (k.vx[i] ** 2 + k.vy[i] ** 2) + k.g * k.py[i]; return e / k.N; };
      const e0 = energie();
      let summe = 0, n = 0, maxAbw = 0;
      for (let i = 0; i < 300; i++) {
        advance(s, 1 / 30);
        const e = energie();
        summe += e; n++; maxAbw = Math.max(maxAbw, relativ(e, e0));
        for (let j = 0; j < k.N; j++) expect(k.px[j] >= k.r && k.px[j] <= k.b - k.r && k.py[j] >= k.r && k.py[j] <= k.h - k.r).toBe(true);
      }
      expect(relativ(summe / n, e0), JSON.stringify(p)).toBeLessThan(0.001);
      expect(maxAbw, JSON.stringify(p)).toBeLessThan(0.001);
    }
  });
});

describe("Wurf mit Luftwiderstand gegen eine unabhängige Rechnung", () => {
  /** Runge-Kutta vierter Ordnung, quadratischer Luftwiderstand a = −k·|v|·v − g·ŷ, kleiner Schritt (an die Bremsung angepasst). */
  function rk4(v: number, winkel: number, h: number, g: number, k: number) {
    const a = (winkel * Math.PI) / 180;
    let x = 0, y = h, vx = v * Math.cos(a), vy = v * Math.sin(a), t = 0, gipfel = h;
    const f = (ux: number, uy: number): [number, number] => { const s = Math.hypot(ux, uy); return [-k * s * ux, -g - k * s * uy]; };
    for (let i = 0; i < 5e7; i++) {
      const dt = Math.min(2e-4, 1e-3 / (k * Math.hypot(vx, vy) + 1e-12));
      const [a1x, a1y] = f(vx, vy);
      const [a2x, a2y] = f(vx + 0.5 * dt * a1x, vy + 0.5 * dt * a1y);
      const [a3x, a3y] = f(vx + 0.5 * dt * a2x, vy + 0.5 * dt * a2y);
      const [a4x, a4y] = f(vx + dt * a3x, vy + dt * a3y);
      const nx = x + (dt / 6) * (vx + 2 * (vx + 0.5 * dt * a1x) + 2 * (vx + 0.5 * dt * a2x) + (vx + dt * a3x));
      const ny = y + (dt / 6) * (vy + 2 * (vy + 0.5 * dt * a1y) + 2 * (vy + 0.5 * dt * a2y) + (vy + dt * a3y));
      vx += (dt / 6) * (a1x + 2 * a2x + 2 * a3x + a4x);
      vy += (dt / 6) * (a1y + 2 * a2y + 2 * a3y + a4y);
      if (ny < 0) { const q = y / (y - ny); return { flugzeit: t + q * dt, reichweite: x + q * (nx - x), gipfel }; }
      x = nx; y = ny; t += dt; gipfel = Math.max(gipfel, y);
    }
    throw new Error("RK4 landet nicht");
  }

  it("range, peak and flight time agree with RK4 within 0.5 %", () => {
    for (const [v, a, h, k] of [[20, 45, 0, 0.01], [50, 70, 100, 0.2], [300, 30, 0, 0.001], [10, -20, 50, 0.5], [100, 45, 0, 0.05]]) {
      const s = createSim(wurf({ geschwindigkeit: v, winkel: a, hoehe: h, luftwiderstand: k })), soll = rk4(v, a, h, 9.81, k);
      const fall = JSON.stringify([v, a, h, k]);
      expect(relativ(wert(s, "flugzeit"), soll.flugzeit), fall).toBeLessThan(0.005);
      expect(relativ(wert(s, "reichweite"), soll.reichweite), fall).toBeLessThan(0.005);
      expect(relativ(wert(s, "gipfelhoehe"), soll.gipfel), fall).toBeLessThan(0.005);
    }
  });
});

describe("Gleiche Ergebnisse für jede Bildrate", () => {
  it("gives identical results for fixed chunks of 1/24, 1/30, 1/60 and 1/144 s", () => {
    for (const input of [pendel({ winkel: 120, daempfung: 0.1 }), gas({ anzahl: 60, schwerkraft: 30 }), wurf({ luftwiderstand: 0.05, hoehe: 20 })]) {
      const bilder = [1 / 24, 1 / 30, 1 / 60, 1 / 144].map((c) => {
        const s = createSim(input), T = Math.round((2 * s.tempo) / s.dt) * s.dt;
        while (s.phase === "laeuft" && s.soll + c * s.tempo <= T) advance(s, c * s.tempo);
        if (T - s.soll > 0) advance(s, T - s.soll);
        expect(s.phase, input.modell).toBe("laeuft");
        return snapshot(s);
      });
      for (const b of bilder) expect(b, input.modell).toEqual(bilder[0]);
    }
  });
});

describe("Zahlen in der Textfassung", () => {
  it("keeps the decimals of a parameter without float tails", () => {
    expect(formatZahl(120.5)).toBe("120,5");
    expect(formatZahl(1234.5)).toBe("1234,5");
    expect(formatZahl(12345.5)).toBe("12 345,5");
    expect(formatZahl(1e6)).toBe("1 000 000");
    expect(formatZahl(0.1 + 0.2)).toBe("0,3");
    expect(formatZahl(100)).toBe("100");
    expect(formatZahl(999.25)).toBe("999,25");
    expect(formatZahl(-0.25)).toBe("-0,25");
    expect(formatZahl(2 / 3)).toBe("0,666667");
    expect(formatZahl(1.5e-7)).toBe("0,00000015");
    expect(formatZahl(1e-13)).toBe("0");
    expect(formatZahl(-1e-13)).toBe("0");
    expect(formatZahl(Infinity)).toBe("–");
    expect(createSim(gas({ kasten: [120.5, 100] })).text).toContain("Kasten 120,5 mal 100 Einheiten");
    expect(createSim(wurf({ geschwindigkeit: 250.75 })).text).toContain("Wurf mit 250,75 m/s");
  });
});

describe("Starke Dämpfung", () => {
  it("a strongly damped spring creeps back at the wanted tempo and its energy never rises", () => {
    for (const input of [feder({ masse: 0.001, federkonstante: 1e6, auslenkung: 10, daempfung: 10000 }), feder({ daempfung: 10000 }),
      feder({ masse: 0.001, federkonstante: 20, daempfung: 3 })]) {
      const s = createSim(input), soll = s.tempo / 30, k = s.kern as FederKern;
      let e = wert(s, "energie"), x = k.x;
      for (let i = 0; i < 300; i++) {
        const z = s.zeit, res = advance(s, soll, 4000);
        expect(res.begrenzt).toBe(false);
        expect(s.zeit - z, JSON.stringify(input.parameter)).toBeGreaterThanOrEqual(0.5 * soll);
        const en = wert(s, "energie");
        expect(en).toBeLessThanOrEqual(e + 1e-9);
        e = en;
        if (k.zeta >= 1) { expect(k.x).toBeGreaterThanOrEqual(0); expect(k.x).toBeLessThanOrEqual(x); }
        x = k.x;
      }
    }
  });

  it("an overdamped spring returns to rest without oscillating and follows the closed-form solution", () => {
    for (const daempfung of [50, 2 * Math.sqrt(10), 7, 1e4]) {
      const s = createSim(feder({ masse: 1, federkonstante: 10, auslenkung: 0.5, daempfung })), k = s.kern as FederKern;
      const w0 = Math.sqrt(10), a = daempfung / 2, q = Math.sqrt(Math.max(0, a * a - w0 * w0));
      const exakt = (t: number) => q > 1e-9 * a
        ? (0.5 / (2 * q)) * ((q + a) * Math.exp((-a + q) * t) + (q - a) * Math.exp((-a - q) * t))
        : 0.5 * (1 + w0 * t) * Math.exp(-w0 * t);
      let prev = k.x;
      while (s.zeit < 10 * s.periode) {
        schritte(s, 7);
        expect(k.x).toBeGreaterThanOrEqual(0);
        expect(k.x).toBeLessThanOrEqual(prev);
        expect(Math.abs(k.x - exakt(s.zeit))).toBeLessThan(1e-9 + 1e-6 * exakt(s.zeit));
        prev = k.x;
      }
      expect(k.x).toBeLessThan(1e-3 * 0.5);
    }
  });

  it("a strongly damped long pendulum creeps at the wanted tempo and its energy never rises", () => {
    const s = createSim(pendel({ laenge: 100, g: 0.1, daempfung: 5, winkel: 30 })), soll = s.tempo / 30;
    let e = wert(s, "energie"), th = (s.kern as { th: number }).th;
    for (let i = 0; i < 300; i++) {
      const z = s.zeit;
      expect(advance(s, soll, 4000).begrenzt).toBe(false);
      expect(s.zeit - z).toBeGreaterThanOrEqual(0.5 * soll);
      const en = wert(s, "energie"), t = (s.kern as { th: number }).th;
      expect(en).toBeLessThanOrEqual(e + 1e-9);
      expect(t).toBeGreaterThan(0);
      expect(t).toBeLessThanOrEqual(th);
      e = en; th = t;
    }
  });
});

describe("Eingabe wie im Python-Schema", () => {
  it("rejects a throw from height 0 that does not go upwards, and orbits with a semi-major axis ratio above 100", () => {
    for (const winkel of [0, -30, -90]) {
      const s = createSim(wurf({ hoehe: 0, winkel }));
      expect(s.config.ungueltig).toBe(true);
      expect(s.phase).toBe("instabil");
    }
    expect(createSim(wurf({ hoehe: 0, winkel: 0.5 })).config.ungueltig).toBe(false);
    expect(createSim(wurf({ hoehe: 1, winkel: -30 })).config.ungueltig).toBe(false);
    const weit = createSim(umlauf({ koerper: [koerper(0.5), koerper(60, 0, 0, "Mars")] }));
    expect(weit.config.ungueltig).toBe(true);
    expect(weit.phase).toBe("instabil");
    expect(createSim(umlauf({ koerper: [koerper(1), koerper(100, 0, 0, "Mars")] })).config.ungueltig).toBe(false);
    expect(createSim(umlauf({ koerper: [koerper(1), koerper(1, 0, 0, "Erde")] })).config.ungueltig).toBe(false);   // gleiche Namen erlaubt
  });

  it("names every replaced or clamped field in angepasst", () => {
    const faelle: Record<string, unknown>[] = [
      pendel({ laenge: 500, winkel: "30", g: 0 }),
      feder({ masse: 0.001, federkonstante: 1e6, daempfung: -1 }),
      wurf({ geschwindigkeit: 0, luftwiderstand: 2, hoehe: 20000 }),
      umlauf({ zentralmasse: 1000, koerper: [{ name: "x".repeat(40), abstand: 2000, exzentrizitaet: 1, phase: 30, farbe: "rot" },
        { abstand: 1, exzentrizitaet: 0, phase: 0, farbe: "ok" }, { name: "a‮b", abstand: 5, exzentrizitaet: 0, phase: 400, farbe: "ok" }] }),
      gas({ anzahl: 2.7, startwert: 3.5, kasten: [5000, 10], radius: 50, geschwindigkeit: 20, schwerkraft: -1, stoesse: "ja" }),
      gas({ anzahl: 299.5, kasten: [1, 1], radius: 0 }),
      { ...pendel(), laufzeit: 1, tempo: 0.01, spur: "ja", beschreibung: "a\u0000b" },
      { ...pendel(), beschreibung: "x".repeat(500), tempo: 1000 },
    ];
    for (const input of faelle) {
      const cfg = normalizeSim(input) as unknown as Record<string, unknown>;
      const genannt = (pfad: string) => cfg.angepasst instanceof Array && cfg.angepasst.some((a: string) => pfad === a || pfad.startsWith(a + "."));
      for (const key of ["laufzeit", "tempo", "spur", "beschreibung"]) {
        if (cfg[key] !== input[key]) expect(genannt(key), `${key} in ${JSON.stringify(input)}`).toBe(true);
      }
      const roh = input.parameter as Record<string, unknown>, neu = cfg.parameter as Record<string, unknown>;
      for (const key of Object.keys(neu)) {
        if (key === "koerper") {
          (neu.koerper as Record<string, unknown>[]).forEach((kn, i) => {
            const kr = (roh.koerper as Record<string, unknown>[])[i];
            for (const f of Object.keys(kn)) if (kn[f] !== kr[f]) expect(genannt(`parameter.koerper.${i}.${f}`), `koerper.${i}.${f}`).toBe(true);
          });
        } else if (JSON.stringify(neu[key]) !== JSON.stringify(roh[key])) {
          expect(genannt(`parameter.${key}`), `${key} in ${JSON.stringify(roh)}`).toBe(true);
        }
      }
    }
  });

  it("treats __proto__ as an ordinary own key and survives a throwing getter", () => {
    const roh = JSON.parse('{"modell":"pendel","__proto__":{"modell":"gas"},"parameter":{"__proto__":{"laenge":50},"laenge":2,"winkel":10}}');
    expect(Object.prototype.hasOwnProperty.call(roh, "__proto__")).toBe(true);
    const s = createSim(roh);
    expect(s.modell).toBe("pendel");
    expect((s.config.parameter as { laenge: number }).laenge).toBe(2);
    expect(({} as Record<string, unknown>).laenge).toBeUndefined();
    expect(({} as Record<string, unknown>).modell).toBeUndefined();
    const nur = createSim(JSON.parse('{"__proto__":{"modell":"gas","parameter":{"anzahl":5}}}'));
    expect(nur.config.ungueltig).toBe(true);
    expect(nur.phase).toBe("instabil");
    const u = createSim(JSON.parse('{"modell":"umlauf","parameter":{"koerper":[{"__proto__":{"abstand":50},"abstand":2,"name":"__proto__","farbe":"ok","phase":0,"exzentrizitaet":0}]}}'));
    expect(u.phase).toBe("laeuft");
    expect((u.config.parameter as { koerper: { abstand: number; name: string }[] }).koerper[0]).toMatchObject({ abstand: 2, name: "__proto__" });
    const wirft = { modell: "pendel", parameter: { get laenge(): number { throw new Error("böse"); } } };
    let w: SimState | undefined;
    expect(() => { w = createSim(wirft); }).not.toThrow();
    expect(() => advance(w!, 1, 4000)).not.toThrow();
    expect(() => standbild(w!)).not.toThrow();
    expect(w!.phase === "instabil" || isFiniteSnapshot(snapshot(w!))).toBe(true);
    expect(w!.config.angepasst.length).toBeGreaterThan(0);
  });
});

// --- P5b: Doppelpendel, Welle, Umlauf mit Anziehung, Regler ----------------------------------------------------------

const dp = (p: object = {}, extra: object = {}) => ({
  ...basis, modell: "doppelpendel",
  parameter: { laenge1: 1, laenge2: 1, masse1: 1, masse2: 1, winkel1: 90, winkel2: 0, g: 9.81, daempfung: 0, ...p }, ...extra,
});
const w1 = (w: object = {}) => ({ amplitude: 0.5, wellenlaenge: 2, frequenz: 1, phase: 0, richtung: "rechts", ...w });
const welle = (wellen: object[] = [w1()], p: object = {}, extra: object = {}) => ({ ...basis, modell: "welle", parameter: { wellen, bereich: 0, ...p }, ...extra });
const mk = (abstand: number, e: number, phase: number, name: string, masse: number) => ({ ...koerper(abstand, e, phase, name), masse });
const nk = (liste: object[], p: object = {}, extra: object = {}) => umlauf({ anziehung: true, koerper: liste, ...p }, extra);

/** Energie des Doppelpendels unabhängig vom Modul gerechnet (Nullpunkt ganz unten). */
function dpEnergieTest(s: SimState): number {
  const k = s.kern as DoppelpendelKern, M = k.m1 + k.m2;
  return 0.5 * M * k.L1 ** 2 * k.om1 ** 2 + 0.5 * k.m2 * k.L2 ** 2 * k.om2 ** 2 + k.m2 * k.L1 * k.L2 * k.om1 * k.om2 * Math.cos(k.th1 - k.th2)
    + M * k.g * k.L1 * (1 - Math.cos(k.th1)) + k.m2 * k.g * k.L2 * (1 - Math.cos(k.th2));
}

/** Kepler-Lage ohne Anziehung zur Zeit t (geschlossen, unabhängig von der Simulation). */
function keplerLage(M: number, a: number, e: number, phaseGrad: number, t: number): [number, number] {
  const nu = (phaseGrad * Math.PI) / 180, P = Math.sqrt(a ** 3 / M);
  const E0 = 2 * Math.atan2(Math.sqrt(1 - e) * Math.sin(nu / 2), Math.sqrt(1 + e) * Math.cos(nu / 2));
  const E = solveKepler(E0 - e * Math.sin(E0) + (TAU * t) / P, e);
  return [a * (Math.cos(E) - e), a * Math.sqrt(1 - e * e) * Math.sin(E)];
}

describe("Doppelpendel", () => {
  it("keeps its energy within 0.5 % over 30 s without damping, also for large angles and unequal arms", () => {
    for (const input of [dp(), dp({ winkel1: 120, winkel2: -30 }), dp({ winkel1: 180, winkel2: 179 }), dp({ winkel1: -170, winkel2: 170, laenge2: 0.5, masse2: 3 }),
      dp({ laenge1: 2, laenge2: 0.3, masse1: 0.2, masse2: 5, winkel1: 150, winkel2: -100, g: 25 })]) {
      const s = createSim(input), e0 = dpEnergieTest(s);
      let maxAbw = 0;
      while (s.zeit < 30) {
        schritte(s, Math.max(1, Math.round(0.05 / s.dt)));
        maxAbw = Math.max(maxAbw, relativ(dpEnergieTest(s), e0));
      }
      expect(s.phase).toBe("laeuft");
      console.info(`[physics] doppelpendel ${input.parameter.winkel1}/${input.parameter.winkel2}: dt ${s.dt.toExponential(2)} s, energy drift over 30 s ${(100 * maxAbw).toExponential(1)} %`);
      expect(maxAbw, JSON.stringify(input.parameter)).toBeLessThan(0.005);
      expect(Math.abs(wert(s, "energie") - 100)).toBeLessThan(0.5);
    }
  });

  it("with damping the energy never rises", () => {
    for (const input of [dp({ daempfung: 0.1 }), dp({ daempfung: 5, winkel1: 170, winkel2: -170 }), dp({ daempfung: 0.01, winkel1: 180, winkel2: 90, masse2: 0.1 })]) {
      const s = createSim(input);
      let prev = wert(s, "energie");
      for (let i = 0; i < 20000; i++) {
        schritte(s, 1);
        const e = wert(s, "energie");
        expect(e, `${JSON.stringify(input.parameter)} Schritt ${i}`).toBeLessThanOrEqual(prev + 1e-9);
        prev = e;
      }
      expect(prev).toBeLessThan(100);
    }
  });

  it("small angles: oscillates with the normal-mode periods of the linearised double pendulum (1 %)", () => {
    for (const [L1, L2, m1, m2, g] of [[1, 1, 1, 1, 9.81], [2, 0.5, 3, 1, 9.81], [0.3, 1.2, 0.5, 2, 1.62]]) {
      // m1·L1·L2·x² − (m1+m2)·g·(L1+L2)·x + (m1+m2)·g² = 0 mit x = ω², hier mit der Schulformel gelöst.
      const a = m1 * L1 * L2, b = -(m1 + m2) * g * (L1 + L2), c = (m1 + m2) * g * g, d = Math.sqrt(b * b - 4 * a * c);
      const moden = [(-b - d) / (2 * a), (-b + d) / (2 * a)];
      const eigen = doppelpendelEigen(L1, L2, m1, m2, g);
      expect(relativ(eigen[0], moden[0])).toBeLessThan(1e-12);
      expect(relativ(eigen[1], moden[1])).toBeLessThan(1e-12);
      for (const x of moden) {
        const r = ((m1 + m2) * (g - x * L1)) / (x * m2 * L2), eps = 0.5 / Math.max(1, Math.abs(r));   // Eigenform θ2/θ1 = r
        const s = createSim(dp({ laenge1: L1, laenge2: L2, masse1: m1, masse2: m2, g, winkel1: eps, winkel2: eps * r }));
        const T = TAU / Math.sqrt(x);
        const z = nulldurchgaenge(s, () => (s.kern as DoppelpendelKern).th1, Math.ceil((5.2 * T) / s.dt));
        expect(z.length, `${[L1, L2, m1, m2, g]} T = ${T}`).toBeGreaterThanOrEqual(5);
        expect(relativ((z[z.length - 1] - z[0]) / (z.length - 1), T), `${[L1, L2, m1, m2, g]} T = ${T}`).toBeLessThan(0.01);
      }
    }
  });

  it("names it chaotic, shows both angles and the energy, keeps a trail for the lower bob only, stays in its extent", () => {
    const s = createSim(dp({ winkel1: 120, winkel2: -30 }));
    expect(s.text).toBe("Doppelpendel, Längen 1 m und 1 m, Massen 1 kg und 1 kg, Start bei 120 Grad und -30 Grad, ohne Dämpfung. "
      + "Kleine Schwingungen dauern etwa 2,6 s (beide Arme gleichsinnig) oder 1,1 s (gegensinnig). "
      + "Die Bewegung ist chaotisch: kleinste Änderungen am Start führen zu ganz anderen Bahnen.");
    const snap = snapshot(s);
    expect(snap.kennwerte.map((k) => k.id)).toEqual(["winkel1", "winkel2", "energie"]);
    expect(wert(snap, "winkel1")).toBeCloseTo(120, 9);
    expect(wert(snap, "winkel2")).toBeCloseTo(-30, 9);
    expect(snap.kennwerte[2].text).toBe("100 %");
    expect(snap.spurKoerper).toEqual([1]);
    expect(snap.anker).toEqual([0, 0]);
    expect(snap.koerper).toHaveLength(2);
    expect(snap.koerper[1].x).toBeCloseTo(Math.sin((120 * Math.PI) / 180) + Math.sin((-30 * Math.PI) / 180), 12);
    expect(s.koerper).toBe(2);
    expect(s.periode / s.tempo).toBeGreaterThanOrEqual(3);
    expect(s.periode / s.tempo).toBeLessThanOrEqual(6);
    expect(createSim(dp({ daempfung: 0.5, g: 3.7 })).text).toContain("Dämpfung 0,5 pro Sekunde, Fallbeschleunigung 3,7 m/s²");
    for (const input of [dp({ winkel1: 120, winkel2: -30 }), dp({ winkel1: 30, winkel2: 10 }), dp({ winkel1: 180, winkel2: 180, masse1: 0.01 }), dp({ laenge1: 0.1, laenge2: 3, winkel1: 90 })]) {
      const q = createSim(input), a = q.ausschnitt;
      for (let i = 0; i < 400; i++) {
        advance(q, q.periode / 50, 1e6);
        for (const p of snapshot(q).koerper) expect(p.x >= a.minX && p.x <= a.maxX && p.y >= a.minY && p.y <= a.maxY, JSON.stringify(input.parameter)).toBe(true);
      }
    }
  });

  it("is deterministic: same input, same numbers; chunks of 1/24, 1/30, 1/60 and 1/144 s give identical results", () => {
    const input = dp({ winkel1: 150, winkel2: -60, daempfung: 0.05 });
    const a = createSim(input), b = createSim(input);
    schritte(a, 10000); schritte(b, 10000);
    expect(snapshot(a)).toEqual(snapshot(b));
    const bilder = [1 / 24, 1 / 30, 1 / 60, 1 / 144].map((c) => {
      const s = createSim(input), T = Math.round((2 * s.tempo) / s.dt) * s.dt;
      while (s.soll + c * s.tempo <= T) advance(s, c * s.tempo);
      if (T - s.soll > 0) advance(s, T - s.soll);
      return snapshot(s);
    });
    for (const q of bilder) expect(q).toEqual(bilder[0]);
  });

  it("chooses a step from the fast normal mode and from the energy, so fast rotations stay accurate", () => {
    const ruhig = createSim(dp({ winkel1: 1, winkel2: 1 })), k = ruhig.kern as DoppelpendelKern;
    expect(ruhig.dt).toBeCloseTo(k.Tschnell / 2000, 15);
    const wild = createSim(dp({ winkel1: 180, winkel2: 0, masse1: 1000, masse2: 0.01 }));
    expect(wild.dt).toBeLessThan((wild.kern as DoppelpendelKern).Tschnell / 2000);
    // Größte mögliche Winkelgeschwindigkeit aus der Energie: höchstens 2π/500 rad je Schritt.
    const kw = wild.kern as DoppelpendelKern, E = dpEnergieTest(wild);
    const lmin = (kw.m1 * kw.m2 * kw.L1 ** 2 * kw.L2 ** 2) / ((kw.m1 + kw.m2) * kw.L1 ** 2 + kw.m2 * kw.L2 ** 2);
    expect(Math.sqrt((2 * E) / lmin) * wild.dt).toBeLessThanOrEqual(TAU / 500 + 1e-12);
    // Läuft trotzdem im Budget je Bild (Tempo automatisch).
    expect(advance(wild, wild.tempo / 30, 4000).koerperSchritte).toBeLessThanOrEqual(4000);
  });

  it("still picture: start position and the path of the lower bob over the first 10 s, within the budget", () => {
    const s = createSim(dp({ winkel1: 120, winkel2: -30 })), b = standbild(s);
    if (b.modell !== "doppelpendel") throw new Error(b.modell);
    expect(b.dauer).toBeCloseTo(10, 2);
    expect(b.bahn.length).toBeGreaterThan(100);
    expect(b.bahn.length).toBeLessThanOrEqual(1200);
    expect(b.bahn[0]).toEqual([snapshot(s).koerper[1].x, snapshot(s).koerper[1].y]);
    expect(b.start).toBe(s.startBild);
    expect(s.vorausSchritte).toBeLessThanOrEqual(VORAUS_BUDGET);
    // Der Weg ist derselbe wie im Lauf: nach 10 s steht der untere Körper am letzten Punkt.
    const lauf = createSim(dp({ winkel1: 120, winkel2: -30 }));
    schritte(lauf, Math.round(b.dauer / lauf.dt));
    expect(b.bahn[b.bahn.length - 1]).toEqual([snapshot(lauf).koerper[1].x, snapshot(lauf).koerper[1].y]);
    const schwer = createSim(dp({ laenge1: 100, laenge2: 0.05, masse1: 0.01, masse2: 1000, winkel1: 180, winkel2: 180 }));
    const sb = standbild(schwer);
    if (sb.modell !== "doppelpendel") throw new Error(sb.modell);
    expect(schwer.vorausSchritte).toBeLessThanOrEqual(VORAUS_BUDGET);
    expect(sb.dauer).toBeLessThan(10);                                    // passt nicht ganz ins Budget: kürzer
    expect(bildEndlich(sb)).toBe(true);
  });
});

describe("Welle", () => {
  const kurveBei = (s: SimState) => snapshot(s).kurve!;

  it("a single wave is A·sin(kx − ωt + φ) at every point, at start and later", () => {
    for (const richtung of ["rechts", "links"]) {
      const A = 0.7, lam = 1.5, f = 2, ph = 40;
      const s = createSim(welle([w1({ amplitude: A, wellenlaenge: lam, frequenz: f, phase: ph, richtung })], { bereich: 3 }));
      for (const n of [0, 137, 4000]) {
        schritte(s, n);
        const t = s.zeit, kurve = kurveBei(s), sgn = richtung === "rechts" ? -1 : 1;
        expect(kurve).toHaveLength(WELLE_PUNKTE);
        expect(kurve[0][0]).toBe(0);
        expect(kurve[WELLE_PUNKTE - 1][0]).toBeCloseTo(3, 12);
        for (const [x, y] of kurve) expect(Math.abs(y - A * Math.sin((TAU / lam) * x + sgn * TAU * f * t + (ph * Math.PI) / 180))).toBeLessThan(1e-12);
        expect(snapshot(s).teilkurven).toEqual([kurve]);
      }
    }
  });

  it("two and three waves superpose point by point", () => {
    const wellen = [w1({ amplitude: 0.3, wellenlaenge: 1, frequenz: 1 }), w1({ amplitude: 0.2, wellenlaenge: 0.7, frequenz: 1.7, phase: 90, richtung: "links" }),
      w1({ amplitude: 0.1, wellenlaenge: 3, frequenz: 0.4, phase: 300 })];
    const s = createSim(welle(wellen, { bereich: 4 }));
    schritte(s, 777);
    const snap = snapshot(s), t = s.zeit;
    expect(snap.teilkurven).toHaveLength(3);
    snap.kurve!.forEach(([x, y], i) => {
      const summe = snap.teilkurven!.reduce((a, q) => a + q[i][1], 0);
      expect(Math.abs(y - summe)).toBeLessThan(1e-12);
      const soll = wellen.reduce((a, q) => a + q.amplitude * Math.sin((TAU / q.wellenlaenge) * x + (q.richtung === "rechts" ? -1 : 1) * TAU * q.frequenz * t + (q.phase * Math.PI) / 180), 0);
      expect(Math.abs(y - soll)).toBeLessThan(1e-12);
    });
    expect(wert(snap, "auslenkung")).toBe(Math.max(...snap.kurve!.map((p) => Math.abs(p[1]))));
    expect(createSim(welle(wellen.slice(0, 2))).text).toMatch(/^Überlagerung von zwei Wellen über 2 m \(doppelte größte Wellenlänge\)\. Welle 1: /);
    expect(s.text).toMatch(/^Überlagerung von drei Wellen über 4 m\. /);
  });

  it("„rechts“ moves the crest to larger x, „links“ to smaller x", () => {
    for (const [richtung, soll] of [["rechts", 0.375], ["links", 0.125]] as const) {
      const s = createSim(welle([w1({ amplitude: 1, wellenlaenge: 1, frequenz: 1, richtung })], { bereich: 1 }));
      const gipfel = () => { const k = kurveBei(s); let m = 0; k.forEach((p, i) => { if (p[1] > k[m][1]) m = i; }); return k[m][0]; };
      expect(gipfel()).toBeCloseTo(0.25, 2);
      advance(s, 1 / 8);                                                // ein Achtel der Periode
      expect(s.zeit).toBeCloseTo(1 / 8, 9);
      expect(gipfel(), richtung).toBeCloseTo(soll, 2);
    }
  });

  it("two equal waves running against each other form a standing wave with fixed nodes", () => {
    const s = createSim(welle([w1({ amplitude: 1, wellenlaenge: 2, frequenz: 0.5 }), w1({ amplitude: 1, wellenlaenge: 2, frequenz: 0.5, richtung: "links" })], { bereich: 3.99 }));
    expect(s.text).toContain("Zusammen ergeben sie eine stehende Welle mit festen Knoten.");
    let bauch = 0;
    for (let i = 0; i < 40; i++) {
      const k = kurveBei(s);
      for (const n of [0, 100, 200, 300]) expect(Math.abs(k[n][1])).toBeLessThan(1e-9);   // Knoten bei x = 0, 1, 2, 3 m
      bauch = Math.max(bauch, Math.abs(k[50][1]));
      advance(s, 0.13);
    }
    expect(bauch).toBeGreaterThan(1.9);                                 // Bauch bei x = 0,5 m schwingt bis fast 2·A
    const b = standbild(s);
    if (b.modell !== "welle") throw new Error(b.modell);
    expect(b.exakt).toBe(true);
    expect(b.huelleMax[100][1]).toBeLessThan(1e-9);
    expect(b.huelleMax[50][1]).toBeCloseTo(2 * Math.abs(Math.sin(Math.PI * b.huelleMax[50][0])), 9);
  });

  it("automatic range is twice the largest wavelength; automatic tempo shows one period of the slowest wave in 3 to 6 s", () => {
    const s = createSim(welle([w1({ wellenlaenge: 2, frequenz: 3 }), w1({ wellenlaenge: 5, frequenz: 0.2 })]));
    expect((s.kern as WelleKern).bereich).toBe(10);
    expect(s.ausschnitt.maxX).toBe(10);
    expect(s.ausschnitt.minX).toBe(0);
    expect(s.ausschnitt.maxY).toBeCloseTo(1.1 * 1, 12);
    expect(kurveBei(s)[WELLE_PUNKTE - 1][0]).toBe(10);
    expect(s.periode).toBeCloseTo(5, 12);
    for (const input of [welle(), welle([w1({ frequenz: 100 })]), welle([w1({ frequenz: 0.01 }), w1({ frequenz: 50 })])]) {
      const q = createSim(input);
      expect(q.periode / q.tempo).toBeGreaterThanOrEqual(3);
      expect(q.periode / q.tempo).toBeLessThanOrEqual(6);
    }
    const snap = snapshot(s);
    expect(snap.kennwerte.map((k) => k.id)).toEqual(["periode.0", "geschwindigkeit.0", "periode.1", "geschwindigkeit.1", "auslenkung"]);
    expect(wert(snap, "periode.0")).toBeCloseTo(1 / 3, 12);
    expect(wert(snap, "geschwindigkeit.1")).toBeCloseTo(1, 12);
  });

  it("still picture: curve at t = 0 and the envelope over one period of the slowest wave", () => {
    const eine = standbild(createSim(welle([w1({ amplitude: 0.4 })])));
    if (eine.modell !== "welle") throw new Error(eine.modell);
    expect(eine.exakt).toBe(true);
    for (const p of eine.huelleMax) expect(p[1]).toBeCloseTo(0.4, 12);
    for (const p of eine.huelleMin) expect(p[1]).toBeCloseTo(-0.4, 12);
    expect(eine.kurve).toEqual(eine.start.kurve);
    const s = createSim(welle([w1({ amplitude: 0.3, frequenz: 1 }), w1({ amplitude: 0.2, frequenz: 1.5, wellenlaenge: 0.8, richtung: "links" })]));
    const b = standbild(s);
    if (b.modell !== "welle") throw new Error(b.modell);
    expect(b.exakt).toBe(false);
    expect(b.dauer).toBe(1);
    b.kurve.forEach((p, i) => {
      expect(b.huelleMin[i][1]).toBeLessThanOrEqual(p[1]);
      expect(b.huelleMax[i][1]).toBeGreaterThanOrEqual(p[1]);
      expect(b.huelleMax[i][1]).toBeLessThanOrEqual(0.5 + 1e-12);
    });
    expect(Math.max(...b.huelleMax.map((p) => p[1]))).toBeGreaterThan(0.45);
    expect(s.vorausSchritte).toBeLessThanOrEqual(VORAUS_BUDGET);
    expect(bildEndlich(b)).toBe(true);
  });

  it("is deterministic for every chunk size", () => {
    const input = welle([w1({ frequenz: 1.3 }), w1({ frequenz: 0.7, richtung: "links" })]);
    const bilder = [1 / 24, 1 / 30, 1 / 60, 1 / 144].map((c) => {
      const s = createSim(input), T = Math.round((2 * s.tempo) / s.dt) * s.dt;
      while (s.soll + c * s.tempo <= T) advance(s, c * s.tempo);
      if (T - s.soll > 0) advance(s, T - s.soll);
      return snapshot(s);
    });
    for (const q of bilder) expect(q).toEqual(bilder[0]);
  });
});

/** Zahlen aus P5a (aufgenommen vor jeder Änderung für P5b): Umlauf ohne Anziehung muss Bit für Bit gleich bleiben. */
const UMLAUF_P5A = JSON.parse(String.raw`[{"dt":0.0008770580193070292,"tempo":0.2192645048267573,"periode":0.8770580193070292,"text":"Umlaufbahnen um eine Zentralmasse von 1,3 Sonnenmassen, 3 Körper, ohne gegenseitige Anziehung. A: große Halbachse 1 AE, Exzentrizität 0,3, Umlaufzeit etwa 0,88 Jahre, kleinster Abstand 0,70 AE. B: große Halbachse 2,7 AE, Exzentrizität 0,8, Umlaufzeit etwa 3,9 Jahre, kleinster Abstand 0,54 AE. C: große Halbachse 9 AE, Exzentrizität 0,05, Umlaufzeit etwa 23,7 Jahre, kleinster Abstand 8,5 AE.","ausschnitt":{"minX":-10.530000000000001,"maxX":9.629999999999999,"minY":-10.06874295994718,"maxY":10.06874295994718}},{"zeit":0,"xy":[0.5668343516606851,0.4756304954170933,-0.45766926555258836,-1.257435972684122,8.549999999999999,0],"kw":[["umlaufzeit.0",0.8770580193070292,"0,88 Jahre"],["abstand.0",0.7399496945017945,"0,74 AE"],["umlaufzeit.1",3.891114137463618,"3,9 Jahre"],["abstand.1",1.3381354124420708,"1,3 AE"],["umlaufzeit.2",23.680566521289787,"23,7 Jahre"],["abstand.2",8.549999999999999,"8,5 AE"]]},{"zeit":0.0008770580193070292,"xy":[0.5625730865373879,0.4826288222299214,-0.4516767982702862,-1.2545068600193057,8.549999729979021,0.0022018688928422537],"kw":[["umlaufzeit.0",0.8770580193070292,"0,88 Jahre"],["abstand.0",0.7412280740387835,"0,74 AE"],["umlaufzeit.1",3.891114137463618,"3,9 Jahre"],["abstand.1",1.3333414386162288,"1,3 AE"],["umlaufzeit.2",23.680566521289787,"23,7 Jahre"],["abstand.2",8.550000013501048,"8,6 AE"]]},{"zeit":0.12103400666437003,"xy":[-0.26853967297885545,0.953467002847811,0.38908047921655264,-0.5340299015708385,8.544858313157665,0.3037969986732734],"kw":[["umlaufzeit.0",0.8770580193070292,"0,88 Jahre"],["abstand.0",0.9905619018936567,"0,99 AE"],["umlaufzeit.1",3.891114137463618,"3,9 Jahre"],["abstand.1",0.6607356166267576,"0,66 AE"],["umlaufzeit.2",23.680566521289787,"23,7 Jahre"],["abstand.2",8.550257084342116,"8,6 AE"]]},{"zeit":0.9980920259713992,"xy":[-0.26853967297885456,0.9534670028478109,-3.4117279085020944,1.4353897754643892,8.203037234866512,2.4717674335348914],"kw":[["umlaufzeit.0",0.8770580193070292,"0,88 Jahre"],["abstand.0",0.9905619018936563,"0,99 AE"],["umlaufzeit.1",3.891114137463618,"3,9 Jahre"],["abstand.1",3.7013823268016752,"3,7 AE"],["umlaufzeit.2",23.680566521289787,"23,7 Jahre"],["abstand.2",8.567348138256675,"8,6 AE"]]},{"zeit":11.825373274316675,"xy":[-1.2791371614086284,-0.19384086624155042,0.5237064424501309,-0.17770510141973395,-9.449936120199537,0.03386676463572718],"kw":[["umlaufzeit.0",0.8770580193070292,"0,88 Jahre"],["abstand.0",1.2937411484225885,"1,3 AE"],["umlaufzeit.1",3.891114137463618,"3,9 Jahre"],["abstand.1",0.5530348460398952,"0,55 AE"],["umlaufzeit.2",23.680566521289787,"23,7 Jahre"],["abstand.2",9.449996806009976,"9,4 AE"]]},{"zeit":46.90769404659784,"xy":[-1.279137161408632,-0.19384086624153382,0.3659822976104699,0.5721790240624613,8.477943001612779,-1.1351670253991304],"kw":[["umlaufzeit.0",0.8770580193070292,"0,88 Jahre"],["abstand.0",1.2937411484225896,"1,3 AE"],["umlaufzeit.1",3.891114137463618,"3,9 Jahre"],["abstand.1",0.6792141619116238,"0,68 AE"],["umlaufzeit.2",23.680566521289787,"23,7 Jahre"],["abstand.2",8.553602849919361,"8,6 AE"]]},[[181,[0.7,0],[0.6702957262759965,0.23077877989362072],[0.6993908270190958,-0.03329199801423696]],[181,[0.5399999999999999,0],[0.4597984609451904,0.39191347087146167],[0.5383552329515585,-0.05653718465805132]],[181,[8.549999999999999,0],[8.282661536483968,2.1745737359285897],[8.544517443171861,-0.3137026052903041]]]]`);

describe("Umlauf mit gegenseitiger Anziehung", () => {
  const ABC = [koerper(1, 0.3, 40, "A"), koerper(2.7, 0.8, 250, "B"), koerper(9, 0.05, 0, "C")];

  it("without attraction stays bit-identical to P5a (recorded before the change), also with anziehung false and masses given", () => {
    for (const p of [{ zentralmasse: 1.3, koerper: ABC }, { zentralmasse: 1.3, anziehung: false, koerper: ABC.map((k, i) => ({ ...k, masse: 0.003 * i })) }]) {
      const input = umlauf(p), s = createSim(input);
      expect(s.anziehung).toBe(false);
      const reihe = (snap: SimSnapshot) => ({ zeit: snap.zeit, xy: snap.koerper.flatMap((b) => [b.x, b.y]), kw: snap.kennwerte.map((q) => [q.id, q.wert, q.text]) });
      const neu: unknown[] = [{ dt: s.dt, tempo: s.tempo, periode: s.periode, text: s.text, ausschnitt: s.ausschnitt }, reihe(snapshot(s))];
      for (const n of [1, 137, 1000, 12345, 40000]) { schritte(s, n); neu.push(reihe(snapshot(s))); }
      const b = standbild(createSim(input));
      if (b.modell !== "umlauf") throw new Error(b.modell);
      expect(b.offen).toBeUndefined();
      neu.push(b.bahnen.map((q) => [q.punkte.length, q.punkte[0], q.punkte[7], q.punkte[q.punkte.length - 2]]));
      expect(neu).toEqual(UMLAUF_P5A);
    }
  });

  it("two bodies with tiny masses: total energy within 0.5 % over 10 inner orbits and positions equal to Kepler within 0.5 %", () => {
    for (const e of [0, 0.2, 0.6]) {
      const liste = [mk(1, e, 0, "A", 1e-9), mk(1.6, 0.1, 120, "B", 1e-9)];
      const s = createSim(nk(liste));
      expect(s.anziehung).toBe(true);
      expect(s.kern.art).toBe("nkoerper");
      let maxAbw = 0;
      while (s.zeit < 10) {
        schritte(s, 50);
        maxAbw = Math.max(maxAbw, Math.abs(wert(s, "energieAbweichung")));
      }
      expect(maxAbw, `e = ${e}`).toBeLessThan(0.5);
      const snap = snapshot(s);
      liste.forEach((q, i) => {
        const [x, y] = keplerLage(1, q.abstand, q.exzentrizitaet, q.phase, s.zeit);
        expect(Math.hypot(snap.koerper[i].x - x, snap.koerper[i].y - y) / q.abstand, `e = ${e}, ${q.name}`).toBeLessThan(0.005);
      });
    }
  });

  it("starts exactly on the Kepler positions, keeps the angular momentum about the centre, and its energy stays plausible", () => {
    const liste = [mk(1, 0.1, 0, "A", 0.01), mk(1.5, 0.2, 90, "B", 0.005), mk(2.2, 0.05, 200, "C", 0.002)];
    const s = createSim(nk(liste)), k = s.kern as NKoerperKern, ohne = createSim(umlauf({ koerper: liste }));
    snapshot(s).koerper.forEach((p, i) => { expect(p.x).toBeCloseTo(snapshot(ohne).koerper[i].x, 12); expect(p.y).toBeCloseTo(snapshot(ohne).koerper[i].y, 12); });
    const drall = () => { let L = 0; for (let i = 0; i < k.n; i++) L += k.m[i] * (k.x[i] * k.vy[i] - k.y[i] * k.vx[i]); return L; };
    const L0 = drall();
    let maxE = 0;
    for (let i = 0; i < 200; i++) {
      schritte(s, 1000);
      expect(relativ(drall(), L0)).toBeLessThan(1e-11);
      maxE = Math.max(maxE, Math.abs(wert(s, "energieAbweichung")));
    }
    expect(maxE).toBeLessThan(0.5);
    // Die Anziehung wirkt wirklich: die Bahn weicht von Kepler ab (mehr als ohne Anziehung im selben Lauf).
    const [x, y] = keplerLage(1, 1, 0.1, 0, s.zeit);
    expect(Math.hypot(snapshot(s).koerper[0].x - x, snapshot(s).koerper[0].y - y)).toBeGreaterThan(1e-3);
  });

  it("says that the bodies attract each other, names the energy, exports the flag and respects both budgets", () => {
    const liste = Array.from({ length: 8 }, (_, i) => mk(1 + i * 0.7, 0.3, 45 * i, `K${i}`, 0.01));
    const s = createSim(nk(liste));
    expect(s.anziehung).toBe(true);
    expect(s.text).toContain("Die Körper ziehen sich gegenseitig an.");
    expect(s.text).not.toContain("ohne gegenseitige Anziehung");
    expect(createSim(nk([mk(1, 0, 0, "A", 0)])).text).toContain("ohne eigene Masse");
    const snap = snapshot(s);
    expect(snap.modell).toBe("umlauf");
    expect(snap.kennwerte.map((q) => q.id)).toEqual([...liste.flatMap((_, i) => [`umlaufzeit.${i}`, `abstand.${i}`]), "energieAbweichung"]);
    expect(snap.kennwerte[snap.kennwerte.length - 1]).toMatchObject({ name: "Energieabweichung", wert: 0, einheit: "%", text: "0,00 %" });
    expect(snap.ausserhalb).toBe(0);
    // Schritt: innerster Umlauf / 2000 (mit Exzentrizität), höchstens 0,05·√(ε³/(G·2·m_max)) und 0,05·√(ε³/(G·(M + m_max)))
    // mit ε = 0,01 der kleinsten Halbachse.
    const G = TAU * TAU, eps = 0.01;
    expect(s.dt).toBeCloseTo(Math.min((s.periode * 0.7 ** 1.5) / 2000, 0.05 * Math.sqrt(eps ** 3 / (G * 2 * 0.01)), 0.05 * Math.sqrt(eps ** 3 / (G * 1.01))), 15);
    expect(createSim(nk([mk(1, 0, 0, "A", 0), mk(2, 0, 0, "B", 0)])).dt).toBeCloseTo(1 / 2000, 15);   // ohne Massen: wie bisher
    // Glättung zur Zentralmasse: 0,01 bei schweren Körpern (Stoßverhältnis √(200·m/M) ≥ 0,1), sonst 0,001 der kleinsten Halbachse.
    expect((s.kern as NKoerperKern).eps2z).toBeCloseTo(0.01 ** 2, 15);
    const leicht = createSim(nk([mk(1, 0, 0, "A", 1e-6), mk(2, 0, 0, "B", 1e-6)]));
    expect((leicht.kern as NKoerperKern).eps2z).toBeCloseTo(0.001 ** 2, 18);
    expect(leicht.dt).toBeCloseTo(1 / 2000, 15);                          // keine Grenze aus der Zentralmasse
    for (let i = 0; i < 30; i++) expect(advance(s, s.tempo / 30, 4000).koerperSchritte).toBeLessThanOrEqual(4000);
    expect(advance(s, 1e6, 4000).begrenzt).toBe(true);
    const b = standbild(s);
    if (b.modell !== "umlauf") throw new Error(b.modell);
    expect(b.offen).toBe(true);
    expect(b.dauer).toBeGreaterThan(0);
    expect(b.bahnen).toHaveLength(8);
    for (const q of b.bahnen) expect(q.punkte.length).toBeLessThanOrEqual(361);
    expect(s.vorausSchritte).toBeLessThanOrEqual(VORAUS_BUDGET);
    expect(bildEndlich(b)).toBe(true);
  });

  it("all massless: each body follows its own orbit and the energy figure is the sum of the orbit energies", () => {
    const s = createSim(nk([mk(1, 0.3, 0, "A", 0), mk(2, 0, 0, "B", 0)]));
    for (let i = 0; i < 40; i++) schritte(s, 100);
    expect(Math.abs(wert(s, "energieAbweichung"))).toBeLessThan(0.05);
    const [x, y] = keplerLage(1, 2, 0, 0, s.zeit);
    expect(Math.hypot(snapshot(s).koerper[1].x - x, snapshot(s).koerper[1].y - y)).toBeLessThan(0.01);
  });

  it("is deterministic for every chunk size", () => {
    const input = nk([mk(1, 0.2, 0, "A", 0.01), mk(1.8, 0.4, 100, "B", 0.01)]);
    const bilder = [1 / 24, 1 / 30, 1 / 60, 1 / 144].map((c) => {
      const s = createSim(input), T = Math.round((2 * s.tempo) / s.dt) * s.dt;
      while (s.soll + c * s.tempo <= T) advance(s, c * s.tempo);
      if (T - s.soll > 0) advance(s, T - s.soll);
      return snapshot(s);
    });
    for (const q of bilder) expect(q).toEqual(bilder[0]);
  });
});

describe("P5b: Grenzen, feindliche Eingaben und Last", () => {
  const ecken = <T extends Record<string, [number, number]>>(g: T): Record<keyof T, number>[] => {
    const keys = Object.keys(g);
    return Array.from({ length: 2 ** keys.length }, (_, m) => Object.fromEntries(keys.map((k, i) => [k, g[k][(m >> i) & 1]])) as Record<keyof T, number>);
  };
  function pruefe(input: object): SimState {
    const s = createSim(input);
    expect(s.phase, JSON.stringify(input)).toBe("laeuft");
    for (let i = 0; i < 20; i++) expect(advance(s, s.tempo / 30, 4000).koerperSchritte).toBeLessThanOrEqual(4000);
    expect(s.phase, JSON.stringify(input)).toBe("laeuft");
    expect(isFiniteSnapshot(snapshot(s)), JSON.stringify(input)).toBe(true);
    expect([s.dt, s.tempo, s.periode, ...Object.values(s.ausschnitt)].every(Number.isFinite)).toBe(true);
    expect(s.dt).toBeGreaterThan(0);
    expect(s.ausschnitt.maxX > s.ausschnitt.minX && s.ausschnitt.maxY > s.ausschnitt.minY).toBe(true);
    expect(s.text).not.toMatch(/NaN|Infinity|–/);
    const b = standbild(s);
    expect(bildEndlich(b), JSON.stringify(input)).toBe(true);
    expect(s.vorausSchritte).toBeLessThanOrEqual(VORAUS_BUDGET);
    return s;
  }

  it("keeps the corners of every new limit finite and within both budgets", () => {
    for (const p of ecken({ laenge1: [0.05, 100], laenge2: [0.05, 100], masse1: [0.01, 1000], masse2: [0.01, 1000], winkel1: [-180, 180] })) {
      const i = (p.laenge1 > 1 ? 1 : 0) + (p.masse2 > 1 ? 2 : 0);
      pruefe(dp({ ...p, winkel2: [180, -180, 0, 179.9][i], g: [0.1, 100][i % 2], daempfung: [0, 5][(i >> 1) % 2] }));
    }
    for (const p of ecken({ amplitude: [0.001, 100], wellenlaenge: [0.01, 1000], frequenz: [0.01, 100], phase: [0, 360], bereich: [0, 10000] })) {
      const wellen = [w1(p), w1({ ...p, richtung: "links", frequenz: 100.01 - p.frequenz }), w1({ amplitude: 100.001 - p.amplitude, wellenlaenge: 1000.01 - p.wellenlaenge })];
      pruefe(welle(wellen, { bereich: p.bereich }));
      pruefe(welle([w1(p)], { bereich: p.bereich === 0 ? 0.01 : p.bereich }));
    }
    for (const p of ecken({ zentralmasse: [0.01, 100], abstand: [0.01, 1000], exzentrizitaet: [0, 0.95], phase: [0, 360], masse: [0, 0.01] })) {
      const many = Array.from({ length: 8 }, (_, i) => mk(p.abstand * (i % 2 ? 1 : 0.01 / p.abstand + 1), p.exzentrizitaet, (p.phase + 45 * i) % 360, `K${i}`, p.masse));
      pruefe(nk([mk(p.abstand, p.exzentrizitaet, p.phase, "A", p.masse)], { zentralmasse: p.zentralmasse }));
      pruefe(nk(many, { zentralmasse: p.zentralmasse }));
    }
  });

  it("normalizes valid new input without changes and names every clamped or replaced field", () => {
    expect(MODELLE).toEqual(["pendel", "feder", "wurf", "umlauf", "gas"]);
    expect(MODELLE_ALLE).toEqual(["pendel", "feder", "wurf", "umlauf", "gas", "doppelpendel", "welle"]);
    for (const input of [dp(), welle([w1(), w1({ richtung: "links" }), w1({ phase: 360 })], { bereich: 5 }), nk([mk(1, 0, 0, "A", 0.01), mk(2, 0.5, 30, "B", 0)])]) {
      expect(normalizeSim(input).angepasst, input.modell).toEqual([]);
      expect(normalizeSim(input)).toMatchObject(input);
    }
    const a = normalizeSim(dp({ laenge1: 500, masse2: 0, winkel1: 200, g: "9,81", daempfung: -1 }));
    expect(a.angepasst).toEqual(["parameter.laenge1", "parameter.masse2", "parameter.winkel1", "parameter.g", "parameter.daempfung"]);
    expect(a.parameter).toMatchObject({ laenge1: 100, masse2: 0.01, winkel1: 180, g: 9.81, daempfung: 0 });
    const w = normalizeSim(welle([w1({ richtung: "oben", amplitude: 1000 }), 5 as unknown as object, w1(), w1(), w1()], { bereich: 0.001 }));
    expect(w.angepasst).toEqual(expect.arrayContaining(["parameter.wellen", "parameter.wellen.0.richtung", "parameter.wellen.0.amplitude", "parameter.wellen.1", "parameter.bereich"]));
    expect(w.parameter).toMatchObject({ bereich: 0.01, wellen: [{ richtung: "rechts", amplitude: 100 }, {}] });
    expect((w.parameter as { wellen: unknown[] }).wellen).toHaveLength(2);    // drei behalten, die kaputte zweite fällt weg
    const leer = normalizeSim({ ...basis, modell: "welle", parameter: { wellen: "viele", bereich: -5 } });
    expect(leer.angepasst).toEqual(["parameter.wellen", "parameter.bereich"]);
    expect(leer.parameter).toEqual({ wellen: [{ amplitude: 1, wellenlaenge: 2, frequenz: 0.5, phase: 0, richtung: "rechts" }], bereich: 0 });
    const u = normalizeSim(umlauf({ anziehung: "ja", koerper: [mk(1, 0, 0, "A", 1), mk(2, 0, 0, "B", -1), { ...koerper(3, 0, 0, "C"), masse: NaN }] }));
    expect(u.angepasst).toEqual(["parameter.koerper.0.masse", "parameter.koerper.1.masse", "parameter.koerper.2.masse", "parameter.anziehung"]);
    expect(u.parameter).toMatchObject({ anziehung: false, koerper: [{ masse: 0.01 }, { masse: 0 }, { masse: 0 }] });
    expect(createSim(umlauf({ anziehung: "ja" })).anziehung).toBe(false);
    expect("anziehung" in normalizeSim(umlauf()).parameter).toBe(false);   // ältere Eingabe: Feld bleibt weg, keine Meldung
  });

  it("never throws on hostile new input", () => {
    const boese: unknown[] = [
      { modell: "doppelpendel" }, { modell: "doppelpendel", parameter: { laenge1: NaN, winkel1: Infinity, masse1: "x" } },
      { modell: "welle", parameter: null }, { modell: "welle", parameter: { wellen: [null, [], { amplitude: -1, frequenz: 0, wellenlaenge: 1e9 }] } },
      { modell: "umlauf", parameter: { anziehung: true, koerper: Array.from({ length: 20 }, () => ({ abstand: 1, masse: 1e9, exzentrizitaet: 0, phase: 0, name: "x", farbe: "ok" })) } },
      { modell: "umlauf", parameter: { anziehung: true, koerper: [{ abstand: 1, masse: 0.01, name: "a", farbe: "ok", phase: 0, exzentrizitaet: 0 }, { abstand: 1, masse: 0.01, name: "b", farbe: "ok", phase: 0, exzentrizitaet: 0 }], zentralmasse: 0.01 } },
    ];
    for (const input of boese) {
      let s: SimState | undefined;
      expect(() => { s = createSim(input); }).not.toThrow();
      for (let i = 0; i < 30; i++) expect(() => advance(s!, s!.tempo / 30, 4000)).not.toThrow();
      expect(() => standbild(s!)).not.toThrow();
      expect(s!.phase === "instabil" || isFiniteSnapshot(snapshot(s!)), `Eingabe ${boese.indexOf(input)}`).toBe(true);
    }
  });

  it("never calls Math.random", () => {
    const spy = vi.spyOn(Math, "random");
    for (const input of [dp(), welle([w1(), w1({ frequenz: 3, richtung: "links" })]), nk([mk(1, 0.2, 0, "A", 0.01), mk(2, 0, 0, "B", 0.01)])]) {
      const s = createSim(input);
      advance(s, s.tempo, 4000);
      standbild(s);
      mitWert(input, GRENZEN[input.modell as keyof typeof GRENZEN][0].feld, 1);
    }
    expect(spy).not.toHaveBeenCalled();
  });

  it("computes a frame of the heaviest new cases fast (4000 body-steps)", () => {
    for (const [name, input] of [["doppelpendel", dp({ winkel1: 180, winkel2: 0, masse1: 1000, masse2: 0.01 })],
      ["umlauf mit Anziehung, 8 Körper", nk(Array.from({ length: 8 }, (_, i) => mk(1 + i, 0.95, 40 * i, `K${i}`, 0.01)))],
      ["welle, 3 Wellen", welle([w1(), w1({ frequenz: 3 }), w1({ frequenz: 7, richtung: "links" })])]] as const) {
      const s = createSim(input);
      advance(s, 1, 4000);
      const t = performance.now();
      let n = 0;
      for (let i = 0; i < 30; i++) { n += advance(s, s.tempo, 4000).koerperSchritte; snapshot(s); }
      const ms = (performance.now() - t) / 30;
      console.info(`[physics] heaviest frame ${name}: ${ms.toFixed(2)} ms for ${n / 30} body-steps incl. snapshot`);
      expect(n / 30).toBeLessThanOrEqual(4000);
      expect(ms).toBeLessThan(50);
    }
  });
});

describe("Regler: GRENZEN und mitWert", () => {
  it("lists the slider fields with the limits of the schema", () => {
    const kurz = Object.fromEntries(Object.entries(GRENZEN).map(([m, l]) => [m, l.map((g) => [g.feld, g.einheit, g.min, g.max])]));
    expect(kurz).toEqual({
      pendel: [["laenge", "m", 0.05, 100], ["winkel", "Grad", -170, 170]],
      feder: [["masse", "kg", 0.001, 1000], ["federkonstante", "N/m", 0.001, 1e6]],
      wurf: [["geschwindigkeit", "m/s", 0.1, 1000], ["winkel", "Grad", -90, 90]],
      umlauf: [["zentralmasse", "Sonnenmassen", 0.01, 100]],
      gas: [["geschwindigkeit", "Kastenbreiten/s", 0.01, 10], ["schwerkraft", "Einheiten/s²", 0, 100]],
      doppelpendel: [["winkel1", "Grad", -180, 180], ["laenge2", "m", 0.05, 100]],
      welle: [["wellen.0.frequenz", "Hz", 0.01, 100]],
    });
    for (const l of Object.values(GRENZEN)) for (const g of l) {
      expect(g.name.length).toBeGreaterThan(0);
      expect(g.schritt).toBeGreaterThan(0);
      expect(g.skala).toBe(g.max >= 1000 * g.min && g.min > 0 ? "log" : "linear");
    }
    expect(Object.isFrozen(GRENZEN) && Object.isFrozen(GRENZEN.pendel) && Object.isFrozen(GRENZEN.pendel[0])).toBe(true);
  });

  it("sets and clamps one field, never mutates the input, and the result needs no further adjustment", () => {
    const basisJe: Record<string, object> = { pendel: pendel(), feder: feder(), wurf: wurf(), umlauf: umlauf(), gas: gas(), doppelpendel: dp(), welle: welle([w1(), w1({ richtung: "links" })]) };
    for (const [m, l] of Object.entries(GRENZEN)) for (const g of l) {
      for (const ziel of [g.min - 1e6, g.min, (g.min + g.max) / 2, g.max, g.max * 10 + 1]) {
        const vorher = JSON.stringify(basisJe[m]);
        const out = mitWert(basisJe[m], g.feld, ziel) as { parameter: Record<string, unknown> };
        expect(JSON.stringify(basisJe[m]), `${m}.${g.feld}`).toBe(vorher);
        expect(out).not.toBe(basisJe[m]);
        const gesetzt = g.feld.split(".").reduce<unknown>((o, k) => (o as Record<string, unknown>)[k], out.parameter) as number;
        expect(gesetzt, `${m}.${g.feld} = ${ziel}`).toBeGreaterThanOrEqual(g.min);
        expect(gesetzt).toBeLessThanOrEqual(g.max);
        const abgeleitet = m === "feder" || (m === "wurf" && g.feld === "winkel" && ziel <= 0);   // eigene Tests unten
        if (ziel >= g.min && ziel <= g.max && !abgeleitet) expect(gesetzt).toBe(ziel);
        expect(normalizeSim(out).angepasst, `${m}.${g.feld} = ${ziel}`).toEqual([]);
      }
    }
    const w = welle([w1(), w1({ richtung: "links" })]), out = mitWert(w, "wellen.0.frequenz", 1000);
    const vorher = w.parameter.wellen as { frequenz: number }[], nachher = out.parameter.wellen as { frequenz: number }[];
    expect(nachher[0]).toEqual({ ...w1(), frequenz: 100 });
    expect(nachher[1]).toBe(vorher[1]);                                    // nicht berührte Teile dürfen geteilt werden
    expect(nachher).not.toBe(vorher);
    expect(vorher[0].frequenz).toBe(1);
  });

  it("follows the derived rules of the schema (spring period, throw from height 0) and ignores unknown fields", () => {
    const f = mitWert(feder({ federkonstante: 0.001 }), "masse", 1000) as { parameter: { masse: number; federkonstante: number } };
    expect(TAU * Math.sqrt(f.parameter.masse / f.parameter.federkonstante)).toBeLessThanOrEqual(1000);
    expect(f.parameter.masse).toBeCloseTo(0.001 * (1000 / TAU) ** 2, 6);
    const k = mitWert(feder({ masse: 0.001 }), "federkonstante", 1e6) as { parameter: { masse: number; federkonstante: number } };
    expect(TAU * Math.sqrt(k.parameter.masse / k.parameter.federkonstante)).toBeGreaterThanOrEqual(0.05);
    expect(normalizeSim(f).angepasst).toEqual([]);
    expect(normalizeSim(k).angepasst).toEqual([]);
    expect((mitWert(wurf({ hoehe: 0 }), "winkel", -30) as { parameter: { winkel: number } }).parameter.winkel).toBe(1);
    expect((mitWert(wurf({ hoehe: 10 }), "winkel", -30) as { parameter: { winkel: number } }).parameter.winkel).toBe(-30);
    const p = pendel();
    for (const [feld, wert_] of [["daempfung", 3], ["laenge", NaN], ["laenge", Infinity], ["__proto__", 1], ["parameter.laenge", 2]] as const) {
      const out = mitWert(p, feld, wert_);
      expect(out).toEqual(p);
      expect(out).not.toBe(p);
    }
    expect(mitWert(null, "laenge", 1)).toBeNull();
    expect(mitWert({ modell: "quatsch", parameter: {} }, "laenge", 1)).toEqual({ modell: "quatsch", parameter: {} });
    expect(mitWert(welle([]), "wellen.0.frequenz", 5)).toEqual(welle([]));   // keine erste Welle: nichts gesetzt
  });

  it("ignores hostile paths and model names and never pollutes a prototype", () => {
    const w = welle([w1(), w1({ richtung: "links" })]);
    for (const feld of ["wellen.5.frequenz", "wellen.-1.frequenz", "wellen.0x0.frequenz", "constructor.prototype.x", "__proto__.polluted", "wellen.0.__proto__.polluted"]) {
      expect(mitWert(w, feld, 5), feld).toEqual(w);
    }
    for (const modell of ["__proto__", "toString", "constructor", "hasOwnProperty"]) {
      const roh = { ...basis, modell, parameter: { laenge: 1 } };
      expect(mitWert(roh, "laenge", 5), modell).toEqual(roh);
      expect(mitWert(roh, "polluted", 5)).toEqual(roh);
    }
    const proto = JSON.parse('{"modell":"__proto__","parameter":{"__proto__":{"polluted":1}}}');
    expect(mitWert(proto, "polluted", 5)).toEqual(proto);
    expect(({} as Record<string, unknown>).polluted).toBeUndefined();
    expect(({} as Record<string, unknown>).x).toBeUndefined();
  });
});

describe("P5b Nachbesserung: steife Doppelpendel, nahe Vorbeiflüge, Wellen-Alias", () => {
  /** Unabhängige Rechnung: Lagrange-Gleichungen mit der Massenmatrix (2 x 2 gelöst), fester RK4-Schritt. */
  function rk4Massenmatrix(p: { laenge1: number; laenge2: number; masse1: number; masse2: number; winkel1: number; winkel2: number; g: number }, h: number, n: number) {
    const { laenge1: L1, laenge2: L2, masse1: m1, masse2: m2, g } = p, M = m1 + m2;
    const f = (y: number[]): number[] => {
      const [t1, w1, t2, w2] = y, d = t1 - t2, c = Math.cos(d), s = Math.sin(d);
      // [M·L1, m2·L2·c; L1·c, L2] · [α1; α2] = [−m2·L2·w2²·s − M·g·sin t1; L1·w1²·s − g·sin t2]
      const a11 = M * L1, a12 = m2 * L2 * c, a21 = L1 * c, a22 = L2;
      const r1 = -m2 * L2 * w2 * w2 * s - M * g * Math.sin(t1), r2 = L1 * w1 * w1 * s - g * Math.sin(t2);
      const det = a11 * a22 - a12 * a21;
      return [w1, (r1 * a22 - a12 * r2) / det, w2, (a11 * r2 - a21 * r1) / det];
    };
    let y = [(p.winkel1 * Math.PI) / 180, 0, (p.winkel2 * Math.PI) / 180, 0];
    for (let i = 0; i < n; i++) {
      const k1 = f(y), k2 = f(y.map((v, j) => v + 0.5 * h * k1[j])), k3 = f(y.map((v, j) => v + 0.5 * h * k2[j])), k4 = f(y.map((v, j) => v + h * k3[j]));
      y = y.map((v, j) => v + (h / 6) * (k1[j] + 2 * k2[j] + 2 * k3[j] + k4[j]));
    }
    return y;
  }
  const winkelAbstand = (a: number, b: number) => Math.abs(Math.atan2(Math.sin(a - b), Math.cos(a - b)));

  it("double pendulum without damping keeps its energy within 1 % over 10 s also at extreme mass and length ratios", () => {
    for (const p of [{ masse1: 0.01, masse2: 1000, winkel1: 179, winkel2: -179 }, { masse1: 0.01, masse2: 1000, winkel1: 90, winkel2: 0 },
      { masse1: 0.1, masse2: 1000, winkel1: 179, winkel2: -179 }, { masse1: 1000, masse2: 0.01, winkel1: 179, winkel2: -179 },
      { laenge1: 0.05, laenge2: 100, winkel1: 179, winkel2: -179 }, { laenge1: 100, laenge2: 0.05, winkel1: 179, winkel2: -179 }]) {
      const s = createSim(dp(p)), e0 = dpEnergieTest(s), t0 = performance.now();
      let maxAbw = 0, teil = 0, raster = 0;
      while (s.zeit < 10) {
        const r = schritte(s, Math.max(1, Math.round(0.05 / s.dt)));
        teil += r.koerperSchritte / 2; raster += r.schritte;
        maxAbw = Math.max(maxAbw, relativ(dpEnergieTest(s), e0));
      }
      console.info(`[physics] doppelpendel ${JSON.stringify(p)}: dt ${s.dt.toExponential(2)} s, ${(teil / raster).toFixed(2)} Teilschritte je Rasterschritt, `
        + `energy drift over 10 s ${(100 * maxAbw).toExponential(1)} %, ${(performance.now() - t0).toFixed(0)} ms`);
      expect(s.phase).toBe("laeuft");
      expect(maxAbw, JSON.stringify(p)).toBeLessThan(0.01);
      expect(Math.abs(wert(s, "energie") - 100)).toBeLessThan(1);
    }
  }, 60_000);

  it("double pendulum follows an independent RK4 with the mass matrix (step dt/20) over 3 s within 1e-6 rad", () => {
    // Nur nicht steife Fälle: beim Peitschen (oberer Körper 0,01 kg, unterer 1000 kg) vergrößert das Chaos jeden Rundungsunterschied
    // beider Rechnungen in 3 s auf ganze Radiant; dort prüft der Energietest oben, dass die Rechnung stimmt.
    for (const p of [{ winkel1: 90, winkel2: 0 }, { winkel1: 120, winkel2: -30, laenge2: 0.7, masse2: 2 }, { winkel1: 150, winkel2: 30, masse1: 1000, masse2: 0.01 }]) {
      const s = createSim(dp(p)), n = Math.round(3 / s.dt);
      schritte(s, n);
      const k = s.kern as DoppelpendelKern, soll = rk4Massenmatrix({ ...(dp().parameter), ...p }, s.dt / 20, 20 * n);
      const abw = Math.max(winkelAbstand(k.th1, soll[0]), winkelAbstand(k.th2, soll[2]));
      console.info(`[physics] doppelpendel ${JSON.stringify(p)} gegen RK4 (dt/20) über 3 s: |Δθ| = ${abw.toExponential(1)} rad`);
      expect(abw, JSON.stringify(p)).toBeLessThan(1e-6);
    }
  }, 60_000);

  it("orbits with attraction: close encounters no longer eject bodies by a numerical error; energy within 1 % over 60 years", () => {
    const zwei = nk([mk(1, 0, 0, "A", 0.01), mk(1.1, 0, 5, "B", 0.01)], { zentralmasse: 0.01 });
    const acht = (versatz: number) => nk(Array.from({ length: 8 }, (_, i) => mk(1 + 0.3 * i, 0.1, (45 * i + versatz) % 360, `K${i}`, 0.01)), { zentralmasse: 0.01 });
    for (const [name, input] of [["zwei", zwei], ["acht", acht(0)], ["acht, um 20 Grad gedreht", acht(20)]] as const) {
      const s = createSim(input), k = s.kern as NKoerperKern, t0 = performance.now();
      const kepler = Math.max(...(input.parameter.koerper as { abstand: number; exzentrizitaet: number }[]).map((q) => q.abstand * (1 + q.exzentrizitaet)));
      let maxAbw = 0;
      while (s.zeit < 60) {
        schritte(s, 2000);
        maxAbw = Math.max(maxAbw, Math.abs(wert(s, "energieAbweichung")));
      }
      // Zwei Körper: keiner fliegt hinaus (vorher bis 800 AE, rein zahlengemacht). Acht Körper so schwer wie die Zentralmasse
      // streuen einander wirklich: ein Körper darf dann weiter als das Dreifache der Kepler-Größe hinaus (auf eine weite Bahn oder
      // ungebunden). Das ist Physik und keine Zahlenpanne, weil die Gesamtenergie dabei auf 1 % erhalten bleibt (Prüfung unten).
      let draussen = 0, gebunden = 0;
      const Mges = k.GM / (TAU * TAU) + k.m.reduce((a, b) => a + b, 0);
      for (let i = 0; i < k.n; i++) {
        const r = Math.hypot(k.x[i], k.y[i]);
        if (r > 3 * kepler) { draussen++; if (0.5 * (k.vx[i] ** 2 + k.vy[i] ** 2) < (TAU * TAU * Mges) / r) gebunden++; }
      }
      console.info(`[physics] umlauf mit Anziehung (${name}): dt ${s.dt.toExponential(2)} Jahre, energy deviation over 60 years ${maxAbw.toExponential(1)} %, `
        + `${draussen} Körper weiter als 3 × Kepler (davon ${gebunden} gebunden), ${(performance.now() - t0).toFixed(0)} ms`);
      if (name === "zwei") expect(draussen).toBe(0);
      expect(maxAbw, name).toBeLessThan(1);
      expect(s.dt).toBeLessThanOrEqual(0.05 * Math.sqrt((0.01 ** 3) / (TAU * TAU * 2 * 0.01)) + 1e-15);
      expect(snapshot(s).ausserhalb).toBe(snapshot(s).koerper.filter((p) => p.x < s.ausschnitt.minX || p.x > s.ausschnitt.maxX || p.y < s.ausschnitt.minY || p.y > s.ausschnitt.maxY).length);
    }
  }, 60_000);

  it("counts the bodies outside the extent", () => {
    const s = createSim(nk([mk(1, 0, 0, "A", 0), mk(2, 0, 0, "B", 0), mk(3, 0, 0, "C", 0)]));
    const k = s.kern as NKoerperKern;
    expect(snapshot(s).ausserhalb).toBe(0);
    k.x[0] = s.ausschnitt.maxX + 1;
    expect(snapshot(s).ausserhalb).toBe(1);
    k.y[2] = s.ausschnitt.minY - 0.5;
    expect(snapshot(s).ausserhalb).toBe(2);
    expect(snapshot(createSim(dp())).ausserhalb).toBeUndefined();
    expect(snapshot(createSim(umlauf())).ausserhalb).toBeUndefined();
  });

  it("waves: a range of more than 50 shortest wavelengths is shortened and noted, the drawn curve keeps the true wavelength", () => {
    for (const [wellen, bereich] of [[[w1({ wellenlaenge: 0.01 })], 10000], [[w1({ wellenlaenge: 0.01 }), w1({ wellenlaenge: 1, richtung: "links" })], 0]] as const) {
      const input = welle([...wellen], { bereich }), cfg = normalizeSim(input);
      expect(cfg.angepasst).toContain("parameter.bereich");
      expect((cfg.parameter as { bereich: number }).bereich).toBeCloseTo(0.5, 12);
      const s = createSim(input);
      expect(s.text).toContain("Der gezeigte Bereich wurde auf 0,5 m gekürzt (50 kürzeste Wellenlängen), damit die Welle richtig dargestellt wird.");
      expect(s.ausschnitt.maxX).toBeCloseTo(0.5, 12);
      if (wellen.length > 1) continue;
      const k = snapshot(s).kurve!, auf: number[] = [];
      for (let i = 1; i < k.length; i++) if (k[i - 1][1] < 0 && k[i][1] >= 0) auf.push(k[i - 1][0] + (k[i][0] - k[i - 1][0]) * (-k[i - 1][1] / (k[i][1] - k[i - 1][1])));
      expect(auf.length).toBeGreaterThanOrEqual(48);
      expect(relativ((auf[auf.length - 1] - auf[0]) / (auf.length - 1), 0.01)).toBeLessThan(0.01);   // die wahre Wellenlänge 0,01 m
    }
    expect(normalizeSim(welle([w1({ wellenlaenge: 0.01 })], { bereich: 0.5 })).angepasst).toEqual([]);   // genau 50: bleibt
    expect(createSim(welle([w1({ wellenlaenge: 0.01 })], { bereich: 0.5 })).text).not.toContain("gekürzt");
  });
});
