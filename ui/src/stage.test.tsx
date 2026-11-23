import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App, staged } from "./App";
import { hasWebGL } from "./components/Core3D";
import { ApiClient } from "./lib/api";
import { STATE_VIEW } from "./lib/avatarState";
import { MockSocket, transcriptEntry } from "./lib/mock";
import { AVATAR_MIN, avatarSize, coreSmall } from "./lib/useBoxSize";

const TOKEN = "t".repeat(43);
afterEach(cleanup);

async function open() {
  const sock: { current?: MockSocket } = {};
  const loader = async () => ({
    client: new ApiClient({ port: 5000, token: TOKEN }, (u) => (sock.current = new MockSocket(u, TOKEN))),
  });
  const app = <App load={loader} />;
  const { rerender } = render(app);
  // Ansichten kommen aus Abfragen (außerhalb von act): waitFor sieht den Commit, bevor React dessen useEffect ausführt. React
  // führt offene Effekte vor jeder neuen Arbeit aus: dasselbe Element neu geben holt sie sofort nach (etwa den Esc-Listener).
  flushEffects = () => rerender(app);
  await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
  return sock;
}
let flushEffects = () => {};
const stage = () => screen.getByRole("region", { name: "Gespräch" });
const showSystem = async (sock: { current?: MockSocket }, id = 1) => {
  sock.current!.show({ id: `s${id}`, art: "antwort", titel: "System", bausteine: [{ typ: "systemzustand" }] });
  await waitFor(() => expect(stage()).toHaveAttribute("data-mode", "zeige"), { timeout: 3000 });
};

describe("Bühne", () => {
  it("ohne WebGL (jsdom) zeichnet der 2D-Orb als Ersatz, mit Zustand als aria-label", async () => {
    expect(hasWebGL()).toBe(false);
    await open();
    expect(screen.getByRole("img")).toHaveAttribute("aria-label", STATE_VIEW.idle.label);
  });

  it("im Gespräch nur der Kern: keine Standard-Panels auf dem Start", async () => {
    await open();
    expect(stage()).toHaveAttribute("data-mode", "dialog");
    for (const name of ["Systemzustand", "Verlauf", "Claude"]) expect(screen.queryByRole("region", { name })).toBeNull();
    expect(screen.queryByRole("complementary", { name: "Claude" })).toBeNull();
  });

  it("eine normale Antwort ändert nichts, der Kern bleibt groß in der Mitte", async () => {
    const sock = await open();
    sock.current!.entries.push(transcriptEntry({ id: 1, heard: "Wie spät ist es?", reply: "Zehn Uhr." }));
    await new Promise((r) => setTimeout(r, 1300));
    expect(stage()).toHaveAttribute("data-mode", "dialog");
  });

  it("fragt man nach dem System, zeigt kushim den Systemzustand; Esc und Schließen bringen das Gespräch zurück", async () => {
    const sock = await open();
    await showSystem(sock);
    expect(screen.getByRole("region", { name: "Systemzustand" })).toBeInTheDocument();
    flushEffects();
    await act(async () => { fireEvent.keyDown(window, { key: "Escape" }); });
    expect(stage()).toHaveAttribute("data-mode", "dialog");
    await showSystem(sock, 2);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Schließen (Esc)" })); });
    expect(stage()).toHaveAttribute("data-mode", "dialog");
  });

  it("eine neue Frage (Zuhören) bringt das Gespräch zurück", async () => {
    const sock = await open();
    await showSystem(sock);
    sock.current!.voice = { active: true, state: "listening", level: 0.3 };
    await waitFor(() => expect(stage()).toHaveAttribute("data-mode", "dialog"), { timeout: 3000 });
  });

  it("Verlauf und Claude stehen in der Übersicht", async () => {
    await open();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Übersicht" })); });
    expect(screen.getByRole("region", { name: "Verlauf" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Claude" })).toBeInTheDocument();
  });

  it("der Kern ist im Gespräch groß und im Zeige-Modus klein, nie unter dem Minimum", () => {
    const box = { width: 1200, height: 900 };
    expect(coreSmall(box)).toBeLessThan(avatarSize(box));
    expect(avatarSize(box)).toBeGreaterThanOrEqual(600 * 0.9);
    expect(coreSmall({ width: 200, height: 200 })).toBe(AVATAR_MIN);
  });
});

describe("View Transition beim schnellen Wechsel", () => {
  type Rej = (reason: unknown) => void;
  type Proc = { on(e: string, f: (r: unknown) => void): void; off(e: string, f: (r: unknown) => void): void };
  const proc = (globalThis as unknown as { process: Proc }).process;
  const tick = () => new Promise<void>((r) => setTimeout(r, 0));
  const SKIP = "Transition was skipped. New ViewTransition started";

  /** Falsches startViewTransition wie in Chromium: ruft den Wechsel kurz danach (nicht im Aufruf), dann scheitern die
   *  Versprechen mit `fail()`. */
  function fakeTransitions(fail: (name: string) => unknown) {
    const handled: string[] = [];
    const rejections: Promise<unknown>[] = [];
    const start = vi.fn((cb: () => void) => {
      queueMicrotask(cb);
      const t: Record<string, Promise<unknown>> = {};
      for (const name of ["ready", "finished", "updateCallbackDone"]) {
        let rej: Rej = () => undefined;
        const p = new Promise<unknown>((_res, r) => { rej = r; });
        const then = p.then.bind(p);
        p.then = ((ok?: (v: unknown) => unknown, bad?: Rej) => {     // wer einen Fehler-Zweig anhängt, fängt ab
          if (bad) handled.push(name);
          const next = then(ok, bad);
          rejections.push(next);
          return next;
        }) as typeof p.then;
        t[name] = p;
        queueMicrotask(() => rej(fail(name)));
      }
      return t;
    });
    Object.defineProperty(document, "startViewTransition", { value: start, configurable: true, writable: true });
    return { start, handled, rejections };
  }
  const unhandled: unknown[] = [];
  const onUnhandled = (r: unknown) => { unhandled.push(r); };
  beforeEach(() => { unhandled.length = 0; proc.on("unhandledRejection", onUnhandled); });
  afterEach(() => {
    proc.off("unhandledRejection", onUnhandled);
    delete (document as unknown as { startViewTransition?: unknown }).startViewTransition;
    vi.restoreAllMocks();
  });

  it("übersprungene Wechsel (AbortError, InvalidStateError) werfen keinen unbehandelten Fehler; der Wechsel selbst läuft", async () => {
    const vt = fakeTransitions((name) => new DOMException(SKIP, name === "finished" ? "InvalidStateError" : "AbortError"));
    const done: number[] = [];
    for (let i = 1; i <= 3; i++) staged(() => done.push(i));          // drei Wechsel kurz hintereinander
    expect(vt.start).toHaveBeenCalledTimes(3);
    expect(vt.handled.sort()).toEqual(Array.from({ length: 3 }, () => ["finished", "ready", "updateCallbackDone"]).flat().sort());
    await tick(); await tick();
    expect(done).toEqual([1, 2, 3]);                                  // jeder Wechsel kommt an, in Reihenfolge
    expect((await Promise.allSettled(vt.rejections)).every((s) => s.status === "fulfilled")).toBe(true);
    expect(unhandled).toEqual([]);
  });

  it("App: schnell wechselnde Ansichten im Demo lassen keinen unbehandelten Fehler zurück, die letzte Ansicht steht", async () => {
    const vt = fakeTransitions(() => new DOMException(SKIP, "AbortError"));
    const sock = await open();
    for (let i = 1; i <= 4; i++) sock.current!.show({ id: `w${i}`, art: "antwort", titel: `Wechsel ${i}`, bausteine: [{ typ: "text", absaetze: [`Satz ${i}`] }] });
    await screen.findByRole("heading", { name: "Wechsel 4" }, { timeout: 3000 });
    await waitFor(() => expect(stage()).toHaveAttribute("data-mode", "zeige"));
    expect(vt.start).toHaveBeenCalled();
    await tick(); await tick();
    await Promise.allSettled(vt.rejections);
    expect(unhandled).toEqual([]);
  });

  it("wirft der Wechsel selbst einen echten Fehler, bleibt er sichtbar (einmal, über updateCallbackDone)", async () => {
    const boom = new Error("kaputt");
    const vt = fakeTransitions(() => boom);
    staged(() => undefined);
    const settled = await Promise.allSettled(vt.rejections);
    const rejected = settled.filter((s): s is PromiseRejectedResult => s.status === "rejected");
    expect(rejected.map((s) => s.reason)).toEqual([boom]);
    await tick(); await tick();
    expect(unhandled).toEqual([]);                                    // hier abgefangen von allSettled; ohne Test wäre er sichtbar
  });

  it("ohne startViewTransition oder bei weniger Bewegung: sofort, ohne Animation", () => {
    const done: string[] = [];
    staged(() => done.push("ohne"));
    expect(done).toEqual(["ohne"]);
    const vt = fakeTransitions(() => new DOMException(SKIP, "AbortError"));
    vi.spyOn(window, "matchMedia").mockImplementation(((q: string) =>
      ({ matches: q === "(prefers-reduced-motion: reduce)", media: q, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia);
    staged(() => done.push("ruhig"));
    expect(done).toEqual(["ohne", "ruhig"]);
    expect(vt.start).not.toHaveBeenCalled();
  });
});
