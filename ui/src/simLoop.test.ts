import { describe, expect, it } from "vitest";
import { formatFest, isFiniteSnapshot, type SimSnapshot } from "./lib/physics";
import { createSimLoop, MAX_KOERPER_SCHRITTE, PHYSIK, statusWort, type LoopState, type SimEngine } from "./lib/simLoop";

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

function aufbau(input: unknown, engine?: SimEngine) {
  let t = 0, id = 0, hidden = false;
  const queue = new Map<number, (ts: number) => void>();
  const scheduler = {
    now: () => t,
    requestFrame: (cb: (ts: number) => void) => { queue.set(++id, cb); return id; },
    cancelFrame: (i: number) => { queue.delete(i); },
  };
  const frames: { t: number; snap: SimSnapshot }[] = [], states: LoopState[] = [];
  const loop = createSimLoop({
    input, scheduler, engine, isHidden: () => hidden,
    onFrame: (snap) => frames.push({ t, snap }), onState: (s) => states.push(s),
  });
  /** Ein angebotenes Bild nach `ms` Millisekunden. */
  const bild = (ms: number) => { t += ms; const cbs = [...queue.values()]; queue.clear(); for (const cb of cbs) cb(t); };
  /** `sekunden` lang Bilder mit `hz` anbieten; `jedes` läuft nach jedem angebotenen Bild. */
  const lauf = (sekunden: number, hz = 60, jedes?: () => void) => {
    for (let i = 0, n = Math.round(sekunden * hz); i < n; i++) { bild(1000 / hz); jedes?.(); }
  };
  return { loop, frames, states, bild, lauf, wartend: () => queue.size, verstecke: (v: boolean) => { hidden = v; } };
}

const worte = (states: LoopState[]) => states.map((s) => s.wort);

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
