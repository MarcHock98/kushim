// Client für die Backend-API (`kushim serve`): nur ws://127.0.0.1, Token nur im Speicher.
// Die UI führt nichts selbst aus, sie sendet nur Anfragen {type, ...}; das Backend entscheidet.

export interface Credentials { port: number; token: string }
export type ApiReply = { ok: true; [k: string]: unknown } | { ok: false; error: string };

export interface Socket {
  send(data: string): void;
  close(): void;
  onmessage: ((e: { data: unknown }) => void) | null;
  onclose: (() => void) | null;
  onopen: (() => void) | null;
  onerror: (() => void) | null;
}
export type SocketFactory = (url: string) => Socket;

const TIMEOUT_MS = 10_000;

// ----- Mikrofon-Schwellen zur Laufzeit (voice.tuning.*). Das Backend prüft Grenzen, Notaus und ob der Sprachdienst läuft. -----

/** Die vier Werte, die sich im laufenden Betrieb verstellen lassen (Einheiten: Pegel als RMS-Rohwert 0 bis 32767,
 *  Millisekunden ganzzahlig, Sekunden). Pegel können Kommazahlen sein (Stufen der Sprachsteuerung, auf 0,1 gerundet). */
export type TuningKey = "speech_level" | "barge_in_level" | "barge_in_ms" | "end_silence_seconds";
export type TuningValues = Record<TuningKey, number>;
/** Grenzen in der Oberfläche immer als [min, max]. */
export type TuningBounds = Record<TuningKey, [number, number]>;
/** Grenzen, wie das Backend sie liefert (`voice/tuning.py: bounds()`): {name: {min, max}} plus die Stufe. Die ältere Form
 *  [min, max] aus dem ersten Vertrag wird ebenfalls angenommen. */
export type WireBound = { min: number; max: number } | [number, number];
export type WireBounds = Partial<Record<TuningKey | "step", WireBound>>;
export const TUNING_KEYS: readonly TuningKey[] = ["speech_level", "barge_in_level", "barge_in_ms", "end_silence_seconds"];
/** Grenzen laut Vertrag; gelten nur, wenn das Backend für einen Wert keine brauchbaren Grenzen liefert. */
export const TUNING_BOUNDS: TuningBounds = {
  speech_level: [80, 600], barge_in_level: [150, 1500], barge_in_ms: [160, 400], end_silence_seconds: [0.6, 3.0],
};
/** Höchster Pegel (16-Bit-Rohwert) für RMS und Spitze. */
export const LEVEL_RAW_MAX = 32767;

/** Antwort auf `voice.tuning.get` (und auf erfolgreiche set/reset/save): aktive Werte, Werte aus wakewords.toml, Grenzen,
 *  Stufe der Sprachsteuerung (-2 bis 2), Live-Pegel (RMS und Spitze, Rohwerte), wer zuletzt verstellt hat und ein Zähler
 *  `version`, der jede Änderung zählt. Ohne Sprachdienst (`active: false`) kommen die Werte aus der Datei, Pegel 0; ist
 *  die Datei fehlerhaft, sind `values` und `file_values` null. */
export interface TuningState {
  active: boolean;
  values: TuningValues | null;
  file_values: TuningValues | null;
  bounds: TuningBounds;
  step: number;
  rms: number;
  peak: number;
  last_source: "ui" | "voice" | "file";
  version: number;
}
/** `voice.tuning.set {values: teilweise, confirm: true}`; `reset` und `save` nur mit `confirm: true`. `save` meldet
 *  zusätzlich `backup`: ob vorher eine Sicherungskopie (wakewords.toml.bak) angelegt wurde. */
export type TuningSetRequest = { values: Partial<TuningValues>; confirm: true };
export type TuningError = "invalid" | "kill" | "unavailable" | "bad_request" | "confirm_required" | "broken_file" | "not_saved";

export class ApiClient {
  private sock: Socket | null = null;
  private waiting: Array<(r: ApiReply) => void> = [];
  private unsupported = new Set<string>();           // Typen, die dieser Dienst nicht kennt: nicht erneut abfragen
  onDisconnect: () => void = () => {};

  constructor(private creds: Credentials, private make: SocketFactory = (u) => new WebSocket(u) as unknown as Socket) {
    if (!Number.isInteger(creds.port) || creds.port < 1 || creds.port > 65535) throw new Error("bad port");
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      const s = this.make(`ws://127.0.0.1:${this.creds.port}`);   // Host ist fest, nie aus Eingaben
      this.sock = s;
      s.onopen = () => resolve();
      s.onerror = () => reject(new Error("ws-connect"));
      s.onmessage = (e) => {
        const next = this.waiting.shift();           // der Server antwortet in Reihenfolge
        if (!next) return;
        try { next(JSON.parse(String(e.data)) as ApiReply); } catch { next({ ok: false, error: "bad_reply" }); }
      };
      s.onclose = () => {
        this.sock = null;
        this.waiting.splice(0).forEach((w) => w({ ok: false, error: "offline" }));
        this.onDisconnect();
      };
    });
  }

  call(type: string, data: Record<string, unknown> = {}): Promise<ApiReply> {
    const s = this.sock;
    if (!s) return Promise.resolve({ ok: false, error: "offline" });
    if (this.unsupported.has(type)) return Promise.resolve({ ok: false, error: "unknown_type" });
    return new Promise((resolve) => {
      let done = false;
      const finish = (r: ApiReply) => {
        if (done) return;
        done = true;
        clearTimeout(t);
        if (!r.ok && r.error === "unknown_type") this.unsupported.add(type);
        resolve(r);
      };
      const t = setTimeout(() => {
        finish({ ok: false, error: "timeout" });
        s.close();                                   // Antworten wären sonst verschoben: neu verbinden
      }, TIMEOUT_MS);
      this.waiting.push(finish);
      s.send(JSON.stringify({ ...data, type, token: this.creds.token }));
    });
  }

  close(): void { this.sock?.close(); }
}
