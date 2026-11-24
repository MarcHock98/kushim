import type { ReactNode } from "react";
import { IconVoiceCpu, IconVoiceLoading, IconVoiceOff, IconVoiceReady } from "./Icons";

// Stimm-Chip: Zustand der Sprachausgabe aus `voice.state` (Feld `tts`, src/kushim/voice/statefile.py). Nur Anzeige: der Chip
// sendet nichts, speichert nichts und ist kein Bedienelement. Immer Wort plus Symbol, nie nur Farbe.

export type TtsState = "loading" | "ready" | "cpu" | "failed" | "off";

const TTS_STATES: readonly TtsState[] = ["loading", "ready", "cpu", "failed", "off"];

/** Feld `tts` aus voice.state prüfen. Fehlt es (älterer Dienst) oder ist es unbekannt: null, dann gibt es keinen Chip. */
export function parseTts(v: unknown): TtsState | null {
  return typeof v === "string" && (TTS_STATES as readonly string[]).includes(v) ? (v as TtsState) : null;
}

interface ChipView { long: string; short: string; tone: string; icon: ReactNode }

/** Wörter (lang für die Kopfzeile, kurz für das kleine Fenster), feste Klasse je Zustand und Symbol. */
export const VOICE_CHIP: Record<TtsState, ChipView> = {
  loading: { long: "Stimme lädt", short: "lädt", tone: "voice-chip is-loading", icon: <IconVoiceLoading /> },
  ready: { long: "Stimme bereit", short: "bereit", tone: "voice-chip is-ready", icon: <IconVoiceReady /> },
  cpu: { long: "Stimme langsam (CPU)", short: "CPU", tone: "voice-chip is-cpu", icon: <IconVoiceCpu /> },
  failed: { long: "Stimme aus, nur Text", short: "nur Text", tone: "voice-chip is-text", icon: <IconVoiceOff /> },
  off: { long: "Stimme aus, nur Text", short: "nur Text", tone: "voice-chip is-text", icon: <IconVoiceOff /> },
};

/** Der Chip. Groß: langes Wort (in sehr schmalen Fenstern per CSS das kurze, das lange bleibt für Screenreader).
 *  Klein (`compact`): kurzes Wort, das lange im `title` und für Screenreader. */
export function VoiceChip({ tts, compact = false }: { tts: TtsState; compact?: boolean }) {
  const v = VOICE_CHIP[tts];
  return (
    <span className={compact ? `${v.tone} is-compact` : v.tone} title={v.long} aria-live="polite">
      {v.icon}
      {compact
        ? <><span aria-hidden="true">{v.short}</span><span className="v-sr">{v.long}</span></>
        : <><span className="voice-long">{v.long}</span><span className="voice-short" aria-hidden="true">{v.short}</span></>}
    </span>
  );
}
