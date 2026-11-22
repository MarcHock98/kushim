import { afterEach, describe, expect, it, vi } from "vitest";
import {
  atomModell, bindungenAusAbstand, ELEMENTE, elementNachSymbol, elementNachZ, komma, kugelRadius, ladungText, molekuelGeometrie,
  normalizeTeilchen, orbitalPunkte, ORBITALE, phaseWort, summenformel, type AtomConfig, type MolekuelAtom, type MolekuelConfig,
  type OrbitalConfig, type OrbitalName, type V3,
} from "./lib/chem";

// Chemie-Kern für `teilchen` (Plan docs/ui-p5-plan.md, Abschnitt 7 und 10): reine Zahlen, kein DOM, kein Zufall ohne Startwert.

const PALETTE = ["arc", "amber", "ok", "warn", "alarm", "text", "gedaempft"];
const at = (element: string, x: number, y: number, z: number): MolekuelAtom => ({ element, position: [x, y, z] });

const WASSER: MolekuelAtom[] = [at("O", 0, 0, 0), at("H", 0.757, 0.586, 0), at("H", -0.757, 0.586, 0)];
const ETHANOL: MolekuelAtom[] = [
  at("C", 1.1879, -0.3829, 0), at("C", 0, 0.5526, 0), at("O", -1.1867, -0.2472, 0), at("H", -1.9237, 0.385, 0),
  at("H", 2.0985, 0.2306, 0), at("H", 1.1184, -1.0093, 0.8869), at("H", 1.1184, -1.0093, -0.8869),
  at("H", -0.0227, 1.1812, 0.8852), at("H", -0.0227, 1.1812, -0.8852),
];
const BENZOL: MolekuelAtom[] = [];
for (let k = 0; k < 6; k++) {
  const w = (k * Math.PI) / 3;
  BENZOL.push(at("C", 1.39 * Math.cos(w), 1.39 * Math.sin(w), 0));
  BENZOL.push(at("H", 2.48 * Math.cos(w), 2.48 * Math.sin(w), 0));
}
const t = 0.629;
const METHAN: MolekuelAtom[] = [at("C", 0, 0, 0), at("H", t, t, t), at("H", -t, -t, t), at("H", -t, t, -t), at("H", t, -t, -t)];

const molekuel = (atome: unknown, extra: object = {}): MolekuelConfig =>
  normalizeTeilchen({ typ: "teilchen", form: "molekuel", name: "", atome, bindungen: [], beschriftungen: [], darstellung: "kugel-stab", ...extra }) as MolekuelConfig;
const atom = (element: string, neutronen: number, ladung: number, schalen: number[]): AtomConfig =>
  normalizeTeilchen({ typ: "teilchen", form: "atom", element, neutronen, ladung, schalen }) as AtomConfig;
const orbital = (o: OrbitalName, punkte = 2500, startwert = 1): OrbitalConfig =>
  normalizeTeilchen({ typ: "teilchen", form: "orbital", orbital: o, punkte, startwert }) as OrbitalConfig;
const ms = (t0: number) => Math.round((performance.now() - t0) * 10) / 10;

afterEach(() => vi.restoreAllMocks());

describe("Elemente", () => {
  it("hat alle 118 Elemente mit eindeutigen Symbolen und Ordnungszahlen 1 bis 118", () => {
    expect(ELEMENTE).toHaveLength(118);
    expect(new Set(ELEMENTE.map((e) => e.symbol)).size).toBe(118);
    ELEMENTE.forEach((e, i) => {
      expect(e.z).toBe(i + 1);
      expect(e.symbol).toMatch(/^[A-Z][a-z]?$/);
      expect(e.name.length).toBeGreaterThan(1);
      expect(e.kovalenzradius).toBeGreaterThan(0);
      expect(e.vdwRadius).toBeGreaterThan(0);
      expect(PALETTE).toContain(e.farbe);
    });
    expect(Object.isFrozen(ELEMENTE) && Object.isFrozen(ELEMENTE[0])).toBe(true);
  });

  it("nennt bekannte Symbole, deutsche Namen und Radien", () => {
    const e = (s: string) => elementNachSymbol(s)!;
    expect([e("H").name, e("C").name, e("N").name, e("O").name, e("Fe").name, e("Au").name, e("Hg").name, e("Og").name])
      .toEqual(["Wasserstoff", "Kohlenstoff", "Stickstoff", "Sauerstoff", "Eisen", "Gold", "Quecksilber", "Oganesson"]);
    expect([e("Fe").z, e("Au").z, e("U").z, e("Og").z, e("Cl").z]).toEqual([26, 79, 92, 118, 17]);
    expect([e("H").kovalenzradius, e("C").kovalenzradius, e("N").kovalenzradius, e("O").kovalenzradius, e("Cl").kovalenzradius])
      .toEqual([0.31, 0.76, 0.71, 0.66, 1.02]);
    expect([e("H").vdwRadius, e("C").vdwRadius, e("O").vdwRadius, e("Na").vdwRadius]).toEqual([1.2, 1.7, 1.52, 2.27]);
    expect([e("Og").kovalenzradius, e("Og").vdwRadius, e("Fe").vdwRadius]).toEqual([1.5, 2.0, 2.0]);   // Ersatzwerte
  });

  it("färbt nur aus der Palette wie im Plan", () => {
    const f = (s: string) => elementNachSymbol(s)!.farbe;
    expect([f("O"), f("N"), f("H"), f("C"), f("S")]).toEqual(["alarm", "arc", "text", "gedaempft", "warn"]);
    expect(["F", "Cl", "Br", "I", "At"].map(f)).toEqual(["ok", "ok", "ok", "ok", "ok"]);
    expect(["Na", "Fe", "He", "Ts", "P"].map(f)).toEqual(["amber", "amber", "amber", "amber", "amber"]);
  });

  it("sucht nach Symbol in genauer Schreibweise und nach Ordnungszahl", () => {
    expect(elementNachSymbol("Na")?.z).toBe(11);
    for (const s of ["na", "NA", "Xx", "", "__proto__", "constructor", "toString", 11, null, undefined]) expect(elementNachSymbol(s)).toBeUndefined();
    expect(elementNachZ(26)?.symbol).toBe("Fe");
    expect(elementNachZ(118)?.symbol).toBe("Og");
    for (const z of [0, 119, 1.5, NaN, -1, "6"]) expect(elementNachZ(z)).toBeUndefined();
  });
});

describe("Summenformel (Hill)", () => {
  it("ordnet C, dann H, dann alphabetisch; ohne C alles alphabetisch", () => {
    expect(summenformel(WASSER)).toBe("H2O");
    expect(summenformel(ETHANOL)).toBe("C2H6O");
    expect(summenformel(METHAN)).toBe("CH4");
    expect(summenformel(BENZOL)).toBe("C6H6");
    expect(summenformel([at("Na", 0, 0, 0), at("Cl", 2.4, 0, 0)])).toBe("ClNa");
    expect(summenformel([at("N", 0, 0, 0), at("H", 1, 0, 0), at("H", 0, 1, 0), at("H", 0, 0, 1)])).toBe("H3N");
    expect(summenformel([at("S", 0, 0, 0), at("O", 1, 0, 0), at("O", 2, 0, 0), at("O", 3, 0, 0), at("O", 4, 0, 0), at("H", 5, 0, 0), at("H", 6, 0, 0)]))
      .toBe("H2O4S");
    expect(summenformel([at("Cl", 0, 0, 0), at("C", 1, 0, 0), at("Br", 2, 0, 0)])).toBe("CBrCl");   // mit C, ohne H
    expect(summenformel([at("C", 0, 0, 0), at("O", 1, 0, 0), at("O", 2, 0, 0)])).toBe("CO2");
  });

  it("übergeht Unbekanntes und wirft nie", () => {
    expect(summenformel([at("Xx", 0, 0, 0), at("H", 0, 0, 0)])).toBe("H");
    expect(summenformel([])).toBe("");
    expect(summenformel(null as unknown as MolekuelAtom[])).toBe("");
    expect(summenformel([null, 3, { element: "__proto__" }] as unknown as MolekuelAtom[])).toBe("");
  });
});

describe("Bindungen aus Abständen", () => {
  const paare = (atome: MolekuelAtom[]) => bindungenAusAbstand(atome).map((b) => `${atome[b.von].element}${b.von}-${atome[b.bis].element}${b.bis}`);

  it("Wasser: zwei O–H", () => {
    expect(paare(WASSER)).toEqual(["O0-H1", "O0-H2"]);
  });

  it("Ethanol: 8 Bindungen (C–C, C–O, O–H, 5 C–H)", () => {
    const b = bindungenAusAbstand(ETHANOL);
    expect(b).toHaveLength(8);
    expect(paare(ETHANOL)).toEqual(["C0-C1", "C0-H4", "C0-H5", "C0-H6", "C1-O2", "C1-H7", "C1-H8", "O2-H3"]);
    expect(b.every((x) => x.ordnung === 1 && x.von < x.bis)).toBe(true);
  });

  it("Benzol: 12 Bindungen mit C–H, jedes C dreimal gebunden", () => {
    const b = bindungenAusAbstand(BENZOL);
    expect(b).toHaveLength(12);
    const grad = new Array(12).fill(0);
    for (const x of b) { grad[x.von]++; grad[x.bis]++; }
    BENZOL.forEach((a, i) => expect(grad[i]).toBe(a.element === "C" ? 3 : 1));
    expect(bindungenAusAbstand(METHAN)).toHaveLength(4);
  });

  it("keine Bindung bei 3 Å Abstand und keine bei zu kleinem Abstand", () => {
    expect(bindungenAusAbstand([at("C", 0, 0, 0), at("C", 3, 0, 0)])).toEqual([]);
    expect(bindungenAusAbstand([at("C", 0, 0, 0), at("C", 0.3, 0, 0)])).toEqual([]);
    expect(bindungenAusAbstand([at("C", 0, 0, 0), at("C", 1.82, 0, 0)])).toHaveLength(1);     // knapp unter 1,2 × 1,52
    expect(bindungenAusAbstand([at("C", 0, 0, 0), at("C", 1.83, 0, 0)])).toHaveLength(0);
  });

  it("höchstens 6 Bindungen je Atom, die kürzesten zuerst", () => {
    const atome: MolekuelAtom[] = [at("C", 0, 0, 0)];
    let k = 0;
    for (const sx of [-1, 1]) for (const sy of [-1, 1]) for (const sz of [-1, 1]) {
      const d = (1 + 0.01 * k++) / Math.sqrt(3);
      atome.push(at("H", sx * d, sy * d, sz * d));
    }
    const b = bindungenAusAbstand(atome);
    expect(b).toHaveLength(6);
    expect(b.map((x) => x.bis)).toEqual([1, 2, 3, 4, 5, 6]);           // die zwei fernsten H (7, 8) bleiben ohne Bindung
  });

  it("300 Atome im dichten Gitter: schnell, höchstens 400 Bindungen, 6 je Atom, gleiches Ergebnis bei gleicher Eingabe", () => {
    const atome: MolekuelAtom[] = [];
    for (let x = 0; x < 10; x++) for (let y = 0; y < 10; y++) for (let z = 0; z < 3; z++) atome.push(at("C", x, y, z));
    const t0 = performance.now();
    const b = bindungenAusAbstand(atome);
    const dauer = ms(t0);
    console.info(`[chem] Bindungen aus Abständen, 300 Atome im Gitter: ${dauer} ms`);
    expect(dauer).toBeLessThan(500);
    expect(b).toHaveLength(400);
    const grad = new Array(300).fill(0);
    for (const x of b) { grad[x.von]++; grad[x.bis]++; expect(x.von).toBeLessThan(x.bis); }
    expect(Math.max(...grad)).toBeLessThanOrEqual(6);
    for (const x of b) {                                                 // nur nächste Nachbarn (1 Å), da genug davon da sind
      const p = atome[x.von].position, q = atome[x.bis].position;
      expect(Math.hypot(q[0] - p[0], q[1] - p[1], q[2] - p[2])).toBeCloseTo(1, 9);
    }
    expect(bindungenAusAbstand(atome)).toEqual(b);
    const sortiert = [...b].sort((u, v) => u.von - v.von || u.bis - v.bis);
    expect(b).toEqual(sortiert);
  });

  it("alle 300 Atome an einem Punkt oder weit verstreut: keine Bindung, kein Absturz", () => {
    expect(bindungenAusAbstand(Array.from({ length: 300 }, () => at("C", 1, 1, 1)))).toEqual([]);
    const weit = Array.from({ length: 300 }, (_, i) => at("C", i * 1e5, -i * 1e5, 0));
    expect(bindungenAusAbstand(weit)).toEqual([]);
    expect(bindungenAusAbstand(null as unknown as MolekuelAtom[])).toEqual([]);
    expect(bindungenAusAbstand([at("C", NaN, 0, 0), at("C", 0, 0, 0), { element: "C" } as MolekuelAtom, at("Xx", 0.5, 0, 0)])).toEqual([]);
  });
});

describe("Molekül-Geometrie", () => {
  it("Ethanol: Text, Zahlen, Mittelpunkt, Radien und Atomtabelle", () => {
    const g = molekuelGeometrie(molekuel(ETHANOL, { name: "Ethanol" }));
    expect(g.text).toBe("Molekül Ethanol, Summenformel C2H6O, 9 Atome, 8 Bindungen.");
    expect([g.atomzahl, g.bindungszahl, g.summenformel, g.bindungenAbgeleitet]).toEqual([9, 8, "C2H6O", true]);
    for (let k = 0; k < 3; k++) {                                         // Hüllbox um den Ursprung
      const v = g.atome.map((a) => a.position[k]);
      expect(Math.min(...v) + Math.max(...v)).toBeCloseTo(0, 9);
    }
    for (const a of g.atome) expect(Math.hypot(...a.position) + a.radius).toBeLessThanOrEqual(g.radius + 1e-9);
    const c = g.atome[0], h = g.atome[3];
    expect([c.radius, h.radius]).toEqual([0.3 * 0.76, 0.2]);             // Kugel-Stab: 0,3 × Kovalenzradius, mindestens 0,2 Å
    expect([c.radiusKalotte, h.radiusKalotte]).toEqual([1.7, 1.2]);
    expect(g.zeilen[2]).toEqual({ index: 2, symbol: "O", name: "Sauerstoff", koordinaten: ["-1,19", "-0,25", "0,00"], lage: "-1,19; -0,25; 0,00" });
    expect(g.bindungen[0].laenge).toBeCloseTo(1.512, 2);
  });

  it("Kalotte: Van-der-Waals-Radien, größerer Hüllradius", () => {
    const ks = molekuelGeometrie(molekuel(WASSER, { name: "Wasser" }));
    const ka = molekuelGeometrie(molekuel(WASSER, { name: "Wasser", darstellung: "kalotte" }));
    expect(ks.text).toBe("Molekül Wasser, Summenformel H2O, 3 Atome, 2 Bindungen.");
    expect(ka.atome.map((a) => a.radius)).toEqual([1.52, 1.2, 1.2]);
    expect(ka.radius).toBeGreaterThan(ks.radius);
    expect(kugelRadius(elementNachSymbol("O")!, "kalotte")).toBe(1.52);
  });

  it("angegebene Bindungen gelten statt der Abstände; Einzahl im Text", () => {
    const g = molekuelGeometrie(molekuel(WASSER, { bindungen: [{ von: 0, bis: 1, ordnung: 2 }] }));
    expect(g.bindungenAbgeleitet).toBe(false);
    expect(g.bindungen.map((b) => [b.von, b.bis, b.ordnung])).toEqual([[0, 1, 2]]);
    expect(g.text).toBe("Molekül, Summenformel H2O, 3 Atome, 1 Bindung.");
    expect(molekuelGeometrie(molekuel([at("He", 5, 5, 5)])).text).toBe("Molekül, Summenformel He, 1 Atom, 0 Bindungen.");
  });

  it("ohne gültiges Atom: leere Geometrie, kein Absturz", () => {
    const cfg = molekuel([at("Xx", 0, 0, 0)]);
    expect(cfg.ungueltig).toBe(true);
    const g = molekuelGeometrie(cfg);
    expect([g.atomzahl, g.radius, g.atome.length]).toEqual([0, 1, 0]);
    expect(molekuelGeometrie(null as unknown as MolekuelConfig).atomzahl).toBe(0);
  });
});

describe("Atom (Schalenmodell)", () => {
  it("Natrium mit und ohne Neutronen", () => {
    const na = atomModell(atom("Na", 12, 0, [2, 8, 1]));
    expect(na.text).toBe("Natrium, 11 Protonen, 12 Neutronen, 11 Elektronen in den Schalen 2, 8, 1. Vereinfachtes Schalenmodell.");
    expect([na.z, na.massenzahl, na.elektronen, na.ungueltig]).toEqual([11, 23, 11, false]);
    const ohne = atomModell(atom("Na", -1, 0, [2, 8, 1]));
    expect(ohne.text).toBe("Natrium, 11 Protonen, 11 Elektronen in den Schalen 2, 8, 1. Vereinfachtes Schalenmodell.");
    expect([ohne.neutronen, ohne.massenzahl]).toEqual([null, null]);
  });

  it("H+ und Cl− mit Ladung in Worten", () => {
    const h = atomModell(atom("H", -1, 1, []));
    expect(h.text).toBe("Wasserstoff, einfach positiv geladen, 1 Proton, keine Elektronen. Vereinfachtes Schalenmodell.");
    expect([h.elektronen, h.ungueltig]).toEqual([0, false]);
    const cl = atomModell(atom("Cl", 18, -1, [2, 8, 8]));
    expect(cl.text).toBe("Chlor, einfach negativ geladen, 17 Protonen, 18 Neutronen, 18 Elektronen in den Schalen 2, 8, 8. Vereinfachtes Schalenmodell.");
    expect(cl.massenzahl).toBe(35);
    expect(atomModell(atom("H", 0, 0, [1])).text).toBe("Wasserstoff, 1 Proton, 0 Neutronen, 1 Elektron in einer Schale. Vereinfachtes Schalenmodell.");
    expect([ladungText(2), ladungText(-3), ladungText(0)]).toEqual(["zweifach positiv geladen", "dreifach negativ geladen", ""]);
  });

  it("falsche Schalensumme, unbekanntes Element oder zu viel Ladung ist ungültig", () => {
    expect(atom("Na", 12, 0, [2, 8, 2]).ungueltig).toBe(true);
    expect(atom("Xx", 0, 0, [1]).ungueltig).toBe(true);
    expect(atom("na", 0, 0, [2, 8, 1]).ungueltig).toBe(true);
    expect(atom("H", -1, 3, []).ungueltig).toBe(true);                   // −2 Elektronen
    expect(atomModell(atom("Na", 12, 0, [2, 8, 2])).ungueltig).toBe(true);
  });

  it("ohne Schalen bis 20 Elektronen nach 2, 8, 8, 2, darüber ungültig; leere Schalen am Ende entfallen", () => {
    expect(normalizeTeilchen({ form: "atom", element: "Ca" })).toMatchObject({ schalen: [2, 8, 8, 2], ungueltig: false, neutronen: -1, ladung: 0 });
    expect(normalizeTeilchen({ form: "atom", element: "Fe" }).ungueltig).toBe(true);
    expect(atomModell(atom("Na", 12, 0, [2, 8, 1, 0, 0])).schalen).toEqual([2, 8, 1]);
  });
});

describe("Orbital-Wolke", () => {
  it("gleicher Startwert gleiche Punkte, anderer Startwert andere, nie Math.random", () => {
    const spy = vi.spyOn(Math, "random");
    const a = orbitalPunkte(orbital("2p_z", 2500, 7)), b = orbitalPunkte(orbital("2p_z", 2500, 7)), c = orbitalPunkte(orbital("2p_z", 2500, 8));
    expect(spy).not.toHaveBeenCalled();
    expect(a.anzahl).toBe(2500);
    expect(Array.from(a.positionen)).toEqual(Array.from(b.positionen));
    expect(Array.from(a.phasen)).toEqual(Array.from(b.phasen));
    expect(Array.from(a.positionen)).not.toEqual(Array.from(c.positionen));
  });

  it("5000 Punkte je Orbital, alle endlich, innerhalb der Versuchsgrenze; Zeit gemessen", () => {
    const zeiten: string[] = [];
    for (const o of ORBITALE) {
      const t0 = performance.now();
      const w = orbitalPunkte(orbital(o, 5000, 3));
      const dauer = ms(t0);
      zeiten.push(`${o} ${dauer} ms`);
      expect(dauer).toBeLessThan(1000);
      expect([w.anzahl, w.vollstaendig, w.positionen.length, w.phasen.length]).toEqual([5000, true, 15000, 5000]);
      expect(w.versuche).toBeLessThanOrEqual(200 * 5000);
      expect(w.plus + w.minus).toBe(5000);
      expect(Array.from(w.positionen).every(Number.isFinite)).toBe(true);
      expect(Array.from(w.phasen).every((p) => p === 1 || p === -1)).toBe(true);
      expect(Number.isFinite(w.ausdehnung) && w.ausdehnung > 0).toBe(true);
    }
    console.info(`[chem] Orbital-Wolken mit 5000 Punkten: ${zeiten.join(", ")}`);
  });

  it("Vorzeichen plausibel: 1s nur plus, 2p_z Vorzeichen gleich dem Vorzeichen von z, 3d_z2 beide", () => {
    const s = orbitalPunkte(orbital("1s"));
    expect([s.plus, s.minus]).toEqual([2500, 0]);
    const p = orbitalPunkte(orbital("2p_z"));
    for (let i = 0; i < p.anzahl; i++) expect(Math.sign(p.positionen[3 * i + 2])).toBe(p.phasen[i]);
    expect(p.plus / p.anzahl).toBeGreaterThan(0.4);
    expect(p.plus / p.anzahl).toBeLessThan(0.6);
    const px = orbitalPunkte(orbital("2p_x"));
    for (let i = 0; i < px.anzahl; i++) expect(Math.sign(px.positionen[3 * i])).toBe(px.phasen[i]);
    const dxy = orbitalPunkte(orbital("3d_xy"));
    for (let i = 0; i < dxy.anzahl; i++) expect(Math.sign(dxy.positionen[3 * i] * dxy.positionen[3 * i + 1])).toBe(dxy.phasen[i]);
    const dz = orbitalPunkte(orbital("3d_z2"));
    expect(dz.plus).toBeGreaterThan(0);
    expect(dz.minus).toBeGreaterThan(0);
    const s2 = orbitalPunkte(orbital("2s"));                               // außerhalb r = 2 Bohr-Radien Phase minus, innen plus
    for (let i = 0; i < s2.anzahl; i++) {
      const r = Math.hypot(s2.positionen[3 * i], s2.positionen[3 * i + 1], s2.positionen[3 * i + 2]);
      if (Math.abs(r - 2) > 1e-4) expect(s2.phasen[i]).toBe(r < 2 ? 1 : -1);
    }
    expect([phaseWort(1), phaseWort(-1)]).toEqual(["Phase plus", "Phase minus"]);
  });

  it("Ausdehnung wächst von 1s über 2p bis 3d", () => {
    const a = (o: OrbitalName) => orbitalPunkte(orbital(o)).ausdehnung;
    expect(a("1s")).toBeLessThan(a("2p_z"));
    expect(a("2p_z")).toBeLessThan(a("3d_xy"));
    expect(a("1s")).toBeLessThan(a("3d_z2"));
  });

  it("Text mit fester Beschreibung", () => {
    expect(orbitalPunkte(orbital("2p_z")).text).toBe("Orbital 2p_z, 2500 Punkte, zwei Lappen entlang der z-Achse mit entgegengesetzter Phase.");
    expect(orbitalPunkte(orbital("1s", 500)).text).toBe("Orbital 1s, 500 Punkte, kugelförmig, überall dieselbe Phase.");
  });
});

describe("Eingabe begrenzen", () => {
  it("gültige Eingaben bleiben unverändert", () => {
    const m = molekuel(WASSER, { name: "Wasser", bindungen: [{ von: 0, bis: 1, ordnung: 1 }], beschriftungen: [{ atom: 0, text: "Sauerstoff" }] });
    expect([m.angepasst, m.ungueltig]).toEqual([[], false]);
    expect(atom("Na", 12, 0, [2, 8, 1]).angepasst).toEqual([]);
    expect(orbital("3d_x2-y2", 1000, 42)).toEqual({ typ: "teilchen", form: "orbital", orbital: "3d_x2-y2", punkte: 1000, startwert: 42, angepasst: [], ungueltig: false });
  });

  it("unbekanntes Element im Molekül fällt mit Hinweis weg, Indizes rücken nach", () => {
    const m = molekuel([at("O", 0, 0, 0), at("Xx", 9, 9, 9), at("H", 0.96, 0, 0)], {
      bindungen: [{ von: 0, bis: 2, ordnung: 1 }, { von: 0, bis: 1, ordnung: 1 }], beschriftungen: [{ atom: 2, text: "H" }, { atom: 1, text: "weg" }],
    });
    expect(m.ungueltig).toBe(false);
    expect(m.atome.map((a) => a.element)).toEqual(["O", "H"]);
    expect(m.bindungen).toEqual([{ von: 0, bis: 1, ordnung: 1 }]);
    expect(m.beschriftungen).toEqual([{ atom: 1, text: "H" }]);
    expect(m.angepasst).toEqual(["atome.1.element", "bindungen.1", "beschriftungen.1"]);
  });

  it("Bindungen ins Leere, auf sich selbst, doppelt oder mit falscher Ordnung", () => {
    const m = molekuel(WASSER, {
      bindungen: [{ von: 0, bis: 1, ordnung: 1 }, { von: 1, bis: 0, ordnung: 1 }, { von: 2, bis: 2, ordnung: 1 }, { von: 0, bis: 9, ordnung: 1 },
        { von: 0.5, bis: 1, ordnung: 1 }, { von: 0, bis: 2, ordnung: 7 }],
    });
    expect(m.bindungen).toEqual([{ von: 0, bis: 1, ordnung: 1 }, { von: 0, bis: 2, ordnung: 3 }]);
    expect(m.angepasst).toEqual(["bindungen.1", "bindungen.2", "bindungen.3", "bindungen.4", "bindungen.5.ordnung"]);
  });

  it("Lagen, Texte und Zahlen werden begrenzt und notiert", () => {
    const m = molekuel([{ element: "C", position: [NaN, 500, -1e9] }, { element: "H", position: "0,0,0" }], {
      name: "x".repeat(80), darstellung: "wuerfel", beschriftungen: [{ atom: 0, text: "a\u202eb" + "y".repeat(50) }],
    });
    expect(m.atome.map((a) => a.position)).toEqual([[0, 200, -200], [0, 0, 0]]);
    expect([m.name.length, m.darstellung, m.beschriftungen[0].text.length]).toEqual([60, "kugel-stab", 40]);
    expect(m.beschriftungen[0].text.startsWith("ab")).toBe(true);
    expect(m.angepasst).toEqual(expect.arrayContaining(["name", "darstellung", "atome.0.position", "atome.1.position", "beschriftungen.0.text"]));
    const o = normalizeTeilchen({ form: "orbital", orbital: "2p_z", punkte: NaN, startwert: -5.5 }) as OrbitalConfig;
    expect([o.punkte, o.startwert, o.angepasst]).toEqual([2500, 0, ["punkte", "startwert"]]);
    expect((normalizeTeilchen({ form: "orbital", orbital: "1s", punkte: 1e9 }) as OrbitalConfig).punkte).toBe(5000);
    expect((normalizeTeilchen({ form: "orbital", orbital: "1s", punkte: 10 }) as OrbitalConfig).punkte).toBe(500);
    const a = normalizeTeilchen({ form: "atom", element: "O", neutronen: 999, ladung: NaN, schalen: [2, 6] }) as AtomConfig;
    expect([a.neutronen, a.ladung, a.ungueltig, a.angepasst]).toEqual([200, 0, false, ["neutronen", "ladung"]]);
  });

  it("unbekannte Form oder unbekanntes Orbital ist ungültig", () => {
    for (const x of [null, undefined, 3, "molekuel", [], {}, { form: "kristall" }, { form: "__proto__" }]) {
      const c = normalizeTeilchen(x);
      expect(c.ungueltig).toBe(true);
      expect(c.typ).toBe("teilchen");
    }
    const o = normalizeTeilchen({ form: "orbital", orbital: "4f_xyz" });
    expect([o.ungueltig, (o as OrbitalConfig).orbital]).toEqual([true, "1s"]);
    expect(normalizeTeilchen({ form: "molekuel", atome: [] }).ungueltig).toBe(true);
    expect(normalizeTeilchen({ form: "molekuel" }).ungueltig).toBe(true);
  });

  it("10 000 Atome werden auf 300 gekürzt, ohne alle zu lesen; Rechnen bleibt schnell", () => {
    let gelesen = 0;
    const atome = Array.from({ length: 10_000 }, (_, i) => ({
      get element() { gelesen++; return "C"; }, position: [(i % 20) * 1.5, Math.floor(i / 20) * 1.5, 0] as V3,
    }));
    const t0 = performance.now();
    const m = molekuel(atome);
    const g = molekuelGeometrie(m);
    const dauer = ms(t0);
    console.info(`[chem] 10 000 Atome normalisieren und Geometrie: ${dauer} ms`);
    expect(m.atome).toHaveLength(300);
    expect(m.angepasst).toContain("atome");
    expect(gelesen).toBeLessThanOrEqual(300);
    expect(g.atomzahl).toBe(300);
    expect(g.bindungszahl).toBeLessThanOrEqual(400);
    expect(dauer).toBeLessThan(1000);
    expect(molekuel(Array.from({ length: 401 }, () => at("H", 0, 0, 0)), {
      bindungen: Array.from({ length: 500 }, (_, i) => ({ von: 0, bis: i + 1, ordnung: 1 })),
    }).bindungen).toHaveLength(299);                                       // 400 gelesen, Indizes über 299 fallen weg
  });

  it("__proto__-Schlüssel verschmutzen nichts und werden nicht gelesen", () => {
    const roh = JSON.parse('{"form":"molekuel","__proto__":{"darstellung":"kalotte","polluted":1},'
      + '"atome":[{"element":"__proto__","position":[0,0,0]},{"element":"C","position":[0,0,0],"__proto__":{"element":"O"}}],'
      + '"bindungen":[{"__proto__":{"von":0,"bis":1}}]}');
    const m = molekuel(roh.atome, { __proto__: { name: "x" } });
    expect(m.atome.map((a) => a.element)).toEqual(["C"]);
    const n = normalizeTeilchen(roh) as MolekuelConfig;
    expect([n.darstellung, n.atome.length, n.bindungen.length]).toEqual(["kugel-stab", 1, 0]);
    expect(({} as Record<string, unknown>).polluted).toBeUndefined();
    expect(Object.prototype.hasOwnProperty.call(Object.prototype, "polluted")).toBe(false);
  });

  it("werfende Getter und Proxys werfen nicht nach außen", () => {
    const boese = { form: "molekuel", get atome(): unknown { throw new Error("boom"); } };
    const c = normalizeTeilchen(boese);
    expect(c.ungueltig).toBe(true);
    expect(c.angepasst).toContain("intern");
    const falle = new Proxy({}, { get() { throw new Error("x"); }, has() { throw new Error("x"); }, getOwnPropertyDescriptor() { throw new Error("x"); } });
    expect(() => normalizeTeilchen(falle)).not.toThrow();
    expect(normalizeTeilchen(falle).ungueltig).toBe(true);
    expect(() => molekuelGeometrie(boese as unknown as MolekuelConfig)).not.toThrow();
    expect(() => atomModell(falle as AtomConfig)).not.toThrow();
    expect(() => orbitalPunkte(falle as OrbitalConfig)).not.toThrow();
    expect(orbitalPunkte(falle as OrbitalConfig).anzahl).toBe(2500);       // Ersatz: 1s mit Standardzahl
    expect(() => summenformel([falle] as unknown as MolekuelAtom[])).not.toThrow();
    expect(() => bindungenAusAbstand([falle, falle] as unknown as MolekuelAtom[])).not.toThrow();
  });

  it("Helfer begrenzen noch einmal, wenn die Eingabe am Backend vorbei kommt", () => {
    const w = orbitalPunkte({ typ: "teilchen", form: "orbital", orbital: "2p_z", punkte: 1e7, startwert: NaN, angepasst: [], ungueltig: false } as OrbitalConfig);
    expect(w.anzahl).toBe(5000);
    const a = atomModell({ typ: "teilchen", form: "atom", element: "Na", neutronen: Infinity, ladung: 9, schalen: [2, 8, 1], angepasst: [], ungueltig: false } as AtomConfig);
    expect([a.ladung, a.neutronen, a.ungueltig]).toEqual([3, null, true]);
    expect([komma(-0.001), komma(1.005, 1), komma(NaN), komma(-12.346)]).toEqual(["0,00", "1,0", "–", "-12,35"]);
  });
});
