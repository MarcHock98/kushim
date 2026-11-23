import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { parseUsage, standText, USAGE_HINT, USAGE_POLL_MS, usageParts, useUsage, type Usage } from "./components/CompactBar";
import { ApiClient } from "./lib/api";
import { STATE_VIEW } from "./lib/avatarState";
import { DEMO_VIEWS, MockSocket, usageDemo } from "./lib/mock";

// E2 (docs/ui-e2e3-plan.md, Abschnitte 3, 4 und 7): kleines Fenster, Freigabe darin, Verbrauch, Tastenkürzel.

const { invoke } = vi.hoisted(() => ({ invoke: vi.fn(async (_cmd: string, _args?: unknown) => undefined) }));
vi.mock("@tauri-apps/api/core", () => ({ invoke }));

const TOKEN = "t".repeat(43);
const WINDOW_CMDS = ["set_compact", "set_always_on_top", "grow_for_approval", "attention"];
const POLLS = new Set(["safety.status", "voice.state", "approvals.get", "transcript.get", "safety.overview", "stage.get", "usage.get",
  "dashboard.get", "system.stats", "claude.folder_list", "memory.search"]);

const tauri = (on: boolean) => {
  const w = window as unknown as Record<string, unknown>;
  if (on) w.__TAURI_INTERNALS__ = {}; else delete w.__TAURI_INTERNALS__;
};

beforeEach(() => { invoke.mockClear(); });
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
      m.entries = [{ id: 1, heard: "<script>alert(1)</script>", reply: "Erste Zeile\nZweite Zeile", outcome: "spoken" }];
    });
    await toSmall();
    const you = await within(compactBox()).findByText("Du: <script>alert(1)</script>");
    expect(you).toHaveAttribute("title", "Du: <script>alert(1)</script>");
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
    expect(document.querySelector(".view-card")).toBeNull();
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
});
