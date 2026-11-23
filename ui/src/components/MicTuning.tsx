// Kasten „Mikrofon“ in der Ansicht Sicherheit: Schwellen der Spracherkennung im laufenden Betrieb verstellen (voice.tuning.*).
// Die Oberfläche sendet nur Anfragen: `set` entprellt und erst nach dem Loslassen bzw. einer Tastenpause, `reset` auf Klick,
// `save` erst nach einer Bestätigung im Kasten. Alles mit confirm: true; das Backend prüft Grenzen, Notaus und Sprachdienst.
// Beim Laden wird nur gelesen (`get`), nie geschrieben. Abgefragt wird nur, solange der Kasten zu sehen ist.
import { useCallback, useEffect, useId, useRef, useState, type RefObject } from "react";
import { TUNING_BOUNDS, TUNING_KEYS, type ApiClient, type ApiReply, type TuningBounds, type TuningKey, type TuningState,
  type TuningValues } from "../lib/api";

export const TUNING_POLL_MS = 250;                      // Live-Pegel, solange der Sprachdienst läuft
export const TUNING_IDLE_MS = 2000;                     // Sprachdienst aus oder keine Antwort: seltener nachsehen
export const SEND_DELAY_MS = 200;                       // Entprellen der Regler
export const NOTE_NOW = "Änderung gilt sofort, bis zum Neustart.";
export const SAVE_NOTE = "Gilt dauerhaft, schreibt wakewords.toml (mit Sicherung).";
export const NOT_RUNNING = "Sprachdienst läuft nicht";

/** Logarithmische Skala des Pegelbalkens: 10 bis 10.000 (drei Zehnerstufen). */
export const METER_MIN = 10;
export const METER_MAX = 10_000;
export const SENS_MAX = 100;                            // Regler „Empfindlichkeit“: 0 (unempfindlich) bis 100 (empfindlich)

const de = (n: number, digits = 0) => n.toLocaleString("de-DE", { maximumFractionDigits: digits, minimumFractionDigits: digits });
const finite = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);
const clamp = (x: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, x));

/** Lage auf dem Pegelbalken (0 bis 100 %) für einen Pegel, logarithmisch. */
export function meterPct(x: number): number {
  if (!finite(x) || x <= METER_MIN) return 0;
  return clamp(((Math.log10(x) - Math.log10(METER_MIN)) / (Math.log10(METER_MAX) - Math.log10(METER_MIN))) * 100, 0, 100);
}

/** Regler → Schwelle: nach rechts EMPFINDLICHER, die Schwelle sinkt (logarithmisch zwischen den Grenzen, ganze Zahl). */
export function sensToLevel(pos: number, [lo, hi]: [number, number]): number {
  const p = clamp(pos, 0, SENS_MAX) / SENS_MAX;
  return clamp(Math.round(Math.exp(Math.log(hi) - p * (Math.log(hi) - Math.log(lo)))), lo, hi);
}
/** Schwelle → Regler (Umkehrung von `sensToLevel`). */
export function levelToSens(level: number, [lo, hi]: [number, number]): number {
  const l = clamp(level, lo, hi);
  return clamp(Math.round(((Math.log(hi) - Math.log(l)) / (Math.log(hi) - Math.log(lo))) * SENS_MAX), 0, SENS_MAX);
}

function parseValues(x: unknown): TuningValues | null {
  const v = x as Record<string, unknown> | null;
  if (!v || typeof v !== "object") return null;
  return TUNING_KEYS.every((k) => finite(v[k])) ? (Object.fromEntries(TUNING_KEYS.map((k) => [k, v[k]])) as TuningValues) : null;
}
function parseBounds(x: unknown): TuningBounds {
  const b = (x && typeof x === "object" ? x : {}) as Record<string, unknown>;
  return Object.fromEntries(TUNING_KEYS.map((k) => {
    const v = b[k];
    const ok = Array.isArray(v) && v.length === 2 && finite(v[0]) && finite(v[1]) && v[0] > 0 && v[0] < v[1];
    return [k, ok ? [v[0], v[1]] : TUNING_BOUNDS[k]];
  })) as TuningBounds;
}

/** Antwort von `voice.tuning.get` prüfen, nicht blind vertrauen. Fehlen die Werte, gibt es nichts anzuzeigen (null). */
export function parseTuning(r: ApiReply): TuningState | null {
  if (!r.ok) return null;
  const values = parseValues(r.values);
  if (!values) return null;
  const src = r.last_source;
  return {
    active: r.active === true,
    values,
    file_values: parseValues(r.file_values) ?? values,
    bounds: parseBounds(r.bounds),
    step: finite(r.step) ? clamp(Math.round(r.step), -2, 2) : 0,
    rms: finite(r.rms) && r.rms > 0 ? r.rms : 0,
    peak: finite(r.peak) && r.peak > 0 ? r.peak : 0,
    last_source: src === "ui" || src === "voice" || src === "file" ? src : "file",
  };
}

/** Fehler in klaren Worten, ohne Fachbegriffe; `what` sagt, was nicht passiert ist. */
export function tuningError(error: string, what = "Nichts wurde geändert."): string {
  if (error === "invalid") return `Dieser Wert ist nicht erlaubt. ${what}`;
  if (error === "kill") return `Notaus ist aktiv. ${what}`;
  if (error === "unavailable") return `Der Sprachdienst läuft nicht. ${what} Starte ihn mit „kushim talk“.`;
  if (error === "offline" || error === "timeout") return `Keine Verbindung zu kushim. ${what}`;
  if (error === "unknown_type") return "Dieser Dienst kennt die Mikrofon-Einstellung noch nicht. Starte kushim in der neuen Fassung.";
  return `Das hat nicht geklappt. ${what}`;
}

const stepWord = (s: number) => (s > 0 ? `+${s}` : s < 0 ? `−${-s}` : "0");
/** Fokus nie einer offenen Freigabe-Leiste wegnehmen. */
const approvalOpen = () => document.querySelector(".approval") !== null;

type Phase = "loading" | "ready" | "offline" | "unknown" | "error";

interface SliderProps {
  id: string; label: string; value: number; min: number; max: number; step: number; text: string; valueText: string;
  low?: string; high?: string; disabled: boolean; onChange: (v: number) => void; onGrab: () => void;
}

function Slider({ id, label, value, min, max, step, text, valueText, low, high, disabled, onChange, onGrab }: SliderProps) {
  const hint = low && high ? `${id}-ends` : undefined;
  return (
    <div className="mic-slider">
      <label htmlFor={id}>{label}</label>
      <span className="mic-num">{text}</span>
      <input id={id} type="range" min={min} max={max} step={step} value={value} disabled={disabled} aria-valuetext={valueText}
        aria-describedby={hint} onChange={(e) => onChange(Number(e.target.value))} onPointerDown={onGrab} />
      {low && high && <span className="mic-ends" id={hint}><span>{low}</span><span>{high}</span></span>}
    </div>
  );
}

export function MicTuning({ client, connected, kill, visible = true, sendDelay = SEND_DELAY_MS }: {
  client: RefObject<ApiClient | null>; connected: boolean; kill: boolean; visible?: boolean; sendDelay?: number }) {
  const [data, setData] = useState<TuningState | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [draft, setDraft] = useState<Partial<TuningValues>>({});   // gezogen, aber noch nicht bestätigt
  const [note, setNote] = useState("");
  const [asking, setAsking] = useState(false);                     // Bestätigung für „Merken“ offen
  const [busy, setBusy] = useState(false);
  const [docHidden, setDocHidden] = useState(() => typeof document !== "undefined" && document.hidden);
  const [inView, setInView] = useState(true);
  const box = useRef<HTMLElement | null>(null);
  const saveBtn = useRef<HTMLButtonElement | null>(null);
  const cancelBtn = useRef<HTMLButtonElement | null>(null);
  const pending = useRef<Partial<TuningValues>>({});
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dragging = useRef(false);
  const alive = useRef(true);
  const uid = useId();

  const read = useCallback(async (type: string, d: Record<string, unknown> = {}): Promise<ApiReply> => {
    const c = client.current;
    return c ? c.call(type, d) : { ok: false, error: "offline" };
  }, [client]);

  // ----- Sichtbarkeit: Fenster verdeckt (visibilitychange) und Kasten im Bild (IntersectionObserver, wo vorhanden)
  useEffect(() => {
    const on = () => setDocHidden(document.hidden);
    document.addEventListener("visibilitychange", on);
    return () => document.removeEventListener("visibilitychange", on);
  }, []);
  useEffect(() => {
    const el = box.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver((list) => { for (const e of list) setInView(e.isIntersecting); });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  // ----- Abfrage: nur lesen, etwa alle 250 ms, solange der Kasten zu sehen ist und das Fenster nicht verdeckt ist
  const polling = connected && visible && !docHidden && inView && phase !== "unknown";
  useEffect(() => {
    if (!polling) return;
    let stop = false;
    let t: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      const r = await read("voice.tuning.get");
      if (stop) return;
      const s = parseTuning(r);
      if (s) { setData(s); setPhase("ready"); }
      else if (!r.ok && r.error === "unknown_type") { setPhase("unknown"); return; }
      else setPhase(!r.ok && (r.error === "offline" || r.error === "timeout") ? "offline" : "error");
      t = setTimeout(tick, s?.active ? TUNING_POLL_MS : TUNING_IDLE_MS);
    };
    void tick();
    return () => { stop = true; if (t) clearTimeout(t); };
  }, [polling, read]);
  useEffect(() => { if (!connected) setPhase((p) => (p === "unknown" ? p : "offline")); }, [connected]);

  // ----- Senden: gesammelte Änderungen eines Zugs in einem `set`
  const flush = useCallback(async () => {
    timer.current = null;
    const patch = pending.current;
    pending.current = {};
    if (Object.keys(patch).length === 0) return;
    const r = await read("voice.tuning.set", { values: patch, confirm: true });
    if (!alive.current) return;
    if (r.ok) {
      setData((d) => (d ? { ...d, values: { ...d.values, ...patch }, last_source: "ui" } : d));
      setNote("");
    } else setNote(tuningError(r.error));
    setDraft((d) => {                                   // was inzwischen weiter gezogen wurde, bleibt Entwurf
      const next = { ...d };
      for (const k of Object.keys(patch) as TuningKey[]) if (next[k] === patch[k] && pending.current[k] === undefined) delete next[k];
      return next;
    });
  }, [read]);
  const schedule = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    if (dragging.current) return;                       // erst beim Loslassen
    timer.current = setTimeout(() => void flush(), sendDelay);
  }, [flush, sendDelay]);
  const change = (k: TuningKey, v: number) => {
    setDraft((d) => ({ ...d, [k]: v }));
    pending.current = { ...pending.current, [k]: v };
    schedule();
  };
  const grab = useCallback(() => {                      // Zeiger auf dem Regler: senden erst nach dem Loslassen
    dragging.current = true;
    const up = () => {
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
      dragging.current = false;
      if (Object.keys(pending.current).length) schedule();
    };
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
  }, [schedule]);
  useEffect(() => {                                     // beim Abbau: offene Änderung des Nutzers noch absenden, Zeitgeber weg
    alive.current = true;
    return () => {
      alive.current = false;
      if (timer.current) { clearTimeout(timer.current); timer.current = null; void flush(); }
    };
  }, [flush]);

  // ----- Knöpfe
  const reset = async () => {
    setBusy(true);
    const r = await read("voice.tuning.reset", { confirm: true });
    setBusy(false);
    if (r.ok) {
      pending.current = {};
      setDraft({});
      setData((d) => (d ? { ...d, values: { ...d.file_values }, step: 0, last_source: "file" } : d));
      setNote("Zurück auf die Werte aus wakewords.toml.");
    } else setNote(tuningError(r.error));
  };
  const openAsk = () => { setNote(""); setAsking(true); };
  const refocus = useRef(false);
  const closeAsk = useCallback(() => { refocus.current = true; setAsking(false); }, []);
  useEffect(() => {                                     // nur nach eigener Bedienung: auf, Standard „Abbrechen“; zu, zurück auf „Merken“
    if (approvalOpen()) return;
    if (asking) cancelBtn.current?.focus();
    else if (refocus.current) {
      refocus.current = false;
      const b = saveBtn.current;
      (b && !b.disabled ? b : box.current?.querySelector<HTMLElement>("h2"))?.focus();
    }
  }, [asking, busy]);
  const save = async () => {
    setBusy(true);
    const r = await read("voice.tuning.save", { confirm: true });
    setBusy(false);
    closeAsk();
    if (r.ok) {
      setData((d) => (d ? { ...d, file_values: { ...d.values } } : d));
      setNote("Gemerkt. Die Werte gelten jetzt auch nach dem Neustart.");
    } else setNote(tuningError(r.error, "Nichts wurde gespeichert."));
  };

  // ----- Anzeige
  const active = data?.active === true;
  const locked = kill || !active || phase !== "ready";
  const val = (k: TuningKey) => draft[k] ?? data?.values[k] ?? TUNING_BOUNDS[k][0];
  const b = data?.bounds ?? TUNING_BOUNDS;
  const differs = !!data && TUNING_KEYS.some((k) => data.values[k] !== data.file_values[k]);
  const fileNote = (k: TuningKey, unit = "", digits = 0) =>
    data && data.file_values[k] !== val(k) ? ` (Datei ${de(data.file_values[k], digits)}${unit})` : "";
  const status = phase === "loading" ? "lädt" : phase === "offline" ? "keine Verbindung" : phase === "unknown" ? "nicht verfügbar"
    : phase === "error" ? "unbekannt" : active ? "live" : NOT_RUNNING;
  const speech = val("speech_level"), barge = val("barge_in_level");
  const rms = active ? data?.rms ?? 0 : 0, peak = active ? data?.peak ?? 0 : 0;

  return (
    <section ref={box} className="panel mic-tune" aria-labelledby={`${uid}-h`} data-active={active ? "ja" : "nein"}>
      <div className="panel-head">
        <h2 id={`${uid}-h`} tabIndex={-1}>Mikrofon</h2>
        <span className="label">{status}</span>
      </div>

      {phase === "ready" && !active && <p className="mic-text">{NOT_RUNNING}. Starte ihn mit „kushim talk“, dann lassen sich die Schwellen einstellen.</p>}
      {phase === "offline" && <p className="mic-text">Keine Verbindung zu kushim. Die Schwellen lassen sich gerade nicht lesen.</p>}
      {phase === "unknown" && <p className="mic-text">Dieser Dienst kennt die Mikrofon-Einstellung noch nicht. Starte kushim in der neuen Fassung.</p>}
      {phase === "error" && <p className="mic-text">Die Schwellen sind gerade nicht lesbar. Es gelten die Werte aus <code>wakewords.toml</code>.</p>}
      {kill && <p className="mic-lock" role="status">Gesperrt: Notaus aktiv. Ändern geht erst nach dem Aufheben.</p>}

      <div className="mic-meter-box">
        <div className="mic-meter" role="meter" aria-label="Mikrofonpegel, logarithmisch" aria-valuemin={0} aria-valuemax={METER_MAX}
          aria-valuenow={Math.round(rms)} aria-valuetext={active ? `RMS ${de(rms)}, Spitze ${de(peak)}` : "kein Signal"}>
          <div className="mic-fill" style={{ width: `${meterPct(rms)}%` }} />
          {active && peak > 0 && <div className="mic-peak" style={{ left: `${meterPct(peak)}%` }} />}
          {data && <div className="mic-mark mic-mark-speech" style={{ left: `${meterPct(speech)}%` }} />}
          {data && <div className="mic-mark mic-mark-barge" style={{ left: `${meterPct(barge)}%` }} />}
        </div>
        <div className="mic-scale" aria-hidden="true">
          <span className="mic-s0">10</span><span className="mic-s1">100</span><span className="mic-s2">1.000</span><span className="mic-s3">10.000</span>
        </div>
      </div>
      <ul className="mic-legend">
        <li><span className="mic-key mic-key-speech" aria-hidden="true" />Sprechen ab {data ? de(speech) : "unbekannt"}</li>
        <li><span className="mic-key mic-key-barge" aria-hidden="true" />Unterbrechen ab {data ? de(barge) : "unbekannt"}</li>
        <li>RMS {active ? de(rms) : "kein Signal"}</li>
        <li>Spitze {active ? de(peak) : "kein Signal"}</li>
      </ul>
      {data?.last_source === "voice" && <p className="mic-voice">per Stimme: Stufe {stepWord(data.step)}</p>}

      <fieldset className="mic-fields" disabled={locked}>
        <legend className="v-sr">Schwellen</legend>
        <Slider id={`${uid}-speech`} label="Empfindlichkeit Sprechen" min={0} max={SENS_MAX} step={1}
          value={levelToSens(speech, b.speech_level)} text={`Schwelle ${de(speech)}${fileNote("speech_level")}`}
          valueText={`Schwelle ${de(speech)}, nach rechts empfindlicher`} low="weniger empfindlich" high="empfindlicher"
          disabled={locked} onGrab={grab} onChange={(p) => change("speech_level", sensToLevel(p, b.speech_level))} />
        <Slider id={`${uid}-barge`} label="Empfindlichkeit Unterbrechen" min={0} max={SENS_MAX} step={1}
          value={levelToSens(barge, b.barge_in_level)} text={`Schwelle ${de(barge)}${fileNote("barge_in_level")}`}
          valueText={`Schwelle ${de(barge)}, nach rechts empfindlicher`} low="weniger empfindlich" high="empfindlicher"
          disabled={locked} onGrab={grab} onChange={(p) => change("barge_in_level", sensToLevel(p, b.barge_in_level))} />
        <details className="mic-adv">
          <summary>Erweitert</summary>
          <div className="mic-adv-body">
            <Slider id={`${uid}-pause`} label="Pause bis Satzende" min={b.end_silence_seconds[0]} max={b.end_silence_seconds[1]} step={0.1}
              value={val("end_silence_seconds")} text={`${de(val("end_silence_seconds"), 1)} s${fileNote("end_silence_seconds", " s", 1)}`}
              valueText={`${de(val("end_silence_seconds"), 1)} Sekunden`} disabled={locked} onGrab={grab}
              onChange={(v) => change("end_silence_seconds", Math.round(v * 10) / 10)} />
            <Slider id={`${uid}-ms`} label="Mindestdauer Unterbrechen" min={b.barge_in_ms[0]} max={b.barge_in_ms[1]} step={10}
              value={val("barge_in_ms")} text={`${de(val("barge_in_ms"))} ms${fileNote("barge_in_ms", " ms")}`}
              valueText={`${de(val("barge_in_ms"))} Millisekunden`} disabled={locked} onGrab={grab}
              onChange={(v) => change("barge_in_ms", Math.round(v))} />
          </div>
        </details>
      </fieldset>

      <p className="mic-text mic-hint">{NOTE_NOW}</p>
      <div className="mic-actions">
        <button type="button" disabled={locked || busy || asking || !differs} onClick={() => void reset()}
          title="Zurück auf die Werte aus wakewords.toml">Standard</button>
        <button ref={saveBtn} type="button" disabled={locked || busy || asking || !differs} aria-expanded={asking}
          onClick={openAsk}>Merken</button>
      </div>
      {asking && (
        <div className="mic-confirm" role="alertdialog" aria-labelledby={`${uid}-ask`} aria-describedby={`${uid}-ask-d`}
          onKeyDown={(e) => {
            if (e.ctrlKey || e.altKey || e.metaKey) return;                  // Tasten mit Strg, Alt oder Meta gehören dem Browser
            if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeAsk(); }
          }}>
          <p className="mic-confirm-h" id={`${uid}-ask`}>Werte dauerhaft merken?</p>
          <p className="mic-text" id={`${uid}-ask-d`}>{SAVE_NOTE}</p>
          <div className="mic-actions">
            <button ref={cancelBtn} type="button" onClick={closeAsk}>Abbrechen</button>
            <button type="button" className="primary" disabled={locked || busy} onClick={() => void save()}>Dauerhaft merken</button>
          </div>
        </div>
      )}
      <div className="mic-msg" role="status" aria-live="polite">{note && <p>{note}</p>}</div>
    </section>
  );
}
