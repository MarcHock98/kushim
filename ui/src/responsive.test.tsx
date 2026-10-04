import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { ApiClient } from "./lib/api";
import { STATE_VIEW } from "./lib/avatarState";
import { MockSocket } from "./lib/mock";
import { AVATAR_DEFAULT, AVATAR_MAX, AVATAR_MIN, avatarSize } from "./lib/useBoxSize";

const TOKEN = "t".repeat(43);
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const loader = async () => ({
  client: new ApiClient({ port: 5000, token: TOKEN }, (u) => new MockSocket(u, TOKEN)),
});

describe("Avatar-Größe", () => {
  it("ohne Messung gilt der Standard, sonst wächst und schrumpft sie mit dem Fenster, immer innerhalb der Grenzen", () => {
    expect(avatarSize(null)).toBe(AVATAR_DEFAULT);
    expect(avatarSize({ width: 320, height: 420 })).toBeGreaterThanOrEqual(AVATAR_MIN);
    expect(avatarSize({ width: 320, height: 420 })).toBeLessThan(avatarSize({ width: 1400, height: 900 }) + 1);
    expect(avatarSize({ width: 3000, height: 3000 })).toBe(AVATAR_MAX);
    expect(avatarSize({ width: 10, height: 10 })).toBe(AVATAR_MIN);
  });

  it("richtet sich nach der kleineren Seite: ein breites, aber niedriges Fenster bekommt keinen riesigen Avatar", () => {
    expect(avatarSize({ width: 1400, height: 300 })).toBeLessThan(avatarSize({ width: 1400, height: 900 }));
  });
});

describe("Navigation", () => {
  it("vier Bereiche als Navigation mit Beschriftung, der aktive trägt aria-current, Wechsel funktioniert", async () => {
    render(<App load={loader} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    const nav = screen.getByRole("navigation", { name: "Bereiche" });
    const buttons = nav.querySelectorAll("button");
    expect([...buttons].map((b) => b.textContent)).toEqual(["Start", "Übersicht", "Gedächtnis", "Sicherheit"]);
    expect(buttons[0]).toHaveAttribute("aria-current", "page");
    expect(nav.querySelector("svg[aria-hidden='true']")).not.toBeNull();                 // Symbole sind für Screenreader verborgen
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Sicherheit" })); });
    expect(screen.getByRole("button", { name: "Sicherheit" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Start" })).not.toHaveAttribute("aria-current");
  });

  it("NOTAUS steht in jeder Ansicht in der Kopfzeile, nie in der Navigation versteckt", async () => {
    render(<App load={loader} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    for (const name of ["Übersicht", "Gedächtnis", "Sicherheit", "Start"]) {
      await act(async () => { fireEvent.click(screen.getByRole("button", { name })); });
      expect(document.querySelector(".head .kill")).not.toBeNull();
    }
  });

  it("der Avatar übernimmt die gemessene Größe des Bereichs (ResizeObserver)", async () => {
    let cb: ResizeObserverCallback = () => {};
    vi.stubGlobal("ResizeObserver", class { constructor(c: ResizeObserverCallback) { cb = c; } observe() {} disconnect() {} unobserve() {} });
    render(<App load={loader} />);
    await waitFor(() => screen.getByRole("img"));
    expect(screen.getByRole("img")).toHaveStyle({ width: `${AVATAR_DEFAULT}px` });
    await act(async () => { cb([{ contentRect: { width: 400, height: 500 } } as ResizeObserverEntry], {} as ResizeObserver); });
    await waitFor(() => expect(screen.getByRole("img")).toHaveStyle({ width: "180px" }));      // min(400*0,55=220, 500*0,36=180)
    await act(async () => { cb([{ contentRect: { width: 1600, height: 1000 } } as ResizeObserverEntry], {} as ResizeObserver); });
    await waitFor(() => expect(screen.getByRole("img")).toHaveStyle({ width: `${AVATAR_MAX}px` }));
  });
});

describe("Dienst ohne Übersicht (kushim serve)", () => {
  it("sagt ehrlich, dass es die Übersicht nur mit dem Sprachdienst gibt, statt ewig zu laden", async () => {
    const client = new ApiClient({ port: 5000, token: TOKEN }, (u) => {
      const s = new MockSocket(u, TOKEN);
      const send = s.send.bind(s);
      s.send = (d: string) => (JSON.parse(d).type === "dashboard.get"
        ? queueMicrotask(() => s.onmessage?.({ data: JSON.stringify({ ok: false, error: "unknown_type" }) }))
        : send(d));
      return s;
    });
    render(<App load={async () => ({ client })} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Übersicht" })); });
    await waitFor(() => screen.getByText(/nur mit dem Sprachdienst/));
    expect(screen.queryByText(/wird geladen/)).toBeNull();
  });
});
