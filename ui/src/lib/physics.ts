// Rechenkern für den Baustein `simulation` (Plan docs/ui-p5-plan.md, Abschnitte 2 bis 6, P5a): fünf feste Modelle mit festem
// Zeitschritt. Reine Funktionen ohne DOM, ohne Zeitgeber, ohne Paket und ohne Zufall ohne Startwert. Das Ergebnis hängt nur von
// der Eingabe ab, nie von der Bildrate oder der Uhr: ein Teilschritt dauert immer gleich lang in Modellzeit, die Bildrate
// bestimmt nur, wie viele Teilschritte je Bild gerechnet werden. Das Backend prüft die Eingabe; hier wird trotzdem alles noch
// einmal begrenzt (die Mock-Demo umgeht das Backend). Nichts wirft, keine Schleife läuft ohne Grenze, und jede Zahl, die das
// Modul verlässt, ist endlich, sonst steht der Zustand auf „instabil“.
// Verfahren: Pendel und Feder mit Geschwindigkeits-Verlet, Dämpfung exakt als Faktor vor und nach dem Schritt (die Energie fällt
// dann nur); Wurf ohne Luftwiderstand geschlossen, mit Luftwiderstand fester Schritt (Schwerkraft und Bremsung je exakt, im
// Wechsel); Umlauf geschlossen über die Kepler-Gleichung; Gas mit festem Schritt, elastischen Stößen über ein Raster und Wänden.

export type SimModell = "pendel" | "feder" | "wurf" | "umlauf" | "gas";
export type Farbe = "arc" | "amber" | "ok" | "warn" | "alarm" | "text" | "gedaempft";
export type Pt = [number, number];
/** `laeuft`: rechnet weiter; `gelandet`: Wurf am Boden (Ende); `instabil`: eine Zahl war nicht endlich oder die Eingabe unbrauchbar. */
export type SimPhase = "laeuft" | "gelandet" | "instabil";

export interface PendelParameter { laenge: number; winkel: number; anfangsgeschwindigkeit: number; daempfung: number; g: number }
export interface FederParameter { masse: number; federkonstante: number; auslenkung: number; daempfung: number }
export interface WurfParameter { geschwindigkeit: number; winkel: number; hoehe: number; g: number; luftwiderstand: number }
export interface UmlaufKoerper { name: string; abstand: number; exzentrizitaet: number; phase: number; farbe: Farbe }
export interface UmlaufParameter { zentralmasse: number; koerper: UmlaufKoerper[] }
export interface GasParameter {
  anzahl: number; kasten: [number, number]; radius: number; geschwindigkeit: number; schwerkraft: number; stoesse: boolean; startwert: number;
}
interface Gemeinsam { laufzeit: number; tempo: number; spur: boolean; beschreibung: string }
/** Eingabe wie vom Backend geprüft (Standardwerte gefüllt). Einheiten: SI; `umlauf` in AE, Jahren, Sonnenmassen; `gas` in „Einheiten“. */
export type SimInput = Gemeinsam & (
  | { modell: "pendel"; parameter: PendelParameter }
  | { modell: "feder"; parameter: FederParameter }
  | { modell: "wurf"; parameter: WurfParameter }
  | { modell: "umlauf"; parameter: UmlaufParameter }
  | { modell: "gas"; parameter: GasParameter });
/** Begrenzte Eingabe. `angepasst` nennt jedes Feld, das fehlte, kaputt war oder begrenzt wurde; `ungueltig`: Modell unbekannt. */
export type SimConfig = SimInput & { angepasst: string[]; ungueltig: boolean };

/** Bildausschnitt in Modelleinheiten (y nach oben), einmal vorab gerechnet, damit das Bild nicht springt. */
export interface Ausschnitt { minX: number; maxX: number; minY: number; maxY: number }
/** Ein Körper zum Zeichnen. `r` ist nur beim Gas ein echter Radius (Modelleinheiten), sonst 0 = Zeichen in fester Größe. */
export interface SimKoerper { x: number; y: number; r: number; farbe: Farbe; name: string }
export interface Kennwert { id: string; name: string; wert: number; einheit: string; text: string }
/** Geschwindigkeitsverteilung: 11 Grenzen, 10 Klassen; die letzte Klasse nimmt auch alles darüber. */
export interface Verteilung { grenzen: number[]; anzahl: number[] }
export interface SimSnapshot {
  modell: SimModell;
  /** Modellzeit (Sekunden, bei `umlauf` Jahre). */
  zeit: number;
  einheit: "s" | "Jahre";
  phase: SimPhase;
  koerper: SimKoerper[];
  /** Aufhängung (Pendel), Wand (Feder), Zentralmasse (Umlauf); sonst null. */
  anker: Pt | null;
  ausschnitt: Ausschnitt;
  kennwerte: Kennwert[];
  verteilung: Verteilung | null;
}
/** Standbild für „weniger Bewegung“. `kurve`: Punkte (Zeit in s, Wert); `bahn`/`punkte`: Lagen in Modelleinheiten. */
export type Standbild =
  | { modell: "pendel" | "feder"; start: SimSnapshot; kurve: Pt[]; groesse: string; einheit: string; dauer: number }
  | { modell: "wurf"; start: SimSnapshot; bahn: Pt[]; gipfel: Pt; aufprall: Pt; flugzeit: number; vollstaendig: boolean }
  | { modell: "umlauf"; start: SimSnapshot; bahnen: { name: string; farbe: Farbe; punkte: Pt[] }[] }
  | { modell: "gas"; start: SimSnapshot; verteilung: Verteilung; zeit: number };
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
export type SimKern = PendelKern | FederKern | WurfKern | UmlaufKern | GasKern;

/** Zustand einer Simulation. `advance` ändert ihn an Ort und Stelle; `kern` ist innen und nur für Tests lesbar. */
export interface SimState {
  readonly config: SimConfig;
  readonly modell: SimModell;
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

/** Parameterzahl ohne überflüssige Nullen: 1 → „1“, 9.81 → „9,81“, 0.017 → „0,017“. */
export function formatZahl(x: number): string {
  if (!fin(x) || Math.abs(x) >= 1e15) return "–";
  const a = Math.abs(x);
  if (a < 1e-12) return "0";
  const st = a >= 100 ? 0 : a >= 10 ? 1 : a >= 1 ? 2 : Math.min(12, 2 - Math.floor(Math.log10(a)));
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

/** Begrenzt eine Eingabe auf die Grenzen des Plans. Wirft nie; Fehlendes wird mit Standardwerten gefüllt und in `angepasst` genannt. */
export function normalizeSim(input: unknown): SimConfig {
  try {
    return normalisiere(input);
  } catch {
    return normalisiere(null);
  }
}

function normalisiere(input: unknown): SimConfig {
  const fix: string[] = [];
  const src: Obj = isObj(input) ? input : {};
  const m = own(src, "modell");
  const bekannt = typeof m === "string" && (MODELLE as readonly string[]).includes(m);
  if (!bekannt) fix.push("modell");
  const rawP = own(src, "parameter");
  const p: Obj = isObj(rawP) ? rawP : {};
  if (!isObj(rawP)) fix.push("parameter");
  const laufzeit = zahl(src, "laufzeit", 30, 5, 60, fix, "");
  let tempo = zahl(src, "tempo", 0, 0, 100, fix, "");
  if (tempo > 0 && tempo < 0.1) { tempo = 0.1; fix.push("tempo"); }
  const spur = bool(src, "spur", true, fix, "");
  const basis = { laufzeit, tempo, spur, beschreibung: text(own(src, "beschreibung"), 400), angepasst: fix, ungueltig: !bekannt };
  const P = "parameter.";
  switch (bekannt ? (m as SimModell) : "pendel") {
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
    case "wurf":
      return {
        ...basis, modell: "wurf", parameter: {
          geschwindigkeit: zahl(p, "geschwindigkeit", 20, 0.1, 1000, fix, P), winkel: zahl(p, "winkel", 45, -90, 90, fix, P),
          hoehe: zahl(p, "hoehe", 0, 0, 10000, fix, P), g: zahl(p, "g", 9.81, 0.1, 100, fix, P),
          luftwiderstand: zahl(p, "luftwiderstand", 0, 0, 1, fix, P),
        },
      };
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
        koerper.push({
          name: text(own(k, "name"), 30) || `Körper ${i + 1}`, abstand: zahl(k, "abstand", 1, 0.01, 1000, fix, pf),
          exzentrizitaet: zahl(k, "exzentrizitaet", 0, 0, 0.95, fix, pf),
          phase: typeof ph === "number" && fin(ph) ? ((ph % 360) + 360) % 360 : 0,
          farbe: (FARBEN as readonly unknown[]).includes(f) ? (f as Farbe) : "arc",
        });
      });
      if (!koerper.length) koerper.push({ name: "Körper 1", abstand: 1, exzentrizitaet: 0, phase: 0, farbe: "arc" });
      return { ...basis, modell: "umlauf", parameter: { zentralmasse, koerper } };
    }
    case "gas": {
      const anzahl = Math.round(zahl(p, "anzahl", 100, 2, GAS_MAX, fix, P));
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
      return {
        ...basis, modell: "gas", parameter: {
          anzahl, kasten: [b, h], radius, geschwindigkeit,
          schwerkraft: zahl(p, "schwerkraft", 0, 0, 100, fix, P), stoesse: bool(p, "stoesse", true, fix, P),
          startwert: Math.floor(zahl(p, "startwert", 1, 0, 2147483647, fix, P)),
        },
      };
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

function pendelSchritt(k: PendelKern, dt: number): void {
  k.om *= k.damp;
  k.om += 0.5 * dt * k.a;
  k.th += dt * k.om;
  if (k.th > Math.PI || k.th < -Math.PI) k.th -= TAU * Math.round(k.th / TAU);
  k.a = -k.w2 * Math.sin(k.th);
  k.om += 0.5 * dt * k.a;
  k.om *= k.damp;
}

interface Teile { kern: SimKern; dt: number; periode: number; ausschnitt: Ausschnitt; text: string; koerper: number; einheit: "s" | "Jahre"; voraus: number }

function pendelTeile(p: PendelParameter): Teile {
  const L = p.laenge, w2 = p.g / L, w0 = Math.sqrt(w2), T0 = TAU / w0, c = p.daempfung;
  const th = p.winkel * RAD, om = p.anfangsgeschwindigkeit * RAD;
  const E = 0.5 * om * om + w2 * (1 - Math.cos(th)), wb = Math.sqrt(2 * E);
  let dt = T0 / 1000;
  if (wb > 0) dt = Math.min(dt, TAU / (1000 * wb));
  if (c > 0) dt = Math.min(dt, 0.02 / c);
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

/** Für Verlet am harmonischen Schwinger exakt erhaltene Energie: ½mv² + ½kx²(1 − ω²dt²/4). */
const federEnergie = (k: FederKern, dt: number): number => 0.5 * k.m * k.v * k.v + 0.5 * k.k * k.x * k.x * (1 - (k.w2 * dt * dt) / 4);

function federSchritt(k: FederKern, dt: number): void {
  k.v *= k.damp;
  k.v += 0.5 * dt * k.a;
  k.x += dt * k.v;
  k.a = -k.w2 * k.x;
  k.v += 0.5 * dt * k.a;
  k.v *= k.damp;
}

function federTeile(p: FederParameter): Teile {
  const m = p.masse, kk = p.federkonstante, w2 = kk / m, w0 = Math.sqrt(w2), T = TAU / w0, c = p.daempfung / m, A = p.auslenkung;
  let dt = T / 1000;
  if (c > 0) dt = Math.min(dt, 0.02 / c);
  const zeta = c / (2 * w0), S = Math.abs(A) > 0 ? Math.abs(A) : 1;
  const kern: FederKern = { art: "feder", m, k: kk, w2, c, damp: Math.exp((-c * dt) / 2), x: A, v: 0, a: -w2 * A, E0: 0, T, S, zeta };
  kern.E0 = federEnergie(kern, dt);
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

function gasWand(k: GasKern, i: number): void {
  const r = k.r, bx = k.b - r, by = k.h - r;
  let x = k.px[i], y = k.py[i];
  if (x < r) { x = Math.min(2 * r - x, bx); k.vx[i] = Math.abs(k.vx[i]); }
  else if (x > bx) { x = Math.max(2 * bx - x, r); k.vx[i] = -Math.abs(k.vx[i]); }
  if (y < r) { y = Math.min(2 * r - y, by); k.vy[i] = Math.abs(k.vy[i]); }
  else if (y > by) { y = Math.max(2 * by - y, r); k.vy[i] = -Math.abs(k.vy[i]); }
  k.px[i] = x; k.py[i] = y;
}

/** Elastische Stöße gleicher Massen, gefunden über ein gleichmäßiges Raster (Zelle ≥ Durchmesser, halbe Nachbarschaft). */
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
  for (let cy = 0; cy < ny; cy++) for (let cx = 0; cx < nx; cx++) {
    const z = cx + cy * nx, s1 = zaehler[z + 1];
    for (let a = zaehler[z]; a < s1; a++) {
      const i = folge[a];
      for (let b = a + 1; b < s1; b++) paar(i, folge[b]);
      mitZelle(i, cx + 1, cy); mitZelle(i, cx - 1, cy + 1); mitZelle(i, cx, cy + 1); mitZelle(i, cx + 1, cy + 1);
    }
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
  const nx = clamp(Math.floor(b / (2 * r)), 1, 64), ny = clamp(Math.floor(h / (2 * r)), 1, 64);
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

// --- Zustand -----------------------------------------------------------------------------------------------------------

function teileFuer(cfg: SimConfig, budget: number): Teile {
  switch (cfg.modell) {
    case "pendel": return pendelTeile(cfg.parameter);
    case "feder": return federTeile(cfg.parameter);
    case "wurf": return wurfTeile(cfg.parameter, budget);
    case "umlauf": return umlaufTeile(cfg.parameter);
    case "gas": return gasTeile(cfg.parameter);
  }
}

function kernEndlich(k: SimKern): boolean {
  switch (k.art) {
    case "pendel": return fin(k.th) && fin(k.om) && fin(k.a);
    case "feder": return fin(k.x) && fin(k.v) && fin(k.a);
    case "wurf": return fin(k.x) && fin(k.y) && fin(k.vx) && fin(k.vy);
    case "umlauf": return k.bahnen.every((b) => fin(b.E));
    case "gas":
      for (let i = 0; i < k.N; i++) if (!fin(k.px[i]) || !fin(k.py[i]) || !fin(k.vx[i]) || !fin(k.vy[i])) return false;
      return true;
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

function baue(cfg: SimConfig): SimState {
  const t = teileFuer(cfg, VORAUS_BUDGET);
  if (t.kern.art === "gas" && t.kern.rKleiner) cfg.angepasst.push("parameter.radius");
  const auto = cfg.modell === "gas" ? 1 : clamp(t.periode > 0 && fin(t.periode) ? t.periode / 4 : 1, 1e-6, 1e7);
  const s: SimState = {
    config: cfg, modell: cfg.modell, dt: t.dt, tempo: cfg.tempo > 0 ? cfg.tempo : auto, koerper: t.koerper, ausschnitt: t.ausschnitt,
    text: t.text, einheit: t.einheit, periode: t.periode, startBild: null as unknown as SimSnapshot,
    phase: cfg.ungueltig ? "instabil" : t.kern.art === "wurf" && t.kern.gelandet ? "gelandet" : "laeuft",
    schritt: 0, zeit: 0, vorausSchritte: t.voraus, soll: 0, kern: t.kern, bild: null,
  };
  if (!(s.dt > 0 && fin(s.dt)) || !kernEndlich(s.kern)) s.phase = "instabil";
  (s as { startBild: SimSnapshot }).startBild = snapshot(s);
  if (!isFiniteSnapshot(s.startBild)) s.phase = "instabil";
  return s;
}

function einSchritt(s: SimState): void {
  const k = s.kern;
  switch (k.art) {
    case "pendel": pendelSchritt(k, s.dt); break;
    case "feder": federSchritt(k, s.dt); break;
    case "wurf": wurfSchritt(k, s.dt, s.schritt * s.dt); break;
    case "gas": gasSchritt(k, s.dt); break;
    case "umlauf": break;
  }
  s.schritt++;
}

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
    if (k.art === "umlauf" || (k.art === "wurf" && k.geschlossen)) {
      state.schritt = ziel;
      state.zeit = ziel * state.dt;
      if (k.art === "umlauf") umlaufStellen(k, state.zeit);
      else { wurfAuswerten(k, state.zeit); if (k.gelandet) { state.zeit = k.landezeit; state.phase = "gelandet"; } }
      out = { schritte: n, koerperSchritte: state.koerper, begrenzt: false };
    } else {
      const mb = fin(maxBodySteps) && maxBodySteps > 0 ? Math.min(maxBodySteps, MAX_CALL) : MAX_CALL;
      const m = Math.min(n, Math.max(1, Math.floor(mb / state.koerper)));
      let done = 0;
      while (done < m) {
        einSchritt(state);
        done++;
        if (k.art === "wurf" && k.gelandet) break;
      }
      const gelandet = k.art === "wurf" && k.gelandet;
      state.zeit = gelandet ? (k as WurfKern).landezeit : state.schritt * state.dt;
      if (gelandet) state.phase = "gelandet";
      const begrenzt = done < n && !gelandet;
      if (begrenzt) state.soll = state.schritt * state.dt;
      out = { schritte: done, koerperSchritte: done * state.koerper, begrenzt };
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
            kw("energie", "Energie in Prozent des Starts", prozent(federEnergie(k, state.dt), k.E0), "%")],
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
    return true;
  } catch {
    return false;
  }
}

// --- Standbild ---------------------------------------------------------------------------------------------------------

/** Standbild für „weniger Bewegung“, einmal gerechnet und gemerkt. Teilt sich die Vorausrechnung (VORAUS_BUDGET) mit
 *  `createSim`. Pendel und Feder: Lage-Zeit-Kurve über drei Schwingungen; Wurf: ganze Bahn mit Gipfel und Aufprall; Umlauf: alle
 *  Bahnen; Gas: Verteilung nach 10 s gerechneter Zeit (passt das nicht ins Budget, mit gröberem Schritt oder kürzer, siehe `zeit`). */
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
