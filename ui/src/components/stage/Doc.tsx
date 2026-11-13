import type { Block } from "../../lib/stage";

// Dateitext und Änderungen, die Claude Code schickt (Plan docs/ui-p3b-plan.md, Weg A). kushim liest selbst keine Dateien:
// Der Name ist nur eine Beschriftung. Jede Zeile ist Text (kein HTML, keine Links, keine Hervorhebung über ein Paket).
// Plus und Minus stehen als Zeichen UND Farbe da, nie nur als Farbe. Nichts hier ist anklickbar.

type Of<T extends Block["typ"]> = Extract<Block, { typ: T }>;

export function Document({ b }: { b: Of<"dokument"> }) {
  const width = String(b.zeilen.length).length;
  return (
    <section className="v-doc" aria-label={`Datei ${b.name}`}>
      <p className="d-name"><span className="label">Datei</span> <code>{b.name}</code>{b.ausschnitt && <small> · {b.ausschnitt}</small>}</p>
      <div className="d-layout">
        {b.gliederung.length > 0 && (
          <nav className="d-outline" aria-label="Gliederung">
            <span className="label">Gliederung</span>
            <ol>{b.gliederung.map((g, i) => <li key={i}>{g}</li>)}</ol>
          </nav>
        )}
        <pre className="d-code" tabIndex={0} aria-label={`Inhalt von ${b.name}`}>
          {b.zeilen.map((z, i) => (
            <span key={i} className="d-line"><span className="d-no" aria-hidden="true">{String(i + 1).padStart(width, " ")}</span>{z}{"\n"}</span>
          ))}
        </pre>
      </div>
    </section>
  );
}

const MARK = { gleich: " ", neu: "+", weg: "-" } as const;
const WORD = { gleich: "unverändert", neu: "neu", weg: "entfernt" } as const;

export function Change({ b }: { b: Of<"aenderung"> }) {
  const all = b.bloecke.flatMap((k) => k.zeilen);
  const added = all.filter((z) => z.art === "neu").length, removed = all.filter((z) => z.art === "weg").length;
  return (
    <section className="v-doc v-change" aria-label={`Änderung an ${b.name}`}>
      <p className="d-name"><span className="label">Änderung</span> <code>{b.name}</code>
        <small> · {added} neu, {removed} entfernt</small></p>
      {b.zusammenfassung && <p className="d-sum">{b.zusammenfassung}</p>}
      {b.bloecke.map((k, i) => (
        <div key={i} className="d-hunk">
          {k.kopf && <p className="d-head">{k.kopf}</p>}
          <pre className="d-code" tabIndex={0}>
            {k.zeilen.map((z, j) => (
              <span key={j} className={`d-line d-${z.art}`} title={WORD[z.art]}>
                <span className="d-mark" aria-label={WORD[z.art]}>{MARK[z.art]}</span>{z.text}{"\n"}
              </span>
            ))}
          </pre>
        </div>
      ))}
      <p className="v-note">Anzeige von Claude. Ob die Änderung geschrieben wird, entscheidest du in Claude Code.</p>
    </section>
  );
}
