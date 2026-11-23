import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import {
  BROKEN_FILE, levelToSens, meterPct, MicTuning, NOTE_NOW, NOT_RUNNING, parseBound, parseTuning, SAVE_NOTE, SEND_DELAY_MS, sensToLevel, TUNING_IDLE_MS,
  TUNING_POLL_MS, tuningError,
} from "./components/MicTuning";
import { ApiClient } from "./lib/api";
import { STATE_VIEW } from "./lib/avatarState";
import { MockSocket } from "./lib/mock";

/** Kasten „Mikrofon“ (voice.tuning.*) gegen das gefälschte Backend. Zeitgeber gefälscht: Entprellen und Abfrage genau prüfbar. */

const TOKEN = "t".repeat(43);
type Msg = Record<string, unknown> & { type: string };

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
});

const tick = (ms = 0) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

async function mount(prep?: (m: MockSocket) => void, props: { kill?: boolean; visible?: boolean } = {}) {
  vi.useFakeTimers();
  let sock!: MockSocket;
  const client = new ApiClient({ port: 5000, token: TOKEN }, (u) => { sock = new MockSocket(u, TOKEN); prep?.(sock); return sock; });
  await client.connect();
  render(<MicTuning client={{ current: client }} connected kill={props.kill ?? false} visible={props.visible ?? true} />);
  await tick();
  const sent = (type?: string) => (sock.sent as Msg[]).filter((m) => !type || m.type === type);
  return { sock, sent };
}

const box = () => within(screen.getByRole("region", { name: "Mikrofon" }));
const slider = (name: string) => box().getByLabelText(name) as HTMLInputElement;
const btn = (name: string) => box().getByRole("button", { name }) as HTMLButtonElement;
const click = async (el: HTMLElement) => { await act(async () => { fireEvent.click(el); }); await tick(); };

describe("Umrechnung Regler und Schwelle", () => {
  it("nach rechts wird es empfindlicher: die Schwelle sinkt, ganz links die obere, ganz rechts die untere Grenze", () => {
    expect(sensToLevel(0, [80, 600])).toBe(600);
    expect(sensToLevel(100, [80, 600])).toBe(80);
    expect(sensToLevel(0, [150, 1500])).toBe(1500);
    expect(sensToLevel(100, [150, 1500])).toBe(150);
    for (let p = 1; p <= 100; p++) expect(sensToLevel(p, [80, 600])).toBeLessThan(sensToLevel(p - 1, [80, 600]));
  });

  it("Hin und zurück ergibt dieselbe Reglerstellung, Werte außerhalb werden an die Grenzen gelegt", () => {
    for (const b of [[80, 600], [150, 1500]] as [number, number][]) {
      for (let p = 0; p <= 100; p++) expect(levelToSens(sensToLevel(p, b), b)).toBe(p);
    }
    expect(levelToSens(600, [80, 600])).toBe(0);
    expect(levelToSens(80, [80, 600])).toBe(100);
    expect(levelToSens(5000, [80, 600])).toBe(0);
    expect(levelToSens(1, [80, 600])).toBe(100);
    expect(levelToSens(200, [80, 600])).toBe(55);           // ln(600/200) / ln(600/80) = 0,545
  });

  it("Pegelbalken logarithmisch von 10 bis 32.767 (Rohwert)", () => {
    expect(meterPct(10)).toBe(0);
    expect(meterPct(0)).toBe(0);
    expect(meterPct(Number.NaN)).toBe(0);
    const decade = 100 / Math.log10(32_767 / 10);
    expect(meterPct(100)).toBeCloseTo(decade, 6);
    expect(meterPct(1000)).toBeCloseTo(2 * decade, 6);
    expect(meterPct(10_000)).toBeCloseTo(3 * decade, 6);
    expect(meterPct(10_000)).toBeLessThan(90);
    expect(meterPct(32_767)).toBe(100);
    expect(meterPct(40_000)).toBe(100);
  });
});

describe("Antwort des Backends prüfen", () => {
  const reply = (extra: Record<string, unknown>) => ({
    ok: true as const, active: true, values: { speech_level: 142.9, barge_in_level: 178.6, barge_in_ms: 240, end_silence_seconds: 0.9 },
    file_values: { speech_level: 200, barge_in_level: 250, barge_in_ms: 240, end_silence_seconds: 0.9 },
    bounds: { speech_level: { min: 80, max: 600 }, barge_in_level: { min: 150, max: 1500 }, barge_in_ms: { min: 160, max: 400 },
      end_silence_seconds: { min: 0.6, max: 3 }, step: { min: -2, max: 2 } },
    step: 1, rms: 512.3, peak: 1800.5, last_source: "voice", version: 7, ...extra });

  it("Grenzen in beiden Formen: {min, max} (Backend) und [min, max]; Unbrauchbares fällt auf den Vertrag zurück", () => {
    expect(parseBound({ min: 80, max: 600 })).toEqual([80, 600]);
    expect(parseBound([80, 600])).toEqual([80, 600]);
    for (const bad of [{ min: 600, max: 80 }, [1, 2, 3], { min: "80", max: 600 }, null, 5, { min: 0, max: 10 }, { min: 80 }]) {
      expect(parseBound(bad)).toBeNull();
    }
    const s = parseTuning(reply({}))!;
    expect(s.bounds).toEqual({ speech_level: [80, 600], barge_in_level: [150, 1500], barge_in_ms: [160, 400], end_silence_seconds: [0.6, 3] });
    expect(s.version).toBe(7);
    expect(s.step).toBe(1);
    expect(parseTuning(reply({ bounds: { speech_level: [100, 500], barge_in_level: { min: 1, max: 0 } } }))!.bounds)
      .toEqual({ speech_level: [100, 500], barge_in_level: [150, 1500], barge_in_ms: [160, 400], end_silence_seconds: [0.6, 3] });
  });

  it("Pegel sind Rohwerte von 0 bis 32767; ohne Sprachdienst immer 0", () => {
    expect(parseTuning(reply({ rms: 40_000, peak: -5 }))).toMatchObject({ rms: 32_767, peak: 0 });
    expect(parseTuning(reply({ active: false, rms: 300, peak: 900 }))).toMatchObject({ rms: 0, peak: 0 });
  });

  it("Werte null nur ohne Sprachdienst (Datei fehlerhaft); mit Sprachdienst ist das keine gültige Antwort", () => {
    expect(parseTuning(reply({ active: false, values: null, file_values: null }))).toMatchObject({ active: false, values: null, file_values: null });
    expect(parseTuning(reply({ values: null, file_values: null }))).toBeNull();
    expect(parseTuning(reply({ active: false, values: { speech_level: "x" } }))).toBeNull();
    expect(parseTuning(reply({ active: "ja" }))).toBeNull();
    expect(parseTuning({ ok: false, error: "kill" })).toBeNull();
  });

  it("klare Texte für alle Fehler des Backends, ohne Fachbegriffe", () => {
    const all = ["invalid", "kill", "unavailable", "bad_request", "confirm_required", "broken_file", "not_saved", "offline", "timeout", "unknown_type", "was"];
    for (const e of all) {
      const t = tuningError(e);
      expect(t.length).toBeGreaterThan(10);
      expect(t).not.toMatch(/bad_request|confirm_required|broken_file|not_saved|invalid|unavailable|Error|Fehlercode/);
    }
    expect(tuningError("bad_request")).toBe("kushim hat die Anfrage nicht verstanden. Nichts wurde geändert. Lade das Fenster neu.");
    expect(tuningError("confirm_required")).toBe("Die Bestätigung fehlte. Nichts wurde geändert. Versuch es noch einmal.");
    expect(tuningError("broken_file")).toMatch(/^wakewords\.toml ist fehlerhaft und wurde nicht überschrieben\./);
    expect(tuningError("not_saved")).toMatch(/^Speichern hat nicht geklappt: wakewords\.toml ließ sich nicht schreiben\./);
  });
});

describe("Kasten Mikrofon", () => {
  it("zeigt Werte, Marken, Pegel und Hinweis; Zustand als Wort", async () => {
    await mount();
    expect(box().getByText("live")).toBeInTheDocument();
    expect(box().getByText("Sprechen ab 200")).toBeInTheDocument();
    expect(box().getByText("Unterbrechen ab 250")).toBeInTheDocument();
    expect(box().getByText("Schwelle 200")).toBeInTheDocument();
    expect(box().getByText("Schwelle 250")).toBeInTheDocument();
    expect(box().getByText(/^RMS \d/)).toBeInTheDocument();
    expect(box().getByText(/^Spitze \d/)).toBeInTheDocument();
    expect(box().getByText(NOTE_NOW)).toBeInTheDocument();
    expect(slider("Empfindlichkeit Sprechen").value).toBe(String(levelToSens(200, [80, 600])));
    expect(slider("Empfindlichkeit Sprechen")).toHaveAttribute("aria-valuetext", "Schwelle 200, nach rechts empfindlicher");
    const meter = box().getByRole("meter", { name: /Mikrofonpegel/ });
    expect(meter.getAttribute("aria-valuetext")).toMatch(/^RMS \d+, Spitze \d+/);
    expect(document.querySelectorAll(".mic-mark")).toHaveLength(2);
    // Erweitert: eingeklappt, Pause bis Satzende mit Dateiwert 2,5 s, Mindestdauer 240 ms
    const adv = box().getByText("Erweitert").closest("details")!;
    expect(adv.open).toBe(false);
    expect(slider("Pause bis Satzende")).toHaveAttribute("min", "0.6");
    expect(slider("Pause bis Satzende")).toHaveAttribute("max", "3");
    expect(slider("Pause bis Satzende")).toHaveAttribute("step", "0.1");
    expect(slider("Pause bis Satzende").value).toBe("2.5");
    expect(box().getByText("2,5 s")).toBeInTheDocument();
    expect(slider("Mindestdauer Unterbrechen")).toHaveAttribute("min", "160");
    expect(slider("Mindestdauer Unterbrechen")).toHaveAttribute("max", "400");
    expect(box().getByText("240 ms")).toBeInTheDocument();
    // nichts verstellt: Standard und Merken haben nichts zu tun
    expect(btn("Standard")).toBeDisabled();
    expect(btn("Merken")).toBeDisabled();
  });

  it("keine Wirkung ohne Klick: beim Laden und Abfragen nur get, kein set, kein Speicher, kein Netz, kein Ton", async () => {
    const store = vi.spyOn(Storage.prototype, "setItem");
    const net = vi.fn();
    vi.stubGlobal("fetch", net);
    const audio = vi.fn();
    vi.stubGlobal("AudioContext", audio);
    const { sent } = await mount();
    await tick(2000);
    expect(sent().length).toBeGreaterThan(3);
    expect(new Set(sent().map((m) => m.type))).toEqual(new Set(["voice.tuning.get"]));
    expect(store).not.toHaveBeenCalled();
    expect(net).not.toHaveBeenCalled();
    expect(audio).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("Regler nach rechts: entprellt genau ein set mit niedrigerer Schwelle, erst nach der Tastenpause", async () => {
    const { sock, sent } = await mount();
    const s = slider("Empfindlichkeit Sprechen");
    const start = Number(s.value);
    for (const p of [start + 2, start + 5, start + 10]) {
      await act(async () => { fireEvent.change(s, { target: { value: String(p) } }); });
      await tick(100);                                 // Pause unter 200 ms: noch nichts senden
    }
    expect(sent("voice.tuning.set")).toHaveLength(0);
    expect(box().getByText(`Schwelle ${sensToLevel(start + 10, [80, 600])} (Datei 200)`)).toBeInTheDocument();   // Zahl folgt sofort
    await tick(99);
    expect(sent("voice.tuning.set")).toHaveLength(0);
    await tick(10);
    const sets = sent("voice.tuning.set");
    expect(sets).toHaveLength(1);
    expect(sets[0]).toMatchObject({ confirm: true, values: { speech_level: sensToLevel(start + 10, [80, 600]) } });
    expect(Object.keys(sets[0].values as object)).toEqual(["speech_level"]);
    expect(sensToLevel(start + 10, [80, 600])).toBeLessThan(200);
    expect(sock.tuningValues.speech_level).toBe(sensToLevel(start + 10, [80, 600]));
    await tick(1000);
    expect(sent("voice.tuning.set")).toHaveLength(1);
  });

  it("mit der Maus: erst beim Loslassen senden, beide Regler eines Zugs in einem set", async () => {
    const { sent } = await mount();
    const a = slider("Empfindlichkeit Sprechen"), b = slider("Empfindlichkeit Unterbrechen");
    fireEvent.pointerDown(a);
    await act(async () => { fireEvent.change(a, { target: { value: "80" } }); });
    await tick(1000);                                  // noch gedrückt: nichts senden
    expect(sent("voice.tuning.set")).toHaveLength(0);
    fireEvent.pointerDown(b);
    await act(async () => { fireEvent.change(b, { target: { value: "70" } }); });
    await act(async () => { window.dispatchEvent(new Event("pointerup")); });
    expect(sent("voice.tuning.set")).toHaveLength(0);
    await tick(210);
    const sets = sent("voice.tuning.set");
    expect(sets).toHaveLength(1);
    expect(sets[0].values).toEqual({ speech_level: sensToLevel(80, [80, 600]), barge_in_level: sensToLevel(70, [150, 1500]) });
  });

  it("Erweitert: Pause bis Satzende in Schritten von 0,1 s", async () => {
    const { sent } = await mount();
    await act(async () => { fireEvent.change(slider("Pause bis Satzende"), { target: { value: "1.2" } }); });
    await tick(210);
    expect(sent("voice.tuning.set")[0]).toMatchObject({ confirm: true, values: { end_silence_seconds: 1.2 } });
    expect(box().getByText("1,2 s (Datei 2,5 s)")).toBeInTheDocument();
  });

  it("per Stimme verstellt: „per Stimme: Stufe +1“; „Standard“ setzt mit confirm zurück", async () => {
    const { sock, sent } = await mount((m) => m.voiceTune(1));
    expect(sock.tuningValues.speech_level).toBe(142.9);                // 200 / 1,4, auf 0,1 gerundet (wie das Backend)
    expect(box().getByText("per Stimme: Stufe +1")).toBeInTheDocument();
    expect(box().getByText("Sprechen ab 143")).toBeInTheDocument();
    expect(box().getByText("Unterbrechen ab 179")).toBeInTheDocument();
    expect(box().getByText("Schwelle 143 (Datei 200)")).toBeInTheDocument();
    await click(btn("Standard"));
    expect(sent("voice.tuning.reset")).toEqual([expect.objectContaining({ type: "voice.tuning.reset", confirm: true })]);
    expect(sock.tuningValues.speech_level).toBe(200);
    expect(box().getByText("Zurück auf die Werte aus wakewords.toml.")).toBeInTheDocument();
    expect(box().queryByText(/per Stimme/)).toBeNull();                // sofort aus der Antwort von reset, nicht erst beim nächsten get
    await tick(TUNING_POLL_MS);
    expect(box().queryByText(/per Stimme/)).toBeNull();
    expect(box().getByText("Sprechen ab 200")).toBeInTheDocument();
    expect(sent("voice.tuning.save")).toHaveLength(0);
    expect(sent("voice.tuning.set")).toHaveLength(0);
  });

  it("Stufe negativ mit Minuszeichen", async () => {
    await mount((m) => m.voiceTune(-2));
    expect(box().getByText("per Stimme: Stufe −2")).toBeInTheDocument();
  });

  it("„Merken“ fragt erst im Kasten nach (Hinweis auf wakewords.toml), Abbrechen sendet nichts, Bestätigen speichert", async () => {
    const { sock, sent } = await mount((m) => m.voiceTune(1));
    await click(btn("Merken"));
    const ask = box().getByRole("alertdialog", { name: "Werte dauerhaft merken?" });
    expect(within(ask).getByText(SAVE_NOTE)).toBeInTheDocument();
    expect(SAVE_NOTE).toBe("Gilt dauerhaft, schreibt wakewords.toml (mit Sicherung).");
    expect(document.activeElement).toBe(within(ask).getByRole("button", { name: "Abbrechen" }));
    expect(sent("voice.tuning.save")).toHaveLength(0);
    await click(within(ask).getByRole("button", { name: "Abbrechen" }));
    expect(box().queryByRole("alertdialog")).toBeNull();
    expect(document.activeElement).toBe(btn("Merken"));
    expect(sent("voice.tuning.save")).toHaveLength(0);
    // Esc schließt ebenfalls ohne Wirkung
    await click(btn("Merken"));
    await act(async () => { fireEvent.keyDown(box().getByRole("alertdialog"), { key: "Escape" }); });
    expect(box().queryByRole("alertdialog")).toBeNull();
    expect(sent("voice.tuning.save")).toHaveLength(0);
    // Strg+Esc gehört dem Browser: der Dialog bleibt offen
    await click(btn("Merken"));
    await act(async () => { fireEvent.keyDown(box().getByRole("alertdialog"), { key: "Escape", ctrlKey: true }); });
    expect(box().getByRole("alertdialog")).toBeInTheDocument();
    await click(within(box().getByRole("alertdialog")).getByRole("button", { name: "Dauerhaft merken" }));
    expect(sent("voice.tuning.save")).toEqual([expect.objectContaining({ type: "voice.tuning.save", confirm: true })]);
    expect(sock.tuningSaves).toBe(1);
    expect(sock.tuningFile.speech_level).toBe(142.9);
    expect(box().getByRole("status")).toHaveTextContent(
      "Gemerkt, die alte Datei liegt als wakewords.toml.bak daneben. Die Werte gelten jetzt auch nach dem Neustart.");
    expect(btn("Merken")).toBeDisabled();             // Datei und aktive Werte sind jetzt gleich
    expect(document.activeElement).toBe(box().getByRole("heading", { name: "Mikrofon" }));   // nicht auf BODY fallen lassen
  });

  it("„Merken“ ohne vorhandene Datei: backup false, das wird ehrlich gesagt", async () => {
    const { sock } = await mount((m) => { m.voiceTune(1); m.tuningNoFile = true; });
    await click(btn("Merken"));
    await click(within(box().getByRole("alertdialog")).getByRole("button", { name: "Dauerhaft merken" }));
    expect(sock.tuningSaves).toBe(1);
    expect(box().getByRole("status")).toHaveTextContent("Eine Sicherung gab es nicht, weil wakewords.toml noch fehlte.");
  });

  it("set übernimmt den Stand aus der Antwort (version steigt), ohne auf das nächste get zu warten", async () => {
    const { sock, sent } = await mount();
    await act(async () => { fireEvent.change(slider("Empfindlichkeit Unterbrechen"), { target: { value: "100" } }); });
    await tick(SEND_DELAY_MS + 1);
    expect(sent("voice.tuning.set")[0]).toMatchObject({ values: { barge_in_level: 150 } });
    expect(sock.tuningVersion).toBe(1);
    expect(box().getByText("Unterbrechen ab 150")).toBeInTheDocument();
    expect(box().getByText("Schwelle 150 (Datei 250)")).toBeInTheDocument();
    expect(btn("Merken")).toBeEnabled();
  });

  it.each([
    ["invalid", "Dieser Wert ist nicht erlaubt. Nichts wurde geändert."],
    ["kill", "Notaus ist aktiv. Nichts wurde geändert."],
    ["unavailable", "Der Sprachdienst läuft nicht. Nichts wurde geändert. Starte ihn mit „kushim talk“."],
    ["bad_request", "kushim hat die Anfrage nicht verstanden. Nichts wurde geändert. Lade das Fenster neu."],
    ["confirm_required", "Die Bestätigung fehlte. Nichts wurde geändert. Versuch es noch einmal."],
  ] as const)("set mit Fehler %s: klare Meldung, Wert springt zurück", async (error, text) => {
    const { sock } = await mount();
    sock.tuningFail = error;
    await act(async () => { fireEvent.change(slider("Empfindlichkeit Sprechen"), { target: { value: "90" } }); });
    await tick(210);
    expect(box().getByRole("status")).toHaveTextContent(text);
    expect(box().getByText("Schwelle 200")).toBeInTheDocument();
    expect(sock.tuningValues.speech_level).toBe(200);
  });

  it("Mock prüft wie das Backend: Form zuerst (bad_request), dann Grenzen (invalid), barge_in_ms ganzzahlig", async () => {
    const { sock } = await mount();
    const ask = (msg: Record<string, unknown>) => new Promise<unknown>((resolve) => {
      sock.onmessage = (e) => resolve(JSON.parse(String(e.data)));
      sock.send(JSON.stringify({ type: "voice.tuning.set", token: TOKEN, confirm: true, ...msg }));
    });
    expect(await ask({ values: { speech_level: 5000 } })).toEqual({ ok: false, error: "invalid" });
    expect(await ask({ values: { barge_in_ms: 240.5 } })).toEqual({ ok: false, error: "invalid" });
    expect(await ask({ values: { lautstaerke: 3 } })).toEqual({ ok: false, error: "bad_request" });
    expect(await ask({ values: { speech_level: "200" } })).toEqual({ ok: false, error: "bad_request" });
    expect(await ask({ values: {} })).toEqual({ ok: false, error: "bad_request" });
    expect(await ask({ values: { speech_level: 300 }, confirm: false })).toEqual({ ok: false, error: "confirm_required" });
    const ok = await ask({ values: { speech_level: 300 } }) as Record<string, unknown>;
    expect(ok).toMatchObject({ ok: true, active: true, version: 1, last_source: "ui", values: { speech_level: 300 } });
    expect((ok.bounds as Record<string, unknown>).speech_level).toEqual({ min: 80, max: 600 });
    expect((ok.bounds as Record<string, unknown>).step).toEqual({ min: -2, max: 2 });
  });

  it.each([
    ["kill", "Notaus ist aktiv. Nichts wurde gespeichert."],
    ["broken_file", "wakewords.toml ist fehlerhaft und wurde nicht überschrieben. Prüfe die Datei, dann noch einmal merken."],
    ["not_saved", "Speichern hat nicht geklappt: wakewords.toml ließ sich nicht schreiben. Bis zum Neustart gelten die eingestellten Werte weiter."],
  ] as const)("„Merken“ mit Fehler %s: klare Meldung, nichts gespeichert", async (error, text) => {
    const { sock } = await mount((m) => m.voiceTune(1));
    await click(btn("Merken"));
    sock.tuningFail = error;
    await click(within(box().getByRole("alertdialog")).getByRole("button", { name: "Dauerhaft merken" }));
    expect(box().getByRole("status")).toHaveTextContent(text);
    expect(sock.tuningSaves).toBe(0);
    expect(btn("Merken")).toBeEnabled();              // die Werte gelten weiter und lassen sich noch einmal merken
  });

  it("active:false: Werte aus der Datei, Kasten deaktiviert mit „Sprachdienst läuft nicht“", async () => {
    await mount((m) => { m.tuningActive = false; m.tuningFile = { ...m.tuningFile, speech_level: 260 }; });
    expect(box().getByText(/Angezeigt sind die Werte aus wakewords\.toml\./)).toBeInTheDocument();
    expect(box().getByText("Sprechen ab 260")).toBeInTheDocument();
    expect(box().getByText("Schwelle 260")).toBeInTheDocument();
    expect(box().getByText("RMS kein Signal")).toBeInTheDocument();
    expect(slider("Empfindlichkeit Sprechen")).toBeDisabled();
  });

  it("active:false und wakewords.toml fehlerhaft (values null): „unbekannt“, keine Marken, ruhiger Hinweis", async () => {
    await mount((m) => { m.tuningActive = false; m.tuningFileBroken = true; });
    expect(box().getByText(BROKEN_FILE)).toBeInTheDocument();
    expect(box().getByText(NOT_RUNNING)).toBeInTheDocument();
    expect(box().getByText("Sprechen ab unbekannt")).toBeInTheDocument();
    expect(box().getByText("Unterbrechen ab unbekannt")).toBeInTheDocument();
    expect(box().getAllByText("Schwelle unbekannt")).toHaveLength(2);
    expect(slider("Empfindlichkeit Sprechen")).toHaveAttribute("aria-valuetext", "Schwelle unbekannt, nach rechts empfindlicher");
    expect(slider("Pause bis Satzende")).toHaveAttribute("aria-valuetext", "unbekannt");
    expect(document.querySelectorAll(".mic-mark")).toHaveLength(0);
    expect(slider("Empfindlichkeit Sprechen")).toBeDisabled();
    expect(btn("Merken")).toBeDisabled();
    expect(btn("Standard")).toBeDisabled();
  });

  it("active:false: Kasten deaktiviert mit „Sprachdienst läuft nicht“, seltener abfragen", async () => {
    const { sent } = await mount((m) => { m.tuningActive = false; });
    expect(box().getAllByText(new RegExp(NOT_RUNNING)).length).toBeGreaterThan(0);
    expect(slider("Empfindlichkeit Sprechen")).toBeDisabled();
    expect(slider("Empfindlichkeit Unterbrechen")).toBeDisabled();
    expect(slider("Pause bis Satzende")).toBeDisabled();
    expect(btn("Standard")).toBeDisabled();
    expect(btn("Merken")).toBeDisabled();
    expect(box().getByRole("meter")).toHaveAttribute("aria-valuetext", "kein Signal");
    const n = sent("voice.tuning.get").length;
    await tick(TUNING_IDLE_MS - 10);
    expect(sent("voice.tuning.get")).toHaveLength(n);
    await tick(20);
    expect(sent("voice.tuning.get")).toHaveLength(n + 1);
  });

  it("Notaus: gesperrt mit Wort, keine Regler bedienbar", async () => {
    await mount(undefined, { kill: true });
    expect(box().getByText(/Gesperrt: Notaus aktiv/)).toBeInTheDocument();
    expect(slider("Empfindlichkeit Sprechen")).toBeDisabled();
  });

  it("Abfrage etwa alle 250 ms; stoppt bei verdecktem Fenster und läuft danach weiter", async () => {
    const { sent } = await mount();
    const n0 = sent("voice.tuning.get").length;
    await tick(1000);
    const n1 = sent("voice.tuning.get").length;
    expect(n1 - n0).toBeGreaterThanOrEqual(3);
    expect(n1 - n0).toBeLessThanOrEqual(5);
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    const n2 = sent("voice.tuning.get").length;
    await tick(3000);
    expect(sent("voice.tuning.get")).toHaveLength(n2);
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await tick(600);
    expect(sent("voice.tuning.get").length).toBeGreaterThan(n2);
  });

  it("nicht sichtbar (kleines Fenster): keine Abfrage", async () => {
    const { sent } = await mount(undefined, { visible: false });
    await tick(2000);
    expect(sent("voice.tuning.get")).toHaveLength(0);
  });

  it("älterer Dienst ohne voice.tuning: ruhiger Hinweis, keine weiteren Abfragen", async () => {
    const { sent } = await mount((m) => {
      (m as unknown as { tuningReply: () => unknown }).tuningReply = () => ({ ok: false, error: "unknown_type" });
    });
    expect(box().getByText("nicht verfügbar")).toBeInTheDocument();
    expect(box().getByText(/kennt die Mikrofon-Einstellung noch nicht/)).toBeInTheDocument();
    const n = sent("voice.tuning.get").length;
    await tick(3000);
    expect(sent("voice.tuning.get")).toHaveLength(n);
  });

  it("Pegel und Marken stehen nur als Zahlen im Stil (Breite und Lage in Prozent), nie in class oder id", async () => {
    await mount();
    for (const el of Array.from(document.querySelectorAll<HTMLElement>(".mic-fill, .mic-peak, .mic-mark"))) {
      expect(el.getAttribute("style")).toMatch(/^(width|left): \d+(\.\d+)?%;?$/);
    }
  });
});

describe("Ort in der App", () => {
  it("Kasten Mikrofon steht in der Ansicht Sicherheit; der Sicherheitsstatus selbst bleibt ohne Knöpfe", async () => {
    const loader = async () => ({ client: new ApiClient({ port: 5000, token: TOKEN }, (u) => new MockSocket(u, TOKEN)) });
    render(<App load={loader} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    expect(screen.queryByRole("region", { name: "Mikrofon" })).toBeNull();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Sicherheit" })); });
    await waitFor(() => screen.getByText("Sprechen ab 200"));
    expect(screen.getByRole("region", { name: "Mikrofon" })).toBeInTheDocument();
    expect(document.querySelector(".security button")).toBeNull();
    expect(screen.getByRole("button", { name: "NOTAUS" })).toBeInTheDocument();
  });
});
