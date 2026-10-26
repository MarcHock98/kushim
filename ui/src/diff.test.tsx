import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "./App";
import { ApiClient } from "./lib/api";
import { MockSocket } from "./lib/mock";

const TOKEN = "t".repeat(43);
afterEach(cleanup);

async function open() {
  const sock: { current?: MockSocket } = {};
  const loader = async () => ({
    client: new ApiClient({ port: 5000, token: TOKEN }, (u) => {
      const s = new MockSocket(u, TOKEN);
      s.folders = ["kushim"];
      s.session = { id: "s", folder: "kushim", branch: "b", turn: 1, status: "waiting", cost_usd: 0, seconds: 3, error: "", offers: [] };
      s.review = {
        files: [{ status: "M", path: "README.md" }, { status: "M", path: "src/kushim/safety/rules.py" }],
        protected: ["src/kushim/safety/rules.py"], shortstat: "2 files changed",
        overview: { done: "Fertig", question: "", next_steps: [] },
      };
      s.diffText = "@@ -1 +1 @@\n-alt\n+neu <b>fett</b>\n";
      sock.current = s;
      return s;
    }),
  });
  render(<App load={loader} />);
  await waitFor(() => screen.getByRole("list", { name: "Geänderte Dateien" }), { timeout: 3000 });
  return sock;
}

describe("Diff-Ansicht", () => {
  it("zeigt den Diff einer Datei nur nach Klick, als Text mit Hinzugefügt/Entfernt-Markierung", async () => {
    const sock = await open();
    expect(sock.current!.sent.some((m) => (m as { type: string }).type === "claude.diff")).toBe(false);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /README\.md/ })); });
    await waitFor(() => screen.getByLabelText("Diff README.md"));
    const pre = screen.getByLabelText("Diff README.md");
    expect(pre.querySelector(".add")?.textContent).toContain("+neu <b>fett</b>");     // Text, nicht HTML
    expect(pre.querySelector("b")).toBeNull();
    expect(pre.querySelector(".del")?.textContent).toContain("-alt");
    expect(pre.querySelector(".hunk")).not.toBeNull();
    expect(screen.queryByText(/Änderungen daran übernimmt nur der Nutzer/)).toBeNull();   // README ist nicht geschützt
  });

  it("geschützte Dateien werden in der Liste und im Diff gekennzeichnet", async () => {
    await open();
    expect(screen.getByRole("button", { name: /rules\.py \(geschützt\)/ })).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /rules\.py/ })); });
    await waitFor(() => screen.getByText(/Änderungen daran übernimmt nur der Nutzer/));
  });

  it("zweiter Klick schließt den Diff wieder", async () => {
    await open();
    const btn = screen.getByRole("button", { name: /README\.md/ });
    await act(async () => { fireEvent.click(btn); });
    await waitFor(() => screen.getByLabelText("Diff README.md"));
    await act(async () => { fireEvent.click(btn); });
    expect(screen.queryByLabelText("Diff README.md")).toBeNull();
  });
});

describe("Abfragen", () => {
  it("holt den Bericht (mehrere git-Befehle im Backend) nur einmal, solange sich der Lauf nicht ändert", async () => {
    const sock = await open();
    await new Promise((r) => setTimeout(r, 4600));                                   // mehr als zwei Abfragerunden
    const types = sock.current!.sent.map((m) => (m as { type: string }).type);
    expect(types.filter((t) => t === "claude.status").length).toBeGreaterThanOrEqual(2);
    expect(types.filter((t) => t === "claude.review")).toHaveLength(1);
  }, 15000);
});
