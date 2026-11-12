import { IconCross } from "./Icons";
import type { Entry } from "./Transcript";

/** Karte auf der Bühne (Modus „Begleiten“): die letzte Antwort von kushim/Claude, groß lesbar neben dem Kern.
 *  Nur Text, nie HTML. Schließen per Knopf oder Esc; die nächste Frage räumt sie selbst ab. Später (P2) kommen hier die
 *  Ansichten aus `zeige` hin (Rechenweg, Markt, Recherche). */
export function StageCard({ entry, onClose }: { entry: Entry; onClose: () => void }) {
  return (
    <article className="stage-card" aria-labelledby="stage-card-h">
      <div className="panel-head">
        <h2 id="stage-card-h">Antwort</h2>
        <button type="button" className="ghost-icon" aria-label="Schließen (Esc)" title="Schließen (Esc)" onClick={onClose}><IconCross /></button>
      </div>
      {entry.heard && <p className="stage-q"><span className="label">Du</span>{entry.heard}</p>}
      <p className="stage-a"><span className="label">kushim</span>{entry.reply}</p>
    </article>
  );
}
