import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "./App";
import { hasWebGL } from "./components/Core3D";
import { ApiClient } from "./lib/api";
import { STATE_VIEW } from "./lib/avatarState";
import { MockSocket } from "./lib/mock";
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

describe("Bühne", () => {
  it("ohne WebGL (jsdom) zeichnet der 2D-Orb als Ersatz, mit Zustand als aria-label", async () => {
    expect(hasWebGL()).toBe(false);
    await open();
    expect(screen.getByRole("img")).toHaveAttribute("aria-label", STATE_VIEW.idle.label);
  });

  it("Ruhe: Kern groß ohne Karte; eine Antwort öffnet die Karte im Modus Begleiten", async () => {
    const sock = await open();
    expect(stage()).toHaveAttribute("data-mode", "ruhe");
    sock.current!.entries.push({ id: 1, heard: "Wie spät ist es?", reply: "Zehn Uhr.", outcome: "answered" });
    await waitFor(() => expect(stage()).toHaveAttribute("data-mode", "begleiten"), { timeout: 3000 });
    expect(screen.getByRole("article", { name: "Antwort" }).textContent).toContain("Zehn Uhr.");
  });

  it("Esc und der Schließen-Knopf bringen die Ruhe zurück", async () => {
    const sock = await open();
    sock.current!.entries.push({ id: 1, heard: "a", reply: "b", outcome: "answered" });
    await waitFor(() => expect(stage()).toHaveAttribute("data-mode", "begleiten"), { timeout: 3000 });
    await act(async () => { fireEvent.keyDown(window, { key: "Escape" }); });
    expect(stage()).toHaveAttribute("data-mode", "ruhe");
    sock.current!.entries.push({ id: 2, heard: "c", reply: "d", outcome: "answered" });
    await waitFor(() => expect(stage()).toHaveAttribute("data-mode", "begleiten"), { timeout: 3000 });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Schließen (Esc)" })); });
    expect(stage()).toHaveAttribute("data-mode", "ruhe");
  });

  it("eine neue Frage (Zuhören) räumt die Karte ab", async () => {
    const sock = await open();
    sock.current!.entries.push({ id: 1, heard: "a", reply: "b", outcome: "answered" });
    await waitFor(() => expect(stage()).toHaveAttribute("data-mode", "begleiten"), { timeout: 3000 });
    sock.current!.voice = { active: true, state: "listening", level: 0.3 };
    await waitFor(() => expect(stage()).toHaveAttribute("data-mode", "ruhe"), { timeout: 3000 });
  });

  it("der Kern ist in Ruhe groß und beim Begleiten klein, nie unter dem Minimum", () => {
    const box = { width: 1200, height: 900 };
    expect(coreSmall(box)).toBeLessThan(avatarSize(box));
    expect(coreSmall({ width: 200, height: 200 })).toBe(AVATAR_MIN);
  });
});
