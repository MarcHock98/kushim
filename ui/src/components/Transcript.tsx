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
export function Transcript({ entries }: { entries: Entry[] }) {
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
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}
