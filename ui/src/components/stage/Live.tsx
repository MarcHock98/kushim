import { useEffect, useState, type ReactNode } from "react";
import type { Block } from "../../lib/stage";
import { IconCheck, IconCross } from "../Icons";

// Bausteine für Live-Arbeit (Plan docs/ui-p3-plan.md): Fortschritt, Aufgaben, Zeitplan, Mail, Mail-Entwurf, Countdown.
// Alles ist Anzeige: nichts hier ist anklickbar, nichts wird gesendet, geöffnet oder nachgeladen. Zustände stehen immer
// als Wort da, nie nur als Farbe oder Symbol.

type Of<T extends Block["typ"]> = Extract<Block, { typ: T }>;

const STEP: Record<string, { word: string; mark: ReactNode }> = {
  offen: { word: "offen", mark: <span className="p-dot" /> },
  laeuft: { word: "läuft", mark: <span className="p-dot p-dot-run" /> },
  fertig: { word: "fertig", mark: <IconCheck /> },
  fehler: { word: "Fehler", mark: <IconCross /> },
};

export function Progress({ b }: { b: Of<"fortschritt"> }) {
  const done = b.schritte.filter((s) => s.zustand === "fertig").length;
  const failed = b.schritte.filter((s) => s.zustand === "fehler").length;
  return (
    <div className="v-progress">
      <p className="label p-count">{done} von {b.schritte.length} fertig{failed > 0 && `, ${failed} mit Fehler`}</p>
      <ol className="p-steps">
        {b.schritte.map((s, i) => {
          const st = STEP[s.zustand] ?? STEP.offen;
          return (
            <li key={i} className={`p-step p-${s.zustand}`} aria-current={s.zustand === "laeuft" ? "step" : undefined}>
              <span className="p-mark" aria-hidden="true">{st.mark}</span>
              <span className="p-text">{s.text}</span>
              <span className="p-state">{st.word}</span>
            </li>
          );
        })}
      </ol>
      {b.hinweis && <p className="v-note">{b.hinweis}</p>}
    </div>
  );
}

export function Tasks({ b }: { b: Of<"aufgaben"> }) {
  const done = b.punkte.filter((p) => p.erledigt).length;
  return (
    <div className="v-progress">
      <p className="label p-count">{done} von {b.punkte.length} erledigt</p>
      <ul className="p-steps">
        {b.punkte.map((p, i) => (
          <li key={i} className={`p-step ${p.erledigt ? "p-fertig" : "p-offen"}`}>
            <span className="p-mark" aria-hidden="true">{p.erledigt ? <IconCheck /> : <span className="p-dot" />}</span>
            <span className="p-text">{p.text}</span>
            <span className="p-state">{p.erledigt ? "erledigt" : "offen"}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const minutes = (hhmm: string) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5));

export function Schedule({ b }: { b: Of<"zeitplan"> }) {
  const span = b.termine.map((t) => [minutes(t.von), minutes(t.bis)] as const);
  const lo = Math.min(...span.map((s) => s[0])), hi = Math.max(...span.map((s) => s[1]));
  const clash = (i: number) => span.some((s, j) => j !== i && s[0] < span[i][1] && s[1] > span[i][0]);
  return (
    <div className="v-schedule">
      {b.tag && <p className="label">{b.tag}</p>}
      <ol className="s-list">
        {b.termine.map((t, i) => (
          <li key={i} className={clash(i) ? "s-item s-clash" : "s-item"}>
            <span className="s-time">{t.von} bis {t.bis}</span>
            <span className="s-title">{t.titel}{t.ort && <small> · {t.ort}</small>}{clash(i) && <em className="s-warn"> überschneidet sich</em>}</span>
            <span className="s-track" aria-hidden="true">
              <span className="s-block" style={{ left: `${((span[i][0] - lo) / (hi - lo || 1)) * 100}%`, width: `${Math.max(2, ((span[i][1] - span[i][0]) / (hi - lo || 1)) * 100)}%` }} />
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function Head({ rows }: { rows: [string, string][] }) {
  return (
    <dl className="m-head">
      {rows.filter(([, v]) => v).map(([k, v]) => <div key={k}><dt className="label">{k}</dt><dd>{v}</dd></div>)}
    </dl>
  );
}

export function Mail({ b }: { b: Of<"mail"> }) {
  return (
    <section className="v-mail" aria-label="Mail">
      <p className="m-flag">Fremder Inhalt, nur Text</p>
      <Head rows={[["Von", b.von], ["An", b.an], ["Betreff", b.betreff], ["Datum", b.datum]]} />
      {b.zusammenfassung && <div className="m-summary"><span className="label">Zusammenfassung</span><p>{b.zusammenfassung}</p></div>}
      <div className="m-body">{b.absaetze.map((a, i) => <p key={i}>{a}</p>)}</div>
    </section>
  );
}

export function MailDraft({ b }: { b: Of<"mail-entwurf"> }) {
  return (
    <section className="v-mail v-draft" aria-label="Mail-Entwurf">
      <p className="m-flag">Entwurf, noch nicht gesendet. Gesendet wird nur in Claude Code mit deiner Freigabe.</p>
      <Head rows={[["An", b.an], ["Cc", b.cc], ["Betreff", b.betreff]]} />
      <div className="m-body">{b.absaetze.map((a, i) => <p key={i}>{a}</p>)}</div>
    </section>
  );
}

const two = (n: number) => String(n).padStart(2, "0");

const DAY_MS = 24 * 3600 * 1000;

/** Restzeit als Text; `null`, wenn das Ende keine gültige Zeit ist oder mehr als 24 Stunden entfernt liegt. */
export function remaining(ende: string, now: number): string | null {
  const end = Date.parse(ende);
  if (!Number.isFinite(end) || Math.abs(end - now) > DAY_MS) return null;      // nie eine Zeit, die weiter als ein Tag weg ist
  const s = Math.ceil((end - now) / 1000);
  if (s <= 0) return "abgelaufen";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}:${two(m)}:${two(s % 60)}` : `${two(m)}:${two(s % 60)}`;
}

/** Nur eine Anzeige: kushim hat keinen Wecker und gibt keinen Ton. */
export function Countdown({ b }: { b: Of<"countdown"> }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  const rest = remaining(b.ende, now);
  return (
    <div className={`v-countdown${rest === "abgelaufen" ? " c-over" : ""}`} role="timer" aria-label={b.titel}>
      <span className="label">{b.titel}</span>
      <span className="c-rest">{rest ?? "Zeit unbekannt"}</span>
      <span className="v-note">Nur Anzeige, ohne Ton</span>
    </div>
  );
}
