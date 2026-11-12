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
export const AVATAR_MAX = 600;
export const AVATAR_DEFAULT = 320;

/** Größe des 3D-Kerns im Gespräch: allein und groß in der Mitte; Zustandswort und Hinweise bleiben darunter sichtbar. */
export function avatarSize(box: Box | null): number {
  if (!box) return AVATAR_DEFAULT;
  const byWidth = box.width * 0.7;
  const byHeight = box.height * 0.68;
  return Math.round(Math.max(AVATAR_MIN, Math.min(AVATAR_MAX, byWidth, byHeight)));
}

/** Kleiner Kern, wenn kushim etwas zeigt (Zeige-Modus): rückt zur Seite und macht dem Inhalt Platz. */
export function coreSmall(box: Box | null): number {
  return Math.max(AVATAR_MIN, Math.min(220, Math.round(avatarSize(box) * 0.4)));
}
