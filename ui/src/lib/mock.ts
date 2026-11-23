// Gefälschtes Backend für Entwicklung und Tests (kein Netz). Antwortet wie `ApiCore`: Token zuerst, neutrale Fehler.
import type { Socket, TuningBounds, TuningValues } from "./api";

/** Ein Eintrag wie `transcript.get` ihn liefert (src/kushim/voice/transcript.py), mit allen Feldern. */
export interface MockEntry {
  id: number; rev: number; heard: string; raw: string; ts: number; status: "pending" | "sent" | "dropped"; reason: string;
  sent_ts: number | null; reply: string; outcome: string;
}

/** Vollständiger Eintrag mit den Standardwerten des Backends: rev = id, raw = heard, gesendet zur Erkennungszeit, Antwort leer. */
export function transcriptEntry(p: Partial<MockEntry> & { id: number }): MockEntry {
  const ts = p.ts ?? Date.now() / 1000;
  const status = p.status ?? "sent";
  return { rev: p.id, heard: "", raw: p.heard ?? "", ts, status, reason: "", sent_ts: status === "sent" ? ts : null, reply: "",
    outcome: "spoken", ...p };
}

export class MockSocket implements Socket {
  onmessage: Socket["onmessage"] = null;
  onclose: Socket["onclose"] = null;
  onopen: Socket["onopen"] = null;
  onerror: Socket["onerror"] = null;
  kill = false;
  voice: { active: boolean; state: string; level: number } = { active: false, state: "idle", level: 0 };
  pending: { request_id: string; tool_name: string; description: string; input_preview: string; digest: string; summary: string;
    truncated?: boolean }[] = [];
  entries: MockEntry[] = [];                            // wie transcript.get: alle Felder (id, rev, heard, raw, ts, status, ...)
  revSeq = 0;                                           // höchste vergebene rev (hear/change)
  /** Wie `Transcript.heard` nach der Spracherkennung: neuer Eintrag „pending“ (mit `reason` gleich „dropped“). Gibt die id zurück. */
  hear(raw: string, heard: string, reason = ""): number {
    const id = Math.max(0, ...this.entries.map((e) => e.id)) + 1;
    this.revSeq = Math.max(this.revSeq, ...this.entries.map((e) => e.rev)) + 1;
    this.entries.push(transcriptEntry({ id, rev: this.revSeq, raw, heard, ts: Date.now() / 1000,
      status: reason ? "dropped" : "pending", reason, sent_ts: null, outcome: "" }));
    return id;
  }
  /** Wie `sent`, `drop` und `add`: Felder eines Eintrags ändern, rev steigt. */
  change(id: number, patch: Partial<Omit<MockEntry, "id" | "rev">>): void {
    this.revSeq = Math.max(this.revSeq, ...this.entries.map((e) => e.rev)) + 1;
    this.entries = this.entries.map((e) => (e.id === id ? { ...e, ...patch, rev: this.revSeq } : e));
  }
  folders: string[] = [];
  overview: Record<string, unknown> = {
    kill: false, tools_active: [], vault: { where: "local", exists: true, open: true },
    backup: { configured: true, age_days: 2 }, money_limit_eur: 0, audit: [],
  };
  facts: { id: number; text: string; kind: string; source: string; created: number }[] = [];
  deleted: number[] = [];
  system: Record<string, unknown> | null = {          // Beispielwerte; null = Dienst kennt system.stats nicht
    cpu: { percent: 34 }, memory: { percent: 61, used_gb: 9.8, total_gb: 16 },
    gpu: { percent: 22, vram_used_mb: 3100, vram_total_mb: 8192, temp_c: 58 },
    disk: { percent: 41, used_gb: 412, total_gb: 1000 }, battery: { present: false, percent: null, on_ac: null },
    net: { down_mbit: 42.1, up_mbit: 8.3 }, system: { os: "Windows 11", uptime_s: 568800 }, warn_at: 80,
  };
  stage: Record<string, unknown>[] = [];                // Ansichten wie von Claude über `zeige` (mit seq)
  stageSeq = 0;
  /** Wie Claudes Werkzeug `zeige`: legt eine Ansicht ab, die die Oberfläche über stage.get abholt. */
  show(view: Record<string, unknown>): void {
    this.stageSeq += 1;
    this.stage = [...this.stage.filter((v) => v.id !== view.id), { ...view, seq: this.stageSeq }];
  }
  dash: Record<string, unknown> = { timers: [], tasks: [], pending_approvals: 0, results: [] };
  folderProposal: { name: string; path: string } | null = null;
  rated = new Set<number>();
  ratings: { entry: number; rating: number }[] = [];
  sent: unknown[] = [];

  /** E2b: Verbrauch wie `usage.get` (alle Felder, wie das Backend sie liefert); null = Dienst kennt usage.get nicht.
   *  Im Browser wählt `?mock&usage=alt` den veralteten Stand und `?mock&usage=keine` „nicht verfügbar“. */
  usage: Record<string, unknown> | null = usageDemo("frisch");

  constructor(public url: string, private token = "t".repeat(43), private fail = false) {
    const query = new URLSearchParams(typeof location !== "undefined" ? location.search : "");
    const pick = query.get("usage");
    if (pick === "alt" || pick === "keine") this.usage = usageDemo(pick);
    if (query.has("freigabe")) this.pending = [{ request_id: "demo1", tool_name: "Bash", description: "Tests ausführen (Beispiel)",
      input_preview: "cd ui && npx vitest run", digest: "d".repeat(64), summary: "Claude möchte die Tests ausführen.", truncated: false }];
    this.setupFromUrl();                                // E3: ?mock&setup (Erststart), ?mock&setup&novoice (ohne Sprachdienst)
    this.tuningFromUrl();                               // Mikrofon: ?mock&mic=aus (Sprachdienst aus), ?mock&mic=stimme (per Stimme verstellt)
    queueMicrotask(() => (this.fail ? this.onerror?.() : this.onopen?.()));
  }

  // ===== E3 Setup-Assistent (Mock): setup.*, audio.*, voice.level_*, wake.*; Formen wie im Vertrag, Beispieldaten =====
  setupSteps: Record<string, "open" | "done" | "skipped"> = Object.fromEntries(SETUP_IDS.map((s) => [s, "done"]));
  checks: { id: string; label: string; ok: boolean; hint: string }[] = [
    { id: "pkg_faster_whisper", label: "Python-Paket faster_whisper (Spracherkennung)", ok: true, hint: "" },
    { id: "pkg_sounddevice", label: "Python-Paket sounddevice (Mikrofon)", ok: true, hint: "" },
    { id: "model_whisper", label: "Whisper-Modell", ok: true, hint: "" },
    { id: "model_piper", label: "Piper-Stimme", ok: true, hint: "" },
    { id: "model_kws", label: "Wake-Word-Modell", ok: true, hint: "" },
    { id: "gpu_libs", label: "GPU-Bibliotheken (cuBLAS/cuDNN)", ok: true, hint: "" },
    { id: "kill_off", label: "Notaus nicht aktiv", ok: true, hint: "kushim resume" },
    { id: "vault", label: "Vault vorhanden", ok: false, hint: "kushim memory init" },
    { id: "claude_installed", label: "Claude Code installiert", ok: true, hint: "" },
    { id: "claude_version", label: "Claude Code mindestens 2.1.234 (ist 2.1.240)", ok: true, hint: "" },
    { id: "claude_login", label: "In Claude Code angemeldet", ok: false, hint: "claude auth login" },
  ];
  claudeChecking = false;                               // erste Claude-Prüfung läuft: Platzhalter statt claude_*, Schritt „Wird geprüft“
  checksReply: Record<string, unknown> | null = null;   // Tests: setup.checks genau so beantworten (Fehler, kaputte Einträge)
  levelOverride: Record<string, unknown> | null = null; // Tests: voice.level_result genau so beantworten
  noWakeCount = false;                                  // Variante: älterer Sprachdienst ohne wake_count/wake_last
  devices: { inputs: string[]; outputs: string[] } | null = {
    inputs: ["Mikrofon (USB Audio Device)", "Headset-Mikrofon (Jabra Evolve 65)", "Mikrofonarray (Realtek Audio)"],
    outputs: ["Lautsprecher (Realtek Audio)", "Kopfhörer (Jabra Evolve 65)"],
  };
  audio = { mic: "", out: "" };
  levels = { speech_level: 200, barge_in_level: 250 };
  words: { phrase: string; enabled: boolean }[] = ["hey kushim", "kushim", "kush", "hallo kush", "hi kushim", "kushi"].map((phrase) => ({ phrase, enabled: true }));
  wakeCount = 0;
  wakeLast = "";
  voiceUnavailable = false;                             // Variante: kein Sprachdienst (Pegeltest und Wake-Word-Test gehen nicht)
  levelUnavailable = false;                             // Variante: Sprachdienst läuft, der Pegeltest steht aber nicht zur Verfügung
  levelStart: number | null = null;                     // Pegeltest: 3 s still sein, dann 6 s sprechen, dann Vorschlag
  now = () => Date.now();

  /** Wie beim ersten Start: alle Schritte offen. */
  firstStart(): void { for (const s of SETUP_IDS) this.setupSteps[s] = "open"; }
  /** Wie der Sprachdienst ein Wake Word erkennt (nur Zähler und Name). */
  wake(phrase: string): void { this.wakeCount += 1; this.wakeLast = phrase; }
  /** Vorführung im Browser: Pegel bewegt sich, alle 6 s wird ein aktives Wake Word „erkannt“. */
  setupDemo(): void {
    this.voice = { active: !this.voiceUnavailable, state: "idle", level: 0 };
    if (this.voiceUnavailable) return;
    let t = 0;
    this.setupTimers.push(
      setInterval(() => { t += 1; this.voice = { ...this.voice, level: Math.round((0.15 + 0.35 * Math.abs(Math.sin(t / 4))) * 100) / 100 }; }, 200),
      setInterval(() => { const on = this.words.filter((w) => w.enabled); if (on.length) this.wake(on[this.wakeCount % on.length].phrase); }, 6000));
  }
  private setupTimers: ReturnType<typeof setInterval>[] = [];
  private stopSetupDemo(): void { this.setupTimers.splice(0).forEach(clearInterval); }
  private setupFromUrl(): void {
    if (typeof location === "undefined") return;
    const q = new URLSearchParams(location.search);
    if (!q.has("mock") || !q.has("setup")) return;
    this.voiceUnavailable = q.has("novoice");
    this.firstStart();
    this.setupDemo();
    this.claudeChecking = true;                         // die erste Claude-Prüfung dauert ein paar Sekunden
    this.setupTimers.push(setTimeout(() => { this.claudeChecking = false; }, 8000));
  }
  private setupStatus(): Record<string, unknown> {
    return { ok: true, kill: this.kill,
      steps: SETUP_IDS.map((s) => (s === "claude" && this.claudeChecking
        ? { step: s, title: SETUP_TITLES[s], status: "open", detail: "Wird geprüft" }
        : { step: s, title: SETUP_TITLES[s], status: this.setupSteps[s], detail: "" })),
      first_start: SETUP_IDS.some((s) => this.setupSteps[s] === "open"),
      restricted: SETUP_IDS.filter((s) => this.setupSteps[s] === "skipped").map((s) => `${SETUP_TITLES[s]}: ${SETUP_SKIPPED[s]}`) };
  }
  private voiceReply(): Record<string, unknown> {
    if (this.voiceUnavailable) return { ok: true, active: false, state: "idle", level: 0, wake_count: 0, wake_last: "" };
    return this.noWakeCount ? { ok: true, ...this.voice } : { ok: true, ...this.voice, wake_count: this.wakeCount, wake_last: this.wakeLast };
  }
  private levelResult(): Record<string, unknown> {
    if (this.levelOverride) return { ...this.levelOverride };
    if (this.voiceUnavailable) return { ok: true, state: "unavailable", seconds_left: 0, suggestion: null };
    if (this.levelStart === null) return { ok: true, state: "idle", seconds_left: 0, suggestion: null };
    const t = (this.now() - this.levelStart) / 1000;
    if (t < 3) return { ok: true, state: "quiet", seconds_left: Math.ceil(3 - t), suggestion: null };
    if (t < 9) return { ok: true, state: "speak", seconds_left: Math.ceil(9 - t), suggestion: null };
    return { ok: true, state: "done", seconds_left: 0, suggestion: { speech_level: 240, barge_in_level: 320 } };
  }
  /** Antwort auf die Setup-Typen; undefined = kein Setup-Typ. Schreibende brauchen confirm: true und lehnen bei Notaus mit „kill“ ab. */
  private setupReply(msg: Record<string, unknown>): unknown {
    const type = String(msg.type);
    const writes = ["setup.skip", "setup.reopen", "setup.done", "audio.set", "voice.level_test", "voice.level_apply", "wake.set"];
    if (writes.includes(type)) {
      if (msg.confirm !== true) return { ok: false, error: "confirm_required" };
      if (this.kill) return { ok: false, error: "kill" };
    }
    const step = typeof msg.step === "string" && (SETUP_IDS as readonly string[]).includes(msg.step) ? msg.step : null;
    switch (type) {
      case "setup.status": return this.setupStatus();
      case "setup.skip": case "setup.reopen": case "setup.done":
        if (!step) return { ok: false, error: "bad_step" };
        if (type === "setup.done" && !["audio_voice", "wake_words", "safety"].includes(step)) return { ok: false, error: "not_allowed" };
        this.setupSteps[step] = type === "setup.skip" ? "skipped" : type === "setup.done" ? "done" : "open";
        return this.setupStatus();
      case "setup.checks":
        if (this.checksReply) return { ...this.checksReply };
        return { ok: true, checks: this.claudeChecking
          ? [...this.checks.filter((c) => !c.id.startsWith("claude")), { id: "claude_checking", label: "Claude Code wird geprüft", ok: false, hint: "" }]
          : this.checks };
      case "audio.devices": return this.devices ? { ok: true, ...this.devices } : { ok: false, error: "unavailable" };
      case "audio.get": return { ok: true, ...this.audio };
      case "audio.set":
        if (typeof msg.mic !== "string" || typeof msg.out !== "string") return { ok: false, error: "bad_device" };
        this.audio = { mic: msg.mic, out: msg.out };
        return { ok: true, ...this.audio, restart_needed: true };
      case "voice.level_test":
        if (this.voiceUnavailable || this.levelUnavailable) return { ok: false, error: "unavailable" };
        this.levelStart = this.now();
        return { ok: true };
      case "voice.level_result": return this.levelResult();
      case "voice.level_apply": {
        const a = msg.speech_level, b = msg.barge_in_level;
        if (typeof a !== "number" || typeof b !== "number" || a < 50 || a > 5000 || b < 100 || b > 20000) return { ok: false, error: "bad_level" };
        this.levels = { speech_level: a, barge_in_level: b };
        return { ok: true, ...this.levels, restart_needed: true };
      }
      case "wake.get": return { ok: true, words: this.words, max: 12 };
      case "wake.set": {
        const w = Array.isArray(msg.words) ? msg.words as { phrase?: unknown; enabled?: unknown }[] : [];
        const ok = w.length >= 1 && w.length <= 12 && w.every((x) => typeof x.phrase === "string" && /^[a-zäöüß]+( [a-zäöüß]+){0,3}$/.test(x.phrase)
          && x.phrase.length >= 3 && x.phrase.length <= 40 && typeof x.enabled === "boolean")
          && new Set(w.map((x) => x.phrase)).size === w.length && w.some((x) => x.enabled === true);
        if (!ok) return { ok: false, error: "bad_words" };
        this.words = w.map((x) => ({ phrase: x.phrase as string, enabled: x.enabled as boolean }));
        return { ok: true, words: this.words, max: 12, restart_needed: true };
      }
      default: return undefined;
    }
  }
  // ===== Ende E3 =====

  // ===== Mikrofon-Schwellen zur Laufzeit (voice.tuning.*), genau wie das Backend (api/voice_api.py, voice/tuning.py; routine/
  // mic-tuning): Grenzen als {min, max} plus Stufe, `version`, Pegel als Rohwerte 0 bis 32767; set/reset/save antworten mit dem
  // ganzen Stand, save zusätzlich mit `backup`. Fehler in derselben Reihenfolge: bad_request, confirm_required, kill, unavailable,
  // invalid bzw. broken_file/not_saved. =====
  /** Läuft der Sprachdienst für die Schwellen? Im Browser zeigt `?mock&mic=aus` den deaktivierten Kasten. */
  tuningActive = true;
  tuningFile: TuningValues = { speech_level: 200, barge_in_level: 250, barge_in_ms: 240, end_silence_seconds: 2.5 };
  tuningValues: TuningValues = { ...this.tuningFile };
  tuningBounds: TuningBounds = { speech_level: [80, 600], barge_in_level: [150, 1500], barge_in_ms: [160, 400], end_silence_seconds: [0.6, 3.0] };
  tuningStep = 0;
  tuningSource: "ui" | "voice" | "file" = "file";
  tuningVersion = 0;
  /** wakewords.toml fehlerhaft: ohne Sprachdienst sind values/file_values null, „Merken“ lehnt mit broken_file ab (`?mock&mic=kaputt`). */
  tuningFileBroken = false;
  /** Es gibt noch keine wakewords.toml: „Merken“ legt keine Sicherung an (backup: false). */
  tuningNoFile = false;
  /** Tests: das nächste set/reset/save genau so ablehnen (danach wieder normal). */
  tuningFail: "invalid" | "kill" | "unavailable" | "bad_request" | "confirm_required" | "broken_file" | "not_saved" | null = null;
  tuningSaves = 0;                                      // wie oft „Merken“ die Datei geschrieben hätte
  /** Wie die Sprachsteuerung („Mikrofon empfindlicher“): Stufe -2 bis 2, Faktor 1,4 je Stufe auf Sprechen und Unterbrechen,
   *  begrenzt und auf 0,1 gerundet, Grundlage sind die Dateiwerte. */
  voiceTune(step: number): void {
    this.tuningStep = Math.max(-2, Math.min(2, Math.round(step)));
    const stepped = (k: "speech_level" | "barge_in_level") => {
      const [lo, hi] = this.tuningBounds[k];
      return Math.round(Math.max(lo, Math.min(hi, this.tuningFile[k] / 1.4 ** this.tuningStep)) * 10) / 10;
    };
    this.tuningValues = { ...this.tuningValues, speech_level: stepped("speech_level"), barge_in_level: stepped("barge_in_level") };
    this.tuningSource = "voice";
    this.tuningVersion += 1;
  }
  /** Simulierter Pegel (Rohwerte): ruhiger Raum um 40, beim Sprechen bis etwa 2.000, Spitze gut doppelt so hoch, abhängig von `now`. */
  private tuningLevel(): { rms: number; peak: number } {
    const t = this.now() / 1000;
    const speech = Math.max(0, Math.sin(t * 0.9)) ** 2;
    const rms = Math.round((40 + 1960 * speech * (0.7 + 0.3 * Math.abs(Math.sin(t * 7.3)))) * 10) / 10;
    return { rms, peak: Math.min(32767, Math.round(rms * (2.1 + 0.4 * Math.abs(Math.sin(t * 3.1))) * 10) / 10) };
  }
  private tuningState(): Record<string, unknown> {
    const bounds = { ...Object.fromEntries(Object.entries(this.tuningBounds).map(([k, [min, max]]) => [k, { min, max }])), step: { min: -2, max: 2 } };
    if (!this.tuningActive) {                           // wie ohne Sprachprozess: Werte aus der Datei (oder null), Pegel 0
      const file = this.tuningFileBroken ? null : { ...this.tuningFile };
      return { active: false, values: file, file_values: file ? { ...file } : null, bounds, step: 0, rms: 0, peak: 0,
        last_source: "file", version: 0 };
    }
    return { active: true, values: { ...this.tuningValues }, file_values: { ...this.tuningFile }, bounds, step: this.tuningStep,
      ...this.tuningLevel(), last_source: this.tuningSource, version: this.tuningVersion };
  }
  private tuningReply(msg: Record<string, unknown>): unknown {
    const type = String(msg.type);
    if (type === "voice.tuning.get") return { ok: true, ...this.tuningState() };
    if (!["voice.tuning.set", "voice.tuning.reset", "voice.tuning.save"].includes(type)) return { ok: false, error: "unknown_type" };
    let patch: Record<string, number> = {};
    if (type === "voice.tuning.set") {                  // Form zuerst: ein nicht leeres Objekt mit bekannten Namen und Zahlen
      const v = msg.values as Record<string, unknown> | null;
      const ok = !!v && typeof v === "object" && !Array.isArray(v) && Object.keys(v).length > 0
        && Object.entries(v).every(([k, x]) => k in this.tuningBounds && typeof x === "number" && Number.isFinite(x));
      if (!ok) return { ok: false, error: "bad_request" };
      patch = v as Record<string, number>;
    }
    if (msg.confirm !== true) return { ok: false, error: "confirm_required" };
    if (this.tuningFail) { const error = this.tuningFail; this.tuningFail = null; return { ok: false, error }; }
    if (this.kill) return { ok: false, error: "kill" };
    if (!this.tuningActive) return { ok: false, error: "unavailable" };
    if (type === "voice.tuning.reset") {
      this.tuningValues = { ...this.tuningFile }; this.tuningStep = 0; this.tuningSource = "ui"; this.tuningVersion += 1;
      return { ok: true, ...this.tuningState() };
    }
    if (type === "voice.tuning.save") {
      if (this.tuningFileBroken) return { ok: false, error: "broken_file" };
      const backup = !this.tuningNoFile;
      this.tuningFile = { ...this.tuningValues }; this.tuningNoFile = false; this.tuningSaves += 1;
      this.tuningStep = 0; this.tuningSource = "ui"; this.tuningVersion += 1;
      return { ok: true, ...this.tuningState(), backup };
    }
    const inside = Object.entries(patch).every(([k, x]) => {
      const [lo, hi] = this.tuningBounds[k as keyof TuningBounds];
      return x >= lo && x <= hi && (k !== "barge_in_ms" || Number.isInteger(x));
    });
    if (!inside) return { ok: false, error: "invalid" };
    this.tuningValues = { ...this.tuningValues, ...(patch as Partial<TuningValues>) };
    this.tuningSource = "ui";
    this.tuningVersion += 1;
    return { ok: true, ...this.tuningState() };
  }
  private tuningFromUrl(): void {
    if (typeof location === "undefined") return;
    const q = new URLSearchParams(location.search);
    if (!q.has("mock")) return;
    if (q.get("mic") === "aus") this.tuningActive = false;
    if (q.get("mic") === "kaputt") { this.tuningActive = false; this.tuningFileBroken = true; }
    if (q.get("mic") === "stimme") this.voiceTune(1);
  }
  // ===== Ende Mikrofon-Schwellen =====

  /** Vorführung im Browser (`?mock&demo`): erst ein reines Gespräch (Kern bleibt groß), dann zeigt „Claude“ der Reihe nach
   *  Rechnung, Markt, Recherche und Systemzustand. Nur Mock, Beispieldaten. */
  demo(): void {
    const turn = (at: number, heard: string, reply: string, view?: Record<string, unknown>) => {
      const steps: [string, number][] = [["listening", 0.6], ["thinking", 0], ["speaking", 0.7], ["idle", 0]];
      let id = 0;
      steps.forEach(([state, level], i) => setTimeout(() => {
        this.voice = { active: true, state, level };
        if (state === "thinking") id = this.hear(`Hey kushim, ${heard}`, heard);                   // Zeile „Du“ sofort: wartet
        if (state === "thinking") setTimeout(() => this.change(id, { status: "sent", sent_ts: Date.now() / 1000 }), 800);
        if (state === "speaking") {
          this.change(id, { reply, outcome: "spoken" });
          if (view) this.show(view);
        }
      }, at + i * 2500));
    };
    turn(2000, "Wie wird das Wetter morgen?", "Morgen 11 Grad, ab Nachmittag leichter Regen.");
    setTimeout(() => this.hear("Hey kushim.", "", "wake_only"), 10500);                            // verworfen: nur Weckwort
    setTimeout(() => this.hear("Hey kushim, abbrechen", "abbrechen", "cancelled"), 11500);         // verworfen: Abbruch
    turn(13000, "Löse x² minus 5x plus 6 gleich 0.", "Die Lösungen sind 2 und 3.", DEMO_VIEWS[0]);
    turn(24000, "Wie steht der DAX?", "Der DAX liegt bei 19.420 Punkten.", DEMO_VIEWS[1]);
    turn(35000, "Was weiß man über Koffein und Schlaf?", "Ich habe drei Quellen zusammengefasst.", DEMO_VIEWS[2]);
    turn(46000, "Wie ist die Systemauslastung?", "Ich zeige dir den Systemzustand.", DEMO_VIEWS[3]);
    turn(57000, "Mach die Tests grün und plane meinen Dienstag.", "Ich arbeite den Plan ab.", {
      ...DEMO_VIEWS[4], bausteine: [...(DEMO_VIEWS[4].bausteine as unknown[]),
        { typ: "countdown", titel: "Tee zieht", ende: new Date(Date.now() + 4 * 60000).toISOString() }] });
    turn(68000, "Was schreibt Anna, und antworte ihr.", "Hier die Mail und mein Entwurf.", DEMO_VIEWS[5]);
    turn(79000, "Lies mir rechnen.py und gib mir eine Übersicht.", "Zwei Funktionen, neu ist die Prüfung auf leere Eingaben.", DEMO_VIEWS[6]);
    turn(90000, "Zeig mir das Regal in 3D, vorher und nachher.", "Hier ist das Regal, der neue Boden ist hervorgehoben.", DEMO_VIEWS[7]);
    turn(101000, "Zeichne den Grundriss vom Wohnzimmer.", "Hier ist der Grundriss mit Maßen.", DEMO_VIEWS[8]);
    turn(112000, "Bahn oder Auto nach Hamburg?", "Hier der Vergleich.", DEMO_VIEWS[9]);
    turn(123000, "Wie ging die Geschichte des Buchdrucks?", "Hier die wichtigsten Daten.", DEMO_VIEWS[10]);
    turn(134000, "Übersetze mir ein paar Sätze ins Arabische.", "Hier sind die Sätze.", DEMO_VIEWS[11]);
    turn(145000, "Ich will Hauptstädte üben.", "Hier sind Karten und ein kurzes Quiz.", DEMO_VIEWS[12]);
    turn(156000, "Wie backe ich Pfannkuchen?", "Hier die Anleitung Schritt für Schritt.", DEMO_VIEWS[13]);
    turn(167000, "Wie läuft eine Bestellung ab?", "Hier der Ablauf.", DEMO_VIEWS[14]);
    turn(178000, "Zeig mir den Aufbau der Firma.", "Hier das Organigramm.", DEMO_VIEWS[15]);
    turn(189000, "Sammle Ideen für den Urlaub.", "Hier die Mindmap.", DEMO_VIEWS[16]);
    turn(200000, "Zeig mir, wie ein Pendel schwingt.", "Hier ein Pendel mit einem Meter Länge.", DEMO_VIEWS[17]);
    turn(211000, "Wie fliegt ein schräg geworfener Ball?", "Hier der Wurf unter 45 Grad.", DEMO_VIEWS[18]);
    turn(222000, "Wie bewegen sich Teilchen in einem Gas?", "Hier ein Gas mit 60 Teilchen.", DEMO_VIEWS[19]);
    turn(233000, "Wie sieht ein Wassermolekül aus?", "Hier Wasser, gewinkelt mit zwei Bindungen.", TEILCHEN_DEMOS[0]);
    turn(244000, "Zeig mir Ethanol.", "Hier Ethanol; die Bindungen sind aus den Abständen berechnet.", TEILCHEN_DEMOS[1]);
    turn(255000, "Wie ist ein Natriumatom aufgebaut?", "Hier das Schalenmodell von Natrium.", TEILCHEN_DEMOS[2]);
    turn(266000, "Wie sieht ein 2p-Orbital aus?", "Hier das 2p_z-Orbital als Wolke.", TEILCHEN_DEMOS[3]);
    // P5b-Simulationen über ihre id (die Liste wächst an anderer Stelle mit)
    const sim = (id: string) => DEMO_VIEWS.find((v) => v.id === id);
    turn(277000, "Zeig mir ein Doppelpendel.", "Hier ein Doppelpendel, das chaotisch schwingt.", sim("doppelpendel"));
    turn(288000, "Wie entsteht eine stehende Welle?", "Hier zwei Wellen, die gegeneinander laufen.", sim("welle"));
    turn(299000, "Was passiert, wenn sich Planeten gegenseitig anziehen?", "Hier drei Planeten, die sich gegenseitig stören.", sim("anziehung"));
  }

  send(data: string): void {
    const msg = JSON.parse(data) as { type?: string; token?: string };
    this.sent.push(msg);
    let reply: unknown;
    if (msg.token !== this.token) reply = { ok: false, error: "unauthorized" };
    else if (msg.type === "safety.status") reply = { ok: true, kill: this.kill };
    else if (msg.type === "voice.state") reply = this.voiceReply();                                         // E3: mit wake_count/wake_last
    else if (msg.type && SETUP_TYPES.has(msg.type)) reply = this.setupReply(msg as Record<string, unknown>);   // E3
    else if (msg.type?.startsWith("voice.tuning.")) reply = this.tuningReply(msg as Record<string, unknown>);  // Mikrofon-Schwellen
    else if (msg.type === "transcript.get") {
      const since = (msg as { since?: number }).since ?? 0;
      const entries = this.entries.filter((e) => e.rev > since);                 // since ist eine rev, keine id
      reply = { ok: true, entries, last: Math.max(since, ...entries.map((e) => e.rev)) };
    }
    else if (msg.type === "safety.overview") reply = { ok: true, ...this.overview, kill: this.kill };
    else if (msg.type === "memory.search") {
      const q = ((msg as { query?: string }).query ?? "").toLowerCase();
      reply = { ok: true, facts: this.facts.filter((f) => !this.deleted.includes(f.id) && f.text.toLowerCase().includes(q)) };
    }
    else if (msg.type === "memory.update") {
      const m = msg as { id?: number; text?: string; kind?: string; confirm?: boolean };
      const f = this.facts.find((x) => x.id === m.id);
      if (m.confirm !== true) reply = { ok: false, error: "confirm_required" };
      else if (!f) reply = { ok: false, error: "not_found" };
      else { f.text = m.text ?? f.text; f.kind = m.kind ?? f.kind; f.source = "user"; reply = { ok: true, updated: m.id }; }
    }
    else if (msg.type === "memory.delete") {
      const m = msg as { id?: number; confirm?: boolean };
      if (m.confirm !== true) reply = { ok: false, error: "confirm_required" };
      else { this.deleted.push(m.id ?? -1); reply = { ok: true, deleted: m.id }; }
    }
    else if (msg.type === "system.stats" && this.system) reply = { ok: true, ...this.system };
    else if (msg.type === "usage.get" && this.usage) reply = { ok: true, ...this.usage };
    else if (msg.type === "stage.get") {
      const since = (msg as { since?: number }).since ?? 0;
      reply = { ok: true, items: this.kill ? [] : this.stage.filter((v) => (v.seq as number) > since), last: this.stageSeq };
    }
    else if (msg.type === "dashboard.get") reply = { ok: true, ...this.dash };
    else if (msg.type === "claude.folder_list") reply = { ok: true, folders: this.folders.map((n) => ({ name: n, path: `C:/proj/${n}` })) };
    else if (msg.type === "claude.folder_propose") {
      const m = msg as { name?: string; path?: string };
      if (m.path === "C:/Windows") reply = { ok: true, allowed: false, reason: "Dieser Ordner liegt in einem geschützten Bereich (System, AppData, .ssh, .claude)." };
      else { this.folderProposal = { name: m.name ?? "", path: m.path ?? "" }; reply = { ok: true, allowed: true, proposal: "f1", name: m.name, preview: `Claude darf in «${m.path}» arbeiten (Name «${m.name}»)`, expires_in: 120 }; }
    }
    else if (msg.type === "claude.folder_confirm") {
      const m = msg as { proposal?: string; confirm?: boolean };
      if (m.confirm !== true) reply = { ok: false, error: "confirm_required" };
      else if (m.proposal !== "f1" || !this.folderProposal) reply = { ok: false, error: "unknown_proposal" };
      else { this.folders.push(this.folderProposal.name); this.folderProposal = null; reply = { ok: true, folders: this.folders.map((n) => ({ name: n, path: "x" })) }; }
    }
    else if (msg.type === "claude.folder_deny") { this.folderProposal = null; reply = { ok: true, denied: true }; }
    else if (msg.type === "claude.folder_remove") {
      const n = (msg as { name?: string }).name ?? "";
      this.folders = this.folders.filter((x) => x !== n);
      reply = { ok: true, folders: this.folders.map((x) => ({ name: x, path: "x" })) };
    }
    else if (msg.type === "feedback.add") {
      const m = msg as { entry?: number; rating?: number };
      if (!this.entries.some((e) => e.id === m.entry && e.reply)) reply = { ok: false, error: "not_found" };   // wie das Backend: nur mit Antwort
      else if (this.rated.has(m.entry ?? -1)) reply = { ok: false, error: "already_rated" };
      else { this.rated.add(m.entry ?? -1); this.ratings.push({ entry: m.entry ?? -1, rating: m.rating ?? 0 }); reply = { ok: true, rated: m.entry, rating: m.rating }; }
    }
    else if (msg.type === "approvals.get") reply = { ok: true, pending: this.pending };
    else if (msg.type === "approvals.decide") {
      const m = msg as { request_id?: string; digest?: string; approve?: boolean; confirm?: boolean };
      const p = this.pending.find((x) => x.request_id === m.request_id);
      if (this.kill) reply = { ok: false, error: "kill" };
      else if (!p) reply = { ok: false, error: "none" };
      else if (m.digest !== p.digest) reply = { ok: false, error: "stale" };
      else if (m.approve && m.confirm !== true) reply = { ok: false, error: "confirm_required" };
      else { this.pending = this.pending.filter((x) => x !== p); reply = { ok: true, result: m.approve ? "allow" : "deny" }; }
    }
    else if (msg.type === "safety.kill") { this.kill = true; reply = { ok: true, kill: true }; }
    else if (msg.type === "safety.resume") reply = { ok: true, kill: (this.kill = false) };
    else reply = { ok: false, error: "unknown_type" };
    queueMicrotask(() => this.onmessage?.({ data: JSON.stringify(reply) }));
  }

  close(): void { this.stopSetupDemo(); queueMicrotask(() => this.onclose?.()); }   // E3: Vorführungs-Intervalle aufräumen
}

/** E2b: Beispiel für `usage.get` (erfundene Werte, nur im Mock), vollständig wie vom Backend: frisch (vor 2 min), veraltet
 *  (vor 3 h, stale) oder nicht verfügbar (keine Statuszeile). Die Fensterbefehle (set_compact usw.) gibt es im Browser nicht:
 *  `windowCommand` tut ohne Tauri nichts, dort schaltet nur die CSS-Klasse. */
export function usageDemo(kind: "frisch" | "alt" | "keine"): Record<string, unknown> {
  const now = Math.floor(Date.now() / 1000);
  if (kind === "keine") {
    return { available: false, model: "", context_pct: null, five_h_pct: null, seven_d_pct: null, cost_usd: null, stand: 0, stale: false };
  }
  if (kind === "alt") {
    return { available: true, model: "Opus", context_pct: 87, five_h_pct: 64, seven_d_pct: null, cost_usd: null, stand: now - 3 * 3600, stale: true };
  }
  return { available: true, model: "Opus", context_pct: 42, five_h_pct: 30, seven_d_pct: 12, cost_usd: null, stand: now - 120, stale: false };
}
// ===== E3 Setup-Assistent (Mock): Schritte, Titel und Folgen des Überspringens wie setup/status.py (plus claude, folder) =====
const SETUP_IDS = ["system", "claude", "audio_voice", "wake_words", "folder", "safety"] as const;
const SETUP_TYPES = new Set(["setup.status", "setup.skip", "setup.reopen", "setup.done", "setup.checks", "audio.devices", "audio.get",
  "audio.set", "voice.level_test", "voice.level_result", "voice.level_apply", "wake.get", "wake.set"]);
const SETUP_TITLES: Record<string, string> = { system: "Systemcheck und Vault", claude: "Claude Code", audio_voice: "Mikrofon und Lautsprecher",
  wake_words: "Wake Words", folder: "Arbeitsordner", safety: "Sicherheit und Notaus" };
const SETUP_SKIPPED: Record<string, string> = {
  system: "Kein Gedächtnis. Notaus und Sicherheitsregeln gelten weiter.",
  claude: "Ohne Claude Code bekommt kushim keine Antworten.",
  audio_voice: "Es gelten die Windows-Standardgeräte und die Standard-Pegel.",
  wake_words: "Es gelten die Standard-Wörter aus der Vorlage.",
  folder: "Claude arbeitet nur in Ordnern, die schon freigegeben sind.",
  safety: "Der Notaus wirkt trotzdem.",
};
// ===== Ende E3 =====

/** Beispiel-Ansichten für die Vorführung (erfundene Beispielwerte, nur im Mock). */
export const DEMO_VIEWS: Record<string, unknown>[] = [
  { id: "mathe-1", art: "rechnung", titel: "Quadratische Gleichung", bausteine: [
    { typ: "formel", tex: "x^2 - 5x + 6 = 0" },
    { typ: "schritte", schritte: [
      { text: "Mitternachtsformel mit a = 1, b = -5, c = 6", tex: "x_{1,2} = \\frac{5 \\pm \\sqrt{25 - 24}}{2}" },
      { text: "Wurzel ausrechnen", tex: "x_{1,2} = \\frac{5 \\pm 1}{2}" },
      { text: "Beide Lösungen", tex: "x_1 = 3,\\quad x_2 = 2" } ] },
    { typ: "ergebnis", tex: "x \\in \\{2,\\, 3\\}" } ] },
  { id: "dax", art: "markt", titel: "DAX heute (Beispielwerte)", stand: "12.11.2026 14:05", bausteine: [
    { typ: "kennzahlen", werte: [
      { name: "DAX", wert: 19420.5, einheit: "Pkt", aenderung: "+0,8 %", richtung: "auf" },
      { name: "MDAX", wert: 26110, einheit: "Pkt", aenderung: "-0,3 %", richtung: "ab" },
      { name: "Euro in Dollar", wert: 1.0721, aenderung: "±0,0 %", richtung: "gleich" } ] },
    { typ: "diagramm", form: "linie", x_titel: "Uhrzeit", y_titel: "Punkte", reihen: [
      { name: "DAX", punkte: [["09:00", 19260], ["10:00", 19310], ["11:00", 19280], ["12:00", 19350], ["13:00", 19390], ["14:00", 19420.5]] } ] },
    { typ: "tabelle", spalten: ["Titel", "Kurs", "Änderung"], zeilen: [["SAP", 231.4, "+1,9 %"], ["Siemens", 188, "+0,6 %"], ["BASF", 44.1, "-1,2 %"]] } ] },
  { id: "koffein", art: "recherche", titel: "Koffein und Schlaf", bausteine: [
    { typ: "text", absaetze: ["Kurz: Koffein am Nachmittag kann den Schlaf verkürzen; wie stark, ist von Mensch zu Mensch verschieden."] },
    { typ: "aussagen", aussagen: [
      { text: "Koffein wirkt mehrere Stunden nach.", quellen: [1, 2] },
      { text: "Später Konsum verkürzt bei vielen die Schlafdauer.", quellen: [1, 3] } ] },
    { typ: "widerspruch", aussagen: [{ text: "Wie viele Stunden Abstand nötig sind, geben die Quellen unterschiedlich an.", quellen: [2, 3] }] },
    { typ: "quellen", quellen: [
      { nr: 1, titel: "Übersichtsarbeit (Beispiel)", adresse: "beispiel.org/schlaf" },
      { nr: 2, titel: "Ratgeber (Beispiel)", adresse: "beispiel.org/koffein" },
      { nr: 3, titel: "Studie (Beispiel)" } ] } ] },
  { id: "system", art: "antwort", titel: "Systemzustand", bausteine: [{ typ: "systemzustand" }] },
  { id: "auftrag", art: "auftrag", titel: "Tests grün machen (Beispiel)", bausteine: [
    { typ: "fortschritt", hinweis: "Zwei Tests sind noch rot.", schritte: [
      { text: "Tests laufen lassen", zustand: "fertig" }, { text: "Ursache im Schema finden", zustand: "fertig" },
      { text: "Fehler beheben", zustand: "laeuft" }, { text: "Alte Ausgabe löschen", zustand: "fehler" },
      { text: "Committen", zustand: "offen" } ] },
    { typ: "zeitplan", tag: "Dienstag, 17. November", termine: [
      { von: "09:00", bis: "10:00", titel: "Team-Runde", ort: "Büro" }, { von: "09:30", bis: "11:00", titel: "Zahnarzt", ort: "" },
      { von: "13:00", bis: "14:30", titel: "Projektplanung", ort: "Video" } ] },
    { typ: "aufgaben", punkte: [{ text: "Milch kaufen", erledigt: true }, { text: "Paket abholen", erledigt: false }] } ] },
  { id: "mail", art: "mail", titel: "Mail von Anna (Beispiel)", bausteine: [
    { typ: "mail", von: "Anna Beispiel <anna@beispiel.org>", an: "", betreff: "Treffen am Dienstag", datum: "12.11.2026 09:14",
      zusammenfassung: "Anna fragt, ob das Treffen am Dienstag um 13 Uhr passt.",
      absaetze: ["Hallo,", "passt dir Dienstag um 13 Uhr für die Projektplanung? Ich würde den Raum buchen.", "Viele Grüße, Anna"] },
    { typ: "mail-entwurf", an: "anna@beispiel.org", cc: "", betreff: "Re: Treffen am Dienstag",
      absaetze: ["Hallo Anna,", "Dienstag um 13 Uhr passt. Bitte buch den Raum.", "Viele Grüße"] } ] },
  { id: "datei", art: "dokument", titel: "Übersicht: rechnen.py (Beispiel)", bausteine: [
    { typ: "text", absaetze: ["Die Datei hat zwei Funktionen: eine rechnet, eine formatiert. Neu gegenüber gestern ist nur die Prüfung auf leere Eingaben."] },
    { typ: "dokument", name: "src/rechnen.py", ausschnitt: "Zeilen 1 bis 12", gliederung: ["rechne(a, b)", "formatiere(wert)"], zeilen: [
      "def rechne(a, b):", "    if a is None or b is None:", "        return 0", "    return max(a, b)", "",
      "def formatiere(wert):", "    return f\"{wert:.2f}\"", "", "if __name__ == \"__main__\":", "    print(formatiere(rechne(2, 3)))" ] },
    { typ: "aenderung", name: "src/rechnen.py", zusammenfassung: "Leere Eingaben liefern jetzt 0 statt eines Fehlers.", bloecke: [
      { kopf: "rechne", zeilen: [
        { art: "gleich", text: "def rechne(a, b):" }, { art: "neu", text: "    if a is None or b is None:" },
        { art: "neu", text: "        return 0" }, { art: "weg", text: "    return a + b" }, { art: "neu", text: "    return max(a, b)" } ] } ] } ] },
  { id: "regal", art: "modell", titel: "Regal, vorher und nachher (Beispiel)", bausteine: [
    { typ: "szene3d", einheit: "cm", hervorheben: ["Boden 4", "Boden 3"], beschriftungen: [{ objekt: "Boden 4", text: "neu: oberster Boden" }, { objekt: "Rückwand", text: "neu: stabilisiert" }], szenen: [
      { name: "vorher", objekte: [
        { form: "box", name: "Seite links", masse: [2, 180, 30], position: [-39, 90, 0], drehung: [0, 0, 0], farbe: "text" },
        { form: "box", name: "Seite rechts", masse: [2, 180, 30], position: [39, 90, 0], drehung: [0, 0, 0], farbe: "text" },
        { form: "box", name: "Boden 1", masse: [76, 2, 30], position: [0, 2, 0], drehung: [0, 0, 0], farbe: "amber" },
        { form: "box", name: "Boden 2", masse: [76, 2, 30], position: [0, 60, 0], drehung: [0, 0, 0], farbe: "amber" },
        { form: "box", name: "Boden 3", masse: [76, 2, 30], position: [0, 118, 0], drehung: [0, 0, 0], farbe: "amber" } ] },
      { name: "nachher", objekte: [
        { form: "box", name: "Seite links", masse: [2, 180, 30], position: [-39, 90, 0], drehung: [0, 0, 0], farbe: "text" },
        { form: "box", name: "Seite rechts", masse: [2, 180, 30], position: [39, 90, 0], drehung: [0, 0, 0], farbe: "text" },
        { form: "box", name: "Boden 1", masse: [76, 2, 30], position: [0, 2, 0], drehung: [0, 0, 0], farbe: "amber" },
        { form: "box", name: "Boden 2", masse: [76, 2, 30], position: [0, 60, 0], drehung: [0, 0, 0], farbe: "amber" },
        { form: "box", name: "Boden 3", masse: [76, 2, 30], position: [0, 130, 0], drehung: [0, 0, 0], farbe: "amber" },
        { form: "box", name: "Boden 4", masse: [76, 2, 30], position: [0, 178, 0], drehung: [0, 0, 0], farbe: "arc" },
        { form: "box", name: "Rückwand", masse: [76, 176, 1], position: [0, 90, -15], drehung: [0, 0, 0], farbe: "gedaempft" } ] } ] } ] },
  { id: "grundriss", art: "plan", titel: "Grundriss Wohnzimmer (Beispiel)", bausteine: [
    { typ: "plan2d", einheit: "cm", ebenen: ["Wände", "Möbel", "Maße"], elemente: [
      { art: "rechteck", ebene: "Wände", x: 0, y: 0, b: 500, h: 400 },
      { art: "linie", ebene: "Wände", von: [200, 0], bis: [200, 120] },
      { art: "bogen", ebene: "Wände", x: 200, y: 0, r: 90, von: 0, bis: 90 },
      { art: "rechteck", ebene: "Möbel", x: 30, y: 250, b: 200, h: 90 },
      { art: "kreis", ebene: "Möbel", x: 380, y: 200, r: 55 },
      { art: "text", ebene: "Möbel", x: 60, y: 285, text: "Sofa" },
      { art: "text", ebene: "Möbel", x: 345, y: 195, text: "Tisch" },
      { art: "mass", ebene: "Maße", von: [0, -30], bis: [500, -30] },
      { art: "mass", ebene: "Maße", von: [530, 0], bis: [530, 400], text: "4 m (Wunsch)" } ] } ] },
  // P6a: Vergleich, Zeitstrahl, Gegenüberstellung, Lernkarten, Quiz, Anleitung (vollständig wie nach der Backend-Prüfung)
  { id: "vergleich", art: "antwort", titel: "Bahn oder Auto nach Hamburg (Beispiel)", bausteine: [
    { typ: "vergleich", optionen: ["Bahn", "Auto", "Fernbus"], kriterien: [
      { name: "Fahrzeit", werte: ["3:40 h", "4:50 h", "6:10 h"] },
      { name: "Kosten in Euro", werte: [59.9, 92, 24.99] },
      { name: "Arbeiten unterwegs", werte: ["gut", "nein", "eingeschränkt"] } ],
      vorteile: [["schnell", "arbeiten möglich"], ["flexibel vor Ort"], ["günstig"]],
      nachteile: [["Verspätungen möglich"], ["Stau", "Parkplatzsuche"], []],
      fazit: "Für eine Tagesreise allein ist die Bahn am bequemsten." } ] },
  { id: "zeitstrahl", art: "recherche", titel: "Geschichte des Buchdrucks (Beispiel)", bausteine: [
    { typ: "zeitstrahl", einheit: "Jahren nach Christus", ereignisse: [
      { zeit: "um 1450", titel: "Gutenberg druckt mit beweglichen Lettern", text: "In Mainz entsteht ein Verfahren mit Metall-Lettern." },
      { zeit: "1455", titel: "Gutenberg-Bibel fertig", text: "" },
      { zeit: "1501", titel: "Ende der Inkunabelzeit", text: "Frühdrucke bis 1500 heißen Inkunabeln." },
      { zeit: "1811", titel: "Schnellpresse von Koenig", text: "Dampfbetrieben, viel schneller als die Handpresse." } ] } ] },
  { id: "uebersetzung", art: "antwort", titel: "Sätze für die Reise (Beispiel)", bausteine: [
    { typ: "gegenueber", sprachen: ["Deutsch", "Arabisch"], paare: [
      { original: "Guten Morgen", uebersetzung: "صباح الخير" },
      { original: "Danke", uebersetzung: "شكرا" },
      { original: "Wo ist der Bahnhof?", uebersetzung: "أين محطة القطار؟" } ] } ] },
  { id: "lernen", art: "lernen", titel: "Hauptstädte üben (Beispiel)", bausteine: [
    { typ: "lernkarten", karten: [
      { frage: "Hauptstadt von Portugal?", antwort: "Lissabon" },
      { frage: "Hauptstadt von Kanada?", antwort: "Ottawa" },
      { frage: "Hauptstadt von Australien?", antwort: "Canberra" } ] },
    { typ: "quiz", fragen: [
      { frage: "Welche Stadt ist die Hauptstadt der Schweiz?", optionen: ["Zürich", "Bern", "Genf"], richtig: 1,
        erklaerung: "Bern ist Bundesstadt und Sitz der Regierung." },
      { frage: "Welcher Fluss fließt durch Wien?", optionen: ["Donau", "Rhein", "Elbe", "Moldau"], richtig: 0, erklaerung: "" } ] } ] },
  { id: "anleitung", art: "lernen", titel: "Pfannkuchen backen (Beispiel)", bausteine: [
    { typ: "anleitung", aktuell: 0, schritte: [
      { titel: "Zutaten bereitstellen", text: "250 g Mehl, 3 Eier, 500 ml Milch, eine Prise Salz.", sekunden: 0 },
      { titel: "Teig rühren", text: "Alles glatt rühren, bis keine Klümpchen mehr da sind.", sekunden: 0 },
      { titel: "Teig ruhen lassen", text: "Den Teig abgedeckt ruhen lassen.", sekunden: 300 },
      { titel: "Ausbacken", text: "Wenig Fett in die Pfanne, je Seite etwa eine Minute.", sekunden: 60 } ] } ] },
  // P6b: Diagramme (Ablauf mit Entscheidung und Rückweg, Organigramm, Mindmap), vollständig wie nach der Backend-Prüfung
  { id: "ablauf", art: "netz", titel: "Bestellung bearbeiten (Beispiel)", bausteine: [
    { typ: "netz", form: "ablauf", knoten: [
      { id: "s", text: "Bestellung eingegangen", art: "start" },
      { id: "p", text: "Ware auf Lager?", art: "entscheidung" },
      { id: "v", text: "Ware versenden", art: "schritt" },
      { id: "n", text: "Ware nachbestellen", art: "schritt" },
      { id: "w", text: "Lieferung abwarten", art: "" },
      { id: "r", text: "Rechnung schicken", art: "schritt" },
      { id: "e", text: "Fertig", art: "ende" } ],
    kanten: [
      { von: "s", bis: "p", text: "" }, { von: "p", bis: "v", text: "ja" }, { von: "p", bis: "n", text: "nein" },
      { von: "n", bis: "w", text: "" }, { von: "w", bis: "p", text: "erneut prüfen" },
      { von: "v", bis: "r", text: "" }, { von: "r", bis: "e", text: "" } ] } ] },
  { id: "organigramm", art: "netz", titel: "Aufbau der Firma (Beispiel)", bausteine: [
    { typ: "netz", form: "baum", knoten: [
      { id: "gf", text: "Geschäftsführung", art: "" }, { id: "ve", text: "Vertrieb", art: "" }, { id: "en", text: "Entwicklung", art: "" },
      { id: "vw", text: "Verwaltung", art: "" }, { id: "in", text: "Innendienst", art: "" }, { id: "au", text: "Außendienst", art: "" },
      { id: "so", text: "Software", art: "" }, { id: "hw", text: "Hardware", art: "" }, { id: "te", text: "Test und Qualität", art: "" },
      { id: "pe", text: "Personal", art: "" }, { id: "bu", text: "Buchhaltung", art: "" } ],
    kanten: [
      { von: "gf", bis: "ve", text: "" }, { von: "gf", bis: "en", text: "" }, { von: "gf", bis: "vw", text: "" },
      { von: "ve", bis: "in", text: "" }, { von: "ve", bis: "au", text: "" },
      { von: "en", bis: "so", text: "" }, { von: "en", bis: "hw", text: "" }, { von: "en", bis: "te", text: "" },
      { von: "vw", bis: "pe", text: "" }, { von: "vw", bis: "bu", text: "" } ] } ] },
  { id: "mindmap", art: "netz", titel: "Urlaub planen (Beispiel)", bausteine: [
    { typ: "netz", form: "mindmap", knoten: [
      { id: "u", text: "Urlaub planen", art: "" },
      { id: "z", text: "Reiseziel", art: "" }, { id: "z1", text: "Strand", art: "" }, { id: "z2", text: "Berge", art: "" },
      { id: "b", text: "Budget", art: "" }, { id: "b1", text: "Flug", art: "" }, { id: "b2", text: "Unterkunft", art: "" },
      { id: "p", text: "Packliste", art: "" }, { id: "p1", text: "Kleidung", art: "" }, { id: "p2", text: "Ausweis und Karten", art: "" },
      { id: "t", text: "Termine", art: "" }, { id: "t1", text: "Urlaubsantrag", art: "" } ],
    kanten: [
      { von: "u", bis: "z", text: "" }, { von: "z", bis: "z1", text: "" }, { von: "z", bis: "z2", text: "" },
      { von: "u", bis: "b", text: "" }, { von: "b", bis: "b1", text: "" }, { von: "b", bis: "b2", text: "" },
      { von: "u", bis: "p", text: "" }, { von: "p", bis: "p1", text: "" }, { von: "p", bis: "p2", text: "" },
      { von: "u", bis: "t", text: "" }, { von: "t", bis: "t1", text: "" } ] } ] },
  // P5a: Simulationen (Pendel, Wurf, Gas), genau wie nach der Backend-Prüfung: alle Felder mit Standardwerten, stand "" und schliessen false
  { id: "pendel", art: "simulation", titel: "Pendel, 1 m (Beispiel)", stand: "", schliessen: false, bausteine: [
    { typ: "simulation", modell: "pendel", parameter: { laenge: 1, winkel: 30, anfangsgeschwindigkeit: 0, daempfung: 0, g: 9.81 },
      laufzeit: 30, tempo: 0, spur: true, beschreibung: "Ein Fadenpendel ohne Reibung, losgelassen bei 30 Grad." } ] },
  { id: "wurf", art: "simulation", titel: "Schräger Wurf (Beispiel)", stand: "", schliessen: false, bausteine: [
    { typ: "simulation", modell: "wurf", parameter: { geschwindigkeit: 20, winkel: 45, hoehe: 1.5, g: 9.81, luftwiderstand: 0 },
      laufzeit: 30, tempo: 0, spur: true, beschreibung: "Ein Ball, aus 1,5 m Höhe mit 20 m/s unter 45 Grad geworfen, ohne Luftwiderstand." } ] },
  { id: "gas", art: "simulation", titel: "Gas im Kasten (Beispiel)", stand: "", schliessen: false, bausteine: [
    { typ: "simulation", modell: "gas",
      parameter: { anzahl: 60, kasten: [100, 60], radius: 1.5, geschwindigkeit: 0.5, schwerkraft: 0, stoesse: true, startwert: 7 },
      laufzeit: 30, tempo: 0, spur: true, beschreibung: "60 gleich schnelle Teilchen stoßen sich; die Geschwindigkeiten verteilen sich mit der Zeit." } ] },
  // P5b: Doppelpendel, stehende Welle, Umlauf mit Anziehung; genau wie nach der Backend-Prüfung (routine/p5b-schema, validate(view) == view)
  { id: "doppelpendel", art: "simulation", titel: "Doppelpendel (Beispiel)", stand: "", schliessen: false, bausteine: [
    { typ: "simulation", modell: "doppelpendel",
      parameter: { laenge1: 1, laenge2: 1, masse1: 1, masse2: 1, winkel1: 120, winkel2: -10, g: 9.81, daempfung: 0 },
      laufzeit: 30, tempo: 0, spur: true, beschreibung: "Zwei gleich lange Arme mit gleichen Massen, oben bei 120 Grad und unten bei -10 Grad losgelassen, ohne Reibung." } ] },
  { id: "welle", art: "simulation", titel: "Stehende Welle (Beispiel)", stand: "", schliessen: false, bausteine: [
    { typ: "simulation", modell: "welle",
      parameter: { wellen: [
        { amplitude: 1, wellenlaenge: 2, frequenz: 0.5, phase: 0, richtung: "rechts" },
        { amplitude: 1, wellenlaenge: 2, frequenz: 0.5, phase: 0, richtung: "links" } ], bereich: 0 },
      laufzeit: 30, tempo: 0, spur: true, beschreibung: "Zwei gleiche Wellen laufen gegeneinander. Zusammen entsteht eine stehende Welle: Manche Stellen bewegen sich nie." } ] },
  { id: "anziehung", art: "simulation", titel: "Drei Planeten, die sich anziehen (Beispiel)", stand: "", schliessen: false, bausteine: [
    { typ: "simulation", modell: "umlauf",
      parameter: { zentralmasse: 1, koerper: [
        { name: "Innen", abstand: 1, exzentrizitaet: 0, phase: 0, masse: 0.001, farbe: "arc" },
        { name: "Mitte", abstand: 1.6, exzentrizitaet: 0.05, phase: 120, masse: 0.003, farbe: "amber" },
        { name: "Außen", abstand: 2.5, exzentrizitaet: 0.1, phase: 240, masse: 0.001, farbe: "ok" } ], anziehung: true },
      laufzeit: 30, tempo: 0, spur: true, beschreibung: "Ein sonnenähnlicher Stern in der Mitte und drei Planeten mit einigen Jupitermassen. Die Planeten stören ihre Bahnen gegenseitig." } ] },
];

/** P5b: Teilchen (Wasser mit Bindungen, Ethanol ohne Bindungen, Natrium-Atom, Orbital 2p_z), genau wie nach der Backend-Prüfung:
 *  alle Felder mit Standardwerten, stand "" und schliessen false. Eigene Liste, damit die Zählung der übrigen Beispiele gleich bleibt;
 *  die Vorführung zeigt sie nach den übrigen Beispielen. Lagen in Ångström. */
export const TEILCHEN_DEMOS: Record<string, unknown>[] = [
  { id: "wasser", art: "teilchen", titel: "Wasser (Beispiel)", stand: "", schliessen: false, bausteine: [
    { typ: "teilchen", form: "molekuel", name: "Wasser", atome: [
      { element: "O", position: [0, 0, 0.1173] },
      { element: "H", position: [0, 0.7572, -0.4692] },
      { element: "H", position: [0, -0.7572, -0.4692] } ],
      bindungen: [{ von: 0, bis: 1, ordnung: 1 }, { von: 0, bis: 2, ordnung: 1 }],
      beschriftungen: [{ atom: 0, text: "Sauerstoff, leicht negativ" }], darstellung: "kugel-stab" } ] },
  { id: "ethanol", art: "teilchen", titel: "Ethanol (Beispiel)", stand: "", schliessen: false, bausteine: [
    { typ: "teilchen", form: "molekuel", name: "Ethanol", atome: [
      { element: "C", position: [1.1879, -0.3829, 0] },
      { element: "C", position: [0, 0.5526, 0] },
      { element: "O", position: [-1.1867, -0.2472, 0] },
      { element: "H", position: [2.0939, 0.2191, 0] },
      { element: "H", position: [1.1757, -1.0213, 0.8812] },
      { element: "H", position: [1.1757, -1.0213, -0.8812] },
      { element: "H", position: [0.0258, 1.1997, 0.8794] },
      { element: "H", position: [0.0258, 1.1997, -0.8794] },
      { element: "H", position: [-1.9447, 0.3544, 0] } ],
      bindungen: [], beschriftungen: [], darstellung: "kugel-stab" } ] },
  { id: "natrium", art: "teilchen", titel: "Natrium-Atom (Beispiel)", stand: "", schliessen: false, bausteine: [
    { typ: "teilchen", form: "atom", element: "Na", neutronen: 12, ladung: 0, schalen: [2, 8, 1] } ] },
  { id: "orbital-2pz", art: "teilchen", titel: "Orbital 2p_z (Beispiel)", stand: "", schliessen: false, bausteine: [
    { typ: "teilchen", form: "orbital", orbital: "2p_z", punkte: 2500, startwert: 1 } ] },
];
