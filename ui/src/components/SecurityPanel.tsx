import { useState, type ReactNode } from "react";
import { IconCheck, IconCross, IconWarn } from "./Icons";

export interface Overview {
  mode: "A" | "C";
  kill: boolean;
  tools_active: string[] | null;
  vault: { where: string; exists: boolean; open: boolean };
  backup: { configured: boolean; age_days: number | null };
  money_limit_eur: number;
  audit: { ts: number; event: string; detail: string }[];
}

type Tone = "ok" | "warn" | "alarm";
const ICON: Record<Tone, ReactNode> = { ok: <IconCheck />, warn: <IconWarn />, alarm: <IconCross /> };

function Row({ label, tone, text }: { label: string; tone: Tone; text: string }) {
  // Zustand immer mit Wort UND Symbol UND Farbe, nie nur Farbe.
  return (
    <li className={`sec-row tone-${tone}`}>
      <span className="sec-label">{label}</span>
      <span className="sec-val"><span aria-hidden="true" className="sec-icon">{ICON[tone]}</span> {text}</span>
    </li>
  );
}

export const BACKUP_WARN_DAYS = 7;

/** Warnungen oben, sachlich. Nur Anzeige, nichts davon lässt sich hier ändern (Einstellungen kommen mit eigenem Schutz). */
export function warnings(o: Overview): string[] {
  const w: string[] = [];
  if (o.mode === "C") w.push("Modus C ist aktiv: Texte, die du freigibst, gehen an Anthropic.");
  if (o.kill) w.push("Notaus ist aktiv.");
  if (!o.vault.exists) w.push("Es gibt noch keinen Vault.");
  if (o.backup.configured && (o.backup.age_days === null || o.backup.age_days > BACKUP_WARN_DAYS)) {
    w.push(o.backup.age_days === null ? "Es gibt noch keine Sicherung." : `Die letzte Sicherung ist älter als ${BACKUP_WARN_DAYS} Tage.`);
  }
  return w;
}

export function SecurityPanel({ overview }: { overview: Overview | null }) {
  const [filter, setFilter] = useState("");
  if (!overview) return <p className="hint">Sicherheitsstatus wird geladen …</p>;
  const o = overview;
  const rows = o.audit.filter((a) => `${a.event} ${a.detail}`.toLowerCase().includes(filter.toLowerCase())).reverse();
  const when = (ts: number) => new Date(ts * 1000).toLocaleString("de-DE");
  return (
    <section className="security" aria-label="Sicherheitsstatus">
      {warnings(o).map((w) => <p key={w} className="sec-warn" role="status">{w}</p>)}
      <ul className="sec-list">
        <Row label="Modus" tone={o.mode === "A" ? "ok" : "warn"} text={o.mode === "A" ? "Lokal (Modus A)" : "Claude erlaubt (Modus C)"} />
        <Row label="Notaus" tone={o.kill ? "alarm" : "ok"} text={o.kill ? "aktiv" : "bereit"} />
        <Row label="Werkzeuge" tone={o.tools_active === null ? "warn" : "ok"} text={o.tools_active === null ? "unbekannt" : o.tools_active.length ? o.tools_active.join(", ") : "keines eingeschaltet"} />
        <Row label="Vault" tone={o.vault.exists && o.vault.open ? "ok" : "warn"}
          text={`${o.vault.where === "local" ? "lokal" : "im Netz"}, ${o.vault.exists ? (o.vault.open ? "offen" : "nicht geöffnet") : "nicht gefunden"}`} />
        <Row label="Sicherung" tone={!o.backup.configured ? "warn" : o.backup.age_days !== null && o.backup.age_days <= BACKUP_WARN_DAYS ? "ok" : "warn"}
          text={!o.backup.configured ? "nicht eingerichtet" : o.backup.age_days === null ? "noch keine" : `vor ${o.backup.age_days.toLocaleString("de-DE")} Tagen`} />
        <Row label="Geldlimit" tone="ok" text={o.money_limit_eur === 0 ? "0 €, gesperrt" : `${o.money_limit_eur} €`} />
      </ul>
      <div className="sec-log">
      <h2 className="sec-h">Protokoll (nur lesen)</h2>
      <input type="search" aria-label="Protokoll filtern" placeholder="Filtern …" value={filter} onChange={(e) => setFilter(e.target.value)} />
      {o.audit.length === 0 ? <p className="hint">Noch keine Einträge (oder der Vault ist nicht offen).</p> : (
        <ol className="audit">
          {rows.map((a, i) => (
            <li key={`${a.ts}-${i}`}><time>{when(a.ts)}</time> <strong>{a.event}</strong> {a.detail}</li>
          ))}
        </ol>
      )}
      </div>
    </section>
  );
}
