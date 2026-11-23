import { useEffect, useRef, useState, type RefObject } from "react";
import type { ApiClient, ApiReply } from "../lib/api";
import { STATE_VIEW, type AvatarState } from "../lib/avatarState";
import { windowCommand } from "../lib/windowCmd";
import { Core3D } from "./Core3D";
import { HaltedBanner, KillButton } from "./KillButton";
import { PermissionBar, type PermissionRequest } from "./PermissionBar";
import type { Entry } from "./Transcript";

// E2 (docs/ui-e2e3-plan.md, Abschnitte 3 und 4): kleines Fenster mit Kern, Zustandswort, letztem Befehl, NOTAUS und Verbrauch.
// Die Leiste entscheidet nichts selbst: Freigaben laufen über dieselbe PermissionBar und denselben Aufruf wie im großen Fenster.
// Alle Inhalte sind reiner Text. Fensterbefehle ändern nur Größe und Lage des eigenen Fensters und holen nie den Fokus.

/* ----- Verbrauch (usage.get) ------------------------------------------------------------------------------------------ */

export const USAGE_POLL_MS = 30_000;
const STALE_S = 30 * 60;                                   // älter als 30 min: gedämpft mit „veraltet“ (auch wenn der Dienst es nicht meldet)
export const USAGE_HINT = "Verbrauch: Statuszeile oder /usage im Claude-Fenster";

export type Usage =
  | { kind: "none" }                                       // nicht verfügbar oder Dienst kennt usage.get nicht
  | { kind: "bad" }                                        // Antwort nicht lesbar
  | { kind: "ok"; model: string; context: number | null; five: number | null; seven: number | null; cost: number | null;
      stand: number; stale: boolean };

const pct = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= 100 ? v : null);

/** Prüft die Antwort von usage.get Feld für Feld; was nicht passt, fällt weg. Nie eine Zahl erfinden. */
export function parseUsage(r: ApiReply): Usage {
  if (!r.ok) return r.error === "unknown_type" ? { kind: "none" } : { kind: "bad" };
  if (r.available !== true) return { kind: "none" };
  if (typeof r.stand !== "number" || !Number.isFinite(r.stand) || r.stand <= 0) return { kind: "bad" };
  const model = typeof r.model === "string" ? r.model.replace(/[\u0000-\u001f\u007f-\u009f]/g, "").trim().slice(0, 40) : "";
  const cost = typeof r.cost_usd === "number" && Number.isFinite(r.cost_usd) && r.cost_usd >= 0 ? r.cost_usd : null;
  const old = Date.now() / 1000 - r.stand > STALE_S;
  return { kind: "ok", model, context: pct(r.context_pct), five: pct(r.five_h_pct), seven: pct(r.seven_d_pct), cost,
    stand: r.stand, stale: r.stale !== false || old };
}

const two = (n: number) => String(n).padStart(2, "0");

/** „Stand 14:05“ in Ortszeit; nicht von heute: mit Datum. */
export function standText(epochS: number, now = new Date()): string {
  const d = new Date(epochS * 1000);
  const time = `${two(d.getHours())}:${two(d.getMinutes())}`;
  const today = d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
  return today ? `Stand ${time}` : `Stand ${two(d.getDate())}.${two(d.getMonth() + 1)}. ${time}`;
}

/** Die Werte als eine Zeile; leere Felder fallen weg. */
export function usageParts(u: Extract<Usage, { kind: "ok" }>): string[] {
  const parts: string[] = [];
  if (u.model) parts.push(u.model);
  if (u.context !== null) parts.push(`Kontext ${Math.round(u.context)} %`);
  if (u.five !== null) parts.push(`5h ${Math.round(u.five)} %`);
  if (u.seven !== null) parts.push(`7d ${Math.round(u.seven)} %`);
  if (u.cost !== null) parts.push(`Kosten ${u.cost.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} $`);
  return parts;
}

/** Fragt usage.get höchstens alle 30 s ab, nur solange `active` gilt und das Fenster sichtbar ist. */
export function useUsage(client: RefObject<ApiClient | null>, connected: boolean, active: boolean): Usage | null {
  const [usage, setUsage] = useState<Usage | null>(null);
  const lastAt = useRef(-Infinity);
  useEffect(() => {
    if (!connected || !active) return;
    let stop = false, busy = false;
    const pull = async () => {
      if (busy || document.hidden || Date.now() - lastAt.current < USAGE_POLL_MS - 500) return;
      busy = true;
      lastAt.current = Date.now();
      const r = await client.current?.call("usage.get");
      busy = false;
      if (stop || !r) return;
      if (r.ok || r.error === "unknown_type") setUsage(parseUsage(r));       // offline oder Zeitüberschreitung: letzten Stand behalten
    };
    void pull();
    const id = setInterval(pull, USAGE_POLL_MS);
    const onVisible = () => { if (!document.hidden) void pull(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { stop = true; clearInterval(id); document.removeEventListener("visibilitychange", onVisible); };
  }, [client, connected, active]);
  return usage;
}

/** Verbrauch als ruhige Textzeile mit Stand; veraltet gedämpft mit Wort. Ohne Werte der Hinweis auf Statuszeile oder /usage. */
export function UsageLine({ usage }: { usage: Usage | null }) {
  if (!usage) return null;
  if (usage.kind === "bad") return <p className="usage">Verbrauch: unbekannt (Antwort nicht lesbar)</p>;
  const parts = usage.kind === "ok" ? usageParts(usage) : [];
  if (usage.kind !== "ok" || parts.length === 0) return <p className="usage">{USAGE_HINT}</p>;
  const values = parts.join(" · ");
  const when = `${standText(usage.stand)}${usage.stale ? " · veraltet" : ""}`;
  return (
    <p className={usage.stale ? "usage is-stale" : "usage"} title={`${values}, ${when}`}>
      <span className="usage-values">{values}</span> <span className="usage-when">{when}</span>
    </p>
  );
}

/* ----- Kleines Fenster ---------------------------------------------------------------------------------------------------- */

const NOTE: Record<string, string> = {
  rejected_speaker: "Stimme nicht erkannt. Keine Antwort.",
  killed: "Notaus ausgelöst.",
  interrupted: "(unterbrochen)",
  cancelled: "Abgebrochen.",
};

export const COMPACT_CORE = 72;

interface Props {
  state: AvatarState;
  level: number;
  connected: boolean;
  voiceActive: boolean;
  last: Entry | null;                                      // letzter Eintrag aus transcript.get
  request: PermissionRequest | null;                       // offene Freigabe (nur wenn der Zustand „asking“ ist)
  more: number;
  onDecide: (request: PermissionRequest, approve: boolean) => void;
  onKill: () => void;
  onResume: () => void;
  onBig: () => void;
  onTop: boolean;
  onToggleTop: () => void;
  usage: Usage | null;
  view: { id: string; titel: string } | null;             // gerade gezeigte Ansicht von Claude
  toast: string;
}

export function CompactBar(p: Props) {
  const stateView = STATE_VIEW[p.state];
  const asking = p.request !== null;
  const requestKey = p.request ? `${p.request.request_id}\n${p.request.digest}` : null;

  useEffect(() => {                                       // Freigabe offen: wachsen, danach zurück auf klein (Fokus bleibt, wo er ist)
    if (!asking) return;
    void windowCommand("grow_for_approval", { on: true });
    return () => { void windowCommand("grow_for_approval", { on: false }); };
  }, [asking]);
  useEffect(() => {                                       // je neuer Anfrage einmal die Taskleiste blinken lassen
    if (requestKey) void windowCommand("attention");
  }, [requestKey]);

  const startView = useRef(p.view?.id ?? null);           // nur Ansichten melden, die nach dem Umschalten kamen
  const freshView = p.view && p.view.id !== startView.current ? p.view : null;

  const heard = p.last?.heard ?? "";
  const replyFull = p.last ? p.last.reply || NOTE[p.last.outcome] || "" : "";
  const reply = replyFull.split("\n")[0];
  const you = heard ? `Du: ${heard}`
    : !p.connected ? "Kein Dienst. „Groß“ zeigt den Grund."
    : p.voiceActive ? "Noch nichts gesagt. Sag „hey kushim“." : "";

  return (
    <section className="compact" aria-label="Kleines Fenster" data-state={p.state} data-mode={asking ? "freigabe" : "klein"}>
      <div className="compact-core">
        {!asking && <Core3D state={p.state} size={COMPACT_CORE} level={p.level} />}
        <p className="compact-word" aria-live={stateView.live}>{stateView.label}</p>
      </div>
      <div className="compact-actions">
        <button type="button" onClick={p.onBig} title="Großes Fenster (Strg+Umschalt+M)" autoFocus>Groß</button>
        <KillButton onKill={p.onKill} />
      </div>
      <div className="compact-text">
        {p.state === "halted" ? <HaltedBanner onResume={p.onResume} /> : <>
          {you && <p className="compact-you" title={you}>{you}</p>}
          {reply && <p className={p.last?.outcome === "rejected_speaker" ? "compact-reply alarm" : "compact-reply"} title={replyFull}>kushim: {reply}</p>}
          {p.connected && !p.voiceActive && <p className="compact-muted">Kein Sprachdienst</p>}
          {freshView && <p className="compact-note" title={freshView.titel}>Neue Ansicht von Claude: {freshView.titel}. Zum Ansehen „Groß“.</p>}
        </>}
        <p className="compact-toast" role="status" aria-live="polite">{p.toast}</p>
      </div>
      {p.request && (
        <div className="compact-approval">
          <PermissionBar request={p.request} more={p.more} onDecide={p.onDecide} />
        </div>
      )}
      <div className="compact-foot">
        <UsageLine usage={p.usage} />
        <button type="button" aria-pressed={p.onTop} onClick={p.onToggleTop}
          title="Bleibt über anderen Fenstern, solange es klein ist">Immer im Vordergrund: {p.onTop ? "an" : "aus"}</button>
      </div>
    </section>
  );
}
