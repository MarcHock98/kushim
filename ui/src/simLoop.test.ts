import { describe, expect, it } from "vitest";
import { formatFest, isFiniteSnapshot, mulberry32, type SimSnapshot } from "./lib/physics";
import { createSimLoop, MAX_KOERPER_SCHRITTE, PHYSIK, statusWort, TEMPO_FAKTOREN, tempoFaktor, type LoopState, type SimEngine } from "./lib/simLoop";

// Taktschleife (Plan docs/ui-p5-plan.md, Abschnitte 5, 6 und 10) mit falscher Uhr und falschem Bildtakt.

const basis = { laufzeit: 30, tempo: 0, spur: true, beschreibung: "" };
const pendel = (extra: object = {}) =>
  ({ ...basis, modell: "pendel", parameter: { laenge: 1, winkel: 30, anfangsgeschwindigkeit: 0, daempfung: 0, g: 9.81 }, ...extra });
const wurf = (extra: object = {}) =>
  ({ ...basis, modell: "wurf", parameter: { geschwindigkeit: 20, winkel: 45, hoehe: 0, g: 9.81, luftwiderstand: 0 }, ...extra });
const schnellesGas = (extra: object = {}) => ({
  ...basis, modell: "gas", laufzeit: 60,
  parameter: { anzahl: 300, kasten: [1000, 100], radius: 5, geschwindigkeit: 10, schwerkraft: 0, stoesse: true, startwert: 1 }, ...extra,
});

/** Eingriffe für die Tests: werfende Rückrufe, eine andere Uhr, ein anderer Zeitstempel im Bildtakt. */
interface Extra {
  onFrame?: (snap: SimSnapshot) => void;
  onState?: (s: LoopState) => void;
  /** `now()` aus der echten Zeit t. */
  now?: (t: number) => number;
  /** Zeitstempel, den der Bildtakt übergibt (Standard: t). */
  stempel?: (t: number) => number;
  /** Läuft bei jeder Bestellung (n = laufende Nummer), darf werfen. */
  requestFrame?: (n: number) => void;
}

function aufbau(input: unknown, engine?: SimEngine, extra: Extra = {}) {
  let t = 0, id = 0, hidden = false, anfragen = 0;
  const queue = new Map<number, (ts: number) => void>();
  const scheduler = {
    now: () => (extra.now ? extra.now(t) : t),
    requestFrame: (cb: (ts: number) => void) => { extra.requestFrame?.(++anfragen); queue.set(++id, cb); return id; },
    cancelFrame: (i: number) => { queue.delete(i); },
  };
  const frames: { t: number; snap: SimSnapshot }[] = [], states: LoopState[] = [];
  const loop = createSimLoop({
    input, scheduler, engine, isHidden: () => hidden,
    onFrame: (snap) => { frames.push({ t, snap }); extra.onFrame?.(snap); },
    onState: (s) => { states.push(s); extra.onState?.(s); },
  });
  /** Ein angebotenes Bild zur echten Zeit `abs` (ms). */
  const bildBei = (abs: number) => {
    t = abs;
    const cbs = [...queue.values()];
    queue.clear();
    for (const cb of cbs) cb(extra.stempel ? extra.stempel(t) : t);
  };
  /** Ein angebotenes Bild nach `ms` Millisekunden. */
  const bild = (ms: number) => bildBei(t + ms);
  /** `sekunden` lang Bilder mit `hz` anbieten; `jedes` läuft nach jedem angebotenen Bild. */
  const lauf = (sekunden: number, hz = 60, jedes?: () => void) => {
    for (let i = 0, n = Math.round(sekunden * hz); i < n; i++) { bild(1000 / hz); jedes?.(); }
  };
  return { loop, frames, states, bild, bildBei, lauf, jetzt: () => t, wartend: () => queue.size, verstecke: (v: boolean) => { hidden = v; } };
}

const worte = (states: LoopState[]) => states.map((s) => s.wort);
/** Größte Zahl von Bildern in einem Fenster von 1000 ms. */
function maxImFenster(ts: number[]): number {
  let m = 0;
  for (let i = 0, j = 0; i < ts.length; i++) {
    while (ts[i] - ts[j] > 1000) j++;
    m = Math.max(m, i - j + 1);
  }
  return m;
}
const INSTABIL = "Simulation instabil, angehalten";
const ZEITLUPE = "Zeitlupe, Rechengrenze erreicht";

describe("simLoop", () => {
  it("delivers a start picture at once and says „läuft“", () => {
    const a = aufbau(pendel());
    expect(a.frames).toHaveLength(1);
    expect(a.frames[0].snap.zeit).toBe(0);
    expect(worte(a.states)).toEqual(["läuft"]);
    expect(a.loop.pending()).toBe(1);
    expect(a.wartend()).toBe(1);
  });

  it("never runs more than 30 frames per second, even at 144 Hz, and reaches 30 at 60 Hz", () => {
    for (const hz of [144, 120, 60, 240]) {
      const a = aufbau(pendel({ laufzeit: 60 }));
      a.lauf(10, hz);
      const ts = a.frames.slice(1).map((f) => f.t);
      expect(ts.length, `${hz} Hz`).toBeLessThanOrEqual(300);
      for (let i = 1; i < ts.length; i++) expect(ts[i] - ts[i - 1]).toBeGreaterThanOrEqual(1000 / 30 - 0.5);
      // 30 Bildabstände dauern mindestens fast eine Sekunde (0,5 ms Spiel je Abstand gegen Zittern der Bildzeiten).
      for (let i = 0; i + 30 < ts.length; i++) expect(ts[i + 30] - ts[i]).toBeGreaterThanOrEqual(1000 - 30 * 0.5);
      if (hz === 60 || hz === 120 || hz === 240) expect(ts.length).toBeGreaterThanOrEqual(298);
    }
  });

  it("keeps the body-steps per frame at 4000 and then says „Zeitlupe, Rechengrenze erreicht“", () => {
    const a = aufbau(schnellesGas());
    let max = 0;
    a.lauf(3, 60, () => { max = Math.max(max, a.loop.getState().koerperSchritte); });
    expect(max).toBeGreaterThan(0);
    expect(max).toBeLessThanOrEqual(MAX_KOERPER_SCHRITTE);
    expect(a.loop.getState().status).toBe("zeitlupe");
    expect(worte(a.states)).toEqual(["läuft", "Zeitlupe, Rechengrenze erreicht"]);
    const st = a.loop.getState(), sim = a.loop.getSim();
    expect(st.simZeit).toBeLessThan(0.5 * st.laufzeit * sim.tempo);       // Modellzeit läuft langsamer als verlangt
    for (const p of a.frames[a.frames.length - 1].snap.koerper) expect(p.x >= 5 && p.x <= 995 && p.y >= 5 && p.y <= 95).toBe(true);
    const b = aufbau(pendel());
    b.lauf(3, 60, () => expect(b.loop.getState().koerperSchritte).toBeLessThanOrEqual(MAX_KOERPER_SCHRITTE));
    expect(worte(b.states)).toEqual(["läuft"]);
  });

  it("stops after the run time, keeps the last frame and schedules nothing", () => {
    const a = aufbau(pendel({ laufzeit: 5 }));
    a.lauf(8);
    const st = a.loop.getState();
    expect(st.status).toBe("angehalten");
    expect(st.wort).toBe("angehalten nach 5 s");
    expect(st.laufzeit).toBeCloseTo(5, 9);
    expect(worte(a.states)).toEqual(["läuft", "angehalten nach 5 s"]);
    expect(a.loop.pending()).toBe(0);
    expect(a.wartend()).toBe(0);
    const n = a.frames.length;
    expect(a.frames[n - 1].snap.zeit).toBe(st.simZeit);
    a.lauf(2);
    expect(a.frames).toHaveLength(n);
    a.loop.resume();                                         // Weiter geht nach dem Stopp nicht, nur Neu starten
    expect(a.loop.pending()).toBe(0);
  });

  it("computes nothing while hidden and does not catch up afterwards", () => {
    const a = aufbau(pendel({ laufzeit: 60 }));
    a.lauf(1);
    const n = a.frames.length, before = a.loop.getState();
    a.verstecke(true);
    a.lauf(5);
    expect(a.frames).toHaveLength(n);
    expect(a.loop.getState().simZeit).toBe(before.simZeit);
    expect(a.loop.getState().laufzeit).toBe(before.laufzeit);
    a.verstecke(false);
    a.lauf(0.2);
    const after = a.loop.getState(), tempo = a.loop.getSim().tempo;
    expect(a.frames.length).toBeGreaterThan(n);
    expect(after.laufzeit - before.laufzeit).toBeLessThanOrEqual(0.2 + 1e-9);
    expect(after.simZeit - before.simZeit).toBeLessThanOrEqual(0.2 * tempo + 0.01);
  });

  it("does not start with a frame while hidden, and shows the start picture once visible", () => {
    let hidden = true;
    const frames: SimSnapshot[] = [];
    let t = 0, cb: ((ts: number) => void) | null = null;
    createSimLoop({
      input: pendel(), isHidden: () => hidden, onFrame: (s) => frames.push(s),
      scheduler: { now: () => t, requestFrame: (f) => { cb = f; return 1; }, cancelFrame: () => { cb = null; } },
    });
    expect(frames).toHaveLength(0);
    const tick = () => { t += 16; const f = cb; cb = null; f?.(t); };
    tick(); tick();
    expect(frames).toHaveLength(0);
    hidden = false;
    tick();
    expect(frames).toHaveLength(1);
    expect(frames[0].zeit).toBe(0);
  });

  it("clamps a long gap between two frames: no burst of steps", () => {
    const a = aufbau(pendel({ laufzeit: 60 }));
    a.lauf(1);
    const n = a.frames.length, before = a.loop.getState();
    a.bild(5000);
    const after = a.loop.getState(), tempo = a.loop.getSim().tempo;
    expect(a.frames.length - n).toBeLessThanOrEqual(1);
    expect(after.laufzeit - before.laufzeit).toBeLessThanOrEqual(0.1 + 1e-9);
    expect(after.simZeit - before.simZeit).toBeLessThanOrEqual(0.1 * tempo + a.loop.getSim().dt);   // plus Rest unter einem Rasterschritt
  });

  it("pauses, resumes and restarts; paused means no scheduled frame", () => {
    const a = aufbau(pendel({ laufzeit: 60 }));
    a.lauf(1);
    a.loop.pause();
    expect(a.loop.getState().wort).toBe("pausiert");
    expect(a.loop.pending()).toBe(0);
    expect(a.wartend()).toBe(0);
    const n = a.frames.length, z = a.loop.getState().simZeit;
    a.lauf(3);
    expect(a.frames).toHaveLength(n);
    expect(a.loop.getState().simZeit).toBe(z);
    a.loop.resume();
    expect(a.loop.getState().wort).toBe("läuft");
    expect(a.loop.pending()).toBe(1);
    a.lauf(1);
    expect(a.frames.length).toBeGreaterThan(n);
    expect(a.loop.getState().laufzeit).toBeLessThan(2.05);    // die Pause zählt nicht zur Laufzeit
    a.loop.restart();
    expect(a.frames[a.frames.length - 1].snap.zeit).toBe(0);
    expect(a.loop.getState().laufzeit).toBe(0);
    expect(a.loop.getState().status).toBe("laeuft");
    expect(worte(a.states)).toEqual(["läuft", "pausiert", "läuft"]);
    const stop = aufbau(pendel({ laufzeit: 5 }));
    stop.lauf(6);
    stop.loop.restart();
    expect(stop.loop.getState().wort).toBe("läuft");
    expect(stop.loop.pending()).toBe(1);
  });

  it("after dispose nothing is scheduled and nothing is called back", () => {
    const a = aufbau(pendel());
    a.lauf(0.5);
    a.loop.dispose();
    expect(a.loop.pending()).toBe(0);
    expect(a.wartend()).toBe(0);
    const n = a.frames.length, s = a.states.length;
    a.loop.resume(); a.loop.restart(); a.loop.pause();
    a.lauf(1);
    expect(a.frames).toHaveLength(n);
    expect(a.states).toHaveLength(s);
    expect(a.wartend()).toBe(0);
  });

  it("stops with „instabil“ at the first non-finite snapshot and never delivers it", () => {
    let calls = 0;
    const kaputt: SimEngine = {
      ...PHYSIK,
      snapshot: (st) => {
        const snap = PHYSIK.snapshot(st);
        return ++calls > 10 ? { ...snap, koerper: [{ ...snap.koerper[0], x: NaN }] } : snap;
      },
    };
    const a = aufbau(pendel(), kaputt);
    a.lauf(3);
    expect(a.loop.getState().status).toBe("instabil");
    expect(a.loop.getState().wort).toBe("Simulation instabil, angehalten");
    expect(a.frames).toHaveLength(10);
    expect(a.frames.every((f) => isFiniteSnapshot(f.snap))).toBe(true);
    expect(a.loop.pending()).toBe(0);
    expect(a.wartend()).toBe(0);
    const wirft = aufbau(pendel(), { ...PHYSIK, advance: () => { throw new Error("kaputt"); } });
    wirft.lauf(1);
    expect(wirft.loop.getState().status).toBe("instabil");
    expect(wirft.wartend()).toBe(0);
    const unbekannt = aufbau({ modell: "quatsch" });
    expect(unbekannt.frames).toHaveLength(0);
    expect(unbekannt.loop.getState().wort).toBe("Simulation instabil, angehalten");
    expect(unbekannt.wartend()).toBe(0);
  });

  it("ends a throw with „gelandet nach X s“ and schedules nothing", () => {
    const a = aufbau(wurf({ laufzeit: 60 }));
    for (let i = 0; i < 20 * 60 && a.loop.getState().status === "laeuft"; i++) a.bild(1000 / 60);
    const st = a.loop.getState(), T = a.loop.getSim().periode;
    expect(st.status).toBe("gelandet");
    expect(st.wort).toBe(`gelandet nach ${formatFest(T, 1)} s`);
    expect(st.wort).toBe("gelandet nach 2,9 s");
    expect(st.laufzeit).toBeGreaterThan(3);                   // Flug dauert mit automatischem Tempo etwa 4 s
    expect(st.laufzeit).toBeLessThan(6);
    expect(a.frames[a.frames.length - 1].snap.phase).toBe("gelandet");
    expect(a.frames[a.frames.length - 1].snap.koerper[0].y).toBe(0);
    expect(a.loop.pending()).toBe(0);
    const zaeh = aufbau(wurf({ laufzeit: 60, parameter: { geschwindigkeit: 30, winkel: 60, hoehe: 5, g: 9.81, luftwiderstand: 0.05 } }));
    for (let i = 0; i < 20 * 60 && zaeh.loop.getState().status === "laeuft"; i++) zaeh.bild(1000 / 60);
    expect(zaeh.loop.getState().status).toBe("gelandet");
    expect(zaeh.loop.getState().simZeit).toBe(zaeh.loop.getSim().periode);
  });

  it("names every state in German words", () => {
    expect(statusWort("laeuft")).toBe("läuft");
    expect(statusWort("pausiert")).toBe("pausiert");
    expect(statusWort("angehalten", 30)).toBe("angehalten nach 30 s");
    expect(statusWort("gelandet", 4.23)).toBe("gelandet nach 4,2 s");
    expect(statusWort("zeitlupe")).toBe("Zeitlupe, Rechengrenze erreicht");
    expect(statusWort("instabil")).toBe("Simulation instabil, angehalten");
  });
});

describe("simLoop: Bildtakt mit Zittern", () => {
  it("keeps about 30 fps under timer jitter and never more than 31 frames in any 1000 ms", () => {
    // 60 und 120 Hz erlauben genau 30 Bilder, 144 Hz mit jedem fünften Bild 28,8; 75 Hz ohne ungleiche Abstände nur 25.
    for (const [hz, zittern, mindest] of [[60, 1, 28], [60, 2, 28], [120, 2, 28], [144, 1, 28], [144, 2, 28], [75, 1, 24], [75, 2, 24]]) {
      const a = aufbau(pendel({ laufzeit: 60 })), r = mulberry32(hz * 10 + zittern);
      for (let i = 1; i <= 20 * hz; i++) a.bildBei((i * 1000) / hz + zittern * (2 * r() - 1));
      const ts = a.frames.map((f) => f.t), fall = `${hz} Hz ±${zittern} ms`;
      expect(maxImFenster(ts), fall).toBeLessThanOrEqual(31);
      const fps = (ts.length - 1) / ((ts[ts.length - 1] - ts[0]) / 1000);
      expect(fps, fall).toBeGreaterThanOrEqual(mindest);
      expect(fps, fall).toBeLessThanOrEqual(30.5);
      expect(a.loop.getState().status, fall).toBe("laeuft");
    }
  });

  it("uses the timestamp of the frame callback, not a jittering now()", () => {
    const r = mulberry32(5);
    const a = aufbau(pendel({ laufzeit: 60 }), undefined, { now: (t) => t + 3 * (2 * r() - 1) });   // Uhr zittert ±3 ms, Takt nicht
    a.lauf(10, 60);
    const ts = a.frames.map((f) => f.t);
    expect(ts.length).toBeGreaterThanOrEqual(298);
    expect(maxImFenster(ts)).toBeLessThanOrEqual(31);
  });

  it("the same real duration at 60, 120 and 144 Hz gives the same model time within one frame", () => {
    const laeufe = [60, 120, 144].map((hz) => { const a = aufbau(pendel({ laufzeit: 60 })); a.lauf(10, hz); return a; });
    const sim = laeufe[0].loop.getSim(), z0 = laeufe[0].loop.getState().simZeit;
    for (const a of laeufe) expect(Math.abs(a.loop.getState().simZeit - z0)).toBeLessThanOrEqual(sim.tempo / 28 + sim.dt);
    expect(z0).toBeGreaterThan(9.9 * sim.tempo);
  });

  it("survives now() going backwards: re-references, never steps backwards, keeps running", () => {
    let zurueck = 0;
    const a = aufbau(pendel({ laufzeit: 60 }), undefined, { now: (t) => t - zurueck, stempel: () => NaN });
    a.lauf(2);
    zurueck = 500;                                           // Uhr eine halbe Sekunde zurückgestellt
    let lz = a.loop.getState().laufzeit, z = a.loop.getState().simZeit;
    a.lauf(2, 60, () => {
      const st = a.loop.getState();
      expect(st.laufzeit).toBeGreaterThanOrEqual(lz);
      expect(st.laufzeit - lz).toBeLessThanOrEqual(0.1 + 1e-9);
      expect(st.simZeit).toBeGreaterThanOrEqual(z);
      lz = st.laufzeit; z = st.simZeit;
    });
    expect(a.loop.getState().status).toBe("laeuft");
    expect(a.loop.getState().laufzeit).toBeGreaterThan(3.8);
    expect(a.loop.getState().laufzeit).toBeLessThanOrEqual(4 + 1e-9);
    // Zittert die Uhr ständig rückwärts, bleibt es endlich und monoton.
    let n = 0;
    const b = aufbau(pendel({ laufzeit: 60 }), undefined, { now: (t) => (++n % 7 === 0 ? t - 200 : t), stempel: () => NaN });
    let blz = 0;
    b.lauf(3, 60, () => { const st = b.loop.getState(); expect(st.laufzeit).toBeGreaterThanOrEqual(blz); blz = st.laufzeit; });
    expect(b.loop.getState().status).toBe("laeuft");
    expect(b.frames.length).toBeGreaterThan(30);
    expect(b.frames.every((f) => isFiniteSnapshot(f.snap))).toBe(true);
  });

  it("survives now() returning NaN: waits without load; uses the frame timestamp when that is finite", () => {
    const a = aufbau(pendel({ laufzeit: 60 }), undefined, { now: () => NaN, stempel: () => NaN });
    expect(() => a.lauf(1)).not.toThrow();
    expect(a.frames).toHaveLength(1);                        // nur das Startbild
    expect(a.loop.getState().laufzeit).toBe(0);
    expect(a.loop.getState().status).toBe("laeuft");
    expect(a.loop.pending()).toBe(1);
    const b = aufbau(pendel({ laufzeit: 60 }), undefined, { now: () => NaN });
    b.lauf(2);
    expect(b.frames.length).toBeGreaterThanOrEqual(59);
    expect(b.loop.getState().laufzeit).toBeGreaterThan(1.9);
  });
});

describe("simLoop: werfende Rückrufe und Bildtakt", () => {
  it("stops with „instabil“ when onFrame throws, and the constructor never throws", () => {
    let n = 0;
    const a = aufbau(pendel(), undefined, { onFrame: () => { if (++n === 5) throw new Error("Zeichnen kaputt"); } });
    expect(() => a.lauf(1)).not.toThrow();
    expect(a.loop.getState().status).toBe("instabil");
    expect(a.loop.getState().wort).toBe(INSTABIL);
    expect(worte(a.states)).toEqual(["läuft", INSTABIL]);
    expect(a.frames).toHaveLength(5);
    expect(a.loop.pending()).toBe(0);
    expect(a.wartend()).toBe(0);
    let b: ReturnType<typeof aufbau> | undefined;
    expect(() => { b = aufbau(pendel(), undefined, { onFrame: () => { throw new Error("sofort"); } }); }).not.toThrow();
    expect(b!.loop.getState().wort).toBe(INSTABIL);
    expect(b!.wartend()).toBe(0);
    b!.lauf(1);
    expect(b!.frames).toHaveLength(1);
  });

  it("stops with „instabil“ when onState throws, also in the constructor", () => {
    let a: ReturnType<typeof aufbau> | undefined;
    expect(() => { a = aufbau(pendel(), undefined, { onState: (s) => { if (s.status === "laeuft") throw new Error("Ansage kaputt"); } }); }).not.toThrow();
    expect(a!.loop.getState().status).toBe("instabil");
    expect(a!.loop.getState().wort).toBe(INSTABIL);
    expect(a!.loop.pending()).toBe(0);
    expect(a!.wartend()).toBe(0);
    const immer = aufbau(pendel(), undefined, { onState: () => { throw new Error("immer"); } });
    expect(immer.loop.getState().status).toBe("instabil");
    expect(immer.wartend()).toBe(0);
    const spaeter = aufbau(schnellesGas(), undefined, { onState: (s) => { if (s.status === "zeitlupe") throw new Error("später"); } });
    expect(() => spaeter.lauf(1)).not.toThrow();
    expect(spaeter.loop.getState().status).toBe("instabil");
    expect(worte(spaeter.states)).toEqual(["läuft", ZEITLUPE, INSTABIL]);
    expect(spaeter.loop.pending()).toBe(0);
    expect(spaeter.wartend()).toBe(0);
  });

  it("stops with „instabil“ when requestFrame throws, without throwing itself", () => {
    let a: ReturnType<typeof aufbau> | undefined;
    expect(() => { a = aufbau(pendel(), undefined, { requestFrame: () => { throw new Error("kein Takt"); } }); }).not.toThrow();
    expect(a!.loop.getState().wort).toBe(INSTABIL);
    expect(a!.loop.pending()).toBe(0);
    const b = aufbau(pendel(), undefined, { requestFrame: (n) => { if (n >= 20) throw new Error("Takt weg"); } });
    expect(() => b.lauf(2)).not.toThrow();
    expect(b.loop.getState().status).toBe("instabil");
    expect(b.loop.pending()).toBe(0);
    expect(b.wartend()).toBe(0);
    const n = b.frames.length;
    b.lauf(1);
    expect(b.frames).toHaveLength(n);
  });
});

describe("simLoop: Zeitlupe", () => {
  it("goes back from „Zeitlupe“ to „läuft“ once the load drops (after a second without the limit)", () => {
    let schwer = true;
    const eng: SimEngine = { ...PHYSIK, advance: (s, sec, max) => { const r = PHYSIK.advance(s, sec, max); return schwer ? { ...r, begrenzt: true } : r; } };
    const a = aufbau(pendel({ laufzeit: 60 }), eng);
    a.lauf(1);
    expect(a.loop.getState().status).toBe("zeitlupe");
    schwer = false;
    a.lauf(0.5);
    expect(a.loop.getState().status).toBe("zeitlupe");      // kein Flackern: erst nach 30 ruhigen Bildern
    a.lauf(1.5);
    expect(a.loop.getState().status).toBe("laeuft");
    expect(worte(a.states)).toEqual(["läuft", ZEITLUPE, "läuft"]);
    expect(a.loop.pending()).toBe(1);
  });

  it("pauses while in „Zeitlupe“ and still stops after the run time", () => {
    const a = aufbau(schnellesGas({ laufzeit: 5 }));
    a.lauf(1);
    expect(a.loop.getState().status).toBe("zeitlupe");
    a.loop.pause();
    expect(a.loop.getState().wort).toBe("pausiert");
    expect(a.loop.pending()).toBe(0);
    expect(a.wartend()).toBe(0);
    const lz = a.loop.getState().laufzeit, z = a.loop.getState().simZeit;
    a.lauf(2);
    expect(a.loop.getState().laufzeit).toBe(lz);
    expect(a.loop.getState().simZeit).toBe(z);
    a.loop.resume();
    expect(a.loop.getState().wort).toBe("läuft");
    a.lauf(6);
    const st = a.loop.getState();
    expect(st.status).toBe("angehalten");
    expect(st.wort).toBe("angehalten nach 5 s");
    expect(st.laufzeit).toBeCloseTo(5, 9);
    expect(worte(a.states)).toEqual(["läuft", ZEITLUPE, "pausiert", "läuft", ZEITLUPE, "angehalten nach 5 s"]);
    expect(a.loop.pending()).toBe(0);
    expect(a.wartend()).toBe(0);
  });
});

describe("simLoop: Tempo halb, normal, doppelt (P5b)", () => {
  it("snaps every number to 0.5, 1 or 2", () => {
    expect(TEMPO_FAKTOREN).toEqual([0.5, 1, 2]);
    const faelle: [unknown, number][] = [[0.5, 0.5], [1, 1], [2, 2], [3, 2], [Infinity, 2], [1.5, 2], [1.4, 1], [0.8, 1], [0.7, 0.5], [0.1, 0.5], [-1, 0.5], [-Infinity, 0.5], [NaN, 1], ["2", 1], [undefined, 1]];
    for (const [f, soll] of faelle) expect(tempoFaktor(f), String(f)).toBe(soll);
    const a = aufbau(pendel());
    expect(a.loop.getTempoFaktor!()).toBe(1);
    expect(a.loop.getState().tempoFaktor).toBe(1);
    a.loop.setTempoFaktor!(7);
    expect(a.loop.getTempoFaktor!()).toBe(2);
    expect(a.loop.getState().tempoFaktor).toBe(2);
  });

  it("changes the model time per real second by the factor", () => {
    const laeufe = TEMPO_FAKTOREN.map((f) => { const a = aufbau(pendel({ laufzeit: 60 })); a.loop.setTempoFaktor!(f); a.lauf(4, 60); return a; });
    const sim = laeufe[1].loop.getSim(), z = laeufe.map((a) => a.loop.getState().simZeit);
    expect(z[1]).toBeGreaterThan(3.9 * sim.tempo);
    expect(Math.abs(z[0] - 0.5 * z[1])).toBeLessThanOrEqual(2 * sim.dt);
    expect(Math.abs(z[2] - 2 * z[1])).toBeLessThanOrEqual(2 * sim.dt);
    for (const a of laeufe) {
      expect(a.loop.getState().laufzeit).toBeCloseTo(laeufe[1].loop.getState().laufzeit, 9);   // die echte Laufzeit bleibt gleich
      expect(a.loop.getState().status).toBe("laeuft");
    }
  });

  it("switches from the next frame on without a jump in the picture and keeps the factor after a restart", () => {
    const a = aufbau(pendel({ laufzeit: 60 }));
    a.lauf(1);
    const tempo = a.loop.getSim().tempo, dt = a.loop.getSim().dt, n = a.frames.length, z0 = a.loop.getState().simZeit;
    a.loop.setTempoFaktor!(2);
    expect(a.frames).toHaveLength(n);                                    // kein Bild beim Umschalten
    expect(a.loop.getState().simZeit).toBe(z0);
    a.lauf(1);
    const f = a.frames.slice(n - 1);
    for (let i = 1; i < f.length; i++) {
      const d = f[i].snap.zeit - f[i - 1].snap.zeit;
      expect(d).toBeGreaterThanOrEqual(0);
      expect(d).toBeLessThanOrEqual((2 * tempo * 1.05) / 30 + dt);        // ein Bild: höchstens doppeltes Tempo, kein Sprung
      const p = f[i].snap.koerper[0], q = f[i - 1].snap.koerper[0];
      expect(Math.hypot(p.x - q.x, p.y - q.y)).toBeLessThan(0.2);        // Pendel 1 m: der Körper springt nicht
    }
    expect(a.loop.getState().simZeit - z0).toBeGreaterThan(1.9 * tempo);
    a.loop.restart();
    expect(a.loop.getTempoFaktor!()).toBe(2);
    expect(a.loop.getState().simZeit).toBe(0);
  });

  it("never exceeds 4000 body-steps per frame at double tempo: then „Zeitlupe“", () => {
    const a = aufbau(schnellesGas());
    a.loop.setTempoFaktor!(2);
    let max = 0;
    a.lauf(3, 60, () => { max = Math.max(max, a.loop.getState().koerperSchritte); });
    expect(max).toBeLessThanOrEqual(MAX_KOERPER_SCHRITTE);
    expect(a.loop.getState().status).toBe("zeitlupe");
    for (const input of [{ ...basis, modell: "doppelpendel", parameter: { laenge1: 1, laenge2: 1, masse1: 1000, masse2: 0.01, winkel1: 180, winkel2: 0, g: 9.81, daempfung: 0 } }]) {
      const b = aufbau(input);
      b.loop.setTempoFaktor!(2);
      let m = 0;
      b.lauf(2, 60, () => { m = Math.max(m, b.loop.getState().koerperSchritte); });
      expect(m).toBeLessThanOrEqual(MAX_KOERPER_SCHRITTE);
      expect(b.frames.every((x) => isFiniteSnapshot(x.snap))).toBe(true);
    }
  });

  it("runs the new models: double pendulum, waves, orbits with attraction", () => {
    const eingaben = [
      { ...basis, modell: "doppelpendel", parameter: { laenge1: 1, laenge2: 1, masse1: 1, masse2: 1, winkel1: 120, winkel2: -30, g: 9.81, daempfung: 0 } },
      { ...basis, modell: "welle", parameter: { wellen: [{ amplitude: 1, wellenlaenge: 2, frequenz: 0.5, phase: 0, richtung: "rechts" }, { amplitude: 1, wellenlaenge: 2, frequenz: 0.5, phase: 0, richtung: "links" }], bereich: 0 } },
      { ...basis, modell: "umlauf", parameter: { zentralmasse: 1, anziehung: true, koerper: [
        { name: "A", abstand: 1, exzentrizitaet: 0.1, phase: 0, farbe: "arc", masse: 0.01 }, { name: "B", abstand: 1.6, exzentrizitaet: 0.2, phase: 180, farbe: "ok", masse: 0.01 }] } },
    ];
    for (const input of eingaben) {
      const a = aufbau(input);
      let max = 0;
      a.lauf(3, 60, () => { max = Math.max(max, a.loop.getState().koerperSchritte); });
      expect(a.loop.getState().status, input.modell).toBe("laeuft");
      expect(max).toBeGreaterThan(0);
      expect(max).toBeLessThanOrEqual(MAX_KOERPER_SCHRITTE);
      expect(a.frames.length).toBeGreaterThanOrEqual(89);
      expect(a.frames.every((f) => isFiniteSnapshot(f.snap))).toBe(true);
      expect(a.loop.getState().simZeit).toBeGreaterThan(2.9 * a.loop.getSim().tempo);
      if (input.modell === "welle") expect(a.frames[a.frames.length - 1].snap.kurve).toHaveLength(400);
      if (input.modell === "umlauf") expect(a.loop.getSim().anziehung).toBe(true);
    }
  });
});
