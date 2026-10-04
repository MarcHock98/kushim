import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { MemoryPanel } from "./components/MemoryPanel";
import { ApiClient } from "./lib/api";
import { MockSocket } from "./lib/mock";

const TOKEN = "t".repeat(43);
afterEach(cleanup);

const FACTS = [
  { id: 1, text: "Ich trinke gern Tee", kind: "preference", source: "user", created: 1_700_000_000 },
  { id: 2, text: "Meine Katze heißt <b>Mia</b>", kind: "person", source: "user", created: 1_700_000_100 },
];

async function setup(undoMs = 150) {
  const sock: { current?: MockSocket } = {};
  const client = new ApiClient({ port: 5000, token: TOKEN }, (u) => {
    sock.current = new MockSocket(u, TOKEN);
    sock.current.facts = FACTS.map((f) => ({ ...f }));
    return sock.current;
  });
  await client.connect();
  const ref = createRef<ApiClient | null>() as { current: ApiClient | null };
  ref.current = client;
  render(<MemoryPanel client={ref} connected active undoMs={undoMs} />);
  await waitFor(() => screen.getByText("Ich trinke gern Tee"), { timeout: 2000 });
  return sock.current!;
}

const sentTypes = (s: MockSocket) => s.sent.map((m) => (m as { type: string }).type);

describe("Gedächtnis", () => {
  it("Bearbeiten: Speichern sendet Text, Art und confirm; Abbrechen sendet nichts", async () => {
    const sock = await setup();
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: /^Bearbeiten/ })[0]); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Abbrechen" })); });
    expect(sentTypes(sock)).not.toContain("memory.update");
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: /^Bearbeiten/ })[0]); });
    fireEvent.change(screen.getByLabelText("Erinnerung bearbeiten"), { target: { value: "Ich trinke gern Kaffee" } });
    fireEvent.change(screen.getByLabelText("Art"), { target: { value: "routine" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Speichern" })); });
    const upd = sock.sent.find((m) => (m as { type: string }).type === "memory.update") as { id: number; text: string; kind: string; confirm: boolean };
    expect(upd).toMatchObject({ id: 1, text: "Ich trinke gern Kaffee", kind: "routine", confirm: true });
    await waitFor(() => screen.getByText("Ich trinke gern Kaffee"), { timeout: 2000 });
    expect(screen.getByText("Gespeichert.")).toBeInTheDocument();
  });

  it("zeigt Einträge als reinen Text und filtert beim Suchen", async () => {
    await setup();
    expect(screen.getByText("Meine Katze heißt <b>Mia</b>")).toBeInTheDocument();
    expect(document.querySelector(".fact b")).toBeNull();
    fireEvent.change(screen.getByLabelText("Gedächtnis durchsuchen"), { target: { value: "tee" } });
    await waitFor(() => expect(screen.queryByText(/Katze/)).toBeNull(), { timeout: 2000 });
    expect(screen.getByText("Ich trinke gern Tee")).toBeInTheDocument();
  });

  it("Löschen: sofort ausgeblendet, aber erst nach der Frist wirklich gelöscht (mit confirm)", async () => {
    const sock = await setup(300);
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: /^Löschen/ })[0]); });
    expect(screen.queryByText("Ich trinke gern Tee")).toBeNull();               // erste Zeile ausgeblendet
    expect(screen.getByText("Meine Katze heißt <b>Mia</b>")).toBeInTheDocument();   // die andere bleibt
    expect(screen.getByText(/Gelöscht in 10 Sekunden/)).toBeInTheDocument();
    expect(sentTypes(sock)).not.toContain("memory.delete");                    // noch nichts gelöscht
    await waitFor(() => expect(sentTypes(sock)).toContain("memory.delete"), { timeout: 2000 });
    const del = sock.sent.find((m) => (m as { type: string }).type === "memory.delete") as { id: number; confirm: boolean };
    expect(del).toMatchObject({ id: 1, confirm: true });
    await waitFor(() => expect(screen.queryByText(/Gelöscht in 10 Sekunden/)).toBeNull());
  });

  it("Rückgängig stellt den Eintrag wieder her und löscht nie", async () => {
    const sock = await setup(300);
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: /^Löschen/ })[0]); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Rückgängig" })); });
    expect(screen.getByText("Ich trinke gern Tee")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 500));
    expect(sentTypes(sock)).not.toContain("memory.delete");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("zeigt den Leerzustand", async () => {
    const sock: { current?: MockSocket } = {};
    const client = new ApiClient({ port: 5000, token: TOKEN }, (u) => (sock.current = new MockSocket(u, TOKEN)));
    await client.connect();
    render(<MemoryPanel client={{ current: client }} connected active />);
    await waitFor(() => screen.getByText("Noch keine Erinnerungen."), { timeout: 2000 });
  });
});
