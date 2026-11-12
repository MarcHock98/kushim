import { useState } from "react";
import type { ApiClient } from "../lib/api";
import { FolderManager } from "./FolderManager";

/** Ordner, in denen Claude Code arbeiten darf. Die Arbeit selbst läuft im Fenster von Claude Code; was Claude dabei zeigt,
 *  erscheint auf der Bühne (Art `auftrag`). Jede Freigabe entscheidet das Backend. */
export function FolderPanel({ client, connected }: { client: React.RefObject<ApiClient | null>; connected: boolean }) {
  const [note, setNote] = useState("");
  if (!connected) return null;
  return (
    <section className="claude" aria-label="Claude">
      <h2>Claude</h2>
      <p className="hint">Claude Code arbeitet in seinem eigenen Fenster. Hier stehen die Ordner, die du dafür freigegeben hast.</p>
      {note && <p className="hint" role="status">{note}</p>}
      <FolderManager client={client} connected={connected} onChange={(m) => setNote(m ?? "")} />
    </section>
  );
}
