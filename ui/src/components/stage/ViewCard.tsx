import { Component, type ReactNode } from "react";
import { ART_LABEL, type Block, type View } from "../../lib/stage";
import { IconCross } from "../Icons";
import { SystemPanel, type SysData } from "../SystemPanel";
import { Chart } from "./Chart";
import { Compare, Pairs, Timeline } from "./Compare";
import { Change, Document } from "./Doc";
import { Flashcards, Guide, Quiz } from "./Learn";
import { Model3D } from "./Model3D";
import { Net } from "./Net";
import { Plan2D } from "./Plan2D";
import { Simulation } from "./Simulation";
import { Countdown, Mail, MailDraft, Progress, Schedule, Tasks } from "./Live";
import { AtomShells } from "./AtomShells";
import { Molecule3D } from "./Molecule3D";
import { Orbital3D } from "./Orbital3D";
import { Tex } from "./Tex";

// Eine Ansicht von Claude auf der Bühne. Layout je Art (antwort, rechnung, markt, recherche, auftrag, mail, lernen), Bausteine nur als Text.
// Quellen-Adressen sind Text, kein Link: nichts öffnet sich, nichts wird nachgeladen. Knöpfe in Lernkarten, Quiz und Anleitung
// ändern nur die Anzeige im Fenster, sie senden nichts. Ebenso Zoom und Verschieben im Diagramm (netz) und Pause, Weiter und
// Neu starten der Simulation. Last: höchstens 2 Simulationen und höchstens 2 WebGL-Bausteine (szene3d, teilchen als Molekül oder
// Orbital) je Ansicht; das Backend lehnt mehr ab, hier gilt dieselbe Grenze ein zweites Mal (darüber nur ein kurzer Hinweis).

/** Fängt einen Fehler in einem einzelnen Baustein ab: Er zeigt dann einen Hinweis, der Rest der Oberfläche läuft weiter.
 *  (Das Backend prüft jede Ansicht, aber ein Darstellungsfehler darf nie das ganze Fenster leeren.) */
class BlockGuard extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed ? <p className="v-note" role="alert">Dieser Teil der Ansicht konnte nicht angezeigt werden.</p> : this.props.children;
  }
}

const num = (v: string | number) => (typeof v === "number" ? v.toLocaleString("de-DE", { maximumFractionDigits: 2 }) : v);
const ARROW: Record<string, string> = { auf: "▲ steigt", ab: "▼ fällt", gleich: "► unverändert" };

function Sup({ nrs }: { nrs: number[] }) {
  return nrs.length ? <sup className="cite" aria-label={`Quellen ${nrs.join(", ")}`}>[{nrs.join("] [")}]</sup> : null;
}

function BlockView({ b, sys, sysNo }: { b: Block; sys: SysData | null; sysNo: boolean }): ReactNode {
  switch (b.typ) {
    case "text": return <div className="v-text">{b.absaetze.map((a, i) => <p key={i}>{a}</p>)}</div>;
    case "liste": {
      const items = b.punkte.map((p, i) => <li key={i}>{p}</li>);
      return b.nummeriert ? <ol className="v-list">{items}</ol> : <ul className="v-list">{items}</ul>;
    }
    case "formel": return <div className="v-formula"><Tex tex={b.tex} block /></div>;
    case "schritte": return (
      <ol className="v-steps">
        {b.schritte.map((s, i) => (
          <li key={i}><span className="v-step-n" aria-hidden="true">{i + 1}</span>
            <div><p>{s.text}</p>{s.tex && <Tex tex={s.tex} block />}</div></li>
        ))}
      </ol>
    );
    case "ergebnis": return (
      <div className="v-result"><span className="label">Ergebnis</span>{b.text && <p>{b.text}</p>}{b.tex && <Tex tex={b.tex} block />}</div>
    );
    case "kennzahlen": return (
      <div className="v-figures">
        {b.werte.map((k, i) => (
          <div key={i} className={`v-figure dir-${k.richtung || "none"}`}>
            <span className="label">{k.name}</span>
            <span className="v-figure-val">{num(k.wert)}{k.einheit && <small> {k.einheit}</small>}</span>
            {(k.aenderung || k.richtung) && <span className="v-figure-chg">{k.richtung && ARROW[k.richtung]} {k.aenderung}</span>}
          </div>
        ))}
      </div>
    );
    case "tabelle": return (
      <div className="v-table-wrap">
        <table className="v-table">
          <thead><tr>{b.spalten.map((s, i) => <th key={i} scope="col">{s}</th>)}</tr></thead>
          <tbody>{b.zeilen.map((z, i) => <tr key={i}>{z.map((c, j) => <td key={j} className={typeof c === "number" ? "num" : ""}>{num(c)}</td>)}</tr>)}</tbody>
        </table>
      </div>
    );
    case "diagramm": return <Chart d={b} />;
    case "aussagen": return <ul className="v-claims">{b.aussagen.map((a, i) => <li key={i}>{a.text}<Sup nrs={a.quellen} /></li>)}</ul>;
    case "widerspruch": return (
      <div className="v-conflict" role="note"><span className="label">Quellen widersprechen sich</span>
        <ul className="v-claims">{b.aussagen.map((a, i) => <li key={i}>{a.text}<Sup nrs={a.quellen} /></li>)}</ul></div>
    );
    case "quellen": return (
      <ol className="v-sources" aria-label="Quellen">
        {b.quellen.map((q) => <li key={q.nr}><span className="v-src-nr">[{q.nr}]</span> {q.titel}{q.adresse && <code>{q.adresse}</code>}</li>)}
      </ol>
    );
    case "hinweis": return <p className="v-note">{b.text}</p>;
    case "systemzustand": return <SystemPanel data={sys} unavailable={sysNo} />;
    case "fortschritt": return <Progress b={b} />;
    case "aufgaben": return <Tasks b={b} />;
    case "zeitplan": return <Schedule b={b} />;
    case "mail": return <Mail b={b} />;
    case "mail-entwurf": return <MailDraft b={b} />;
    case "countdown": return <Countdown b={b} />;
    case "dokument": return <Document b={b} />;
    case "aenderung": return <Change b={b} />;
    case "szene3d": return <Model3D b={b} />;
    case "plan2d": return <Plan2D b={b} />;
    case "vergleich": return <Compare b={b} />;
    case "zeitstrahl": return <Timeline b={b} />;
    case "gegenueber": return <Pairs b={b} />;
    case "lernkarten": return <Flashcards b={b} />;
    case "quiz": return <Quiz b={b} />;
    case "anleitung": return <Guide b={b} />;
    case "netz": return <Net b={b} />;
    case "simulation": return <Simulation b={b} />;
    case "teilchen": {
      const form = (b as { form?: unknown }).form;                     // unbekannte Form: das Schalenmodell sagt „kann nicht gezeigt werden“
      return form === "molekuel" ? <Molecule3D b={b} /> : form === "orbital" ? <Orbital3D b={b} /> : <AtomShells b={b} />;
    }
  }
}

export const SIM_MAX = 2;
export const WEBGL_MAX = 2;
const usesWebGL = (b: Block) => b.typ === "szene3d"
  || (b.typ === "teilchen" && ((b as { form?: unknown }).form === "molekuel" || (b as { form?: unknown }).form === "orbital"));

/** Je Baustein: "" (zeigen), "sim" oder "webgl" (über der Grenze, nur Hinweis). Gezählt wird in der Reihenfolge der Ansicht. */
export function overLimit(blocks: Block[]): ("" | "sim" | "webgl")[] {
  let sims = 0, gl = 0;
  return blocks.map((b) => {
    if (b.typ === "simulation") return ++sims > SIM_MAX ? "sim" : "";
    if (usesWebGL(b)) return ++gl > WEBGL_MAX ? "webgl" : "";
    return "";
  });
}
const LIMIT_NOTE = {
  sim: `Weitere Simulation nicht gezeigt: höchstens ${SIM_MAX} je Ansicht.`,
  webgl: `Weitere 3D-Ansicht nicht gezeigt: höchstens ${WEBGL_MAX} je Ansicht.`,
};

export function ViewCard({ view, sys, sysNo, onClose }: { view: View; sys: SysData | null; sysNo: boolean; onClose: () => void }) {
  const sources = view.bausteine.filter((b) => b.typ === "quellen");
  const main = view.art === "recherche" ? view.bausteine.filter((b) => b.typ !== "quellen") : view.bausteine;
  const over = overLimit(main);
  return (
    <article className={`view-card view-${view.art}`} aria-labelledby={`v-${view.id}`}>
      <div className="panel-head">
        <h2 id={`v-${view.id}`}>{view.titel || ART_LABEL[view.art]}</h2>
        <span className="label">{ART_LABEL[view.art]}{view.stand && ` · Stand: ${view.stand}`}</span>
        <button type="button" className="ghost-icon" aria-label="Schließen (Esc)" title="Schließen (Esc)" onClick={onClose}><IconCross /></button>
      </div>
      {view.art === "markt" && !view.stand && <p className="v-note">Stand: unbekannt</p>}
      <div className="view-body">
        <div className="view-main">{main.map((b, i) => {
          const o = over[i];
          return <BlockGuard key={`${i}-${view.seq}`}>{o ? <p className="v-note" role="note">{LIMIT_NOTE[o]}</p> : <BlockView b={b} sys={sys} sysNo={sysNo} />}</BlockGuard>;
        })}</div>
        {view.art === "recherche" && sources.length > 0 && (
          <aside className="view-aside" aria-label="Quellen">{sources.map((b, i) => <BlockGuard key={`${i}-${view.seq}`}><BlockView b={b} sys={sys} sysNo={sysNo} /></BlockGuard>)}</aside>
        )}
      </div>
      {view.art === "markt" && <p className="v-note">Nur zur Information, keine Anlageberatung.</p>}
    </article>
  );
}

export function ViewTabs({ views, active, onPick }: { views: View[]; active: string; onPick: (id: string) => void }) {
  if (views.length < 2) return null;
  return (
    <div className="view-tabs" role="tablist" aria-label="Gezeigte Ansichten">
      {views.slice(-5).map((v) => (
        <button key={v.id} type="button" role="tab" aria-selected={v.id === active} className={v.id === active ? "tab active" : "tab"}
          onClick={() => onPick(v.id)}>{v.titel || ART_LABEL[v.art]}</button>
      ))}
    </div>
  );
}
