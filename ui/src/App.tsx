import { useCallback, useEffect, useRef, useState } from "react";
import { ApprovalBar, type Pending } from "./components/ApprovalBar";
import { Avatar } from "./components/Avatar";
import { ClaudePanel } from "./components/ClaudePanel";
import { Dashboard, type DashData } from "./components/Dashboard";
import { MemoryPanel } from "./components/MemoryPanel";
import { SecurityPanel, type Overview } from "./components/SecurityPanel";
import { Transcript, type Entry } from "./components/Transcript";
import { HaltedBanner, KillButton } from "./components/KillButton";
import { ApiClient, type Credentials } from "./lib/api";
import { isAvatarState, resolveState, STATE_VIEW, type AvatarState } from "./lib/avatarState";
import { MockSocket } from "./lib/mock";

const WHY: Record<string, string> = {
  offline: "kein laufender Dienst gefunden (run/api.json fehlt oder ist nicht lesbar)",
  bad_file: "run/api.json ist beschädigt",
  "ws-connect": "Verbindung zum Dienst auf 127.0.0.1 fehlgeschlagen (Dienst beendet oder Verbindung gesperrt)",
  "no-credentials": "keine Zugangsdaten (nur in der App oder mit ?mock)",
};

const POLL_MS = 2000;
const VOICE_POLL_MS = 200;

export type Loader = () => Promise<{ client: ApiClient }>;

/** Echte Zugangsdaten kommen vom Tauri-Rustteil (liest run/api.json). Ohne Tauri: nur mit ?mock das gefälschte Backend. */
export async function defaultLoader(): Promise<{ client: ApiClient }> {
  const inTauri = "__TAURI_INTERNALS__" in window;
  if (!inTauri) {
    if (!new URLSearchParams(location.search).has("mock")) throw new Error("no-credentials");
    return { client: new ApiClient({ port: 1, token: "t".repeat(43) }, (u) => new MockSocket(u)) };
  }
  const { invoke } = await import("@tauri-apps/api/core");
  const creds = await invoke<Credentials>("api_info");
  return { client: new ApiClient(creds) };
}

export function App({ load = defaultLoader }: { load?: Loader }) {
  const [connected, setConnected] = useState(false);
  const [kill, setKill] = useState<boolean | null>(null);
  const [voice, setVoice] = useState<{ active: boolean; state?: AvatarState; level: number }>({ active: false, level: 0 });
  const [pending, setPending] = useState<Pending | null>(null);
  const [toast, setToast] = useState("");
  const [why, setWhy] = useState("");
  const [view, setView] = useState<"home" | "dashboard" | "security" | "memory">("home");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [dash, setDash] = useState<DashData | null>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const lastId = useRef(0);
  const [rated, setRated] = useState<Record<number, 1 | -1>>({});
  const client = useRef<ApiClient | null>(null);

  const refresh = useCallback(async () => {
    const c = client.current;
    if (!c) return;
    const r = await c.call("safety.status");
    if (r.ok) { setConnected(true); setKill(r.kill === true); }
    else if (r.error === "offline" || r.error === "timeout") setConnected(false);
  }, []);

  const connect = useCallback(async () => {
    try {
      client.current?.close();
      const { client: c } = await load();
      c.onDisconnect = () => setConnected(false);
      await c.connect();
      client.current = c;
      await refresh();
    } catch (e) {
      setConnected(false);
      const msg = e instanceof Error ? e.message : typeof e === "string" ? e : "unbekannt";
      setWhy(/^[a-z_-]{1,30}$/.test(msg) ? msg : "unbekannt");     // nur kurze feste Codes, nie Text oder Pfade
    }
  }, [load, refresh]);

  useEffect(() => { void connect(); return () => client.current?.close(); }, [connect]);
  useEffect(() => {
    const id = setInterval(() => { if (connected) void refresh(); }, POLL_MS);
    return () => clearInterval(id);
  }, [connected, refresh]);

  useEffect(() => {                                     // Zustand und Pegel der Sprach-Pipeline (nur Zahlen und Namen)
    if (!connected) { setVoice({ active: false, level: 0 }); return; }
    let busy = false;
    const id = setInterval(async () => {
      if (busy || document.hidden) return;              // verdeckt: nicht abfragen
      busy = true;
      const r = await client.current?.call("voice.state");
      busy = false;
      if (r?.ok && r.active === true && isAvatarState(r.state)) {
        const level = typeof r.level === "number" ? Math.min(1, Math.max(0, r.level)) : 0;
        setVoice({ active: true, state: r.state, level });
      } else if (r?.ok) setVoice({ active: false, level: 0 });
    }, VOICE_POLL_MS);
    return () => clearInterval(id);
  }, [connected]);

  useEffect(() => {                                     // Freigabe nur abfragen, solange das Backend eine meldet
    if (!connected || voice.state !== "asking") { setPending(null); return; }
    let stop = false;
    const get = async () => {
      const r = await client.current?.call("approvals.get");
      if (stop || !r?.ok) return;
      const p = r.pending as Pending | null;
      setPending((old) => (p && old && old.digest === p.digest ? old : p));   // gleiche Freigabe: Zähler nicht zurücksetzen
    };
    void get();
    const id = setInterval(get, 1000);
    return () => { stop = true; clearInterval(id); };
  }, [connected, voice.state]);

  useEffect(() => {                                     // Verlauf: nur neue Einträge, nicht bei verdecktem Fenster
    if (!connected) return;
    let stop = false, busy = false;
    const pull = async () => {
      if (busy || document.hidden) return;
      busy = true;
      const r = await client.current?.call("transcript.get", { since: lastId.current });
      busy = false;
      if (stop || !r?.ok || !Array.isArray(r.entries) || r.entries.length === 0) return;
      const fresh = (r.entries as Entry[]).filter((e) => typeof e.id === "number" && e.id > lastId.current);
      if (fresh.length === 0) return;
      lastId.current = Math.max(...fresh.map((e) => e.id));
      setEntries((old) => [...old, ...fresh].slice(-20));
    };
    void pull();
    const id = setInterval(pull, 1000);
    return () => { stop = true; clearInterval(id); };
  }, [connected]);

  useEffect(() => {                                     // Sicherheitsstatus: immer (Modus C bleibt sichtbar), selten abfragen
    if (!connected) { setOverview(null); return; }
    let stop = false;
    const pull = async () => {
      if (document.hidden) return;
      const r = await client.current?.call("safety.overview");
      if (!stop && r?.ok && typeof r.mode === "string") setOverview(r as unknown as Overview);
    };
    void pull();
    const id = setInterval(pull, view === "security" ? 3000 : 10000);
    return () => { stop = true; clearInterval(id); };
  }, [connected, view]);

  useEffect(() => {                                     // Übersicht nur abfragen, solange sie offen ist
    if (!connected || view !== "dashboard") return;
    let stop = false;
    const pull = async () => {
      if (document.hidden) return;
      const r = await client.current?.call("dashboard.get");
      if (!stop && r?.ok && Array.isArray(r.timers)) setDash(r as unknown as DashData);
    };
    void pull();
    const id = setInterval(pull, 2000);
    return () => { stop = true; clearInterval(id); };
  }, [connected, view]);

  const rate = useCallback(async (id: number, rating: 1 | -1) => {
    const r = await client.current?.call("feedback.add", { entry: id, rating });
    if (r?.ok || (r && !r.ok && r.error === "already_rated")) setRated((old) => ({ ...old, [id]: old[id] ?? rating }));
    else setToast("Die Bewertung konnte nicht gespeichert werden.");
  }, []);

  const decide = useCallback(async (approve: boolean) => {
    const p = pending;
    if (!p) return;
    setPending(null);                                   // nie doppelt absenden
    const r = await client.current?.call("approvals.decide", { approve, digest: p.digest, ...(approve ? { confirm: true } : {}) });
    if (r?.ok) setToast(approve ? "Erlaubt. Ich führe es aus." : "Abgelehnt. Es wurde nichts gesendet.");
    else setToast(r && !r.ok && r.error === "stale" ? "Die Vorschau hat sich geändert. Bitte neu prüfen."
      : "Nichts mehr zu entscheiden (abgelaufen oder erledigt).");
    setTimeout(() => setToast(""), 5000);
  }, [pending]);

  const doKill = useCallback(async () => {
    setKill(true);                                      // sofort sichtbar, das Backend bestätigt beim nächsten Abruf
    await client.current?.call("safety.kill");
    void refresh();
  }, [refresh]);
  const doResume = useCallback(async () => {
    await client.current?.call("safety.resume", { confirm: true });
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "k") { e.preventDefault(); void doKill(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [doKill]);

  const state = resolveState({ connected, killActive: kill, backendState: voice.active ? voice.state : undefined });
  const stateView = STATE_VIEW[state];

  return (
    <div className={`app ${state === "halted" ? "is-halted" : ""}`}>
      <header className="head">
        <img className="logo" src="/kushim.png" alt="" width={28} height={28} />
        <span className="brand">kushim</span>
        <span className="status" aria-live={stateView.live}>{stateView.label}</span>
        {overview?.mode === "C" && <span className="chip mode-c" title="Claude ist erlaubt: freigegebene Texte gehen an Anthropic">Modus C</span>}
        <KillButton onKill={() => void doKill()} />
      </header>
      <nav className="tabs" aria-label="Bereiche">
        <button type="button" aria-pressed={view === "home"} onClick={() => setView("home")}>Start</button>
        <button type="button" aria-pressed={view === "dashboard"} onClick={() => setView("dashboard")}>Übersicht</button>
        <button type="button" aria-pressed={view === "memory"} onClick={() => setView("memory")}>Gedächtnis</button>
        <button type="button" aria-pressed={view === "security"} onClick={() => setView("security")}>Sicherheit</button>
      </nav>
      {state === "halted" && <HaltedBanner onResume={() => void doResume()} />}
      {pending && state === "asking" && <ApprovalBar pending={pending} onDecide={(a) => void decide(a)} />}
      <div className="toast" role="status" aria-live="polite">{toast}</div>
      <main className="stage" hidden={view !== "memory"}>
        <MemoryPanel client={client} connected={connected} active={view === "memory"} />
      </main>
      {view === "dashboard" && <main className="stage"><Dashboard data={dash} overview={overview} /></main>}
      {view === "security" ? (
        <main className="stage"><SecurityPanel overview={overview} /></main>
      ) : view === "home" && (
      <main className="stage">
        <Avatar state={state} size={240} level={voice.level} />
        <p className="line">{stateView.label}</p>
        {connected && <Transcript entries={entries} rated={rated} onRate={(id, r) => void rate(id, r)} />}
        <ClaudePanel client={client} connected={connected} />
        {connected && !voice.active && state === "idle" && (
          <p className="hint">Der Sprachdienst läuft nicht. Starte ihn mit „kushim talk“.</p>
        )}
        {state === "offline" && why && <p className="hint">Grund: {WHY[why] ?? why}</p>}
        {state === "offline" && (
          <button type="button" className="primary" onClick={() => void connect()}>Erneut versuchen</button>
        )}
      </main>
      )}
    </div>
  );
}
