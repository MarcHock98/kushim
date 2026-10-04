import { useEffect, useState } from "react";
import type { Overview } from "./SecurityPanel";

export interface DashData {
  timers: { id: string; label: string; due_in: number }[];
  tasks: string[];
  pending_approvals: number;
  results: { ts: number; query: string; kind: string; answer: string; note: string; sources: { title: string; url: string }[] }[];
}

const mmss = (s: number) => {
  const v = Math.max(0, Math.floor(s));
  return `${Math.floor(v / 60)}:${String(v % 60).padStart(2, "0")}`;
};

/** Übersicht: Heute (Timer, Aufgaben), Ergebnisse (Recherchen mit Quellen), Aktivität (letzte Gate-Entscheidungen).
 *  Nur echte Daten, sonst Leerzustand mit Hinweis. Quellen sind Text: nichts wird automatisch geöffnet oder nachgeladen. */
export function Dashboard({ data, overview, unavailable = false }: { data: DashData | null; overview: Overview | null; unavailable?: boolean }) {
  const [tick, setTick] = useState(0);
  useEffect(() => { const id = setInterval(() => setTick((t) => t + 1), 1000); return () => clearInterval(id); }, []);
  useEffect(() => { setTick(0); }, [data]);                          // neue Daten: Zähler neu ansetzen

  if (!data && unavailable) return <p className="hint">Die Übersicht gibt es nur mit dem Sprachdienst (kushim talk --ui).</p>;
  if (!data) return <p className="hint">Übersicht wird geladen …</p>;
  const activity = (overview?.audit ?? []).slice(-8).reverse();

  return (
    <section className="dash" aria-label="Übersicht">
      <article className="card" aria-labelledby="d-today">
        <h2 id="d-today">Heute</h2>
        {data.timers.length === 0 && data.tasks.length === 0 && data.pending_approvals === 0 && (
          <p className="hint">Keine Timer und keine laufenden Aufgaben.</p>
        )}
        <ul>
          {data.timers.map((t) => (
            <li key={t.id}>
              <span>{t.label || "Timer"}</span>{" "}
              <strong>{t.due_in - tick <= 0 ? "abgelaufen" : mmss(t.due_in - tick)}</strong>
            </li>
          ))}
          {data.tasks.map((n, i) => <li key={`${n}-${i}`}>{n} <em>läuft</em></li>)}
          {data.pending_approvals > 0 && <li>{data.pending_approvals} Freigabe(n) warten <em>auf dich</em></li>}
        </ul>
      </article>

      <article className="card" aria-labelledby="d-res">
        <h2 id="d-res">Ergebnisse</h2>
        {data.results.length === 0 && <p className="hint">Keine Recherche gestartet. Sag zum Beispiel: „Recherchiere die Höhe des Eiffelturms.“</p>}
        {data.results.map((r) => (
          <div key={r.ts} className="result">
            <h3>{r.query || "Recherche"}</h3>
            {r.answer && <p>{r.answer}</p>}
            {r.note && <p className="hint">{r.note}</p>}
            {r.sources.length > 0 && (
              <ul className="sources" aria-label="Quellen">
                {r.sources.map((s) => <li key={s.url}>{s.title} <code>{s.url}</code></li>)}
              </ul>
            )}
            {!r.answer && r.sources.length === 0 && <p className="hint">Nichts gefunden.</p>}
          </div>
        ))}
      </article>

      <article className="card" aria-labelledby="d-act">
        <h2 id="d-act">Aktivität</h2>
        {activity.length === 0 && <p className="hint">Noch keine Aktionen protokolliert.</p>}
        <ol className="audit">
          {activity.map((a, i) => <li key={`${a.ts}-${i}`}><strong>{a.event}</strong> {a.detail}</li>)}
        </ol>
      </article>
    </section>
  );
}
