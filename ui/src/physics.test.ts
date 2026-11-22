import { afterEach, describe, expect, it, vi } from "vitest";
import {
  addToTrail, advance, createSim, createTrail, formatFest, formatWert, formatZahl, isFiniteSnapshot, mulberry32, normalizeSim, snapshot,
  solveKepler, standbild, trailPoints, VORAUS_BUDGET, type SimSnapshot, type SimState, type Standbild,
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
