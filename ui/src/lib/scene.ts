import type { Block } from "./stage";

// Rechenlogik für die 3D-Szene und den Plan (Plan docs/ui-p4-plan.md). Reine Funktionen, ohne three.js und ohne DOM,
// damit sie sich ohne Grafik testen lassen. Alle Zahlen stammen von Claude und sind im Backend auf endliche Werte geprüft.

export type SceneBlock = Extract<Block, { typ: "szene3d" }>;
export type Obj = SceneBlock["szenen"][number]["objekte"][number];
export type PlanBlock = Extract<Block, { typ: "plan2d" }>;
export type PlanEl = PlanBlock["elemente"][number];
export type V3 = [number, number, number];
export interface Box3 { min: V3; max: V3 }

/** Palettenname → CSS-Variable (freie Farben gibt es nicht, alles bleibt im Designsystem). */
export const PALETTE_VAR: Record<string, string> = {
  arc: "--arc", amber: "--amber", ok: "--ok", warn: "--warn", alarm: "--alarm", text: "--text", gedaempft: "--text-muted",
};

const RAD = Math.PI / 180;

/** Dreht einen Punkt wie three.js bei Euler-Reihenfolge XYZ (erst Z, dann Y, dann X), Winkel in Grad. */
export function rotate(p: V3, deg: V3): V3 {
  let [x, y, z] = p;
  const [ax, ay, az] = [deg[0] * RAD, deg[1] * RAD, deg[2] * RAD];
  [x, y] = [x * Math.cos(az) - y * Math.sin(az), x * Math.sin(az) + y * Math.cos(az)];
  [x, z] = [x * Math.cos(ay) + z * Math.sin(ay), -x * Math.sin(ay) + z * Math.cos(ay)];
  [y, z] = [y * Math.cos(ax) - z * Math.sin(ax), y * Math.sin(ax) + z * Math.cos(ax)];
  return [x, y, z];
}

/** Halbe Ausdehnung des Körpers in seinem eigenen Raum (Achsen wie bei three.js: Zylinder und Kegel stehen auf y). */
function halfSize(o: Exclude<Obj, { form: "linie" }>): V3 {
  const m = o.masse;
  switch (o.form) {
    case "box": return [m[0] / 2, m[1] / 2, m[2] / 2];
    case "kugel": return [m[0], m[0], m[0]];
    case "zylinder": case "kegel": return [m[0], m[1] / 2, m[0]];
    case "torus": return [m[0] + m[1], m[0] + m[1], m[1]];
    case "ebene": return [m[0] / 2, m[1] / 2, 0];
  }
}

export function objectBounds(o: Obj): Box3 {
  if (o.form === "linie") {
    const xs = o.punkte.map((p) => p[0]), ys = o.punkte.map((p) => p[1]), zs = o.punkte.map((p) => p[2]);
    return { min: [Math.min(...xs), Math.min(...ys), Math.min(...zs)], max: [Math.max(...xs), Math.max(...ys), Math.max(...zs)] };
  }
  const h = halfSize(o);
  const min: V3 = [Infinity, Infinity, Infinity], max: V3 = [-Infinity, -Infinity, -Infinity];
  for (const sx of [-1, 1]) for (const sy of [-1, 1]) for (const sz of [-1, 1]) {
    const q = rotate([sx * h[0], sy * h[1], sz * h[2]], o.drehung);
    for (let i = 0; i < 3; i++) {
      min[i] = Math.min(min[i], q[i] + o.position[i]);
      max[i] = Math.max(max[i], q[i] + o.position[i]);
    }
  }
  return { min, max };
}

export function unionBounds(boxes: Box3[]): Box3 {
  const min: V3 = [Infinity, Infinity, Infinity], max: V3 = [-Infinity, -Infinity, -Infinity];
  for (const b of boxes) for (let i = 0; i < 3; i++) { min[i] = Math.min(min[i], b.min[i]); max[i] = Math.max(max[i], b.max[i]); }
  return { min, max };
}

export function sceneBounds(objs: Obj[]): Box3 { return unionBounds(objs.map(objectBounds)); }
export function allBounds(b: SceneBlock): Box3 { return unionBounds(b.szenen.map((s) => sceneBounds(s.objekte))); }

export const fmt = (n: number) => n.toLocaleString("de-DE", { maximumFractionDigits: 2 });

/** Hüllmaße in Worten. Ohne Einheit von Claude steht ausdrücklich „Einheit unbekannt“. */
export function describeSize(box: Box3, einheit: string): string {
  const d = [0, 1, 2].map((i) => fmt(box.max[i] - box.min[i]));
  return `Breite ${d[0]} × Höhe ${d[1]} × Tiefe ${d[2]} ${einheit || "(Einheit unbekannt)"}`.trim();
}

export interface SceneDiff { neu: string[]; weg: string[]; geaendert: string[] }

/** Vergleicht zwei Szenen nur über benannte Objekte (Namen sind die Schlüssel; Objekte ohne Namen bleiben außen vor). */
export function diffScenes(a: Obj[], b: Obj[]): SceneDiff {
  const ma = new Map(a.filter((o) => o.name).map((o) => [o.name, JSON.stringify(o)]));
  const mb = new Map(b.filter((o) => o.name).map((o) => [o.name, JSON.stringify(o)]));
  return {
    neu: [...mb.keys()].filter((k) => !ma.has(k)),
    weg: [...ma.keys()].filter((k) => !mb.has(k)),
    geaendert: [...mb.keys()].filter((k) => ma.has(k) && ma.get(k) !== mb.get(k)),
  };
}

export function diffText(d: SceneDiff): string {
  const parts = [d.neu.length && `neu: ${d.neu.join(", ")}`, d.weg.length && `entfernt: ${d.weg.join(", ")}`,
    d.geaendert.length && `verändert: ${d.geaendert.join(", ")}`].filter(Boolean);
  return parts.length ? parts.join("; ") : "keine Unterschiede bei benannten Objekten";
}

export function describeObject(o: Obj): string {
  if (o.form === "linie") return `Linie, ${o.punkte.length} Punkte`;
  const m = o.masse.map(fmt).join(" × ");
  return `${o.form} ${m}`;
}

// ----- Plan ------------------------------------------------------------------------------------------------------

export interface Box2 { minX: number; minY: number; maxX: number; maxY: number }

export function elementBounds(e: PlanEl): Box2 {
  switch (e.art) {
    case "linie": case "mass":
      return { minX: Math.min(e.von[0], e.bis[0]), minY: Math.min(e.von[1], e.bis[1]), maxX: Math.max(e.von[0], e.bis[0]), maxY: Math.max(e.von[1], e.bis[1]) };
    case "polylinie": {
      const xs = e.punkte.map((p) => p[0]), ys = e.punkte.map((p) => p[1]);
      return { minX: Math.min(...xs), minY: Math.min(...ys), maxX: Math.max(...xs), maxY: Math.max(...ys) };
    }
    case "rechteck": return { minX: e.x, minY: e.y, maxX: e.x + e.b, maxY: e.y + e.h };
    case "kreis": return { minX: e.x - e.r, minY: e.y - e.r, maxX: e.x + e.r, maxY: e.y + e.r };
    case "bogen": {                                                  // Endpunkte und alle Viertelkreis-Punkte im Bereich
      const sweep = ((e.bis - e.von) % 360 + 360) % 360 || 360;
      const angles = [e.von, e.bis];
      for (let a = Math.ceil(e.von / 90) * 90; a < e.von + sweep; a += 90) angles.push(a);
      const xs = angles.map((a) => e.x + e.r * Math.cos(a * RAD)), ys = angles.map((a) => e.y + e.r * Math.sin(a * RAD));
      return { minX: Math.min(...xs), minY: Math.min(...ys), maxX: Math.max(...xs), maxY: Math.max(...ys) };
    }
    case "text": return { minX: e.x, minY: e.y, maxX: e.x, maxY: e.y };
  }
}

export function planBounds(els: PlanEl[]): Box2 {
  const b: Box2 = { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity };
  for (const e of els) {
    const q = elementBounds(e);
    b.minX = Math.min(b.minX, q.minX); b.minY = Math.min(b.minY, q.minY); b.maxX = Math.max(b.maxX, q.maxX); b.maxY = Math.max(b.maxY, q.maxY);
  }
  return b;
}

export const lengthOf = (a: [number, number], b: [number, number]) => Math.hypot(b[0] - a[0], b[1] - a[1]);

/** Text einer Maßlinie: Claudes Text, sonst die selbst gerechnete Länge mit Einheit (oder „Einheit unbekannt“). */
export function measureText(e: Extract<PlanEl, { art: "mass" }>, einheit: string): string {
  return e.text || `${fmt(lengthOf(e.von, e.bis))} ${einheit || "(Einheit unbekannt)"}`;
}

/** Anfang, Ende und „großer Bogen“-Marke eines Kreisbogens. Winkel in Grad gegen den Uhrzeigersinn, y zeigt nach oben. */
export function arcEnds(x: number, y: number, r: number, from: number, to: number) {
  const p = (deg: number): [number, number] => [x + r * Math.cos(deg * RAD), y + r * Math.sin(deg * RAD)];
  const sweep = ((to - from) % 360 + 360) % 360;
  return { start: p(from), end: p(to), large: sweep > 180 };
}
