import { describe, expect, it } from "vitest";
import { ORBIT_BUTTONS, orbitDrag, orbitEye, orbitHome, orbitKey, orbitSize, orbitStep, orbitWheel, type Orbit } from "./lib/orbitCamera";

// Kamerabahn der 3D-Betrachter (aus Model3D.tsx gezogen, P5b): reine Funktionen, Grenzen, Tasten ohne Strg, Alt und Meta.

const close = (a: number, b: number) => expect(Math.abs(a - b)).toBeLessThan(1e-9);

describe("Kamerabahn", () => {
  it("Startlage wie in P4a: schräg von vorn oben, Abstand 1,3 × Größe", () => {
    expect(orbitHome(10)).toEqual({ theta: 0.7, phi: 1.15, dist: 13 });
    expect(orbitHome(Number.NaN).dist).toBe(1.3);                                  // kaputte Größe: 1
    expect(orbitHome(-5).dist).toBe(1.3);
    expect(orbitSize(1e-12)).toBe(1e-6);
  });

  it("Drehen, Kippen und Zoomen bleiben in den Grenzen; Zurücksetzen holt die Startlage", () => {
    let o: Orbit = orbitHome(10);
    o = orbitStep(o, "left", 10); close(o.theta, 0.5);
    o = orbitStep(o, "right", 10); o = orbitStep(o, "right", 10); close(o.theta, 0.9);
    for (let i = 0; i < 50; i++) o = orbitStep(o, "up", 10);
    close(o.phi, 0.15);
    for (let i = 0; i < 50; i++) o = orbitStep(o, "down", 10);
    close(o.phi, Math.PI - 0.15);
    for (let i = 0; i < 80; i++) o = orbitStep(o, "in", 10);
    close(o.dist, 2);                                                                // 0,2 × Größe
    for (let i = 0; i < 80; i++) o = orbitStep(o, "out", 10);
    close(o.dist, 100);                                                              // 10 × Größe
    expect(orbitStep(o, "reset", 10)).toEqual(orbitHome(10));
  });

  it("Ziehen dreht und kippt; das Kippen bleibt begrenzt", () => {
    const o = orbitDrag(orbitHome(4), 20, -10, 4);
    close(o.theta, 0.5); close(o.phi, 1.25);
    expect(orbitDrag(o, 0, 10_000, 4).phi).toBe(0.15);
    expect(orbitDrag(o, Number.NaN, Number.POSITIVE_INFINITY, 4)).toEqual(o);
  });

  it("Kameralage wie in P4a gerechnet, nie NaN", () => {
    const o = orbitHome(10), c: [number, number, number] = [1, 2, 3];
    const e = orbitEye(o, c, 10), s = Math.sin(1.15);
    close(e[0], 1 + 13 * s * Math.sin(0.7)); close(e[1], 2 + 13 * Math.cos(1.15)); close(e[2], 3 + 13 * s * Math.cos(0.7));
    const bad = orbitEye({ theta: Number.NaN, phi: Number.NaN, dist: -1 }, [Number.NaN, 0, 0], 10);
    expect(bad.every(Number.isFinite)).toBe(true);
  });

  it("Tasten: Pfeile, Plus, Minus, Null, Pos1; mit Strg, Alt oder Meta gehört die Taste dem Browser", () => {
    expect(orbitKey({ key: "ArrowLeft" })).toBe("left");
    expect(orbitKey({ key: "+" })).toBe("in");
    expect(orbitKey({ key: "-" })).toBe("out");
    expect(orbitKey({ key: "0" })).toBe("reset");
    expect(orbitKey({ key: "Home" })).toBe("reset");
    expect(orbitKey({ key: "x" })).toBeNull();
    expect(orbitKey({ key: "toString" })).toBeNull();                               // keine geerbten Schlüssel
    for (const mod of ["ctrlKey", "altKey", "metaKey"]) expect(orbitKey({ key: "+", [mod]: true })).toBeNull();
    expect(orbitWheel(-1)).toBe("in");
    expect(orbitWheel(3)).toBe("out");
  });

  it("Knöpfe in fester Reihenfolge mit den Beschriftungen aus P4a", () => {
    expect(ORBIT_BUTTONS.map(([, t]) => t)).toEqual(
      ["Links drehen", "Rechts drehen", "Nach oben kippen", "Nach unten kippen", "Näher", "Weiter weg", "Ansicht zurücksetzen"]);
  });
});
