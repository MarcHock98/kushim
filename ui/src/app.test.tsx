import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { Avatar } from "./components/Avatar";
import { ApiClient } from "./lib/api";
import { resolveState, STATE_VIEW } from "./lib/avatarState";
import { MockSocket } from "./lib/mock";

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

describe("Freigabe-Leiste", () => {
  const P = { kind: "research", preview: "Suchtext: Höhe des Eiffelturms", digest: "d".repeat(64), expires_in: 125, sends_data_out: true };

  async function asking() {
    const sock: { current?: MockSocket } = {};
    render(<App load={loaderWith(sock)} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    sock.current!.pending = { ...P };
    sock.current!.voice = { active: true, state: "asking", level: 0 };
    await waitFor(() => expect(screen.getByRole("alertdialog")).toBeInTheDocument(), { timeout: 3000 });
    return sock.current!;
  }

  it("zeigt den exakten Text, die Restzeit und den Hinweis auf Daten nach außen; Standardfokus liegt auf Ablehnen", async () => {
    await asking();
    expect(screen.getByText("Suchtext: Höhe des Eiffelturms")).toBeInTheDocument();
    expect(screen.getByText(/Läuft ab in 02:0\d/)).toBeInTheDocument();
    expect(screen.getByText(/Sendet Daten nach außen/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ablehnen" })).toHaveFocus();
    expect(screen.queryByText(/immer/i)).toBeNull();                     // kein "Immer erlauben"
  });

  it("Erlauben sendet Hash und confirm; ohne Klick passiert nichts", async () => {
    const sock = await asking();
    expect(sock.sent.some((m) => (m as { type: string }).type === "approvals.decide")).toBe(false);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Erlauben" })); });
    const sent = sock.sent.find((m) => (m as { type: string }).type === "approvals.decide") as { approve: boolean; digest: string; confirm: boolean };
    expect(sent).toMatchObject({ approve: true, digest: P.digest, confirm: true });
    await waitFor(() => expect(screen.getByText(/Erlaubt/)).toBeInTheDocument());
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it("Ablehnen und Esc lehnen ab und senden kein confirm", async () => {
    const sock = await asking();
    await act(async () => { fireEvent.keyDown(screen.getByRole("alertdialog"), { key: "Escape" }); });
    const sent = sock.sent.find((m) => (m as { type: string }).type === "approvals.decide") as { approve: boolean; confirm?: boolean };
    expect(sent.approve).toBe(false);
    expect(sent.confirm).toBeUndefined();
    await waitFor(() => expect(screen.getByText(/Abgelehnt/)).toBeInTheDocument());
  });

  it("zeigt die Leiste nicht, solange das Backend nicht 'asking' meldet", async () => {
    const sock: { current?: MockSocket } = {};
    render(<App load={loaderWith(sock)} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    sock.current!.pending = { ...P };
    sock.current!.voice = { active: true, state: "thinking", level: 0 };
    await new Promise((r) => setTimeout(r, 600));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });
});

describe("Daumen-Feedback", () => {
  async function withReply() {
    const sock: { current?: MockSocket } = {};
    render(<App load={loaderWith(sock)} />);
    await waitFor(() => screen.getByText(/Noch nichts gesagt/));
    sock.current!.entries = [{ id: 7, heard: "Wie spät?", reply: "Zehn Uhr.", outcome: "spoken" },
      { id: 8, heard: "", reply: "", outcome: "rejected_speaker" }];
    await waitFor(() => screen.getByText("Zehn Uhr."), { timeout: 3000 });
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
    await waitFor(() => screen.getByText(/Noch nichts gesagt/));
    sock.current!.entries = [
      { id: 1, heard: "Wie spät ist es?", reply: "Es ist <b>zehn</b> Uhr.", outcome: "spoken" },
      { id: 2, heard: "", reply: "", outcome: "rejected_speaker" },
    ];
    await waitFor(() => screen.getByText("Wie spät ist es?"), { timeout: 3000 });
    expect(screen.getByText("Es ist <b>zehn</b> Uhr.")).toBeInTheDocument();      // als Text, nicht als Element
    expect(document.querySelector(".bubble b")).toBeNull();
    expect(screen.getByText("Stimme nicht erkannt. Keine Antwort.")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 1300));
    const gets = sock.current!.sent.filter((m) => (m as { type: string }).type === "transcript.get") as { since: number }[];
    expect(gets[gets.length - 1].since).toBe(2);                                   // ab dem letzten Eintrag
    expect(screen.getAllByText("Wie spät ist es?")).toHaveLength(1);
  });
});

describe("Claude-Bereich", () => {
  async function ready() {
    const sock: { current?: MockSocket } = {};
    const loader = async () => ({
      client: new ApiClient({ port: 5000, token: TOKEN }, (u) => {
        sock.current = new MockSocket(u, TOKEN);
        sock.current.folders = ["kushim"];
        return sock.current;
      }),
    });
    render(<App load={loader} />);
    await waitFor(() => screen.getByLabelText("Auftrag"));
    return sock;
  }

  it("zeigt erst die exakte Vorschau; gestartet wird nur nach Klick auf Erlauben, mit confirm", async () => {
    const sock = await ready();
    fireEvent.change(screen.getByLabelText("Auftrag"), { target: { value: "Baue den Timer" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Vorschau ansehen" })); });
    await waitFor(() => screen.getByText("Auftrag: «Baue den Timer»"));
    expect(screen.getByRole("button", { name: "Ablehnen" })).toHaveFocus();
    expect(sock.current!.sent.some((m) => (m as { type: string }).type === "claude.approve")).toBe(false);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Erlauben" })); });
    const sent = sock.current!.sent.find((m) => (m as { type: string }).type === "claude.approve") as { confirm: boolean; proposal: string };
    expect(sent).toMatchObject({ confirm: true, proposal: "p1" });
    await waitFor(() => screen.getByText(/Zug 1: arbeitet/), { timeout: 3000 });
    expect(screen.getByRole("button", { name: "Stoppen" })).toBeInTheDocument();
  });

  it("Ablehnen sendet claude.deny und keinen Start", async () => {
    const sock = await ready();
    fireEvent.change(screen.getByLabelText("Auftrag"), { target: { value: "Etwas" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Vorschau ansehen" })); });
    await waitFor(() => screen.getByRole("button", { name: "Ablehnen" }));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Ablehnen" })); });
    const types = sock.current!.sent.map((m) => (m as { type: string }).type);
    expect(types).toContain("claude.deny");
    expect(types).not.toContain("claude.approve");
    await waitFor(() => screen.getByText(/Abgelehnt/));
  });

  it("zeigt den Grund, wenn das Backend die Vorschau verweigert (z. B. IBAN), ohne Freigabe-Leiste", async () => {
    await ready();
    fireEvent.change(screen.getByLabelText("Auftrag"), { target: { value: "Zahle auf IBAN ein" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Vorschau ansehen" })); });
    await waitFor(() => screen.getByText("Enthält eine IBAN."));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("ohne freigegebenen Ordner steht der Hinweis, kein Formular", async () => {
    render(<App load={loaderWith({})} />);
    await waitFor(() => screen.getByText(/kein Ordner freigegeben/));
    expect(screen.queryByLabelText("Auftrag")).toBeNull();
  });
});

describe("Claude: Rückfragen und Erlaubnisse", () => {
  async function waiting() {
    const sock: { current?: MockSocket } = {};
    const loader = async () => ({
      client: new ApiClient({ port: 5000, token: TOKEN }, (u) => {
        sock.current = new MockSocket(u, TOKEN);
        sock.current.folders = ["kushim"];
        sock.current.session = { id: "s", folder: "kushim", branch: "b", turn: 2, status: "waiting", cost_usd: 0, seconds: 5, error: "",
          offers: ["Bash(pytest*)"] };
        return sock.current;
      }),
    });
    render(<App load={loader} />);
    await waitFor(() => screen.getByLabelText("Antwort an Claude"));
    return sock;
  }

  it("zeigt Erlaubnisse als nicht vorausgewählte Kästchen und sendet nur die angehakten", async () => {
    const sock = await waiting();
    const box = screen.getByRole("checkbox") as HTMLInputElement;
    expect(box.checked).toBe(false);                                           // nichts vorausgefüllt
    fireEvent.change(screen.getByLabelText("Antwort an Claude"), { target: { value: "Ja, mach weiter" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Vorschau ansehen" })); });
    await waitFor(() => screen.getByRole("alertdialog"));
    const first = sock.current!.sent.find((m) => (m as { type: string }).type === "claude.answer") as { allow: string[] };
    expect(first.allow).toEqual([]);                                           // ohne Haken keine Erlaubnis
    expect(screen.getByText("Antwort an Claude", { selector: "h2" })).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Ablehnen" })); });
    await waitFor(() => screen.getByLabelText("Antwort an Claude"));
    fireEvent.click(screen.getByRole("checkbox"));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Vorschau ansehen" })); });
    await waitFor(() => screen.getByText(/Erlaubt: Bash\(pytest\*\)/));
    const answers = sock.current!.sent.filter((m) => (m as { type: string }).type === "claude.answer") as { allow: string[] }[];
    expect(answers[answers.length - 1].allow).toEqual(["Bash(pytest*)"]);
    expect(sock.current!.sent.some((m) => (m as { type: string }).type === "claude.approve")).toBe(false);   // erst nach Klick
  });

  it("zeigt im Wartezustand kein Startformular", async () => {
    await waiting();
    expect(screen.queryByLabelText("Auftrag")).toBeNull();
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
