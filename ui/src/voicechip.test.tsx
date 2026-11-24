import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { parseEntry, Transcript, unspokenText, type Entry } from "./components/Transcript";
import { parseTts, VOICE_CHIP, VoiceChip, type TtsState } from "./components/VoiceChip";
import { ApiClient } from "./lib/api";
import { STATE_VIEW } from "./lib/avatarState";
import { MockSocket, transcriptEntry, unspokenDemo, type MockEntry } from "./lib/mock";

// Stimm-Chip (Zustand der Sprachausgabe aus voice.state, Feld `tts`) und Vermerk „nicht gesprochen“ im Verlauf. Nur Anzeige.

const { invoke } = vi.hoisted(() => ({ invoke: vi.fn(async (_cmd: string, _args?: unknown) => undefined) }));
vi.mock("@tauri-apps/api/core", () => ({ invoke }));

const TOKEN = "t".repeat(43);
const TS = 1_790_000_000;
const STATES: TtsState[] = ["loading", "ready", "cpu", "failed", "off"];
const LONG: Record<TtsState, string> = {
  loading: "Stimme lädt", ready: "Stimme bereit", cpu: "Stimme langsam (CPU)", failed: "Stimme aus, nur Text", off: "Stimme aus, nur Text" };
const SHORT: Record<TtsState, string> = { loading: "lädt", ready: "bereit", cpu: "CPU", failed: "nur Text", off: "nur Text" };
const POLLS = new Set(["safety.status", "voice.state", "approvals.get", "transcript.get", "safety.overview", "stage.get", "usage.get",
  "dashboard.get", "system.stats", "claude.folder_list", "memory.search", "setup.status", "setup.checks"]);

afterEach(() => {
  cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); invoke.mockReset();
  history.replaceState(null, "", "/");
});

function loaderWith(sock: { current?: MockSocket }, setup: (m: MockSocket) => void = () => {}) {
  return async () => ({
    client: new ApiClient({ port: 5000, token: TOKEN }, (u) => {
      sock.current = new MockSocket(u, TOKEN);
      setup(sock.current);
      return sock.current;
    }),
  });
}
async function start(sock: { current?: MockSocket }, setup?: (m: MockSocket) => void) {
  render(<App load={loaderWith(sock, setup)} />);
  await waitFor(() => expect(screen.getAllByText(STATE_VIEW.idle.label).length).toBeGreaterThan(0));
}
const talking = (tts: MockSocket["tts"]) => (m: MockSocket) => { m.voice = { active: true, state: "idle", level: 0 }; m.tts = tts; };
const head = () => document.querySelector("header.head") as HTMLElement;
const chips = () => document.querySelectorAll(".voice-chip");
const actions = (m: MockSocket) => m.sent.filter((x) => !POLLS.has((x as { type: string }).type));
const entry = (p: Partial<MockEntry> & { id: number }): Entry => parseEntry(transcriptEntry({ ts: TS, ...p }))!;

describe("parseTts", () => {
  it("nimmt nur die fünf Zustände an; fehlt das Feld oder ist es fremd, gibt es keinen Chip", () => {
    for (const s of STATES) expect(parseTts(s)).toBe(s);
    for (const bad of [undefined, null, "", "READY", "gpu", 1, true, {}, ["ready"], "ready "]) expect(parseTts(bad)).toBeNull();
  });
});

describe("Stimm-Chip in der Kopfzeile", () => {
  it.each(STATES)("%s: Wort plus SVG-Symbol, nicht nur Farbe", async (tts) => {
    const sock: { current?: MockSocket } = {};
    await start(sock, talking(tts));
    await waitFor(() => expect(within(head()).getByText(LONG[tts])).toBeInTheDocument());
    const chip = within(head()).getByText(LONG[tts]).closest(".voice-chip") as HTMLElement;
    expect(chip.querySelector("svg")).not.toBeNull();
    expect(chip.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(chip).toHaveAttribute("title", LONG[tts]);
    expect(chip).toHaveAttribute("aria-live", "polite");
    expect(chip.textContent).toContain(LONG[tts]);
    expect(chips()).toHaveLength(1);
    expect(chip.className).toBe(VOICE_CHIP[tts].tone);                       // feste Klasse aus der Tabelle, nie der Rohwert
  });

  it("„bereit“ ist dezent (eigene Klasse ohne Warnfarbe), „CPU“ und „nur Text“ warnen, „lädt“ informiert", () => {
    expect(VOICE_CHIP.ready.tone).toBe("voice-chip is-ready");
    expect(VOICE_CHIP.loading.tone).toBe("voice-chip is-loading");
    expect(VOICE_CHIP.cpu.tone).toBe("voice-chip is-cpu");
    expect(VOICE_CHIP.failed.tone).toBe("voice-chip is-text");
    expect(VOICE_CHIP.off.tone).toBe("voice-chip is-text");
  });

  it("fehlt das Feld (älterer Dienst), gibt es keinen Chip", async () => {
    const sock: { current?: MockSocket } = {};
    await start(sock, talking(null));
    await waitFor(() => expect(sock.current!.sent.filter((x) => (x as { type: string }).type === "voice.state").length).toBeGreaterThan(2));
    expect(chips()).toHaveLength(0);
    expect(screen.queryByText(/^Stimme /)).toBeNull();
  });

  it("ohne Sprachdienst gibt es keinen Chip, auch nicht „nur Text“", async () => {
    const sock: { current?: MockSocket } = {};
    await start(sock, (m) => { m.tts = "failed"; });                         // voice.active false: der Dienst meldet tts „off“
    await waitFor(() => screen.getByText(/Der Sprachdienst läuft nicht/));
    await waitFor(() => expect(sock.current!.sent.filter((x) => (x as { type: string }).type === "voice.state").length).toBeGreaterThan(2));
    expect(chips()).toHaveLength(0);
  });

  it("wechselt mit dem Dienst: lädt, dann bereit; endet der Sprachdienst, verschwindet der Chip", async () => {
    const sock: { current?: MockSocket } = {};
    await start(sock, talking("loading"));
    await waitFor(() => within(head()).getByText("Stimme lädt"));
    const before = head().querySelector(".voice-chip");
    sock.current!.tts = "ready";
    await waitFor(() => within(head()).getByText("Stimme bereit"));
    expect(head().querySelector(".voice-chip")).toBe(before);              // dasselbe Element: aria-live meldet den Wechsel
    sock.current!.voice = { active: false, state: "idle", level: 0 };
    await waitFor(() => expect(chips()).toHaveLength(0));
  });

  it("ohne Verbindung kein Chip", async () => {
    const sock: { current?: MockSocket } = {};
    await start(sock, talking("cpu"));
    await waitFor(() => within(head()).getByText("Stimme langsam (CPU)"));
    await act(async () => { sock.current!.close(); });
    await waitFor(() => expect(chips()).toHaveLength(0));
  });
});

describe("Stimm-Chip im kleinen Fenster", () => {
  it.each(STATES)("%s: kurzes Wort mit Symbol, das lange im title und für Screenreader", async (tts) => {
    const sock: { current?: MockSocket } = {};
    await start(sock, talking(tts));
    await waitFor(() => within(head()).getByText(LONG[tts]));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Klein" })); });
    const box = screen.getByRole("region", { name: "Kleines Fenster" });
    const chip = box.querySelector(".voice-chip") as HTMLElement;
    expect(chip).not.toBeNull();
    expect(chip).toHaveClass("is-compact");
    expect(chip).toHaveAttribute("title", LONG[tts]);
    expect(chip.querySelector("svg")).not.toBeNull();
    expect(within(chip).getByText(SHORT[tts])).toHaveAttribute("aria-hidden", "true");
    expect(within(chip).getByText(LONG[tts])).toHaveClass("v-sr");
    expect(head()).not.toBeVisible();                                       // der große Kopf ist versteckt: kein zweiter sichtbarer Chip
  });

  it("ohne Feld auch im kleinen Fenster kein Chip", async () => {
    const sock: { current?: MockSocket } = {};
    await start(sock, talking(null));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Klein" })); });
    await waitFor(() => expect(sock.current!.sent.filter((x) => (x as { type: string }).type === "voice.state").length).toBeGreaterThan(2));
    expect(chips()).toHaveLength(0);
  });

  it("Baustein: groß langes und kurzes Wort (kurz nur für schmale Fenster, für Screenreader verborgen)", () => {
    render(<VoiceChip tts="cpu" />);
    expect(screen.getByText("Stimme langsam (CPU)")).toHaveClass("voice-long");
    expect(screen.getByText("CPU")).toHaveClass("voice-short");
    expect(screen.getByText("CPU")).toHaveAttribute("aria-hidden", "true");
  });
});

describe("Vermerk „nicht gesprochen“ im Verlauf", () => {
  it("Text mit Zahl der Sätze; nichts bei 0 oder ohne Antwort", () => {
    expect(unspokenText({ reply: "a", unspoken: 1 })).toBe("nicht gesprochen (Stimme aus), 1 Satz");
    expect(unspokenText({ reply: "a. b.", unspoken: 2 })).toBe("nicht gesprochen (Stimme aus), 2 Sätze");
    expect(unspokenText({ reply: "a", unspoken: 0 })).toBe("");
    expect(unspokenText({ reply: "", unspoken: 3 })).toBe("");
  });

  it("parseEntry: Feld fehlt (älterer Dienst) oder ist ungültig: 0", () => {
    const base = transcriptEntry({ id: 1, ts: TS, reply: "x" }) as Partial<MockEntry>;
    delete base.unspoken;
    expect(parseEntry(base)!.unspoken).toBe(0);
    for (const bad of [-1, 1.5, "2", true, null, Number.NaN, Number.POSITIVE_INFINITY, 2 ** 60]) {
      expect(parseEntry({ ...base, unspoken: bad })!.unspoken).toBe(0);
    }
    expect(parseEntry({ ...base, unspoken: 3 })!.unspoken).toBe(3);
  });

  it("Baustein: steht als Text mit Symbol unter der Antwort, nur dort", () => {
    render(<Transcript entries={[
      entry({ id: 1, heard: "Wie spät?", reply: "Zehn Uhr." }),
      entry({ id: 2, heard: "Wetter?", reply: "Morgen 11 Grad. Ab Nachmittag Regen.", unspoken: 2 }),
      entry({ id: 3, heard: "", raw: "", reply: "", outcome: "rejected_speaker", status: "dropped", unspoken: 2 }),
    ]} onRate={() => {}} />);
    const notes = screen.getAllByText(/^nicht gesprochen/);
    expect(notes).toHaveLength(1);
    expect(notes[0]).toHaveTextContent("nicht gesprochen (Stimme aus), 2 Sätze");
    expect(notes[0]).toHaveClass("bot-note");
    expect(notes[0].querySelector("svg")).not.toBeNull();
    expect(notes[0].closest(".bubble.bot")).toHaveTextContent("Morgen 11 Grad. Ab Nachmittag Regen.");
  });

  it("in der App: Übersicht zeigt den Vermerk am Eintrag, der nur als Text kam", async () => {
    const sock: { current?: MockSocket } = {};
    await start(sock, (m) => { m.entries = unspokenDemo(TS); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Übersicht" })); });
    const log = await screen.findByRole("list", { name: "Verlauf" }, { timeout: 3000 });
    await waitFor(() => within(log).getByText("nicht gesprochen (Stimme aus), 2 Sätze"), { timeout: 3000 });
    expect(within(log).getAllByText(/^nicht gesprochen/)).toHaveLength(1);
    expect(within(log).getByText("Es ist zehn nach drei.")).toBeInTheDocument();
  });
});

describe("Keine Wirkung", () => {
  it("Chip und Vermerk senden nichts, speichern nichts, kein Netz, kein Ton, kein Fensterbefehl", async () => {
    const fetchSpy = vi.fn();
    const wsSpy = vi.fn();
    const audioSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    vi.stubGlobal("WebSocket", wsSpy);
    vi.stubGlobal("Audio", audioSpy);
    vi.stubGlobal("AudioContext", audioSpy);
    const store = [vi.spyOn(Storage.prototype, "setItem"), vi.spyOn(Storage.prototype, "getItem"), vi.spyOn(Storage.prototype, "removeItem")];
    const sock: { current?: MockSocket } = {};
    await start(sock, (m) => { talking("failed")(m); m.entries = unspokenDemo(TS); });
    await waitFor(() => within(head()).getByText("Stimme aus, nur Text"));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Übersicht" })); });
    const note = await screen.findByText("nicht gesprochen (Stimme aus), 2 Sätze", undefined, { timeout: 3000 });
    const before = JSON.stringify(actions(sock.current!));
    const chip = head().querySelector(".voice-chip") as HTMLElement;
    expect(chip.tagName).toBe("SPAN");                                       // kein Bedienelement
    expect(chip).not.toHaveAttribute("tabindex");
    expect(within(chip).queryByRole("button")).toBeNull();
    await act(async () => {
      for (const el of [chip, note]) {
        fireEvent.click(el);
        fireEvent.keyDown(el, { key: "Enter" });
        fireEvent.keyDown(el, { key: " " });
      }
    });
    await act(async () => { await new Promise((r) => setTimeout(r, 300)); });
    expect(JSON.stringify(actions(sock.current!))).toBe(before);
    expect(actions(sock.current!)).toEqual([]);
    for (const s of store) expect(s).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(wsSpy).not.toHaveBeenCalled();
    expect(audioSpy).not.toHaveBeenCalled();
    expect(invoke).not.toHaveBeenCalled();
  });
});

describe("Mock: ?mock&tts=…", () => {
  const reply = async (m: MockSocket, type: string) => {
    const got = new Promise<Record<string, unknown>>((res) => { m.onmessage = (e) => res(JSON.parse(String(e.data))); });
    m.send(JSON.stringify({ type, token: TOKEN }));
    return got;
  };

  it.each(["loading", "cpu", "failed", "ready", "off"] as const)("tts=%s: Sprachdienst läuft, voice.state meldet den Zustand", async (tts) => {
    history.replaceState(null, "", `/?mock&tts=${tts}`);
    const m = new MockSocket("ws://127.0.0.1:1", TOKEN);
    const r = await reply(m, "voice.state");
    expect(r).toEqual({ ok: true, active: true, state: "idle", level: 0, wake_count: 0, wake_last: "", tts });
  });

  it("tts=failed bringt ein Beispiel mit „nicht gesprochen“ (vollständige Einträge wie transcript.get)", async () => {
    history.replaceState(null, "", "/?mock&tts=failed");
    const m = new MockSocket("ws://127.0.0.1:1", TOKEN);
    const r = await reply(m, "transcript.get");
    const entries = r.entries as Record<string, unknown>[];
    expect(entries.map((e) => e.unspoken)).toEqual([0, 2]);
    const keys = ["id", "rev", "heard", "raw", "ts", "status", "reason", "sent_ts", "reply", "outcome", "unspoken"].sort();
    for (const e of entries) expect(Object.keys(e).sort()).toEqual(keys);
  });

  it("tts=alt: Feld fehlt (älterer Dienst); ohne Sprachdienst meldet der Mock wie das Backend „off“", async () => {
    history.replaceState(null, "", "/?mock&tts=alt");
    expect(await reply(new MockSocket("ws://127.0.0.1:1", TOKEN), "voice.state")).not.toHaveProperty("tts");
    history.replaceState(null, "", "/?mock");
    expect(await reply(new MockSocket("ws://127.0.0.1:1", TOKEN), "voice.state")).toMatchObject({ active: false, tts: "off" });
  });

  it("ohne Parameter bleibt alles wie bisher (kein Beispiel-Eintrag)", async () => {
    history.replaceState(null, "", "/?mock&tts=unsinn");
    const m = new MockSocket("ws://127.0.0.1:1", TOKEN);
    expect(m.entries).toEqual([]);
    expect(m.voice.active).toBe(false);
  });
});
