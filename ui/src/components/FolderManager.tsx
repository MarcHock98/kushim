import { useCallback, useEffect, useState } from "react";
import type { ApiClient } from "../lib/api";
import { ApprovalBar, type Pending } from "./ApprovalBar";

interface Entry { name: string; path: string }

/** Ordner für Claude: Liste mit Entziehen (sofort) und Freigeben (Vorschau mit exaktem Pfad, dann Erlauben/Ablehnen).
 *  Die UI prüft keine Pfadregeln selbst: das Backend lehnt unzulässige Ordner mit Klartext ab. */
export function FolderManager({ client, connected, onChange }: {
  client: React.RefObject<ApiClient | null>; connected: boolean; onChange: (message?: string) => void }) {
  const [list, setList] = useState<Entry[]>([]);
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [proposal, setProposal] = useState<{ id: string; pending: Pending } | null>(null);
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    const r = await client.current?.call("claude.folder_list");
    if (r?.ok && Array.isArray(r.folders)) setList(r.folders as Entry[]);
  }, [client]);
  useEffect(() => { if (connected) void load(); }, [connected, load]);

  const propose = async () => {
    setNote("");
    const r = await client.current?.call("claude.folder_propose", { name: name.trim(), path: path.trim() });
    if (!r?.ok) return setNote("Das hat nicht geklappt.");
    if (r.allowed !== true) return setNote(typeof r.reason === "string" ? r.reason : "Nicht zulässig.");
    setProposal({ id: String(r.proposal), pending: {
      kind: "folder", preview: String(r.preview), digest: String(r.proposal),
      expires_in: typeof r.expires_in === "number" ? r.expires_in : 0, sends_data_out: true } });
  };

  const decide = async (approve: boolean) => {
    const p = proposal;
    if (!p) return;
    setProposal(null);                                                  // nie doppelt absenden
    if (approve) {
      const r = await client.current?.call("claude.folder_confirm", { proposal: p.id, confirm: true });
      if (r?.ok) { setNote(""); setName(""); setPath(""); await load(); onChange("Ordner freigegeben."); }
      else setNote("Nicht freigegeben (abgelaufen oder inzwischen nicht mehr zulässig).");
    } else {
      await client.current?.call("claude.folder_deny", { proposal: p.id });
      setNote("Abgelehnt. Nichts wurde freigegeben.");
    }
  };

  const remove = async (n: string) => {
    const r = await client.current?.call("claude.folder_remove", { name: n });
    if (r?.ok) { setNote(""); await load(); onChange(`Freigabe für «${n}» entzogen.`); }
    else setNote(r && !r.ok && r.error === "in_use" ? "Dort arbeitet Claude gerade. Erst den Lauf stoppen." : "Nicht entzogen.");
  };

  return (
    <details className="folders" open={list.length === 0}>
      <summary>Ordner für Claude ({list.length})</summary>
      {list.length === 0 && <p className="hint">Kein Ordner freigegeben. Gib einen Git-Ordner frei, in dem Claude arbeiten darf.</p>}
      <ul className="folder-list">
        {list.map((f) => (
          <li key={f.name}>
            <span><strong>{f.name}</strong> <code>{f.path}</code></span>
            <button type="button" onClick={() => void remove(f.name)} aria-label={`Freigabe entziehen: ${f.name}`}>Entziehen</button>
          </li>
        ))}
      </ul>
      {proposal ? <ApprovalBar pending={proposal.pending} onDecide={(a) => void decide(a)} /> : (
        <form className="cl-form" onSubmit={(e) => { e.preventDefault(); if (name.trim() && path.trim()) void propose(); }}>
          <label>Name (klein, ohne Leerzeichen)
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={31} />
          </label>
          <label>Pfad zum Git-Ordner
            <input value={path} onChange={(e) => setPath(e.target.value)} maxLength={400} />
          </label>
          <button type="submit" disabled={!name.trim() || !path.trim()}>Freigabe-Vorschau ansehen</button>
        </form>
      )}
      {note && <p className="hint" role="status">{note}</p>}
    </details>
  );
}
