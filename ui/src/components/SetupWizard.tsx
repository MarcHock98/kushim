// Setup-Assistent (E3, docs/ui-e2e3-plan.md Abschnitt 5): erscheint beim Start, solange `first_start` gilt, später über
// „Einrichtung“ in der Sicherheitsansicht. Links die Schritte mit Status als Wort, rechts der Inhalt, unten Zurück / Überspringen /
// Weiter. Nur im großen Fenster: trägt `.app` die Klasse des kleinen Fensters, wartet der Assistent unsichtbar.
// Die Oberfläche führt nichts selbst aus: Sie sendet nur die Typen setup.*, audio.*, voice.level_*, wake.* und claude.folder_*;
// alles Schreibende geht mit confirm: true, das Backend prüft (Notaus sperrt) und meldet, ob es erst ab dem nächsten Start gilt.
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import type { ApiClient, ApiReply } from "../lib/api";
import { IconCheck, IconWarn } from "./Icons";
import {
  ClaudeStep, FolderStep, MicStep, parseChecks, redact, SafetyStep, SystemStep, WakeStep, type Call, type ChecksState, type StepCtx,
} from "./SetupSteps";

export const STEPS: { id: string; title: string; skip: string }[] = [
  { id: "system", title: "Systemcheck", skip: "Kein Gedächtnis. Notaus und Sicherheitsregeln gelten weiter." },
  { id: "claude", title: "Claude", skip: "Ohne Claude Code bekommt kushim keine Antworten. Notaus und Sicherheitsregeln gelten weiter." },
  { id: "audio_voice", title: "Mikrofon", skip: "Es gelten die Windows-Standardgeräte und die Standard-Pegel." },
  { id: "wake_words", title: "Wake Words", skip: "Es gelten die Standard-Wörter aus der Vorlage." },
  { id: "folder", title: "Arbeitsordner", skip: "Claude arbeitet nur in Ordnern, die schon freigegeben sind." },
  { id: "safety", title: "Sicherheit", skip: "Der Notaus wirkt trotzdem." },
];

export const RESTART = "Gilt ab dem nächsten Start von kushim.";
const COMPACT_CLASSES = ["is-compact", "compact"];

export interface SetupStatus {
  steps: { step: string; status: string; detail: string }[];
  first_start: boolean;
  restricted: string[];
  kill: boolean;
}

export function parseStatus(r: ApiReply): SetupStatus | null {
  if (!r.ok || !Array.isArray(r.steps)) return null;
  const steps = r.steps.filter((s): s is Record<string, unknown> => !!s && typeof s === "object" && typeof s.step === "string" && typeof s.status === "string")
    .map((s) => ({ step: String(s.step).slice(0, 40), status: String(s.status).slice(0, 20), detail: typeof s.detail === "string" ? redact(s.detail.slice(0, 300)) : "" }));
  const restricted = Array.isArray(r.restricted) ? r.restricted.filter((x): x is string => typeof x === "string").slice(0, 12).map((x) => redact(x.slice(0, 300))) : [];
  return { steps, first_start: r.first_start === true, restricted, kill: r.kill === true };
}

const WORD: Record<string, string> = { done: "erledigt", skipped: "übersprungen", open: "offen" };
const TONE: Record<string, string> = { done: "ok", skipped: "warn", open: "open" };

function errorText(error: string): string {
  if (error === "kill") return "Notaus ist aktiv. Nichts wurde geändert.";
  if (error === "offline" || error === "timeout") return "Keine Verbindung zu kushim. Nichts wurde geändert.";
  if (error === "unavailable") return "Starte kushim mit Sprache, dann geht der Test.";
  if (error === "unknown_type") return "Dieser Dienst kennt das noch nicht. Starte kushim in der neuen Fassung.";
  return "Das hat nicht geklappt. Nichts wurde geändert.";
}

interface WizardProps {
  client: RefObject<ApiClient | null>;
  connected: boolean;
  read: Call;
  status: SetupStatus | null;
  onStatus: (s: SetupStatus) => void;
  kill: boolean;
  hidden: boolean;
  onClose: () => void;
}

export function SetupWizard({ client, connected, read, status, onStatus, kill, hidden, onClose }: WizardProps) {
  const [cur, setCur] = useState(() => {
    const i = STEPS.findIndex((s) => status?.steps.find((x) => x.step === s.id)?.status === "open");
    return i < 0 ? 0 : i;
  });
  const [note, setNote] = useState("");
  const [restart, setRestart] = useState(false);
  const [checks, setChecks] = useState<ChecksState>({ list: null, state: "loading" });
  const head = useRef<HTMLHeadingElement>(null);
  const stepBtns = useRef<(HTMLButtonElement | null)[]>([]);
  const locked = kill || status?.kill === true;
  const step = STEPS[cur];

  const write = useCallback<Call>(async (type, data = {}) => {
    const r = await read(type, { ...data, confirm: true });
    if (r.ok) { if (r.restart_needed === true) setRestart(true); }
    else setNote(errorText(r.error));
    return r;
  }, [read]);
  const say = useCallback((t: string) => setNote(t), []);
  const done = useCallback(async (id: string) => {
    const r = await write("setup.done", { step: id });
    const s = parseStatus(r);
    if (s) { onStatus(s); setNote("Schritt bestätigt."); }
  }, [write, onStatus]);
  const ctx: StepCtx = { read, write, locked, say, done };

  const loadChecks = useCallback(async () => {
    setChecks((c) => ({ list: c.list, state: "loading" }));
    const r = await read("setup.checks");
    const list = parseChecks(r);
    setChecks(list ? { list, state: "ready" } : { list: null, state: !r.ok && r.error === "unknown_type" ? "unknown" : "error" });
  }, [read]);
  useEffect(() => { void loadChecks(); }, [loadChecks]);

  const go = useCallback((i: number) => {
    if (i < 0 || i >= STEPS.length) return;
    setCur(i); setNote(""); setRestart(false);
  }, []);
  const stayInList = useRef(false);                   // Pfeiltasten in der Schrittliste: Fokus bleibt in der Liste
  useEffect(() => {                                   // Fokus auf die Schrittüberschrift, aber nie einer offenen Freigabe wegnehmen
    if (stayInList.current) { stayInList.current = false; return; }
    if (!hidden && !document.activeElement?.closest?.(".approval")) head.current?.focus();
  }, [cur, hidden]);

  const skip = async () => {
    const r = await write("setup.skip", { step: step.id });
    const s = parseStatus(r);
    if (!s) return;
    onStatus(s);
    if (cur === STEPS.length - 1) onClose(); else go(cur + 1);
  };
  const reopen = async () => {
    const s = parseStatus(await write("setup.reopen", { step: step.id }));
    if (s) { onStatus(s); setNote("Schritt wieder offen."); }
  };

  const onListKey = (e: React.KeyboardEvent, i: number) => {
    if (e.ctrlKey || e.altKey || e.metaKey) return;                 // Tasten mit Strg, Alt oder Meta gehören dem Browser
    const to = e.key === "ArrowDown" ? i + 1 : e.key === "ArrowUp" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? STEPS.length - 1 : null;
    if (to === null || to < 0 || to >= STEPS.length) return;
    e.preventDefault();
    if (to === cur) return;
    stayInList.current = true;
    go(to);
    stepBtns.current[to]?.focus();
  };

  const statusOf = (id: string) => status?.steps.find((x) => x.step === id)?.status ?? "";
  const mine = statusOf(step.id);
  const last = cur === STEPS.length - 1;

  return (
    <section className="setup" aria-labelledby="setup-h" hidden={hidden}>
      <div className="panel-head setup-head">
        <h2 id="setup-h">Einrichtung</h2>
        <span className="label">Schritt {cur + 1} von {STEPS.length}</span>
        <button type="button" onClick={onClose}>Schließen</button>
      </div>
      {locked && <p className="setup-lock" role="status">Gesperrt: Notaus aktiv. Ändern geht erst nach dem Aufheben.</p>}
      <div className="setup-body">
        <nav className="setup-nav" aria-label="Schritte der Einrichtung">
          <ol className="setup-steps">
            {STEPS.map((s, i) => {
              const st = statusOf(s.id);
              return (
                <li key={s.id}>
                  <button type="button" ref={(el) => { stepBtns.current[i] = el; }} aria-current={i === cur ? "step" : undefined}
                    aria-label={`${s.title}, ${WORD[st] ?? "unbekannt"}`}
                    onClick={() => go(i)} onKeyDown={(e) => onListKey(e, i)} className={`tone-${TONE[st] ?? "open"}`}>
                    <span className="setup-n" aria-hidden="true">{i + 1}</span>
                    <span className="setup-t">{s.title}</span>
                    <span className="setup-st">
                      <span aria-hidden="true" className="sec-icon">{st === "done" ? <IconCheck /> : st === "skipped" ? <IconWarn /> : null}</span>
                      {WORD[st] ?? "unbekannt"}
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
          {status && status.restricted.length > 0 && (
            <div className="setup-restricted">
              <p className="label">Eingeschränkt</p>
              {status.restricted.map((n) => <p key={n} className="setup-calm">{n}</p>)}
            </div>
          )}
        </nav>
        <div className="setup-main">
          <h3 ref={head} tabIndex={-1}>{cur + 1}. {step.title}</h3>
          {mine === "skipped" && (
            <div className="setup-calm-box">
              <p className="setup-calm">Übersprungen. {step.skip}</p>
              <button type="button" disabled={locked} onClick={() => void reopen()}>Wieder aufnehmen</button>
            </div>
          )}
          {step.id === "system" && <SystemStep checks={checks} reload={() => void loadChecks()} />}
          {step.id === "claude" && <ClaudeStep checks={checks} reload={() => void loadChecks()} />}
          {step.id === "audio_voice" && <MicStep ctx={ctx} />}
          {step.id === "wake_words" && <WakeStep ctx={ctx} />}
          {step.id === "folder" && <FolderStep client={client} connected={connected} locked={locked} say={say} />}
          {step.id === "safety" && <SafetyStep ctx={ctx} />}
          <div className="setup-msg" role="status" aria-live="polite">
            {note && <p>{note}</p>}
            {restart && <p>{RESTART}</p>}
          </div>
        </div>
      </div>
      <div className="setup-foot">
        <p className="setup-skipnote">Wenn du überspringst: {step.skip}</p>
        <div className="setup-buttons">
          <button type="button" disabled={cur === 0} onClick={() => go(cur - 1)}>Zurück</button>
          <button type="button" disabled={locked} onClick={() => void skip()}>Überspringen</button>
          <button type="button" className="primary" onClick={() => (last ? onClose() : go(cur + 1))}>{last ? "Fertig" : "Weiter"}</button>
        </div>
      </div>
    </section>
  );
}

/** Eintrag „Einrichtung“ in der Sicherheitsansicht: übersprungene Schritte als ruhige Zeilen, Knopf öffnet den Assistenten. */
function SetupEntry({ status, onOpen }: { status: SetupStatus | null; onOpen: () => void }) {
  const open = status ? status.steps.filter((s) => s.status === "open").length : null;
  return (
    <section className="panel setup-entry" aria-labelledby="setup-entry-h">
      <div className="panel-head">
        <h2 id="setup-entry-h">Einrichtung</h2>
        <span className="label">{open === null ? "Stand unbekannt" : open === 0 ? "nichts offen" : `${open} offen`}</span>
      </div>
      <p className="setup-text">Systemcheck, Claude, Mikrofon, Wake Words, Arbeitsordner und Sicherheit, Schritt für Schritt.</p>
      {status?.restricted.map((n) => <p key={n} className="setup-calm">{n}</p>)}
      <div className="setup-row"><button type="button" className="primary" onClick={onOpen}>Einrichtung öffnen</button></div>
    </section>
  );
}

/** Alles zum Setup an einer Stelle im Hauptbereich: der Assistent, der Eintrag in der Sicherheitsansicht und die ruhige Zeile
 *  für den eingeschränkten Modus. Liest den Status einmal nach dem Verbinden; öffnet den Assistenten, solange `first_start` gilt. */
export function SetupHost({ client, connected, kill, view }: {
  client: RefObject<ApiClient | null>; connected: boolean; kill: boolean; view: string }) {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [compact, setCompact] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const asked = useRef(false);
  const lastView = useRef(view);

  const read = useCallback<Call>(async (type, data = {}) => {
    const c = client.current;
    return c ? c.call(type, data) : { ok: false, error: "offline" };
  }, [client]);
  const refresh = useCallback(async () => {
    const s = parseStatus(await read("setup.status"));
    if (s) setStatus(s);
    return s;
  }, [read]);

  useEffect(() => {                                   // einmal nach dem ersten Verbinden: Erststart?
    if (!connected || asked.current) return;
    asked.current = true;
    void refresh().then((s) => { if (s?.first_start) setOpen(true); });
  }, [connected, refresh]);

  const lastKill = useRef(kill);
  useEffect(() => {                                   // Notaus ausgelöst oder aufgehoben: Stand neu holen (Sperre im Assistenten)
    if (lastKill.current === kill) return;
    lastKill.current = kill;
    if (connected) void refresh();
  }, [kill, connected, refresh]);

  useEffect(() => {                                   // anderer Bereich gewählt: Assistent schließen; Sicherheit: Stand neu holen
    if (lastView.current === view) return;
    lastView.current = view;
    setOpen(false);
    if (view === "security" && connected) void refresh();
  }, [view, connected, refresh]);

  useEffect(() => {                                   // kleines Fenster (E2): Klasse an .app beobachten, der Assistent wartet
    const app = root.current?.closest(".app");
    if (!app) return;
    const check = () => setCompact(COMPACT_CLASSES.some((c) => app.classList.contains(c)));
    check();
    const mo = new MutationObserver(check);
    mo.observe(app, { attributes: true, attributeFilter: ["class"] });
    return () => mo.disconnect();
  }, []);

  const close = useCallback(() => { setOpen(false); void refresh(); }, [refresh]);

  return (
    <div className="setup-host" ref={root}>
      {open && connected && (
        <SetupWizard client={client} connected={connected} read={read} status={status} onStatus={setStatus} kill={kill}
          hidden={compact} onClose={close} />
      )}
      {!open && !compact && view === "security" && connected && <SetupEntry status={status} onOpen={() => setOpen(true)} />}
      {!open && !compact && view !== "security" && status && status.restricted.length > 0 && (
        <div className="setup-calm-line">
          {status.restricted.map((n) => <p key={n} className="setup-calm">Eingeschränkt: {n}</p>)}
          <p className="setup-calm">Nachholen unter Sicherheit, Einrichtung.</p>
        </div>
      )}
    </div>
  );
}
