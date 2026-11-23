// E2: Befehle für das eigene Fenster (Rustteil, ui/src-tauri/src/main.rs). Sie ändern nur Größe, Lage und „immer im
// Vordergrund“; keiner holt den Fokus. Im Browser (Mock, Tests ohne Tauri) tun sie nichts: dort schaltet nur die CSS-Klasse.
import { invoke } from "@tauri-apps/api/core";

export type WindowCommand = "set_compact" | "set_always_on_top" | "grow_for_approval" | "attention";

export const inTauri = (): boolean => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

let queue: Promise<unknown> = Promise.resolve();

/** Sendet einen Fensterbefehl an den Rustteil, streng nacheinander: der nächste startet erst, wenn der vorige fertig ist
 *  (sonst könnte `grow_for_approval` vor `set_compact` ankommen und verworfen werden). Ohne Tauri: nichts. Fehler werden
 *  geschluckt (das Fenster bleibt dann, wie es ist). */
export function windowCommand(cmd: WindowCommand, args: { on?: boolean } = {}): Promise<boolean> {
  if (!inTauri()) return Promise.resolve(false);
  const run = queue.then(() => invoke(cmd, args)).then(() => true, () => false);
  queue = run;
  return run;
}
