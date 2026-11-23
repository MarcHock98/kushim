import { describe, expect, it } from "vitest";
import {
  FUNKTIONEN, istGeprueft, kompiliere, liestIndex, MAX_KNOTEN, MAX_TIEFE, MAX_ZAHL, OPS_EINS, OPS_ZWEI, pruefeRpn, uebersetze, type GeprueftesRpn,
} from "./lib/formel";

// Stapelmaschine (Plan P7 Stufe 1): Testvektoren aus tests/fixtures/formel_vektoren.json (Python-Seite), solange es sie nicht gibt
// aus ui/src/fixtures/formel_vektoren_ui.json; dazu die Strukturprüfung.

const nodeFs = "node:fs";
const fs = (await import(/* @vite-ignore */ nodeFs)) as { readFileSync(p: string, enc: string): string; existsSync(p: string): boolean };
const PYTHON = "../tests/fixtures/formel_vektoren.json", EIGEN = "src/fixtures/formel_vektoren_ui.json";   // Vitest läuft im Ordner ui
const quelle = fs.existsSync(PYTHON) ? PYTHON : EIGEN;
const daten = JSON.parse(fs.readFileSync(quelle, "utf-8")) as unknown;

type Rec = Record<string, unknown>;
interface Vektor { name: string; rpn: unknown; env: number[]; wert: number }
/** Erwarteter Wert: Zahl, „inf“, „-inf“, „nan“ oder null (NaN). */
function erwartet(w: unknown): number | undefined {
  if (typeof w === "number") return w;
  if (w === null) return NaN;
  if (typeof w === "string") {
    const s = w.toLowerCase();
    if (s === "inf" || s === "+inf" || s === "infinity") return Infinity;
    if (s === "-inf" || s === "-infinity") return -Infinity;
    if (s === "nan") return NaN;
  }
  return undefined;
}
/** Liest die Vektoren tolerant (Liste oder Objekt mit `vektoren`/`faelle`/`gueltig`); Einträge ohne RPN oder Wert zählen nicht. */
function vektoren(d: unknown): Vektor[] {
  const r = d as Rec;
  const liste = (Array.isArray(d) ? d : r.vektoren ?? r.faelle ?? r.gueltig ?? r.cases ?? []) as Rec[];
  const out: Vektor[] = [];
  for (const v of liste) {
    const rpn = v.rpn ?? (v.formel as Rec | undefined)?.rpn ?? (v.ergebnis as Rec | undefined)?.rpn;
    const w = erwartet("wert" in v ? v.wert : "erwartet" in v ? v.erwartet : v.expected);
    if (!Array.isArray(rpn) || w === undefined) continue;
    out.push({ name: String(v.name ?? out.length), rpn, env: Array.isArray(v.env) ? (v.env as number[]) : [], wert: w });
  }
  return out;
}
const VEKTOREN = vektoren(daten);

function gleich(ist: number, soll: number): boolean {
  if (Number.isNaN(soll)) return Number.isNaN(ist);
  if (!Number.isFinite(soll)) return ist === soll;
  return Math.abs(ist - soll) <= 1e-12 * Math.max(1, Math.abs(soll));
}

describe("formel: Testvektoren", () => {
  it(`has vectors (${quelle})`, () => {
    expect(VEKTOREN.length).toBeGreaterThanOrEqual(20);
  });
  it.each(VEKTOREN.map((v) => [v.name, v] as const))("%s", (_name, v) => {
    const f = uebersetze(v.rpn, Math.max(v.env.length, 1));
    expect(f).not.toBeNull();
    expect(gleich(f!(v.env), v.wert)).toBe(true);
    expect(gleich(f!(v.env), v.wert)).toBe(true);           // zweimal: der Stapel wird sauber wiederverwendet
  });
  it("covers every operation and function in the own vectors", () => {
    const eigene = vektoren(JSON.parse(fs.readFileSync(EIGEN, "utf-8")));
    const benutzt = new Set(eigene.flatMap((v) => (v.rpn as [string, unknown][]).filter((k) => k[0] === "o" || k[0] === "f").map((k) => String(k[1]))));
    for (const op of [...OPS_ZWEI, ...OPS_EINS, ...Object.keys(FUNKTIONEN)]) expect(benutzt.has(op), op).toBe(true);
  });
});

describe("formel: Strukturprüfung", () => {
  const eigene = JSON.parse(fs.readFileSync(EIGEN, "utf-8")) as { ungueltig: { name: string; rpn: unknown; env_len: number; fehler: string }[] };
  it.each(eigene.ungueltig.map((u) => [u.name, u] as const))("rejects %s", (_n, u) => {
    const p = pruefeRpn(u.rpn, u.env_len);
    expect(p).toEqual({ ok: false, fehler: u.fehler });
    expect(uebersetze(u.rpn, u.env_len)).toBeNull();
  });

  it("rejects stack underflow at the first node that needs more than it has", () => {
    expect(pruefeRpn([["c", 1], ["c", 2], ["o", "+"], ["o", "*"]], 1)).toEqual({ ok: false, fehler: "unterlauf@3" });
    expect(pruefeRpn([["c", 1], ["c", 2], ["f", "clamp"]], 1)).toEqual({ ok: false, fehler: "unterlauf@2" });
    expect(pruefeRpn([["c", 1], ["c", 2], ["c", 3], ["f", "clamp"]], 1).ok).toBe(true);
  });

  it("rejects indices outside the env and checks against the given length", () => {
    expect(pruefeRpn([["v", 5]], 6).ok).toBe(true);
    expect(pruefeRpn([["v", 6]], 6)).toEqual({ ok: false, fehler: "index@0" });
    expect(pruefeRpn([["v", "1"]], 6)).toEqual({ ok: false, fehler: "index@0" });
    expect(pruefeRpn([["v", Number.NaN]], 6)).toEqual({ ok: false, fehler: "index@0" });
    expect(pruefeRpn([["c", 1]], -1)).toEqual({ ok: false, fehler: "env_laenge" });
    expect(pruefeRpn([["c", 1]], 1.5)).toEqual({ ok: false, fehler: "env_laenge" });
  });

  it("rejects unknown opcodes, operations and functions, also names from the object prototype", () => {
    for (const art of ["C", "var", "", "op", "fn", "__proto__"]) expect(pruefeRpn([[art, 1]], 1)).toEqual({ ok: false, fehler: "unbekannter_opcode@0" });
    for (const s of ["%", "**", "&&", "neg2", "toString", "valueOf"]) expect(pruefeRpn([["c", 1], ["c", 2], ["o", s]], 1)).toEqual({ ok: false, fehler: "unbekannte_operation@2" });
    for (const n of ["eval", "Function", "constructor", "__proto__", "hasOwnProperty", "pow", "random", "SIN"])
      expect(pruefeRpn([["c", 1], ["f", n]], 1)).toEqual({ ok: false, fehler: "unbekannte_funktion@1" });
    expect(pruefeRpn([["c", 1], ["f", 1]], 1)).toEqual({ ok: false, fehler: "unbekannte_funktion@1" });
  });

  it("allows exactly 64 nodes and rejects 65", () => {
    const summe = (n: number): unknown[] => (n === 1 ? [["c", 1]] : [...summe(Math.floor(n / 2)), ...summe(n - Math.floor(n / 2)), ["o", "+"]]);
    const n64 = [...summe(32), ["o", "neg"]];                          // ausgeglichen: 63 Knoten, Tiefe 6, dazu neg
    expect(n64).toHaveLength(MAX_KNOTEN);
    const p = pruefeRpn(n64, 1);
    expect(p.ok).toBe(true);
    expect(kompiliere((p as { rpn: GeprueftesRpn }).rpn)!([0])).toBe(-32);
    expect(pruefeRpn([...n64, ["o", "neg"]], 1)).toEqual({ ok: false, fehler: "zu_lang" });
  });

  it("rejects non-finite or non-number constants", () => {
    for (const c of [Infinity, -Infinity, NaN, "2", null, true, [1], { x: 1 }]) expect(pruefeRpn([["c", c]], 1)).toEqual({ ok: false, fehler: "zahl@0" });
  });

  it("is as strict as aus_rpn in the backend: constants 0 to 1e12, never negative, tree depth at most 16", () => {
    for (const c of [0, 1e-300, 3.5, MAX_ZAHL]) expect(pruefeRpn([["c", c]], 1).ok).toBe(true);
    for (const c of [-1, -1e-300, -0, MAX_ZAHL * (1 + 1e-15), 1e13]) expect(pruefeRpn([["c", c]], 1)).toEqual({ ok: false, fehler: "zahl@0" });
    expect(pruefeRpn([["c", 1], ["c", 2], ["o", "+"], ["c", 3], ["o", "-"]], 1).ok).toBe(true);
    const kette = (negs: number) => [["c", 1], ...Array.from({ length: negs }, () => ["o", "neg"])];
    expect(MAX_TIEFE).toBe(16);
    expect(pruefeRpn(kette(15), 1).ok).toBe(true);                     // Tiefe 16
    expect(pruefeRpn(kette(16), 1)).toEqual({ ok: false, fehler: "zu_tief" });
    const links = (n: number) => [["c", 1], ...Array.from({ length: n }, () => [["v", 0], ["o", "*"]]).flat()];
    expect(pruefeRpn(links(15), 1).ok).toBe(true);                     // linke Kette aus 15 Produkten: Tiefe 16
    expect(pruefeRpn(links(16), 1)).toEqual({ ok: false, fehler: "zu_tief" });
    expect(pruefeRpn([["c", 1], ["c", 2], ["c", 3], ["f", "clamp"], ...Array.from({ length: 14 }, () => ["o", "neg"])], 1).ok).toBe(true);
    expect(pruefeRpn([["c", 1], ["c", 2], ["c", 3], ["f", "clamp"], ...Array.from({ length: 15 }, () => ["o", "neg"])], 1)).toEqual({ ok: false, fehler: "zu_tief" });
  });

  it("rejects malformed nodes and non-lists", () => {
    for (const r of [null, undefined, "c 1", 7, { 0: ["c", 1], length: 1 }]) expect(pruefeRpn(r, 1)).toEqual({ ok: false, fehler: "keine_liste" });
    for (const k of [["c"], ["c", 1, 2], "c1", null, { 0: "c", 1: 1 }]) expect(pruefeRpn([k], 1)).toEqual({ ok: false, fehler: "knoten@0" });
  });

  it("only compiles what the check produced", () => {
    const echt = pruefeRpn([["c", 2]], 1);
    expect(echt.ok && istGeprueft(echt.rpn)).toBe(true);
    const falsch = { knoten: [["v", 99]], tiefe: 1, envLen: 1, liest: [99] } as unknown as GeprueftesRpn;
    expect(istGeprueft(falsch)).toBe(false);
    expect(kompiliere(falsch)).toBeNull();
    expect(kompiliere({ ...(echt as { rpn: GeprueftesRpn }).rpn })).toBeNull();     // auch keine Kopie
  });

  it("the checked piece is frozen and names the env indices it reads", () => {
    const p = pruefeRpn([["v", 3], ["v", 1], ["o", "*"], ["v", 3], ["o", "+"]], 6);
    if (!p.ok) throw new Error(p.fehler);
    expect(p.rpn.liest).toEqual([1, 3]);
    expect(p.rpn.tiefe).toBe(2);
    expect(liestIndex(p.rpn, 3) && !liestIndex(p.rpn, 4)).toBe(true);
    expect(Object.isFrozen(p.rpn) && Object.isFrozen(p.rpn.knoten) && Object.isFrozen(p.rpn.knoten[0])).toBe(true);
  });

  it("evaluates with a reused stack and reports the node count", () => {
    const f = uebersetze([["v", 0], ["v", 0], ["o", "*"], ["c", 1], ["o", "+"], ["f", "sqrt"]], 1)!;
    expect(f.knoten).toBe(6);
    expect(f([3])).toBeCloseTo(Math.sqrt(10), 14);
    expect(f(new Float64Array([0]))).toBe(1);
    for (let i = 0; i < 1000; i++) f([i]);
    expect(f([3])).toBeCloseTo(Math.sqrt(10), 14);
  });

  it("never throws on hostile input", () => {
    const boese = new Proxy([], { get() { throw new Error("x"); } });
    expect(pruefeRpn(boese, 1)).toEqual({ ok: false, fehler: "intern" });
    expect(() => uebersetze(boese, 1)).not.toThrow();
  });
});
