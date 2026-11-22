// Chemie-Kern für den Baustein `teilchen` (Plan docs/ui-p5-plan.md, Abschnitt 7, P5b): Elementliste, Molekül, Schalenmodell und
// Orbital-Wolke. Reine Funktionen ohne DOM, ohne three.js, ohne Zeitgeber, ohne Paket und ohne Zufall ohne Startwert. Das
// Backend prüft die Eingabe; hier wird trotzdem alles noch einmal begrenzt (die Mock-Demo umgeht das Backend). Nichts wirft,
// jede Schleife hat eine feste Grenze, und jede Zahl, die das Modul verlässt, ist endlich.
// Claude schickt nur Elementsymbole, Lagen und Zahlen. Die Orbital-Formel (wasserstoffähnlich, reelle Orbitale, Längen in
// Bohr-Radien) ist fest eingebaut; es gibt keinen Weg, eine Formel von außen auszuwerten.

import { mulberry32, type Farbe } from "./physics";

export type V3 = [number, number, number];
export type TeilchenForm = "molekuel" | "atom" | "orbital";
export type Darstellung = "kugel-stab" | "kalotte";
export type Bindungsordnung = 1 | 2 | 3;
export type OrbitalName =
  | "1s" | "2s" | "2p_x" | "2p_y" | "2p_z" | "3s" | "3p_x" | "3p_y" | "3p_z"
  | "3d_xy" | "3d_xz" | "3d_yz" | "3d_x2-y2" | "3d_z2";

/** Ein Element der festen Liste. Radien in Ångström; `farbe` nur aus der Palette (das Symbol steht immer als Text daneben). */
export interface ChemElement {
  readonly symbol: string;
  readonly z: number;
  readonly name: string;
  readonly kovalenzradius: number;
  readonly vdwRadius: number;
  readonly farbe: Farbe;
}

export interface MolekuelAtom { element: string; position: V3 }
/** `von` und `bis` sind 0-basierte Atom-Indizes. */
export interface Bindung { von: number; bis: number; ordnung: Bindungsordnung }
export interface Beschriftung { atom: number; text: string }

export interface MolekuelInput {
  form: "molekuel"; name: string; atome: MolekuelAtom[]; bindungen: Bindung[]; beschriftungen: Beschriftung[]; darstellung: Darstellung;
}
/** `neutronen`: -1 = nicht angegeben. `schalen`: Elektronen je Schale von innen nach außen, Summe = Z − ladung. */
export interface AtomInput { form: "atom"; element: string; neutronen: number; ladung: number; schalen: number[] }
export interface OrbitalInput { form: "orbital"; orbital: OrbitalName; punkte: number; startwert: number }
export type TeilchenInput = MolekuelInput | AtomInput | OrbitalInput;
/** Begrenzte Eingabe. `angepasst` nennt jedes Feld, das kaputt war, ersetzt, gerundet, gekürzt oder begrenzt wurde (fehlende
 *  freiwillige Felder bekommen still ihren Standard); `ungueltig`: die Eingabe ist so nicht darstellbar (unbekannte Form, unbekanntes
 *  Element bei `atom`/`orbital`, unbekanntes Orbital, falsche Schalensumme, Molekül ohne gültiges Atom). */
export type TeilchenConfig = TeilchenInput & { typ: "teilchen"; angepasst: string[]; ungueltig: boolean };
export type MolekuelConfig = Extract<TeilchenConfig, { form: "molekuel" }>;
export type AtomConfig = Extract<TeilchenConfig, { form: "atom" }>;
export type OrbitalConfig = Extract<TeilchenConfig, { form: "orbital" }>;

export interface GeoAtom {
  index: number;
  element: string;
  name: string;
  farbe: Farbe;
  /** Lage um den Mittelpunkt der Hüllbox verschoben (Å). */
  position: V3;
  /** Kugelradius für die gewählte Darstellung (Å). */
  radius: number;
  radiusKugelStab: number;
  radiusKalotte: number;
}
export interface GeoBindung extends Bindung { laenge: number }
/** Zeile der Atomtabelle: Lage wie eingegeben (Å), mit Dezimalkomma. */
export interface AtomZeile { index: number; symbol: string; name: string; koordinaten: [string, string, string]; lage: string }
export interface MolekuelGeometrie {
  atome: GeoAtom[];
  bindungen: GeoBindung[];
  /** true: keine Bindungen angegeben, aus Abständen gerechnet. */
  bindungenAbgeleitet: boolean;
  beschriftungen: Beschriftung[];
  darstellung: Darstellung;
  /** Mittelpunkt der Hüllbox in Eingabe-Koordinaten (Å); `atome[i].position` ist relativ dazu. */
  zentrum: V3;
  /** Radius einer Kugel um den Ursprung, die alle Atomkugeln der gewählten Darstellung enthält (Å). */
  radius: number;
  atomzahl: number;
  bindungszahl: number;
  summenformel: string;
  text: string;
  zeilen: AtomZeile[];
  /** true: die Eingabe war ungültig; dann ohne Atome und mit neutralem Text. */
  ungueltig: boolean;
}
export interface AtomModell {
  symbol: string;
  name: string;
  farbe: Farbe;
  z: number;
  protonen: number;
  /** null: nicht angegeben. */
  neutronen: number | null;
  /** Z + neutronen, null ohne Neutronen. */
  massenzahl: number | null;
  ladung: number;
  elektronen: number;
  /** Elektronen je Schale von innen nach außen, ohne leere Schalen am Ende. */
  schalen: number[];
  /** „einfach positiv geladen“ usw., leer bei Ladung 0. */
  ladungText: string;
  text: string;
  ungueltig: boolean;
}
export type Phase = 1 | -1;
export interface OrbitalWolke {
  orbital: OrbitalName;
  /** Verlangte Punktzahl. */
  soll: number;
  /** Wirklich gezogene Punkte (kleiner als `soll` nur, wenn die Versuchsgrenze erreicht wurde). */
  anzahl: number;
  vollstaendig: boolean;
  /** x, y, z je Punkt hintereinander, Länge 3 × anzahl, in Bohr-Radien. */
  positionen: Float32Array;
  /** Vorzeichen von ψ je Punkt: +1 „Phase plus“, -1 „Phase minus“. */
  phasen: Int8Array;
  plus: number;
  minus: number;
  /** Abstand des fernsten Punkts vom Kern (Bohr-Radien); ohne Punkte die Rechengrenze des Orbitals. */
  ausdehnung: number;
  versuche: number;
  beschreibung: string;
  text: string;
  /** true: die Eingabe war ungültig; dann ohne Punkte und mit neutralem Text. */
  ungueltig: boolean;
}

export const FORMEN: readonly TeilchenForm[] = ["molekuel", "atom", "orbital"];
export const ORBITALE: readonly OrbitalName[] = [
  "1s", "2s", "2p_x", "2p_y", "2p_z", "3s", "3p_x", "3p_y", "3p_z", "3d_xy", "3d_xz", "3d_yz", "3d_x2-y2", "3d_z2",
];
export const ATOME_MAX = 300;
export const BINDUNGEN_MAX = 400;
export const BESCHRIFTUNGEN_MAX = 20;
/** Höchstens so viele Bindungen je Atom, wenn sie aus Abständen gerechnet werden. */
export const BINDUNGEN_JE_ATOM = 6;
export const LAGE_MAX = 200;
export const PUNKTE_MIN = 500;
export const PUNKTE_MAX = 5000;
export const PUNKTE_STANDARD = 2500;
/** Höchstens so viele Versuche je verlangtem Punkt beim Ziehen der Orbital-Wolke. */
export const VERSUCHE_JE_PUNKT = 200;
/** Farben der beiden Phasen (zusätzlich immer als Wort). */
export const PHASEN_FARBE: Readonly<Record<"plus" | "minus", Farbe>> = { plus: "arc", minus: "amber" };
export const phaseWort = (p: Phase): string => (p < 0 ? "Phase minus" : "Phase plus");

/** Ersatzwerte für Elemente ohne gut bekannten Radius. */
export const KOVALENZ_ERSATZ = 1.5;
export const VDW_ERSATZ = 2.0;

const fin = Number.isFinite;
const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));

// --- Elemente ----------------------------------------------------------------------------------------------------------

// Symbol, deutscher Name, Kovalenzradius (Einfachbindung, Cordero u. a. 2008; Kohlenstoff sp3, Mn/Fe/Co low spin) und
// Van-der-Waals-Radius (Bondi 1964, ergänzt nach Mantina u. a. 2009), beide in Å; 0 = kein gut bekannter Wert, dann Ersatz.
const DATEN: readonly (readonly [string, string, number, number])[] = [
  ["H", "Wasserstoff", 0.31, 1.2], ["He", "Helium", 0.28, 1.4], ["Li", "Lithium", 1.28, 1.82], ["Be", "Beryllium", 0.96, 1.53],
  ["B", "Bor", 0.84, 1.92], ["C", "Kohlenstoff", 0.76, 1.7], ["N", "Stickstoff", 0.71, 1.55], ["O", "Sauerstoff", 0.66, 1.52],
  ["F", "Fluor", 0.57, 1.47], ["Ne", "Neon", 0.58, 1.54], ["Na", "Natrium", 1.66, 2.27], ["Mg", "Magnesium", 1.41, 1.73],
  ["Al", "Aluminium", 1.21, 1.84], ["Si", "Silicium", 1.11, 2.1], ["P", "Phosphor", 1.07, 1.8], ["S", "Schwefel", 1.05, 1.8],
  ["Cl", "Chlor", 1.02, 1.75], ["Ar", "Argon", 1.06, 1.88], ["K", "Kalium", 2.03, 2.75], ["Ca", "Calcium", 1.76, 2.31],
  ["Sc", "Scandium", 1.7, 0], ["Ti", "Titan", 1.6, 0], ["V", "Vanadium", 1.53, 0], ["Cr", "Chrom", 1.39, 0],
  ["Mn", "Mangan", 1.39, 0], ["Fe", "Eisen", 1.32, 0], ["Co", "Cobalt", 1.26, 0], ["Ni", "Nickel", 1.24, 1.63],
  ["Cu", "Kupfer", 1.32, 1.4], ["Zn", "Zink", 1.22, 1.39], ["Ga", "Gallium", 1.22, 1.87], ["Ge", "Germanium", 1.2, 2.11],
  ["As", "Arsen", 1.19, 1.85], ["Se", "Selen", 1.2, 1.9], ["Br", "Brom", 1.2, 1.85], ["Kr", "Krypton", 1.16, 2.02],
  ["Rb", "Rubidium", 2.2, 3.03], ["Sr", "Strontium", 1.95, 2.49], ["Y", "Yttrium", 1.9, 0], ["Zr", "Zirconium", 1.75, 0],
  ["Nb", "Niob", 1.64, 0], ["Mo", "Molybdän", 1.54, 0], ["Tc", "Technetium", 1.47, 0], ["Ru", "Ruthenium", 1.46, 0],
  ["Rh", "Rhodium", 1.42, 0], ["Pd", "Palladium", 1.39, 1.63], ["Ag", "Silber", 1.45, 1.72], ["Cd", "Cadmium", 1.44, 1.58],
  ["In", "Indium", 1.42, 1.93], ["Sn", "Zinn", 1.39, 2.17], ["Sb", "Antimon", 1.39, 2.06], ["Te", "Tellur", 1.38, 2.06],
  ["I", "Iod", 1.39, 1.98], ["Xe", "Xenon", 1.4, 2.16], ["Cs", "Caesium", 2.44, 3.43], ["Ba", "Barium", 2.15, 2.68],
  ["La", "Lanthan", 2.07, 0], ["Ce", "Cer", 2.04, 0], ["Pr", "Praseodym", 2.03, 0], ["Nd", "Neodym", 2.01, 0],
  ["Pm", "Promethium", 1.99, 0], ["Sm", "Samarium", 1.98, 0], ["Eu", "Europium", 1.98, 0], ["Gd", "Gadolinium", 1.96, 0],
  ["Tb", "Terbium", 1.94, 0], ["Dy", "Dysprosium", 1.92, 0], ["Ho", "Holmium", 1.92, 0], ["Er", "Erbium", 1.89, 0],
  ["Tm", "Thulium", 1.9, 0], ["Yb", "Ytterbium", 1.87, 0], ["Lu", "Lutetium", 1.87, 0], ["Hf", "Hafnium", 1.75, 0],
  ["Ta", "Tantal", 1.7, 0], ["W", "Wolfram", 1.62, 0], ["Re", "Rhenium", 1.51, 0], ["Os", "Osmium", 1.44, 0],
  ["Ir", "Iridium", 1.41, 0], ["Pt", "Platin", 1.36, 1.75], ["Au", "Gold", 1.36, 1.66], ["Hg", "Quecksilber", 1.32, 1.55],
  ["Tl", "Thallium", 1.45, 1.96], ["Pb", "Blei", 1.46, 2.02], ["Bi", "Bismut", 1.48, 2.07], ["Po", "Polonium", 1.4, 1.97],
  ["At", "Astat", 1.5, 2.02], ["Rn", "Radon", 1.5, 2.2], ["Fr", "Francium", 2.6, 3.48], ["Ra", "Radium", 2.21, 2.83],
  ["Ac", "Actinium", 2.15, 0], ["Th", "Thorium", 2.06, 0], ["Pa", "Protactinium", 2.0, 0], ["U", "Uran", 1.96, 1.86],
  ["Np", "Neptunium", 1.9, 0], ["Pu", "Plutonium", 1.87, 0], ["Am", "Americium", 1.8, 0], ["Cm", "Curium", 1.69, 0],
  ["Bk", "Berkelium", 0, 0], ["Cf", "Californium", 0, 0], ["Es", "Einsteinium", 0, 0], ["Fm", "Fermium", 0, 0],
  ["Md", "Mendelevium", 0, 0], ["No", "Nobelium", 0, 0], ["Lr", "Lawrencium", 0, 0], ["Rf", "Rutherfordium", 0, 0],
  ["Db", "Dubnium", 0, 0], ["Sg", "Seaborgium", 0, 0], ["Bh", "Bohrium", 0, 0], ["Hs", "Hassium", 0, 0],
  ["Mt", "Meitnerium", 0, 0], ["Ds", "Darmstadtium", 0, 0], ["Rg", "Roentgenium", 0, 0], ["Cn", "Copernicium", 0, 0],
  ["Nh", "Nihonium", 0, 0], ["Fl", "Flerovium", 0, 0], ["Mc", "Moscovium", 0, 0], ["Lv", "Livermorium", 0, 0],
  ["Ts", "Tenness", 0, 0], ["Og", "Oganesson", 0, 0],
];

const FARBE_VON: Readonly<Record<string, Farbe>> = {
  O: "alarm", N: "arc", H: "text", C: "gedaempft", S: "warn", F: "ok", Cl: "ok", Br: "ok", I: "ok", At: "ok",
};

/** Alle 118 Elemente in der Reihenfolge der Ordnungszahl (Index = Z − 1). */
export const ELEMENTE: readonly ChemElement[] = Object.freeze(DATEN.map(([symbol, name, kov, vdw], i) => Object.freeze({
  symbol, z: i + 1, name, kovalenzradius: kov > 0 ? kov : KOVALENZ_ERSATZ, vdwRadius: vdw > 0 ? vdw : VDW_ERSATZ,
  farbe: Object.prototype.hasOwnProperty.call(FARBE_VON, symbol) ? FARBE_VON[symbol] : "amber",
})));

const NACH_SYMBOL: ReadonlyMap<string, ChemElement> = new Map(ELEMENTE.map((e) => [e.symbol, e]));

/** Element zum Symbol (genaue Schreibweise, „Na“, nicht „na“), sonst undefined. */
export function elementNachSymbol(symbol: unknown): ChemElement | undefined {
  return typeof symbol === "string" ? NACH_SYMBOL.get(symbol) : undefined;
}

/** Element zur Ordnungszahl 1 bis 118, sonst undefined. */
export function elementNachZ(z: unknown): ChemElement | undefined {
  return typeof z === "number" && Number.isInteger(z) && z >= 1 && z <= ELEMENTE.length ? ELEMENTE[z - 1] : undefined;
}

// --- Zahlen und Texte --------------------------------------------------------------------------------------------------

/** Feste Nachkommastellen mit Dezimalkomma: komma(-0.4567) = „-0,46“, komma(-0.001) = „0,00“. */
export function komma(x: number, stellen = 2): string {
  if (!fin(x)) return "–";
  const st = clamp(Math.round(stellen) || 0, 0, 6);
  const s = x.toFixed(st);
  return (/[1-9]/.test(s) ? s : s.replace("-", "")).replace(".", ",");
}

const mehrzahl = (n: number, eins: string, viele: string): string => `${n} ${n === 1 ? eins : viele}`;

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const own = (o: Obj, k: string): unknown => (Object.prototype.hasOwnProperty.call(o, k) ? o[k] : undefined);
const hat = (o: Obj, k: string): boolean => Object.prototype.hasOwnProperty.call(o, k);
const STEUER = /[\u0000-\u001f\u007f-\u009f\u200b-\u200f\u2028-\u202e\u2066-\u2069\ufeff]/g;
const text = (v: unknown, max: number): string => (typeof v === "string" ? v.replace(STEUER, "").slice(0, max).trim() : "");
/** Trug die Eingabe selbst schon `ungueltig: true` (oder ist sie kein Objekt)? Wirft das Lesen, gilt sie als ungültig. */
function warUngueltig(c: unknown): boolean {
  try {
    return !isObj(c) || own(c, "ungueltig") === true;
  } catch {
    return true;
  }
}
const ganz = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v);

/** Ganze Zahl in [lo, hi]; fehlt sie, gilt `def` still; kaputt, gerundet oder begrenzt wird notiert. */
function ganzzahl(o: Obj, key: string, def: number, lo: number, hi: number, fix: string[], pfad: string): number {
  if (!hat(o, key)) return def;
  const v = own(o, key);
  if (typeof v !== "number" || !fin(v)) { fix.push(pfad + key); return def; }
  const r = clamp(Math.round(v), lo, hi);
  if (r !== v) fix.push(pfad + key);
  return r;
}

// --- Eingabe begrenzen -------------------------------------------------------------------------------------------------

/** Begrenzt eine `teilchen`-Eingabe auf die Grenzen des Plans. Wirft nie. Unbekannte Form: Ersatz Wasserstoff-Atom, ungültig. */
export function normalizeTeilchen(input: unknown): TeilchenConfig {
  try {
    return normalisiere(input);
  } catch {
    const ersatz = ersatzAtom(["intern"]);
    return ersatz;
  }
}

const ersatzAtom = (fix: string[]): TeilchenConfig =>
  ({ typ: "teilchen", form: "atom", element: "H", neutronen: -1, ladung: 0, schalen: [1], angepasst: fix, ungueltig: true });

function normalisiere(input: unknown): TeilchenConfig {
  const fix: string[] = [];
  const src: Obj = isObj(input) ? input : {};
  if (!isObj(input)) fix.push("eingabe");
  if (hat(src, "typ") && own(src, "typ") !== "teilchen") fix.push("typ");
  const form = own(src, "form");
  switch (form) {
    case "molekuel": return molekuelNorm(src, fix);
    case "atom": return atomNorm(src, fix);
    case "orbital": return orbitalNorm(src, fix);
    default:
      fix.push("form");
      return ersatzAtom(fix);
  }
}

function lage(roh: unknown, fix: string[], pfad: string): V3 {
  if (!Array.isArray(roh) || roh.length !== 3) { fix.push(pfad); return [0, 0, 0]; }
  let geaendert = false;
  const p: V3 = [0, 0, 0];
  for (let k = 0; k < 3; k++) {
    const v: unknown = roh[k];
    if (typeof v !== "number" || !fin(v)) { geaendert = true; continue; }
    p[k] = clamp(v, -LAGE_MAX, LAGE_MAX);
    if (p[k] !== v) geaendert = true;
  }
  if (geaendert) fix.push(pfad);
  return p;
}

function molekuelNorm(src: Obj, fix: string[]): MolekuelConfig {
  const rohName = own(src, "name"), name = text(rohName, 60);
  if (rohName !== undefined && rohName !== name) fix.push("name");
  const rohD = own(src, "darstellung");
  const darstellung: Darstellung = rohD === "kalotte" ? "kalotte" : "kugel-stab";
  if (rohD !== undefined && rohD !== darstellung) fix.push("darstellung");

  // Atome: höchstens 300; unbekannte Elemente fallen mit Hinweis weg, die Indizes der übrigen rücken nach (Tabelle `neu`).
  const rohA = own(src, "atome");
  const listeA: unknown[] = Array.isArray(rohA) ? rohA.slice(0, ATOME_MAX) : [];
  if (!Array.isArray(rohA) || rohA.length > ATOME_MAX) fix.push("atome");
  const atome: MolekuelAtom[] = [];
  const neu: number[] = [];
  for (let i = 0; i < listeA.length; i++) {
    const a = listeA[i], pf = `atome.${i}`;
    neu.push(-1);
    if (!isObj(a)) { fix.push(pf); continue; }
    const el = elementNachSymbol(own(a, "element"));
    if (!el) { fix.push(pf + ".element"); continue; }
    neu[i] = atome.length;
    atome.push({ element: el.symbol, position: lage(own(a, "position"), fix, pf + ".position") });
  }
  const n = atome.length;
  const index = (v: unknown): number => (ganz(v) && v >= 0 && v < neu.length ? neu[v] : -1);

  // Bindungen: Indizes vorhanden, von ≠ bis, kein Paar doppelt, Ordnung 1 bis 3; sonst fällt die Bindung mit Hinweis weg.
  const bindungen: Bindung[] = [];
  const rohB = own(src, "bindungen");
  if (rohB !== undefined) {
    const listeB: unknown[] = Array.isArray(rohB) ? rohB.slice(0, BINDUNGEN_MAX) : [];
    if (!Array.isArray(rohB) || rohB.length > BINDUNGEN_MAX) fix.push("bindungen");
    const gesehen = new Set<number>();
    for (let i = 0; i < listeB.length; i++) {
      const b = listeB[i], pf = `bindungen.${i}`;
      if (!isObj(b)) { fix.push(pf); continue; }
      const von = index(own(b, "von")), bis = index(own(b, "bis"));
      if (von < 0 || bis < 0 || von === bis) { fix.push(pf); continue; }
      const key = Math.min(von, bis) * ATOME_MAX + Math.max(von, bis);
      if (gesehen.has(key)) { fix.push(pf); continue; }
      gesehen.add(key);
      const rohO = own(b, "ordnung");
      let ordnung: Bindungsordnung = 1;
      if (rohO === 1 || rohO === 2 || rohO === 3) ordnung = rohO;
      else {
        if (rohO !== undefined) fix.push(pf + ".ordnung");
        if (typeof rohO === "number" && fin(rohO)) ordnung = clamp(Math.round(rohO), 1, 3) as Bindungsordnung;
      }
      bindungen.push({ von, bis, ordnung });
    }
  }

  const beschriftungen: Beschriftung[] = [];
  const rohL = own(src, "beschriftungen");
  if (rohL !== undefined) {
    const listeL: unknown[] = Array.isArray(rohL) ? rohL.slice(0, BESCHRIFTUNGEN_MAX) : [];
    if (!Array.isArray(rohL) || rohL.length > BESCHRIFTUNGEN_MAX) fix.push("beschriftungen");
    for (let i = 0; i < listeL.length; i++) {
      const l = listeL[i], pf = `beschriftungen.${i}`;
      if (!isObj(l)) { fix.push(pf); continue; }
      const atom = index(own(l, "atom")), rohT = own(l, "text"), t = text(rohT, 40);
      if (atom < 0 || !t) { fix.push(pf); continue; }
      if (t !== rohT) fix.push(pf + ".text");
      beschriftungen.push({ atom, text: t });
    }
  }
  return { typ: "teilchen", form: "molekuel", name, atome, bindungen, beschriftungen, darstellung, angepasst: fix, ungueltig: n === 0 };
}

/** Schalen nach der einfachen Regel 2, 8, 8, 2 (nur bis 20 Elektronen sinnvoll). */
function schalenRegel(elektronen: number): number[] {
  const out: number[] = [];
  let rest = elektronen;
  for (const max of [2, 8, 8, 2]) {
    if (rest <= 0) break;
    const k = Math.min(max, rest);
    out.push(k); rest -= k;
  }
  return out;
}

function atomNorm(src: Obj, fix: string[]): AtomConfig {
  const el = elementNachSymbol(own(src, "element"));
  let ungueltig = false;
  if (!el) { fix.push("element"); ungueltig = true; }
  const z = el ? el.z : 1;
  let neutronen = -1;
  if (hat(src, "neutronen")) {
    const v = own(src, "neutronen");
    if (typeof v !== "number" || !fin(v)) fix.push("neutronen");
    else if (v < 0) { if (v !== -1) fix.push("neutronen"); }
    else { neutronen = clamp(Math.round(v), 0, 200); if (neutronen !== v) fix.push("neutronen"); }
  }
  const ladung = ganzzahl(src, "ladung", 0, -3, 3, fix, "");
  const elektronen = z - ladung;
  if (elektronen < 0) ungueltig = true;                                   // mehr positive Ladung als Protonen
  let schalen: number[];
  const rohS = own(src, "schalen");
  if (rohS === undefined) {
    schalen = schalenRegel(Math.max(0, elektronen));
    // Die Regel 2, 8, 8, 2 stimmt nur bis Ordnungszahl 20 (ab Scandium füllt sich die dritte Schale weiter, auch bei Ionen
    // wie Sc³⁺ mit 18 Elektronen). Darum gilt sie nur bei Z ≤ 20 und Z − ladung ≤ 20, sonst ist `schalen` Pflicht.
    if (z > 20 || elektronen > 20) { fix.push("schalen"); ungueltig = true; }
  } else if (!Array.isArray(rohS)) {
    fix.push("schalen"); ungueltig = true; schalen = schalenRegel(Math.max(0, Math.min(elektronen, 20)));
  } else {
    if (rohS.length > 7) fix.push("schalen");
    schalen = [];
    const liste: unknown[] = rohS.slice(0, 7);
    for (let i = 0; i < liste.length; i++) {
      const v = liste[i];
      if (typeof v !== "number" || !fin(v)) { fix.push(`schalen.${i}`); schalen.push(0); continue; }
      const k = clamp(Math.round(v), 0, 32);
      if (k !== v) fix.push(`schalen.${i}`);
      schalen.push(k);
    }
    if (schalen.reduce((s, k) => s + k, 0) !== elektronen) ungueltig = true;
  }
  return { typ: "teilchen", form: "atom", element: el ? el.symbol : "H", neutronen, ladung, schalen, angepasst: fix, ungueltig };
}

function orbitalNorm(src: Obj, fix: string[]): OrbitalConfig {
  const o = own(src, "orbital");
  const bekannt = typeof o === "string" && (ORBITALE as readonly string[]).includes(o);
  if (!bekannt) fix.push("orbital");
  const punkte = ganzzahl(src, "punkte", PUNKTE_STANDARD, PUNKTE_MIN, PUNKTE_MAX, fix, "");
  let startwert = 1;
  if (hat(src, "startwert")) {
    const v = own(src, "startwert");
    if (typeof v !== "number" || !fin(v)) fix.push("startwert");
    else { startwert = clamp(Math.floor(v), 0, 2147483647); if (startwert !== v) fix.push("startwert"); }
  }
  return {
    typ: "teilchen", form: "orbital", orbital: bekannt ? (o as OrbitalName) : "1s", punkte, startwert, angepasst: fix, ungueltig: !bekannt,
  };
}

// --- Molekül -----------------------------------------------------------------------------------------------------------

/** Summenformel in Hill-Ordnung: mit Kohlenstoff erst C, dann H, dann alphabetisch; ohne Kohlenstoff alles alphabetisch.
 *  Anzahl als Ziffern, 1 entfällt: Ethanol „C2H6O“, Wasser „H2O“, Kochsalz „ClNa“. Unbekannte Symbole zählen nicht; höchstens
 *  die ersten 300 Atome. */
export function summenformel(atome: readonly { element: string }[]): string {
  try {
    if (!Array.isArray(atome)) return "";
    const anzahl = new Map<string, number>();
    const n = Math.min(atome.length, ATOME_MAX);
    for (let i = 0; i < n; i++) {
      const a: unknown = atome[i];
      const el = isObj(a) ? elementNachSymbol(own(a, "element")) : undefined;
      if (el) anzahl.set(el.symbol, (anzahl.get(el.symbol) ?? 0) + 1);
    }
    const symbole = [...anzahl.keys()].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
    const ordnung = anzahl.has("C") ? ["C", ...(anzahl.has("H") ? ["H"] : []), ...symbole.filter((s) => s !== "C" && s !== "H")] : symbole;
    return ordnung.map((s) => { const k = anzahl.get(s) ?? 0; return k === 1 ? s : `${s}${k}`; }).join("");
  } catch {
    return "";
  }
}

interface Kandidat { i: number; j: number; d: number }

/** Bindungen aus Abständen: Bindung, wenn 0,4 Å < Abstand ≤ 1,2 × (Summe der Kovalenzradien). Gesucht wird über ein Raster
 *  (Zellen so groß wie der größte mögliche Bindungsabstand, nur die 27 Nachbarzellen), jedes Paar höchstens einmal. Höchstens
 *  400 Bindungen und 6 je Atom, die kürzesten zuerst; Ergebnis nach `von`, dann `bis` sortiert (`von` < `bis`), Ordnung 1.
 *  Atome mit unbekanntem Element oder kaputter Lage bekommen keine Bindung; höchstens die ersten 300 Atome. */
export function bindungenAusAbstand(atome: readonly MolekuelAtom[]): Bindung[] {
  try {
    return abstandsBindungen(atome);
  } catch {
    return [];
  }
}

function abstandsBindungen(atome: readonly MolekuelAtom[]): Bindung[] {
  if (!Array.isArray(atome)) return [];
  const n = Math.min(atome.length, ATOME_MAX);
  const xs = new Float64Array(n), ys = new Float64Array(n), zs = new Float64Array(n), rad = new Float64Array(n);
  const gueltig: boolean[] = [];
  let rMax = 0;
  for (let i = 0; i < n; i++) {
    const a: unknown = atome[i];
    gueltig.push(false);
    if (!isObj(a)) continue;
    const el = elementNachSymbol(own(a, "element")), p = own(a, "position");
    if (!el || !Array.isArray(p) || p.length !== 3) continue;
    const [x, y, z] = [p[0], p[1], p[2]];
    if (typeof x !== "number" || typeof y !== "number" || typeof z !== "number" || !fin(x) || !fin(y) || !fin(z)) continue;
    xs[i] = x; ys[i] = y; zs[i] = z; rad[i] = el.kovalenzradius; gueltig[i] = true;
    rMax = Math.max(rMax, el.kovalenzradius);
  }
  const zelle = Math.max(0.5, 2.4 * rMax);
  // Zellnummer je Achse, auf ±20 000 begrenzt (nur für das Raster; die Abstandsprüfung nutzt die echten Lagen). Fallen weit
  // entfernte Atome in dieselbe Randzelle, kostet das nur Prüfungen, keine falsche Bindung.
  const K = 20001, M = 65536;
  const achse = (v: number): number => clamp(Math.floor(v / zelle), -20000, 20000) + K;
  const schluessel = (cx: number, cy: number, cz: number): number => (cx * M + cy) * M + cz;
  const raster = new Map<number, number[]>();
  const cxs = new Int32Array(n), cys = new Int32Array(n), czs = new Int32Array(n);
  for (let i = 0; i < n; i++) {
    if (!gueltig[i]) continue;
    cxs[i] = achse(xs[i]); cys[i] = achse(ys[i]); czs[i] = achse(zs[i]);
    const k = schluessel(cxs[i], cys[i], czs[i]);
    const liste = raster.get(k);
    if (liste) liste.push(i); else raster.set(k, [i]);
  }
  const kandidaten: Kandidat[] = [];
  for (let i = 0; i < n; i++) {
    if (!gueltig[i]) continue;
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) for (let dz = -1; dz <= 1; dz++) {
      const liste = raster.get(schluessel(cxs[i] + dx, cys[i] + dy, czs[i] + dz));
      if (!liste) continue;
      for (const j of liste) {
        if (j <= i) continue;
        const ex = xs[j] - xs[i], ey = ys[j] - ys[i], ez = zs[j] - zs[i];
        const d = Math.sqrt(ex * ex + ey * ey + ez * ez);
        if (d > 0.4 && d <= 1.2 * (rad[i] + rad[j])) kandidaten.push({ i, j, d });
      }
    }
  }
  kandidaten.sort((a, b) => a.d - b.d || a.i - b.i || a.j - b.j);
  const grad = new Int32Array(n);
  const out: Bindung[] = [];
  for (const k of kandidaten) {
    if (out.length >= BINDUNGEN_MAX) break;
    if (grad[k.i] >= BINDUNGEN_JE_ATOM || grad[k.j] >= BINDUNGEN_JE_ATOM) continue;
    grad[k.i]++; grad[k.j]++;
    out.push({ von: k.i, bis: k.j, ordnung: 1 });
  }
  return out.sort((a, b) => a.von - b.von || a.bis - b.bis);
}

/** Radius der Atomkugel: Kugel-Stab etwa 0,3 × Kovalenzradius (mindestens 0,2 Å), Kalotte der Van-der-Waals-Radius. */
export function kugelRadius(el: ChemElement, darstellung: Darstellung): number {
  return darstellung === "kalotte" ? el.vdwRadius : Math.max(0.2, 0.3 * el.kovalenzradius);
}

const leereGeometrie = (darstellung: Darstellung): MolekuelGeometrie => ({
  atome: [], bindungen: [], bindungenAbgeleitet: false, beschriftungen: [], darstellung, zentrum: [0, 0, 0], radius: 1,
  atomzahl: 0, bindungszahl: 0, summenformel: "", text: "Ungültige Molekülangabe.", zeilen: [], ungueltig: true,
});

/** Alles, was die Ansicht zum Zeichnen und für die Textfassung braucht. Wirft nie; die Eingabe wird noch einmal begrenzt. */
export function molekuelGeometrie(config: MolekuelConfig): MolekuelGeometrie {
  let darstellung: Darstellung = "kugel-stab";
  try {
    const cfg = normalizeTeilchen({ ...config, form: "molekuel" }) as MolekuelConfig;
    darstellung = cfg.darstellung;
    if (cfg.ungueltig || warUngueltig(config)) return leereGeometrie(darstellung);
    return geometrie(cfg);
  } catch {
    return leereGeometrie(darstellung);
  }
}

function geometrie(cfg: MolekuelConfig): MolekuelGeometrie {
  const { atome, darstellung } = cfg;
  if (!atome.length) return leereGeometrie(darstellung);
  const min: V3 = [Infinity, Infinity, Infinity], max: V3 = [-Infinity, -Infinity, -Infinity];
  for (const a of atome) for (let k = 0; k < 3; k++) { min[k] = Math.min(min[k], a.position[k]); max[k] = Math.max(max[k], a.position[k]); }
  const zentrum: V3 = [(min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2];
  let radius = 0;
  const geo: GeoAtom[] = atome.map((a, index) => {
    const el = elementNachSymbol(a.element) ?? ELEMENTE[0];
    const position: V3 = [a.position[0] - zentrum[0], a.position[1] - zentrum[1], a.position[2] - zentrum[2]];
    const radiusKugelStab = kugelRadius(el, "kugel-stab"), radiusKalotte = kugelRadius(el, "kalotte");
    const r = darstellung === "kalotte" ? radiusKalotte : radiusKugelStab;
    radius = Math.max(radius, Math.hypot(position[0], position[1], position[2]) + r);
    return { index, element: el.symbol, name: el.name, farbe: el.farbe, position, radius: r, radiusKugelStab, radiusKalotte };
  });
  const abgeleitet = cfg.bindungen.length === 0;
  const roh = abgeleitet ? bindungenAusAbstand(atome) : cfg.bindungen;
  const bindungen: GeoBindung[] = roh.map((b) => {
    const p = atome[b.von].position, q = atome[b.bis].position;
    return { von: b.von, bis: b.bis, ordnung: b.ordnung, laenge: Math.hypot(q[0] - p[0], q[1] - p[1], q[2] - p[2]) };
  });
  const formel = summenformel(atome);
  const text = `Molekül${cfg.name ? " " + cfg.name : ""}, Summenformel ${formel}, ${mehrzahl(atome.length, "Atom", "Atome")}, `
    + `${mehrzahl(bindungen.length, "Bindung", "Bindungen")}.`;
  const zeilen: AtomZeile[] = atome.map((a, index) => {
    const koordinaten: [string, string, string] = [komma(a.position[0]), komma(a.position[1]), komma(a.position[2])];
    return { index, symbol: a.element, name: geo[index].name, koordinaten, lage: koordinaten.join("; ") };
  });
  return {
    atome: geo, bindungen, bindungenAbgeleitet: abgeleitet, beschriftungen: cfg.beschriftungen.map((l) => ({ ...l })), darstellung,
    zentrum, radius: radius > 0 && fin(radius) ? radius : 1, atomzahl: atome.length, bindungszahl: bindungen.length, summenformel: formel,
    text, zeilen, ungueltig: false,
  };
}

// --- Atom (Schalenmodell) ----------------------------------------------------------------------------------------------

const VIELFACH = ["", "einfach", "zweifach", "dreifach"];

/** „einfach positiv geladen“, „zweifach negativ geladen“; leer bei 0. */
export function ladungText(ladung: number): string {
  if (!fin(ladung) || ladung === 0) return "";
  const k = clamp(Math.round(Math.abs(ladung)), 1, 3);
  return `${VIELFACH[k]} ${ladung > 0 ? "positiv" : "negativ"} geladen`;
}

/** Vereinfachtes Schalenmodell mit Textfassung, zum Beispiel „Natrium, 11 Protonen, 12 Neutronen, 11 Elektronen in den Schalen
 *  2, 8, 1. Vereinfachtes Schalenmodell.“ Wirft nie; die Eingabe wird noch einmal begrenzt. */
export function atomModell(config: AtomConfig): AtomModell {
  let cfg: AtomConfig;
  try {
    cfg = normalizeTeilchen({ ...config, form: "atom" }) as AtomConfig;
  } catch {
    cfg = ersatzAtom(["intern"]) as AtomConfig;
  }
  const ungueltig = cfg.ungueltig || warUngueltig(config);
  const el =elementNachSymbol(cfg.element) ?? ELEMENTE[0];
  const neutronen = cfg.neutronen >= 0 ? cfg.neutronen : null;
  const elektronen = Math.max(0, el.z - cfg.ladung);
  const schalen = cfg.schalen.slice();
  while (schalen.length && schalen[schalen.length - 1] === 0) schalen.pop();
  const lt = ladungText(cfg.ladung);
  const teile = [el.name];
  if (lt) teile.push(lt);
  teile.push(mehrzahl(el.z, "Proton", "Protonen"));
  if (neutronen !== null) teile.push(mehrzahl(neutronen, "Neutron", "Neutronen"));
  let e = elektronen === 0 ? "keine Elektronen" : mehrzahl(elektronen, "Elektron", "Elektronen");
  if (elektronen > 0 && schalen.length === 1) e += " in einer Schale";
  else if (elektronen > 0 && schalen.length > 1) e += ` in den Schalen ${schalen.join(", ")}`;
  teile.push(e);
  return {
    symbol: el.symbol, name: el.name, farbe: el.farbe, z: el.z, protonen: el.z, neutronen,
    massenzahl: neutronen !== null ? el.z + neutronen : null, ladung: cfg.ladung, elektronen, schalen, ladungText: lt,
    text: ungueltig ? "Ungültige Atomangabe." : `${teile.join(", ")}. Vereinfachtes Schalenmodell.`, ungueltig,
  };
}

// --- Orbital -----------------------------------------------------------------------------------------------------------

interface OrbitalDef {
  /** Radialteil ohne Normierung, mit richtigem Vorzeichen (r in Bohr-Radien, Kernladung 1). */
  radial: (r: number) => number;
  /** Winkelteil als Polynom der Richtung (Einheitsvektor), ohne Normierung, mit Vorzeichen. */
  winkel: (x: number, y: number, z: number) => number;
  /** Größtes Quadrat des Winkelteils über alle Richtungen. */
  winkelMax: number;
  /** Rechengrenze für r: außerhalb liegt nur ein verschwindender Teil der Aufenthaltswahrscheinlichkeit. */
  rMax: number;
  beschreibung: string;
}

const R1 = (r: number) => Math.exp(-r);
const R2s = (r: number) => (2 - r) * Math.exp(-r / 2);
const R2p = (r: number) => r * Math.exp(-r / 2);
const R3s = (r: number) => (27 - 18 * r + 2 * r * r) * Math.exp(-r / 3);
const R3p = (r: number) => r * (6 - r) * Math.exp(-r / 3);
const R3d = (r: number) => r * r * Math.exp(-r / 3);
const eins = () => 1;
const px = (x: number) => x, py = (_x: number, y: number) => y, pz = (_x: number, _y: number, z: number) => z;
const zweiLappen = (a: string) => `zwei Lappen entlang der ${a}-Achse mit entgegengesetzter Phase`;
const vierZwischen = (a: string, b: string) => `vier Lappen zwischen der ${a}- und der ${b}-Achse, die Phase wechselt von Lappen zu Lappen`;

const ORBITAL_DEF: Readonly<Record<OrbitalName, OrbitalDef>> = {
  "1s": { radial: R1, winkel: eins, winkelMax: 1, rMax: 10, beschreibung: "kugelförmig, überall dieselbe Phase" },
  "2s": { radial: R2s, winkel: eins, winkelMax: 1, rMax: 25, beschreibung: "kugelförmig mit einer kugelförmigen Knotenfläche, innen und außen entgegengesetzte Phase" },
  "2p_x": { radial: R2p, winkel: px, winkelMax: 1, rMax: 25, beschreibung: zweiLappen("x") },
  "2p_y": { radial: R2p, winkel: py, winkelMax: 1, rMax: 25, beschreibung: zweiLappen("y") },
  "2p_z": { radial: R2p, winkel: pz, winkelMax: 1, rMax: 25, beschreibung: zweiLappen("z") },
  "3s": { radial: R3s, winkel: eins, winkelMax: 1, rMax: 40, beschreibung: "kugelförmig mit zwei kugelförmigen Knotenflächen, die Phase wechselt zweimal von innen nach außen" },
  "3p_x": { radial: R3p, winkel: px, winkelMax: 1, rMax: 40, beschreibung: zweiLappen("x") + " und einer kugelförmigen Knotenfläche" },
  "3p_y": { radial: R3p, winkel: py, winkelMax: 1, rMax: 40, beschreibung: zweiLappen("y") + " und einer kugelförmigen Knotenfläche" },
  "3p_z": { radial: R3p, winkel: pz, winkelMax: 1, rMax: 40, beschreibung: zweiLappen("z") + " und einer kugelförmigen Knotenfläche" },
  "3d_xy": { radial: R3d, winkel: (x, y) => x * y, winkelMax: 0.25, rMax: 40, beschreibung: vierZwischen("x", "y") },
  "3d_xz": { radial: R3d, winkel: (x, _y, z) => x * z, winkelMax: 0.25, rMax: 40, beschreibung: vierZwischen("x", "z") },
  "3d_yz": { radial: R3d, winkel: (_x, y, z) => y * z, winkelMax: 0.25, rMax: 40, beschreibung: vierZwischen("y", "z") },
  "3d_x2-y2": { radial: R3d, winkel: (x, y) => x * x - y * y, winkelMax: 1, rMax: 40, beschreibung: "vier Lappen entlang der x- und der y-Achse, die Phase wechselt von Lappen zu Lappen" },
  "3d_z2": { radial: R3d, winkel: (_x, _y, z) => 3 * z * z - 1, winkelMax: 4, rMax: 40, beschreibung: "zwei Lappen entlang der z-Achse mit gleicher Phase und ein Ring in der xy-Ebene mit entgegengesetzter Phase" },
};

/** Feste Kurzbeschreibung der Form eines Orbitals. */
export function orbitalBeschreibung(orbital: OrbitalName): string {
  return Object.prototype.hasOwnProperty.call(ORBITAL_DEF, orbital) ? ORBITAL_DEF[orbital].beschreibung : ORBITAL_DEF["1s"].beschreibung;
}

const radialMaxCache = new Map<OrbitalName, number>();

/** Größter Wert der radialen Dichte r²·R(r)² auf [0, rMax], aus einem feinen Gitter, mit 5 % Reserve (die Dichte ist glatt). */
function radialMax(name: OrbitalName, d: OrbitalDef): number {
  const c = radialMaxCache.get(name);
  if (c !== undefined) return c;
  let m = 0;
  for (let i = 0; i <= 4000; i++) {
    const r = (d.rMax * i) / 4000, R = d.radial(r);
    m = Math.max(m, r * r * R * R);
  }
  const wert = m * 1.05;
  radialMaxCache.set(name, wert);
  return wert;
}

/** Zieht die Punktwolke aus |ψ|² der fest eingebauten Wasserstoff-Formel mit dem Startwert. Weil ψ = R(r)·Y(Richtung) sich
 *  trennt, wird r aus der radialen Dichte r²·R² und die Richtung aus |Y|² je mit Verwerfen gezogen; das ergibt genau |ψ|².
 *  Höchstens 200 Versuche je verlangtem Punkt; reicht das nicht, sagt `anzahl` ehrlich, wie viele es sind. Gleicher Startwert,
 *  gleiche Wolke. Wirft nie. */
export function orbitalPunkte(config: OrbitalConfig): OrbitalWolke {
  let cfg: OrbitalConfig;
  try {
    cfg = normalizeTeilchen({ ...config, form: "orbital" }) as OrbitalConfig;
  } catch {
    cfg = { typ: "teilchen", form: "orbital", orbital: "1s", punkte: PUNKTE_STANDARD, startwert: 1, angepasst: ["intern"], ungueltig: true };
  }
  const name = cfg.orbital, d = ORBITAL_DEF[name], soll = cfg.punkte, ungueltig = cfg.ungueltig || warUngueltig(config);
  const pos = new Float32Array(ungueltig ? 0 : 3 * soll), ph = new Int8Array(ungueltig ? 0 : soll);
  let n = 0, versuche = 0, plus = 0, weit = 0;
  if (!ungueltig) try {                                              // ungültig: keine Wolke, die ein echtes Orbital vortäuscht
    const rng = mulberry32(cfg.startwert), pMax = radialMax(name, d), grenze = VERSUCHE_JE_PUNKT * soll;
    while (n < soll && versuche < grenze) {
      versuche++;
      const r = d.rMax * rng(), R = d.radial(r);
      if (rng() * pMax > r * r * R * R) continue;
      let x = 0, y = 0, z = 0, w = 0, ok = false;
      while (versuche < grenze) {
        versuche++;
        z = 2 * rng() - 1;
        const phi = 2 * Math.PI * rng(), s = Math.sqrt(Math.max(0, 1 - z * z));
        x = s * Math.cos(phi); y = s * Math.sin(phi);
        w = d.winkel(x, y, z);
        if (rng() * d.winkelMax <= w * w) { ok = true; break; }
      }
      if (!ok) break;
      const X = r * x, Y = r * y, Z = r * z;
      if (!fin(X) || !fin(Y) || !fin(Z)) continue;
      pos[3 * n] = X; pos[3 * n + 1] = Y; pos[3 * n + 2] = Z;
      const p: Phase = R * w < 0 ? -1 : 1;
      ph[n] = p;
      if (p > 0) plus++;
      weit = Math.max(weit, r);
      n++;
    }
  } catch {
    // nichts: die bis hierher gezogenen Punkte bleiben gültig
  }
  const positionen = n === soll ? pos : pos.slice(0, 3 * n), phasen = n === soll ? ph : ph.slice(0, n);
  const zahl = n === soll ? mehrzahl(n, "Punkt", "Punkte") : `${n} von ${soll} Punkten`;
  return {
    orbital: name, soll, anzahl: n, vollstaendig: n === soll, positionen, phasen, plus, minus: n - plus,
    ausdehnung: n > 0 ? weit : d.rMax, versuche, beschreibung: d.beschreibung,
    text: ungueltig ? "Ungültige Orbitalangabe." : `Orbital ${name}, ${zahl}, ${d.beschreibung}.`, ungueltig,
  };
}
