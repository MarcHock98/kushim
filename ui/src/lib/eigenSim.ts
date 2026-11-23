// Rechenkern für den Baustein `sim_eigen` (Plan P7 Stufe 1, „Simulation als Daten“). Das Backend hat die Formeln schon geprüft und
// als RPN geliefert; hier wird nur gerechnet. Formeln laufen ausschließlich über `formel.ts` (Stapelmaschine), nie über Text.
// Wie `physics.ts`: reine Funktionen ohne DOM, ohne Zeitgeber, ohne Paket, Zufall nur mit Startwert (mulberry32). Das Ergebnis
// hängt nur von der Eingabe ab: fester Zeitschritt `dt`, die Bildrate bestimmt nur, wie viele Schritte je Bild gerechnet werden.
// Die Eingabe wird noch einmal begrenzt (die Mock-Demo umgeht das Backend); Unbrauchbares in Pflichtteilen macht die Simulation
// ungültig (Phase „instabil“), Fehlendes in Nebenteilen wird ersetzt und in `angepasst` genannt. Nichts wirft.
// Verfahren: Form `ode` mit Runge-Kutta vierter Ordnung (env = [t, Zustand…, Parameter…, Hilfsgrößen…], die Hilfsgrößen der Reihe
// nach ausgewertet). Form `teilchen` mit Geschwindigkeits-Verlet, wenn keine Kraft die Geschwindigkeit liest (Kraft ohne vx/vy und
// Federn ohne Dämpfung), sonst semi-implizit nach Euler (erst Geschwindigkeit, dann Lage). Kraft je Teilchen mit
// env = [t, x, y, vx, vy, m, Parameter…] (Beschleunigung = Kraft / m), Paarkraft mit env = [r, Parameter…] (positiv stößt ab,
// r nie kleiner als der Mindestabstand, ab der Reichweite 0), Federn als Kette oder feste Paare (k, l0, Dämpfung entlang der Feder),
// feste Teilchen bewegen sich nie, Wände keine, reflektieren oder periodisch (Paare dann über den kürzesten Weg).
// Grenzen: höchstens KNOTEN_BUDGET Knotenauswertungen und MAX_KOERPER_SCHRITTE Körper × Schritte je Bild (sonst läuft die Zeit
// langsamer: „Zeitlupe“, mindestens ein Schritt je Bild); Kosten je Schritt mindestens 1 je Teilchen, Feder und Paar; eine nicht endliche Zahl oder |Zustand| > 1e9 hält an („instabil, angehalten“); weicht die Erhaltungsgröße um mehr als
// 1 % vom Start ab, gibt das Bild einen Hinweis.

import { pruefeRpn, kompiliere, liestIndex, type Auswerter } from "./formel";
import {
  addToTrail, createTrail, formatFest, formatWert, formatZahl, mulberry32, SPUR_MAX,
  type AdvanceResult, type Ausschnitt, type GrenzFeld, type Kennwert, type Pt, type SimKoerper, type SimSnapshot, type SimState, type Trail,
} from "./physics";
import { MAX_KOERPER_SCHRITTE, type SimEngine } from "./simLoop";

/** Knotenauswertungen je Bild, darüber „Zeitlupe“. */
export const KNOTEN_BUDGET = 150_000;
/** Knotenauswertungen für die Vorausrechnung des Bildausschnitts, einmal beim Anlegen. */
export const VORAUS_KNOTEN = 200_000;
/** Größter Betrag einer Zustandszahl, darüber „instabil“. */
export const ZUSTAND_MAX = 1e9;
/** Abweichung der Erhaltungsgröße in Prozent, ab der das Bild einen Hinweis trägt. */
export const DRIFT_HINWEIS_PROZENT = 1;
export const GRENZEN_EIGEN = Object.freeze({
  zustand: 12, parameter: 12, hilf: 12, kennwerte: 4, knotenGesamt: 600, teilchen: 300, teilchenMitPaar: 100, federn: 400,
  darstellung: 2, dtMin: 1e-5, dtMax: 1, laufzeitMin: 5, laufzeitMax: 60, tempoMax: 100,
});
/** Fester Satz, den die Ansicht immer zeigt. */
export const EIGEN_HINWEIS = "Eigene Simulation, von kushim beschrieben, nicht geprüft. Simulation, keine Messung";
const NAME_MAX = 24, TEXT_MAX = 400;

// --- Eingabe (vom Backend geprüft, Standardwerte gefüllt) ----------------------------------------------------------------

/** Eine übersetzte Formel: RPN-Knoten und TeX zum Anzeigen. */
export interface FormelDaten { rpn: unknown[]; tex: string }
export interface EigenParameter { name: string; wert: number; min: number; max: number; einheit: string }
export interface EigenZustand { name: string; start: number; einheit: string }
export interface EigenHilf { name: string; formel: FormelDaten }
export interface EigenKennwert { name: string; formel: FormelDaten; einheit: string }
/** `koerper`: bei `ode` mit Formeln für x und y (env der ODE) und optionalem Anker, bei `teilchen` alle Teilchen. `zeitreihe` und
 *  `phasenraum` nennen Zustandsgrößen (nur `ode`), `pfeile` zeigt die Geschwindigkeiten der Teilchen. */
export type EigenDarstellung =
  | { form: "koerper"; x?: FormelDaten | null; y?: FormelDaten | null; anker?: Pt | null }
  | { form: "zeitreihe"; groessen: string[] }
  | { form: "phasenraum"; x: string; y: string }
  | { form: "pfeile" };
export type EigenStart = "linie" | "gitter" | "zufall" | "liste";
export type EigenWaende = "keine" | "reflektieren" | "periodisch";
export interface EigenFedern { kette: boolean; paare: [number, number][]; k: number; l0: number; daempfung: number }
export interface EigenPaar { f_r: FormelDaten; reichweite: number; mindestabstand: number }
interface EigenGemeinsam {
  typ?: "sim_eigen"; name: string; beschreibung: string; parameter: EigenParameter[]; darstellung: EigenDarstellung[];
  kennwerte: EigenKennwert[]; erhaltung: FormelDaten | null; dt: number; laufzeit: number; tempo: number; spur: boolean;
  /** Namen je env-Feld, wie das Backend sie gelegt hat; fehlt das Feld, gilt die feste Reihenfolge. */
  env?: { ode?: string[]; kraft?: string[]; paar?: string[] };
}
export interface EigenOdeInput extends EigenGemeinsam {
  form: "ode"; zustand: EigenZustand[]; hilf: EigenHilf[];
  /** Genau eine Ableitung je Zustand: als Objekt nach Namen oder als Liste in der Reihenfolge des Zustands. */
  ableitungen: Record<string, FormelDaten> | FormelDaten[];
}
export interface EigenTeilchenInput extends EigenGemeinsam {
  form: "teilchen"; anzahl: number; start: EigenStart; punkte: number[][]; startwert: number; masse: number;
  kasten: [number, number]; waende: EigenWaende; kraft: { fx: FormelDaten; fy: FormelDaten } | null; paar: EigenPaar | null;
  federn: EigenFedern | null; fest: number[];
}
export type EigenInput = EigenOdeInput | EigenTeilchenInput;

/** Begrenzte Eingabe; `angepasst` nennt ersetzte oder begrenzte Felder, `fehler` die Gründe einer ungültigen Eingabe (Code + Pfad). */
export interface EigenConfig {
  form: "ode" | "teilchen"; name: string; beschreibung: string; laufzeit: number; tempo: number; spur: boolean; dt: number;
  parameter: EigenParameter[]; angepasst: string[]; ungueltig: boolean; fehler: string[];
}

// --- Zustand ------------------------------------------------------------------------------------------------------------

export type EigenPhase = "laeuft" | "instabil";
export type EigenIntegrator = "rk4" | "verlet" | "euler";
/** Warum angehalten: Eingabe unbrauchbar, eine Zahl nicht endlich, ein Zustand zu groß. */
export type EigenGrund = "eingabe" | "nicht_endlich" | "zu_gross";

interface Ausgabe { name: string; f: Auswerter; einheit: string }
interface OdeKern {
  art: "ode"; n: number; p: number; h: number; env: Float64Array; y: Float64Array;
  k1: Float64Array; k2: Float64Array; k3: Float64Array; k4: Float64Array; tmp: Float64Array;
  ableit: Auswerter[]; hilf: Auswerter[]; namen: string[]; einheiten: string[];
  koerperX: Auswerter | null; koerperY: Auswerter | null; anker: Pt | null;
  reihe: number[]; phasen: [number, number] | null; kennwerte: Ausgabe[]; erhaltung: Auswerter | null;
}
interface TeilchenKern {
  art: "teilchen"; N: number; b: number; h: number; waende: EigenWaende;
  x: Float64Array; y: Float64Array; vx: Float64Array; vy: Float64Array; ax: Float64Array; ay: Float64Array;
  fx: Float64Array; fy: Float64Array; m: number; fest: Uint8Array; festListe: number[];
  envK: Float64Array; envP: Float64Array; kraftX: Auswerter | null; kraftY: Auswerter | null;
  paar: Auswerter | null; reichweite: number; rmin: number;
  fa: Int32Array; fb: Int32Array; k: number; l0: number; daempfung: number; federn: [number, number][];
  pfeile: boolean; kostenKraft: number;
}
type EigenKern = OdeKern | TeilchenKern;

/** Zustand einer eigenen Simulation. Felder wie `SimState`, die die Taktschleife liest: `config.laufzeit`, `tempo`, `phase`, `zeit`. */
export interface EigenState {
  readonly config: EigenConfig;
  readonly modell: "eigen";
  readonly form: "ode" | "teilchen";
  readonly integrator: EigenIntegrator;
  readonly dt: number;
  readonly tempo: number;
  /** Körper je Schritt (Teilchen: Anzahl, ODE: 1). */
  readonly koerper: number;
  /** Knotenauswertungen je Schritt (höchstens; bei RK4 alle vier Stufen). */
  readonly kostenJeSchritt: number;
  readonly ausschnitt: Ausschnitt;
  /** Bereich jeder Zustandsgröße aus der Vorausrechnung (ODE), für Zeitreihe und Phasenraum ohne Springen. */
  readonly bereiche: readonly { name: string; min: number; max: number }[];
  readonly text: string;
  readonly einheit: "s";
  readonly periode: number;
  readonly startBild: EigenSnapshot;
  phase: EigenPhase;
  grund: EigenGrund | null;
  schritt: number;
  zeit: number;
  soll: number;
  /** Erhaltungsgröße beim Start (ODE mit `erhaltung`), sonst null. */
  e0: number | null;
  /** Einmal über DRIFT_HINWEIS_PROZENT: bleibt gesetzt (kein Flackern). */
  hinweis: string | null;
  kern: EigenKern;
}

export interface EigenSnapshot {
  modell: "eigen";
  form: "ode" | "teilchen";
  zeit: number;
  einheit: "s";
  phase: EigenPhase;
  /** ODE mit Darstellung `koerper`: ein Körper; Teilchen: alle (feste in „amber“). */
  koerper: SimKoerper[];
  anker: Pt | null;
  ausschnitt: Ausschnitt;
  kennwerte: Kennwert[];
  verteilung: null;
  /** Zustandsgrößen jetzt (ODE). */
  werte: { name: string; wert: number; einheit: string }[];
  /** Die Größen der Zeitreihe jetzt, in der Reihenfolge der Darstellung (ODE). */
  zeitreihe: { name: string; wert: number }[];
  /** Punkt im Phasenraum jetzt (ODE mit `phasenraum`). */
  phasen: { x: string; y: string; punkt: Pt } | null;
  /** Federn als Indexpaare (Teilchen), dieselbe Liste in jedem Bild. */
  federn: readonly (readonly [number, number])[];
  /** Indizes der festen Teilchen. */
  fest: readonly number[];
  /** Geschwindigkeiten der Teilchen als [x, y, vx, vy] (Darstellung `pfeile`), sonst null. */
  pfeile: [number, number, number, number][] | null;
  /** Abweichung der Erhaltungsgröße vom Start in Prozent (ODE mit `erhaltung`), sonst null. */
  drift: number | null;
  hinweis: string | null;
}
export interface EigenAdvanceResult extends AdvanceResult {
  /** Knotenauswertungen in diesem Aufruf. */
  knoten: number;
}

// --- Hilfen ---------------------------------------------------------------------------------------------------------------

type Obj = Record<string, unknown>;
const fin = Number.isFinite;
const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const own = (o: Obj, k: string): unknown => (Object.prototype.hasOwnProperty.call(o, k) ? o[k] : undefined);
/** Steuerzeichen, unsichtbare Zeichen und Richtungswechsel (wie in physics.ts) fallen heraus. */
const steuer = (c: number): boolean => c <= 0x1f || (c >= 0x7f && c <= 0x9f) || (c >= 0x200b && c <= 0x200f) || (c >= 0x2028 && c <= 0x202e)
  || (c >= 0x2066 && c <= 0x2069) || c === 0xfeff;
const text = (v: unknown, max: number): string => {
  if (typeof v !== "string") return "";
  let out = "";
  for (let i = 0; i < v.length && out.length < max; i++) if (!steuer(v.charCodeAt(i))) out += v[i];
  return out;
};
const kw = (id: string, name: string, wert: number, einheit: string): Kennwert =>
  ({ id, name, wert, einheit, text: einheit ? `${formatWert(wert)} ${einheit}` : formatWert(wert) });

/** Bildausschnitt mit Rand; ein zu kleiner Bereich wird auf mindestens 1 Einheit (bzw. 10 % des Betrags) aufgeweitet. */
function rahmen(minX: number, maxX: number, minY: number, maxY: number, rand = 0.08): Ausschnitt {
  const weit = (lo: number, hi: number): [number, number] => {
    if (!fin(lo) || !fin(hi) || lo > hi) return [-1, 1];
    const w = hi - lo, m = Math.max(1e-9, 0.1 * Math.max(Math.abs(lo), Math.abs(hi)), w < 1e-9 ? 1 : 0);
    if (w < 1e-9) return [lo - m, hi + m];
    return [lo - rand * w, hi + rand * w];
  };
  const [a, b] = weit(minX, maxX), [c, d] = weit(minY, maxY);
  return { minX: a, maxX: b, minY: c, maxY: d };
}

// --- Eingabe begrenzen ----------------------------------------------------------------------------------------------------

interface Formel { f: Auswerter; knoten: number; liestV: boolean }
interface Lese { fix: string[]; fehler: string[]; knoten: number }

/** Liest `{rpn, tex}` und übersetzt; unbrauchbar: null und ein Fehlercode mit Pfad. */
function formelVon(v: unknown, envLen: number, pfad: string, l: Lese, pflicht: boolean): Formel | null {
  const rpn = isObj(v) ? own(v, "rpn") : undefined;
  const p = pruefeRpn(rpn, envLen);
  if (!p.ok) { (pflicht ? l.fehler : l.fix).push(`${pfad}:${p.fehler}`); return null; }
  const f = kompiliere(p.rpn);
  if (!f) { (pflicht ? l.fehler : l.fix).push(`${pfad}:intern`); return null; }
  l.knoten += f.knoten;
  return { f, knoten: f.knoten, liestV: liestIndex(p.rpn, 3) || liestIndex(p.rpn, 4) };
}

function zahlVon(o: Obj, key: string, def: number, lo: number, hi: number, l: Lese, pfad: string): number {
  const v = own(o, key);
  if (typeof v !== "number" || !fin(v)) { l.fix.push(pfad + key); return def; }
  if (v < lo || v > hi) { l.fix.push(pfad + key); return clamp(v, lo, hi); }
  return v;
}

function namenListe(v: unknown, max: number, pfad: string, l: Lese): Obj[] {
  if (v === undefined) return [];
  if (!Array.isArray(v)) { l.fix.push(pfad); return []; }
  if (v.length > max) l.fix.push(pfad);
  return v.slice(0, max).filter((e, i) => { const ok = isObj(e); if (!ok) l.fix.push(`${pfad}.${i}`); return ok; }) as Obj[];
}

function leseParameter(src: Obj, l: Lese): EigenParameter[] {
  const out: EigenParameter[] = [];
  namenListe(own(src, "parameter"), GRENZEN_EIGEN.parameter, "parameter", l).forEach((p, i) => {
    const pfad = `parameter.${i}.`, name = text(own(p, "name"), NAME_MAX), wert = own(p, "wert");
    if (!name || typeof wert !== "number" || !fin(wert)) { l.fehler.push(`parameter.${i}:unbrauchbar`); return; }
    let min = own(p, "min"), max = own(p, "max");
    if (typeof min !== "number" || !fin(min)) { l.fix.push(pfad + "min"); min = wert; }
    if (typeof max !== "number" || !fin(max)) { l.fix.push(pfad + "max"); max = wert; }
    let lo = min as number, hi = max as number;
    if (lo > hi) { l.fix.push(pfad + "min"); [lo, hi] = [hi, lo]; }
    const w = clamp(wert, lo, hi);
    if (w !== wert) l.fix.push(pfad + "wert");
    out.push({ name, wert: w, min: lo, max: hi, einheit: text(own(p, "einheit"), NAME_MAX) });
  });
  return out;
}

/** Vergleicht die vom Backend genannten env-Namen (falls vorhanden) mit der festen Reihenfolge. */
function pruefeEnv(src: Obj, slot: "ode" | "kraft" | "paar", namen: string[], l: Lese): void {
  const env = own(src, "env");
  if (!isObj(env)) return;
  const liste = own(env, slot);
  if (liste === undefined) return;
  if (!Array.isArray(liste) || liste.length !== namen.length || liste.some((n, i) => n !== namen[i])) l.fehler.push(`env.${slot}:reihenfolge`);
}

interface Gelesen { cfg: EigenConfig; bau: () => EigenKern | null; integrator: EigenIntegrator; koerper: number; kosten: number; text: string; e0Formel: boolean }

function lese(input: unknown): Gelesen {
  const l: Lese = { fix: [], fehler: [], knoten: 0 };
  const src = isObj(input) ? input : {};
  if (!isObj(input)) l.fehler.push("eingabe:kein_objekt");
  const form = own(src, "form") === "teilchen" ? "teilchen" : own(src, "form") === "ode" ? "ode" : null;
  if (!form) l.fehler.push("form:unbekannt");
  const name = text(own(src, "name"), 80), beschreibung = text(own(src, "beschreibung"), TEXT_MAX);
  const laufzeit = zahlVon(src, "laufzeit", 30, GRENZEN_EIGEN.laufzeitMin, GRENZEN_EIGEN.laufzeitMax, l, "");
  let tempo = zahlVon(src, "tempo", 0, 0, GRENZEN_EIGEN.tempoMax, l, "");
  if (tempo > 0 && tempo < 0.1) { tempo = 0.1; l.fix.push("tempo"); }
  const sp = own(src, "spur"), spur = typeof sp === "boolean" ? sp : (l.fix.push("spur"), true);
  const dt = zahlVon(src, "dt", form === "teilchen" ? 0.005 : 0.01, GRENZEN_EIGEN.dtMin, GRENZEN_EIGEN.dtMax, l, "");
  const parameter = leseParameter(src, l);
  const pNamen = parameter.map((p) => p.name), pWerte = parameter.map((p) => p.wert), P = parameter.length;
  const cfg: EigenConfig = { form: form ?? "ode", name, beschreibung, laufzeit, tempo, spur, dt, parameter, angepasst: l.fix, ungueltig: false, fehler: l.fehler };
  const dars = namenListe(own(src, "darstellung"), GRENZEN_EIGEN.darstellung, "darstellung", l);
  const fertig = (g: Omit<Gelesen, "cfg">): Gelesen => {
    if (l.knoten > GRENZEN_EIGEN.knotenGesamt) l.fehler.push("knoten:zu_viele");
    cfg.ungueltig = l.fehler.length > 0;
    return { cfg, ...g };
  };
  const leer = (): Gelesen => fertig({ bau: () => null, integrator: "rk4", koerper: 1, kosten: 0, text: "", e0Formel: false });
  if (!form) return leer();

  if (form === "ode") {
    // Zustand, Hilfsgrößen, Ableitungen
    const zustand: EigenZustand[] = [];
    namenListe(own(src, "zustand"), GRENZEN_EIGEN.zustand, "zustand", l).forEach((z, i) => {
      const n = text(own(z, "name"), NAME_MAX), s = own(z, "start");
      if (!n || typeof s !== "number" || !fin(s)) { l.fehler.push(`zustand.${i}:unbrauchbar`); return; }
      zustand.push({ name: n, start: s, einheit: text(own(z, "einheit"), NAME_MAX) });
    });
    if (!zustand.length) l.fehler.push("zustand:leer");
    const N = zustand.length;
    const hilfRoh = namenListe(own(src, "hilf"), GRENZEN_EIGEN.hilf, "hilf", l), H = hilfRoh.length;
    const envLen = 1 + N + P + H;
    const hNamen = hilfRoh.map((h) => text(own(h, "name"), NAME_MAX));
    pruefeEnv(src, "ode", ["t", ...zustand.map((z) => z.name), ...pNamen, ...hNamen], l);
    // Hilfsgröße j darf nur env bis vor sich selbst lesen
    const hilf = hilfRoh.map((h, j) => formelVon(own(h, "formel"), 1 + N + P + j, `hilf.${j}`, l, true));
    const ab = own(src, "ableitungen");
    const ableit = zustand.map((z, i) => {
      const v = Array.isArray(ab) ? ab[i] : isObj(ab) ? own(ab, z.name) : undefined;
      return formelVon(v, envLen, `ableitungen.${i}`, l, true);
    });
    // Darstellung
    const idx = (n: unknown): number => (typeof n === "string" ? zustand.findIndex((z) => z.name === n) : -1);
    let koerperX: Formel | null = null, koerperY: Formel | null = null, anker: Pt | null = null, reihe: number[] = [];
    let phasen: [number, number] | null = null, hatDarstellung = false;
    dars.forEach((d, i) => {
      const f = own(d, "form");
      if (f === "koerper") {
        koerperX = formelVon(own(d, "x"), envLen, `darstellung.${i}.x`, l, false);
        koerperY = formelVon(own(d, "y"), envLen, `darstellung.${i}.y`, l, false);
        const a = own(d, "anker");
        if (Array.isArray(a) && a.length === 2 && a.every((q) => typeof q === "number" && fin(q))) anker = [a[0], a[1]];
        else if (a !== undefined && a !== null) l.fix.push(`darstellung.${i}.anker`);
        if (koerperX && koerperY) hatDarstellung = true; else { koerperX = koerperY = null; anker = null; }
      } else if (f === "zeitreihe") {
        const g = own(d, "groessen");
        reihe = Array.isArray(g) ? g.slice(0, GRENZEN_EIGEN.zustand).map(idx).filter((q) => q >= 0) : [];
        if (!Array.isArray(g) || reihe.length !== g.length) l.fix.push(`darstellung.${i}.groessen`);
        if (reihe.length) hatDarstellung = true;
      } else if (f === "phasenraum") {
        const a = idx(own(d, "x")), b = idx(own(d, "y"));
        if (a >= 0 && b >= 0) { phasen = [a, b]; hatDarstellung = true; } else l.fix.push(`darstellung.${i}`);
      } else l.fix.push(`darstellung.${i}`);
    });
    if (!hatDarstellung) { reihe = zustand.slice(0, 4).map((_, i) => i); if (N) l.fix.push("darstellung"); }
    // Kennwerte, Erhaltung
    const kennwerte: { name: string; f: Formel; einheit: string }[] = [];
    namenListe(own(src, "kennwerte"), GRENZEN_EIGEN.kennwerte, "kennwerte", l).forEach((k, i) => {
      const f = formelVon(own(k, "formel"), envLen, `kennwerte.${i}`, l, false), n = text(own(k, "name"), 80);
      if (f && n) kennwerte.push({ name: n, f, einheit: text(own(k, "einheit"), NAME_MAX) });
      else if (f) l.fix.push(`kennwerte.${i}.name`);
    });
    const er = own(src, "erhaltung");
    const erhaltung = er === undefined || er === null ? null
      : formelVon(isObj(er) && own(er, "formel") !== undefined ? own(er, "formel") : er, envLen, "erhaltung", l, false);
    const kosten = 4 * (hilf.reduce((s, f) => s + (f?.knoten ?? 0), 0) + ableit.reduce((s, f) => s + (f?.knoten ?? 0), 0));
    const zText = zustand.map((z) => (z.einheit ? `${z.name} (${z.einheit})` : z.name)).join(", ");
    const pText = parameter.map((p) => `${p.name} = ${formatZahl(p.wert)}${p.einheit ? " " + p.einheit : ""}`).join(", ");
    const satz = `Eigene Simulation${name ? ` „${name}“` : ""}, nicht geprüft: Differentialgleichung mit den Größen ${zText || "keine"}`
      + `${pText ? `; Parameter ${pText}` : ""}.`;
    const kx = koerperX as Formel | null, ky = koerperY as Formel | null;
    const bau = (): OdeKern | null => {
      if (l.fehler.length || hilf.some((f) => !f) || ableit.some((f) => !f)) return null;
      const env = new Float64Array(envLen);
      for (let j = 0; j < P; j++) env[1 + N + j] = pWerte[j];
      const y = Float64Array.from(zustand.map((z) => z.start));
      const mk = () => new Float64Array(N);
      return {
        art: "ode", n: N, p: P, h: H, env, y, k1: mk(), k2: mk(), k3: mk(), k4: mk(), tmp: mk(),
        ableit: ableit.map((f) => f!.f), hilf: hilf.map((f) => f!.f), namen: zustand.map((z) => z.name), einheiten: zustand.map((z) => z.einheit),
        koerperX: kx?.f ?? null, koerperY: ky?.f ?? null, anker, reihe, phasen,
        kennwerte: kennwerte.map((k) => ({ name: k.name, f: k.f.f, einheit: k.einheit })), erhaltung: erhaltung?.f ?? null,
      };
    };
    return fertig({ bau, integrator: "rk4", koerper: 1, kosten, text: satz, e0Formel: !!erhaltung });
  }

  // --- Teilchen ---
  const paarRoh = own(src, "paar");
  const maxN = isObj(paarRoh) ? GRENZEN_EIGEN.teilchenMitPaar : GRENZEN_EIGEN.teilchen;
  const anzahl = Math.round(zahlVon(src, "anzahl", 10, 1, maxN, l, ""));
  const kRoh = own(src, "kasten");
  let b = 1, h = 1;
  if (Array.isArray(kRoh) && kRoh.length === 2 && kRoh.every((q) => typeof q === "number" && fin(q) && q > 0 && q <= 1e6)) [b, h] = kRoh as number[];
  else l.fix.push("kasten");
  const wRoh = own(src, "waende");
  const waende: EigenWaende = wRoh === "keine" || wRoh === "periodisch" || wRoh === "reflektieren" ? wRoh : (l.fix.push("waende"), "reflektieren");
  const envKN = ["t", "x", "y", "vx", "vy", "m", ...pNamen], envPN = ["r", ...pNamen];
  pruefeEnv(src, "kraft", envKN, l);
  const kraftRoh = own(src, "kraft");
  let kraftX: Formel | null = null, kraftY: Formel | null = null;
  if (isObj(kraftRoh)) {
    kraftX = formelVon(own(kraftRoh, "fx"), envKN.length, "kraft.fx", l, true);
    kraftY = formelVon(own(kraftRoh, "fy"), envKN.length, "kraft.fy", l, true);
  } else if (kraftRoh !== undefined && kraftRoh !== null) l.fehler.push("kraft:unbrauchbar");
  let paar: Formel | null = null, reichweite = Infinity, rmin = 1e-3 * Math.min(b, h);
  if (isObj(paarRoh)) {
    pruefeEnv(src, "paar", envPN, l);
    paar = formelVon(own(paarRoh, "f_r"), envPN.length, "paar.f_r", l, true);
    const rw = own(paarRoh, "reichweite");
    if (typeof rw === "number" && rw > 0) reichweite = rw; else l.fix.push("paar.reichweite");
    const mi = own(paarRoh, "mindestabstand");
    if (typeof mi === "number" && fin(mi) && mi > 0) rmin = mi; else if (mi !== undefined) l.fix.push("paar.mindestabstand");
  } else if (paarRoh !== undefined && paarRoh !== null) l.fehler.push("paar:unbrauchbar");
  // Federn
  const fRoh = own(src, "federn"), federn: [number, number][] = [];
  let fk = 0, fl0 = 0, fd = 0;
  if (isObj(fRoh)) {
    fk = zahlVon(fRoh, "k", 1, 0, 1e9, l, "federn.");
    fl0 = zahlVon(fRoh, "l0", 0, 0, 1e6, l, "federn.");
    fd = own(fRoh, "daempfung") === undefined ? 0 : zahlVon(fRoh, "daempfung", 0, 0, 1e9, l, "federn.");
    const kette = own(fRoh, "kette") === true || own(fRoh, "verbindung") === "kette";
    if (kette) for (let i = 0; i + 1 < anzahl; i++) federn.push([i, i + 1]);
    const pr = own(fRoh, "paare");
    if (Array.isArray(pr)) for (const q of pr) {
      if (Array.isArray(q) && q.length === 2 && Number.isInteger(q[0]) && Number.isInteger(q[1]) && q[0] !== q[1]
        && q[0] >= 0 && q[1] >= 0 && q[0] < anzahl && q[1] < anzahl) federn.push([q[0], q[1]]);
      else l.fix.push("federn.paare");
    }
    if (federn.length > GRENZEN_EIGEN.federn) { federn.length = GRENZEN_EIGEN.federn; l.fix.push("federn"); }
    if (!federn.length) l.fix.push("federn");
  } else if (fRoh !== undefined && fRoh !== null) l.fix.push("federn");
  const festRoh = own(src, "fest"), festListe: number[] = [];
  if (Array.isArray(festRoh)) for (const q of festRoh) {
    if (Number.isInteger(q) && q >= 0 && q < anzahl && !festListe.includes(q)) festListe.push(q); else l.fix.push("fest");
  } else if (festRoh !== undefined) l.fix.push("fest");
  // Masse: aus der Eingabe, sonst Parameter „m“, sonst 1
  const mRoh = own(src, "masse"), mPar = parameter.find((p) => p.name === "m");
  const masse = typeof mRoh === "number" && fin(mRoh) && mRoh > 0 ? mRoh : mPar && mPar.wert > 0 ? mPar.wert : 1;
  // Startlage
  const stRoh = own(src, "start");
  const start: EigenStart = stRoh === "gitter" || stRoh === "zufall" || stRoh === "liste" || stRoh === "linie" ? stRoh : (l.fix.push("start"), "linie");
  const startwert = zahlVon(src, "startwert", 1, -1e15, 1e15, l, "");
  const punkte = own(src, "punkte");
  let pfeile = false, koerperDarst = false;
  dars.forEach((d, i) => {
    const f = own(d, "form");
    if (f === "pfeile") pfeile = true;
    else if (f === "koerper") koerperDarst = true;
    else l.fix.push(`darstellung.${i}`);
  });
  if (!koerperDarst && !pfeile) l.fix.push("darstellung");
  if (own(src, "kennwerte") !== undefined && Array.isArray(own(src, "kennwerte")) && (own(src, "kennwerte") as unknown[]).length) l.fix.push("kennwerte");
  if (own(src, "erhaltung") !== undefined && own(src, "erhaltung") !== null) l.fix.push("erhaltung");
  const nutztV = !!(kraftX?.liestV || kraftY?.liestV) || (federn.length > 0 && fd > 0);
  const paare = paar ? (anzahl * (anzahl - 1)) / 2 : 0;
  // Wie im Backend (schema.py): Formelknoten je Teilchen und je Paar, dazu mindestens 1 je Teilchen, je Feder und je Paar. Ohne
  // Formeln wären die Kosten sonst 0, und kein Budget griffe.
  const kostenKraft = anzahl * ((kraftX?.knoten ?? 0) + (kraftY?.knoten ?? 0)) + paare * (paar?.knoten ?? 0) + anzahl + federn.length + paare;
  const satz = `Eigene Simulation${name ? ` „${name}“` : ""}, nicht geprüft: ${anzahl} Teilchen in einem Kasten von ${formatZahl(b)} mal ${formatZahl(h)}`
    + `, Wände ${waende}${federn.length ? `, ${federn.length} Federn` : ""}${festListe.length ? `, ${festListe.length} feste Teilchen` : ""}`
    + `${paar ? ", mit Kraft zwischen den Teilchen" : ""}${parameter.length ? `; Parameter ${parameter.map((p) => `${p.name} = ${formatZahl(p.wert)}${p.einheit ? " " + p.einheit : ""}`).join(", ")}` : ""}.`;
  const bau = (): TeilchenKern | null => {
    if (l.fehler.length) return null;
    const N = anzahl, x = new Float64Array(N), y = new Float64Array(N), vx = new Float64Array(N), vy = new Float64Array(N);
    const linie = (i: number) => { x[i] = (b * (i + 0.5)) / N; y[i] = h / 2; };
    if (start === "gitter") {
      const sp = Math.max(1, Math.ceil(Math.sqrt((N * b) / h))), zl = Math.ceil(N / sp);
      for (let i = 0; i < N; i++) { x[i] = (b * ((i % sp) + 0.5)) / sp; y[i] = (h * (Math.floor(i / sp) + 0.5)) / zl; }
    } else if (start === "zufall") {
      const rnd = mulberry32(startwert);
      for (let i = 0; i < N; i++) { x[i] = rnd() * b; y[i] = rnd() * h; }
    } else if (start === "liste") {
      const pl = Array.isArray(punkte) ? punkte : [];
      for (let i = 0; i < N; i++) {
        const q: unknown = pl[i];
        if (Array.isArray(q) && (q.length === 2 || q.length === 4) && q.every((z) => typeof z === "number" && fin(z) && Math.abs(z) <= 1e6)) {
          x[i] = q[0]; y[i] = q[1]; if (q.length === 4) { vx[i] = q[2]; vy[i] = q[3]; }
        } else { linie(i); if (!l.fix.includes("punkte")) l.fix.push("punkte"); }
      }
    } else for (let i = 0; i < N; i++) linie(i);
    const fest = new Uint8Array(N);
    for (const i of festListe) { fest[i] = 1; vx[i] = 0; vy[i] = 0; }
    const envK = new Float64Array(6 + P), envP = new Float64Array(1 + P);
    for (let j = 0; j < P; j++) { envK[6 + j] = pWerte[j]; envP[1 + j] = pWerte[j]; }
    envK[5] = masse;
    return {
      art: "teilchen", N, b, h, waende, x, y, vx, vy, ax: new Float64Array(N), ay: new Float64Array(N), fx: new Float64Array(N), fy: new Float64Array(N),
      m: masse, fest, festListe: festListe.slice(), envK, envP, kraftX: kraftX?.f ?? null, kraftY: kraftY?.f ?? null,
      paar: paar?.f ?? null, reichweite, rmin, fa: Int32Array.from(federn.map((q) => q[0])), fb: Int32Array.from(federn.map((q) => q[1])),
      k: fk, l0: fl0, daempfung: fd, federn: federn.map((q) => Object.freeze([q[0], q[1]]) as [number, number]), pfeile, kostenKraft,
    };
  };
  return fertig({ bau, integrator: nutztV ? "euler" : "verlet", koerper: anzahl, kosten: kostenKraft, text: satz, e0Formel: false });
}

// --- Rechnen: ODE ---------------------------------------------------------------------------------------------------------

/** Ableitungen bei (t, y) nach `out`; danach stehen im env Zeit, Zustand und alle Hilfsgrößen. */
function odeAbl(k: OdeKern, t: number, y: Float64Array, out: Float64Array): void {
  const env = k.env, n = k.n, h0 = 1 + n + k.p;
  env[0] = t;
  for (let i = 0; i < n; i++) env[1 + i] = y[i];
  for (let j = 0; j < k.h; j++) env[h0 + j] = k.hilf[j](env);
  for (let i = 0; i < n; i++) out[i] = k.ableit[i](env);
}

function odeSchritt(k: OdeKern, t: number, dt: number): void {
  const { n, y, k1, k2, k3, k4, tmp } = k;
  odeAbl(k, t, y, k1);
  for (let i = 0; i < n; i++) tmp[i] = y[i] + 0.5 * dt * k1[i];
  odeAbl(k, t + 0.5 * dt, tmp, k2);
  for (let i = 0; i < n; i++) tmp[i] = y[i] + 0.5 * dt * k2[i];
  odeAbl(k, t + 0.5 * dt, tmp, k3);
  for (let i = 0; i < n; i++) tmp[i] = y[i] + dt * k3[i];
  odeAbl(k, t + dt, tmp, k4);
  for (let i = 0; i < n; i++) y[i] += (dt / 6) * (k1[i] + 2 * k2[i] + 2 * k3[i] + k4[i]);
}

// --- Rechnen: Teilchen ----------------------------------------------------------------------------------------------------

/** Winkel der festen Richtung von j nach i für zwei Teilchen an genau derselben Stelle: hängt nur von den Indizes ab (gleiche
 *  Eingabe, gleiche Simulation), nie vom Zufall. Acht Richtungen im Abstand von 45 Grad. */
const richtung = (i: number, j: number): number => (((i * 7 + j * 13) % 8) * Math.PI) / 4;

/** Kürzester Abstand in einer Richtung (periodische Wände: über den Rand). */
const kurz = (d: number, L: number, periodisch: boolean): number => (periodisch ? d - L * Math.round(d / L) : d);

/** Kräfte und Beschleunigungen zur Zeit t aus den aktuellen Lagen und Geschwindigkeiten (feste Teilchen: 0). */
function beschl(k: TeilchenKern, t: number): void {
  const { N, x, y, vx, vy, fx, fy, fest, envK, envP } = k, per = k.waende === "periodisch";
  fx.fill(0); fy.fill(0);
  if (k.kraftX && k.kraftY) {
    envK[0] = t;
    for (let i = 0; i < N; i++) {
      if (fest[i]) continue;
      envK[1] = x[i]; envK[2] = y[i]; envK[3] = vx[i]; envK[4] = vy[i];
      fx[i] += k.kraftX(envK); fy[i] += k.kraftY(envK);
    }
  }
  if (k.paar) {
    const R = k.reichweite;
    for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) {
      const dx = kurz(x[i] - x[j], k.b, per), dy = kurz(y[i] - y[j], k.h, per), d = Math.hypot(dx, dy);
      if (!(d <= R)) continue;                                        // weiter als die Reichweite (oder keine Zahl): keine Kraft
      envP[0] = Math.max(d, k.rmin);                                  // näher als der Mindestabstand: mit dem Mindestabstand rechnen
      let ex: number, ey: number;
      if (d > 0) { ex = dx / d; ey = dy / d; } else { const w = richtung(i, j); ex = Math.cos(w); ey = Math.sin(w); }   // dieselbe Stelle
      const f = k.paar(envP), ux = f * ex, uy = f * ey;
      fx[i] += ux; fy[i] += uy; fx[j] -= ux; fy[j] -= uy;
    }
  }
  for (let s = 0; s < k.fa.length; s++) {
    const a = k.fa[s], c = k.fb[s];
    const dx = kurz(x[a] - x[c], k.b, per), dy = kurz(y[a] - y[c], k.h, per), d = Math.hypot(dx, dy);
    if (!(d >= 0)) continue;
    let ux: number, uy: number;
    if (d > 0) { ux = dx / d; uy = dy / d; } else { const w = richtung(a, c); ux = Math.cos(w); uy = Math.sin(w); }
    const rel = (vx[a] - vx[c]) * ux + (vy[a] - vy[c]) * uy;
    const F = -k.k * (d - k.l0) - k.daempfung * rel;
    fx[a] += F * ux; fy[a] += F * uy; fx[c] -= F * ux; fy[c] -= F * uy;
  }
  for (let i = 0; i < N; i++) {
    if (fest[i]) { k.ax[i] = 0; k.ay[i] = 0; } else { k.ax[i] = fx[i] / k.m; k.ay[i] = fy[i] / k.m; }
  }
}

function waende(k: TeilchenKern, i: number): void {
  if (k.waende === "keine") return;
  const { x, y, vx, vy, b, h } = k;
  if (k.waende === "periodisch") {
    if (x[i] < 0 || x[i] >= b) x[i] -= b * Math.floor(x[i] / b);
    if (y[i] < 0 || y[i] >= h) y[i] -= h * Math.floor(y[i] / h);
    return;
  }
  if (x[i] < 0) { x[i] = Math.min(-x[i], b); vx[i] = Math.abs(vx[i]); } else if (x[i] > b) { x[i] = Math.max(2 * b - x[i], 0); vx[i] = -Math.abs(vx[i]); }
  if (y[i] < 0) { y[i] = Math.min(-y[i], h); vy[i] = Math.abs(vy[i]); } else if (y[i] > h) { y[i] = Math.max(2 * h - y[i], 0); vy[i] = -Math.abs(vy[i]); }
}

function teilchenSchritt(k: TeilchenKern, t: number, dt: number, verlet: boolean): void {
  const { N, x, y, vx, vy, ax, ay, fest } = k;
  if (verlet) {
    // Geschwindigkeits-Verlet: Lage mit alter Beschleunigung, neue Beschleunigung, Geschwindigkeit mit dem Mittel beider.
    for (let i = 0; i < N; i++) {
      if (fest[i]) continue;
      x[i] += vx[i] * dt + 0.5 * ax[i] * dt * dt; y[i] += vy[i] * dt + 0.5 * ay[i] * dt * dt;
      vx[i] += 0.5 * ax[i] * dt; vy[i] += 0.5 * ay[i] * dt;
      waende(k, i);
    }
    beschl(k, t + dt);
    for (let i = 0; i < N; i++) if (!fest[i]) { vx[i] += 0.5 * ax[i] * dt; vy[i] += 0.5 * ay[i] * dt; }
  } else {
    beschl(k, t);
    for (let i = 0; i < N; i++) {
      if (fest[i]) continue;
      vx[i] += ax[i] * dt; vy[i] += ay[i] * dt;
      x[i] += vx[i] * dt; y[i] += vy[i] * dt;
      waende(k, i);
    }
  }
}

// --- Prüfen ----------------------------------------------------------------------------------------------------------------

/** null: alles gut; sonst der Grund für „instabil“. */
function pruefeZustand(k: EigenKern): EigenGrund | null {
  const listen = k.art === "ode" ? [k.y] : [k.x, k.y, k.vx, k.vy];
  for (const q of listen) for (let i = 0; i < q.length; i++) {
    const v = q[i];
    if (!fin(v)) return "nicht_endlich";
    if (v > ZUSTAND_MAX || v < -ZUSTAND_MAX) return "zu_gross";
  }
  return null;
}

function einSchritt(s: EigenState): void {
  const t = s.schritt * s.dt, k = s.kern;
  if (k.art === "ode") odeSchritt(k, t, s.dt);
  else teilchenSchritt(k, t, s.dt, s.integrator === "verlet");
  s.schritt++;
}

// --- Anlegen ----------------------------------------------------------------------------------------------------------------

const KEIN_KERN = (): OdeKern => ({
  art: "ode", n: 0, p: 0, h: 0, env: new Float64Array(1), y: new Float64Array(0), k1: new Float64Array(0), k2: new Float64Array(0),
  k3: new Float64Array(0), k4: new Float64Array(0), tmp: new Float64Array(0), ableit: [], hilf: [], namen: [], einheiten: [],
  koerperX: null, koerperY: null, anker: null, reihe: [], phasen: null, kennwerte: [], erhaltung: null,
});

/** Läuft eine frische Kopie voraus (höchstens VORAUS_KNOTEN), um Bildausschnitt und Bereiche der Größen festzulegen. */
function vorausBereiche(g: Gelesen, dt: number, dauer: number): { aus: Ausschnitt; bereiche: { name: string; min: number; max: number }[] } {
  const k = g.bau();
  if (!k || k.art !== "ode") return { aus: rahmen(0, 1, 0, 1), bereiche: [] };
  const lo = Array.from(k.y), hi = Array.from(k.y);
  let kx0 = Infinity, kx1 = -Infinity, ky0 = Infinity, ky1 = -Infinity;
  const tmp = new Float64Array(k.n);
  const koerper = (t: number): void => {
    if (!k.koerperX || !k.koerperY) return;
    odeAbl(k, t, k.y, tmp);
    const px = k.koerperX(k.env), py = k.koerperY(k.env);
    if (fin(px) && fin(py)) { kx0 = Math.min(kx0, px); kx1 = Math.max(kx1, px); ky0 = Math.min(ky0, py); ky1 = Math.max(ky1, py); }
  };
  koerper(0);
  const proSchritt = Math.max(1, g.kosten + (k.koerperX ? 2 * (k.koerperX.knoten + k.koerperY!.knoten) : 0));
  const n = Math.min(Math.ceil(dauer / dt), Math.floor(VORAUS_KNOTEN / proSchritt));
  for (let i = 0; i < n; i++) {
    odeSchritt(k, i * dt, dt);
    if (pruefeZustand(k)) break;
    for (let j = 0; j < k.n; j++) { if (k.y[j] < lo[j]) lo[j] = k.y[j]; if (k.y[j] > hi[j]) hi[j] = k.y[j]; }
    koerper((i + 1) * dt);
  }
  if (k.anker) { kx0 = Math.min(kx0, k.anker[0]); kx1 = Math.max(kx1, k.anker[0]); ky0 = Math.min(ky0, k.anker[1]); ky1 = Math.max(ky1, k.anker[1]); }
  const bereiche = k.namen.map((name, j) => ({ name, min: lo[j], max: hi[j] }));
  let aus: Ausschnitt;
  if (k.koerperX && fin(kx0)) {
    // gleicher Maßstab in x und y (ein Pendel bleibt rund): beide Seiten auf die größere Spanne
    const cx = (kx0 + kx1) / 2, cy = (ky0 + ky1) / 2, w = Math.max(kx1 - kx0, ky1 - ky0) / 2;
    aus = rahmen(cx - w, cx + w, cy - w, cy + w);
  } else if (k.phasen) {
    const [a, b] = k.phasen;
    aus = rahmen(lo[a], hi[a], lo[b], hi[b]);
  } else aus = rahmen(0, 1, 0, 1);
  return { aus, bereiche };
}

/** Legt eine eigene Simulation an: Eingabe begrenzen, RPN prüfen und übersetzen, Ausschnitt vorab rechnen. Wirft nie. */
export function createEigen(input: unknown): EigenState {
  let g: Gelesen;
  try { g = lese(input); } catch { g = lese(null); g.cfg.ungueltig = true; g.cfg.fehler.push("intern"); }
  let kern: EigenKern | null = null;
  try { kern = g.cfg.ungueltig ? null : g.bau(); } catch { kern = null; }
  const tempo = g.cfg.tempo > 0 ? g.cfg.tempo : 1;
  let aus: Ausschnitt = rahmen(0, 1, 0, 1), bereiche: { name: string; min: number; max: number }[] = [];
  if (kern?.art === "teilchen") aus = { minX: -0.04 * kern.b, maxX: 1.04 * kern.b, minY: -0.04 * kern.h, maxY: 1.04 * kern.h };
  else if (kern) { try { ({ aus, bereiche } = vorausBereiche(g, g.cfg.dt, g.cfg.laufzeit * tempo)); } catch { /* bleibt Standard */ } }
  const s: EigenState = {
    config: g.cfg, modell: "eigen", form: g.cfg.form, integrator: g.integrator, dt: g.cfg.dt, tempo, koerper: g.koerper,
    kostenJeSchritt: Math.max(1, g.kosten), ausschnitt: aus, bereiche, text: g.text, einheit: "s", periode: 1,
    startBild: null as unknown as EigenSnapshot, phase: kern ? "laeuft" : "instabil", grund: kern ? null : "eingabe",
    schritt: 0, zeit: 0, soll: 0, e0: null, hinweis: null, kern: kern ?? KEIN_KERN(),
  };
  try {
    if (kern) {
      // Probe bei t = 0: Ableitungen bzw. Beschleunigungen müssen endlich sein (Verlet braucht sie ohnehin als Start).
      if (kern.art === "ode") {
        odeAbl(kern, 0, kern.y, kern.k1);
        for (let i = 0; i < kern.n; i++) if (!fin(kern.k1[i])) { s.phase = "instabil"; s.grund = "nicht_endlich"; }
        if (kern.erhaltung) { const e = kern.erhaltung(kern.env); s.e0 = fin(e) ? e : null; }
      } else {
        beschl(kern, 0);
        for (let i = 0; i < kern.N; i++) if (!fin(kern.ax[i]) || !fin(kern.ay[i])) { s.phase = "instabil"; s.grund = "nicht_endlich"; }
      }
      const grund = pruefeZustand(kern);
      if (grund) { s.phase = "instabil"; s.grund = grund; }
    }
  } catch { s.phase = "instabil"; s.grund = "nicht_endlich"; }
  (s as { startBild: EigenSnapshot }).startBild = snapshotEigen(s);
  return s;
}

// --- Weiterrechnen ------------------------------------------------------------------------------------------------------------

/** Rechnet um `simSeconds` Modellzeit weiter, in festen Schritten auf dem Raster t = n·dt. Je Aufruf höchstens KNOTEN_BUDGET Knoten
 *  und höchstens `maxBodySteps` Körper × Schritte (wie bei den eingebauten Modellen, Standard MAX_KOERPER_SCHRITTE), mindestens ein
 *  Schritt; reicht das nicht, bleibt die Zeit zurück (`begrenzt`, kein Nachholen, „Zeitlupe“). Wirft nie; eine nicht endliche oder
 *  zu große Zahl setzt „instabil“. */
export function advanceEigen(s: EigenState, simSeconds: number, maxBodySteps: number = MAX_KOERPER_SCHRITTE): EigenAdvanceResult {
  const nichts: EigenAdvanceResult = { schritte: 0, koerperSchritte: 0, begrenzt: false, knoten: 0 };
  if (s.phase !== "laeuft") return nichts;
  try {
    s.soll += fin(simSeconds) && simSeconds > 0 ? Math.min(simSeconds, 1e12) : 0;
    const ziel = Math.floor(s.soll / s.dt + 1e-9), n = ziel - s.schritt;
    if (n <= 0) return nichts;
    const je = s.kostenJeSchritt, koerper = Math.max(1, s.koerper);
    const maxK = fin(maxBodySteps) && maxBodySteps > 0 ? Math.min(maxBodySteps, MAX_KOERPER_SCHRITTE) : MAX_KOERPER_SCHRITTE;
    let done = 0, knoten = 0;
    while (done < n && (done === 0 || (knoten + je <= KNOTEN_BUDGET && (done + 1) * koerper <= maxK))) {
      einSchritt(s);
      knoten += je;
      done++;
      const grund = pruefeZustand(s.kern);
      if (grund) { s.phase = "instabil"; s.grund = grund; break; }
    }
    s.zeit = s.schritt * s.dt;
    const begrenzt = done < n && s.phase === "laeuft";
    if (begrenzt) s.soll = s.schritt * s.dt;
    if (!fin(s.zeit)) { s.phase = "instabil"; s.grund = "nicht_endlich"; }
    return { schritte: done, koerperSchritte: done * s.koerper, begrenzt, knoten };
  } catch {
    s.phase = "instabil"; s.grund = "nicht_endlich";
    return nichts;
  }
}

// --- Bild ----------------------------------------------------------------------------------------------------------------------

/** Was zum Zeichnen gebraucht wird. Eine nicht endliche Ausgabe (Körperlage, Kennwert) setzt „instabil“. Wirft nie. */
export function snapshotEigen(s: EigenState): EigenSnapshot {
  const basis: EigenSnapshot = {
    modell: "eigen", form: s.form, zeit: s.zeit, einheit: "s", phase: s.phase, koerper: [], anker: null, ausschnitt: s.ausschnitt,
    kennwerte: [], verteilung: null, werte: [], zeitreihe: [], phasen: null, federn: [], fest: [], pfeile: null, drift: null, hinweis: s.hinweis,
  };
  try {
    const k = s.kern;
    if (k.art === "ode") {
      if (s.grund === "eingabe") return basis;
      odeAbl(k, s.zeit, k.y, k.tmp);                                // füllt env mit Zeit, Zustand und Hilfsgrößen
      const env = k.env;
      basis.werte = k.namen.map((name, i) => ({ name, wert: k.y[i], einheit: k.einheiten[i] }));
      basis.zeitreihe = k.reihe.map((i) => ({ name: k.namen[i], wert: k.y[i] }));
      if (k.phasen) basis.phasen = { x: k.namen[k.phasen[0]], y: k.namen[k.phasen[1]], punkt: [k.y[k.phasen[0]], k.y[k.phasen[1]]] };
      if (k.koerperX && k.koerperY) {
        basis.koerper = [{ x: k.koerperX(env), y: k.koerperY(env), r: 0, farbe: "arc", name: "Körper" }];
        basis.anker = k.anker;
      }
      basis.kennwerte = k.kennwerte.map((q, i) => kw(`kennwert.${i}`, q.name, q.f(env), q.einheit));
      if (k.erhaltung && s.e0 !== null) {
        const e = k.erhaltung(env), d = (Math.abs(e - s.e0) / Math.max(Math.abs(s.e0), 1e-12)) * 100;
        basis.drift = fin(d) ? d : null;
        if (fin(d)) basis.kennwerte.push({ id: "erhaltung", name: "Abweichung der Erhaltungsgröße", wert: d, einheit: "%", text: `${formatFest(d, d < 1 ? 2 : 1)} %` });
        if ((!fin(d) || d > DRIFT_HINWEIS_PROZENT) && !s.hinweis) {
          s.hinweis = fin(d) ? `Die Erhaltungsgröße weicht um ${formatFest(d, 1)} % vom Start ab. Ein kleinerer Zeitschritt rechnet genauer.`
            : "Die Erhaltungsgröße ist nicht mehr berechenbar.";
        }
      }
    } else {
      const koerper: SimKoerper[] = new Array(k.N);
      let ekin = 0, summe = 0;
      for (let i = 0; i < k.N; i++) {
        koerper[i] = { x: k.x[i], y: k.y[i], r: 0, farbe: k.fest[i] ? "amber" : "arc", name: k.fest[i] ? "festes Teilchen" : "" };
        const q = k.vx[i] * k.vx[i] + k.vy[i] * k.vy[i];
        ekin += 0.5 * k.m * q; summe += Math.sqrt(q);
      }
      basis.koerper = koerper;
      basis.federn = k.federn;
      basis.fest = k.festListe;
      basis.kennwerte = [kw("bewegungsenergie", "Bewegungsenergie", ekin, ""), kw("geschwindigkeit", "Mittlere Geschwindigkeit", summe / Math.max(1, k.N), "")];
      if (k.pfeile) basis.pfeile = Array.from({ length: k.N }, (_, i): [number, number, number, number] => [k.x[i], k.y[i], k.vx[i], k.vy[i]]);
    }
    basis.hinweis = s.hinweis;
    if (!eigenEndlich(basis) && s.phase === "laeuft") { s.phase = "instabil"; s.grund = "nicht_endlich"; basis.phase = "instabil"; }
    return basis;
  } catch {
    s.phase = "instabil"; s.grund = s.grund ?? "nicht_endlich";
    return { ...basis, phase: "instabil", koerper: [], kennwerte: [] };
  }
}

/** Sind alle Zahlen im Bild endlich? (Wie `isFiniteSnapshot`, dazu die Felder der eigenen Simulation.) */
export function eigenEndlich(b: EigenSnapshot | null | undefined): boolean {
  try {
    if (!b || !fin(b.zeit)) return false;
    const a = b.ausschnitt;
    if (!fin(a.minX) || !fin(a.maxX) || !fin(a.minY) || !fin(a.maxY)) return false;
    if (b.anker && (!fin(b.anker[0]) || !fin(b.anker[1]))) return false;
    for (const p of b.koerper) if (!fin(p.x) || !fin(p.y) || !fin(p.r)) return false;
    for (const q of b.kennwerte) if (!fin(q.wert)) return false;
    for (const q of b.werte) if (!fin(q.wert)) return false;
    for (const q of b.zeitreihe) if (!fin(q.wert)) return false;
    if (b.phasen && (!fin(b.phasen.punkt[0]) || !fin(b.phasen.punkt[1]))) return false;
    if (b.pfeile) for (const q of b.pfeile) if (!q.every(fin)) return false;
    return true;
  } catch {
    return false;
  }
}

/** Rechenkern für die Taktschleife (`createSimLoop({ engine: EIGEN })`). Der Zustand passt in die Felder, die die Schleife liest. */
export const EIGEN: SimEngine = {
  create: (input) => createEigen(input) as unknown as SimState,
  advance: (state, sec, max) => advanceEigen(state as unknown as EigenState, sec, max),
  snapshot: (state) => snapshotEigen(state as unknown as EigenState) as unknown as SimSnapshot,
};

// --- Spuren ------------------------------------------------------------------------------------------------------------------

/** Spuren über die Hilfen aus `physics.ts`: Körper (höchstens SPUR_KOERPER_MAX), Zeitreihe (x = Zeit) und Phasenraum. */
export interface EigenSpuren { koerper: Trail; zeitreihe: Trail; phasen: Trail }

export function createEigenSpuren(s: EigenState, max: number = SPUR_MAX): EigenSpuren {
  const k = s.kern;
  return {
    koerper: createTrail(k.art === "ode" ? (k.koerperX ? 1 : 0) : k.N, max),
    zeitreihe: createTrail(k.art === "ode" ? k.reihe.length : 0, max),
    phasen: createTrail(k.art === "ode" && k.phasen ? 1 : 0, max),
  };
}

const alsBild = (koerper: SimKoerper[]): SimSnapshot => ({ koerper } as unknown as SimSnapshot);
const punkt = (x: number, y: number): SimKoerper => ({ x, y, r: 0, farbe: "arc", name: "" });

/** Hängt ein Bild an die Spuren (nur endliche Punkte; gleiche Punkte werden übersprungen). */
export function addEigenSpuren(sp: EigenSpuren, b: EigenSnapshot): void {
  if (!eigenEndlich(b)) return;
  addToTrail(sp.koerper, alsBild(b.koerper));
  addToTrail(sp.zeitreihe, alsBild(b.zeitreihe.map((q) => punkt(b.zeit, q.wert))));
  if (b.phasen) addToTrail(sp.phasen, alsBild([punkt(b.phasen.punkt[0], b.phasen.punkt[1])]));
}

// --- Regler ------------------------------------------------------------------------------------------------------------------

/** Regler je Parameter: `feld` ist der Name des Parameters, Grenzen aus der Eingabe, Schritt etwa ein Hundertstel der Spanne. */
export function eigenRegler(input: unknown): GrenzFeld[] {
  try {
    const g = lese(input);
    // Nur Parameter mit einer echten Spanne und einem Schritt über 0 bekommen einen Regler (eine winzige Spanne wie 1e-323 ergäbe
    // Schritt 0 und unendlich viele Stufen); die übrigen zeigt die Ansicht als feste Zahl.
    return g.cfg.parameter.filter((p) => p.max > p.min).flatMap((p) => {
      const sp = p.max - p.min, schritt = Math.pow(10, Math.floor(Math.log10(sp / 100)));
      if (!(schritt > 0) || !fin(schritt) || !fin(sp / schritt) || sp / schritt > 1e6) return [];
      return [Object.freeze({ feld: p.name, name: p.name, einheit: p.einheit, min: p.min, max: p.max, schritt,
        skala: p.min > 0 && p.max >= 1000 * p.min ? "log" : "linear" }) as GrenzFeld];
    });
  } catch {
    return [];
  }
}

/** Neue Eingabe mit Parameter `name` auf `wert`, begrenzt auf seine Grenzen aus der Eingabe. Ändert die Eingabe nie (kopiert
 *  Eingabe und Parameterliste). Unbekannter Name oder keine endliche Zahl: eine unveränderte Kopie. Wirft nie. */
export function mitParameter<T>(input: T, name: string, wert: number): T {
  try {
    if (!isObj(input)) return input;
    const kopie: Obj = { ...input }, liste = own(input, "parameter");
    if (!Array.isArray(liste) || typeof wert !== "number" || !fin(wert)) return kopie as T;
    const i = liste.findIndex((p) => isObj(p) && own(p, "name") === name);
    if (i < 0) return kopie as T;
    const p = liste[i] as Obj, lo = own(p, "min"), hi = own(p, "max");
    const a = typeof lo === "number" && fin(lo) ? lo : wert, b = typeof hi === "number" && fin(hi) ? hi : wert;
    const neu = liste.slice();
    neu[i] = { ...p, wert: clamp(wert, Math.min(a, b), Math.max(a, b)) };
    kopie.parameter = neu;
    return kopie as T;
  } catch {
    return input;
  }
}
