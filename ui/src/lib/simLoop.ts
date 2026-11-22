// Taktschleife für den Baustein `simulation` (Plan docs/ui-p5-plan.md, Abschnitte 4 bis 6, P5a). Ohne React und ohne eigene
// Uhr: Zeit und Bildtakt kommen als Funktionen herein, damit Tests sie fälschen können. Grenzen: höchstens 30 Bilder je Sekunde,
// höchstens 4000 Körper × Teilschritte je Bild (sonst läuft die Zeit langsamer: „Zeitlupe“), automatischer Stopp nach der
// Laufzeit, verdeckt kein Schritt und kein Bild (ohne Nachholen), eine lange Lücke zwischen zwei Bildern wird gekappt. Pausiert,
// angehalten oder abgebaut: kein Bild bestellt, null Last. Ein Bild mit einer nicht endlichen Zahl wird nie geliefert.

import { advance, createSim, formatFest, isFiniteSnapshot, snapshot, type AdvanceResult, type SimSnapshot, type SimState } from "./physics";

export const MAX_FPS = 30;
export const MAX_KOERPER_SCHRITTE = 4000;
/** Längste Bildlücke, die gerechnet wird (ms); alles darüber wird gekappt, damit nach einem Hänger kein Schwall kommt. */
export const MAX_BILD_LUECKE_MS = 100;
const MIN_ABSTAND_MS = 1000 / MAX_FPS - 0.5;   // 0,5 ms Spiel gegen Zittern der Bildzeiten; 60 Hz gibt genau 30 Bilder
const ZEITLUPE_ERHOLUNG = 30;                  // so viele Bilder ohne Grenze, bis „Zeitlupe“ wieder „läuft“ heißt (kein Flackern)

export type LoopStatus = "laeuft" | "pausiert" | "angehalten" | "gelandet" | "zeitlupe" | "instabil";
export interface LoopState {
  status: LoopStatus;
  /** Zustand in Worten für die Oberfläche (einmal angesagt bei Wechsel). */
  wort: string;
  /** Sichtbare Laufzeit in echten Sekunden (zählt nur, während gerechnet wird). */
  laufzeit: number;
  /** Modellzeit der Simulation. */
  simZeit: number;
  /** Körper × Teilschritte im letzten Bild (≤ MAX_KOERPER_SCHRITTE). */
  koerperSchritte: number;
}
export interface FrameScheduler {
  /** Uhr in Millisekunden. */
  now(): number;
  requestFrame(cb: (time: number) => void): number;
  cancelFrame(id: number): void;
}
/** Rechenkern; Standard ist `physics.ts`. Austauschbar für Tests. */
export interface SimEngine {
  create(input: unknown): SimState;
  advance(state: SimState, simSeconds: number, maxBodySteps: number): AdvanceResult;
  snapshot(state: SimState): SimSnapshot;
}
export const PHYSIK: SimEngine = { create: createSim, advance, snapshot };
export interface SimLoopOptions {
  /** Der Baustein `simulation` (vom Backend geprüft; wird hier noch einmal begrenzt). */
  input: unknown;
  scheduler: FrameScheduler;
  /** Fenster verdeckt oder Ansicht außer Sicht: dann kein Schritt und kein Bild. */
  isHidden?: () => boolean;
  onFrame: (snapshot: SimSnapshot) => void;
  onState?: (state: LoopState) => void;
  engine?: SimEngine;
}
export interface SimLoop {
  pause(): void;
  resume(): void;
  /** Von vorn: neuer Zustand aus derselben Eingabe, Laufzeit wieder 0. */
  restart(): void;
  /** Abbauen: kein Bild mehr, keine Rückrufe mehr. */
  dispose(): void;
  getState(): LoopState;
  getSim(): SimState;
  /** Bestellte, noch nicht gelieferte Bilder (0 oder 1). */
  pending(): number;
}

/** Zustand in Worten: „läuft“, „pausiert“, „angehalten nach 30 s“, „gelandet nach 4,2 s“, „Zeitlupe, …“, „Simulation instabil, …“. */
export function statusWort(status: LoopStatus, sekunden = 0): string {
  const s = Number.isFinite(sekunden) ? sekunden : 0;
  switch (status) {
    case "laeuft": return "läuft";
    case "pausiert": return "pausiert";
    case "angehalten": return `angehalten nach ${Math.round(s)} s`;
    case "gelandet": return `gelandet nach ${formatFest(s, 1)} s`;
    case "zeitlupe": return "Zeitlupe, Rechengrenze erreicht";
    case "instabil": return "Simulation instabil, angehalten";
  }
}

export function createSimLoop(opts: SimLoopOptions): SimLoop {
  const eng = opts.engine ?? PHYSIK;
  let sim: SimState = createSim(null);
  let frameId: number | null = null, last: number | null = null, run = 0, steps = 0, ruhig = 0;
  let status: LoopStatus = "laeuft", wort = "", disposed = false, gezeigt = false;

  const hidden = (): boolean => {
    try { return !!opts.isHidden?.(); } catch { return false; }
  };
  const getState = (): LoopState => ({ status, wort, laufzeit: run, simZeit: sim.zeit, koerperSchritte: steps });
  const setze = (s: LoopStatus): void => {
    status = s;
    const w = statusWort(s, s === "angehalten" ? sim.config.laufzeit : s === "gelandet" ? sim.zeit : 0);
    if (w !== wort) { wort = w; opts.onState?.(getState()); }
  };
  const cancel = (): void => {
    if (frameId !== null) { opts.scheduler.cancelFrame(frameId); frameId = null; }
  };
  const bestelle = (): void => {
    if (frameId === null && !disposed) frameId = opts.scheduler.requestFrame(tick);
  };
  /** Liefert das aktuelle Bild, falls alle Zahlen endlich sind; sonst Stopp mit „instabil“. */
  const liefere = (): boolean => {
    let snap: SimSnapshot | null = null;
    try { snap = eng.snapshot(sim); } catch { snap = null; }
    if (!snap || sim.phase === "instabil" || !isFiniteSnapshot(snap)) { cancel(); setze("instabil"); return false; }
    gezeigt = true;
    opts.onFrame(snap);
    return true;
  };

  function tick(): void {
    frameId = null;
    if (disposed || (status !== "laeuft" && status !== "zeitlupe")) return;
    if (hidden()) { last = null; bestelle(); return; }              // verdeckt: nichts rechnen, später nichts nachholen
    const now = opts.scheduler.now();
    if (!Number.isFinite(now)) { bestelle(); return; }
    if (last === null || now < last) {                               // Bezugsbild nach Start, Weiter oder Verdecken
      last = now;
      if (!gezeigt && !liefere()) return;
      bestelle();
      return;
    }
    const luecke = now - last;
    if (luecke < MIN_ABSTAND_MS) { bestelle(); return; }            // höchstens 30 Bilder je Sekunde
    last = now;
    const lz = sim.config.laufzeit;
    const echt = Math.max(0, Math.min(Math.min(luecke, MAX_BILD_LUECKE_MS) / 1000, lz - run));
    run += echt;
    let res: AdvanceResult | null = null;
    try { res = eng.advance(sim, echt * sim.tempo, MAX_KOERPER_SCHRITTE); } catch { res = null; }
    steps = res ? Math.min(res.koerperSchritte, MAX_KOERPER_SCHRITTE) : 0;
    if (!res) { cancel(); setze("instabil"); return; }
    if (!liefere()) return;
    if (sim.phase === "gelandet") { setze("gelandet"); return; }
    if (run >= lz - 1e-9) { setze("angehalten"); return; }
    if (res.begrenzt) { ruhig = 0; setze("zeitlupe"); }
    else if (status === "zeitlupe" && ++ruhig < ZEITLUPE_ERHOLUNG) { /* bleibt Zeitlupe, bis es eine Sekunde lang reicht */ }
    else setze("laeuft");
    bestelle();
  }

  function start(): void {
    cancel();
    try { sim = eng.create(opts.input); } catch { sim = createSim(null); sim.phase = "instabil"; }
    run = 0; last = null; steps = 0; ruhig = 0; gezeigt = false;
    if (sim.phase === "instabil") { setze("instabil"); return; }
    if (sim.phase === "gelandet") { if (liefere()) setze("gelandet"); return; }   // schon am Boden: ein Bild, dann Ende
    if (!hidden() && !liefere()) return;
    setze("laeuft");
    bestelle();
  }

  start();
  return {
    pause() {
      if (disposed || (status !== "laeuft" && status !== "zeitlupe")) return;
      cancel(); last = null; setze("pausiert");
    },
    resume() {
      if (disposed || status !== "pausiert") return;
      ruhig = 0; setze("laeuft"); bestelle();
    },
    restart() {
      if (!disposed) start();
    },
    dispose() {
      cancel(); disposed = true;
    },
    getState,
    getSim: () => sim,
    pending: () => (frameId === null ? 0 : 1),
  };
}
