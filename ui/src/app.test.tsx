import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { Avatar } from "./components/Avatar";
import { ApiClient } from "./lib/api";
import { resolveState, STATE_VIEW } from "./lib/avatarState";
import { MockSocket } from "./lib/mock";

/** Verlauf und Claude-Bereich stehen in der Übersicht (die Startseite zeigt im Gespräch nur den Kern). */
async function toOverview() {
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Übersicht" })); });
}


const TOKEN = "t".repeat(43);
afterEach(cleanup);

function loaderWith(sock: { current?: MockSocket }, opts: { fail?: boolean; token?: string } = {}) {
  return async () => ({
    client: new ApiClient({ port: 5000, token: opts.token ?? TOKEN }, (u) => {
      sock.current = new MockSocket(u, TOKEN, opts.fail);
      return sock.current;
    }),
  });
}

describe("resolveState", () => {
  it("offline und halted haben Vorrang", () => {
    expect(resolveState({ connected: false, killActive: true, backendState: "speaking" })).toBe("offline");
    expect(resolveState({ connected: true, killActive: true, backendState: "alarm" })).toBe("halted");
    expect(resolveState({ connected: true, killActive: false, backendState: "alarm" })).toBe("alarm");
    expect(resolveState({ connected: true, killActive: false })).toBe("idle");
  });
  it("jeder Zustand hat eine Textzeile, alarm und halted melden assertive", () => {
    for (const s of Object.values(STATE_VIEW)) expect(s.label.length).toBeGreaterThan(3);
    expect(STATE_VIEW.alarm.live).toBe("assertive");
    expect(STATE_VIEW.halted.live).toBe("assertive");
  });
});

describe("ApiClient", () => {
  it("verbindet nur mit 127.0.0.1 und sendet das Token mit", async () => {
    const sock: { current?: MockSocket } = {};
    const c = new ApiClient({ port: 5000, token: TOKEN }, (u) => (sock.current = new MockSocket(u)));
    await c.connect();
    expect(sock.current!.url).toBe("ws://127.0.0.1:5000");
    expect((await c.call("safety.status")).ok).toBe(true);
    expect((sock.current!.sent[0] as { token: string }).token).toBe(TOKEN);
  });
  it("lehnt ungültige Ports ab", () => {
    for (const port of [0, -1, 70000, 1.5, NaN]) expect(() => new ApiClient({ port, token: TOKEN })).toThrow();
  });
  it("falsches Token: neutrale Ablehnung", async () => {
    const c = new ApiClient({ port: 5000, token: "x".repeat(43) }, (u) => new MockSocket(u));
    await c.connect();
    expect(await c.call("safety.status")).toEqual({ ok: false, error: "unauthorized" });
  });
});

describe("App", () => {
  it("zeigt Bereit, wenn das Backend antwortet", async () => {
    render(<App load={loaderWith({})} />);
    await waitFor(() => expect(screen.getAllByText(STATE_VIEW.idle.label).length).toBeGreaterThan(0));
    expect(screen.getByRole("button", { name: "NOTAUS" })).toBeInTheDocument();
  });

  it("zeigt Offline mit Erneut-versuchen, wenn das Backend fehlt; Notaus bleibt sichtbar", async () => {
    render(<App load={loaderWith({}, { fail: true })} />);
    await waitFor(() => expect(screen.getAllByText(STATE_VIEW.offline.label).length).toBeGreaterThan(0));
    expect(screen.getByRole("button", { name: "Erneut versuchen" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "NOTAUS" })).toBeInTheDocument();
  });

  it("Notaus löst mit einem Klick aus (ohne Rückfrage) und Aufheben braucht eine Bestätigung", async () => {
    const sock: { current?: MockSocket } = {};
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<App load={loaderWith(sock)} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "NOTAUS" })); });
    await waitFor(() => expect(screen.getAllByText(STATE_VIEW.halted.label).length).toBeGreaterThan(0));
    expect(confirm).not.toHaveBeenCalled();
    expect(sock.current!.kill).toBe(true);

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Notaus aufheben" })); });
    expect(confirm).toHaveBeenCalled();
    expect(sock.current!.kill).toBe(true);              // abgelehnt: bleibt aktiv

    confirm.mockReturnValue(true);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Notaus aufheben" })); });
    await waitFor(() => expect(sock.current!.kill).toBe(false));
    expect(sock.current!.sent.some((m) => (m as { type: string; confirm?: boolean }).type === "safety.resume" &&
      (m as { confirm?: boolean }).confirm === true)).toBe(true);
  });

  it("Strg+Umschalt+K löst den Notaus aus", async () => {
    const sock: { current?: MockSocket } = {};
    render(<App load={loaderWith(sock)} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    await act(async () => { fireEvent.keyDown(window, { key: "K", ctrlKey: true, shiftKey: true }); });
    await waitFor(() => expect(sock.current!.kill).toBe(true));
  });

  it("ohne Tauri und ohne ?mock gibt es keine Zugangsdaten und kein Backend wird erfunden", async () => {
    render(<App />);
    await waitFor(() => expect(screen.getAllByText(STATE_VIEW.offline.label).length).toBeGreaterThan(0));
  });
});

describe("Avatar", () => {
  it("hat role=img und aria-label mit der Textzeile", () => {
    render(<Avatar state="listening" />);
    expect(screen.getByRole("img")).toHaveAttribute("aria-label", STATE_VIEW.listening.label);
  });

  it("startet bei prefers-reduced-motion keine Animationsschleife", () => {
    const raf = vi.spyOn(window, "requestAnimationFrame");
    const mm = vi.spyOn(window, "matchMedia").mockReturnValue({ matches: true } as MediaQueryList);
    render(<Avatar state="thinking" />);
    expect(raf).not.toHaveBeenCalled();
    mm.mockRestore();
  });
});

describe("Sprach-Zustand vom Backend", () => {
  it("zeigt Zustand und Pegel der Sprach-Pipeline, sobald der Dienst aktiv ist", async () => {
    const sock: { current?: MockSocket } = {};
    render(<App load={loaderWith(sock)} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    expect(screen.getByText(/Der Sprachdienst läuft nicht/)).toBeInTheDocument();   // ehrlich: kein Dienst, kein Zustand
    sock.current!.voice = { active: true, state: "listening", level: 0.5 };
    await waitFor(() => expect(screen.getAllByText(STATE_VIEW.listening.label).length).toBeGreaterThan(0), { timeout: 2000 });
    expect(screen.queryByText(/Der Sprachdienst läuft nicht/)).toBeNull();
  });

  it("Notaus hat Vorrang vor dem gemeldeten Sprachzustand; unbekannte Zustände werden ignoriert", async () => {
    const sock: { current?: MockSocket } = {};
    render(<App load={loaderWith(sock)} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    sock.current!.voice = { active: true, state: "root", level: 0.5 };
    await new Promise((r) => setTimeout(r, 500));
    expect(screen.queryByText(STATE_VIEW.listening.label)).toBeNull();
    sock.current!.voice = { active: true, state: "speaking", level: 0.5 };
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "NOTAUS" })); });
    await waitFor(() => expect(screen.getAllByText(STATE_VIEW.halted.label).length).toBeGreaterThan(0));
    expect(screen.queryByText(STATE_VIEW.speaking.label)).toBeNull();
  });
});

describe("Freigabe-Leiste (Claude Code)", () => {
  const P = { request_id: "abcde", tool_name: "Bash", description: "Tests laufen lassen", input_preview: '{ "command": "npm test" }',
    digest: "d".repeat(64), summary: "Claude möchte den Befehl npm test ausführen." };
  const decides = (s: MockSocket) => s.sent.filter((m) => (m as { type: string }).type === "approvals.decide") as
    { request_id: string; approve: boolean; digest: string; confirm?: boolean }[];

  async function asking(extra: typeof P[] = []) {
    const sock: { current?: MockSocket } = {};
    render(<App load={loaderWith(sock)} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    sock.current!.pending = [{ ...P }, ...extra];
    await waitFor(() => expect(screen.getByRole("alertdialog")).toBeInTheDocument(), { timeout: 3000 });
    await armed();
    return sock.current!;
  }

  async function armed() {                                                  // Knöpfe erst nach ARM_MS freigeschaltet
    await waitFor(() => expect(screen.getByRole("button", { name: "Ablehnen" })).toBeEnabled(), { timeout: 2000 });
  }

  it("nach einem Wechsel der Anfrage sind die Knöpfe kurz gesperrt: ein Klick trifft nie die nachrückende", async () => {
    const sock: { current?: MockSocket } = {};
    render(<App load={loaderWith(sock)} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    sock.current!.pending = [{ ...P }];
    // Die Sperre dauert nur ARM_MS: im selben Schritt prüfen, in dem die Leiste erscheint (sonst läuft sie unter Last ab).
    await waitFor(() => {
      expect(screen.getByRole("alertdialog")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Erlauben" })).toBeDisabled();
      fireEvent.click(screen.getByRole("button", { name: "Erlauben" }));
    }, { timeout: 3000 });
    await act(async () => { fireEvent.keyDown(screen.getByRole("alertdialog"), { key: "Escape" }); });
    expect(decides(sock.current!)).toHaveLength(0);
    await armed();
    sock.current!.pending = [{ ...P, request_id: "neu00", input_preview: "andere", digest: "f".repeat(64) }];   // erledigt, die nächste rückt nach
    await waitFor(() => {
      expect(screen.getByRole("alertdialog").textContent).toContain("Eingabe: andere");
      expect(screen.getByRole("button", { name: "Erlauben" })).toBeDisabled();
      fireEvent.click(screen.getByRole("button", { name: "Erlauben" }));
    }, { timeout: 3000 });
    expect(decides(sock.current!)).toHaveLength(0);
  });

  it("zeigt den exakten Text von Claude; Standardfokus liegt auf Ablehnen; kein 'Immer erlauben'", async () => {
    await asking();
    const dlg = screen.getByRole("alertdialog");
    expect(dlg.textContent).toContain("Werkzeug: Bash");
    expect(dlg.textContent).toContain("Beschreibung: Tests laufen lassen");
    expect(dlg.textContent).toContain('Eingabe: { "command": "npm test" }');
    expect(screen.getByText("Claude möchte den Befehl npm test ausführen.")).toBeInTheDocument();
    // Fokus setzt ein Effekt nach dem Freischalten: auf den Zustand warten, nicht auf den Takt.
    await waitFor(() => expect(screen.getByRole("button", { name: "Ablehnen" })).toHaveFocus());
    expect(screen.queryByText(/immer/i)).toBeNull();
  });

  it("Erlauben sendet Anfrage-Nummer, Hash und confirm; ohne Klick passiert nichts", async () => {
    const sock = await asking();
    await new Promise((r) => setTimeout(r, 1300));                       // mehrere Abfragen später noch nichts entschieden
    expect(decides(sock)).toHaveLength(0);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Erlauben" })); });
    expect(decides(sock)).toHaveLength(1);
    expect(decides(sock)[0]).toMatchObject({ request_id: "abcde", approve: true, digest: P.digest, confirm: true });
    await waitFor(() => expect(screen.getByText(/Erlaubt/)).toBeInTheDocument());
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it("gekürzter Text: kein Erlauben-Knopf, nur Ablehnen und der Hinweis aufs Terminal", async () => {
    const sock: { current?: MockSocket } = {};
    render(<App load={loaderWith(sock)} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    sock.current!.pending = [{ ...P, truncated: true }];
    await waitFor(() => expect(screen.getByRole("alertdialog")).toBeInTheDocument(), { timeout: 3000 });
    expect(screen.queryByRole("button", { name: "Erlauben" })).toBeNull();
    expect(screen.getByText(/Erlauben bitte im Terminal/)).toBeInTheDocument();
    await armed();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Ablehnen" })); });
    expect(decides(sock.current!)[0]).toMatchObject({ request_id: "abcde", approve: false });
  });

  it("Esc lehnt ab und sendet kein confirm", async () => {
    const sock = await asking();
    await act(async () => { fireEvent.keyDown(screen.getByRole("alertdialog"), { key: "Escape" }); });
    expect(decides(sock)[0]).toMatchObject({ request_id: "abcde", approve: false });
    expect(decides(sock)[0].confirm).toBeUndefined();
    await waitFor(() => expect(screen.getByText(/Abgelehnt/)).toBeInTheDocument());
  });

  it("zeigt mehrere Anfragen nacheinander, die erste zuerst", async () => {
    const sock = await asking([{ ...P, request_id: "zzzzz", input_preview: "zweite", digest: "e".repeat(64) }]);
    expect(screen.getByText(/Noch 1 weitere/)).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Ablehnen" })); });
    await waitFor(() => expect(screen.getByRole("alertdialog").textContent).toContain("Eingabe: zweite"));
    expect(decides(sock)).toHaveLength(1);
  });

  it("ändert sich die Anfrage, meldet das Backend 'stale' und die UI sagt es", async () => {
    const sock = await asking();
    sock.pending = [{ ...P, digest: "f".repeat(64) }];                   // zwischen Anzeige und Klick ersetzt
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Erlauben" })); });
    await waitFor(() => expect(screen.getByText(/hat sich geändert/)).toBeInTheDocument());
  });

  it("bei Notaus keine Leiste und keine Entscheidung", async () => {
    const sock: { current?: MockSocket } = {};
    render(<App load={loaderWith(sock)} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "NOTAUS" })); });
    sock.current!.pending = [{ ...P }];
    await new Promise((r) => setTimeout(r, 1300));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(decides(sock.current!)).toHaveLength(0);
  });

  it("ohne offene Anfrage keine Leiste", async () => {
    const sock: { current?: MockSocket } = {};
    render(<App load={loaderWith(sock)} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    await new Promise((r) => setTimeout(r, 1300));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });
});

describe("Daumen-Feedback", () => {
  async function withReply() {
    const sock: { current?: MockSocket } = {};
    render(<App load={loaderWith(sock)} />);
    await toOverview();
    await waitFor(() => screen.getByText(/Noch nichts gesagt/));
    sock.current!.entries = [{ id: 7, heard: "Wie spät?", reply: "Zehn Uhr.", outcome: "spoken" },
      { id: 8, heard: "", reply: "", outcome: "rejected_speaker" }];
    await waitFor(() => within(screen.getByRole("list", { name: "Verlauf" })).getByText("Zehn Uhr."), { timeout: 3000 });
    return sock.current!;
  }

  it("Daumen nur bei Antworten mit Text; Klick sendet die Bewertung genau einmal und sperrt die Knöpfe", async () => {
    const sock = await withReply();
    expect(screen.getAllByRole("button", { name: "Hilfreich" })).toHaveLength(1);        // nicht bei der abgelehnten Stimme
    expect(sock.sent.some((m) => (m as { type: string }).type === "feedback.add")).toBe(false);   // ohne Klick nichts
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Hilfreich" })); });
    await waitFor(() => expect(screen.getByRole("button", { name: "Hilfreich" })).toBeDisabled());
    expect(sock.ratings).toEqual([{ entry: 7, rating: 1 }]);
    expect(screen.getByRole("button", { name: "Hilfreich" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Nicht hilfreich" })).toBeDisabled();
  });

  it("Daumen runter sendet -1", async () => {
    const sock = await withReply();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Nicht hilfreich" })); });
    await waitFor(() => expect(sock.ratings).toEqual([{ entry: 7, rating: -1 }]));
  });
});

describe("Live-Transkript", () => {
  it("zeigt neue Einträge als reinen Text (nie HTML) und holt jeden nur einmal", async () => {
    const sock: { current?: MockSocket } = {};
    render(<App load={loaderWith(sock)} />);
    await toOverview();
    await waitFor(() => screen.getByText(/Noch nichts gesagt/));
    sock.current!.entries = [
      { id: 1, heard: "Wie spät ist es?", reply: "Es ist <b>zehn</b> Uhr.", outcome: "spoken" },
      { id: 2, heard: "", reply: "", outcome: "rejected_speaker" },
    ];
    const log = () => within(screen.getByRole("list", { name: "Verlauf" }));
    await waitFor(() => log().getByText("Wie spät ist es?"), { timeout: 3000 });
    expect(log().getByText("Es ist <b>zehn</b> Uhr.")).toBeInTheDocument();      // als Text, nicht als Element
    expect(document.querySelector(".bubble b")).toBeNull();
    expect(document.querySelector(".stage-card b")).toBeNull();                    // auch die Karte auf der Bühne nur Text
    expect(screen.getByText("Stimme nicht erkannt. Keine Antwort.")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 1300));
    const gets = sock.current!.sent.filter((m) => (m as { type: string }).type === "transcript.get") as { since: number }[];
    expect(gets[gets.length - 1].since).toBe(2);                                   // ab dem letzten Eintrag
    expect(log().getAllByText("Wie spät ist es?")).toHaveLength(1);
  });
});

describe("Dienst mit weniger Fähigkeiten (kushim serve ohne Sprachdienst)", () => {
  it("fragt einen unbekannten Typ nur einmal ab und bleibt verbunden", async () => {
    const sock: { current?: MockSocket } = {};
    const client = new ApiClient({ port: 5000, token: TOKEN }, (u) => (sock.current = new MockSocket(u, TOKEN)));
    await client.connect();
    expect(await client.call("gibt-es-nicht")).toEqual({ ok: false, error: "unknown_type" });
    expect(await client.call("gibt-es-nicht")).toEqual({ ok: false, error: "unknown_type" });
    expect(sock.current!.sent.filter((m) => (m as { type: string }).type === "gibt-es-nicht")).toHaveLength(1);
    expect((await client.call("safety.status")).ok).toBe(true);                   // andere Typen funktionieren weiter
  });
});
