import { useCallback, useEffect, useRef, useState } from "react";
import type { ApiClient } from "../lib/api";

interface Fact { id: number; text: string; kind: string; source: string; created: number }

export const UNDO_MS = 10_000;

const KIND: Record<string, string> = { preference: "Vorliebe", decision: "Entscheidung", person: "Person", routine: "Routine", other: "Sonstiges" };

/** Gedächtnis: durchsuchen und löschen. Löschen ist endgültig: erst nach 10 s ohne Rückgängig geht `memory.delete` mit confirm
 *  ans Backend; bis dahin ist nichts gelöscht. Der Bereich bleibt eingehängt (nur versteckt), damit ein Wechsel des Reiters
 *  die Frist nicht abbricht. Texte werden nie als HTML gezeigt. */
export function MemoryPanel({ client, connected, active, undoMs = UNDO_MS }: {
  client: React.RefObject<ApiClient | null>; connected: boolean; active: boolean; undoMs?: number }) {
  const [query, setQuery] = useState("");
  const [facts, setFacts] = useState<Fact[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [undo, setUndo] = useState<Fact[]>([]);                       // Einträge in der Rückgängig-Frist
  const [editing, setEditing] = useState<{ id: number; text: string; kind: string } | null>(null);
  const [note, setNote] = useState("");
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    const r = await client.current?.call("memory.search", { query, limit: 100 });
    if (r?.ok && Array.isArray(r.facts)) { setFacts(r.facts as Fact[]); setFailed(false); }
    else if (r) setFailed(true);
  }, [client, query]);

  useEffect(() => {
    if (!connected || !active) return;
    const id = setTimeout(() => void load(), 250);
    return () => clearTimeout(id);
  }, [connected, active, load]);

  useEffect(() => { if (active) input.current?.focus(); }, [active]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (active && e.key === "/" && document.activeElement !== input.current) { e.preventDefault(); input.current?.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active]);
  useEffect(() => () => { timers.current.forEach(clearTimeout); }, []);

  const remove = (f: Fact) => {
    setUndo((u) => [...u, f]);
    const t = setTimeout(async () => {
      timers.current.delete(f.id);
      const r = await client.current?.call("memory.delete", { id: f.id, confirm: true });
      setUndo((u) => u.filter((x) => x.id !== f.id));
      if (!r?.ok) void load();                                          // nicht gelöscht: wieder anzeigen
    }, undoMs);
    timers.current.set(f.id, t);
  };
  const restore = (f: Fact) => {
    const t = timers.current.get(f.id);
    if (t) clearTimeout(t);
    timers.current.delete(f.id);
    setUndo((u) => u.filter((x) => x.id !== f.id));
  };

  const save = async () => {
    if (!editing || !editing.text.trim()) return;
    const e = editing;
    setEditing(null);
    const r = await client.current?.call("memory.update", { id: e.id, text: e.text, kind: e.kind, confirm: true });
    setNote(r?.ok ? "Gespeichert." : "Nicht gespeichert (Eintrag nicht gefunden oder Vault nicht erreichbar).");
    void load();
  };

  const hiding = new Set(undo.map((u) => u.id));
  const shown = (facts ?? []).filter((f) => !hiding.has(f.id));

  return (
    <section className="memory" aria-label="Gedächtnis" hidden={!active}>
      <input ref={input} type="search" aria-label="Gedächtnis durchsuchen" placeholder="Suchen … (Taste /)" value={query}
        onChange={(e) => setQuery(e.target.value)} maxLength={200} />
      {failed && <p className="hint" role="alert">Das Gedächtnis ist gerade nicht erreichbar (Vault offen? kushim talk --ui).</p>}
      {facts !== null && shown.length === 0 && undo.length === 0 && !failed && (
        <p className="hint">{query ? "Nichts gefunden." : "Noch keine Erinnerungen."}</p>
      )}
      <ul className="facts">
        {shown.map((f) => (
          <li key={f.id} className="fact">
            {editing?.id === f.id ? (
              <form className="fact-edit" onSubmit={(e) => { e.preventDefault(); void save(); }}>
                <textarea aria-label="Erinnerung bearbeiten" value={editing.text} rows={3} maxLength={2000} autoFocus
                  onChange={(e) => setEditing({ ...editing, text: e.target.value })} />
                <select aria-label="Art" value={editing.kind} onChange={(e) => setEditing({ ...editing, kind: e.target.value })}>
                  {Object.entries(KIND).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                </select>
                <div className="fact-actions">
                  <button type="button" onClick={() => setEditing(null)}>Abbrechen</button>
                  <button type="submit" className="primary" disabled={!editing.text.trim()}>Speichern</button>
                </div>
              </form>
            ) : (
              <>
                <p className="fact-text">{f.text}</p>
                <p className="fact-meta">{KIND[f.kind] ?? f.kind} · {f.source} · {new Date(f.created * 1000).toLocaleDateString("de-DE")}</p>
                <div className="fact-actions">
                  <button type="button" onClick={() => setEditing({ id: f.id, text: f.text, kind: f.kind })} aria-label={`Bearbeiten: ${f.text.slice(0, 40)}`}>Bearbeiten</button>
                  <button type="button" onClick={() => remove(f)} aria-label={`Löschen: ${f.text.slice(0, 40)}`}>Löschen</button>
                </div>
              </>
            )}
          </li>
        ))}
      </ul>
      {note && <p className="hint" role="status">{note}</p>}
      <div className="undo" role="status" aria-live="polite">
        {undo.map((f) => (
          <p key={f.id}>Gelöscht in 10 Sekunden. <button type="button" onClick={() => restore(f)}>Rückgängig</button></p>
        ))}
      </div>
    </section>
  );
}
