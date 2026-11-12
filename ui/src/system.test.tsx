import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "./App";
import { parseSystem } from "./components/SystemPanel";
import { ApiClient } from "./lib/api";
import { STATE_VIEW } from "./lib/avatarState";
import { MockSocket } from "./lib/mock";

const TOKEN = "t".repeat(43);
afterEach(cleanup);

async function open(system: Record<string, unknown> | null | undefined = undefined) {
  const sock: { current?: MockSocket } = {};
  const loader = async () => ({
    client: new ApiClient({ port: 5000, token: TOKEN }, (u) => {
      sock.current = new MockSocket(u, TOKEN);
      if (system === null) sock.current.system = null;
      else if (system) sock.current.system = { ...sock.current.system, ...system };
      return sock.current;
    }),
  });
  render(<App load={loader} />);
  await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
  sock.current!.entries.push({ id: 1, heard: "Wie ist die Systemauslastung?", reply: "Gleich.", outcome: "spoken" });   // kushim soll es zeigen
  await waitFor(() => panel(), { timeout: 3000 });
  return sock;
}

const panel = () => screen.getByRole("region", { name: "Systemzustand" });

describe("Systemzustand", () => {
  it("zeigt die Werte des Dienstes auf der Startseite", async () => {
    await open();
    await waitFor(() => within(panel()).getByText("34 %"));
    const p = within(panel());
    expect(p.getByText("Alle Werte unter 80 %")).toBeInTheDocument();
    expect(p.getByText("9,8 von 16 GB")).toBeInTheDocument();
    expect(p.getByText(/VRAM 3 von 8 GB · 58 °C/)).toBeInTheDocument();
    expect(p.getByText("42,1")).toBeInTheDocument();
    expect(p.getByText(/412 von 1\.000 GB · 41 %/)).toBeInTheDocument();
    expect(p.getByText("kein Akku")).toBeInTheDocument();
    expect(p.getByText("Windows 11")).toBeInTheDocument();
    expect(p.getByText("6 T 14 Std")).toBeInTheDocument();
  });

  it("warnt ab dem Warnwert mit Wort und Symbol, nicht nur mit Farbe", async () => {
    await open({ cpu: { percent: 91 }, disk: { percent: 94, used_gb: 3518, total_gb: 3725 } });
    await waitFor(() => within(panel()).getByText("91 %"));
    expect(within(panel()).getByText("2 Werte hoch")).toBeInTheDocument();
    expect(within(panel()).getAllByText("hoch")).toHaveLength(2);
  });

  it("fehlende oder falsche Werte heißen „unbekannt“, nichts wird erfunden", async () => {
    await open({ cpu: null, gpu: { percent: "viel" }, net: null, battery: null });
    await waitFor(() => within(panel()).getByText("9,8 von 16 GB"));
    expect(within(panel()).getAllByText("unbekannt").length).toBe(4);       // CPU, GPU, Netz, Akku
  });

  it("ein Dienst ohne system.stats bekommt einen ehrlichen Hinweis statt ewig zu laden", async () => {
    await open(null);
    await waitFor(() => within(panel()).getByText(/liefert keine Systemwerte/));
    expect(within(panel()).getByText("nicht verfügbar")).toBeInTheDocument();
  });

  it("fragt nur ab, solange der Systemzustand gezeigt wird", async () => {
    const sock = await open();
    await waitFor(() => within(panel()).getByText("34 %"));
    await act(async () => { fireEvent.keyDown(window, { key: "Escape" }); });
    expect(screen.queryByRole("region", { name: "Systemzustand" })).toBeNull();
    const before = (sock.current!.sent as { type?: string }[]).filter((m) => m.type === "system.stats").length;
    await new Promise((r) => setTimeout(r, 3300));
    const after = (sock.current!.sent as { type?: string }[]).filter((m) => m.type === "system.stats").length;
    expect(after).toBe(before);
  }, 8000);

  it("parseSystem kürzt lange Texte und verwirft falsche Typen", () => {
    const d = parseSystem({ system: { os: "x".repeat(200), uptime_s: "lang" }, memory: { percent: 5 }, warn_at: "hoch" });
    expect(d.system.os).toHaveLength(40);
    expect(d.system.uptime_s).toBeNull();
    expect(d.memory).toBeNull();
    expect(d.warn_at).toBe(80);
  });
});
