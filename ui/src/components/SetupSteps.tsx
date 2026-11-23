// Die sechs Schritte des Setup-Assistenten (docs/ui-e2e3-plan.md, Abschnitt 5). Jeder Schritt liest nur über `read` und schreibt
// nur über `write` (immer mit confirm: true, das Backend prüft und kann mit „kill“ ablehnen). Gerätenamen, Wake Words und Hinweise
// sind reiner Text. Schlüssel, Token oder Anmeldedaten kommen hier nie an und werden nie gezeigt.
import { useCallback, useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import type { ApiClient, ApiReply } from "../lib/api";
import { FolderManager } from "./FolderManager";
import { IconCheck, IconWarn } from "./Icons";

export type Call = (type: string, data?: Record<string, unknown>) => Promise<ApiReply>;

export interface StepCtx {
  read: Call;                                         // nur lesen
  write: Call;                                        // schreiben: confirm: true, Notaus und Neustart meldet der Rahmen
  locked: boolean;                                    // Notaus aktiv: alles Schreibende ist aus
  say: (text: string) => void;                        // ruhige Meldung im Schritt
  done: (step: string) => Promise<void>;              // Schritt als erledigt bestätigen (setup.done)
}

export const NO_VOICE = "Starte kushim mit Sprache, dann geht der Test.";
const VOICE_POLL_MS = 250;
const LEVEL_POLL_MS = 500;
const LEVEL_DEADLINE_MS = 60_000;
export const WAKE_TEST_S = 10;
const de = (n: number, digits = 0) => n.toLocaleString("de-DE", { maximumFractionDigits: digits, minimumFractionDigits: digits });
/** Lange Zeichenketten ohne Leerzeichen (wie Token oder Schlüssel) erscheinen nie im Fenster, auch wenn das Backend sie liefert. */
export const redact = (s: string) => s.replace(/[A-Za-z0-9_\-+/=]{32,}/g, "[verborgen]");
const text = (x: unknown, max = 200) => (typeof x === "string" ? redact(x.slice(0, max)) : "");
/** Gerätenamen nie schwärzen: Sie gehen unverändert in audio.set zurück. Nur Länge begrenzen, angezeigt als Text. */
const deviceName = (x: unknown) => (typeof x === "string" ? x.slice(0, 200) : "");

/** Abfragen ruhen, solange niemand hinsieht: Fenster verdeckt oder kleines Fenster (E2 lässt die große Ansicht dann versteckt
 *  stehen, der Assistent behält Schritt und Entwürfe). */
export const paused = () => document.hidden || document.querySelector(".app.is-compact") !== null;

/* ----- Systemcheck und Claude: eine Liste aus setup.checks ----- */

export interface Check { id: string; label: string; ok: boolean; hint: string }

export function parseChecks(r: ApiReply): Check[] | null {
  if (!r.ok || !Array.isArray(r.checks)) return null;
  return r.checks.filter((c): c is Record<string, unknown> => !!c && typeof c === "object")
    .filter((c) => typeof c.id === "string" && typeof c.label === "string" && typeof c.ok === "boolean")
    .slice(0, 40)
    .map((c) => ({ id: text(c.id, 40), label: text(c.label), ok: c.ok === true, hint: text(c.hint, 300) }));
}

export const isClaudeCheck = (c: Check) => c.id.startsWith("claude");
/** Platzhalter, solange die erste Claude-Prüfung läuft: weder rot noch grün, Wort „wird geprüft“. */
export const isChecking = (c: Check) => c.id === "claude_checking";
const isVault = (c: Check) => c.id === "vault";

/** Was im eigenen Terminal zu tun ist. Die Oberfläche startet nichts davon selbst. */
function terminalHint(c: Check): ReactNode {
  if (isVault(c)) return <><code>kushim memory init</code> im eigenen Terminal</>;
  if (isClaudeCheck(c)) {
    if (/auth|login/.test(c.id)) return <><code>claude auth login</code> im eigenen Terminal</>;
    if (/version/.test(c.id)) return <><code>claude update</code> im eigenen Terminal</>;
    if (/install/.test(c.id)) return <>Claude Code installieren, danach <code>claude auth login</code> im eigenen Terminal</>;
  }
  return c.hint ? <>{c.hint}</> : null;
}

function CheckList({ checks }: { checks: Check[] }) {
  return (
    <ul className="sec-list setup-checks">
      {checks.map((c, i) => isChecking(c) ? (
        <li key={`${i}-${c.id}`} className="sec-row tone-open">
          <span className="setup-check-label">{c.label}</span>
          <span className="sec-val">wird geprüft</span>
        </li>
      ) : (
        <li key={`${i}-${c.id}`} className={`sec-row tone-${c.ok ? "ok" : "warn"}`}>
          <span className="setup-check-label">
            {c.label}
            {!c.ok && terminalHint(c) && <small className="setup-check-hint">Hinweis: {terminalHint(c)}</small>}
          </span>
          <span className="sec-val"><span aria-hidden="true" className="sec-icon">{c.ok ? <IconCheck /> : <IconWarn />}</span> {c.ok ? "in Ordnung" : "nicht in Ordnung"}</span>
        </li>
      ))}
    </ul>
  );
}

export type ChecksState = { list: Check[] | null; state: "loading" | "ready" | "unknown" | "error" };

function ChecksBody({ checks, pick, reload, empty }: { checks: ChecksState; pick: (c: Check) => boolean; reload: () => void; empty: string }) {
  const list = checks.list?.filter(pick) ?? [];
  return (
    <>
      {checks.state === "loading" && <p className="setup-text">Prüfe …</p>}
      {checks.state === "unknown" && <p className="setup-text">Dieser Dienst kennt den Systemcheck noch nicht. Im Terminal: <code>kushim doctor</code>.</p>}
      {checks.state === "error" && <p className="setup-text">Der Systemcheck hat nicht geantwortet. Versuch es noch einmal.</p>}
      {checks.state === "ready" && (list.length ? <CheckList checks={list} /> : <p className="setup-text">{empty}</p>)}
      <div className="setup-row"><button type="button" onClick={reload}>Erneut prüfen</button></div>
    </>
  );
}

export function SystemStep({ checks, reload }: { checks: ChecksState; reload: () => void }) {
  return (
    <>
      <p className="setup-text">Was kushim braucht: Pakete, Modelle, Grafikkarte, Notaus und Vault. Hier wird nur geprüft, nichts geändert.</p>
      <ChecksBody checks={checks} pick={(c) => !isClaudeCheck(c)} reload={reload} empty="Keine Prüfpunkte geliefert." />
    </>
  );
}

export function ClaudeStep({ checks, reload }: { checks: ChecksState; reload: () => void }) {
  return (
    <>
      <p className="setup-text">Claude Code ist das Gehirn von kushim: installiert, aktuell genug und angemeldet. Anmelden und Aktualisieren gehen nur im eigenen Terminal.</p>
      <ChecksBody checks={checks} pick={isClaudeCheck} reload={reload} empty="Keine Angaben zu Claude Code geliefert." />
    </>
  );
}

/* ----- Sprachdienst: Zustand, Pegel und Wake-Word-Zähler aus voice.state (nur Zahlen und Namen) ----- */

export interface VoiceInfo { known: boolean; active: boolean; level: number; wakeCount: number | null; wakeLast: string }

export function useVoice(read: Call): VoiceInfo {
  const [v, setV] = useState<VoiceInfo>({ known: false, active: false, level: 0, wakeCount: null, wakeLast: "" });
  useEffect(() => {
    let stop = false, busy = false;
    const pull = async () => {
      if (busy || paused()) return;
      busy = true;
      const r = await read("voice.state");
      busy = false;
      if (stop || !r.ok) return;
      const active = r.active === true;
      setV({ known: true, active,
        level: active && typeof r.level === "number" && Number.isFinite(r.level) ? Math.min(1, Math.max(0, r.level)) : 0,
        wakeCount: typeof r.wake_count === "number" && Number.isFinite(r.wake_count) ? r.wake_count : null,
        wakeLast: text(r.wake_last, 60) });
    };
    void pull();
    const id = setInterval(pull, VOICE_POLL_MS);
    return () => { stop = true; clearInterval(id); };
  }, [read]);
  return v;
}

/* ----- Mikrofon: Geräte merken, Pegel live, Pegeltest mit Vorschlag ----- */

const names = (x: unknown) => (Array.isArray(x) ? x.filter((n): n is string => typeof n === "string").slice(0, 64).map(deviceName) : []);

type Suggestion = { speech_level: number; barge_in_level: number };
type Level = { phase: "idle" | "starting" | "quiet" | "speak" | "done" | "unavailable"; left: number; sug: Suggestion | null };

function parseSuggestion(x: unknown): Suggestion | null {
  const s = x as Record<string, unknown> | null;
  if (!s || typeof s !== "object") return null;
  const a = s.speech_level, b = s.barge_in_level;
  return typeof a === "number" && typeof b === "number" && Number.isFinite(a) && Number.isFinite(b) && a > 0 && b > 0
    ? { speech_level: Math.round(a), barge_in_level: Math.round(b) } : null;
}

function DeviceSelect({ label, value, list, onPick }: { label: string; value: string; list: string[]; onPick: (v: string) => void }) {
  const all = value && !list.includes(value) ? [value, ...list] : list;
  return (
    <label>{label}
      <select value={value} onChange={(e) => onPick(e.target.value)}>
        <option value="">Systemstandard</option>
        {all.map((n) => <option key={n} value={n}>{list.includes(n) ? n : `${n} (nicht gefunden)`}</option>)}
      </select>
    </label>
  );
}

export function MicStep({ ctx }: { ctx: StepCtx }) {
  const { read, write, locked, say } = ctx;
  const voice = useVoice(read);
  const [inputs, setInputs] = useState<string[]>([]);
  const [outputs, setOutputs] = useState<string[]>([]);
  const [devNo, setDevNo] = useState(false);
  const [saved, setSaved] = useState({ mic: "", out: "" });
  const [pick, setPick] = useState({ mic: "", out: "" });
  const [lv, setLv] = useState<Level>({ phase: "idle", left: 0, sug: null });

  useEffect(() => {
    let stop = false;
    void (async () => {
      const d = await read("audio.devices");
      if (stop) return;
      if (d.ok) { setInputs(names(d.inputs)); setOutputs(names(d.outputs)); } else setDevNo(true);
      const g = await read("audio.get");
      if (!stop && g.ok) { const s = { mic: deviceName(g.mic), out: deviceName(g.out) }; setSaved(s); setPick(s); }
    })();
    return () => { stop = true; };
  }, [read]);

  const save = async () => {
    const r = await write("audio.set", { mic: pick.mic, out: pick.out });
    if (r.ok) { setSaved(pick); say("Auswahl gespeichert."); }
  };

  const running = lv.phase === "starting" || lv.phase === "quiet" || lv.phase === "speak";
  useEffect(() => {                                   // Pegeltest: Ergebnis abfragen, bis er fertig ist (höchstens 60 s)
    if (!running) return;
    let stop = false, busy = false, seen = false;
    const until = Date.now() + LEVEL_DEADLINE_MS;
    const pull = async () => {
      if (busy) return;
      if (Date.now() > until) { setLv({ phase: "idle", left: 0, sug: null }); say("Der Test hat nicht geantwortet. Versuch es noch einmal."); return; }
      if (paused()) return;
      busy = true;
      const r = await read("voice.level_result");
      busy = false;
      if (stop || !r.ok) return;
      const left = typeof r.seconds_left === "number" && Number.isFinite(r.seconds_left) ? Math.max(0, Math.ceil(r.seconds_left)) : 0;
      if (r.state === "quiet" || r.state === "speak") { seen = true; setLv({ phase: r.state, left, sug: null }); }
      else if (r.state === "done") {
        const sug = parseSuggestion(r.suggestion);
        setLv({ phase: sug ? "done" : "idle", left: 0, sug });
        if (!sug) say("Kein Vorschlag: zu wenig Sprache erkannt. Versuch es noch einmal.");
      }
      else if (r.state === "unavailable") setLv({ phase: "unavailable", left: 0, sug: null });
      else if (r.state === "idle" && seen) { setLv({ phase: "idle", left: 0, sug: null }); say("Der Test wurde ohne Ergebnis beendet. Versuch es noch einmal."); }
    };
    void pull();
    const id = setInterval(pull, LEVEL_POLL_MS);
    return () => { stop = true; clearInterval(id); };
  }, [running, read, say]);

  const startTest = async () => {
    const r = await write("voice.level_test");
    if (r.ok) setLv({ phase: "starting", left: 0, sug: null });
    else if (r.error === "unavailable") { say(""); setLv({ phase: "unavailable", left: 0, sug: null }); }   // der Satz steht schon beim Pegel
  };
  const apply = async () => {
    if (!lv.sug) return;
    const r = await write("voice.level_apply", { speech_level: lv.sug.speech_level, barge_in_level: lv.sug.barge_in_level });
    if (r.ok) say("Pegel übernommen.");
  };

  const pct = Math.round(voice.level * 100);
  const noVoice = (voice.known && !voice.active) || lv.phase === "unavailable";
  const dirty = pick.mic !== saved.mic || pick.out !== saved.out;
  const phaseText = lv.phase === "starting" ? "Test startet …"
    : lv.phase === "quiet" ? `Bitte still sein … ${lv.left}`
    : lv.phase === "speak" ? `Jetzt sprechen … ${lv.left}` : "";

  return (
    <>
      <div className="setup-block">
        <h4>Geräte</h4>
        {devNo && <p className="setup-text">Die Geräteliste ist gerade nicht verfügbar. Es gelten die Windows-Standardgeräte.</p>}
        <fieldset className="setup-fields" disabled={locked}>
          <DeviceSelect label="Mikrofon" value={pick.mic} list={inputs} onPick={(mic) => setPick((p) => ({ ...p, mic }))} />
          <DeviceSelect label="Lautsprecher" value={pick.out} list={outputs} onPick={(out) => setPick((p) => ({ ...p, out }))} />
          <div className="setup-row"><button type="button" disabled={locked || !dirty} onClick={() => void save()}>Auswahl speichern</button></div>
        </fieldset>
      </div>
      <div className="setup-block">
        <h4>Pegel</h4>
        <div className="setup-meter-row">
          <div className="track setup-meter" role="meter" aria-label="Mikrofonpegel" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}
            aria-valuetext={voice.active ? `${pct} Prozent` : "kein Sprachdienst"}>
            <div className="fill" style={{ width: `${pct}%` }} />
          </div>
          <span className="setup-num">{voice.active ? `${pct} %` : "kein Signal"}</span>
        </div>
        {noVoice && <p className="setup-text">{NO_VOICE}</p>}
        <p className="setup-big" aria-live="polite">{phaseText}</p>
        {lv.phase === "done" && lv.sug && (
          <div className="setup-sug">
            <p className="setup-text">Vorschlag: Sprechen ab {de(lv.sug.speech_level)}, Unterbrechen ab {de(lv.sug.barge_in_level)}.</p>
            <button type="button" className="primary" disabled={locked} onClick={() => void apply()}>Übernehmen</button>
          </div>
        )}
        <div className="setup-row">
          <button type="button" disabled={locked || running || noVoice} onClick={() => void startTest()}>Pegeltest starten</button>
        </div>
      </div>
      <div className="setup-row">
        <button type="button" disabled={locked} onClick={() => void ctx.done("audio_voice")}>Mikrofon passt</button>
      </div>
    </>
  );
}

/* ----- Wake Words: Schalter, hinzufügen, entfernen, speichern, testen ----- */

export interface Word { phrase: string; enabled: boolean }
const PHRASE = /^[a-zäöüß]+( [a-zäöüß]+){0,3}$/;

/** Prüft ein neues Wort wie das Backend (wakeconfig.validate): klein, 3 bis 40 Zeichen, nur Buchstaben, keine Dopplung, höchstens max. */
export function checkPhrase(raw: string, words: Word[], max: number): { ok: true; phrase: string } | { ok: false; why: string } {
  const p = raw.trim().toLowerCase().split(/\s+/).filter(Boolean).join(" ");
  if (!p) return { ok: false, why: "Bitte ein Wort eingeben." };
  if (words.length >= max) return { ok: false, why: `Höchstens ${max} Wake Words. Entferne erst eines.` };
  if (p.length > 40) return { ok: false, why: "Zu lang: höchstens 40 Zeichen." };
  if (p.length < 3) return { ok: false, why: "Zu kurz: mindestens 3 Zeichen." };
  if (!PHRASE.test(p)) return { ok: false, why: "Nur Buchstaben und Leerzeichen, höchstens vier Wörter." };
  if (words.some((w) => w.phrase === p)) return { ok: false, why: `„${p}“ steht schon in der Liste.` };
  return { ok: true, phrase: p };
}

function parseWords(x: unknown): Word[] {
  return Array.isArray(x) ? x.filter((w): w is Record<string, unknown> => !!w && typeof w === "object")
    .filter((w) => typeof w.phrase === "string" && typeof w.enabled === "boolean")
    // Wake Words nie schwärzen (wie Gerätenamen): Sie gehen unverändert in wake.set zurück (Audit 2026-11-23).
    .slice(0, 40).map((w) => ({ phrase: deviceName(w.phrase).slice(0, 60), enabled: w.enabled === true })) : [];
}

const LAST_ON = "Mindestens ein Wake Word muss aktiv bleiben.";

export function WakeStep({ ctx }: { ctx: StepCtx }) {
  const { read, write, locked, say } = ctx;
  const voice = useVoice(read);
  const [saved, setSaved] = useState<Word[]>([]);
  const [draft, setDraft] = useState<Word[]>([]);
  const [max, setMax] = useState(12);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [input, setInput] = useState("");
  const [why, setWhy] = useState("");
  const [test, setTest] = useState<{ phase: "idle" | "run" | "hit" | "miss"; left: number; base: number; word: string }>({ phase: "idle", left: 0, base: 0, word: "" });

  useEffect(() => {
    let stop = false;
    void (async () => {
      const r = await read("wake.get");
      if (stop) return;
      if (!r.ok) return setState("error");
      const w = parseWords(r.words);
      setSaved(w); setDraft(w);
      if (typeof r.max === "number" && Number.isInteger(r.max) && r.max > 0 && r.max <= 40) setMax(r.max);
      setState("ready");
    })();
    return () => { stop = true; };
  }, [read]);

  const onCount = draft.filter((w) => w.enabled).length;
  const toggle = (i: number) => {
    const w = draft[i];
    if (w.enabled && onCount <= 1) return setWhy(LAST_ON);
    setWhy("");
    setDraft(draft.map((x, j) => (j === i ? { ...x, enabled: !x.enabled } : x)));
  };
  const remove = (i: number) => {
    const w = draft[i];
    if (w.enabled && onCount <= 1) return setWhy(LAST_ON);
    setWhy("");
    setDraft(draft.filter((_, j) => j !== i));
  };
  const add = () => {
    const c = checkPhrase(input, draft, max);
    if (!c.ok) return setWhy(c.why);
    setWhy("");
    setInput("");
    setDraft([...draft, { phrase: c.phrase, enabled: true }]);
  };
  const save = async () => {
    const r = await write("wake.set", { words: draft.map((w) => ({ phrase: w.phrase, enabled: w.enabled })) });
    if (r.ok) {
      const back = parseWords(r.words);
      const now = back.length ? back : draft;
      setSaved(now); setDraft(now);
      say("Wake Words gespeichert.");
    }
  };

  // Test: 10 s lang auf einen steigenden Zähler wake_count achten (nur lesen, nichts wird gesendet außer voice.state).
  const running = test.phase === "run";
  useEffect(() => {
    if (!running) return;
    const t0 = Date.now();
    const id = setInterval(() => {
      const left = Math.max(0, WAKE_TEST_S - Math.floor((Date.now() - t0) / 1000));
      setTest((t) => (t.phase !== "run" ? t : left <= 0 ? { ...t, phase: "miss", left: 0 } : { ...t, left }));
    }, 250);
    return () => clearInterval(id);
  }, [running]);
  useEffect(() => {
    if (running && voice.wakeCount !== null && voice.wakeCount > test.base) setTest((t) => ({ ...t, phase: "hit", word: voice.wakeLast }));
  }, [running, voice.wakeCount, voice.wakeLast, test.base]);

  const noVoice = voice.known && !voice.active;
  const noCounter = voice.known && voice.active && voice.wakeCount === null;
  const startTest = async () => {                     // Ausgangswert frisch lesen: was vor dem Start erkannt wurde, zählt nicht
    const r = await read("voice.state");
    const base = r.ok && typeof r.wake_count === "number" && Number.isFinite(r.wake_count) ? r.wake_count : null;
    if (base === null) return say(r.ok && r.active === true ? "Der Sprachdienst meldet keine erkannten Wörter. Starte kushim neu, dann geht der Test." : NO_VOICE);
    setTest({ phase: "run", left: WAKE_TEST_S, base, word: "" });
  };
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);

  return (
    <>
      <div className="setup-block">
        <h4>Wörter <span className="label">{draft.length} von {max}, {onCount} aktiv</span></h4>
        {state === "loading" && <p className="setup-text">Lade die Wake Words …</p>}
        {state === "error" && <p className="setup-text">Die Wake Words sind gerade nicht lesbar. Es gelten die Wörter aus <code>wakewords.toml</code>.</p>}
        <fieldset className="setup-fields" disabled={locked || state !== "ready"}>
          <ul className="setup-words">
            {draft.map((w, i) => (
              <li key={w.phrase}>
                <label className="setup-switch">
                  <input type="checkbox" role="switch" checked={w.enabled} onChange={() => toggle(i)} />
                  <span className="setup-phrase">{w.phrase}</span>
                </label>
                <span className={`setup-word ${w.enabled ? "is-on" : ""}`}>{w.enabled ? "aktiv" : "aus"}</span>
                <button type="button" aria-label={`Entfernen: ${w.phrase}`} onClick={() => remove(i)}>Entfernen</button>
              </li>
            ))}
          </ul>
          <form className="cl-form setup-add" onSubmit={(e) => { e.preventDefault(); add(); }}>
            <label>Neues Wake Word
              <input value={input} onChange={(e) => setInput(e.target.value)} maxLength={80} autoComplete="off" spellCheck={false} />
            </label>
            <button type="submit">Hinzufügen</button>
          </form>
          {why && <p className="setup-why" role="status">{why}</p>}
          <div className="setup-row"><button type="button" disabled={locked || !dirty} onClick={() => void save()}>Wake Words speichern</button></div>
        </fieldset>
      </div>
      <div className="setup-block">
        <h4>Test</h4>
        {noVoice && <p className="setup-text">{NO_VOICE}</p>}
        {noCounter && <p className="setup-text">Der Sprachdienst meldet keine erkannten Wörter. Starte kushim neu, dann geht der Test.</p>}
        <p className="setup-big" aria-live="polite">
          {test.phase === "run" ? `Sag jetzt ein Wake Word … ${test.left}`
            : test.phase === "hit" ? `erkannt: ${test.word || "unbekannt"}`
            : test.phase === "miss" ? `nichts erkannt in ${WAKE_TEST_S} s` : ""}
        </p>
        <div className="setup-row">
          <button type="button" disabled={running || noVoice || noCounter || !voice.known} onClick={() => void startTest()}>Wake Word testen</button>
        </div>
      </div>
      <div className="setup-row">
        <button type="button" disabled={locked} onClick={() => void ctx.done("wake_words")}>Wörter passen</button>
      </div>
    </>
  );
}

/* ----- Arbeitsordner: der vorhandene FolderManager (claude.folder_*) ----- */

export function FolderStep({ client, connected, locked, say }: { client: RefObject<ApiClient | null>; connected: boolean; locked: boolean; say: (t: string) => void }) {
  const onChange = useCallback((m?: string) => { if (m) say(m); }, [say]);
  return (
    <>
      <p className="setup-text">Claude arbeitet nur in Git-Ordnern, die du hier freigibst. Jede Freigabe zeigt vorher den genauen Pfad.</p>
      <fieldset className="setup-fields" disabled={locked}>
        <FolderManager client={client} connected={connected} onChange={onChange} />
      </fieldset>
    </>
  );
}

/* ----- Sicherheit: nur erklären, „verstanden“ (kein echter Notaus) ----- */

export function SafetyStep({ ctx }: { ctx: StepCtx }) {
  const once = useRef(false);
  return (
    <>
      <ul className="setup-rules">
        <li>Der <strong>NOTAUS</strong>-Knopf steht oben rechts in jedem Fenster. Ein Klick stoppt alle Dienste, ohne Rückfrage.</li>
        <li>Tastenkürzel: <kbd>Strg</kbd>+<kbd>Umschalt</kbd>+<kbd>K</kbd>, solange dieses Fenster den Fokus hat.</li>
        <li>Aufheben ist ein eigener Schritt mit Bestätigung.</li>
        <li>Es gibt keine Sprecher-Prüfung: Jede Stimme im Raum kann Befehle geben.</li>
        <li>Freigaben gibt es deshalb nie per Stimme, nur im Claude-Terminal oder in der Freigabe-Leiste dieses Fensters.</li>
        <li>Überspringen ändert nie eine Sicherheitsregel.</li>
      </ul>
      <p className="setup-text">Hier wird der Notaus nur erklärt, nicht ausgelöst.</p>
      <div className="setup-row">
        <button type="button" className="primary" disabled={ctx.locked}
          onClick={() => { if (!once.current) { once.current = true; void ctx.done("safety").finally(() => { once.current = false; }); } }}>verstanden</button>
      </div>
    </>
  );
}
