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
            <p className="fact-text">{f.text}</p>
            <p className="fact-meta">{KIND[f.kind] ?? f.kind} · {f.source} · {new Date(f.created * 1000).toLocaleDateString("de-DE")}</p>
            <button type="button" onClick={() => remove(f)} aria-label={`Löschen: ${f.text.slice(0, 40)}`}>Löschen</button>
          </li>
        ))}
      </ul>
      <div className="undo" role="status" aria-live="polite">
        {undo.map((f) => (
          <p key={f.id}>Gelöscht in 10 Sekunden. <button type="button" onClick={() => restore(f)}>Rückgängig</button></p>
        ))}
      </div>
    </section>
  );
}
