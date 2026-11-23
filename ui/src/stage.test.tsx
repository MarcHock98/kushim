import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "./App";
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
  render(<App load={loader} />);
  await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
  return sock;
}
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
