// Kamerabahn der 3D-Betrachter (aus Model3D.tsx gezogen, Plan docs/ui-p5-plan.md, Abschnitt 7): die Kamera kreist auf einer
// Kugel um einen Mittelpunkt. Reine Funktionen ohne DOM und ohne three.js; jede Zahl, die das Modul verlässt, ist endlich.
// Benutzt von Model3D (szene3d), Molecule3D und Orbital3D (teilchen). Tasten mit Strg, Alt oder Meta gehören dem Browser.

export type V3 = [number, number, number];
/** theta: Drehung um die senkrechte Achse; phi: Winkel von oben (0 = von oben, π = von unten); dist: Abstand zum Mittelpunkt. */
export interface Orbit { theta: number; phi: number; dist: number }
export type OrbitAction = "left" | "right" | "up" | "down" | "in" | "out" | "reset";

/** Knöpfe in fester Reihenfolge mit ihrer Beschriftung (alles auch ohne Maus und ohne Tasten bedienbar). */
export const ORBIT_BUTTONS: readonly (readonly [OrbitAction, string])[] = [
  ["left", "Links drehen"], ["right", "Rechts drehen"], ["up", "Nach oben kippen"], ["down", "Nach unten kippen"],
  ["in", "Näher"], ["out", "Weiter weg"], ["reset", "Ansicht zurücksetzen"],
];
/** Tasten ohne Strg, Alt und Meta. */
export const ORBIT_KEYS: Readonly<Record<string, OrbitAction>> = {
  ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down", "+": "in", "-": "out", "0": "reset", Home: "reset",
};
export const ORBIT_HINT = "3D-Ansicht. Pfeiltasten drehen, Plus und Minus zoomen, Null setzt zurück.";

const PHI_MIN = 0.15;
const PHI_MAX = Math.PI - PHI_MIN;
const TURN = 0.2, TILT = 0.15, ZOOM = 0.85, DRAG = 0.01;
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** Größe der Szene (Durchmesser, zum Beispiel die Diagonale der Hüllbox); kaputt oder zu klein wird 1e-6 bzw. 1. */
export function orbitSize(size: number): number {
  return Number.isFinite(size) && size > 0 ? Math.max(1e-6, size) : 1;
}

/** Startlage: schräg von vorn oben, Abstand 1,3 × Größe (eine Kugel mit dem Durchmesser `size` passt in 45 Grad Bildwinkel). */
export function orbitHome(size: number): Orbit {
  return { theta: 0.7, phi: 1.15, dist: orbitSize(size) * 1.3 };
}

const safe = (o: Orbit, size: number): Orbit => {
  const home = orbitHome(size);
  return {
    theta: Number.isFinite(o.theta) ? o.theta : home.theta,
    phi: Number.isFinite(o.phi) ? clamp(o.phi, PHI_MIN, PHI_MAX) : home.phi,
    dist: Number.isFinite(o.dist) && o.dist > 0 ? o.dist : home.dist,
  };
};

/** Ein Schritt per Knopf oder Taste. Kippen bleibt zwischen 0,15 und π − 0,15, Zoom zwischen 0,2 und 10 × Größe. */
export function orbitStep(o: Orbit, action: OrbitAction, size: number): Orbit {
  const s = orbitSize(size), v = safe(o, s);
  switch (action) {
    case "left": return { ...v, theta: v.theta - TURN };
    case "right": return { ...v, theta: v.theta + TURN };
    case "up": return { ...v, phi: Math.max(PHI_MIN, v.phi - TILT) };
    case "down": return { ...v, phi: Math.min(PHI_MAX, v.phi + TILT) };
    case "in": return { ...v, dist: Math.max(s * 0.2, v.dist * ZOOM) };
    case "out": return { ...v, dist: Math.min(s * 10, v.dist / ZOOM) };
    case "reset": return orbitHome(s);
    default: return v;
  }
}

/** Ziehen mit Maus oder Finger um dx, dy Pixel. */
export function orbitDrag(o: Orbit, dx: number, dy: number, size: number): Orbit {
  const v = safe(o, size);
  const x = Number.isFinite(dx) ? dx : 0, y = Number.isFinite(dy) ? dy : 0;
  return { ...v, theta: v.theta - x * DRAG, phi: clamp(v.phi - y * DRAG, PHI_MIN, PHI_MAX) };
}

/** Lage der Kamera um den Mittelpunkt. */
export function orbitEye(o: Orbit, center: V3, size: number): V3 {
  const v = safe(o, size);
  const c = center.map((x) => (Number.isFinite(x) ? x : 0));
  const s = Math.sin(v.phi);
  return [c[0] + v.dist * s * Math.sin(v.theta), c[1] + v.dist * Math.cos(v.phi), c[2] + v.dist * s * Math.cos(v.theta)];
}

/** Aktion zu einer Taste; null bei unbekannter Taste oder mit Strg, Alt oder Meta (die gehören dem Browser). */
export function orbitKey(e: { key: string; ctrlKey?: boolean; altKey?: boolean; metaKey?: boolean }): OrbitAction | null {
  if (e.ctrlKey || e.altKey || e.metaKey) return null;
  return Object.prototype.hasOwnProperty.call(ORBIT_KEYS, e.key) ? ORBIT_KEYS[e.key] : null;
}

/** Mausrad: nach vorn näher, nach hinten weiter weg. */
export const orbitWheel = (deltaY: number): OrbitAction => (deltaY < 0 ? "in" : "out");
