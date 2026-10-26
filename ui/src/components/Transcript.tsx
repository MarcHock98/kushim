import { IconThumbDown, IconThumbUp } from "./Icons";

export interface Entry {
  id: number;
  heard: string;
  reply: string;
  outcome: string;
}

const NOTE: Record<string, string> = {
  rejected_speaker: "Stimme nicht erkannt. Keine Antwort.",
  killed: "Notaus ausgelöst.",
  interrupted: "(unterbrochen)",
  cancelled: "Abgebrochen.",
};

/** Die letzten Äußerungen: „Du“ rechts (Cyan-Rand), kushim links (Bernstein-Rand). Nur Text, nie HTML. */
export function Transcript({ entries, rated = {}, onRate }: {
  entries: Entry[]; rated?: Record<number, 1 | -1>; onRate?: (id: number, rating: 1 | -1) => void }) {
  if (entries.length === 0) {
    return <p className="hint">Noch nichts gesagt. Sag „hey kushim“.</p>;
  }
  return (
    <ol className="transcript" aria-label="Verlauf">
      {entries.slice(-4).map((e) => (
        <li key={e.id} className="turn">
          {e.heard && <p className="bubble you"><span className="who">Du</span>{e.heard}</p>}
          {(e.reply || NOTE[e.outcome]) && (
            <p className={`bubble bot${e.outcome === "rejected_speaker" ? " alarm" : ""}`}>
              <span className="who">kushim</span>{e.reply || NOTE[e.outcome]}
              {e.reply && onRate && (
                <span className="thumbs">
                  <button type="button" aria-pressed={rated[e.id] === 1} disabled={rated[e.id] !== undefined}
                    title="Hilfreich" aria-label="Hilfreich" onClick={() => onRate(e.id, 1)}><IconThumbUp /></button>
                  <button type="button" aria-pressed={rated[e.id] === -1} disabled={rated[e.id] !== undefined}
                    title="Nicht hilfreich" aria-label="Nicht hilfreich" onClick={() => onRate(e.id, -1)}><IconThumbDown /></button>
                </span>
              )}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}
