import { useEffect, useState, type RefObject } from "react";

export interface Box { width: number; height: number }

/** Misst ein Element (ResizeObserver). Ohne Messung (z. B. in Tests) bleibt der Wert `null`: der Aufrufer nimmt dann einen festen Standard. */
export function useBoxSize(ref: RefObject<HTMLElement | null>): Box | null {
  const [box, setBox] = useState<Box | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const r = entries[0]?.contentRect;
      if (r && r.width > 0 && r.height > 0) setBox({ width: Math.round(r.width), height: Math.round(r.height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return box;
}

export const AVATAR_MIN = 120;
export const AVATAR_MAX = 440;
export const AVATAR_DEFAULT = 260;

/** Größe des 3D-Kerns in Ruhe: groß in der Mitte, aber Status, Verlauf und Panels bleiben sichtbar. Ab 1000 px teilt sich
 *  die Breite in Spalten (Kern nur in der mittleren), darunter steht er allein in der Breite. */
export function avatarSize(box: Box | null): number {
  if (!box) return AVATAR_DEFAULT;
  const byWidth = box.width * (box.width >= 1000 ? 0.36 : 0.7);
  const byHeight = box.height * 0.5;
  return Math.round(Math.max(AVATAR_MIN, Math.min(AVATAR_MAX, byWidth, byHeight)));
}

/** Kleiner Kern, wenn die Bühne Inhalt zeigt (Modus „Begleiten“): rückt zur Seite und macht der Karte Platz. */
export function coreSmall(box: Box | null): number {
  return Math.max(AVATAR_MIN, Math.round(avatarSize(box) * 0.45));
}
