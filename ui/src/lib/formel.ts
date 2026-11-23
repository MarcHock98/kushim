// Stapelmaschine für eigene Simulationen (Baustein `sim_eigen`, Plan P7 Stufe 1). Das Backend liefert jede Formel schon übersetzt
// als Liste von Knoten [[op, arg], ...] in umgekehrter polnischer Schreibweise; die Oberfläche liest nie Formeltext. Diese Datei
// ist die einzige Stelle, die Knoten ausführt (`tests/test_ui_rules.py`).
// Knoten: ["c", zahl] legt eine Konstante ab, ["v", i] liest env[i], ["o", s] rechnet zweistellig (+ - * / ^ und die Vergleiche,
// die 1 oder 0 liefern) oder einstellig (neg), ["f", name] ruft eine Funktion mit fester Stelligkeit. `^` ist Math.pow,
// mod(a, b) = a − b·floor(a/b), wenn(b, a, c) = a, falls b ≠ 0, sonst c. Teilen durch 0 gibt ±Unendlich oder NaN, das ist kein
// Fehler (die Simulation erkennt nicht endliche Zahlen selbst).
// Ablauf: `pruefeRpn` prüft die Struktur (bekannte Knoten, Indizes im Bereich, kein Unterlauf, am Ende genau ein Wert, höchstens
// 64 Knoten, Zahlen endlich) und gibt ein geprüftes Stück zurück; nur das nimmt `kompiliere` an. `kompiliere` baut daraus eine
// Liste kleiner Funktionen über einen einmal angelegten Float64Array-Stapel (kein Text, kein Code aus Daten). Nichts wirft.

/** Höchstens so viele Knoten je Formel (wie im Backend). */
export const MAX_KNOTEN = 64;
/** Größte erlaubte Länge eines env-Felds (Zeit, 12 Zustände, 12 Parameter, 12 Hilfsgrößen passen weit hinein). */
export const MAX_ENV = 256;
/** Die vier Knotenarten. */
export const KNOTEN_ARTEN = ["c", "v", "o", "f"] as const;
export type KnotenArt = (typeof KNOTEN_ARTEN)[number];
/** Zweistellige Operationen (Vergleiche liefern 1 oder 0). */
export const OPS_ZWEI = ["+", "-", "*", "/", "^", "<", "<=", ">", ">=", "==", "!="] as const;
/** Einstellige Operationen. */
export const OPS_EINS = ["neg"] as const;
export type Op = (typeof OPS_ZWEI)[number] | (typeof OPS_EINS)[number];
/** Funktionen mit ihrer festen Stelligkeit. */
export const FUNKTIONEN: Readonly<Record<string, 1 | 2 | 3>> = Object.freeze({
  sin: 1, cos: 1, tan: 1, asin: 1, acos: 1, atan: 1, sinh: 1, cosh: 1, tanh: 1, exp: 1, log: 1, log10: 1, sqrt: 1, abs: 1, sign: 1,
  floor: 1, ceil: 1,
  atan2: 2, min: 2, max: 2, hypot: 2, mod: 2,
  clamp: 3, wenn: 3,
});

export type Knoten = readonly [KnotenArt, number | string];
/** Ein Stück RPN, das `pruefeRpn` angenommen hat. Nur so entsteht es (siehe GEPRUEFT). */
export interface GeprueftesRpn {
  readonly knoten: readonly Knoten[];
  /** Größte Stapeltiefe während der Auswertung. */
  readonly tiefe: number;
  /** Länge des env-Felds, gegen die geprüft wurde. */
  readonly envLen: number;
  /** Gelesene env-Indizes, aufsteigend. */
  readonly liest: readonly number[];
}
export type PruefErgebnis = { ok: true; rpn: GeprueftesRpn } | { ok: false; fehler: string };
/** Ausgewertete Formel: env hinein, eine Zahl heraus (nicht unbedingt endlich). `knoten` zählt fürs Rechenbudget. */
export interface Auswerter {
  (env: ArrayLike<number>): number;
  readonly knoten: number;
}

const OPS2 = new Set<string>(OPS_ZWEI);
const OPS1 = new Set<string>(OPS_EINS);
const STELLIG = new Map<string, number>(Object.entries(FUNKTIONEN));
const GEPRUEFT = new WeakSet<GeprueftesRpn>();

/** Prüft eine Knotenliste gegen ein env der Länge `envLen`. Fehler als fester Code mit Knotennummer, ohne Inhalt der Eingabe. */
export function pruefeRpn(rpn: unknown, envLen: number): PruefErgebnis {
  try {
    if (!Number.isInteger(envLen) || envLen < 0 || envLen > MAX_ENV) return { ok: false, fehler: "env_laenge" };
    if (!Array.isArray(rpn)) return { ok: false, fehler: "keine_liste" };
    if (rpn.length === 0) return { ok: false, fehler: "leer" };
    if (rpn.length > MAX_KNOTEN) return { ok: false, fehler: "zu_lang" };
    const knoten: Knoten[] = [], liest = new Set<number>();
    let tiefe = 0, max = 0;
    for (let i = 0; i < rpn.length; i++) {
      const k: unknown = rpn[i];
      if (!Array.isArray(k) || k.length !== 2) return { ok: false, fehler: `knoten@${i}` };
      const art: unknown = k[0], arg: unknown = k[1];
      let braucht = 0, gibt = 1;
      if (art === "c") {
        if (typeof arg !== "number" || !Number.isFinite(arg)) return { ok: false, fehler: `zahl@${i}` };
      } else if (art === "v") {
        if (typeof arg !== "number" || !Number.isInteger(arg) || arg < 0 || arg >= envLen) return { ok: false, fehler: `index@${i}` };
        liest.add(arg);
      } else if (art === "o") {
        if (typeof arg !== "string") return { ok: false, fehler: `unbekannte_operation@${i}` };
        if (OPS2.has(arg)) braucht = 2;
        else if (OPS1.has(arg)) braucht = 1;
        else return { ok: false, fehler: `unbekannte_operation@${i}` };
      } else if (art === "f") {
        const n = typeof arg === "string" ? STELLIG.get(arg) : undefined;
        if (n === undefined) return { ok: false, fehler: `unbekannte_funktion@${i}` };
        braucht = n;
      } else {
        return { ok: false, fehler: `unbekannter_opcode@${i}` };
      }
      if (tiefe < braucht) return { ok: false, fehler: `unterlauf@${i}` };
      tiefe += gibt - braucht;
      if (tiefe > max) max = tiefe;
      knoten.push(Object.freeze([art, arg]) as Knoten);
    }
    if (tiefe !== 1) return { ok: false, fehler: "nicht_ein_wert" };
    const g: GeprueftesRpn = Object.freeze({
      knoten: Object.freeze(knoten), tiefe: max, envLen, liest: Object.freeze([...liest].sort((a, b) => a - b)),
    });
    GEPRUEFT.add(g);
    return { ok: true, rpn: g };
  } catch {
    return { ok: false, fehler: "intern" };
  }
}

/** Ist dies ein Stück, das `pruefeRpn` geprüft hat? */
export const istGeprueft = (g: unknown): g is GeprueftesRpn => typeof g === "object" && g !== null && GEPRUEFT.has(g as GeprueftesRpn);

type Schritt = (env: ArrayLike<number>) => void;

/** Übersetzt ein geprüftes Stück in eine schnelle Auswertung. Nicht geprüft (oder sonst unbrauchbar): null. */
export function kompiliere(g: GeprueftesRpn): Auswerter | null {
  if (!istGeprueft(g)) return null;
  try {
    const st = new Float64Array(Math.max(1, g.tiefe));
    let sp = 0;
    const schritte: Schritt[] = g.knoten.map(([art, arg]): Schritt => {
      if (art === "c") { const c = arg as number; return () => { st[sp++] = c; }; }
      if (art === "v") { const i = arg as number; return (env) => { st[sp++] = +env[i]; }; }
      if (art === "o") return op(arg as Op);
      return fn(arg as string);
    });
    function op(s: Op): Schritt {
      switch (s) {
        case "neg": return () => { st[sp - 1] = -st[sp - 1]; };
        case "+": return () => { const b = st[--sp]; st[sp - 1] = st[sp - 1] + b; };
        case "-": return () => { const b = st[--sp]; st[sp - 1] = st[sp - 1] - b; };
        case "*": return () => { const b = st[--sp]; st[sp - 1] = st[sp - 1] * b; };
        case "/": return () => { const b = st[--sp]; st[sp - 1] = st[sp - 1] / b; };
        case "^": return () => { const b = st[--sp]; st[sp - 1] = Math.pow(st[sp - 1], b); };
        case "<": return () => { const b = st[--sp]; st[sp - 1] = st[sp - 1] < b ? 1 : 0; };
        case "<=": return () => { const b = st[--sp]; st[sp - 1] = st[sp - 1] <= b ? 1 : 0; };
        case ">": return () => { const b = st[--sp]; st[sp - 1] = st[sp - 1] > b ? 1 : 0; };
        case ">=": return () => { const b = st[--sp]; st[sp - 1] = st[sp - 1] >= b ? 1 : 0; };
        case "==": return () => { const b = st[--sp]; st[sp - 1] = st[sp - 1] === b ? 1 : 0; };
        case "!=": return () => { const b = st[--sp]; st[sp - 1] = st[sp - 1] !== b ? 1 : 0; };
      }
    }
    function eins(f: (x: number) => number): Schritt {
      return () => { st[sp - 1] = f(st[sp - 1]); };
    }
    function zwei(f: (a: number, b: number) => number): Schritt {
      return () => { const b = st[--sp]; st[sp - 1] = f(st[sp - 1], b); };
    }
    function fn(name: string): Schritt {
      switch (name) {
        case "sin": return eins(Math.sin);
        case "cos": return eins(Math.cos);
        case "tan": return eins(Math.tan);
        case "asin": return eins(Math.asin);
        case "acos": return eins(Math.acos);
        case "atan": return eins(Math.atan);
        case "sinh": return eins(Math.sinh);
        case "cosh": return eins(Math.cosh);
        case "tanh": return eins(Math.tanh);
        case "exp": return eins(Math.exp);
        case "log": return eins(Math.log);
        case "log10": return eins(Math.log10);
        case "sqrt": return eins(Math.sqrt);
        case "abs": return eins(Math.abs);
        case "sign": return eins(Math.sign);
        case "floor": return eins(Math.floor);
        case "ceil": return eins(Math.ceil);
        case "atan2": return zwei(Math.atan2);
        case "min": return zwei(Math.min);
        case "max": return zwei(Math.max);
        case "hypot": return zwei(Math.hypot);
        case "mod": return zwei((a, b) => a - b * Math.floor(a / b));
        case "clamp": return () => { const hi = st[--sp], lo = st[--sp]; st[sp - 1] = Math.min(Math.max(st[sp - 1], lo), hi); };
        case "wenn": return () => { const c = st[--sp], a = st[--sp]; st[sp - 1] = st[sp - 1] !== 0 ? a : c; };
        default: throw new Error("unbekannt");                       // kann nach der Prüfung nicht vorkommen
      }
    }
    const n = schritte.length;
    const f = (env: ArrayLike<number>): number => {
      sp = 0;
      for (let i = 0; i < n; i++) schritte[i](env);
      return st[0];
    };
    return Object.assign(f, { knoten: n });
  } catch {
    return null;
  }
}

/** Prüfen und übersetzen in einem Zug; unbrauchbar: null. */
export function uebersetze(rpn: unknown, envLen: number): Auswerter | null {
  const p = pruefeRpn(rpn, envLen);
  return p.ok ? kompiliere(p.rpn) : null;
}

/** Liest das geprüfte Stück env[i]? (Zum Beispiel: nutzt eine Kraft die Geschwindigkeit?) */
export const liestIndex = (g: GeprueftesRpn, i: number): boolean => g.liest.includes(i);
