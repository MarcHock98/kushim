import type { Block } from "../../lib/stage";

// Vergleich, Zeitstrahl und Gegenüberstellung (Plan docs/ui-p6-plan.md, P6a). Reine Anzeige: nichts hier ist anklickbar,
// nichts wird gesendet. Jeder Inhalt ist ein Textknoten (kein HTML, keine Links, keine Bilder). Vor- und Nachteile stehen
// mit den Wörtern „dafür“ und „dagegen“ da, nie nur als Farbe oder Zeichen.

type Of<T extends Block["typ"]> = Extract<Block, { typ: T }>;

const num = (v: string | number) => (typeof v === "number" ? v.toLocaleString("de-DE", { maximumFractionDigits: 2 }) : v);

function Points({ word, items, cls }: { word: string; items: string[]; cls: string }) {
  if (items.length === 0) return null;
  return (
    <div className={`c-points ${cls}`}>
      <p className="label c-word">{word}</p>
      <ul>{items.map((t, i) => <li key={i}>{t}</li>)}</ul>
    </div>
  );
}

export function Compare({ b }: { b: Of<"vergleich"> }) {
  const pros = b.vorteile ?? [], cons = b.nachteile ?? [];
  const lists = b.optionen.map((o, i) => ({ o, pro: pros[i] ?? [], con: cons[i] ?? [] })).filter((x) => x.pro.length + x.con.length > 0);
  return (
    <section className="v-compare" aria-label="Vergleich">
      {b.kriterien.length > 0 && (
        <div className="v-table-wrap">
          <table className="v-table c-table">
            <thead>
              <tr><th scope="col">Kriterium</th>{b.optionen.map((o, i) => <th key={i} scope="col">{o}</th>)}</tr>
            </thead>
            <tbody>
              {b.kriterien.map((k, i) => (
                <tr key={i}>
                  <th scope="row">{k.name}</th>
                  {b.optionen.map((_, j) => {
                    const v = k.werte[j];
                    return v === undefined || v === ""
                      ? <td key={j} className="c-unknown">unbekannt</td>
                      : <td key={j} className={typeof v === "number" ? "num" : ""}>{num(v)}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {lists.length > 0 && (
        <div className="c-options">
          {lists.map(({ o, pro, con }, i) => (
            <section key={i} className="c-option" aria-label={o}>
              <h3>{o}</h3>
              <Points word="dafür" items={pro} cls="c-pro" />
              <Points word="dagegen" items={con} cls="c-con" />
            </section>
          ))}
        </div>
      )}
      {b.fazit && <div className="c-verdict"><span className="label">Fazit</span><p>{b.fazit}</p></div>}
    </section>
  );
}

export function Timeline({ b }: { b: Of<"zeitstrahl"> }) {
  return (
    <section className="v-timeline" aria-label="Zeitstrahl">
      {b.einheit && <p className="label">Zeitangaben in {b.einheit}</p>}
      <ol className="t-list">
        {b.ereignisse.map((e, i) => (
          <li key={i} className="t-item">
            <span className="t-time">{e.zeit}</span>
            <div className="t-body">
              <p className="t-title">{e.titel}</p>
              {e.text && <p className="t-text">{e.text}</p>}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** Original und Übersetzung nebeneinander (am Handy untereinander). `dir="auto"` an jedem Text: Die Schriftrichtung
 *  bestimmt der Browser aus dem Text selbst, nicht Claude. */
export function Pairs({ b }: { b: Of<"gegenueber"> }) {
  if (!Array.isArray(b.sprachen) || b.sprachen.length !== 2 || !b.sprachen.every((s) => typeof s === "string")) throw new Error("sprachen");
  const [von, nach] = b.sprachen;
  return (
    <section className="v-pairs" aria-label={`Übersetzung ${von} und ${nach}`}>
      <div className="g-head" aria-hidden="true">
        <span className="label" dir="auto">{von}</span>
        <span className="label" dir="auto">{nach}</span>
      </div>
      <ol className="g-list">
        {b.paare.map((p, i) => (
          <li key={i} className="g-pair">
            <p className="g-cell g-orig"><span className="g-lang label" dir="auto">{von}</span><span className="g-text" dir="auto">{p.original}</span></p>
            <p className="g-cell g-trans"><span className="g-lang label" dir="auto">{nach}</span><span className="g-text" dir="auto">{p.uebersetzung}</span></p>
          </li>
        ))}
      </ol>
    </section>
  );
}
