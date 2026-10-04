import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "./App";
import { ApiClient } from "./lib/api";
import { STATE_VIEW } from "./lib/avatarState";
import { MockSocket } from "./lib/mock";

const TOKEN = "t".repeat(43);
afterEach(cleanup);

async function open(dash: Record<string, unknown> = {}, overview: Record<string, unknown> = {}) {
  const sock: { current?: MockSocket } = {};
  const loader = async () => ({
    client: new ApiClient({ port: 5000, token: TOKEN }, (u) => {
      sock.current = new MockSocket(u, TOKEN);
      Object.assign(sock.current.dash, dash);
      Object.assign(sock.current.overview, overview);
      return sock.current;
    }),
  });
  render(<App load={loader} />);
  await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Übersicht" })); });
  await waitFor(() => screen.getByLabelText("Übersicht"), { timeout: 3000 });
  return sock;
}

describe("Übersicht", () => {
  it("zeigt Leerzustände mit Hinweis, wenn nichts da ist", async () => {
    await open();
    expect(screen.getByText(/Keine Timer und keine laufenden Aufgaben/)).toBeInTheDocument();
    expect(screen.getByText(/Keine Recherche gestartet/)).toBeInTheDocument();
    expect(screen.getByText(/Noch keine Aktionen protokolliert/)).toBeInTheDocument();
  });

  it("zeigt Timer mit Restzeit, Aufgaben und wartende Freigaben", async () => {
    await open({ timers: [{ id: "a", label: "Nudeln", due_in: 125 }], tasks: ["Recherche"], pending_approvals: 1 });
    expect(screen.getByText("Nudeln")).toBeInTheDocument();
    expect(screen.getByText(/^2:0\d$/)).toBeInTheDocument();
    expect(screen.getByText("Recherche")).toBeInTheDocument();
    expect(screen.getByText(/1 Freigabe\(n\) warten/)).toBeInTheDocument();
  });

  it("Ergebnisse mit Quellen: nur Text, kein Link, nie HTML", async () => {
    await open({
      results: [{ ts: 5, query: "Eiffelturm", kind: "claude", answer: "324 Meter <b>hoch</b>", note: "", sources: [
        { title: "Eiffelturm", url: "https://de.wikipedia.org/wiki/Eiffelturm" }] }],
    });
    expect(screen.getByText("324 Meter <b>hoch</b>")).toBeInTheDocument();
    expect(document.querySelector(".result b")).toBeNull();
    expect(screen.getByText("https://de.wikipedia.org/wiki/Eiffelturm")).toBeInTheDocument();
    expect(document.querySelector(".dash a")).toBeNull();                      // nichts wird von selbst geöffnet
  });

  it("Aktivität zeigt die letzten Entscheidungen, neueste zuerst", async () => {
    await open({}, { audit: [{ ts: 1, event: "action_allow", detail: "alt" }, { ts: 2, event: "action_deny", detail: "neu" }] });
    const items = document.querySelectorAll(".dash .audit li");
    expect(items[0].textContent).toContain("action_deny");
  });
});
