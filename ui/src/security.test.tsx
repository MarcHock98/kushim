import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "./App";
import { ApiClient } from "./lib/api";
import { STATE_VIEW } from "./lib/avatarState";
import { MockSocket } from "./lib/mock";

const TOKEN = "t".repeat(43);
afterEach(cleanup);

async function open(overview: Record<string, unknown>) {
  const sock: { current?: MockSocket } = {};
  const loader = async () => ({
    client: new ApiClient({ port: 5000, token: TOKEN }, (u) => {
      sock.current = new MockSocket(u, TOKEN);
      Object.assign(sock.current.overview, overview);
      return sock.current;
    }),
  });
  render(<App load={loader} />);
  await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Sicherheit" })); });
  await waitFor(() => screen.getByLabelText("Sicherheitsstatus"));
  return sock;
}

describe("Sicherheitsstatus", () => {
  it("zeigt jeden Punkt mit Wort: Modus A, Geldlimit 0, Notaus bereit, Sicherung", async () => {
    await open({});
    expect(screen.getByText(/Lokal \(Modus A\)/)).toBeInTheDocument();
    expect(screen.getByText(/0 €, gesperrt/)).toBeInTheDocument();
    expect(screen.getByText(/bereit/)).toBeInTheDocument();
    expect(screen.getByText(/vor 2 Tagen/)).toBeInTheDocument();
    expect(document.querySelector(".head .mode-c")).toBeNull();
  });

  it("Modus C steht als Warnung im Bildschirm UND dauerhaft als Chip in der Kopfzeile", async () => {
    await open({ mode: "C" });
    expect(screen.getByText(/Claude erlaubt \(Modus C\)/)).toBeInTheDocument();
    expect(screen.getByText(/Modus C ist aktiv/)).toBeInTheDocument();
    expect(document.querySelector(".head .mode-c")).not.toBeNull();
  });

  it("warnt bei alter Sicherung und fehlendem Vault", async () => {
    await open({ backup: { configured: true, age_days: 12 }, vault: { where: "local", exists: false, open: false } });
    expect(screen.getByText(/älter als 7 Tage/)).toBeInTheDocument();
    expect(screen.getByText(/noch keinen Vault/)).toBeInTheDocument();
  });

  it("Protokoll: neueste zuerst, filterbar, Text nie als HTML", async () => {
    await open({
      audit: [
        { ts: 1000, event: "action_allow", detail: "timer.local: 10 Minuten" },
        { ts: 2000, event: "action_deny", detail: "<img src=x onerror=alert(1)>" },
      ],
    });
    const items = document.querySelectorAll(".audit li");
    expect(items[0].textContent).toContain("action_deny");
    expect(document.querySelector(".audit img")).toBeNull();
    fireEvent.change(screen.getByLabelText("Protokoll filtern"), { target: { value: "timer" } });
    expect(document.querySelectorAll(".audit li")).toHaveLength(1);
  });

  it("kein Bildschirm kann etwas ändern: nur Anzeige, der Notaus bleibt in der Kopfzeile", async () => {
    await open({});
    expect(screen.getByRole("button", { name: "NOTAUS" })).toBeInTheDocument();
    expect(document.querySelector(".security button")).toBeNull();
  });
});
