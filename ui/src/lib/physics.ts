// Rechenkern für den Baustein `simulation` (Plan docs/ui-p5-plan.md, Abschnitte 2 bis 6, P5a): fünf feste Modelle mit festem
// Zeitschritt. Reine Funktionen ohne DOM, ohne Zeitgeber, ohne Paket und ohne Zufall ohne Startwert. Das Ergebnis hängt nur von
// der Eingabe ab, nie von der Bildrate oder der Uhr: ein Teilschritt dauert immer gleich lang in Modellzeit, die Bildrate
// bestimmt nur, wie viele Teilschritte je Bild gerechnet werden. Das Backend prüft die Eingabe; hier wird trotzdem alles noch
// einmal begrenzt (die Mock-Demo umgeht das Backend). Nichts wirft, keine Schleife läuft ohne Grenze, und jede Zahl, die das
// Modul verlässt, ist endlich, sonst steht der Zustand auf „instabil“.
// Verfahren: Pendel mit Geschwindigkeits-Verlet, die halben Stöße mit Dämpfung exakt gelöst (der Schritt kommt nur aus der
// Schwingung); Feder geschlossen über die exakte Übergangsmatrix des gedämpften Schwingers (jede Dämpfung, auch überdämpft; die
// Energie fällt nur); Wurf ohne Luftwiderstand geschlossen, mit Luftwiderstand fester Schritt (Schwerkraft und Bremsung je exakt,
// im Wechsel); Umlauf geschlossen über die Kepler-Gleichung; Gas mit festem Schritt, elastischen Stößen über ein Raster (Zellen
// ≤ 4·N + 16) und energieerhaltenden Wänden.
// P5b (Plan Abschnitt 7): Doppelpendel mit festem Raster und Runge-Kutta vierter Ordnung in Teilschritten, die nur vom Zustand
// abhängen (fängt das „Peitschen“ eines leichten oberen Körpers ab), die Dämpfung je halber Rasterschritt exakt (ω·e^(−c·dt/2), die
// Energie fällt dabei nur); Welle als geschlossene Überlagerung von bis zu drei Sinuswellen auf höchstens 50 kürzesten Wellenlängen;
// Umlauf mit gegenseitiger Anziehung (`anziehung: true`) als Leapfrog (Stoß, Drift, Stoß) mit festem Schritt, fester Zentralmasse
// im Ursprung und kleiner Glättung (Körper untereinander 0,01 der kleinsten großen Halbachse, zur Zentralmasse 0,001, bei schweren
// Körpern 0,01), der Schritt höchstens 0,05 der Glättungs-Zeitmaße; ohne Anziehung bleibt der Umlauf die geschlossene
// Kepler-Lösung, Bit für Bit wie in P5a. Dazu Regler-Grenzen (`GRENZEN`, `mitWert`).
// Typen: `SimModell`, `SimInput` und `SimConfig` bleiben die fünf P5a-Modelle (die Ansicht prüft sie vollständig); die Fassungen
// mit allen sieben Modellen heißen `SimModellAlle`, `SimInputAlle`, `SimConfigAlle`. `normalizeSim` gibt für eine Eingabe vom Typ
// `SimInput` eine `SimConfig` zurück, sonst eine `SimConfigAlle`.

export type SimModell = "pendel" | "feder" | "wurf" | "umlauf" | "gas";
/** Modelle aus P5b. */
export type SimModellP5b = "doppelpendel" | "welle";
export type SimModellAlle = SimModell | SimModellP5b;
export type WellenRichtung = "rechts" | "links";
export type Farbe = "arc" | "amber" | "ok" | "warn" | "alarm" | "text" | "gedaempft";
export type Pt = [number, number];
/** `laeuft`: rechnet weiter; `gelandet`: Wurf am Boden (Ende); `instabil`: eine Zahl war nicht endlich oder die Eingabe unbrauchbar. */
export type SimPhase = "laeuft" | "gelandet" | "instabil";

export interface PendelParameter { laenge: number; winkel: number; anfangsgeschwindigkeit: number; daempfung: number; g: number }
export interface FederParameter { masse: number; federkonstante: number; auslenkung: number; daempfung: number }
export interface WurfParameter { geschwindigkeit: number; winkel: number; hoehe: number; g: number; luftwiderstand: number }
/** `masse` (P5b) in Sonnenmassen 0 bis 0,01, zählt nur mit `anziehung: true`; fehlt sie, gilt 0. */
export interface UmlaufKoerper { name: string; abstand: number; exzentrizitaet: number; phase: number; farbe: Farbe; masse?: number }
/** `anziehung` (P5b): die Körper ziehen sich gegenseitig an; fehlt sie, gilt `false` (geschlossene Kepler-Lösung). */
export interface UmlaufParameter { zentralmasse: number; koerper: UmlaufKoerper[]; anziehung?: boolean }
export interface GasParameter {
  anzahl: number; kasten: [number, number]; radius: number; geschwindigkeit: number; schwerkraft: number; stoesse: boolean; startwert: number;
}
/** Winkel in Grad aus der Senkrechten (nach unten 0), Längen in m, Massen in kg, Dämpfung in 1/s. */
export interface DoppelpendelParameter {
  laenge1: number; laenge2: number; masse1: number; masse2: number; winkel1: number; winkel2: number; g: number; daempfung: number;
}
/** Eine Sinuswelle y = A·sin(k·x ∓ ω·t + φ), k = 2π/λ, ω = 2π·f; „rechts“ läuft zu größerem x. Phase in Grad. */
export interface Welle { amplitude: number; wellenlaenge: number; frequenz: number; phase: number; richtung: WellenRichtung }
/** `bereich` in m; 0 = automatisch (doppelte größte Wellenlänge). */
export interface WelleParameter { wellen: Welle[]; bereich: number }
interface Gemeinsam { laufzeit: number; tempo: number; spur: boolean; beschreibung: string }
/** Eingabe wie vom Backend geprüft (Standardwerte gefüllt). Einheiten: SI; `umlauf` in AE, Jahren, Sonnenmassen; `gas` in „Einheiten“. */
export type SimInput = Gemeinsam & (
  | { modell: "pendel"; parameter: PendelParameter }
  | { modell: "feder"; parameter: FederParameter }
  | { modell: "wurf"; parameter: WurfParameter }
  | { modell: "umlauf"; parameter: UmlaufParameter }
  | { modell: "gas"; parameter: GasParameter });
/** Begrenzte Eingabe. `angepasst` nennt jedes Feld, das fehlte, kaputt war, ersetzt, gerundet oder begrenzt wurde; `ungueltig`:
 *  Modell unbekannt oder eine Kombination, die das Backend ablehnt (Wurf aus Höhe 0 nicht nach oben, Umlauf mit größter durch
 *  kleinste Halbachse über 100). Eine ungültige Eingabe läuft nicht (Phase „instabil“). */
export type SimConfig = SimInput & { angepasst: string[]; ungueltig: boolean };
/** Eingabe der P5b-Modelle (vom Backend geprüft, Standardwerte gefüllt). */
export type SimInputP5b = Gemeinsam & (
  | { modell: "doppelpendel"; parameter: DoppelpendelParameter }
  | { modell: "welle"; parameter: WelleParameter });
export type SimInputAlle = SimInput | SimInputP5b;
export type SimConfigAlle = SimInputAlle & { angepasst: string[]; ungueltig: boolean };

/** Bildausschnitt in Modelleinheiten (y nach oben), einmal vorab gerechnet, damit das Bild nicht springt. */
export interface Ausschnitt { minX: number; maxX: number; minY: number; maxY: number }
/** Ein Körper zum Zeichnen. `r` ist nur beim Gas ein echter Radius (Modelleinheiten), sonst 0 = Zeichen in fester Größe. */
export interface SimKoerper { x: number; y: number; r: number; farbe: Farbe; name: string }
export interface Kennwert { id: string; name: string; wert: number; einheit: string; text: string }
/** Geschwindigkeitsverteilung: 11 Grenzen, 10 Klassen; die letzte Klasse nimmt auch alles darüber. */
export interface Verteilung { grenzen: number[]; anzahl: number[] }
export interface SimSnapshot {
  modell: SimModellAlle;
  /** Modellzeit (Sekunden, bei `umlauf` Jahre). */
  zeit: number;
  einheit: "s" | "Jahre";
  phase: SimPhase;
  /** Doppelpendel: [oberer, unterer] Pendelkörper; Welle: keine. */
  koerper: SimKoerper[];
  /** Aufhängung (Pendel, Doppelpendel), Wand (Feder), Zentralmasse (Umlauf); sonst null. */
  anker: Pt | null;
  /** Welle: x von 0 bis `bereich`, y von −1,1·(Summe der Amplituden) bis +1,1·…, beides in m (die Ansicht skaliert y selbst). */
  ausschnitt: Ausschnitt;
  kennwerte: Kennwert[];
  verteilung: Verteilung | null;
  /** Nur Welle: die Summe y(x) an WELLE_PUNKTE Stellen von 0 bis `bereich` (Lagen in m). */
  kurve?: Pt[];
  /** Nur Welle: jede einzelne Welle an denselben Stellen (eine Kurve je Welle, höchstens drei). */
  teilkurven?: Pt[][];
  /** Indizes der Körper, die eine Spur bekommen (Doppelpendel: nur der untere, [1]); fehlt das Feld: alle. */
  spurKoerper?: number[];
  /** Nur Umlauf mit Anziehung: so viele Körper liegen gerade außerhalb von `ausschnitt` (die Ansicht sagt es in Worten). */
  ausserhalb?: number;
}
/** Standbild für „weniger Bewegung“. `kurve`: Punkte (Zeit in s, Wert); `bahn`/`punkte`: Lagen in Modelleinheiten.
 *  Umlauf mit Anziehung: `bahnen` sind die gerechneten Wege über `dauer` Jahre (`offen: true`, nicht geschlossen zeichnen).
 *  Doppelpendel: Startlage (`start`) und der Weg des unteren Körpers über die ersten `dauer` s (10 s, sonst so viel wie ins
 *  Budget passt). Welle: die Kurve bei t = 0 mit den einzelnen Wellen und die Hülle (kleinster und größter Wert je Stelle über eine
 *  Periode der langsamsten Welle, `dauer` s); `exakt`: alle Frequenzen gleich, Hülle geschlossen gerechnet, sonst abgetastet. */
export type Standbild =
  | { modell: "pendel" | "feder"; start: SimSnapshot; kurve: Pt[]; groesse: string; einheit: string; dauer: number }
  | { modell: "wurf"; start: SimSnapshot; bahn: Pt[]; gipfel: Pt; aufprall: Pt; flugzeit: number; vollstaendig: boolean }
  | { modell: "umlauf"; start: SimSnapshot; bahnen: { name: string; farbe: Farbe; punkte: Pt[] }[]; offen?: boolean; dauer?: number }
  | { modell: "gas"; start: SimSnapshot; verteilung: Verteilung; zeit: number }
  | { modell: "doppelpendel"; start: SimSnapshot; bahn: Pt[]; dauer: number }
  | { modell: "welle"; start: SimSnapshot; kurve: Pt[]; teilkurven: Pt[][]; huelleMin: Pt[]; huelleMax: Pt[]; dauer: number; exakt: boolean };
export interface AdvanceResult {
  /** Gerechnete Teilschritte (bei geschlossener Lösung: übersprungene Raster-Schritte). */
  schritte: number;
  /** Körper × Teilschritte, die wirklich gerechnet wurden (geschlossene Lösung: ein Auswerten je Körper). */
  koerperSchritte: number;
  /** Die Grenze reichte nicht: die Modellzeit läuft langsamer als verlangt (kein Nachholen). */
  begrenzt: boolean;
}

export interface PendelKern {
  art: "pendel"; L: number; w2: number; c: number; damp: number; th: number; om: number; a: number; E0: number; T0: number; Tm: number; rotiert: boolean;
}
export interface FederKern {
  art: "feder"; m: number; k: number; w2: number; c: number; damp: number; x: number; v: number; a: number; E0: number; T: number; S: number; zeta: number;
  /** Übergangsmatrix über einen Teilschritt (geschlossene Lösung): x' = pxx·x + pxv·v, v' = pvx·x + pvv·v. Fehlt sie, wird sie gerechnet. */
  pxx?: number; pxv?: number; pvx?: number; pvv?: number;
}
export interface WurfKern {
  art: "wurf"; g: number; kd: number; geschlossen: boolean; v0x: number; v0y: number; h: number;
  x: number; y: number; vx: number; vy: number; flugzeit: number; reichweite: number; gipfel: number; gipfelX: number;
  gelandet: boolean; landezeit: number; vollstaendig: boolean; bahn: Pt[];
}
export interface UmlaufBahn { name: string; farbe: Farbe; a: number; e: number; b: number; P: number; M0: number; E: number }
export interface UmlaufKern { art: "umlauf"; M: number; bahnen: UmlaufBahn[] }
export interface GasKern {
  art: "gas"; N: number; b: number; h: number; r: number; g: number; stoesse: boolean; v0: number; vref: number; vmax: number;
  px: Float64Array; py: Float64Array; vx: Float64Array; vy: Float64Array; start: Float64Array;
  nx: number; ny: number; zelle: Int32Array; zaehler: Int32Array; zeiger: Int32Array; folge: Int32Array; rKleiner: boolean;
}
/** Doppelpendel: Winkel aus der Senkrechten (rad), Winkelgeschwindigkeiten (rad/s); `damp` = e^(−c·dt/2). */
export interface DoppelpendelKern {
  art: "doppelpendel"; L1: number; L2: number; m1: number; m2: number; g: number; c: number; damp: number;
  th1: number; om1: number; th2: number; om2: number; E0: number;
  /** Schwingungsdauern bei kleinen Ausschlägen: gleichsinnig (langsam) und gegensinnig (schnell). */
  Tlangsam: number; Tschnell: number;
  /** Kreisfrequenz der schnellen Eigenschwingung (Bezug für die Teilschritte) und höchste Zahl der Teilschritte je Rasterschritt. */
  wRef: number; kmax: number;
}
/** Welle: je Welle Amplitude, Wellenzahl k = 2π/λ, Kreisfrequenz ω = 2π·f, Phase (rad) und s = −1 (rechts) oder +1 (links). */
export interface WelleKern {
  art: "welle"; A: number[]; k: number[]; w: number[]; phi: number[]; s: number[]; lambda: number[]; f: number[];
  bereich: number; automatisch: boolean; xs: Float64Array; Tmax: number; Tmin: number;
}
/** Umlauf mit gegenseitiger Anziehung: Lagen (AE), Geschwindigkeiten (AE/Jahr), Beschleunigungen; G = 4π² AE³/(Jahr²·Sonnenmasse). */
export interface NKoerperKern {
  art: "nkoerper"; n: number; GM: number; m: Float64Array; w: Float64Array;
  x: Float64Array; y: Float64Array; vx: Float64Array; vy: Float64Array; ax: Float64Array; ay: Float64Array;
  /** Quadrat der Glättungslänge zur Zentralmasse und zwischen den Körpern (AE²). */
  eps2z: number; eps2: number; bahnen: UmlaufBahn[]; E0: number;
  /** Vorab gerechnete Wege (für Bildausschnitt und Standbild) über `pfadDauer` Jahre. */
  pfade: Pt[][]; pfadDauer: number;
}
export type SimKern = PendelKern | FederKern | WurfKern | UmlaufKern | GasKern | DoppelpendelKern | WelleKern | NKoerperKern;

/** Zustand einer Simulation. `advance` ändert ihn an Ort und Stelle; `kern` ist innen und nur für Tests lesbar. */
export interface SimState {
  readonly config: SimConfigAlle;
  readonly modell: SimModellAlle;
  /** Umlauf mit gegenseitiger Anziehung (die Ansicht zeigt dann ihren festen Satz dazu); sonst false. */
  readonly anziehung?: boolean;
  /** Fester Teilschritt in Modellzeit (bei geschlossener Lösung das Zeitraster). */
  readonly dt: number;
  /** Modellzeit je echter Sekunde (aus der Eingabe oder automatisch). */
  readonly tempo: number;
  /** Körper je Teilschritt (für die Grenze Körper × Teilschritte je Bild). */
  readonly koerper: number;
  readonly ausschnitt: Ausschnitt;
  /** Textfassung für Vorleser: Modell, Parameter und Kennwerte als Satz (ändert sich während des Laufs nicht). */
  readonly text: string;
  readonly einheit: "s" | "Jahre";
  /** Zeitmaß der Bewegung in Modellzeit: eine Schwingung, der Flug, der innerste Umlauf (Gas: 1). */
  readonly periode: number;
  readonly startBild: SimSnapshot;
  phase: SimPhase;
  schritt: number;
  zeit: number;
  /** Bereits verbrauchte Vorausrechnung (Körper-Schritte), höchstens VORAUS_BUDGET. */
  vorausSchritte: number;
  soll: number;
  kern: SimKern;
  bild: Standbild | null;
}

export const MODELLE: readonly SimModell[] = ["pendel", "feder", "wurf", "umlauf", "gas"];
/** Alle sieben Modelle (P5a und P5b). */
export const MODELLE_ALLE: readonly SimModellAlle[] = [...MODELLE, "doppelpendel", "welle"];
/** Stellen, an denen die Welle ausgewertet wird (gleichmäßig von 0 bis `bereich`). */
export const WELLE_PUNKTE = 400;
/** Der gezeigte Bereich umfasst höchstens so viele kürzeste Wellenlängen (sonst wäre die Welle mit WELLE_PUNKTE Stellen falsch). */
export const WELLE_MAX_LAENGEN = 50;
/** Höchstens so viele Punkte im Weg des Standbilds beim Doppelpendel. */
export const DOPPELPENDEL_BAHN_MAX = 1200;
export const FARBEN: readonly Farbe[] = ["arc", "amber", "ok", "warn", "alarm", "text", "gedaempft"];
/** Höchstens so viele Körper-Schritte für Bildausschnitt, Kennwerte und Standbild, einmal beim Öffnen. */
export const VORAUS_BUDGET = 200_000;
/** Höchstens so viele Punkte je Körper in der Spur. */
export const SPUR_MAX = 600;
/** Höchstens so viele Körper bekommen eine Spur (Gas: nur die ersten). */
export const SPUR_KOERPER_MAX = 8;
export const GAS_MAX = 300;

const RAD = Math.PI / 180;
const TAU = 2 * Math.PI;
const MAX_CALL = 1_000_000;          // Körper-Schritte je Aufruf von `advance`, falls der Aufrufer keine Grenze nennt
const GAS_STANDBILD_S = 10;
const DP_STANDBILD_S = 10;           // Weg des unteren Doppelpendel-Körpers im Standbild: die ersten 10 s Modellzeit
const G_AE = TAU * TAU;              // Gravitationskonstante in AE³/(Jahr²·Sonnenmasse)
// Glättung zwischen Körpern und zur Zentralmasse, je mal kleinste Halbachse; zur Zentralmasse 0,01 nur bei schweren Körpern (siehe
// `nkoerperTeile`), sonst 0,001 (dann bleiben auch sehr exzentrische Bahnen bis auf Bruchteile eines Promilles Kepler-genau).
const NK_GLAETTUNG = 1e-2, NK_GLAETTUNG_Z = 1e-3, NK_GLAETTUNG_Z_SCHWER = 1e-2;
const NK_PFAD_PUNKTE = 360;          // Punkte je Körper im vorab gerechneten Weg (Umlauf mit Anziehung)
const fin = Number.isFinite;
const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));

// --- Zahlen auf Deutsch ------------------------------------------------------------------------------------------------

function deutsch(x: number, stellen: number, kuerzen: boolean): string {
  let s = Math.abs(x).toFixed(stellen);
  if (kuerzen && s.includes(".")) s = s.replace(/0+$/, "").replace(/\.$/, "");
  const [ganz, rest] = s.split(".");
  const gruppiert = ganz.length > 4 ? ganz.replace(/\B(?=(\d{3})+(?!\d))/g, "\u00a0") : ganz;
  return (x < 0 && /[1-9]/.test(s) ? "-" : "") + gruppiert + (rest ? "," + rest : "");
}

/** Feste Nachkommastellen mit Komma, zum Beispiel formatFest(4.23, 1) = „4,2“. */
export function formatFest(x: number, stellen: number): string {
  if (!fin(x) || Math.abs(x) >= 1e15) return "–";
  return deutsch(x, clamp(Math.round(stellen) || 0, 0, 12), false);
}

/** Parameterzahl ohne überflüssige Nullen, bis zu 6 gültige Ziffern (die Textfassung nennt den Parameter, nicht eine Rundung):
 *  1 → „1“, 9.81 → „9,81“, 120.5 → „120,5“, 0.1 + 0.2 → „0,3“, 12345.5 → „12 345,5“. */
export function formatZahl(x: number): string {
  if (!fin(x) || Math.abs(x) >= 1e15) return "–";
  const a = Math.abs(x);
  if (a < 1e-12) return "0";
  const st = clamp(5 - Math.floor(Math.log10(a)), 0, 12);
  return deutsch(x, st, true);
}

/** Gerechneter Wert, gerundet: 2.006 → „2,0“, 0.14 → „0,14“, 316228 → „316 228“. */
export function formatWert(x: number): string {
  if (!fin(x) || Math.abs(x) >= 1e15) return "–";
  const a = Math.abs(x);
  if (a < 1e-12) return "0";
  const st = a >= 100 ? 0 : a >= 1 ? 1 : Math.min(12, 1 - Math.floor(Math.log10(a)));
  return deutsch(x, st, false);
}

// --- Zufall mit Startwert ----------------------------------------------------------------------------------------------

/** Kleiner Zufallsgenerator mit Startwert (mulberry32): gleiche Zahl, gleiche Folge, Werte in [0, 1). */
export function mulberry32(seed: number): () => number {
  let a = (fin(seed) ? Math.floor(seed) : 0) >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// --- Eingabe begrenzen -------------------------------------------------------------------------------------------------

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const own = (o: Obj, k: string): unknown => (Object.prototype.hasOwnProperty.call(o, k) ? o[k] : undefined);
const STEUER = /[\u0000-\u001f\u007f-\u009f\u200b-\u200f\u2028-\u202e\u2066-\u2069\ufeff]/g;
const text = (v: unknown, max: number): string => (typeof v === "string" ? v.replace(STEUER, "").slice(0, max) : "");

function zahl(o: Obj, key: string, def: number, lo: number, hi: number, fix: string[], pfad: string): number {
  const v = own(o, key);
  if (typeof v !== "number" || !fin(v)) { fix.push(pfad + key); return def; }
  if (v < lo || v > hi) { fix.push(pfad + key); return clamp(v, lo, hi); }
  return v;
}

function bool(o: Obj, key: string, def: boolean, fix: string[], pfad: string): boolean {
  const v = own(o, key);
  if (typeof v === "boolean") return v;
  fix.push(pfad + key);
  return def;
}

/** Begrenzt eine Eingabe auf die Grenzen des Plans. Wirft nie; Fehlendes wird mit Standardwerten gefüllt und in `angepasst` genannt.
 *  Ausnahme für ältere Eingaben: fehlen beim Umlauf `anziehung` oder `masse`, gilt ohne Meldung `false` bzw. 0 (die Felder
 *  bleiben dann weg). Eine Eingabe vom Typ `SimInput` (die fünf P5a-Modelle) gibt eine `SimConfig`. */
export function normalizeSim(input: SimInput): SimConfig;
export function normalizeSim(input: unknown): SimConfigAlle;
export function normalizeSim(input: unknown): SimConfigAlle {
  try {
    return normalisiere(input);
  } catch {
    return normalisiere(null);
  }
}

function normalisiere(input: unknown): SimConfigAlle {
  const fix: string[] = [];
  const src: Obj = isObj(input) ? input : {};
  const m = own(src, "modell");
  const bekannt = typeof m === "string" && (MODELLE_ALLE as readonly string[]).includes(m);
  if (!bekannt) fix.push("modell");
  const rawP = own(src, "parameter");
  const p: Obj = isObj(rawP) ? rawP : {};
  if (!isObj(rawP)) fix.push("parameter");
  const laufzeit = zahl(src, "laufzeit", 30, 5, 60, fix, "");
  let tempo = zahl(src, "tempo", 0, 0, 100, fix, "");
  if (tempo > 0 && tempo < 0.1) { tempo = 0.1; fix.push("tempo"); }
  const spur = bool(src, "spur", true, fix, "");
  const rohB = own(src, "beschreibung"), beschreibung = text(rohB, 400);
  if (rohB !== undefined && rohB !== beschreibung) fix.push("beschreibung");   // gekürzt, Steuerzeichen entfernt oder kein Text
  const basis = { laufzeit, tempo, spur, beschreibung, angepasst: fix, ungueltig: !bekannt };
  const P = "parameter.";
  switch (bekannt ? (m as SimModellAlle) : "pendel") {
    case "pendel":
      return {
        ...basis, modell: "pendel", parameter: {
          laenge: zahl(p, "laenge", 1, 0.05, 100, fix, P), winkel: zahl(p, "winkel", 30, -170, 170, fix, P),
          anfangsgeschwindigkeit: zahl(p, "anfangsgeschwindigkeit", 0, -720, 720, fix, P), daempfung: zahl(p, "daempfung", 0, 0, 5, fix, P),
          g: zahl(p, "g", 9.81, 0.1, 100, fix, P),
        },
      };
    case "feder": {
      const masse = zahl(p, "masse", 1, 0.001, 1000, fix, P);
      let federkonstante = zahl(p, "federkonstante", 10, 0.001, 1e6, fix, P);
      const auslenkung = zahl(p, "auslenkung", 0.5, -10, 10, fix, P), daempfung = zahl(p, "daempfung", 0, 0, 10000, fix, P);
      const T = TAU * Math.sqrt(masse / federkonstante);
      if (!(T >= 0.05 && T <= 1000)) {                                   // Schwingungsdauer zwischen 0,05 und 1000 s
        federkonstante = masse * (TAU / clamp(fin(T) ? T : 1, 0.05, 1000)) ** 2;
        fix.push(P + "federkonstante");
      }
      return { ...basis, modell: "feder", parameter: { masse, federkonstante, auslenkung, daempfung } };
    }
    case "wurf": {
      const parameter: WurfParameter = {
        geschwindigkeit: zahl(p, "geschwindigkeit", 20, 0.1, 1000, fix, P), winkel: zahl(p, "winkel", 45, -90, 90, fix, P),
        hoehe: zahl(p, "hoehe", 0, 0, 10000, fix, P), g: zahl(p, "g", 9.81, 0.1, 100, fix, P),
        luftwiderstand: zahl(p, "luftwiderstand", 0, 0, 1, fix, P),
      };
      // Wie im Schema: aus Höhe 0 muss der Winkel > 0 sein, sonst landet der Körper sofort (keine Bewegung zu zeigen).
      const ungueltig = basis.ungueltig || (parameter.hoehe <= 0 && parameter.winkel <= 0);
      return { ...basis, ungueltig, modell: "wurf", parameter };
    }
    case "umlauf": {
      const zentralmasse = zahl(p, "zentralmasse", 1, 0.01, 100, fix, P);
      const roh = own(p, "koerper");
      const liste: unknown[] = Array.isArray(roh) ? roh.slice(0, 8) : [];
      if (!Array.isArray(roh) || roh.length === 0 || roh.length > 8) fix.push(P + "koerper");
      const koerper: UmlaufKoerper[] = [];
      liste.forEach((k, i) => {
        const pf = `${P}koerper.${i}.`;
        if (!isObj(k)) { fix.push(pf.slice(0, -1)); return; }
        const ph = own(k, "phase");
        if (typeof ph !== "number" || !fin(ph) || ph < 0 || ph > 360) fix.push(pf + "phase");
        const f = own(k, "farbe");
        if (!(FARBEN as readonly unknown[]).includes(f)) fix.push(pf + "farbe");
        const rn = own(k, "name"), name = text(rn, 30);
        if (!name || name !== rn) fix.push(pf + "name");                // fehlt, leer, gekürzt oder Steuerzeichen entfernt
        const q: UmlaufKoerper = {
          name: name || `Körper ${i + 1}`, abstand: zahl(k, "abstand", 1, 0.01, 1000, fix, pf),
          exzentrizitaet: zahl(k, "exzentrizitaet", 0, 0, 0.95, fix, pf),
          phase: typeof ph === "number" && fin(ph) ? ((ph % 360) + 360) % 360 : 0,
          farbe: (FARBEN as readonly unknown[]).includes(f) ? (f as Farbe) : "arc",
        };
        if (own(k, "masse") !== undefined) q.masse = zahl(k, "masse", 0, 0, 0.01, fix, pf);   // P5b; fehlt sie, gilt 0
        koerper.push(q);
      });
      if (!koerper.length) koerper.push({ name: "Körper 1", abstand: 1, exzentrizitaet: 0, phase: 0, farbe: "arc" });
      // Wie im Schema: größte durch kleinste Halbachse ≤ 100 (sonst ist der innere Körper im Bild nicht zu sehen).
      const halbachsen = koerper.map((q) => q.abstand);
      const ungueltig = basis.ungueltig || Math.max(...halbachsen) > 100 * Math.min(...halbachsen);
      const parameter: UmlaufParameter = { zentralmasse, koerper };
      const ra = own(p, "anziehung");                                // P5b; fehlt sie, gilt false
      if (ra !== undefined) {
        parameter.anziehung = typeof ra === "boolean" ? ra : false;
        if (typeof ra !== "boolean") fix.push(P + "anziehung");
      }
      return { ...basis, ungueltig, modell: "umlauf", parameter };
    }
    case "doppelpendel":
      return {
        ...basis, modell: "doppelpendel", parameter: {
          laenge1: zahl(p, "laenge1", 1, 0.05, 100, fix, P), laenge2: zahl(p, "laenge2", 1, 0.05, 100, fix, P),
          masse1: zahl(p, "masse1", 1, 0.01, 1000, fix, P), masse2: zahl(p, "masse2", 1, 0.01, 1000, fix, P),
          winkel1: zahl(p, "winkel1", 90, -180, 180, fix, P), winkel2: zahl(p, "winkel2", 0, -180, 180, fix, P),
          g: zahl(p, "g", 9.81, 0.1, 100, fix, P), daempfung: zahl(p, "daempfung", 0, 0, 5, fix, P),
        },
      };
    case "welle": {
      const roh = own(p, "wellen");
      const liste: unknown[] = Array.isArray(roh) ? roh.slice(0, 3) : [];
      if (!Array.isArray(roh) || roh.length === 0 || roh.length > 3) fix.push(P + "wellen");
      const wellen: Welle[] = [];
      liste.forEach((w, i) => {
        const pf = `${P}wellen.${i}.`;
        if (!isObj(w)) { fix.push(pf.slice(0, -1)); return; }
        const r = own(w, "richtung");
        if (r !== "rechts" && r !== "links") fix.push(pf + "richtung");
        wellen.push({
          amplitude: zahl(w, "amplitude", 1, 0.001, 100, fix, pf), wellenlaenge: zahl(w, "wellenlaenge", 2, 0.01, 1000, fix, pf),
          frequenz: zahl(w, "frequenz", 0.5, 0.01, 100, fix, pf), phase: zahl(w, "phase", 0, 0, 360, fix, pf),
          richtung: r === "links" ? "links" : "rechts",
        });
      });
      if (!wellen.length) wellen.push({ amplitude: 1, wellenlaenge: 2, frequenz: 0.5, phase: 0, richtung: "rechts" });
      let bereich = zahl(p, "bereich", 0, 0, 10000, fix, P);
      if (bereich > 0 && bereich < 0.01) { bereich = 0.01; fix.push(P + "bereich"); }   // 0 = automatisch, sonst 0,01 bis 10 000 m
      // Höchstens 50 kürzeste Wellenlängen (gegeben oder automatisch): sonst zeigen WELLE_PUNKTE Stellen eine falsche, viel
      // längere Welle (Alias). Der Bereich wird gekürzt und in `angepasst` genannt; die Textfassung sagt es.
      const lmin = Math.min(...wellen.map((q) => q.wellenlaenge)), lmax = Math.max(...wellen.map((q) => q.wellenlaenge));
      if ((bereich > 0 ? bereich : 2 * lmax) > WELLE_MAX_LAENGEN * lmin) {
        bereich = WELLE_MAX_LAENGEN * lmin;
        if (!fix.includes(P + "bereich")) fix.push(P + "bereich");
      }
      return { ...basis, modell: "welle", parameter: { wellen, bereich } };
    }
    case "gas": {
      const rohA = zahl(p, "anzahl", 100, 2, GAS_MAX, fix, P), anzahl = Math.round(rohA);
      if (anzahl !== rohA && !fix.includes(P + "anzahl")) fix.push(P + "anzahl");   // keine ganze Zahl: gerundet
      const kr = own(p, "kasten");
      let b = 100, h = 100;
      if (Array.isArray(kr) && kr.length === 2 && typeof kr[0] === "number" && typeof kr[1] === "number" && fin(kr[0]) && fin(kr[1])) {
        b = clamp(kr[0], 1, 1000); h = clamp(kr[1], 1, 1000);
        if (b !== kr[0] || h !== kr[1]) fix.push(P + "kasten");
      } else fix.push(P + "kasten");
      if (h > 10 * b || h < b / 10) { h = clamp(h, b / 10, 10 * b); fix.push(P + "kasten"); }
      const kurz = Math.min(b, h), rv = own(p, "radius");
      let radius = 0.01 * kurz;
      if (typeof rv === "number" && fin(rv) && rv > 0) radius = rv; else fix.push(P + "radius");
      const rMax = Math.min(0.05 * kurz, Math.sqrt((0.3 * b * h) / (Math.PI * anzahl)));   // ≤ 5 % der kurzen Seite, ≤ 30 % Fläche
      if (radius > rMax) { radius = rMax; fix.push(P + "radius"); }
      if (radius < 1e-6 * kurz) { radius = 1e-6 * kurz; fix.push(P + "radius"); }
      const gv = own(p, "geschwindigkeit");                          // jede Zahl > 0 gilt, auch fast null (Teilchen stehen dann)
      let geschwindigkeit = 1;
      if (typeof gv === "number" && fin(gv) && gv > 0) geschwindigkeit = Math.min(gv, 10); else fix.push(P + "geschwindigkeit");
      if (typeof gv === "number" && gv > 10) fix.push(P + "geschwindigkeit");
      const schwerkraft = zahl(p, "schwerkraft", 0, 0, 100, fix, P), stoesse = bool(p, "stoesse", true, fix, P);
      const rohS = zahl(p, "startwert", 1, 0, 2147483647, fix, P), startwert = Math.floor(rohS);
      if (startwert !== rohS && !fix.includes(P + "startwert")) fix.push(P + "startwert");
      return { ...basis, modell: "gas", parameter: { anzahl, kasten: [b, h], radius, geschwindigkeit, schwerkraft, stoesse, startwert } };
    }
  }
}

// --- Hilfen ------------------------------------------------------------------------------------------------------------

/** Ausschnitt mit Rand; zu schmale Seiten werden auf ein Zehntel der langen Seite verbreitert. */
function rahmen(minX: number, maxX: number, minY: number, maxY: number, rand = 0.08): Ausschnitt {
  const s = Math.max(maxX - minX, maxY - minY, 1e-9);
  if (maxX - minX < 0.1 * s) { const c = (minX + maxX) / 2; minX = c - 0.05 * s; maxX = c + 0.05 * s; }
  if (maxY - minY < 0.1 * s) { const c = (minY + maxY) / 2; minY = c - 0.05 * s; maxY = c + 0.05 * s; }
  const m = rand * s;
  return { minX: minX - m, maxX: maxX + m, minY: minY - m, maxY: maxY + m };
}

/** Arithmetisch-geometrisches Mittel (für die Schwingungsdauer bei großem Ausschlag). */
function agm(a: number, b: number): number {
  b = Math.max(b, 1e-12);
  for (let i = 0; i < 40 && Math.abs(a - b) > 1e-15 * a; i++) { const m = (a + b) / 2; b = Math.sqrt(a * b); a = m; }
  return a;
}

/** Langsamste Abklingrate eines überdämpften Schwingers (ζ ≥ 1), ohne Auslöschung gerechnet. */
const langsam = (w0: number, zeta: number): number => w0 / (zeta + Math.sqrt(Math.max(0, zeta * zeta - 1)));

/** Höchstens `max` Punkte: gleichmäßig ausgedünnt, erster, letzter und `halte` bleiben. */
function ausduennen(pts: Pt[], max: number, halte = -1): Pt[] {
  if (pts.length <= max) return pts.slice();
  const schritt = Math.ceil(pts.length / (max - 2));
  const out: Pt[] = [];
  for (let i = 0; i < pts.length; i++) if (i % schritt === 0 || i === pts.length - 1 || i === halte) out.push(pts[i]);
  return out;
}

const kw = (id: string, name: string, wert: number, einheit: string): Kennwert =>
  ({ id, name, wert, einheit, text: `${formatWert(wert)}${einheit ? " " + einheit : ""}` });

// --- Pendel ------------------------------------------------------------------------------------------------------------

/** Energie, die Verlet bis auf Glieder vierter Ordnung genau erhält (modifizierte Energie je m·L²), Nullpunkt unten. */
function pendelEnergie(k: PendelKern, dt: number): number {
  const s = Math.sin(k.th), c = Math.cos(k.th), w2 = k.w2, om = k.om;
  return 0.5 * om * om + w2 * (1 - c) + dt * dt * ((w2 * c * om * om) / 12 - (w2 * w2 * s * s) / 24);
}

/** Verlet; mit Dämpfung ist jeder halbe Stoß die exakte Lösung von ω' = a − c·ω bei festem a (ω·e^(−c·dt/2) + a·(1 − e^(−c·dt/2))/c).
 *  Damit braucht der Schritt keine Grenze aus der Dämpfung: bei starker Dämpfung kriecht das Pendel mit der richtigen Rate
 *  (ω → a/c), statt dass ein kleiner Schritt die Zeit auf Zeitlupe bremst. Ohne Dämpfung genau das ungedämpfte Verlet. */
function pendelSchritt(k: PendelKern, dt: number): void {
  const h = 0.5 * dt, g = k.c > 0 ? -Math.expm1(-k.c * h) / k.c : h;
  k.om = k.damp * k.om + g * k.a;
  k.th += dt * k.om;
  if (k.th > Math.PI || k.th < -Math.PI) k.th -= TAU * Math.round(k.th / TAU);
  k.a = -k.w2 * Math.sin(k.th);
  k.om = k.damp * k.om + g * k.a;
}

interface Teile { kern: SimKern; dt: number; periode: number; ausschnitt: Ausschnitt; text: string; koerper: number; einheit: "s" | "Jahre"; voraus: number }

function pendelTeile(p: PendelParameter): Teile {
  const L = p.laenge, w2 = p.g / L, w0 = Math.sqrt(w2), T0 = TAU / w0, c = p.daempfung;
  const th = p.winkel * RAD, om = p.anfangsgeschwindigkeit * RAD;
  const E = 0.5 * om * om + w2 * (1 - Math.cos(th)), wb = Math.sqrt(2 * E);
  let dt = T0 / 1000;                                                // Schritt nur aus der Schwingung; die Dämpfung ist exakt
  if (wb > 0) dt = Math.min(dt, TAU / (1000 * wb));
  const rotiert = E >= 2 * w2;
  const thMax = rotiert ? Math.PI : Math.acos(clamp(1 - E / w2, -1, 1));
  let Tm = rotiert ? (2 * TAU) / (wb + Math.sqrt(Math.max(0, 2 * E - 4 * w2))) : T0 / agm(1, Math.cos(thMax / 2));
  if (!(Tm > 0 && Tm <= 20 * T0)) Tm = 20 * T0;
  const zeta = c / (2 * w0);
  const kern: PendelKern = { art: "pendel", L, w2, c, damp: Math.exp((-c * dt) / 2), th, om, a: -w2 * Math.sin(th), E0: 0, T0, Tm, rotiert };
  kern.E0 = pendelEnergie(kern, dt);
  let ausschnitt: Ausschnitt;
  if (thMax >= Math.PI / 2) ausschnitt = rahmen(-L, L, -L, rotiert ? L : Math.max(0, -L * Math.cos(thMax)));
  else { const hw = L * Math.sin(thMax); ausschnitt = rahmen(-hw, hw, -L, 0); }
  const teile = [`Pendel, Länge ${formatZahl(L)} m`, `Start bei ${formatZahl(p.winkel)} Grad`];
  if (om !== 0) teile.push(`Startgeschwindigkeit ${formatZahl(p.anfangsgeschwindigkeit)} Grad pro Sekunde`);
  teile.push(c > 0 ? `Dämpfung ${formatZahl(c)} pro Sekunde` : "ohne Dämpfung");
  if (p.g !== 9.81) teile.push(`Fallbeschleunigung ${formatZahl(p.g)} m/s²`);
  let satz = `${teile.join(", ")}. Schwingungsdauer${c > 0 ? " ohne Dämpfung" : ""} etwa ${formatWert(T0)} s.`;
  if (rotiert) satz += " Das Pendel überschlägt sich.";
  else if (formatWert(Tm) !== formatWert(T0)) satz += ` Bei diesem Ausschlag dauert eine Schwingung etwa ${formatWert(Tm)} s.`;
  if (zeta >= 1) satz += " Die Dämpfung ist so stark, dass das Pendel nicht schwingt, sondern langsam zurückkriecht.";
  return { kern, dt, periode: zeta < 1 ? Tm : 2 / langsam(w0, zeta), ausschnitt, text: satz, koerper: 1, einheit: "s", voraus: 0 };
}

// --- Feder -------------------------------------------------------------------------------------------------------------

/** Energie ½mv² + ½kx²; der exakte Schritt erhält sie ohne Dämpfung und lässt sie mit Dämpfung nur fallen. */
const federEnergie = (k: FederKern): number => 0.5 * k.m * k.v * k.v + 0.5 * k.k * k.x * k.x;

/** Exakter Übergang des gedämpften Schwingers x'' = −ω0²x − c·x' über dt, für jede Dämpfung ohne Überlauf und ohne Auslöschung:
 *  e^(−a·dt)·[[C + a·S, S], [−ω0²·S, C − a·S]] mit a = c/2, C = cos/cosh, S = sin/sinh geteilt durch die Kreisfrequenz. Stark
 *  überdämpft über die beiden reinen Abklingraten (langsam e^(−ω0²/(a+κ)·dt), schnell e^(−(a+κ)·dt)). */
function federMatrix(w0: number, c: number, dt: number): [number, number, number, number] {
  const a = c / 2, w2 = w0 * w0, ed = Math.exp(-a * dt);
  let C: number, S: number;
  if (a < w0) {                                                      // schwingt (ohne Dämpfung: reine Drehung)
    const q = Math.sqrt((w0 - a) * (w0 + a)), z = q * dt;
    C = ed * Math.cos(z); S = ed * (z > 1e-8 ? Math.sin(z) / q : dt);
  } else {
    const kap = Math.sqrt((a - w0) * (a + w0)), z = kap * dt;
    if (z < 1) { C = ed * Math.cosh(z); S = ed * (z > 1e-8 ? Math.sinh(z) / kap : dt); }
    else {
      const e1 = Math.exp((-w2 / (a + kap)) * dt), e2 = Math.exp(-(a + kap) * dt), d = -w2 / (a + kap);   // d = κ − a ohne Auslöschung
      return [(e1 * (kap + a) + e2 * d) / (2 * kap), (e1 - e2) / (2 * kap), (-w2 * (e1 - e2)) / (2 * kap), (e1 * d + e2 * (kap + a)) / (2 * kap)];
    }
  }
  return [C + a * S, S, -w2 * S, C - a * S];
}

function federSchritt(k: FederKern, dt: number): void {
  if (k.pxx === undefined || k.pxv === undefined || k.pvx === undefined || k.pvv === undefined) {
    [k.pxx, k.pxv, k.pvx, k.pvv] = federMatrix(Math.sqrt(k.w2), k.c, dt);
  }
  const x = k.x, v = k.v;
  k.x = k.pxx * x + k.pxv * v;
  k.v = k.pvx * x + k.pvv * v;
  k.a = -k.w2 * k.x - k.c * k.v;
}

function federTeile(p: FederParameter): Teile {
  const m = p.masse, kk = p.federkonstante, w2 = kk / m, w0 = Math.sqrt(w2), T = TAU / w0, c = p.daempfung / m, A = p.auslenkung;
  const zeta = c / (2 * w0), S = Math.abs(A) > 0 ? Math.abs(A) : 1;
  // Schritt aus der Bewegung allein: eine Schwingung, überdämpft das langsame Zurückkriechen; die Dämpfung steckt exakt im Schritt.
  const dt = (zeta < 1 ? T : Math.max(T, 2 / langsam(w0, zeta))) / 1000;
  const [pxx, pxv, pvx, pvv] = federMatrix(w0, c, dt);
  const kern: FederKern = {
    art: "feder", m, k: kk, w2, c, damp: Math.exp((-c * dt) / 2), x: A, v: 0, a: -w2 * A, E0: 0, T, S, zeta, pxx, pxv, pvx, pvv,
  };
  kern.E0 = federEnergie(kern);
  let satz = `Federpendel, Masse ${formatZahl(m)} kg, Federkonstante ${formatZahl(kk)} N/m, Auslenkung ${formatZahl(A)} m, `
    + `${p.daempfung > 0 ? `Dämpfung ${formatZahl(p.daempfung)} kg/s` : "ohne Dämpfung"}. `
    + `Schwingungsdauer${p.daempfung > 0 ? " ohne Dämpfung" : ""} etwa ${formatWert(T)} s.`;
  if (zeta >= 1) satz += " Die Dämpfung ist so stark, dass die Masse nicht schwingt, sondern langsam zurückkriecht.";
  return {
    kern, dt, periode: zeta < 1 ? T : 2 / langsam(w0, zeta), ausschnitt: rahmen(-2 * S, S, -0.3 * S, 0.3 * S), text: satz,
    koerper: 1, einheit: "s", voraus: 0,
  };
}

// --- Wurf --------------------------------------------------------------------------------------------------------------

/** Ein fester Schritt mit Luftwiderstand ab Zeit t: halber Stoß der Schwerkraft, dann Flug mit Bremsung über dt (exakt entlang v:
 *  |v| = s/(1 + k·s·t), Weg ln(1 + k·s·dt)/k), dann wieder halber Stoß. Ohne Luftwiderstand exakt die Parabel, ohne Schwerkraft
 *  exakt die Bremsung; unbedingt stabil. Fällt der Körper unter den Boden, wird der Aufprall in diesem Schritt linear eingepasst. */
function wurfSchritt(k: WurfKern, dt: number, t: number): void {
  const g = k.g, hd = dt / 2, x0 = k.x, y0 = k.y, vx0 = k.vx, vy0 = k.vy;
  let x = x0, y = y0, vx = vx0, vy = vy0 - g * hd;
  const s = Math.hypot(vx, vy);
  if (s > 0) {
    const q = k.kd * s * dt, weg = Math.log1p(q) / k.kd;
    x += (vx / s) * weg; y += (vy / s) * weg; vx /= 1 + q; vy /= 1 + q;
  }
  vy -= g * hd;
  if (y < 0) {
    const f = y0 > 0 ? y0 / (y0 - y) : 0;
    x = x0 + f * (x - x0); vx = vx0 + f * (vx - vx0); vy = vy0 + f * (vy - vy0); y = 0;
    k.gelandet = true; k.landezeit = t + f * dt;
  }
  k.x = x; k.y = y; k.vx = vx; k.vy = vy;
}

/** Geschlossene Lösung ohne Luftwiderstand zur Zeit t; ab der Flugzeit am Aufprallpunkt. */
function wurfAuswerten(k: WurfKern, t: number): void {
  if (t >= k.flugzeit) {
    k.x = k.reichweite; k.y = 0; k.vx = k.v0x; k.vy = k.v0y - k.g * k.flugzeit; k.gelandet = true; k.landezeit = k.flugzeit;
    return;
  }
  k.x = k.v0x * t; k.y = k.h + k.v0y * t - 0.5 * k.g * t * t; k.vx = k.v0x; k.vy = k.v0y - k.g * t;
}

function wurfTeile(p: WurfParameter, budget: number): Teile {
  const g = p.g, kd = p.luftwiderstand, h = p.hoehe, a = p.winkel * RAD;
  const v0x = Math.max(0, p.geschwindigkeit * Math.cos(a)), v0y = p.geschwindigkeit * Math.sin(a);
  const wurzel = Math.sqrt(v0y * v0y + 2 * g * h);                    // nach unten ohne Auslöschung: 2h / (√… − v0y)
  const Tfrei = h <= 0 && v0y <= 0 ? 0 : v0y > 0 ? (v0y + wurzel) / g : (2 * h) / (wurzel - v0y);
  const kern: WurfKern = {
    art: "wurf", g, kd, geschlossen: kd === 0, v0x, v0y, h, x: 0, y: h, vx: v0x, vy: v0y, flugzeit: Tfrei, reichweite: v0x * Tfrei,
    gipfel: h + (v0y > 0 ? (v0y * v0y) / (2 * g) : 0), gipfelX: v0y > 0 ? (v0x * v0y) / g : 0, gelandet: Tfrei <= 0, landezeit: 0,
    vollstaendig: true, bahn: [],
  };
  let dt = Tfrei > 0 ? Math.max(Tfrei / 1000, 1e-12) : 1e-3, voraus = 0;   // Untergrenze: winzige Flüge (Höhe 1e-320) landen im ersten Schritt
  if (!kern.geschlossen) {
    dt = Math.max(1e-12, Math.min(Tfrei > 0 ? Tfrei / 400 : Infinity, 1 / (5 * Math.sqrt(g * kd))));
    if (!(dt > 0 && fin(dt))) dt = 1e-3;
    if (!kern.gelandet) {                                         // Vorausrechnung mit demselben Schritt wie im Lauf
      const sim: WurfKern = { ...kern, bahn: [] }, pts: Pt[] = [[0, h]];
      let n = 0, top = 0;
      while (!sim.gelandet && n < budget) {
        wurfSchritt(sim, dt, n * dt);
        n++;
        if (!fin(sim.x) || !fin(sim.y)) break;
        pts.push([sim.x, sim.y]);
        if (sim.y > pts[top][1]) top = pts.length - 1;
      }
      voraus = n;
      kern.vollstaendig = sim.gelandet;
      kern.flugzeit = sim.gelandet ? sim.landezeit : n * dt;
      kern.reichweite = sim.x; kern.gipfel = pts[top][1]; kern.gipfelX = pts[top][0];
      kern.bahn = ausduennen(pts, SPUR_MAX, top);
    }
  }
  const maxX = Math.max(kern.reichweite, kern.gipfelX, 0);
  const satz = `Wurf mit ${formatZahl(p.geschwindigkeit)} m/s unter ${formatZahl(p.winkel)} Grad aus ${formatZahl(h)} m Höhe, `
    + `${kd > 0 ? `Luftwiderstand ${formatZahl(kd)} pro m` : "ohne Luftwiderstand"}`
    + `${g !== 9.81 ? `, Fallbeschleunigung ${formatZahl(g)} m/s²` : ""}. `
    + `Reichweite etwa ${formatWert(kern.reichweite)} m, Gipfelhöhe etwa ${formatWert(kern.gipfel)} m, `
    + `Flugzeit ${kern.vollstaendig ? "etwa" : "über"} ${formatWert(kern.flugzeit)} s.`;
  return {
    kern, dt, periode: kern.flugzeit, ausschnitt: rahmen(0, maxX, 0, Math.max(kern.gipfel, 0), 0.05), text: satz, koerper: 1, einheit: "s", voraus,
  };
}

// --- Umlauf ------------------------------------------------------------------------------------------------------------

/** Löst die Kepler-Gleichung E − e·sin E = M nach E: Newton mit Einschluss [M − e, M + e] und Halbierung als Rückfall,
 *  höchstens 60 Durchläufe. Ergebnis zu M, auf [0, 2π) gebracht. */
export function solveKepler(M: number, e: number): number {
  if (!fin(M) || !fin(e)) return 0;
  e = clamp(e, 0, 0.999999);
  const m = M - TAU * Math.floor(M / TAU);
  let lo = m - e, hi = m + e;
  let E = clamp(m + e * Math.sin(m), lo, hi);
  for (let i = 0; i < 60; i++) {
    const f = E - e * Math.sin(E) - m;
    if (Math.abs(f) < 1e-15) break;
    if (f > 0) hi = E; else lo = E;
    let En = E - f / (1 - e * Math.cos(E));
    if (!(En > lo && En < hi)) En = 0.5 * (lo + hi);
    if (Math.abs(En - E) < 1e-15) { E = En; break; }
    E = En;
  }
  return E;
}

function umlaufStellen(k: UmlaufKern, t: number): void {
  for (const b of k.bahnen) {
    const u = t / b.P;
    b.E = solveKepler(b.M0 + TAU * (u - Math.floor(u)), b.e);
  }
}

function umlaufTeile(p: UmlaufParameter): Teile {
  const M = p.zentralmasse;
  const bahnen: UmlaufBahn[] = p.koerper.map((q) => {
    const a = q.abstand, e = q.exzentrizitaet, nu = q.phase * RAD;
    const E0 = 2 * Math.atan2(Math.sqrt(1 - e) * Math.sin(nu / 2), Math.sqrt(1 + e) * Math.cos(nu / 2));
    return { name: q.name, farbe: q.farbe, a, e, b: a * Math.sqrt(1 - e * e), P: Math.sqrt((a * a * a) / M), M0: E0 - e * Math.sin(E0), E: 0 };
  });
  const kern: UmlaufKern = { art: "umlauf", M, bahnen };
  umlaufStellen(kern, 0);
  const Pmin = Math.min(...bahnen.map((b) => b.P));
  let minX = 0, maxX = 0, minY = 0, maxY = 0;
  for (const b of bahnen) {
    minX = Math.min(minX, -b.a * (1 + b.e)); maxX = Math.max(maxX, b.a * (1 - b.e)); minY = Math.min(minY, -b.b); maxY = Math.max(maxY, b.b);
  }
  const satz = `Umlaufbahnen um eine Zentralmasse von ${formatZahl(M)} ${M === 1 ? "Sonnenmasse" : "Sonnenmassen"}, `
    + `${bahnen.length} Körper, ohne gegenseitige Anziehung. `
    + bahnen.map((b) => `${b.name}: große Halbachse ${formatZahl(b.a)} AE, Exzentrizität ${formatZahl(b.e)}, `
      + `Umlaufzeit etwa ${formatWert(b.P)} Jahre, kleinster Abstand ${formatWert(b.a * (1 - b.e))} AE.`).join(" ");
  return { kern, dt: Pmin / 1000, periode: Pmin, ausschnitt: rahmen(minX, maxX, minY, maxY, 0.06), text: satz, koerper: bahnen.length, einheit: "Jahre", voraus: 0 };
}

// --- Gas ---------------------------------------------------------------------------------------------------------------

/** Spiegelt an den Wänden. Mit Schwerkraft wird die senkrechte Geschwindigkeit so gesetzt, dass ½v² + g·y gleich bleibt (die
 *  gespiegelte Lage liegt höher oder tiefer als die durchgerechnete; ohne Ausgleich gewönne jedes Teilchen bei jedem Bodenstoß
 *  Energie). Reicht die Energie am Boden nicht für die Spiegelung, steigt das Teilchen nur so hoch, wie die Energie trägt. */
function gasWand(k: GasKern, i: number): void {
  const r = k.r, bx = k.b - r, by = k.h - r, g = k.g;
  let x = k.px[i], y = k.py[i];
  if (x < r) { x = Math.min(2 * r - x, bx); k.vx[i] = Math.abs(k.vx[i]); }
  else if (x > bx) { x = Math.max(2 * bx - x, r); k.vx[i] = -Math.abs(k.vx[i]); }
  if (y < r) {
    const vy = k.vy[i], yn = Math.min(2 * r - y, by);
    if (g > 0) {
      const q = vy * vy - 2 * g * (yn - y);
      if (q >= 0) { k.vy[i] = Math.sqrt(q); y = yn; }
      else { y = Math.min(Math.max(r, y + (vy * vy) / (2 * g)), by); k.vy[i] = 0; }
    } else { y = yn; k.vy[i] = Math.abs(vy); }
  } else if (y > by) {
    const vy = k.vy[i], yn = Math.max(2 * by - y, r);
    k.vy[i] = g > 0 ? -Math.sqrt(vy * vy + 2 * g * (y - yn)) : -Math.abs(vy);
    y = yn;
  }
  k.px[i] = x; k.py[i] = y;
}

/** Elastische Stöße gleicher Massen, gefunden über ein gleichmäßiges Raster (Zelle ≥ Durchmesser, halbe Nachbarschaft). Die Arbeit
 *  je Teilschritt ist O(N + Zellen), die Zellenzahl ist ≤ 4·N + 16 (siehe `gasKern`); besucht werden nur Zellen mit Teilchen, in
 *  derselben Reihenfolge wie ein Lauf über alle Zellen. */
function gasStoesse(k: GasKern): void {
  const { N, nx, ny, px, py, vx, vy, zelle, zaehler, zeiger, folge } = k;
  const cw = k.b / nx, ch = k.h / ny, nZ = nx * ny, d2 = 4 * k.r * k.r, dd = 2 * k.r;
  zaehler.fill(0);
  for (let i = 0; i < N; i++) {
    const cx = clamp(Math.floor(px[i] / cw), 0, nx - 1), cy = clamp(Math.floor(py[i] / ch), 0, ny - 1);
    const z = (cx || 0) + (cy || 0) * nx;
    zelle[i] = z; zaehler[z + 1]++;
  }
  for (let z = 0; z < nZ; z++) zaehler[z + 1] += zaehler[z];
  zeiger.set(zaehler.subarray(0, nZ));
  for (let i = 0; i < N; i++) folge[zeiger[zelle[i]]++] = i;
  const paar = (i: number, j: number): void => {
    const dx = px[j] - px[i], dy = py[j] - py[i], q = dx * dx + dy * dy;
    if (q >= d2) return;
    const d = Math.sqrt(q);
    const ux = d > 1e-12 * dd ? dx / d : 1, uy = d > 1e-12 * dd ? dy / d : 0;
    const rel = (vx[j] - vx[i]) * ux + (vy[j] - vy[i]) * uy;
    if (rel < 0) { vx[i] += rel * ux; vy[i] += rel * uy; vx[j] -= rel * ux; vy[j] -= rel * uy; }
    const s = (dd - d) / 2;
    px[i] -= ux * s; py[i] -= uy * s; px[j] += ux * s; py[j] += uy * s;
  };
  const mitZelle = (i: number, cx: number, cy: number): void => {
    if (cx < 0 || cx >= nx || cy >= ny) return;
    const z = cx + cy * nx;
    for (let b = zaehler[z]; b < zaehler[z + 1]; b++) paar(i, folge[b]);
  };
  for (let a = 0; a < N; a++) {                                     // `folge` ist nach Zellen sortiert
    const i = folge[a], z = zelle[i], s1 = zaehler[z + 1], cy = Math.floor(z / nx), cx = z - cy * nx;
    for (let b = a + 1; b < s1; b++) paar(i, folge[b]);
    mitZelle(i, cx + 1, cy); mitZelle(i, cx - 1, cy + 1); mitZelle(i, cx, cy + 1); mitZelle(i, cx + 1, cy + 1);
  }
}

function gasSchritt(k: GasKern, dt: number): void {
  const g = k.g, gd = 0.5 * g * dt * dt, { N, px, py, vx, vy } = k;
  for (let i = 0; i < N; i++) {
    px[i] += vx[i] * dt; py[i] += vy[i] * dt - gd; vy[i] -= g * dt;
    gasWand(k, i);
  }
  if (k.stoesse) {
    gasStoesse(k);
    for (let i = 0; i < N; i++) gasWand(k, i);
  }
}

function gasKern(p: GasParameter): GasKern {
  const N = Math.round(clamp(p.anzahl, 2, GAS_MAX)), [b, h] = p.kasten, rng = mulberry32(p.startwert);
  let r = p.radius, rKleiner = false;
  const px = new Float64Array(N), py = new Float64Array(N), vx = new Float64Array(N), vy = new Float64Array(N);
  const lim = 4 * r * r * (1 + 1e-9);
  let n = 0;
  for (let versuch = 0; n < N && versuch < 60 * N; versuch++) {   // Startlagen ohne Überlappung, begrenzte Versuche
    const x = r + (b - 2 * r) * rng(), y = r + (h - 2 * r) * rng();
    let frei = true;
    for (let j = 0; j < n && frei; j++) { const dx = px[j] - x, dy = py[j] - y; frei = dx * dx + dy * dy >= lim; }
    if (frei) { px[n] = x; py[n] = y; n++; }
  }
  if (n < N) {                                                       // Rückfall: Gitter, Radius notfalls kleiner
    const cols = Math.max(1, Math.ceil(Math.sqrt((N * b) / h))), rows = Math.ceil(N / cols), sx = b / cols, sy = h / rows;
    if (r > 0.45 * Math.min(sx, sy)) { r = 0.45 * Math.min(sx, sy); rKleiner = true; }
    for (let i = 0; i < N; i++) { px[i] = ((i % cols) + 0.5) * sx; py[i] = (Math.floor(i / cols) + 0.5) * sy; }
  }
  const v0 = p.geschwindigkeit * b;
  for (let i = 0; i < N; i++) { const w = TAU * rng(); vx[i] = v0 * Math.cos(w); vy[i] = v0 * Math.sin(w); }
  const g = p.schwerkraft, vref = Math.sqrt(v0 * v0 + 2 * g * Math.max(0, h - 2 * r));
  // Raster: Zelle ≥ Durchmesser (kein Stoß geht verloren) und höchstens 4·N + 16 Zellen, damit Leeren und Aufsummieren je
  // Teilschritt mit der Teilchenzahl wächst (sonst kosten 2 Teilchen mit winzigem Radius 64 x 64 Zellen je Teilschritt).
  const seite = Math.max(2 * r, Math.sqrt((b * h) / (4 * N + 16)));
  const nx = clamp(Math.floor(b / seite), 1, 64), ny = clamp(Math.floor(h / seite), 1, 64);
  const start = new Float64Array(4 * N);
  start.set(px, 0); start.set(py, N); start.set(vx, 2 * N); start.set(vy, 3 * N);
  return {
    art: "gas", N, b, h, r, g, stoesse: p.stoesse, v0, vref, vmax: 3 * vref, px, py, vx, vy, start, nx, ny,
    zelle: new Int32Array(N), zaehler: new Int32Array(nx * ny + 1), zeiger: new Int32Array(nx * ny), folge: new Int32Array(N), rKleiner,
  };
}

/** Frische Kopie des Startzustands (für das Standbild, ohne den laufenden Zustand zu berühren). */
function gasKopie(k: GasKern): GasKern {
  const N = k.N, s = k.start;
  return {
    ...k, px: s.slice(0, N), py: s.slice(N, 2 * N), vx: s.slice(2 * N, 3 * N), vy: s.slice(3 * N, 4 * N),
    zelle: new Int32Array(N), zaehler: new Int32Array(k.nx * k.ny + 1), zeiger: new Int32Array(k.nx * k.ny), folge: new Int32Array(N),
  };
}

function gasVerteilung(k: GasKern): Verteilung {
  const anzahl = new Array<number>(10).fill(0), w = k.vmax > 0 ? k.vmax : 1;
  for (let i = 0; i < k.N; i++) {
    const s = Math.hypot(k.vx[i], k.vy[i]);
    anzahl[fin(s) ? clamp(Math.floor((s / w) * 10), 0, 9) : 9]++;
  }
  return { grenzen: Array.from({ length: 11 }, (_, i) => (w * i) / 10), anzahl };
}

function gasTeile(p: GasParameter): Teile {
  const kern = gasKern(p), { b, h, r } = kern;
  // Teilschritt: höchstens ein halber Radius bei der Bezugsgeschwindigkeit (Start plus Fallhöhe), höchstens 1/240 s. Keine
  // Untergrenze: ist der Schritt für das Tempo zu klein, greift die Grenze je Bild und die Zeit läuft langsamer (Zeitlupe),
  // statt Stöße zu verlieren. Der Radius ist ≥ 1e-6 der kurzen Seite, darum bleibt der Schritt > 0.
  const dt = kern.vref > 0 ? Math.min(1 / 240, (0.5 * r) / kern.vref) : 1 / 240;
  const satz = `Gas im Kasten ${formatZahl(b)} mal ${formatZahl(h)} Einheiten mit ${kern.N} Teilchen, Radius ${formatZahl(r)}, `
    + `Startgeschwindigkeit ${formatZahl(p.geschwindigkeit)} Kastenbreiten pro Sekunde in zufälliger Richtung (Startwert ${p.startwert}), `
    + `${kern.g > 0 ? `Schwerkraft ${formatZahl(kern.g)}` : "ohne Schwerkraft"}, ${kern.stoesse ? "mit Stößen" : "ohne Stöße"}. `
    + `Alle Teilchen starten mit ${formatWert(kern.v0)} Einheiten pro Sekunde.`;
  return { kern, dt, periode: 1, ausschnitt: { minX: 0, maxX: b, minY: 0, maxY: h }, text: satz, koerper: kern.N, einheit: "s", voraus: 0 };
}

// --- Doppelpendel ------------------------------------------------------------------------------------------------------

let DA1 = 0, DA2 = 0;                // Ergebnis von `dpBeschl` (ohne Speicher je Aufruf)

/** Winkelbeschleunigungen des ungedämpften Doppelpendels (die üblichen Bewegungsgleichungen, Winkel aus der Senkrechten). */
function dpBeschl(k: DoppelpendelKern, t1: number, w1: number, t2: number, w2: number): void {
  const d = t1 - t2, sd = Math.sin(d), cd = Math.cos(d), m1 = k.m1, m2 = k.m2, M = m1 + m2, g = k.g;
  const nenner = 2 * (m1 + m2 * sd * sd);                           // = 2·m1 + m2 − m2·cos(2Δ), immer ≥ 2·m1 > 0
  DA1 = (-g * (2 * m1 + m2) * Math.sin(t1) - m2 * g * Math.sin(t1 - 2 * t2) - 2 * sd * m2 * (w2 * w2 * k.L2 + w1 * w1 * k.L1 * cd)) / (k.L1 * nenner);
  DA2 = (2 * sd * (w1 * w1 * k.L1 * M + g * M * Math.cos(t1) + w2 * w2 * k.L2 * m2 * cd)) / (k.L2 * nenner);
}

/** Ein Runge-Kutta-Schritt vierter Ordnung über h ohne Dämpfung; die Beschleunigung am Anfang (a1, b1) ist schon gerechnet. */
function dpRk4(k: DoppelpendelKern, h: number, a1: number, b1: number): void {
  const t1 = k.th1, w1 = k.om1, t2 = k.th2, w2 = k.om2, hh = 0.5 * h;
  const t1b = t1 + hh * w1, w1b = w1 + hh * a1, t2b = t2 + hh * w2, w2b = w2 + hh * b1;
  dpBeschl(k, t1b, w1b, t2b, w2b);
  const a2 = DA1, b2 = DA2, t1c = t1 + hh * w1b, w1c = w1 + hh * a2, t2c = t2 + hh * w2b, w2c = w2 + hh * b2;
  dpBeschl(k, t1c, w1c, t2c, w2c);
  const a3 = DA1, b3 = DA2, t1d = t1 + h * w1c, w1d = w1 + h * a3, t2d = t2 + h * w2c, w2d = w2 + h * b3;
  dpBeschl(k, t1d, w1d, t2d, w2d);
  const a4 = DA1, b4 = DA2, s = h / 6;
  k.th1 = t1 + s * (w1 + 2 * w1b + 2 * w1c + w1d); k.th2 = t2 + s * (w2 + 2 * w2b + 2 * w2c + w2d);
  k.om1 = w1 + s * (a1 + 2 * a2 + 2 * a3 + a4); k.om2 = w2 + s * (b1 + 2 * b2 + 2 * b3 + b4);
}

/** Höchstens so viel Winkel (rad) je Teilschritt, gemessen an der schnellsten Bewegung des Zustands. */
const DP_ETA = TAU / 500;

/** Ein Rasterschritt dt: halbe Dämpfung exakt (ω·e^(−c·dt/2); entspricht der Reibungskraft −c·M(θ)·ω, die Energie fällt dabei
 *  nur), dann Runge-Kutta vierter Ordnung ohne Dämpfung in Teilschritten, wieder halbe Dämpfung; Winkel danach auf (−π, π].
 *  Teilschritte: jeder höchstens DP_ETA / Rate des Zustands an seinem Anfang, Rate = größte von |ω1| + |ω2| + ω_schnell,
 *  |ω1 − ω2| / r und √(|α1| + |α2|) mit r = √((m1 + m2·sin²Δ)/(m1 + m2)). Bei leichtem oberem Körper und fast gestreckten
 *  Armen (r klein) wird die Massenmatrix fast singulär, der Körper „peitscht“ in sehr kurzer Zeit durch; das fangen die
 *  Teilschritte ab, ohne das Raster zu ändern. Sie hängen nur vom Zustand ab: gleiche Eingabe, gleiche Zahlen, für jede
 *  Bildrate. Höchstens `kmax` Teilschritte (dann nimmt der letzte den Rest). Gibt die Zahl der Teilschritte zurück. */
function dpSchritt(k: DoppelpendelKern, dt: number): number {
  if (k.c > 0) { k.om1 *= k.damp; k.om2 *= k.damp; }
  const M = k.m1 + k.m2;
  let rest = dt, n = 0;
  while (rest > 0) {
    dpBeschl(k, k.th1, k.om1, k.th2, k.om2);
    const a1 = DA1, b1 = DA2, sd = Math.sin(k.th1 - k.th2), r = Math.sqrt((k.m1 + k.m2 * sd * sd) / M);
    const rate = Math.max(Math.abs(k.om1) + Math.abs(k.om2) + k.wRef, Math.abs(k.om1 - k.om2) / r, Math.sqrt(Math.abs(a1) + Math.abs(b1)));
    let h = DP_ETA / rate;
    if (!(h < rest) || n >= k.kmax - 1) h = rest;
    else if (h > 0.5 * rest) h = 0.5 * rest;                         // kein winziger Rest am Ende des Rasterschritts
    dpRk4(k, h, a1, b1);
    rest = h === rest ? 0 : rest - h;
    n++;
  }
  if (k.th1 > Math.PI || k.th1 < -Math.PI) k.th1 -= TAU * Math.round(k.th1 / TAU);
  if (k.th2 > Math.PI || k.th2 < -Math.PI) k.th2 -= TAU * Math.round(k.th2 / TAU);
  if (k.c > 0) { k.om1 *= k.damp; k.om2 *= k.damp; }
  return n;
}

/** Energie in J, Nullpunkt der Lage ganz unten (beide Arme senkrecht nach unten), darum nie negativ. 1 − cos θ = 2·sin²(θ/2). */
function dpEnergie(k: DoppelpendelKern): number {
  const { L1, L2, m1, m2, g, om1, om2 } = k, s1 = Math.sin(k.th1 / 2), s2 = Math.sin(k.th2 / 2);
  return 0.5 * (m1 + m2) * L1 * L1 * om1 * om1 + 0.5 * m2 * L2 * L2 * om2 * om2 + m2 * L1 * L2 * om1 * om2 * Math.cos(k.th1 - k.th2)
    + 2 * (m1 + m2) * g * L1 * s1 * s1 + 2 * m2 * g * L2 * s2 * s2;
}

/** Kreisfrequenzen² der beiden Eigenschwingungen bei kleinen Ausschlägen: Nullstellen von
 *  m1·L1·L2·x² − (m1+m2)·g·(L1+L2)·x + (m1+m2)·g² (ohne Auslöschung gerechnet). [langsam, schnell]. */
export function doppelpendelEigen(L1: number, L2: number, m1: number, m2: number, g: number): [number, number] {
  const M = m1 + m2, B = M * g * (L1 + L2);
  const wurzel = g * Math.sqrt(M * (m1 * (L1 - L2) ** 2 + m2 * (L1 + L2) ** 2));
  return [(2 * M * g * g) / (B + wurzel), (B + wurzel) / (2 * m1 * L1 * L2)];
}

function doppelpendelTeile(p: DoppelpendelParameter): Teile {
  const { laenge1: L1, laenge2: L2, masse1: m1, masse2: m2, g, daempfung: c } = p, M = m1 + m2, R = L1 + L2;
  const [x1, x2] = doppelpendelEigen(L1, L2, m1, m2, g);
  const Tlangsam = TAU / Math.sqrt(x1), Tschnell = TAU / Math.sqrt(x2);
  const kern: DoppelpendelKern = {
    art: "doppelpendel", L1, L2, m1, m2, g, c, damp: 1, th1: p.winkel1 * RAD, om1: 0, th2: p.winkel2 * RAD, om2: 0, E0: 0, Tlangsam, Tschnell,
    // Teilschritte je Rasterschritt: ohne Peitschen höchstens etwa 3, beim Peitschen etwa 2/r (r ≥ √(m1/(m1+m2))); Obergrenze 1024.
    wRef: TAU / Tschnell, kmax: Math.min(1024, Math.ceil(4 / Math.sqrt(m1 / M)) + 8),
  };
  const E = dpEnergie(kern);
  // Schritt aus der schnellen Eigenschwingung (/2000), dazu eine Grenze aus der Energie: |ω| ≤ √(2E/λmin) mit der kleinsten
  // Eigenzahl der Massenmatrix λmin ≥ det/Spur ≥ m1·m2·L1²·L2² / ((m1+m2)·L1² + m2·L2²). So bleibt ein schnelles Überschlagen
  // genau (höchstens 2π/500 rad je Schritt bei der größten möglichen Winkelgeschwindigkeit).
  let dt = Tschnell / 2000;
  const lmin = (m1 * m2 * L1 * L1 * L2 * L2) / (M * L1 * L1 + m2 * L2 * L2), wmax = Math.sqrt((2 * E) / lmin);
  if (wmax > 0 && fin(wmax)) dt = Math.min(dt, TAU / (500 * wmax));
  kern.damp = Math.exp((-c * dt) / 2);
  kern.E0 = E;
  // Höchste erreichbare Lagen aus der Energie (V = m1·g·(y1 + L1) + m2·g·(y2 + L1 + L2) ≤ E), dazu die Startlagen.
  const y1 = -L1 * Math.cos(kern.th1), y2 = y1 - L2 * Math.cos(kern.th2);
  const oben = Math.max(0, y1, y2, Math.min(L1, E / (M * g) - L1), Math.min(R, E / (m2 * g) - R));
  const teile = [`Doppelpendel, Längen ${formatZahl(L1)} m und ${formatZahl(L2)} m`, `Massen ${formatZahl(m1)} kg und ${formatZahl(m2)} kg`,
    `Start bei ${formatZahl(p.winkel1)} Grad und ${formatZahl(p.winkel2)} Grad`, c > 0 ? `Dämpfung ${formatZahl(c)} pro Sekunde` : "ohne Dämpfung"];
  if (g !== 9.81) teile.push(`Fallbeschleunigung ${formatZahl(g)} m/s²`);
  const satz = `${teile.join(", ")}. Kleine Schwingungen dauern etwa ${formatWert(Tlangsam)} s (beide Arme gleichsinnig) `
    + `oder ${formatWert(Tschnell)} s (gegensinnig). Die Bewegung ist chaotisch: kleinste Änderungen am Start führen zu ganz anderen Bahnen.`;
  return { kern, dt, periode: Tlangsam, ausschnitt: rahmen(-R, R, -R, Math.min(R, oben)), text: satz, koerper: 2, einheit: "s", voraus: 0 };
}

const dpLagen = (k: DoppelpendelKern): [number, number, number, number] => {
  const x1 = k.L1 * Math.sin(k.th1), y1 = -k.L1 * Math.cos(k.th1);
  return [x1, y1, x1 + k.L2 * Math.sin(k.th2), y1 - k.L2 * Math.cos(k.th2)];
};

// --- Welle -------------------------------------------------------------------------------------------------------------

/** `gekuerzt`: `normalizeSim` hat den Bereich auf WELLE_MAX_LAENGEN kürzeste Wellenlängen gekürzt (die Textfassung sagt es). */
function welleTeile(p: WelleParameter, gekuerzt = false): Teile {
  const n = p.wellen.length, A: number[] = [], k: number[] = [], w: number[] = [], phi: number[] = [], s: number[] = [], lambda: number[] = [], f: number[] = [];
  for (const q of p.wellen) {
    A.push(q.amplitude); k.push(TAU / q.wellenlaenge); w.push(TAU * q.frequenz); phi.push(q.phase * RAD);
    s.push(q.richtung === "links" ? 1 : -1); lambda.push(q.wellenlaenge); f.push(q.frequenz);
  }
  const automatisch = !(p.bereich > 0), bereich = automatisch ? 2 * Math.max(...lambda) : p.bereich;
  const xs = new Float64Array(WELLE_PUNKTE);
  for (let i = 0; i < WELLE_PUNKTE; i++) xs[i] = (bereich * i) / (WELLE_PUNKTE - 1);
  const Tmax = 1 / Math.min(...f), Tmin = 1 / Math.max(...f), S = A.reduce((a, b) => a + b, 0);
  const kern: WelleKern = { art: "welle", A, k, w, phi, s, lambda, f, bereich, automatisch, xs, Tmax, Tmin };
  const zahlwort = ["eine", "zwei", "drei"][n - 1] ?? String(n);
  const ueber = `über ${formatZahl(bereich)} m${automatisch ? " (doppelte größte Wellenlänge)" : ""}`;
  const beschreibe = (q: Welle) => `Amplitude ${formatZahl(q.amplitude)} m, Wellenlänge ${formatZahl(q.wellenlaenge)} m, Frequenz ${formatZahl(q.frequenz)} Hz`
    + `${q.phase !== 0 ? `, Phase ${formatZahl(q.phase)} Grad` : ""}, nach ${q.richtung}, Periode etwa ${formatWert(1 / q.frequenz)} s, `
    + `Geschwindigkeit etwa ${formatWert(q.wellenlaenge * q.frequenz)} m/s.`;
  let satz = n === 1
    ? `Eine Welle ${ueber}: ${beschreibe(p.wellen[0])}`
    : `Überlagerung von ${zahlwort} Wellen ${ueber}. ` + p.wellen.map((q, i) => `Welle ${i + 1}: ${beschreibe(q)}`).join(" ");
  const [a, b] = p.wellen;
  if (n === 2 && a.amplitude === b.amplitude && a.wellenlaenge === b.wellenlaenge && a.frequenz === b.frequenz && a.richtung !== b.richtung) {
    satz += " Zusammen ergeben sie eine stehende Welle mit festen Knoten.";
  }
  if (gekuerzt) satz += ` Der gezeigte Bereich wurde auf ${formatZahl(bereich)} m gekürzt (${WELLE_MAX_LAENGEN} kürzeste Wellenlängen), damit die Welle richtig dargestellt wird.`;
  return {
    kern, dt: Tmin / 1000, periode: Tmax, ausschnitt: { minX: 0, maxX: bereich, minY: -1.1 * S, maxY: 1.1 * S }, text: satz, koerper: n, einheit: "s", voraus: 0,
  };
}

/** Wert der Welle `j` an der Stelle x zur Zeit t: A·sin(k·x + s·(ω·t) + φ), s = −1 nach rechts, +1 nach links. */
const welleWert = (k: WelleKern, j: number, x: number, t: number): number => k.A[j] * Math.sin(k.k[j] * x + k.s[j] * (k.w[j] * t) + k.phi[j]);

/** Summe und einzelne Wellen an allen Stellen zur Zeit t; dazu die größte Auslenkung der Summe. */
function welleKurven(k: WelleKern, t: number): { kurve: Pt[]; teil: Pt[][]; max: number } {
  const n = k.A.length, kurve: Pt[] = new Array(WELLE_PUNKTE), teil: Pt[][] = Array.from({ length: n }, () => new Array<Pt>(WELLE_PUNKTE));
  let max = 0;
  for (let i = 0; i < WELLE_PUNKTE; i++) {
    const x = k.xs[i];
    let y = 0;
    for (let j = 0; j < n; j++) { const v = welleWert(k, j, x, t); teil[j][i] = [x, v]; y += v; }
    kurve[i] = [x, y];
    max = Math.max(max, Math.abs(y));
  }
  return { kurve, teil, max };
}

// --- Umlauf mit gegenseitiger Anziehung ------------------------------------------------------------------------------

/** Beschleunigungen: Zentralmasse (fest im Ursprung) und alle Paare, beide geglättet (r² + ε²). Paarkräfte sind gleich und
 *  entgegengesetzt und liegen auf der Verbindungslinie, darum bleibt der Drehimpuls um den Ursprung erhalten. */
function nkBeschl(k: NKoerperKern): void {
  const { n, x, y, ax, ay, m } = k;
  for (let i = 0; i < n; i++) {
    const r2 = x[i] * x[i] + y[i] * y[i] + k.eps2z, f = k.GM / (r2 * Math.sqrt(r2));
    ax[i] = -f * x[i]; ay[i] = -f * y[i];
  }
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      if (m[i] === 0 && m[j] === 0) continue;
      const dx = x[j] - x[i], dy = y[j] - y[i], r2 = dx * dx + dy * dy + k.eps2, f = G_AE / (r2 * Math.sqrt(r2));
      ax[i] += m[j] * f * dx; ay[i] += m[j] * f * dy; ax[j] -= m[i] * f * dx; ay[j] -= m[i] * f * dy;
    }
  }
}

/** Leapfrog: halber Stoß, Drift, neue Beschleunigung, halber Stoß (zeitumkehrbar, symplektisch, ohne Energiedrift). */
function nkSchritt(k: NKoerperKern, dt: number): void {
  const { n, x, y, vx, vy, ax, ay } = k, h = 0.5 * dt;
  for (let i = 0; i < n; i++) { vx[i] += h * ax[i]; vy[i] += h * ay[i]; x[i] += dt * vx[i]; y[i] += dt * vy[i]; }
  nkBeschl(k);
  for (let i = 0; i < n; i++) { vx[i] += h * ax[i]; vy[i] += h * ay[i]; }
}

/** Gesamtenergie mit den geglätteten Potentialen, gewichtet mit den Massen (sind alle Massen 0: jede Bahnenergie einfach). */
function nkEnergie(k: NKoerperKern): number {
  const { n, x, y, vx, vy, m, w } = k;
  let e = 0;
  for (let i = 0; i < n; i++) e += w[i] * (0.5 * (vx[i] * vx[i] + vy[i] * vy[i]) - k.GM / Math.sqrt(x[i] * x[i] + y[i] * y[i] + k.eps2z));
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      if (m[i] === 0 || m[j] === 0) continue;
      const dx = x[j] - x[i], dy = y[j] - y[i];
      e -= (G_AE * m[i] * m[j]) / Math.sqrt(dx * dx + dy * dy + k.eps2);
    }
  }
  return e;
}

function nkKopie(k: NKoerperKern): NKoerperKern {
  return { ...k, x: k.x.slice(), y: k.y.slice(), vx: k.vx.slice(), vy: k.vy.slice(), ax: k.ax.slice(), ay: k.ay.slice() };
}

function nkoerperTeile(p: UmlaufParameter, budget: number): Teile {
  const kepler = umlaufTeile(p), uk = kepler.kern as UmlaufKern, bahnen = uk.bahnen, n = bahnen.length, M = p.zentralmasse;
  const amin = Math.min(...bahnen.map((b) => b.a)), Pmin = kepler.periode, Pmax = Math.max(...bahnen.map((b) => b.P));
  const m = new Float64Array(p.koerper.map((q) => q.masse ?? 0)), summe = m.reduce((a, b) => a + b, 0), mmax = Math.max(...m);
  // Schwere Körper: ein naher Vorbeiflug zweier Körper (Abstand ε) gibt einen Stoß von etwa √(2·G·m/ε), verglichen mit der
  // Bahngeschwindigkeit √(G·M/a) ist das q = √(2·m·a/(M·ε)) = √(200·m/M). Ab q ≥ 0,1 können Körper einander auf Bahnen dicht an
  // der Zentralmasse vorbei streuen; dann gilt auch zur Zentralmasse die Glättung 0,01 und eine Schrittgrenze (unten).
  const schwer = Math.sqrt((2 * mmax) / (M * NK_GLAETTUNG)) >= 0.1;
  const kern: NKoerperKern = {
    art: "nkoerper", n, GM: G_AE * M, m, w: summe > 0 ? m.slice() : new Float64Array(n).fill(1),
    x: new Float64Array(n), y: new Float64Array(n), vx: new Float64Array(n), vy: new Float64Array(n), ax: new Float64Array(n), ay: new Float64Array(n),
    eps2z: ((schwer ? NK_GLAETTUNG_Z_SCHWER : NK_GLAETTUNG_Z) * amin) ** 2, eps2: (NK_GLAETTUNG * amin) ** 2, bahnen, E0: 0, pfade: [], pfadDauer: 0,
  };
  bahnen.forEach((b, i) => {                                        // Kepler-Lage und -Geschwindigkeit am Start (wie ohne Anziehung)
    const Ed = TAU / b.P / (1 - b.e * Math.cos(b.E));
    kern.x[i] = b.a * (Math.cos(b.E) - b.e); kern.y[i] = b.b * Math.sin(b.E);
    kern.vx[i] = -b.a * Math.sin(b.E) * Ed; kern.vy[i] = b.b * Math.cos(b.E) * Ed;
  });
  nkBeschl(kern);
  kern.E0 = nkEnergie(kern);
  // Schritt: innerster Umlauf / 2000, bei großer Exzentrizität kleiner (Zeitmaß am Perihel ∝ (1 − e)^1,5, höchstens 20-mal kleiner).
  // Haben die Körper Masse, höchstens 0,05 des Glättungs-Zeitmaßes zweier Körper √(ε³/(G·2·m_max)), bei schweren Körpern auch
  // 0,05 von √(ε³/(G·(M + m_max))) (Körper dicht an der Zentralmasse): sonst springt ein naher Vorbeiflug zwischen zwei Schritten
  // und schleudert Körper zahlengemacht hinaus. Fester Schritt (keine wechselnden Teilschritte), damit Leapfrog symplektisch bleibt
  // und die Energie auch über viele enge Umläufe nicht wegläuft. Reicht die Grenze je Bild nicht, läuft die Zeit langsamer.
  let dt = Math.min(...bahnen.map((b) => b.P * clamp((1 - b.e) ** 1.5, 0.05, 1))) / 2000;
  const eps = NK_GLAETTUNG * amin;
  if (mmax > 0) dt = Math.min(dt, 0.05 * Math.sqrt(eps ** 3 / (G_AE * 2 * mmax)));
  if (schwer) dt = Math.min(dt, 0.05 * Math.sqrt(eps ** 3 / (G_AE * (M + mmax))));
  // Vorausrechnung: die Wege über einen Umlauf des äußersten Körpers, höchstens die Hälfte des Budgets.
  // Dieselben Rasterschritte wie im Lauf; jeder nur, wenn auch seine höchsten Kosten (Teilschritte) noch ins halbe Budget passen.
  const ziel = Math.ceil(Pmax / dt), halb = budget / 2;
  const sim = nkKopie(kern), jede = Math.max(1, Math.ceil(Math.min(ziel, halb / n) / (NK_PFAD_PUNKTE - 2)));
  const pfade: Pt[][] = Array.from({ length: n }, (_, i) => [[sim.x[i], sim.y[i]]]);
  let schritte = 0, kosten = 0;
  while (schritte < ziel && kosten + n <= halb) {
    nkSchritt(sim, dt);
    kosten += n;
    schritte++;
    if (schritte % jede === 0) for (let i = 0; i < n; i++) pfade[i].push([sim.x[i], sim.y[i]]);
  }
  if (schritte % jede !== 0) for (let i = 0; i < n; i++) pfade[i].push([sim.x[i], sim.y[i]]);
  kern.pfade = pfade.every((q) => q.every((pt) => fin(pt[0]) && fin(pt[1]))) ? pfade : [];
  kern.pfadDauer = schritte * dt;
  // Bildausschnitt: die Kepler-Bahnen und die vorab gerechneten Wege, diese höchstens bis zum Dreifachen der Kepler-Größe.
  let minX = 0, maxX = 0, minY = 0, maxY = 0;
  for (const b of bahnen) {
    minX = Math.min(minX, -b.a * (1 + b.e)); maxX = Math.max(maxX, b.a * (1 - b.e)); minY = Math.min(minY, -b.b); maxY = Math.max(maxY, b.b);
  }
  const gross = 3 * Math.max(-minX, maxX, -minY, maxY);
  for (const q of kern.pfade) for (const [px, py] of q) {
    minX = Math.min(minX, Math.max(px, -gross)); maxX = Math.max(maxX, Math.min(px, gross));
    minY = Math.min(minY, Math.max(py, -gross)); maxY = Math.max(maxY, Math.min(py, gross));
  }
  const satz = `Umlaufbahnen um eine Zentralmasse von ${formatZahl(M)} ${M === 1 ? "Sonnenmasse" : "Sonnenmassen"}, `
    + `${n} Körper. Die Körper ziehen sich gegenseitig an. Die Zentralmasse bleibt fest in der Mitte. `
    + bahnen.map((b, i) => `${b.name}: Start auf einer Bahn mit großer Halbachse ${formatZahl(b.a)} AE und Exzentrizität ${formatZahl(b.e)}, `
      + `${m[i] > 0 ? `Masse ${formatZahl(m[i])} Sonnenmassen` : "ohne eigene Masse"}, Umlaufzeit dieser Bahn etwa ${formatWert(b.P)} Jahre.`).join(" ");
  return {
    kern, dt, periode: Pmin, ausschnitt: rahmen(minX, maxX, minY, maxY, 0.06), text: satz, koerper: n, einheit: "Jahre", voraus: kosten,
  };
}

// --- Zustand -----------------------------------------------------------------------------------------------------------

function teileFuer(cfg: SimConfigAlle, budget: number): Teile {
  switch (cfg.modell) {
    case "pendel": return pendelTeile(cfg.parameter);
    case "feder": return federTeile(cfg.parameter);
    case "wurf": return wurfTeile(cfg.parameter, budget);
    case "umlauf": return cfg.parameter.anziehung === true ? nkoerperTeile(cfg.parameter, budget) : umlaufTeile(cfg.parameter);
    case "gas": return gasTeile(cfg.parameter);
    case "doppelpendel": return doppelpendelTeile(cfg.parameter);
    case "welle": {
      const p = cfg.parameter, lmin = Math.min(...p.wellen.map((q) => q.wellenlaenge));
      return welleTeile(p, cfg.angepasst.includes("parameter.bereich") && Math.abs(p.bereich - WELLE_MAX_LAENGEN * lmin) <= 1e-12 * p.bereich);
    }
  }
}

const alleEndlich = (...a: ArrayLike<number>[]): boolean => {
  for (const q of a) for (let i = 0; i < q.length; i++) if (!fin(q[i])) return false;
  return true;
};

function kernEndlich(k: SimKern): boolean {
  switch (k.art) {
    case "pendel": return fin(k.th) && fin(k.om) && fin(k.a);
    case "feder": return fin(k.x) && fin(k.v) && fin(k.a);
    case "wurf": return fin(k.x) && fin(k.y) && fin(k.vx) && fin(k.vy);
    case "umlauf": return k.bahnen.every((b) => fin(b.E));
    case "gas":
      for (let i = 0; i < k.N; i++) if (!fin(k.px[i]) || !fin(k.py[i]) || !fin(k.vx[i]) || !fin(k.vy[i])) return false;
      return true;
    case "doppelpendel": return fin(k.th1) && fin(k.om1) && fin(k.th2) && fin(k.om2);
    case "welle": return fin(k.bereich) && fin(k.Tmax) && fin(k.Tmin) && alleEndlich(k.A, k.k, k.w, k.phi, k.xs);
    case "nkoerper": return alleEndlich(k.x, k.y, k.vx, k.vy, k.ax, k.ay);
  }
}

/** Legt eine Simulation an: Eingabe begrenzen, Zeitschritt wählen, Bildausschnitt und Kennwerte vorab rechnen. Wirft nie. */
export function createSim(input: unknown): SimState {
  const cfg = normalizeSim(input);
  try {
    return baue(cfg);
  } catch {
    const ersatz = normalizeSim(null);
    ersatz.angepasst.push("intern");
    const s = baue(ersatz);
    s.phase = "instabil";
    return s;
  }
}

function baue(cfg: SimConfigAlle): SimState {
  const t = teileFuer(cfg, VORAUS_BUDGET);
  if (t.kern.art === "gas" && t.kern.rKleiner) cfg.angepasst.push("parameter.radius");
  const auto = cfg.modell === "gas" ? 1 : clamp(t.periode > 0 && fin(t.periode) ? t.periode / 4 : 1, 1e-6, 1e7);
  const s: SimState = {
    config: cfg, modell: cfg.modell, anziehung: t.kern.art === "nkoerper", dt: t.dt, tempo: cfg.tempo > 0 ? cfg.tempo : auto, koerper: t.koerper, ausschnitt: t.ausschnitt,
    text: t.text, einheit: t.einheit, periode: t.periode, startBild: null as unknown as SimSnapshot,
    phase: cfg.ungueltig ? "instabil" : t.kern.art === "wurf" && t.kern.gelandet ? "gelandet" : "laeuft",
    schritt: 0, zeit: 0, vorausSchritte: t.voraus, soll: 0, kern: t.kern, bild: null,
  };
  if (!(s.dt > 0 && fin(s.dt)) || !kernEndlich(s.kern)) s.phase = "instabil";
  (s as { startBild: SimSnapshot }).startBild = snapshot(s);
  if (!isFiniteSnapshot(s.startBild)) s.phase = "instabil";
  return s;
}

/** Ein Rasterschritt; gibt die Körper-Schritte zurück, die er gekostet hat (Doppelpendel: 2 je Teilschritt). */
function einSchritt(s: SimState): number {
  const k = s.kern;
  let kosten = s.koerper;
  switch (k.art) {
    case "pendel": pendelSchritt(k, s.dt); break;
    case "feder": federSchritt(k, s.dt); break;
    case "wurf": wurfSchritt(k, s.dt, s.schritt * s.dt); break;
    case "gas": gasSchritt(k, s.dt); break;
    case "doppelpendel": kosten = 2 * dpSchritt(k, s.dt); break;
    case "nkoerper": nkSchritt(k, s.dt); break;
    case "umlauf": case "welle": break;
  }
  s.schritt++;
  return kosten;
}

/** Höchste Kosten eines Rasterschritts in Körper-Schritten (damit die Grenze je Bild nie überschritten wird). */
const hoechstKosten = (s: SimState): number => (s.kern.art === "doppelpendel" ? 2 * s.kern.kmax : s.koerper);

/** Rechnet die Simulation um `simSeconds` Modellzeit weiter, in festen Teilschritten auf dem Raster t = n·dt.
 *  Höchstens `maxBodySteps` Körper × Teilschritte; reicht das nicht, bleibt die Zeit zurück (`begrenzt`, kein Nachholen).
 *  Ändert den Zustand an Ort und Stelle. Wirft nie; eine nicht endliche Zahl setzt die Phase auf „instabil“. */
export function advance(state: SimState, simSeconds: number, maxBodySteps: number = MAX_CALL): AdvanceResult {
  const nichts: AdvanceResult = { schritte: 0, koerperSchritte: 0, begrenzt: false };
  if (state.phase !== "laeuft") return nichts;
  try {
    state.soll += fin(simSeconds) && simSeconds > 0 ? Math.min(simSeconds, 1e12) : 0;
    const ziel = Math.floor(state.soll / state.dt + 1e-9), n = ziel - state.schritt;
    if (n <= 0) return nichts;
    const k = state.kern;
    let out: AdvanceResult;
    if (k.art === "umlauf" || k.art === "welle" || (k.art === "wurf" && k.geschlossen)) {
      state.schritt = ziel;
      state.zeit = ziel * state.dt;
      if (k.art === "umlauf") umlaufStellen(k, state.zeit);
      else if (k.art === "wurf") { wurfAuswerten(k, state.zeit); if (k.gelandet) { state.zeit = k.landezeit; state.phase = "gelandet"; } }
      // Welle: geschlossen, die Kurve rechnet `snapshot` zur Zeit `state.zeit`.
      out = { schritte: n, koerperSchritte: state.koerper, begrenzt: false };
    } else {
      const mb = fin(maxBodySteps) && maxBodySteps > 0 ? Math.min(maxBodySteps, MAX_CALL) : MAX_CALL;
      // Mindestens ein Rasterschritt; jeder weitere nur, wenn auch seine höchsten Kosten noch unter die Grenze passen.
      const hoechst = hoechstKosten(state);
      let done = 0, kosten = 0;
      while (done < n && (done === 0 || kosten + hoechst <= mb)) {
        kosten += einSchritt(state);
        done++;
        if (k.art === "wurf" && k.gelandet) break;
      }
      const gelandet = k.art === "wurf" && k.gelandet;
      state.zeit = gelandet ? (k as WurfKern).landezeit : state.schritt * state.dt;
      if (gelandet) state.phase = "gelandet";
      const begrenzt = done < n && !gelandet;
      if (begrenzt) state.soll = state.schritt * state.dt;
      out = { schritte: done, koerperSchritte: kosten, begrenzt };
    }
    if (!kernEndlich(k) || !fin(state.zeit)) state.phase = "instabil";
    return out;
  } catch {
    state.phase = "instabil";
    return nichts;
  }
}

// --- Bild und Kennwerte ------------------------------------------------------------------------------------------------

function prozent(e: number, e0: number): number {
  return e0 > 1e-300 ? (e / e0) * 100 : 100;
}

/** Was zum Zeichnen gebraucht wird: Lagen in Modelleinheiten, fester Ausschnitt, Kennwerte mit Text. Wirft nie. */
export function snapshot(state: SimState): SimSnapshot {
  const basis = { modell: state.modell, zeit: state.zeit, einheit: state.einheit, phase: state.phase, ausschnitt: state.ausschnitt };
  try {
    const k = state.kern;
    switch (k.art) {
      case "pendel": {
        const deg = k.th / RAD;
        return {
          ...basis, koerper: [{ x: k.L * Math.sin(k.th), y: -k.L * Math.cos(k.th), r: 0, farbe: "arc", name: "Pendelkörper" }], anker: [0, 0],
          kennwerte: [kw("schwingungsdauer", "Schwingungsdauer (kleine Winkel)", k.T0, "s"), kw("winkel", "Winkel jetzt", deg, "Grad"),
            kw("energie", "Energie in Prozent des Starts", prozent(pendelEnergie(k, state.dt), k.E0), "%")],
          verteilung: null,
        };
      }
      case "feder":
        return {
          ...basis, koerper: [{ x: k.x, y: 0, r: 0, farbe: "arc", name: "Masse" }], anker: [-2 * k.S, 0],
          kennwerte: [kw("schwingungsdauer", "Schwingungsdauer", k.T, "s"), kw("auslenkung", "Auslenkung jetzt", k.x, "m"),
            kw("energie", "Energie in Prozent des Starts", prozent(federEnergie(k), k.E0), "%")],
          verteilung: null,
        };
      case "wurf":
        return {
          ...basis, koerper: [{ x: k.x, y: k.y, r: 0, farbe: "arc", name: "Wurfkörper" }], anker: null,
          kennwerte: [kw("reichweite", "Reichweite", k.reichweite, "m"), kw("gipfelhoehe", "Gipfelhöhe", k.gipfel, "m"),
            kw("flugzeit", "Flugzeit", k.flugzeit, "s"), kw("hoehe", "Höhe jetzt", k.y, "m"), kw("weite", "Weite jetzt", k.x, "m")],
          verteilung: null,
        };
      case "umlauf": {
        const koerper: SimKoerper[] = [], kennwerte: Kennwert[] = [];
        k.bahnen.forEach((b, i) => {
          koerper.push({ x: b.a * (Math.cos(b.E) - b.e), y: b.b * Math.sin(b.E), r: 0, farbe: b.farbe, name: b.name });
          kennwerte.push(kw(`umlaufzeit.${i}`, `Umlaufzeit ${b.name}`, b.P, "Jahre"),
            kw(`abstand.${i}`, `Abstand ${b.name} jetzt`, b.a * (1 - b.e * Math.cos(b.E)), "AE"));
        });
        return { ...basis, koerper, anker: [0, 0], kennwerte, verteilung: null };
      }
      case "gas": {
        const koerper: SimKoerper[] = new Array(k.N);
        let summe = 0, energie = 0;
        for (let i = 0; i < k.N; i++) {
          koerper[i] = { x: k.px[i], y: k.py[i], r: k.r, farbe: "arc", name: "" };
          const q = k.vx[i] * k.vx[i] + k.vy[i] * k.vy[i];
          summe += Math.sqrt(q); energie += 0.5 * q;
        }
        return {
          ...basis, koerper, anker: null,
          kennwerte: [kw("geschwindigkeit", "Mittlere Geschwindigkeit", summe / k.N, "Einheiten/s"), kw("bewegungsenergie", "Bewegungsenergie", energie, "Einheiten")],
          verteilung: gasVerteilung(k),
        };
      }
      case "doppelpendel": {
        const [x1, y1, x2, y2] = dpLagen(k);
        return {
          ...basis, anker: [0, 0], spurKoerper: [1],
          koerper: [{ x: x1, y: y1, r: 0, farbe: "arc", name: "oberer Pendelkörper" }, { x: x2, y: y2, r: 0, farbe: "amber", name: "unterer Pendelkörper" }],
          kennwerte: [kw("winkel1", "Winkel des oberen Arms jetzt", k.th1 / RAD, "Grad"), kw("winkel2", "Winkel des unteren Arms jetzt", k.th2 / RAD, "Grad"),
            kw("energie", "Energie in Prozent des Starts", prozent(dpEnergie(k), k.E0), "%")],
          verteilung: null,
        };
      }
      case "welle": {
        const { kurve, teil, max } = welleKurven(k, state.zeit), kennwerte: Kennwert[] = [];
        k.A.forEach((_, j) => kennwerte.push(kw(`periode.${j}`, `Periode Welle ${j + 1}`, 1 / k.f[j], "s"),
          kw(`geschwindigkeit.${j}`, `Geschwindigkeit Welle ${j + 1}`, k.lambda[j] * k.f[j], "m/s")));
        kennwerte.push(kw("auslenkung", "Größte Auslenkung jetzt", max, "m"));
        return { ...basis, koerper: [], anker: null, kennwerte, verteilung: null, kurve, teilkurven: teil };
      }
      case "nkoerper": {
        const koerper: SimKoerper[] = [], kennwerte: Kennwert[] = [];
        k.bahnen.forEach((b, i) => {
          koerper.push({ x: k.x[i], y: k.y[i], r: 0, farbe: b.farbe, name: b.name });
          kennwerte.push(kw(`umlaufzeit.${i}`, `Umlaufzeit ${b.name}`, b.P, "Jahre"), kw(`abstand.${i}`, `Abstand ${b.name} jetzt`, Math.hypot(k.x[i], k.y[i]), "AE"));
        });
        // Die Startenergie ist negativ (gebunden), „Prozent des Starts“ wäre irreführend: darum die Abweichung in Prozent von |E0|.
        const e = nkEnergie(k), abw = Math.abs(k.E0) > 1e-300 ? ((e - k.E0) / Math.abs(k.E0)) * 100 : 0;
        kennwerte.push({ id: "energieAbweichung", name: "Energieabweichung", wert: abw, einheit: "%", text: `${formatFest(abw, Math.abs(abw) < 1 ? 2 : 1)} %` });
        const a = state.ausschnitt;
        const ausserhalb = koerper.filter((p) => !(p.x >= a.minX && p.x <= a.maxX && p.y >= a.minY && p.y <= a.maxY)).length;
        return { ...basis, koerper, anker: [0, 0], kennwerte, verteilung: null, ausserhalb };
      }
    }
  } catch {
    state.phase = "instabil";
    return { ...basis, phase: "instabil", koerper: [], anker: null, kennwerte: [], verteilung: null };
  }
}

/** Sind alle Zahlen im Bild endlich? (Nie ein Bild mit kaputten Werten zeigen.) */
export function isFiniteSnapshot(s: SimSnapshot | null | undefined): boolean {
  try {
    if (!s || !fin(s.zeit)) return false;
    const a = s.ausschnitt;
    if (!a || !fin(a.minX) || !fin(a.maxX) || !fin(a.minY) || !fin(a.maxY)) return false;
    if (s.anker && (!fin(s.anker[0]) || !fin(s.anker[1]))) return false;
    for (const k of s.koerper) if (!fin(k.x) || !fin(k.y) || !fin(k.r)) return false;
    for (const k of s.kennwerte) if (!fin(k.wert)) return false;
    if (s.verteilung && ![...s.verteilung.grenzen, ...s.verteilung.anzahl].every(fin)) return false;
    for (const q of [s.kurve ?? [], ...(s.teilkurven ?? [])]) for (const p of q) if (!fin(p[0]) || !fin(p[1])) return false;
    if (s.ausserhalb !== undefined && !fin(s.ausserhalb)) return false;
    return true;
  } catch {
    return false;
  }
}

// --- Standbild ---------------------------------------------------------------------------------------------------------

/** Standbild für „weniger Bewegung“, einmal gerechnet und gemerkt. Teilt sich die Vorausrechnung (VORAUS_BUDGET) mit
 *  `createSim`. Pendel und Feder: Lage-Zeit-Kurve über drei Schwingungen; Wurf: ganze Bahn mit Gipfel und Aufprall; Umlauf: alle
 *  Bahnen; Gas: Verteilung nach 10 s gerechneter Zeit (passt das nicht ins Budget, mit gröberem Schritt oder kürzer, siehe `zeit`).
 *  P5b: Doppelpendel mit dem Weg des unteren Körpers über 10 s; Welle mit Kurve bei t = 0 und Hülle; Umlauf mit Anziehung mit den
 *  vorab gerechneten Wegen (`offen`). */
export function standbild(state: SimState): Standbild {
  if (state.bild) return state.bild;
  let bild: Standbild;
  try {
    bild = baueStandbild(state);
  } catch {
    bild = { modell: "pendel", start: state.startBild, kurve: [], groesse: "", einheit: "", dauer: 0 };
  }
  state.bild = bild;
  return bild;
}

function baueStandbild(state: SimState): Standbild {
  const rest = () => Math.max(0, VORAUS_BUDGET - state.vorausSchritte), start = state.startBild, k0 = state.kern;
  switch (k0.art) {
    case "pendel": case "feder": {
      const frisch = teileFuer(state.config, 0).kern as PendelKern | FederKern, dt = state.dt;
      const dauer = 3 * state.periode, n = Math.min(Math.ceil(dauer / dt), rest());
      const wert = (): number => (frisch.art === "pendel" ? frisch.th / RAD : frisch.x);
      const alle: Pt[] = [[0, wert()]];
      const jede = Math.max(1, Math.ceil(n / (SPUR_MAX - 1)));
      for (let i = 1; i <= n; i++) {
        if (frisch.art === "pendel") pendelSchritt(frisch, dt); else federSchritt(frisch, dt);
        if (i % jede === 0 || i === n) alle.push([i * dt, wert()]);
      }
      state.vorausSchritte += n;
      const kurve = alle.every((p) => fin(p[0]) && fin(p[1])) ? alle : [];
      return frisch.art === "pendel"
        ? { modell: "pendel", start, kurve, groesse: "Winkel", einheit: "Grad", dauer: n * dt }
        : { modell: "feder", start, kurve, groesse: "Auslenkung", einheit: "m", dauer: n * dt };
    }
    case "wurf": {
      let bahn = k0.bahn;
      if (k0.geschlossen) {
        const T = k0.flugzeit, n = Math.min(200, rest());
        bahn = [];
        const tmp: WurfKern = { ...k0, gelandet: false };
        for (let i = 0; i < n; i++) { wurfAuswerten(tmp, n > 1 ? (T * i) / (n - 1) : 0); bahn.push([tmp.x, tmp.y]); }
        state.vorausSchritte += n;
      }
      if (!bahn.length) bahn = [[0, k0.h]];
      return {
        modell: "wurf", start, bahn, gipfel: [k0.gipfelX, k0.gipfel], aufprall: [k0.reichweite, 0], flugzeit: k0.flugzeit, vollstaendig: k0.vollstaendig,
      };
    }
    case "umlauf": {
      const je = clamp(Math.floor(rest() / Math.max(1, k0.bahnen.length)), 2, 181);
      const bahnen = k0.bahnen.map((b) => ({
        name: b.name, farbe: b.farbe,
        punkte: Array.from({ length: je }, (_, i): Pt => { const E = (TAU * i) / (je - 1); return [b.a * (Math.cos(E) - b.e), b.b * Math.sin(E)]; }),
      }));
      state.vorausSchritte += je * k0.bahnen.length;
      return { modell: "umlauf", start, bahnen };
    }
    case "gas": {
      const sim = gasKopie(k0), maxN = Math.floor(rest() / k0.N);
      let dt = state.dt;
      if (Math.ceil(GAS_STANDBILD_S / dt - 1e-9) > maxN && maxN > 0) {
        dt = Math.min(Math.max(state.dt, GAS_STANDBILD_S / maxN), Math.max(state.dt, (0.5 * k0.r) / Math.max(k0.vref, 1e-300)));
      }
      const n = Math.min(Math.ceil(GAS_STANDBILD_S / dt - 1e-9), maxN);
      for (let i = 0; i < n; i++) gasSchritt(sim, dt);
      state.vorausSchritte += n * k0.N;
      return { modell: "gas", start, verteilung: gasVerteilung(sim), zeit: n * dt };
    }
    case "doppelpendel": {
      const frisch = teileFuer(state.config, 0).kern as DoppelpendelKern, dt = state.dt;
      // So viele Rasterschritte, wie für 10 s nötig sind und mit ihren höchsten Kosten (Teilschritte) ins Budget passen.
      const ziel = Math.ceil(DP_STANDBILD_S / dt - 1e-9), budget = rest(), hoechst = 2 * frisch.kmax;
      const jede = Math.max(1, Math.ceil(Math.min(ziel, budget / 2) / (DOPPELPENDEL_BAHN_MAX - 2)));
      const bahn: Pt[] = [[dpLagen(frisch)[2], dpLagen(frisch)[3]]];
      let n = 0, kosten = 0;
      while (n < ziel && kosten + hoechst <= budget) {
        kosten += 2 * dpSchritt(frisch, dt);
        n++;
        if (n % jede === 0) { const l = dpLagen(frisch); bahn.push([l[2], l[3]]); }
      }
      if (n % jede !== 0) { const l = dpLagen(frisch); bahn.push([l[2], l[3]]); }
      state.vorausSchritte += kosten;
      return { modell: "doppelpendel", start, bahn: bahn.every((p) => fin(p[0]) && fin(p[1])) ? bahn : [], dauer: n * dt };
    }
    case "welle": {
      const nW = k0.A.length, { kurve, teil } = welleKurven(k0, 0);
      const huelleMin: Pt[] = kurve.map((p) => [p[0], p[1]]), huelleMax: Pt[] = kurve.map((p) => [p[0], p[1]]);
      const exakt = k0.f.every((f) => f === k0.f[0]);
      if (exakt) {
        // Gleiche Frequenz: jede Welle ist Im(B_j·e^(iωt)) mit B_j = A·e^(iθ) (links) oder −A·e^(−iθ) (rechts), θ = k·x + φ.
        // Die Summe schwingt an jeder Stelle mit dem Betrag |Σ B_j|: das ist die Hülle, ohne Abtasten.
        for (let i = 0; i < WELLE_PUNKTE; i++) {
          let re = 0, im = 0;
          for (let j = 0; j < nW; j++) {
            const th = k0.k[j] * k0.xs[i] + k0.phi[j], a = k0.A[j];
            if (k0.s[j] > 0) { re += a * Math.cos(th); im += a * Math.sin(th); } else { re -= a * Math.cos(th); im += a * Math.sin(th); }
          }
          const b = Math.hypot(re, im);
          huelleMin[i][1] = -b; huelleMax[i][1] = b;
        }
        state.vorausSchritte += WELLE_PUNKTE * nW;
      } else {
        // Sonst abgetastet über eine Periode der langsamsten Welle: so viele Zeitpunkte, wie ins Budget passen (je Zeitpunkt
        // kosten alle Stellen aller Wellen), höchstens 64 je Periode der schnellsten Welle.
        const proZeit = WELLE_PUNKTE * nW, S = Math.max(2, Math.min(Math.floor(rest() / proZeit), 64 * Math.ceil(k0.Tmax / k0.Tmin)));
        for (let j = 1; j < S; j++) {
          const t = (k0.Tmax * j) / S;
          for (let i = 0; i < WELLE_PUNKTE; i++) {
            let y = 0;
            for (let q = 0; q < nW; q++) y += welleWert(k0, q, k0.xs[i], t);
            if (y < huelleMin[i][1]) huelleMin[i][1] = y;
            if (y > huelleMax[i][1]) huelleMax[i][1] = y;
          }
        }
        state.vorausSchritte += S * proZeit;
      }
      return { modell: "welle", start, kurve, teilkurven: teil, huelleMin, huelleMax, dauer: k0.Tmax, exakt };
    }
    case "nkoerper":
      return {
        modell: "umlauf", start, offen: true, dauer: k0.pfadDauer,
        bahnen: k0.bahnen.map((b, i) => ({ name: b.name, farbe: b.farbe, punkte: k0.pfade[i] ?? [[start.koerper[i].x, start.koerper[i].y]] })),
      };
  }
}

// --- Spur --------------------------------------------------------------------------------------------------------------

/** Spur als Ringpuffer: höchstens `max` (≤ 600) Punkte je Körper, höchstens SPUR_KOERPER_MAX Körper. */
export interface Trail { readonly max: number; readonly xs: Float64Array[]; readonly ys: Float64Array[]; anfang: number[]; laenge: number[] }

export function createTrail(koerper: number, max: number = SPUR_MAX): Trail {
  const n = fin(koerper) ? clamp(Math.floor(koerper), 0, SPUR_KOERPER_MAX) : 0;
  const m = fin(max) ? clamp(Math.floor(max), 1, SPUR_MAX) : SPUR_MAX;
  return {
    max: m, xs: Array.from({ length: n }, () => new Float64Array(m)), ys: Array.from({ length: n }, () => new Float64Array(m)),
    anfang: new Array<number>(n).fill(0), laenge: new Array<number>(n).fill(0),
  };
}

/** Hängt die Lagen eines Bildes an; der älteste Punkt fällt heraus, wenn die Spur voll ist. Gleiche Punkte werden übersprungen. */
export function addToTrail(trail: Trail, snap: SimSnapshot): void {
  const n = Math.min(trail.xs.length, snap.koerper.length);
  for (let i = 0; i < n; i++) {
    const p = snap.koerper[i];
    if (!fin(p.x) || !fin(p.y)) continue;
    const len = trail.laenge[i], m = trail.max;
    if (len > 0) {
      const last = (trail.anfang[i] + len - 1) % m;
      if (trail.xs[i][last] === p.x && trail.ys[i][last] === p.y) continue;
    }
    let at: number;
    if (len < m) { at = (trail.anfang[i] + len) % m; trail.laenge[i] = len + 1; }
    else { at = trail.anfang[i]; trail.anfang[i] = (at + 1) % m; }
    trail.xs[i][at] = p.x; trail.ys[i][at] = p.y;
  }
}

/** Punkte der Spur eines Körpers, älteste zuerst. */
export function trailPoints(trail: Trail, i: number): Pt[] {
  if (!(i >= 0 && i < trail.xs.length)) return [];
  const out: Pt[] = [];
  for (let j = 0; j < trail.laenge[i]; j++) { const q = (trail.anfang[i] + j) % trail.max; out.push([trail.xs[i][q], trail.ys[i][q]]); }
  return out;
}

// --- Regler ------------------------------------------------------------------------------------------------------------

/** Ein Wert, den die Ansicht mit einem Regler ändern darf. `feld` ist der Pfad unter `parameter`, Teile mit Punkt getrennt, Zahlen
 *  zählen in Listen ab 0 (zum Beispiel `laenge` oder `wellen.0.frequenz` = Frequenz der ersten Welle). `min`/`max` sind die
 *  Schema-Grenzen (beim Gas die Geschwindigkeit ab 0,01, weil das Schema nur „> 0“ sagt); `schritt` ist die Feinheit des Reglers;
 *  `skala: "log"` empfiehlt einen logarithmischen Regler (das Verhältnis max/min ist ≥ 1000). */
export interface GrenzFeld { feld: string; name: string; einheit: string; min: number; max: number; schritt: number; skala: "linear" | "log" }

const gf = (feld: string, name: string, einheit: string, min: number, max: number, schritt: number): GrenzFeld =>
  Object.freeze({ feld, name, einheit, min, max, schritt, skala: min > 0 && max >= 1000 * min ? "log" : "linear" });

/** Regler je Modell (ein bis zwei Hauptwerte), dieselben Grenzen wie im Schema. */
export const GRENZEN: Readonly<Record<SimModellAlle, readonly GrenzFeld[]>> = Object.freeze({
  pendel: Object.freeze([gf("laenge", "Länge", "m", 0.05, 100, 0.05), gf("winkel", "Startwinkel", "Grad", -170, 170, 1)]),
  feder: Object.freeze([gf("masse", "Masse", "kg", 0.001, 1000, 0.001), gf("federkonstante", "Federkonstante", "N/m", 0.001, 1e6, 0.001)]),
  wurf: Object.freeze([gf("geschwindigkeit", "Abwurfgeschwindigkeit", "m/s", 0.1, 1000, 0.1), gf("winkel", "Abwurfwinkel", "Grad", -90, 90, 1)]),
  umlauf: Object.freeze([gf("zentralmasse", "Zentralmasse", "Sonnenmassen", 0.01, 100, 0.01)]),
  gas: Object.freeze([gf("geschwindigkeit", "Startgeschwindigkeit", "Kastenbreiten/s", 0.01, 10, 0.01), gf("schwerkraft", "Schwerkraft", "Einheiten/s²", 0, 100, 0.5)]),
  doppelpendel: Object.freeze([gf("winkel1", "Startwinkel oben", "Grad", -180, 180, 1), gf("laenge2", "Länge unten", "m", 0.05, 100, 0.05)]),
  welle: Object.freeze([gf("wellen.0.frequenz", "Frequenz der ersten Welle", "Hz", 0.01, 100, 0.01)]),
});

/** Kopiert `obj` entlang des Pfads und setzt dort `wert`; fehlt ein Zwischenglied, bleibt alles, wie es war (nur kopiert). */
function setzePfad(obj: unknown, teile: string[], wert: number): unknown {
  const [kopf, ...rest] = teile;
  if (Array.isArray(obj)) {
    const i = Number(kopf);
    if (!Number.isInteger(i) || i < 0 || i >= obj.length) return obj.slice();
    const kopie = obj.slice();
    kopie[i] = rest.length ? setzePfad(obj[i], rest, wert) : wert;
    return kopie;
  }
  if (!isObj(obj)) return obj;
  const kopie: Obj = { ...obj };
  if (!rest.length) kopie[kopf] = wert;
  else if (own(obj, kopf) !== undefined) kopie[kopf] = setzePfad(own(obj, kopf), rest, wert);
  return kopie;
}

/** Neue Eingabe mit `feld` (Pfad unter `parameter`, siehe GrenzFeld) auf `wert`, begrenzt auf GRENZEN des Modells. Ändert die Eingabe
 *  nie (kopiert entlang des Pfads). Abgeleitete Regeln wie im Schema: Feder mit Schwingungsdauer 0,05 bis 1000 s (die Masse bzw.
 *  Federkonstante wird entsprechend enger begrenzt); Wurf aus Höhe 0 mit Winkel ≥ ein Reglerschritt (1 Grad). Unbekanntes Modell,
 *  unbekanntes Feld oder keine endliche Zahl: eine unveränderte Kopie. Wirft nie. */
export function mitWert<T>(input: T, feld: string, wert: number): T {
  try {
    if (!isObj(input)) return input;
    const kopie: Obj = { ...input }, m = own(input, "modell"), p = own(input, "parameter");
    const liste = typeof m === "string" && Object.prototype.hasOwnProperty.call(GRENZEN, m) ? GRENZEN[m as SimModellAlle] : [];
    const g = liste.find((x) => x.feld === feld);
    if (!g || typeof wert !== "number" || !fin(wert) || !isObj(p)) return kopie as T;
    let lo = g.min, hi = g.max;
    const zahlVon = (k: string): number | null => { const v = own(p, k); return typeof v === "number" && fin(v) && v > 0 ? v : null; };
    if (m === "feder") {                                              // T = 2π·√(m/k) zwischen 0,05 und 1000 s (knapp innen)
      const kMin = (0.05 / TAU) ** 2 * (1 + 1e-9), kMax = (1000 / TAU) ** 2 * (1 - 1e-9);   // m/k
      const k = zahlVon("federkonstante"), ms = zahlVon("masse");
      let a = lo, b = hi;
      if (feld === "masse" && k !== null) { a = Math.max(lo, k * kMin); b = Math.min(hi, k * kMax); }
      if (feld === "federkonstante" && ms !== null) { a = Math.max(lo, ms / kMax); b = Math.min(hi, ms / kMin); }
      if (a <= b) { lo = a; hi = b; }
    }
    if (m === "wurf" && feld === "winkel" && !(zahlVon("hoehe") !== null)) lo = Math.max(lo, g.schritt);
    kopie.parameter = setzePfad(p, feld.split("."), clamp(wert, lo, hi));
    return kopie as T;
  } catch {
    return input;
  }
}
