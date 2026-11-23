import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { parseUsage, standText, USAGE_HINT, USAGE_POLL_MS, usageParts, useUsage, type Usage } from "./components/CompactBar";
import { ApiClient } from "./lib/api";
import { STATE_VIEW } from "./lib/avatarState";
import { DEMO_VIEWS, MockSocket, transcriptEntry, usageDemo } from "./lib/mock";
import { clockText } from "./components/Transcript";

const TS = 1_790_000_000;                                  // feste Erkennungszeit für die Zeile „Du“

// E2 (docs/ui-e2e3-plan.md, Abschnitte 3, 4 und 7): kleines Fenster, Freigabe darin, Verbrauch, Tastenkürzel.

const { invoke } = vi.hoisted(() => ({ invoke: vi.fn(async (_cmd: string, _args?: unknown) => undefined) }));
vi.mock("@tauri-apps/api/core", () => ({ invoke }));

const TOKEN = "t".repeat(43);
const WINDOW_CMDS = ["set_compact", "set_always_on_top", "grow_for_approval", "attention"];
const POLLS = new Set(["safety.status", "voice.state", "approvals.get", "transcript.get", "safety.overview", "stage.get", "usage.get",
  "dashboard.get", "system.stats", "claude.folder_list", "memory.search", "setup.status", "setup.checks"]);

const tauri = (on: boolean) => {
  const w = window as unknown as Record<string, unknown>;
  if (on) w.__TAURI_INTERNALS__ = {}; else delete w.__TAURI_INTERNALS__;
};

beforeEach(() => { invoke.mockReset(); invoke.mockImplementation(async () => undefined); });
afterEach(() => {
  cleanup(); tauri(false); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers();
  delete (document as unknown as Record<string, unknown>).hidden;
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
const toSmall = async () => { await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Klein" })); }); };
const compactBox = () => screen.getByRole("region", { name: "Kleines Fenster" });
const sentTypes = (m: MockSocket) => m.sent.map((x) => (x as { type: string }).type);
const actions = (m: MockSocket) => sentTypes(m).filter((t) => !POLLS.has(t));

const REQ = { request_id: "r1", tool_name: "Bash", description: "Tests ausführen", digest: "a".repeat(64),
  summary: "Claude möchte die Tests ausführen.", truncated: false,
  input_preview: `cd ui && npx vitest run\n${"x".repeat(3000)}\nENDE-DES-TEXTES` };

describe("Umschalten klein und groß", () => {
  it("in Tauri ruft „Klein“ set_compact über den invoke-Wrapper, „Groß“ schaltet zurück und gibt den Fokus an „Klein“", async () => {
    tauri(true);
    const sock: { current?: MockSocket } = {};
    await start(sock);
    await toSmall();
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("set_compact", { on: true }));
    expect(document.querySelector(".app")).toHaveClass("is-compact");
    expect(compactBox()).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Bereiche" })).toBeNull();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Groß" })); });
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("set_compact", { on: false }));
    expect(document.querySelector(".app")).not.toHaveClass("is-compact");
    expect(screen.getByRole("button", { name: "Klein" })).toHaveFocus();
    expect(invoke.mock.calls.every(([cmd]) => WINDOW_CMDS.includes(cmd))).toBe(true);
  });

  it("nach dem kleinen Fenster folgt der Kern wieder der gemessenen Größe (neuer Hauptbereich wird beobachtet)", async () => {
    const observers: { cb: ResizeObserverCallback; el?: Element; off: boolean }[] = [];
    vi.stubGlobal("ResizeObserver", class {
      o: { cb: ResizeObserverCallback; el?: Element; off: boolean };
      constructor(cb: ResizeObserverCallback) { this.o = { cb, off: false }; observers.push(this.o); }
      observe(el: Element) { this.o.el = el; }
      disconnect() { this.o.off = true; }
      unobserve() {}
    });
    const sock: { current?: MockSocket } = {};
    await start(sock);
    await toSmall();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Groß" })); });
    const live = observers.filter((o) => !o.off && o.el?.isConnected);
    expect(live).toHaveLength(1);
    await act(async () => { live[0].cb([{ contentRect: { width: 400, height: 500 } } as ResizeObserverEntry], {} as ResizeObserver); });
    await waitFor(() => expect(screen.getByRole("img")).toHaveStyle({ width: "280px" }));
  });

  it("im Browser (ohne Tauri) schaltet nur die CSS-Klasse, kein Fensterbefehl", async () => {
    const sock: { current?: MockSocket } = {};
    await start(sock);
    await toSmall();
    expect(document.querySelector(".app")).toHaveClass("is-compact");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Immer im Vordergrund/ })); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Groß" })); });
    await act(async () => { await Promise.resolve(); });
    expect(invoke).not.toHaveBeenCalled();
  });

  it("„Immer im Vordergrund“ ist im kleinen Fenster an, als Wort und aria-pressed, und schaltet über set_always_on_top", async () => {
    tauri(true);
    const sock: { current?: MockSocket } = {};
    await start(sock);
    await toSmall();
    const top = screen.getByRole("button", { name: /Immer im Vordergrund/ });
    expect(top).toHaveAttribute("aria-pressed", "true");
    expect(top).toHaveTextContent("Immer im Vordergrund: an");
    await act(async () => { fireEvent.click(top); });
    expect(top).toHaveAttribute("aria-pressed", "false");
    expect(top).toHaveTextContent("Immer im Vordergrund: aus");
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("set_always_on_top", { on: false }));
  });

  it("kein Klick auf die Fensterknöpfe sendet etwas ans Backend, speichert etwas, geht ins Netz oder macht Ton", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const store = vi.spyOn(Storage.prototype, "setItem");
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    const sock: { current?: MockSocket } = {};
    await start(sock);
    const before = actions(sock.current!);
    await toSmall();
    for (let i = 0; i < 2; i++) await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Immer im Vordergrund/ })); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Groß" })); });
    await act(async () => { await new Promise((r) => setTimeout(r, 50)); });
    expect(actions(sock.current!)).toEqual(before);
    expect(before).toEqual([]);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(store).not.toHaveBeenCalled();
    expect(play).not.toHaveBeenCalled();
  });
});

describe("Tastenkürzel Strg+Umschalt+M", () => {
  it("schaltet nur mit Fokus im Fenster und nur mit genau Strg+Umschalt+M", async () => {
    const focus = vi.spyOn(document, "hasFocus").mockReturnValue(false);
    const sock: { current?: MockSocket } = {};
    await start(sock);
    const isSmall = () => document.querySelector(".app")!.classList.contains("is-compact");
    await act(async () => { fireEvent.keyDown(window, { key: "M", ctrlKey: true, shiftKey: true }); });
    expect(isSmall()).toBe(false);                                     // ohne Fokus: nichts
    focus.mockReturnValue(true);
    for (const other of [{ key: "m", ctrlKey: true }, { key: "M", shiftKey: true }, { key: "M", ctrlKey: true, shiftKey: true, altKey: true },
      { key: "M", ctrlKey: true, shiftKey: true, metaKey: true }, { key: "N", ctrlKey: true, shiftKey: true }]) {
      await act(async () => { fireEvent.keyDown(window, other); });
      expect(isSmall()).toBe(false);
    }
    await act(async () => { fireEvent.keyDown(window, { key: "M", ctrlKey: true, shiftKey: true, repeat: true }); });
    expect(isSmall()).toBe(false);                                     // gehaltene Taste schaltet nicht hin und her
    await act(async () => { fireEvent.keyDown(window, { key: "M", ctrlKey: true, shiftKey: true }); });
    expect(isSmall()).toBe(true);
    await act(async () => { fireEvent.keyDown(window, { key: "M", ctrlKey: true, shiftKey: true }); });
    expect(isSmall()).toBe(false);
    expect(actions(sock.current!)).toEqual([]);
  });
});

describe("NOTAUS im kleinen Fenster", () => {
  it("ist sichtbar, löst mit einem Klick aus, zeigt das Banner mit bestätigtem Aufheben; Strg+Umschalt+K geht auch", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const sock: { current?: MockSocket } = {};
    await start(sock);
    await toSmall();
    const kill = within(compactBox()).getByRole("button", { name: "NOTAUS" });
    expect(kill).toHaveClass("kill");
    await act(async () => { fireEvent.click(kill); });
    await waitFor(() => expect(sock.current!.kill).toBe(true));
    expect(confirm).not.toHaveBeenCalled();
    await waitFor(() => expect(within(compactBox()).getByRole("alert")).toHaveTextContent("NOTAUS aktiv."));
    expect(document.querySelector(".app")).toHaveClass("is-halted");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Notaus aufheben" })); });
    expect(confirm).toHaveBeenCalled();
    expect(sock.current!.kill).toBe(true);
    confirm.mockReturnValue(true);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Notaus aufheben" })); });
    await waitFor(() => expect(sock.current!.kill).toBe(false));
    await act(async () => { fireEvent.keyDown(window, { key: "K", ctrlKey: true, shiftKey: true }); });
    await waitFor(() => expect(sock.current!.kill).toBe(true));
    expect(actions(sock.current!)).toEqual(["safety.kill", "safety.resume", "safety.kill"]);
  });
});

describe("Freigabe im kleinen Fenster", () => {
  it("wächst, blinkt, zeigt den ganzen Text mit Sperre und Fokus auf Ablehnen, holt nie den Fenster-Fokus und wird danach wieder klein", async () => {
    tauri(true);
    const winFocus = vi.spyOn(window, "focus");
    const sock: { current?: MockSocket } = {};
    await start(sock);
    await toSmall();
    sock.current!.pending = [{ ...REQ }];
    const bar = await screen.findByRole("alertdialog", {}, { timeout: 3000 });
    expect(compactBox()).toContainElement(bar);
    expect(document.querySelectorAll('[role="alertdialog"]')).toHaveLength(1);   // genau eine Leiste, auch nicht versteckt im großen Teil
    expect(compactBox()).toHaveAttribute("data-mode", "freigabe");
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("grow_for_approval", { on: true }));
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("attention", {}));
    const pre = bar.querySelector("pre#ap-prev")!;
    expect(pre.textContent).toContain(REQ.input_preview);               // ganzer exakter Text, nichts gekürzt
    expect(pre.textContent).toContain("ENDE-DES-TEXTES");
    const deny = within(bar).getByRole("button", { name: "Ablehnen" });
    const allow = within(bar).getByRole("button", { name: "Erlauben" });
    expect(deny).toBeDisabled();                                        // 700 ms Sperre
    expect(allow).toBeDisabled();
    await waitFor(() => expect(deny).toBeEnabled(), { timeout: 2000 });
    expect(deny).toHaveFocus();                                          // Standardfokus auf Ablehnen
    expect(winFocus).not.toHaveBeenCalled();
    expect(invoke.mock.calls.every(([cmd]) => WINDOW_CMDS.includes(cmd))).toBe(true);
    await act(async () => { fireEvent.click(deny); });
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("grow_for_approval", { on: false }));
    expect(compactBox()).toHaveAttribute("data-mode", "klein");
    const decided = sock.current!.sent.filter((m) => (m as { type: string }).type === "approvals.decide");
    expect(decided).toEqual([{ type: "approvals.decide", request_id: "r1", approve: false, digest: REQ.digest, token: TOKEN }]);
    expect(actions(sock.current!)).toEqual(["approvals.decide"]);
    expect(winFocus).not.toHaveBeenCalled();
  });

  it("Esc lehnt ab; gekürzter Text: nur Ablehnen", async () => {
    const sock: { current?: MockSocket } = {};
    await start(sock, (m) => { m.pending = [{ ...REQ, truncated: true }]; });
    await toSmall();
    const bar = await screen.findByRole("alertdialog", {}, { timeout: 3000 });
    expect(within(bar).queryByRole("button", { name: "Erlauben" })).toBeNull();
    const deny = within(bar).getByRole("button", { name: "Ablehnen" });
    await waitFor(() => expect(deny).toBeEnabled(), { timeout: 2000 });
    await act(async () => { fireEvent.keyDown(bar, { key: "Escape" }); });
    await waitFor(() => expect(sock.current!.pending).toEqual([]));
    expect(sock.current!.sent.some((m) => (m as { type: string; approve?: boolean }).type === "approvals.decide"
      && (m as { approve?: boolean }).approve === false)).toBe(true);
  });
});

describe("Letzter Befehl im kleinen Fenster", () => {
  it("zeigt „Du: …“ und die erste Zeile der Antwort als Text, ganzer Text im title; <script> bleibt Text", async () => {
    const sock: { current?: MockSocket } = {};
    await start(sock, (m) => {
      m.voice = { active: true, state: "idle", level: 0 };
      m.entries = [transcriptEntry({ id: 1, heard: "<script>alert(1)</script>", reply: "Erste Zeile\nZweite Zeile", ts: TS })];
    });
    await toSmall();
    const you = await within(compactBox()).findByText("Du: <script>alert(1)</script> · gesendet");
    expect(you).toHaveAttribute("title", `Erkannt ${clockText(TS)}, gesendet`);
    expect(document.querySelector("script")).toBeNull();
    const reply = within(compactBox()).getByText("kushim: Erste Zeile");
    expect(reply).toHaveAttribute("title", "Erste Zeile\nZweite Zeile");
    await waitFor(() => expect(within(compactBox()).queryByText("Kein Sprachdienst")).toBeNull());   // Sprachdienst meldet sich
  });

  it("ohne Sprachdienst steht „Kein Sprachdienst“", async () => {
    const sock: { current?: MockSocket } = {};
    await start(sock);
    await toSmall();
    expect(await within(compactBox()).findByText("Kein Sprachdienst")).toBeInTheDocument();
  });

  it("eine neue Ansicht von Claude erscheint nur als Hinweis mit „Groß“, die Bühne bleibt im großen Fenster", async () => {
    const sock: { current?: MockSocket } = {};
    await start(sock);
    await toSmall();
    act(() => { sock.current!.show(DEMO_VIEWS[0]); });
    expect(await within(compactBox()).findByText(/Neue Ansicht von Claude: Quadratische Gleichung/, {}, { timeout: 3000 })).toBeInTheDocument();
    expect(document.querySelector("main.view")).toHaveAttribute("hidden");               // die Bühne ist im kleinen Fenster nicht zu sehen
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Groß" })); });
    await waitFor(() => expect(document.querySelector(".view-card")).not.toBeNull());
  });
});

describe("Verbrauch (usage.get)", () => {
  const ok = (extra: Record<string, unknown> = {}) => ({ ok: true as const, ...usageDemo("frisch"), ...extra });

  it("liest nur gültige Felder; leere Felder fallen weg, nichts wird erfunden", () => {
    const u = parseUsage(ok({ five_h_pct: null, seven_d_pct: 140, cost_usd: 1.5 })) as Extract<Usage, { kind: "ok" }>;
    expect(usageParts(u)).toEqual(["Opus", "Kontext 42 %", "Kosten 1,50 $"]);
    expect(usageParts(parseUsage(ok({ model: "", context_pct: null, five_h_pct: null, seven_d_pct: null })) as Extract<Usage, { kind: "ok" }>)).toEqual([]);
    expect(parseUsage(ok({ available: false }))).toEqual({ kind: "none" });
    expect(parseUsage({ ok: false, error: "unknown_type" })).toEqual({ kind: "none" });
    expect(parseUsage(ok({ stand: "gestern" }))).toEqual({ kind: "bad" });
    expect((parseUsage(ok({ model: "Opus\u0007\nX".padEnd(80, "y") })) as Extract<Usage, { kind: "ok" }>).model.length).toBeLessThanOrEqual(40);
    expect((parseUsage(ok({ stale: true })) as Extract<Usage, { kind: "ok" }>).stale).toBe(true);
    expect((parseUsage(ok({ stand: Date.now() / 1000 - 3600, stale: false })) as Extract<Usage, { kind: "ok" }>).stale).toBe(true);   // älter als 30 min
  });

  it("„Stand“ in Ortszeit, an einem anderen Tag mit Datum", () => {
    const d = new Date(2026, 10, 23, 14, 5);
    expect(standText(d.getTime() / 1000, new Date(2026, 10, 23, 18, 0))).toBe("Stand 14:05");
    expect(standText(d.getTime() / 1000, new Date(2026, 10, 24, 9, 0))).toBe("Stand 23.11. 14:05");
  });

  it("im kleinen Fenster: Werte mit „Stand“; veraltet gedämpft mit Wort", async () => {
    const sock: { current?: MockSocket } = {};
    await start(sock);
    await toSmall();
    const line = await within(compactBox()).findByText("Opus · Kontext 42 % · 5h 30 % · 7d 12 %");
    const stand = standText(sock.current!.usage!.stand as number);
    expect(line.parentElement).toHaveTextContent(stand);
    expect(line.parentElement).not.toHaveClass("is-stale");
    expect(line.parentElement).not.toHaveTextContent("veraltet");
    cleanup();
    const sock2: { current?: MockSocket } = {};
    await start(sock2, (m) => { m.usage = usageDemo("alt"); });
    await toSmall();
    const old = await within(compactBox()).findByText("Opus · Kontext 87 % · 5h 64 %");          // 7d fehlt (null): weggelassen
    expect(old.parentElement).toHaveClass("is-stale");
    expect(old.parentElement).toHaveTextContent("veraltet");
  });

  it("nicht verfügbar oder unbekannter Typ: Hinweis auf Statuszeile oder /usage; auch in der Übersicht", async () => {
    const sock: { current?: MockSocket } = {};
    await start(sock, (m) => { m.usage = null; });                     // Dienst kennt usage.get nicht
    await toSmall();
    expect(await within(compactBox()).findByText(USAGE_HINT)).toBeInTheDocument();
    cleanup();
    const sock2: { current?: MockSocket } = {};
    await start(sock2, (m) => { m.usage = usageDemo("keine"); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Übersicht" })); });
    expect(await screen.findByText(USAGE_HINT)).toBeInTheDocument();
    expect(screen.queryByText(/Kontext/)).toBeNull();
  });

  it("fragt höchstens alle 30 s, nur solange aktiv und sichtbar", async () => {
    vi.useFakeTimers();
    const call = vi.fn(async () => ok());
    const client = { current: { call } as unknown as ApiClient };
    const { rerender, unmount } = renderHook(({ active }) => useUsage(client, true, active), { initialProps: { active: true } });
    await act(async () => { await Promise.resolve(); });
    expect(call).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(USAGE_POLL_MS - 1000); });
    expect(call).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(1000); });
    expect(call).toHaveBeenCalledTimes(2);
    rerender({ active: false });                                      // nicht gezeigt: keine Abfrage
    await act(async () => { vi.advanceTimersByTime(USAGE_POLL_MS * 3); });
    expect(call).toHaveBeenCalledTimes(2);
    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    rerender({ active: true });                                       // verdeckt: keine Abfrage
    await act(async () => { vi.advanceTimersByTime(USAGE_POLL_MS * 3); });
    expect(call).toHaveBeenCalledTimes(2);
    Object.defineProperty(document, "hidden", { configurable: true, value: false });
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(call).toHaveBeenCalledTimes(3);                            // wieder sichtbar: einmal nachholen
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(call).toHaveBeenCalledTimes(3);                            // nicht öfter als alle 30 s
    unmount();
    await act(async () => { vi.advanceTimersByTime(USAGE_POLL_MS * 3); });
    expect(call).toHaveBeenCalledTimes(3);                            // Intervall und Listener aufgeräumt
  });

  it("verdecktes Fenster: das kleine Fenster sendet kein usage.get", async () => {
    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    const sock: { current?: MockSocket } = {};
    render(<App load={loaderWith(sock)} />);
    await waitFor(() => expect(screen.getAllByText(STATE_VIEW.idle.label).length).toBeGreaterThan(0));
    await toSmall();
    await act(async () => { await new Promise((r) => setTimeout(r, 100)); });
    expect(sentTypes(sock.current!)).not.toContain("usage.get");
  });

  it("Typen und Grenzen: nur Zahlen von 0 bis 100, Kosten endlich und nicht negativ, ohne stale gilt veraltet, Zukunft ist nicht lesbar", () => {
    type OkUsage = Extract<Usage, { kind: "ok" }>;
    const u = (x: Record<string, unknown>) => parseUsage(ok(x)) as OkUsage;
    expect(u({ context_pct: "42" }).context).toBeNull();
    expect(u({ context_pct: -1 }).context).toBeNull();
    expect(u({ context_pct: 0 }).context).toBe(0);
    expect(usageParts(u({ context_pct: 0, five_h_pct: 100, seven_d_pct: 100.0001 }))).toEqual(["Opus", "Kontext 0 %", "5h 100 %"]);
    for (const cost of [NaN, Infinity, -Infinity, -1, "1.5"]) expect(u({ cost_usd: cost }).cost).toBeNull();
    expect(u({ cost_usd: 0 }).cost).toBe(0);
    const { stale: _drop, ...noStale } = usageDemo("frisch");
    expect((parseUsage({ ok: true, ...noStale }) as OkUsage).stale).toBe(true);
    expect(parseUsage(ok({ stand: Date.now() / 1000 + 3600 }))).toEqual({ kind: "bad" });
    expect(u({ stand: Date.now() / 1000 + 60 }).kind).toBe("ok");                       // kleine Uhrabweichung geht
    expect(u({ model: "Op‮us\u0007 4 .5​\n" }).model).toBe("Opus 4.5");  // Steuer-, Format- und Richtungszeichen weg
    expect(u({ model: 42 }).model).toBe("");
  });

  it("Fehlerantworten behalten den letzten Stand; nur unknown_type zeigt den Hinweis", async () => {
    vi.useFakeTimers();
    const replies: unknown[] = [ok(), { ok: false, error: "timeout" }, { ok: false, error: "offline" }, { ok: false, error: "unknown_type" }];
    const call = vi.fn(async () => replies.shift());
    const client = { current: { call } as unknown as ApiClient };
    const { result } = renderHook(() => useUsage(client, true, true));
    await act(async () => { await Promise.resolve(); });
    expect(result.current?.kind).toBe("ok");
    const first = result.current;
    for (let i = 0; i < 2; i++) {
      await act(async () => { vi.advanceTimersByTime(USAGE_POLL_MS); });
      expect(result.current).toBe(first);
    }
    await act(async () => { vi.advanceTimersByTime(USAGE_POLL_MS); });
    expect(result.current).toEqual({ kind: "none" });
    expect(call).toHaveBeenCalledTimes(4);
  });
});

describe("Freigaben im kleinen Fenster: Abläufe", () => {
  const REQ2 = { ...REQ, request_id: "r2", digest: "b".repeat(64), input_preview: "zweite Anfrage" };
  const winCalls = () => invoke.mock.calls.map(([cmd, args]) => `${cmd}${(args as { on?: boolean } | undefined)?.on === undefined ? "" : `:${(args as { on: boolean }).on}`}`);

  it("beim Start wird der Rustteil einmal auf groß gesetzt (F5 im kleinen Fenster)", async () => {
    tauri(true);
    const sock: { current?: MockSocket } = {};
    await start(sock);
    expect(winCalls()).toEqual(["set_compact:false"]);
  });

  it("Reihenfolge: set_compact ist fertig, bevor grow_for_approval startet; zurück erst set_compact, dann grow(false)", async () => {
    tauri(true);
    const log: string[] = [];
    invoke.mockImplementation(async (cmd: string, args?: unknown) => {
      const on = (args as { on?: boolean } | undefined)?.on;
      log.push(`start ${cmd} ${on}`);
      if (cmd === "set_compact") await new Promise((r) => setTimeout(r, 60));      // langsamer Befehl: darf nicht überholt werden
      log.push(`ende ${cmd} ${on}`);
      return undefined;
    });
    const sock: { current?: MockSocket } = {};
    await start(sock, (m) => { m.pending = [{ ...REQ }]; });
    await waitFor(() => expect(screen.getByRole("alertdialog")).toBeInTheDocument(), { timeout: 3000 });
    await waitFor(() => expect(log).toEqual(["start set_compact false", "ende set_compact false"]));   // Start-Befehl (F5) fertig
    log.length = 0;
    await toSmall();
    await waitFor(() => expect(log).toContain("ende attention undefined"));
    expect(log).toEqual(["start set_compact true", "ende set_compact true", "start grow_for_approval true", "ende grow_for_approval true",
      "start attention undefined", "ende attention undefined"]);
    log.length = 0;
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Groß" })); });
    await waitFor(() => expect(log).toContain("ende grow_for_approval false"));
    expect(log).toEqual(["start set_compact false", "ende set_compact false", "start grow_for_approval false", "ende grow_for_approval false"]);
  });

  it("mehrere Anfragen nacheinander: je Anfrage neue Sperre und einmal Blinken, dazwischen nicht klein, „Noch 1 weitere“", async () => {
    tauri(true);
    const sock: { current?: MockSocket } = {};
    await start(sock, (m) => { m.pending = [{ ...REQ }, { ...REQ2 }]; });
    await toSmall();
    const bar = await screen.findByRole("alertdialog", {}, { timeout: 3000 });
    expect(bar).toHaveTextContent("Noch 1 weitere Anfrage(n) offen.");
    let deny = within(bar).getByRole("button", { name: "Ablehnen" });
    await waitFor(() => expect(deny).toBeEnabled(), { timeout: 2000 });
    await act(async () => { fireEvent.click(deny); });
    await waitFor(() => expect(screen.getByRole("alertdialog").querySelector("pre")!.textContent).toContain("zweite Anfrage"));
    const bar2 = screen.getByRole("alertdialog");
    deny = within(bar2).getByRole("button", { name: "Ablehnen" });
    expect(deny).toBeDisabled();                                                         // neue Sperre für die nachrückende Anfrage
    expect(within(bar2).getByRole("button", { name: "Erlauben" })).toBeDisabled();
    expect(bar2).not.toHaveTextContent("weitere Anfrage");
    await waitFor(() => expect(winCalls().filter((c) => c === "attention")).toHaveLength(2));
    expect(winCalls()).not.toContain("grow_for_approval:false");
    expect(winCalls().filter((c) => c === "grow_for_approval:true")).toHaveLength(1);
    await waitFor(() => expect(deny).toBeEnabled(), { timeout: 2000 });
    expect(deny).toHaveFocus();
    await act(async () => { fireEvent.click(deny); });
    await waitFor(() => expect(winCalls()).toContain("grow_for_approval:false"));
    expect(sock.current!.sent.filter((m) => (m as { type: string }).type === "approvals.decide")
      .map((m) => [(m as { request_id: string }).request_id, (m as { approve: boolean }).approve])).toEqual([["r1", false], ["r2", false]]);
  });

  it("NOTAUS während einer offenen Freigabe: Leiste weg, wieder klein, nichts entschieden; nach dem Aufheben wächst es wieder", async () => {
    tauri(true);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const sock: { current?: MockSocket } = {};
    await start(sock, (m) => { m.pending = [{ ...REQ }]; });
    await toSmall();
    await screen.findByRole("alertdialog", {}, { timeout: 3000 });
    await waitFor(() => expect(winCalls()).toContain("grow_for_approval:true"));
    await act(async () => { fireEvent.click(within(compactBox()).getByRole("button", { name: "NOTAUS" })); });
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    await waitFor(() => expect(winCalls()).toContain("grow_for_approval:false"));
    expect(compactBox()).toHaveAttribute("data-mode", "klein");
    expect(sentTypes(sock.current!)).not.toContain("approvals.decide");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Notaus aufheben" })); });
    await screen.findByRole("alertdialog", {}, { timeout: 3000 });
    await waitFor(() => expect(winCalls().filter((c) => c === "grow_for_approval:true")).toHaveLength(2));
    expect(sentTypes(sock.current!)).not.toContain("approvals.decide");
  });

  it("„Groß“ und „Klein“ während einer Freigabe: dieselbe eine Leiste mit neuer Sperre, nichts entschieden", async () => {
    tauri(true);
    const sock: { current?: MockSocket } = {};
    await start(sock, (m) => { m.pending = [{ ...REQ }]; });
    await toSmall();
    let bar = await screen.findByRole("alertdialog", {}, { timeout: 3000 });
    await waitFor(() => expect(within(bar).getByRole("button", { name: "Ablehnen" })).toBeEnabled(), { timeout: 2000 });
    invoke.mockClear();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Groß" })); });
    expect(screen.getAllByRole("alertdialog")).toHaveLength(1);
    bar = screen.getByRole("alertdialog");
    expect(screen.queryByRole("region", { name: "Kleines Fenster" })).toBeNull();
    expect(within(bar).getByRole("button", { name: "Ablehnen" })).toBeDisabled();       // neue Sperre im großen Fenster
    await waitFor(() => expect(winCalls()).toEqual(["set_compact:false", "grow_for_approval:false"]));
    await waitFor(() => expect(within(bar).getByRole("button", { name: "Ablehnen" })).toBeEnabled(), { timeout: 2000 });
    invoke.mockClear();
    await toSmall();
    expect(screen.getAllByRole("alertdialog")).toHaveLength(1);
    bar = screen.getByRole("alertdialog");
    expect(compactBox()).toContainElement(bar);
    expect(within(bar).getByRole("button", { name: "Ablehnen" })).toBeDisabled();       // und wieder neu im kleinen
    await waitFor(() => expect(winCalls()).toEqual(["set_compact:true", "grow_for_approval:true", "attention"]));
    expect(sentTypes(sock.current!)).not.toContain("approvals.decide");
  });
});

describe("Was im kleinen Fenster weiterläuft und was nicht", () => {
  const tick = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
  const fake = () => vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });

  it("Gedächtnis: eine begonnene Löschung übersteht das kleine Fenster und geht genau einmal zur Frist raus", async () => {
    fake();
    const sock: { current?: MockSocket } = {};
    render(<App load={loaderWith(sock, (m) => {
      m.facts = [{ id: 1, text: "Ich trinke gern Tee", kind: "preference", source: "user", created: 1_700_000_000 }];
    })} />);
    await tick(100);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Gedächtnis" })); });
    await tick(400);
    expect(screen.getByText("Ich trinke gern Tee")).toBeInTheDocument();
    const deletes = () => sentTypes(sock.current!).filter((t) => t === "memory.delete").length;
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /^Löschen/ })); });
    await tick(2000);
    await toSmall();
    await tick(7900);                                                                     // 9,9 s nach dem Klick: noch nichts
    expect(deletes()).toBe(0);
    await tick(200);                                                                      // 10,1 s: genau einmal
    expect(deletes()).toBe(1);
    expect(sock.current!.sent.find((m) => (m as { type: string }).type === "memory.delete")).toMatchObject({ id: 1, confirm: true });
    await tick(15000);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Groß" })); });
    await tick(500);
    expect(deletes()).toBe(1);
    expect(screen.queryByText("Ich trinke gern Tee")).toBeNull();
    expect(screen.getByRole("button", { name: "Gedächtnis" })).toHaveAttribute("aria-current", "page");
  });

  it("das große Layout behält seinen Zustand: Bereich, Suchtext, Scrollposition; Fokus danach auf „Klein“; je Modus genau ein Kern", async () => {
    const sock: { current?: MockSocket } = {};
    await start(sock);
    expect(document.querySelectorAll('[role="img"]')).toHaveLength(1);                 // großer Kern
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Gedächtnis" })); });
    fireEvent.change(screen.getByLabelText("Gedächtnis durchsuchen"), { target: { value: "Tee und Kaffee" } });
    const main = document.querySelector("main.view") as HTMLElement;
    let scroll = 240;
    Object.defineProperty(main, "scrollTop", { configurable: true, get: () => scroll, set: (v: number) => { scroll = v; } });
    await toSmall();
    expect(document.querySelector("main.view")).toBe(main);                              // derselbe Bereich, nicht neu gebaut
    expect(main).toHaveAttribute("hidden");
    expect(document.querySelectorAll('[role="img"]')).toHaveLength(1);                 // nur der kleine Kern
    expect(compactBox().querySelector('[role="img"]')).not.toBeNull();
    scroll = 0;                                                                           // so verhält sich ein versteckter Bereich im Browser
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Groß" })); });
    expect(main).not.toHaveAttribute("hidden");
    expect(scroll).toBe(240);
    expect(screen.getByLabelText("Gedächtnis durchsuchen")).toHaveValue("Tee und Kaffee");
    expect(screen.getByRole("button", { name: "Gedächtnis" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Klein" })).toHaveFocus();
    expect(document.querySelectorAll('[role="img"]')).toHaveLength(0);                 // Gedächtnis offen: kein Kern
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Start" })); });
    expect(document.querySelectorAll('[role="img"]')).toHaveLength(1);
  });

  it("Systemwerte werden im kleinen Fenster nicht abgefragt, Esc schliesst dort keine Ansicht, und es gibt keinen zweiten Kern", async () => {
    fake();
    const sock: { current?: MockSocket } = {};
    render(<App load={loaderWith(sock, (m) => { m.show(DEMO_VIEWS[3]); })} />);
    await tick(3500);
    const stats = () => sentTypes(sock.current!).filter((t) => t === "system.stats").length;
    expect(stats()).toBeGreaterThan(0);
    expect(document.querySelector(".view-card")).not.toBeNull();
    await toSmall();
    expect(document.querySelector("main.view")).toHaveAttribute("hidden");               // Bühne bleibt eingehängt, nur versteckt
    expect(document.querySelector("main.view .view-card")).not.toBeNull();
    expect(document.querySelectorAll('[role="img"]')).toHaveLength(1);                 // nur der kleine Kern
    expect(compactBox().querySelector('[role="img"]')).not.toBeNull();
    const before = stats();
    await tick(10000);
    expect(stats()).toBe(before);
    await act(async () => { fireEvent.keyDown(window, { key: "Escape" }); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Groß" })); });
    await tick(100);
    expect(document.querySelector(".view-card")).not.toBeNull();                         // Ansicht noch da
    await tick(3100);
    expect(stats()).toBeGreaterThan(before);                                             // im großen Fenster wieder
  });
});
