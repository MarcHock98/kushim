import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "./App";
import { ApiClient } from "./lib/api";
import { MockSocket } from "./lib/mock";

const TOKEN = "t".repeat(43);
afterEach(cleanup);

async function open(folders: string[] = []) {
  const sock: { current?: MockSocket } = {};
  const loader = async () => ({
    client: new ApiClient({ port: 5000, token: TOKEN }, (u) => {
      sock.current = new MockSocket(u, TOKEN);
      sock.current.folders = [...folders];
      return sock.current;
    }),
  });
  render(<App load={loader} />);
  await waitFor(() => screen.getByLabelText("Name (klein, ohne Leerzeichen)"), { timeout: 3000 });
  return sock;
}

const types = (h: { current?: MockSocket }) => h.current!.sent.map((m) => (m as { type: string }).type);

async function fill(name: string, path: string) {
  fireEvent.change(screen.getByLabelText("Name (klein, ohne Leerzeichen)"), { target: { value: name } });
  fireEvent.change(screen.getByLabelText("Pfad zum Git-Ordner"), { target: { value: path } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Freigabe-Vorschau ansehen" })); });
}

describe("Ordner für Claude", () => {
  it("ohne Ordner: Hinweis und Formular; Freigeben zeigt erst die Vorschau mit dem Pfad, nichts wird ohne Klick freigegeben", async () => {
    const sock = await open();
    expect(screen.getByText("Claude: kein Ordner freigegeben.")).toBeInTheDocument();
    await fill("proj", "C:/projekte/proj");
    await waitFor(() => screen.getByText(/Claude darf in «C:\/projekte\/proj» arbeiten/));
    expect(screen.getByRole("button", { name: "Ablehnen" })).toHaveFocus();
    expect(types(sock)).not.toContain("claude.folder_confirm");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Erlauben" })); });
    const sent = sock.current!.sent.find((m) => (m as { type: string }).type === "claude.folder_confirm") as { confirm: boolean; proposal: string };
    expect(sent).toMatchObject({ confirm: true, proposal: "f1" });
    await waitFor(() => screen.getByText("Ordner freigegeben."));
    await waitFor(() => screen.getByLabelText("Auftrag"));                      // jetzt gibt es einen Ordner für Aufträge
  });

  it("Ablehnen gibt nichts frei und sendet claude.folder_deny", async () => {
    const sock = await open();
    await fill("proj", "C:/projekte/proj");
    await waitFor(() => screen.getByRole("button", { name: "Ablehnen" }));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Ablehnen" })); });
    expect(types(sock)).toContain("claude.folder_deny");
    expect(types(sock)).not.toContain("claude.folder_confirm");
    await waitFor(() => screen.getByText(/Nichts wurde freigegeben/));
  });

  it("zeigt die Ablehnung des Backends im Klartext und öffnet keine Freigabe-Leiste", async () => {
    await open();
    await fill("sys", "C:/Windows");
    await waitFor(() => screen.getByText(/geschützten Bereich/));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("Entziehen geht sofort, ohne Rückfrage", async () => {
    const sock = await open(["alt"]);
    await waitFor(() => screen.getByRole("button", { name: "Freigabe entziehen: alt" }));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Freigabe entziehen: alt" })); });
    expect(types(sock)).toContain("claude.folder_remove");
    await waitFor(() => screen.getByText(/Freigabe für «alt» entzogen/));
    await waitFor(() => screen.getByText("Claude: kein Ordner freigegeben."));
  });
});
