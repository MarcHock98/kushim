// Zustände des Avatars (siehe .claude/skills/kushim-ui-design/references/avatar-states.md).
// Die UI erfindet keine Zustände: sie zeigt, was das Backend meldet. `offline` und `halted` haben Vorrang.

export type AvatarState =
  | "idle" | "listening" | "thinking" | "speaking" | "asking" | "alarm" | "halted" | "offline";

const ALL: readonly string[] = ["idle", "listening", "thinking", "speaking", "asking", "alarm", "halted", "offline"];
export const isAvatarState = (v: unknown): v is AvatarState => typeof v === "string" && ALL.includes(v);

export interface StateView {
  label: string;      // Textzeile, immer sichtbar (Zustand nie nur über Farbe)
  live: "polite" | "assertive";
}

export const STATE_VIEW: Record<AvatarState, StateView> = {
  idle: { label: "Bereit. Sag „hey kushim“.", live: "polite" },
  listening: { label: "Ich höre zu …", live: "polite" },
  thinking: { label: "Ich denke nach …", live: "polite" },
  speaking: { label: "Ich spreche.", live: "polite" },
  asking: { label: "Wartet auf deine Freigabe.", live: "polite" },
  alarm: { label: "Stimme nicht erkannt. Keine Antwort.", live: "assertive" },
  halted: { label: "NOTAUS aktiv. Zum Fortfahren aufheben.", live: "assertive" },
  offline: { label: "Backend nicht erreicht.", live: "assertive" },
};

export interface Inputs {
  connected: boolean;
  killActive: boolean | null;       // null = unbekannt
  backendState?: AvatarState;       // vom Backend gemeldet (noch nicht vorhanden, siehe docs)
}

/** Vorrang: offline > halted > alarm > Backend-Zustand > idle. */
export function resolveState(i: Inputs): AvatarState {
  if (!i.connected) return "offline";
  if (i.killActive) return "halted";
  if (i.backendState === "alarm") return "alarm";
  return i.backendState ?? "idle";
}
