import { useEffect, useId, useState, type KeyboardEvent, type ReactNode } from "react";
import { IconCheck, IconChevron, IconClock, IconDash, IconThumbDown, IconThumbUp, IconVoiceOff } from "./Icons";

/** Ein Eintrag aus transcript.get (geprüft mit `parseEntry`). `id` ist stabil, `rev` steigt bei jeder Änderung. */
export interface Entry {
  id: number;
  rev: number;
  heard: string;                     // Befehl ohne Weckwort, so wie er an Claude geht
  raw: string;                       // Whisper-Text mit Weckwort (nie geschwärzt)
  ts: number | null;                 // Erkennungszeit (Sekunden seit 1970)
  status: EntryStatus;
  reason: string;                    // Code oder ""
  sent_ts: number | null;
  reply: string;
  outcome: string;
  unspoken: number;                  // Sätze der Antwort, die nur als Text kamen (Stimme aus); 0 = gesprochen oder älterer Dienst
}
export type EntryStatus = "pending" | "sent" | "dropped" | "unknown";

export const MAX_TEXT = 2000;
export const MAX_ENTRIES = 20;

const NOTE: Record<string, string> = {
  rejected_speaker: "Stimme nicht erkannt. Keine Antwort.",
  killed: "Notaus ausgelöst.",
  interrupted: "(unterbrochen)",
  cancelled: "Abgebrochen.",
};

export const STATUS_WORD: Record<EntryStatus, string> = { pending: "wartet", sent: "gesendet", dropped: "verworfen", unknown: "unbekannt" };
const STATUS_ICON: Record<EntryStatus, ReactNode> = { pending: <IconClock />, sent: <IconCheck />, dropped: <IconDash />, unknown: <IconDash /> };

export const REASON: Record<string, string> = {
  killed: "Notaus",
  cancelled: "Abbruch",
  wake_only: "Nur Weckwort, kein Befehl",
  command: "Lokaler Befehl, nicht an Claude",
  end_conversation: "Gespräch beendet",
  shutdown: "kushim beendet",
  halted: "Notaus aktiv",
  not_running: "Claude nicht erreichbar",
  send_failed: "Senden fehlgeschlagen",
};
export const KILLED_TEXT = "Notaus-Befehl erkannt";

/** Erkannter Text: Zeilen- und Tabzeichen werden Leerzeichen, andere Steuer- und Richtungszeichen fallen weg, Länge begrenzt. */
export function cleanText(v: unknown, max = MAX_TEXT): string {
  if (typeof v !== "string") return "";
  const flat = v.replace(/[\t\n\r\v\f\p{Zl}\p{Zp}]+/gu, " ").replace(/[\p{Cc}\p{Cf}]/gu, "");
  return Array.from(flat.trim()).slice(0, max).join("").trim();
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) && v > 0 ? v : null);
const STATUSES = new Set(["pending", "sent", "dropped"]);

/** Prüft einen Eintrag vom Backend Feld für Feld; ohne gültige id fällt er weg. Nie etwas erfinden: Unbekanntes bleibt unbekannt. */
export function parseEntry(x: unknown): Entry | null {
  const r = x as Record<string, unknown> | null;
  if (!r || typeof r !== "object" || typeof r.id !== "number" || !Number.isSafeInteger(r.id) || r.id <= 0) return null;
  const rev = typeof r.rev === "number" && Number.isSafeInteger(r.rev) && r.rev > 0 ? r.rev : r.id;
  const status = typeof r.status === "string" && STATUSES.has(r.status) ? (r.status as EntryStatus) : "unknown";
  const reason = typeof r.reason === "string" ? (/^[a-z_]{1,30}$/.test(r.reason) ? r.reason : r.reason === "" ? "" : "?") : "";
  return {
    id: r.id, rev, heard: cleanText(r.heard), raw: cleanText(r.raw), ts: num(r.ts), status, reason, sent_ts: num(r.sent_ts),
    reply: typeof r.reply === "string" ? r.reply.slice(0, MAX_TEXT) : "",
    outcome: typeof r.outcome === "string" ? r.outcome.slice(0, 40) : "",
    unspoken: typeof r.unspoken === "number" && Number.isSafeInteger(r.unspoken) && r.unspoken > 0 ? r.unspoken : 0,
  };
}

/** Führt neue Stände nach id zusammen: ersetzt (nur mit höherer rev), hängt nie doppelt an, älteste fallen heraus. */
export function mergeEntries(old: Entry[], fresh: Entry[], max = MAX_ENTRIES): Entry[] {
  const next = [...old];
  for (const e of fresh) {
    const i = next.findIndex((o) => o.id === e.id);
    if (i < 0) next.push(e);
    else if (e.rev > next[i].rev) next[i] = e;
  }
  next.sort((a, b) => a.id - b.id);
  return next.slice(-max);
}

const two = (n: number) => String(n).padStart(2, "0");

/** „14:03:22“ in Ortszeit; ohne Zeit „unbekannt“. */
export function clockText(epochS: number | null): string {
  if (epochS === null) return "unbekannt";
  const d = new Date(epochS * 1000);
  return `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}`;
}

/** Wie `clockText`, an einem anderen Tag mit Datum davor („22.11. 14:03:22“). */
export function whenText(epochS: number | null, now = new Date()): string {
  if (epochS === null) return "unbekannt";
  const d = new Date(epochS * 1000);
  const today = d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
  return today ? clockText(epochS) : `${two(d.getDate())}.${two(d.getMonth() + 1)}.${d.getFullYear() === now.getFullYear() ? "" : d.getFullYear()} ${clockText(epochS)}`;
}

const isKilled = (e: Entry) => e.reason === "killed" || e.outcome === "killed";

/** Text der Zeile „Du“: der Befehl, sonst das Rohe (nur Weckwort), beim Notaus der feste Text. Leer: keine Zeile. */
export function youText(e: Entry): string {
  if (isKilled(e) && !e.heard) return KILLED_TEXT;
  return e.heard || e.raw;
}

const reasonText = (code: string) => REASON[code] ?? "unbekannt";

/** Vermerk an einer Antwort, die (ganz oder teilweise) nur als Text kam: „nicht gesprochen (Stimme aus), 2 Sätze“. Sonst leer. */
export function unspokenText(e: Pick<Entry, "reply" | "unspoken">): string {
  if (!e.reply || e.unspoken <= 0) return "";
  return `nicht gesprochen (Stimme aus), ${e.unspoken} ${e.unspoken === 1 ? "Satz" : "Sätze"}`;
}

function statusDetail(e: Entry): string {
  if (e.status === "sent") return e.sent_ts !== null ? `gesendet um ${clockText(e.sent_ts)}` : "gesendet";
  return STATUS_WORD[e.status];
}

/** Zeile „Du“: ein Knopf über die volle Breite, klappt die Erkennungsdetails auf. Nur Text, nie HTML. */
function YouRow({ e, open, onToggle }: { e: Entry; open: boolean; onToggle: () => void }) {
  const detailId = useId();                                // nie die Backend-id in id, class oder style
  const text = youText(e);
  const word = STATUS_WORD[e.status];
  const time = clockText(e.ts);
  const onKey = (ev: KeyboardEvent<HTMLButtonElement>) => {
    if (ev.key !== "Escape" || !open || ev.ctrlKey || ev.altKey || ev.metaKey) return;
    ev.preventDefault();
    ev.stopPropagation();                                  // nur zuklappen, nicht zugleich die Bühne schliessen
    onToggle();
  };
  return (
    <>
      <button type="button" className="you-row" aria-expanded={open} aria-controls={detailId}
        aria-label={`Du: ${text}, ${word}, ${time}`} onClick={onToggle} onKeyDown={onKey}>
        <span className="you-head">
          <span className="who">Du · {time}</span>
          <span className={isKilled(e) ? "you-chip is-alarm" : "you-chip"}>{STATUS_ICON[e.status]}{word}</span>
          <span className={open ? "you-chev is-open" : "you-chev"}><IconChevron /></span>
        </span>
        <span className="you-text">{text}</span>
      </button>
      <dl id={detailId} className="you-details" hidden={!open}>
        {open && <>
          <dt>Erkannt um</dt><dd>{whenText(e.ts)}</dd>
          <dt>Status</dt><dd>{statusDetail(e)}</dd>
          {(e.status === "dropped" || e.reason !== "") && <><dt>Grund</dt><dd>{reasonText(e.reason)}</dd></>}
          {e.raw !== "" && e.raw !== e.heard && <><dt>Erkannt (roh)</dt><dd>{e.raw}</dd></>}
          {e.status === "sent" && e.heard !== "" && <><dt>An Claude</dt><dd>{e.heard}</dd></>}
        </>}
      </dl>
    </>
  );
}

/** Die letzten Äußerungen: „Du“ (Bernstein, aufklappbar), kushim im Cyan-Bogen mit Daumen. Nur Text, nie HTML. */
export function Transcript({ entries, rated = {}, onRate }: {
  entries: Entry[]; rated?: Record<number, 1 | -1>; onRate?: (id: number, rating: 1 | -1) => void }) {
  const [open, setOpen] = useState<Set<number>>(() => new Set());   // nur Ansicht, nie gespeichert
  const shown = entries.slice(-4);
  const shownKey = shown.map((e) => e.id).join(",");
  useEffect(() => {                                       // herausgefallene Einträge vergessen
    const ids = new Set(shownKey ? shownKey.split(",").map(Number) : []);
    setOpen((old) => {
      const keep = new Set([...old].filter((id) => ids.has(id)));
      return keep.size === old.size ? old : keep;
    });
  }, [shownKey]);
  const toggle = (id: number) => setOpen((old) => {
    const next = new Set(old);
    if (!next.delete(id)) next.add(id);
    return next;
  });

  if (entries.length === 0) {
    return <p className="hint">Noch nichts gesagt. Sag „hey kushim“.</p>;
  }
  return (
    <ol className="transcript" aria-label="Verlauf">
      {shown.map((e) => (
        <li key={e.id} className="turn">
          {youText(e) && <YouRow e={e} open={open.has(e.id)} onToggle={() => toggle(e.id)} />}
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
              {unspokenText(e) && <span className="bot-note"><IconVoiceOff />{unspokenText(e)}</span>}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}
