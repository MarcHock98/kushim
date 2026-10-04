import { useCallback, useEffect, useRef, useState } from "react";
import type { ApiClient } from "../lib/api";
import { ApprovalBar, type Pending } from "./ApprovalBar";

interface Session {
  id: string; folder: string; branch: string; turn: number; status: string;
  cost_usd: number; seconds: number; error: string; offers: string[];
}
interface Review {
  files: { status: string; path: string }[];
  protected: string[];
  shortstat: string;
  overview: { done: string; question: string; next_steps: string[] };
}

const STATUS: Record<string, string> = {
  running: "arbeitet", waiting: "wartet auf dich oder ist fertig", failed: "gescheitert", stopped: "gestoppt",
};

/** Claude als Entwickler: Status, Start mit exakter Vorschau, Stopp, Übersicht. Alles Anzeige: jede Aktion entscheidet das Backend. */
export function ClaudePanel({ client, connected }: { client: React.RefObject<ApiClient | null>; connected: boolean }) {
  const [folders, setFolders] = useState<string[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [folder, setFolder] = useState("");
  const [task, setTask] = useState("");
  const [reply, setReply] = useState("");
  const [allow, setAllow] = useState<string[]>([]);
  const [proposal, setProposal] = useState<{ id: string; pending: Pending } | null>(null);
  const [note, setNote] = useState("");
  const busy = useRef(false);

  const refresh = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    const st = await client.current?.call("claude.status");
    if (st?.ok) {
      const s = (st.session as Session | null) ?? null;
      setSession(s);
      if (s && s.status !== "running") {
        const rv = await client.current?.call("claude.review");
        if (rv?.ok) setReview((rv.review as Review | null) ?? null);
      } else setReview(null);
    }
    busy.current = false;
  }, [client]);

  useEffect(() => {
    if (!connected) return;
    void (async () => {
      const f = await client.current?.call("claude.folders");
      if (f?.ok && Array.isArray(f.folders)) {
        const names = (f.folders as unknown[]).filter((x): x is string => typeof x === "string");
        setFolders(names);
        setFolder((old) => old || names[0] || "");
      }
    })();
    void refresh();
    const id = setInterval(() => { if (!document.hidden) void refresh(); }, 2000);
    return () => clearInterval(id);
  }, [connected, client, refresh]);

  if (!connected || folders.length === 0) {
    return connected ? <p className="hint">Claude: kein Ordner freigegeben (kushim claude add).</p> : null;
  }

  const propose = async () => {
    setNote("");
    const r = await client.current?.call("claude.start", { task, folder });
    if (!r?.ok) return setNote("Das hat nicht geklappt.");
    if (r.allowed !== true) return setNote(typeof r.reason === "string" && r.reason ? r.reason : "Das darf ich gerade nicht.");
    setProposal({ id: String(r.proposal), pending: {
      kind: "start", preview: String(r.preview), digest: String(r.proposal),
      expires_in: typeof r.expires_in === "number" ? r.expires_in : 0, sends_data_out: true } });
  };

  const proposeAnswer = async () => {
    setNote("");
    const r = await client.current?.call("claude.answer", { text: reply, allow });
    if (!r?.ok) return setNote("Das hat nicht geklappt.");
    if (r.allowed !== true) return setNote(typeof r.reason === "string" && r.reason ? r.reason : "Das darf ich gerade nicht.");
    setProposal({ id: String(r.proposal), pending: {
      kind: "answer", preview: String(r.preview), digest: String(r.proposal),
      expires_in: typeof r.expires_in === "number" ? r.expires_in : 0, sends_data_out: true } });
  };

  const decide = async (approve: boolean) => {
    const p = proposal;
    if (!p) return;
    setProposal(null);                                   // nie doppelt absenden
    if (approve) {
      const r = await client.current?.call("claude.approve", { proposal: p.id, confirm: true });
      setNote(r?.ok ? "Claude arbeitet." : "Nicht gestartet (abgelaufen, abgelehnt oder Notaus).");
      setTask(""); setReply(""); setAllow([]);
    } else {
      await client.current?.call("claude.deny", { proposal: p.id });
      setNote("Abgelehnt. Es wurde nichts gesendet.");
    }
    void refresh();
  };

  const running = session?.status === "running";
  const waiting = session?.status === "waiting";
  const offers = waiting ? (session?.offers ?? []) : [];

  return (
    <section className="claude" aria-label="Claude">
      <h2>Claude</h2>
      {session && (
        <p className="cl-status" role="status">
          Ordner {session.folder}, Zug {session.turn}: {STATUS[session.status] ?? session.status}
          {session.error ? ` (${session.error})` : ""}
        </p>
      )}
      {running && <button type="button" onClick={() => void client.current?.call("claude.stop").then(refresh)}>Stoppen</button>}
      {review && !running && (
        <div className="cl-review">
          {review.overview.done && <p>{review.overview.done}</p>}
          {review.overview.question && <p><strong>Rückfrage:</strong> {review.overview.question}</p>}
          <p className="hint">{review.shortstat || `${review.files.length} Dateien`}</p>
          {review.protected.length > 0 && (
            <p className="cl-warn" role="alert">Geschützte Dateien geändert: {review.protected.join(", ")}</p>
          )}
        </div>
      )}
      {proposal ? (
        <ApprovalBar pending={proposal.pending} onDecide={(a) => void decide(a)} />
      ) : (
        waiting ? (
          <form className="cl-form" onSubmit={(e) => { e.preventDefault(); if (reply.trim()) void proposeAnswer(); }}>
            <label>Antwort an Claude
              <textarea value={reply} onChange={(e) => setReply(e.target.value)} rows={3} maxLength={2000} />
            </label>
            {offers.length > 0 && (
              <fieldset className="cl-offers">
                <legend>Claude darf zusätzlich ausführen (nur diese, nur für den nächsten Zug):</legend>
                {offers.map((o) => (
                  <label key={o} className="cl-offer">
                    <input type="checkbox" checked={allow.includes(o)}
                      onChange={(e) => setAllow((old) => (e.target.checked ? [...old, o] : old.filter((x) => x !== o)))} />
                    <code>{o}</code>
                  </label>
                ))}
              </fieldset>
            )}
            <button type="submit" disabled={!reply.trim()}>Vorschau ansehen</button>
          </form>
        ) : !running && (
          <form className="cl-form" onSubmit={(e) => { e.preventDefault(); if (task.trim()) void propose(); }}>
            <label>Ordner
              <select value={folder} onChange={(e) => setFolder(e.target.value)}>
                {folders.map((f) => <option key={f}>{f}</option>)}
              </select>
            </label>
            <label>Auftrag
              <textarea value={task} onChange={(e) => setTask(e.target.value)} rows={3} maxLength={2000} />
            </label>
            <button type="submit" disabled={!task.trim()}>Vorschau ansehen</button>
          </form>
        )
      )}
      {note && <p className="hint" role="status">{note}</p>}
    </section>
  );
}
