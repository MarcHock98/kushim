import { describe, expect, it } from "vitest";
import { advanceEigen, createEigen, eigenEndlich, snapshotEigen, type EigenState } from "./lib/eigenSim";
import { parseItem, type EigenBlock, type View } from "./lib/stage";

// Rezeptbuch `sim_eigen` (Plan P7 Stufe 1b). Jede Ansicht kommt genau in der Form des Backends aus src/fixtures/rezept_ansichten.json
// (erzeugt mit schema.validate aus {typ: "sim_eigen", rezept: name}, siehe tests/test_ui_rezept_fixture.py). Die echte Engine rechnet
// jedes Rezept einige Sekunden wie die Taktschleife: nie „ungültig“, nie „instabil“, keine Zeitlupe, alles endlich.

const nodeFs = "node:fs";
const { readFileSync } = (await import(/* @vite-ignore */ nodeFs)) as { readFileSync(p: string, enc: string): string };
const ANSICHTEN = (JSON.parse(readFileSync("src/fixtures/rezept_ansichten.json", "utf-8")) as { ansichten: Record<string, unknown>[] }).ansichten;
const SEKUNDEN = 8;                                                                  // Wanduhr; Modellzeit = SEKUNDEN · tempo

function block(raw: Record<string, unknown>): EigenBlock {
  const v = parseItem({ ...raw, seq: 1 }) as View;
  expect(v).not.toBeNull();
  expect(v.bausteine).toHaveLength(1);
  return v.bausteine[0] as EigenBlock;
}

/** Weiterrechnen wie die Taktschleife: Bilder zu 1/30 s, je Bild `tempo`/30 Modellsekunden; jedes Bild muss endlich sein. */
function lauf(s: EigenState, sekunden: number): void {
  for (let i = 0, n = Math.round(sekunden * 30); i < n; i++) {
    const r = advanceEigen(s, s.tempo / 30);
    expect(r.begrenzt).toBe(false);
    const bild = snapshotEigen(s);
    expect(eigenEndlich(bild)).toBe(true);
    expect(s.phase).toBe("laeuft");
  }
}

describe("Rezepte (sim_eigen mit rezept)", () => {
  it("die Fixture hat je Rezept eine Ansicht, darunter die vier Beispiele des Plans", () => {
    const namen = ANSICHTEN.map((v) => String((block(v) as unknown as Record<string, unknown>).rezept ?? ""));
    expect(namen.length).toBeGreaterThanOrEqual(8);
    expect(namen).toEqual(expect.arrayContaining(["pendel_gedaempft", "raeuber_beute", "lorenz", "federkette"]));
    expect(new Set(namen).size).toBe(namen.length);
  });

  it.each(ANSICHTEN.map((v) => [String(v.id), v] as const))("%s: wird ohne Anpassung gelesen und rechnet stabil", (_id, raw) => {
    const b = block(raw);
    expect(b.typ).toBe("sim_eigen");
    expect(JSON.stringify(b)).not.toMatch(/"formel"\s*:\s*"/);                    // nur RPN und TeX, nie Formeltext
    const s = createEigen(b);
    expect(s.config.fehler).toEqual([]);
    expect(s.config.angepasst).toEqual([]);
    expect(s.config.ungueltig).toBe(false);
    expect(s.phase).toBe("laeuft");
    expect(s.grund).toBeNull();
    lauf(s, SEKUNDEN);
    expect(s.phase).toBe("laeuft");
    expect(s.zeit).toBeGreaterThanOrEqual(SEKUNDEN * s.tempo * 0.99);              // keine Zeitlupe: die Modellzeit kommt mit
    const bild = snapshotEigen(s);
    expect(bild.phase).toBe("laeuft");
    if (b.form === "teilchen") {
      const [breite, hoehe] = b.kasten as number[];
      for (const k of bild.koerper) {
        expect(k.x).toBeGreaterThanOrEqual(0); expect(k.x).toBeLessThanOrEqual(breite);
        expect(k.y).toBeGreaterThanOrEqual(0); expect(k.y).toBeLessThanOrEqual(hoehe);
      }
    }
    if (b.erhaltung) expect(bild.drift ?? Infinity).toBeLessThan(1);           // Erhaltungsgröße: kein Hinweis auf Drift
  });

  it.each(ANSICHTEN.map((v) => [String(v.id), v] as const))("%s: rechnet auch mit allen Parametern an Min oder Max stabil", (_id, raw) => {
    const b = block(raw);
    for (const ecke of ["min", "max"] as const) {
      const s = createEigen({ ...b, parameter: b.parameter.map((p) => ({ ...p, wert: p[ecke] })) });
      expect(s.config.ungueltig).toBe(false);
      expect(s.phase).toBe("laeuft");
      lauf(s, 3);
    }
  });
});
