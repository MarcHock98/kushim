import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { remaining } from "./components/stage/Live";
import { ViewCard } from "./components/stage/ViewCard";
import { ApiClient } from "./lib/api";
import { STATE_VIEW } from "./lib/avatarState";
import { MockSocket } from "./lib/mock";
import { parseItem, type Block, type View } from "./lib/stage";

// Live-Arbeit auf der Bühne (Plan docs/ui-p3-plan.md): Fortschritt, Aufgaben, Zeitplan, Mail, Entwurf, Countdown.

const TOKEN = "t".repeat(43);
afterEach(() => { cleanup(); vi.useRealTimers(); });

const view = (art: View["art"], bausteine: Block[]): View => ({ seq: 1, id: "v1", art, titel: "Titel", stand: "", bausteine });
const card = (v: View) => render(<ViewCard view={v} sys={null} sysNo={false} onClose={() => undefined} />);
const onlyClose = () => expect(within(document.querySelector(".view-card") as HTMLElement).getAllByRole("button").map((b) => b.getAttribute("aria-label")))
  .toEqual(["Schließen (Esc)"]);

describe("Fortschritt und Aufgaben", () => {
  it("jeder Schritt nennt seinen Zustand als Wort, der laufende ist markiert, der Zähler stimmt", () => {
    card(view("auftrag", [{ typ: "fortschritt", hinweis: "Dauert noch etwa zwei Minuten.", schritte: [
      { text: "Tests lesen", zustand: "fertig" }, { text: "Fehler beheben", zustand: "laeuft" },
      { text: "Alte Datei löschen", zustand: "fehler" }, { text: "Committen", zustand: "offen" }] }]));
    expect(screen.getByText("1 von 4 fertig, 1 mit Fehler")).toBeInTheDocument();
    const items = screen.getAllByRole("listitem");
    expect(items.map((li) => li.querySelector(".p-state")!.textContent)).toEqual(["fertig", "läuft", "Fehler", "offen"]);
    expect(items[1]).toHaveAttribute("aria-current", "step");
    expect(items.filter((li) => li.hasAttribute("aria-current"))).toHaveLength(1);
    expect(screen.getByText("Dauert noch etwa zwei Minuten.")).toBeInTheDocument();
    onlyClose();
  });

  it("Aufgaben zeigen Haken und Wort, sind aber nicht anklickbar", () => {
    card(view("antwort", [{ typ: "aufgaben", punkte: [{ text: "Milch", erledigt: true }, { text: "<b>Brot</b>", erledigt: false }] }]));
    expect(screen.getByText("1 von 2 erledigt")).toBeInTheDocument();
    expect(screen.getByText("<b>Brot</b>")).toBeInTheDocument();
    expect(document.querySelector(".view-card b, .view-card input")).toBeNull();
    expect(screen.getAllByRole("listitem").map((li) => li.querySelector(".p-state")!.textContent)).toEqual(["erledigt", "offen"]);
    onlyClose();
  });
});

describe("Zeitplan", () => {
  it("nennt Zeiten und Ort; nur Termine, die sich überschneiden, tragen den Hinweis in Worten", () => {
    card(view("auftrag", [{ typ: "zeitplan", tag: "Dienstag, 17. November", termine: [
      { von: "09:00", bis: "10:00", titel: "Standup", ort: "Büro" },
      { von: "09:30", bis: "11:00", titel: "Zahnarzt", ort: "" },
      { von: "11:00", bis: "12:00", titel: "Mittag", ort: "" }] }]));
    expect(screen.getByText("Dienstag, 17. November")).toBeInTheDocument();
    expect(screen.getByText("09:00 bis 10:00")).toBeInTheDocument();
    expect(screen.getByText(/Büro/)).toBeInTheDocument();
    const items = screen.getAllByRole("listitem");
    expect(items.map((li) => /überschneidet sich/.test(li.textContent ?? ""))).toEqual([true, true, false]);   // 11:00 bis 11:00 berührt nur
    const blocks = [...document.querySelectorAll<HTMLElement>(".s-block")];
    expect(blocks.map((b) => b.style.left)).toEqual(["0%", "16.6667%", "66.6667%"].map((v) => expect.stringMatching(new RegExp(`^${v.slice(0, 4)}`))));
  });

  it("ein einzelner Termin zeichnet ohne NaN", () => {
    card(view("auftrag", [{ typ: "zeitplan", tag: "", termine: [{ von: "08:00", bis: "08:30", titel: "Kaffee", ort: "" }] }]));
    expect(document.querySelector(".v-schedule")!.outerHTML).not.toMatch(/NaN|Infinity/);
    expect(screen.queryByText(/überschneidet/)).toBeNull();
  });
});

describe("Mail und Entwurf", () => {
  const body = ["Hallo,", "klick hier: https://boese.example/login <img src=x onerror=alert(1)>"];

  it("eine Mail ist fremder Inhalt: fester Hinweis, nur Text, kein Link, kein Bild, nichts zum Anklicken", () => {
    card(view("mail", [{ typ: "mail", von: "Anna <anna@example.org>", an: "", betreff: "Termin", datum: "12.11.2026",
      zusammenfassung: "Anna fragt nach Dienstag.", absaetze: body }]));
    const mail = screen.getByRole("region", { name: "Mail" });
    expect(within(mail).getByText("Fremder Inhalt, nur Text")).toBeInTheDocument();
    expect(within(mail).getByText("Anna <anna@example.org>")).toBeInTheDocument();
    expect(within(mail).getByText("Anna fragt nach Dienstag.")).toBeInTheDocument();
    expect(within(mail).getByText(/https:\/\/boese\.example\/login/)).toBeInTheDocument();
    expect(within(mail).queryByText("An")).toBeNull();                                // leere Kopfzeile fällt weg
    expect(mail.querySelector("a, img, [href], button, input, form")).toBeNull();
    onlyClose();
  });

  it("ein Entwurf zeigt den exakten Text und sagt, dass nichts gesendet ist; es gibt keinen Senden-Knopf", () => {
    card(view("mail", [{ typ: "mail-entwurf", an: "anna@example.org", cc: "", betreff: "Re: Termin", absaetze: ["Ja, Dienstag passt.", "Gruß"] }]));
    const draft = screen.getByRole("region", { name: "Mail-Entwurf" });
    expect(within(draft).getByText("Entwurf, noch nicht gesendet. Gesendet wird nur in Claude Code mit deiner Freigabe.")).toBeInTheDocument();
    expect(within(draft).getByText("anna@example.org")).toBeInTheDocument();
    expect(within(draft).getByText("Ja, Dienstag passt.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /send/i })).toBeNull();
    onlyClose();
  });

  it("die festen Hinweise stehen nur bei Mail-Bausteinen", () => {
    card(view("auftrag", [{ typ: "aufgaben", punkte: [{ text: "x", erledigt: false }] }]));
    expect(screen.queryByText(/Fremder Inhalt|noch nicht gesendet/)).toBeNull();
  });
});

describe("Countdown", () => {
  it("Restzeit als Text: Minuten, Stunden, abgelaufen, ungültig, höchstens ein Tag", () => {
    const now = Date.parse("2026-11-12T12:00:00+01:00");
    expect(remaining("2026-11-12T12:09:59+01:00", now)).toBe("09:59");
    expect(remaining("2026-11-12T13:01:05+01:00", now)).toBe("1:01:05");
    expect(remaining("2026-11-12T12:00:00+01:00", now)).toBe("abgelaufen");
    expect(remaining("2026-11-12T11:00:00+01:00", now)).toBe("abgelaufen");
    expect(remaining("morgen", now)).toBeNull();
    expect(remaining("2026-11-13T12:00:01+01:00", now)).toBeNull();                 // mehr als 24 Stunden: keine Anzeige
    expect(remaining("2026-11-10T12:00:00+01:00", now)).toBeNull();
    expect(remaining("2026-11-13T12:00:00+01:00", now)).toBe("24:00:00");
  });

  it("zählt herunter und endet bei „abgelaufen“; er ist nur Anzeige, ohne Ton", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-12T12:00:00+01:00"));
    card(view("auftrag", [{ typ: "countdown", titel: "Tee", ende: "2026-11-12T12:00:03+01:00" }]));
    const timer = screen.getByRole("timer", { name: "Tee" });
    expect(within(timer).getByText("00:03")).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(2000); });
    expect(within(timer).getByText("00:01")).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(2000); });
    expect(within(timer).getByText("abgelaufen")).toBeInTheDocument();
    expect(within(timer).getByText("Nur Anzeige, ohne Ton")).toBeInTheDocument();
    expect(document.querySelector("audio, video")).toBeNull();
  });

  it("eine ungültige Zeit zeigt „Zeit unbekannt“ statt einer falschen Zahl", () => {
    card(view("auftrag", [{ typ: "countdown", titel: "Tee", ende: "kaputt" }]));
    expect(screen.getByText("Zeit unbekannt")).toBeInTheDocument();
  });
});

describe("Bühne mit Auftrag", () => {
  it("kennt die neuen Arten und Bausteine", () => {
    const v = parseItem({ seq: 1, id: "job", art: "auftrag", titel: "T", bausteine: [{ typ: "fortschritt", schritte: [] }, { typ: "mail-entwurf" }, { typ: "skript" }] }) as View;
    expect(v.art).toBe("auftrag");
    expect(v.bausteine.map((b) => b.typ)).toEqual(["fortschritt", "mail-entwurf"]);
    expect((parseItem({ seq: 1, id: "m", art: "mail", titel: "T", bausteine: [] }) as View).art).toBe("mail");
  });

  it("ein Fortschritt wächst unter derselben id, ohne zweiten Reiter", async () => {
    const sock: { current?: MockSocket } = {};
    const loader = async () => ({ client: new ApiClient({ port: 5000, token: TOKEN }, (u) => (sock.current = new MockSocket(u, TOKEN))) });
    render(<App load={loader} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    const step = (zustand: string) => ({ id: "job", art: "auftrag", titel: "Tests grün machen",
      bausteine: [{ typ: "fortschritt", hinweis: "", schritte: [{ text: "Tests lesen", zustand: "fertig" }, { text: "Fehler beheben", zustand }] }] });
    sock.current!.show(step("laeuft"));
    await waitFor(() => screen.getByText("1 von 2 fertig"), { timeout: 3000 });
    expect(screen.getByRole("heading", { name: "Tests grün machen" })).toBeInTheDocument();
    sock.current!.show(step("fertig"));
    await waitFor(() => screen.getByText("2 von 2 fertig"), { timeout: 3000 });
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(document.querySelectorAll("article.view-card")).toHaveLength(1);
  });
});
