// Taktschleife für den Baustein `simulation` (Plan docs/ui-p5-plan.md, Abschnitte 4 bis 6, P5a). Ohne React und ohne eigene
// Uhr: Zeit und Bildtakt kommen als Funktionen herein, damit Tests sie fälschen können. Grenzen: höchstens 30 Bilder je Sekunde,
// höchstens 4000 Körper × Teilschritte je Bild (sonst läuft die Zeit langsamer: „Zeitlupe“), automatischer Stopp nach der
// Laufzeit, verdeckt kein Schritt und kein Bild (ohne Nachholen), eine lange Lücke zwischen zwei Bildern wird gekappt. Pausiert,
// angehalten oder abgebaut: kein Bild bestellt, null Last. Ein Bild mit einer nicht endlichen Zahl wird nie geliefert.
// Nichts wirft: wirft ein Rückruf (`onFrame`, `onState`) oder der Bildtakt (`requestFrame`), endet die Schleife mit „instabil“
// und bestellt nichts mehr. Zeit: der Zeitstempel des Bildtakts (wie bei requestAnimationFrame), sonst `now()`.

import { advance, createSim, formatFest, isFiniteSnapshot, snapshot, type AdvanceResult, type SimSnapshot, type SimState } from "./physics";

export const MAX_FPS = 30;
export const MAX_KOERPER_SCHRITTE = 4000;
/** Längste Bildlücke, die gerechnet wird (ms); alles darüber wird gekappt, damit nach einem Hänger kein Schwall kommt. */
export const MAX_BILD_LUECKE_MS = 100;
const BILD_MS = 1000 / MAX_FPS;
// Spiel gegen Zittern der Bildzeiten: ein Bild darf so viel früher als 1/30 s nach dem letzten kommen. Halber Bildabstand der
// Anzeige (gemessen, gleitend gemittelt), höchstens 6 ms, vor der ersten Messung 0,5 ms. So liefert 60 Hz auch mit ±2 ms
// Zittern jedes zweite Bild, 144 Hz jedes fünfte und 240 Hz jedes achte (nie zwei Bilder im Abstand unter 1/30 s ohne Zittern).
const SPIEL_MIN_MS = 0.5, SPIEL_MAX_MS = 6;
// Harte Grenze über das Spiel hinaus: nie mehr als 31 Bilder in einem Fenster von 1000 ms.
const FENSTER_MS = 1000, FENSTER_BILDER = MAX_FPS + 1;
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
  let vorher: number | null = null, takt: number | null = null;   // letztes angebotenes Bild, gemittelter Bildabstand der Anzeige
  const fenster = new Float64Array(FENSTER_BILDER);                // Zeiten der letzten 31 gelieferten Bilder (Ring)
  let fensterN = 0, fensterKopf = 0;

  const aktiv = (): boolean => status === "laeuft" || status === "zeitlupe";
  const hidden = (): boolean => {
    try { return !!opts.isHidden?.(); } catch { return false; }
  };
  const getState = (): LoopState => ({ status, wort, laufzeit: run, simZeit: sim.zeit, koerperSchritte: steps });
  const cancel = (): void => {
    const id = frameId;
    frameId = null;
    if (id !== null) { try { opts.scheduler.cancelFrame(id); } catch { /* schon weg */ } }
  };
  /** Endgültiger Stopp mit „instabil“: nichts bestellt; ein Fehler im Rückruf ändert daran nichts mehr. */
  const stoppe = (): void => {
    cancel();
    if (status === "instabil") return;
    status = "instabil";
    wort = statusWort("instabil");
    try { opts.onState?.(getState()); } catch { /* bleibt instabil */ }
  };
  const setze = (s: LoopStatus): void => {
    status = s;
    const w = statusWort(s, s === "angehalten" ? sim.config.laufzeit : s === "gelandet" ? sim.zeit : 0);
    if (w === wort) return;
    wort = w;
    try { opts.onState?.(getState()); } catch { stoppe(); }
  };
  const bestelle = (): void => {
    if (frameId !== null || disposed || !aktiv()) return;
    try { frameId = opts.scheduler.requestFrame(tick); } catch { frameId = null; stoppe(); }
  };
  /** Liefert das aktuelle Bild, falls alle Zahlen endlich sind; sonst (oder wenn `onFrame` wirft) Stopp mit „instabil“. */
  const liefere = (): boolean => {
    let snap: SimSnapshot | null = null;
    try { snap = eng.snapshot(sim); } catch { snap = null; }
    if (!snap || sim.phase === "instabil" || !isFiniteSnapshot(snap)) { stoppe(); return false; }
    gezeigt = true;
    try { opts.onFrame(snap); } catch { stoppe(); return false; }
    return true;
  };
  /** Zeitstempel des Bildtakts, falls endlich; sonst die Uhr (NaN, wenn auch sie nichts taugt). */
  const zeitpunkt = (time: unknown): number => {
    if (typeof time === "number" && Number.isFinite(time)) return time;
    try { const t = opts.scheduler.now(); return typeof t === "number" ? t : NaN; } catch { return NaN; }
  };
  const merkeTakt = (ts: number): void => {
    if (vorher !== null) {
      const d = ts - vorher;
      if (d > 0 && d <= MAX_BILD_LUECKE_MS) takt = takt === null ? d : takt + 0.2 * (d - takt);
    }
    vorher = ts;
  };
  const spiel = (): number => (takt === null ? SPIEL_MIN_MS : Math.min(SPIEL_MAX_MS, Math.max(SPIEL_MIN_MS, takt / 2)));
  const fensterFrei = (ts: number): boolean => fensterN < FENSTER_BILDER || ts - fenster[fensterKopf] > FENSTER_MS;
  const merkeBild = (ts: number): void => {
    fenster[fensterKopf] = ts;
    fensterKopf = (fensterKopf + 1) % FENSTER_BILDER;
    fensterN = Math.min(fensterN + 1, FENSTER_BILDER);
  };

  function tick(time?: number): void {
    frameId = null;
    if (disposed || !aktiv()) return;
    try { schritt(time); } catch { stoppe(); }
  }

  function schritt(time: unknown): void {
    if (hidden()) { last = null; vorher = null; bestelle(); return; }   // verdeckt: nichts rechnen, später nichts nachholen
    const now = zeitpunkt(time);
    if (!Number.isFinite(now)) { bestelle(); return; }
    if (last === null || now < last) {                               // Bezugsbild nach Start, Weiter, Verdecken oder Uhr rückwärts
      if (last !== null) { fensterN = 0; vorher = null; }           // alte Zeiten passen nicht mehr zur Uhr
      last = now;
      merkeTakt(now);
      if (!gezeigt) { if (!liefere()) return; merkeBild(now); }
      bestelle();
      return;
    }
    merkeTakt(now);
    const luecke = now - last;
    if (luecke < BILD_MS - spiel() || !fensterFrei(now)) { bestelle(); return; }   // höchstens 30 Bilder je Sekunde
    last = now;
    const lz = sim.config.laufzeit;
    const echt = Math.max(0, Math.min(Math.min(luecke, MAX_BILD_LUECKE_MS) / 1000, lz - run));
    run += echt;
    let res: AdvanceResult | null = null;
    try { res = eng.advance(sim, echt * sim.tempo, MAX_KOERPER_SCHRITTE); } catch { res = null; }
    steps = res ? Math.min(res.koerperSchritte, MAX_KOERPER_SCHRITTE) : 0;
    if (!res) { stoppe(); return; }
    if (!liefere()) return;
    merkeBild(now);
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
    run = 0; last = null; vorher = null; steps = 0; ruhig = 0; gezeigt = false;
    if (sim.phase === "instabil") { setze("instabil"); return; }
    if (sim.phase === "gelandet") { if (liefere()) setze("gelandet"); return; }   // schon am Boden: ein Bild, dann Ende
    if (!hidden() && !liefere()) return;
    setze("laeuft");
    bestelle();
  }
  const sicherStart = (): void => {
    try { start(); } catch { stoppe(); }
  };

  sicherStart();                                                     // wirft nie, auch nicht bei werfenden Rückrufen
  return {
    pause() {
      if (disposed || !aktiv()) return;
      cancel(); last = null; vorher = null; setze("pausiert");
    },
    resume() {
      if (disposed || status !== "pausiert") return;
      ruhig = 0; setze("laeuft"); bestelle();
    },
    restart() {
      if (!disposed) sicherStart();
    },
    dispose() {
      cancel(); disposed = true;
    },
    getState,
    getSim: () => sim,
    pending: () => (frameId === null ? 0 : 1),
  };
}
