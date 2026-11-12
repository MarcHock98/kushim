import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { flushSync } from "react-dom";
import { PermissionBar, type PermissionRequest } from "./components/PermissionBar";
import { Core3D } from "./components/Core3D";
import { FolderPanel } from "./components/FolderPanel";
import { Dashboard, type DashData } from "./components/Dashboard";
import { MemoryPanel } from "./components/MemoryPanel";
import { SecurityPanel, type Overview } from "./components/SecurityPanel";
import { parseSystem, type SysData } from "./components/SystemPanel";
import { ViewCard, ViewTabs } from "./components/stage/ViewCard";
import { ART_LABEL, hasSystem, parseItem, type View as StageView } from "./lib/stage";
import { Transcript, type Entry } from "./components/Transcript";
import { IconHome, IconMemory, IconOverview, IconShield } from "./components/Icons";
import { HaltedBanner, KillButton } from "./components/KillButton";
import { ApiClient, type Credentials } from "./lib/api";
import { isAvatarState, resolveState, STATE_VIEW, type AvatarState } from "./lib/avatarState";
import { MockSocket } from "./lib/mock";
import { avatarSize, coreSmall, useBoxSize } from "./lib/useBoxSize";

const WHY: Record<string, string> = {
  offline: "kein laufender Dienst gefunden (run/api.json fehlt oder ist nicht lesbar)",
  bad_file: "run/api.json ist beschädigt",
  "ws-connect": "Verbindung zum Dienst auf 127.0.0.1 fehlgeschlagen (Dienst beendet oder Verbindung gesperrt)",
  "no-credentials": "keine Zugangsdaten (nur in der App oder mit ?mock)",
};

type View = "home" | "dashboard" | "security" | "memory";

const POLL_MS = 2000;
const VOICE_POLL_MS = 200;
const SYSTEM_POLL_MS = 3000;
const STAGE_POLL_MS = 1000;

/** Welche Ansicht die Bühne gerade zeigt (id). Im reinen Gespräch keine: dann steht nur der Kern groß in der Mitte.
 *  Was gezeigt wird, entscheidet Claude Code über das Werkzeug `zeige` (stage.get), nie die Oberfläche selbst. */
type Shown = string | null;

/** Bühnenwechsel mit Animation (View Transitions in WebView2/Chromium); ohne Unterstützung oder bei weniger Bewegung sofort. */
function staged(change: () => void): void {
  const doc = document as Document & { startViewTransition?: (cb: () => void) => unknown };
  const calm = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (doc.startViewTransition && !calm) doc.startViewTransition(() => flushSync(change));
  else change();
}

export type Loader = () => Promise<{ client: ApiClient }>;

/** Echte Zugangsdaten kommen vom Tauri-Rustteil (liest run/api.json). Ohne Tauri: nur mit ?mock das gefälschte Backend. */
export async function defaultLoader(): Promise<{ client: ApiClient }> {
  const inTauri = "__TAURI_INTERNALS__" in window;
  if (!inTauri) {
    if (!new URLSearchParams(location.search).has("mock")) throw new Error("no-credentials");
    const demo = new URLSearchParams(location.search).has("demo");
    return { client: new ApiClient({ port: 1, token: "t".repeat(43) }, (u) => { const m = new MockSocket(u); if (demo) m.demo(); return m; }) };
  }
  const { invoke } = await import("@tauri-apps/api/core");
  const creds = await invoke<Credentials>("api_info");
  return { client: new ApiClient(creds) };
}

const isRequest = (x: unknown): x is PermissionRequest => {       // Antwort des Backends prüfen, nicht blind vertrauen
  const r = x as Record<string, unknown> | null;
  return !!r && typeof r.request_id === "string" && typeof r.digest === "string" && typeof r.tool_name === "string"
    && typeof r.description === "string" && typeof r.input_preview === "string" && typeof r.summary === "string";
};

export function App({ load = defaultLoader }: { load?: Loader }) {
  const [connected, setConnected] = useState(false);
  const [kill, setKill] = useState<boolean | null>(null);
  const [voice, setVoice] = useState<{ active: boolean; state?: AvatarState; level: number }>({ active: false, level: 0 });
  const [pending, setPending] = useState<PermissionRequest[]>([]);
  const [toast, setToast] = useState("");
  const [why, setWhy] = useState("");
  const [view, setView] = useState<View>("home");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [dash, setDash] = useState<DashData | null>(null);
  const [dashNo, setDashNo] = useState(false);
  const [sys, setSys] = useState<SysData | null>(null);
  const [sysNo, setSysNo] = useState(false);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [shown, setShown] = useState<Shown>(null);           // Bühne: null = Dialog (nur Kern), sonst Zeige-Modus
  const [views, setViews] = useState<StageView[]>([]);        // von Claude gezeigt (älteste zuerst, höchstens 20)
  const stageSeq = useRef(0);
  const lastId = useRef(0);
  const [rated, setRated] = useState<Record<number, 1 | -1>>({});
  const client = useRef<ApiClient | null>(null);
  const viewRef = useRef<HTMLElement | null>(null);
  const box = useBoxSize(viewRef);

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

  useEffect(() => {                                     // offene Freigaben von Claude Code abfragen (nur anzeigen, nie selbst entscheiden)
    if (!connected) { setPending([]); return; }
    let stop = false;
    const get = async () => {
      const r = await client.current?.call("approvals.get");
      if (stop || !r?.ok) return;
      const p = (Array.isArray(r.pending) ? r.pending : []).filter(isRequest);
      setPending((old) => (old.length === p.length && old.every((o, i) => o.digest === p[i].digest) ? old : p));
    };
    void get();
    const id = setInterval(get, 1000);
    return () => { stop = true; clearInterval(id); };
  }, [connected]);

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

  useEffect(() => {                                     // Sicherheitsstatus: selten abfragen
    if (!connected) { setOverview(null); return; }
    let stop = false;
    const pull = async () => {
      if (document.hidden) return;
      const r = await client.current?.call("safety.overview");
      if (!stop && r?.ok && typeof r.kill === "boolean") setOverview(r as unknown as Overview);
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
      else if (!stop && r && !r.ok && r.error === "unknown_type") setDashNo(true);       // dieser Dienst hat keine Übersicht (ohne Sprachdienst)
    };
    void pull();
    const id = setInterval(pull, 2000);
    return () => { stop = true; clearInterval(id); };
  }, [connected, view]);

  useEffect(() => {                                     // Systemzustand nur abfragen, solange er gezeigt wird und das Fenster sichtbar ist
    if (!connected || view !== "home" || !hasSystem(views.find((v) => v.id === shown))) return;
    let stop = false;
    const pull = async () => {
      if (document.hidden) return;
      const r = await client.current?.call("system.stats");
      if (stop || !r) return;
      if (r.ok) { setSys(parseSystem(r)); setSysNo(false); }
      else if (r.error === "unknown_type") setSysNo(true);                    // älterer Dienst ohne Systemwerte
    };
    void pull();
    const id = setInterval(pull, SYSTEM_POLL_MS);
    return () => { stop = true; clearInterval(id); };
  }, [connected, view, shown, views]);

  useEffect(() => {                                     // Ansichten von Claude (zeige): neue öffnen die Bühne, schliessen räumt ab
    if (!connected) return;
    let stop = false, busy = false;
    const pull = async () => {
      if (busy || document.hidden) return;
      busy = true;
      const r = await client.current?.call("stage.get", { since: stageSeq.current });
      busy = false;
      if (stop || !r?.ok || !Array.isArray(r.items)) return;
      if (typeof r.last === "number") stageSeq.current = Math.max(stageSeq.current, r.last);
      const items = r.items.map(parseItem).filter((i) => i !== null);
      if (items.length === 0) return;
      let open: string | null = null;
      const closed = new Set<string>();
      for (const it of items) { if ("schliessen" in it) closed.add(it.id); else open = it.id; }
      setViews((old) => {
        let next = [...old];
        for (const it of items) {
          next = next.filter((v) => v.id !== it.id);
          if (!("schliessen" in it)) next.push(it);
        }
        return next.slice(-20);
      });
      staged(() => setShown((cur) => open ?? (cur && closed.has(cur) ? null : cur)));
    };
    void pull();
    const id = setInterval(pull, STAGE_POLL_MS);
    return () => { stop = true; clearInterval(id); };
  }, [connected]);

  useEffect(() => {                                     // Notaus: Bühne abräumen, nichts mehr zeigen
    if (kill) { setShown(null); setViews([]); }
  }, [kill]);

  const rate = useCallback(async (id: number, rating: 1 | -1) => {
    const r = await client.current?.call("feedback.add", { entry: id, rating });
    if (r?.ok || (r && !r.ok && r.error === "already_rated")) setRated((old) => ({ ...old, [id]: old[id] ?? rating }));
    else setToast("Die Bewertung konnte nicht gespeichert werden.");
  }, []);

  const decide = useCallback(async (p: PermissionRequest, approve: boolean) => {
    // Entschieden wird genau für die angezeigte Anfrage (nie für die, die gerade nachrückt).
    if (!pending.some((o) => o.request_id === p.request_id && o.digest === p.digest)) return;
    setPending((old) => old.filter((o) => o.request_id !== p.request_id));   // nie doppelt absenden
    const r = await client.current?.call("approvals.decide", { request_id: p.request_id, approve, digest: p.digest, ...(approve ? { confirm: true } : {}) });
    if (r?.ok) setToast(approve ? "Erlaubt. Claude Code macht weiter." : "Abgelehnt. Claude Code führt es nicht aus.");
    else setToast(r && !r.ok && r.error === "stale" ? "Die Anfrage hat sich geändert. Bitte neu prüfen."
      : r && !r.ok && r.error === "kill" ? "Notaus ist aktiv. Nichts wurde entschieden."
      : r && !r.ok && r.error === "terminal_only" ? "Der Text ist gekürzt. Erlauben bitte im Terminal."
      : "Nichts mehr zu entscheiden (erledigt oder Claude Code nicht erreichbar).");
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

  const closeShown = useCallback(() => staged(() => setShown(null)), []);
  const shownRef = useRef(shown);
  shownRef.current = shown;
  useEffect(() => {                                     // neue Frage: zurück zum Gespräch, der Kern kommt groß in die Mitte
    if (voice.active && voice.state === "listening" && shownRef.current) closeShown();
  }, [voice.active, voice.state, closeShown]);
  useEffect(() => {
    if (!shown) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !(e.target as HTMLElement | null)?.closest?.(".approval")) closeShown(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [shown, closeShown]);

  const shownView = views.find((v) => v.id === shown) ?? null;
  const state = resolveState({ connected, killActive: kill, backendState: pending.length > 0 ? "asking" : voice.active ? voice.state : undefined });
  const stateView = STATE_VIEW[state];

  const NAV: { id: View; label: string; icon: ReactNode }[] = [
    { id: "home", label: "Start", icon: <IconHome /> },
    { id: "dashboard", label: "Übersicht", icon: <IconOverview /> },
    { id: "memory", label: "Gedächtnis", icon: <IconMemory /> },
    { id: "security", label: "Sicherheit", icon: <IconShield /> },
  ];

  return (
    <div className={`app ${state === "halted" ? "is-halted" : ""}`}>
      <header className="head">
        <img className="logo" src="/kushim.png" alt="" width={28} height={28} />
        <span className="brand">kushim</span>
        <span className="label brand-sub">Sprachassistent</span>
        <span className="status" aria-live={stateView.live} title={stateView.label}>{stateView.label}</span>
        <KillButton onKill={() => void doKill()} />
      </header>
      <nav className="rail" aria-label="Bereiche">
        {NAV.map((n) => (
          <button key={n.id} type="button" aria-current={view === n.id ? "page" : undefined} onClick={() => setView(n.id)}>
            {n.icon}<span className="rail-label">{n.label}</span>
          </button>
        ))}
      </nav>
      <main className="view" ref={viewRef}>
        {state === "halted" && <HaltedBanner onResume={() => void doResume()} />}
        {pending.length > 0 && state === "asking" && <PermissionBar request={pending[0]} more={pending.length - 1} onDecide={(p, a) => void decide(p, a)} />}
        <div className="toast" role="status" aria-live="polite">{toast}</div>
        <div className="content">
          <MemoryPanel client={client} connected={connected} active={view === "memory"} />
          {view === "dashboard" && (
            <div className="overview">
              {connected && (
                <section className="panel overview-log" aria-labelledby="log-h">
                  <div className="panel-head"><h2 id="log-h">Verlauf</h2><span className="label">{entries.length} Einträge</span></div>
                  <Transcript entries={entries} rated={rated} onRate={(id, r) => void rate(id, r)} />
                </section>
              )}
              {views.length > 0 && (
                <section className="panel overview-shown" aria-labelledby="shown-h">
                  <div className="panel-head"><h2 id="shown-h">Gezeigt</h2><span className="label">{views.length} Ansichten</span></div>
                  <ul className="shown-list">
                    {[...views].reverse().map((v) => (
                      <li key={v.id}>
                        <span><span className="label">{ART_LABEL[v.art]}</span> {v.titel}{v.stand && <small> · Stand: {v.stand}</small>}</span>
                        <button type="button" onClick={() => { setView("home"); staged(() => setShown(v.id)); }}>Zeigen</button>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
              <aside className="overview-claude" aria-label="Claude">
                <FolderPanel client={client} connected={connected} />
              </aside>
              <div className="overview-dash"><Dashboard data={dash} overview={overview} unavailable={dashNo} /></div>
            </div>
          )}
          {view === "security" && <SecurityPanel overview={overview} />}
          {view === "home" && (
            <section className="stage" aria-label="Gespräch" data-state={state} data-mode={shownView ? "zeige" : "dialog"}>
              <div className="stage-core">
                <Core3D state={state} size={shownView ? coreSmall(box) : avatarSize(box)} level={voice.level} />
                <p className="line">{stateView.label}</p>
                {connected && !voice.active && state === "idle" && (
                  <p className="hint">Der Sprachdienst läuft nicht. Starte ihn mit „kushim talk“.</p>
                )}
                {state === "offline" && why && <p className="hint">Grund: {WHY[why] ?? why}</p>}
                {state === "offline" && (
                  <button type="button" className="primary" onClick={() => void connect()}>Erneut versuchen</button>
                )}
              </div>
              {shownView && (
                <div className="stage-content">
                  <ViewTabs views={views} active={shownView.id} onPick={(id) => staged(() => setShown(id))} />
                  <ViewCard key={shownView.id} view={shownView} sys={sys} sysNo={sysNo} onClose={closeShown} />
                </div>
              )}
            </section>
          )}
        </div>
      </main>
    </div>
  );
}
