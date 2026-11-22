import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { clock } from "./components/stage/Learn";
import { ViewCard } from "./components/stage/ViewCard";
import { ApiClient } from "./lib/api";
import { STATE_VIEW } from "./lib/avatarState";
import { DEMO_VIEWS, MockSocket } from "./lib/mock";
import { parseItem, type Block, type View } from "./lib/stage";

// P6a (docs/ui-p6-plan.md): Vergleich, Zeitstrahl, Gegenüberstellung, Lernkarten, Quiz, Anleitung.
// Kernregel: Ein Klick ändert nur die Anzeige im Fenster und sendet nie etwas.

const TOKEN = "t".repeat(43);
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

const view = (art: View["art"], bausteine: Block[], extra: Partial<View> = {}): View =>
  ({ seq: 1, id: "v1", art, titel: "Titel", stand: "", bausteine, ...extra });
const card = (v: View) => render(<ViewCard view={v} sys={null} sysNo={false} onClose={() => undefined} />);
const btn = (name: string | RegExp) => screen.getByRole("button", { name });
const click = (name: string | RegExp) => fireEvent.click(btn(name));

const CARDS: Block = { typ: "lernkarten", karten: [
  { frage: "Hauptstadt von Portugal?", antwort: "Lissabon" },
  { frage: "Hauptstadt von Kanada?", antwort: "Ottawa" },
  { frage: "Hauptstadt von Australien?", antwort: "Canberra" }] };
const QUIZ: Block = { typ: "quiz", fragen: [
  { frage: "Hauptstadt der Schweiz?", optionen: ["Zürich", "Bern", "Genf"], richtig: 1, erklaerung: "Bern ist Bundesstadt." },
  { frage: "Fluss durch Wien?", optionen: ["Donau", "Rhein"], richtig: 0, erklaerung: "" }] };
const GUIDE = (aktuell = 0): Block => ({ typ: "anleitung", aktuell, schritte: [
  { titel: "Zutaten", text: "Mehl, Eier, Milch.", sekunden: 0 },
  { titel: "Rühren", text: "Glatt rühren.", sekunden: 0 },
  { titel: "Ruhen", text: "Teig ruhen lassen.", sekunden: 3 },
  { titel: "Backen", text: "Je Seite eine Minute.", sekunden: 0 }] });

describe("Vergleich", () => {
  const b: Block = { typ: "vergleich", optionen: ["Bahn", "Auto"], kriterien: [
    { name: "Fahrzeit", werte: ["3:40 h", "4:50 h"] }, { name: "Kosten", werte: [59.9, 92] }],
    vorteile: [["schnell"], ["flexibel"]], nachteile: [["Verspätung"], []], fazit: "Bahn ist bequemer." };

  it("Tabelle mit einer Spalte je Option, darunter je Option „dafür“ und „dagegen“ als Wörter, Fazit", () => {
    card(view("antwort", [b]));
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Kriterium", "Bahn", "Auto"]);
    expect(within(table).getAllByRole("rowheader").map((h) => h.textContent)).toEqual(["Fahrzeit", "Kosten"]);
    expect(within(table).getByText("59,9")).toBeInTheDocument();                         // Dezimalkomma
    const bahn = screen.getByRole("region", { name: "Bahn" }), auto = screen.getByRole("region", { name: "Auto" });
    expect(within(bahn).getByText("dafür")).toBeInTheDocument();
    expect(within(bahn).getByText("dagegen")).toBeInTheDocument();
    expect(within(bahn).getByText("Verspätung")).toBeInTheDocument();
    expect(within(auto).getByText("dafür")).toBeInTheDocument();
    expect(within(auto).queryByText("dagegen")).toBeNull();                               // leere Liste: keine Überschrift
    expect(screen.getByText("Bahn ist bequemer.")).toBeInTheDocument();
  });

  it("leere Vor- und Nachteile (wie vom Backend aufgefüllt) und leeres Fazit zeigen nichts davon", () => {
    card(view("antwort", [{ ...b, vorteile: [[], []], nachteile: [[], []], fazit: "" } as Block]));
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.queryByText("dafür")).toBeNull();
    expect(screen.queryByText("dagegen")).toBeNull();
    expect(screen.queryByText("Fazit")).toBeNull();
    expect(document.querySelector(".c-options, .c-verdict")).toBeNull();
  });

  it("ein fehlender Wert heißt „unbekannt“ statt einer leeren Zelle", () => {
    card(view("antwort", [{ ...b, kriterien: [{ name: "Komfort", werte: ["gut", ""] }] } as Block]));
    expect(screen.getByText("unbekannt")).toBeInTheDocument();
  });
});

describe("Zeitstrahl", () => {
  it("behält die Reihenfolge wie geschickt, Zeit links, Titel und Text rechts; leere Texte fallen weg", () => {
    card(view("recherche", [{ typ: "zeitstrahl", einheit: "", ereignisse: [
      { zeit: "1811", titel: "Schnellpresse", text: "Dampfbetrieben." },
      { zeit: "um 1450", titel: "Gutenberg", text: "" },
      { zeit: "März 2020", titel: "Später", text: "Text" }] }]));
    const items = [...document.querySelectorAll(".t-item")];
    expect(items.map((li) => li.querySelector(".t-time")!.textContent)).toEqual(["1811", "um 1450", "März 2020"]);   // nicht sortiert
    expect(items.map((li) => li.querySelector(".t-title")!.textContent)).toEqual(["Schnellpresse", "Gutenberg", "Später"]);
    expect(items[1].querySelector(".t-text")).toBeNull();
    expect(screen.queryByText(/Zeitangaben in/)).toBeNull();
  });

  it("nennt die Einheit, wenn es eine gibt", () => {
    card(view("recherche", [{ typ: "zeitstrahl", einheit: "Jahren", ereignisse: [{ zeit: "1", titel: "A", text: "" }] }]));
    expect(screen.getByText("Zeitangaben in Jahren")).toBeInTheDocument();
  });
});

describe("Gegenüberstellung", () => {
  it("zwei Spalten mit Sprachnamen, dir=\"auto\" an jedem Text (auch rechts-nach-links)", () => {
    card(view("antwort", [{ typ: "gegenueber", sprachen: ["Deutsch", "Arabisch"], paare: [
      { original: "Danke", uebersetzung: "شكرا" }, { original: "Guten Morgen", uebersetzung: "صباح الخير" }] }]));
    expect(screen.getByRole("region", { name: "Übersetzung Deutsch und Arabisch" })).toBeInTheDocument();
    const pairs = document.querySelectorAll(".g-pair");
    expect(pairs).toHaveLength(2);
    const texts = [...document.querySelectorAll(".g-text")];
    expect(texts.map((t) => t.textContent)).toEqual(["Danke", "شكرا", "Guten Morgen", "صباح الخير"]);
    expect(texts.every((t) => t.getAttribute("dir") === "auto")).toBe(true);
    expect([...document.querySelectorAll(".v-pairs .label")].every((t) => t.getAttribute("dir") === "auto")).toBe(true);
  });
});

describe("Lernkarten", () => {
  it("Zähler, Antwort erst nach Klick, „gewusst“/„nochmal“, Zusammenfassung am Ende", () => {
    card(view("lernen", [CARDS]));
    expect(screen.getByText("Karte 1 von 3")).toBeInTheDocument();
    expect(screen.getByText("Hauptstadt von Portugal?")).toBeInTheDocument();
    expect(screen.queryByText("Lissabon")).toBeNull();                                    // Antwort noch verdeckt
    expect(screen.queryByRole("button", { name: "gewusst" })).toBeNull();
    click("Antwort zeigen");
    expect(screen.getByText("Lissabon")).toBeInTheDocument();
    expect(document.activeElement).toBe(document.querySelector(".l-card"));               // Fokus zur Antwort, nicht verloren
    click("gewusst");
    expect(screen.getByText("Karte 2 von 3")).toBeInTheDocument();
    expect(screen.queryByText("Ottawa")).toBeNull();
    click("Antwort zeigen"); click("nochmal");
    click("Antwort zeigen"); click("gewusst");
    expect(screen.getByText("2 von 3 gewusst, 1 nochmal")).toBeInTheDocument();
    expect(within(document.querySelector(".l-summary") as HTMLElement).getByText("Hauptstadt von Kanada?")).toBeInTheDocument();
    click(/Nochmal-Karten üben/);
    expect(screen.getByText(/Karte 1 von 1/)).toBeInTheDocument();
    expect(screen.getByText("Hauptstadt von Kanada?")).toBeInTheDocument();
    click("Antwort zeigen"); click("gewusst");
    expect(screen.getByText("1 von 1 gewusst, 0 nochmal")).toBeInTheDocument();
    click("Alle von vorn");
    expect(screen.getByText("Karte 1 von 3")).toBeInTheDocument();
  });

  it("die Ansicht stiehlt beim Erscheinen keinen Fokus", () => {
    card(view("lernen", [CARDS, QUIZ, GUIDE()]));
    expect(document.activeElement).toBe(document.body);
  });
});

describe("Quiz", () => {
  it("nur eine Auswahl, Rückmeldung in Worten für richtig und falsch, Erklärung, Ergebnis am Ende", () => {
    card(view("lernen", [QUIZ]));
    expect(screen.getByText("Frage 1 von 2")).toBeInTheDocument();
    const group = screen.getByRole("group", { name: "Hauptstadt der Schweiz?" });
    const radios = within(group).getAllByRole("radio");
    expect(radios).toHaveLength(3);
    expect(new Set(radios.map((r) => (r as HTMLInputElement).name)).size).toBe(1);       // eine Gruppe
    fireEvent.click(radios[0]); fireEvent.click(radios[2]);
    expect(radios.filter((r) => (r as HTMLInputElement).checked)).toEqual([radios[2]]);  // nur eine Auswahl
    click("Prüfen");
    expect(screen.getByText("falsch, richtig ist „Bern“")).toBeInTheDocument();
    expect(screen.getByText("Bern ist Bundesstadt.")).toBeInTheDocument();
    expect(screen.getByText("richtige Antwort")).toBeInTheDocument();
    expect(screen.getByText("deine Antwort")).toBeInTheDocument();
    expect(radios.every((r) => (r as HTMLInputElement).disabled)).toBe(true);           // nach dem Prüfen fest
    click("Nächste Frage");
    expect(screen.getByText("Frage 2 von 2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Donau" }));
    click("Prüfen");
    expect(document.querySelector(".q-verdict")!.textContent).toBe("richtig");
    expect(document.querySelector(".q-why")).toBeNull();                                  // leere Erklärung: nichts
    click("Ergebnis zeigen");
    expect(screen.getByText("1 von 2 richtig")).toBeInTheDocument();
    expect([...document.querySelectorAll(".q-review .q-word")].map((w) => w.textContent)).toEqual(["falsch", "richtig"]);
    click("Von vorn");
    expect(screen.getByText("Frage 1 von 2")).toBeInTheDocument();
    expect(screen.getAllByRole("radio").some((r) => (r as HTMLInputElement).checked)).toBe(false);
  });

  it("Prüfen ohne Auswahl sagt in Worten, was fehlt, und wertet nichts", () => {
    card(view("lernen", [QUIZ]));
    click("Prüfen");
    expect(screen.getByRole("alert")).toHaveTextContent("Wähle zuerst eine Antwort.");
    expect(document.querySelector(".q-feedback")).toBeNull();
  });
});

describe("Anleitung", () => {
  const step = () => document.querySelector(".a-title")!.textContent;

  it("Weiter und Zurück mit Grenzen, Zähler, aufklappbare Gesamtliste", () => {
    card(view("lernen", [GUIDE()]));
    expect(screen.getByText("Schritt 1 von 4")).toBeInTheDocument();
    expect(step()).toBe("Zutaten");
    click("Zurück");
    expect(step()).toBe("Zutaten");                                                        // untere Grenze
    expect(btn("Zurück")).toHaveAttribute("aria-disabled", "true");
    click("Weiter"); click("Weiter"); click("Weiter"); click("Weiter");
    expect(step()).toBe("Backen");                                                         // obere Grenze
    expect(screen.getByText(/Schritt 4 von 4/)).toHaveTextContent("letzter Schritt");
    expect(btn("Weiter")).toHaveAttribute("aria-disabled", "true");
    click("Zurück");
    expect(step()).toBe("Ruhen");
    const all = document.querySelector("details.a-all") as HTMLDetailsElement;
    expect(all.open).toBe(false);
    expect(within(all).getAllByRole("listitem")).toHaveLength(4);
    expect(within(all).getAllByRole("listitem")[2]).toHaveAttribute("aria-current", "step");
  });

  it("Pfeiltasten blättern, auch an den Grenzen ohne Fehler", () => {
    card(view("lernen", [GUIDE()]));
    const box = document.querySelector(".a-step") as HTMLElement;
    expect(box.tabIndex).toBe(0);
    fireEvent.keyDown(box, { key: "ArrowLeft" });
    expect(step()).toBe("Zutaten");
    fireEvent.keyDown(box, { key: "ArrowRight" });
    fireEvent.keyDown(box, { key: "ArrowRight" });
    expect(step()).toBe("Ruhen");
    fireEvent.keyDown(btn("Weiter"), { key: "ArrowLeft" });                                // auch vom Knopf aus
    expect(step()).toBe("Rühren");
  });

  it("startet bei `aktuell` (0-basiert) und folgt, wenn Claude dieselbe Ansicht mit neuem `aktuell` schickt", () => {
    const v = view("lernen", [GUIDE(1)], { id: "pf" });
    const r = card(v);
    expect(step()).toBe("Rühren");
    r.rerender(<ViewCard view={{ ...v, seq: 2, bausteine: [GUIDE(3)] }} sys={null} sysNo={false} onClose={() => undefined} />);
    expect(step()).toBe("Backen");
    r.rerender(<ViewCard view={{ ...v, seq: 2, bausteine: [GUIDE(0)] }} sys={null} sysNo={false} onClose={() => undefined} />);
    expect(step()).toBe("Zutaten");                                                        // auch ohne Neuaufbau
    r.rerender(<ViewCard view={{ ...v, seq: 3, bausteine: [GUIDE(99)] }} sys={null} sysNo={false} onClose={() => undefined} />);
    expect(step()).toBe("Backen");                                                         // außerhalb: letzter Schritt
  });

  it("Timer nur bei sekunden > 0: zählt herunter und endet in Worten, ohne Ton", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-22T12:00:00+01:00"));
    card(view("lernen", [GUIDE(0)]));
    expect(screen.queryByRole("button", { name: "Timer starten" })).toBeNull();          // sekunden 0: kein Timer
    expect(screen.queryByRole("timer")).toBeNull();
    click("Weiter"); click("Weiter");
    const timer = screen.getByRole("timer", { name: "Timer für Ruhen" });
    expect(within(timer).getByText("Timer nicht gestartet")).toBeInTheDocument();
    expect(timer.querySelector(".c-rest")!.textContent).toBe("00:03");
    click("Timer starten");
    expect(within(timer).getByText("Timer läuft")).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(2000); });
    expect(timer.querySelector(".c-rest")!.textContent).toBe("00:01");
    act(() => { vi.advanceTimersByTime(2000); });
    expect(timer.querySelector(".c-rest")!.textContent).toBe("abgelaufen");
    expect(within(timer).getByText("Timer abgelaufen")).toBeInTheDocument();
    expect(within(timer).getByText("Nur Anzeige, ohne Ton")).toBeInTheDocument();
    expect(btn("Timer neu starten")).toBeInTheDocument();
    expect(document.querySelector("audio, video")).toBeNull();
    expect(vi.getTimerCount()).toBe(0);                                                    // abgelaufen: kein Takt mehr
    click("Weiter");
    expect(screen.queryByRole("timer")).toBeNull();
  });

  it("Timer abbrechen setzt ihn zurück; ein anderer Schritt hat seinen eigenen Timer", () => {
    vi.useFakeTimers();
    card(view("lernen", [GUIDE(2)]));
    click("Timer starten");
    act(() => { vi.advanceTimersByTime(1000); });
    click("Timer abbrechen");
    expect(screen.getByText("Timer nicht gestartet")).toBeInTheDocument();
    expect(document.querySelector(".c-rest")!.textContent).toBe("00:03");
    expect(clock(65)).toBe("01:05");
    expect(clock(3723)).toBe("1:02:03");
  });
});

describe("Sicherheit der Lern-Bausteine", () => {
  it("Eingaben bleiben Text: <script> und <b> stehen wörtlich da, nichts wird HTML", () => {
    const evil = "<script>alert(1)</script><b>fett</b><img src=x onerror=alert(1)>";
    card(view("lernen", [
      { typ: "lernkarten", karten: [{ frage: evil, antwort: evil }] },
      { typ: "quiz", fragen: [{ frage: evil, optionen: [evil, "b"], richtig: 0, erklaerung: evil }] },
      { typ: "anleitung", aktuell: 0, schritte: [{ titel: evil, text: evil, sekunden: 0 }] },
      { typ: "vergleich", optionen: [evil, "b"], kriterien: [{ name: evil, werte: [evil, 1] }], vorteile: [[evil], []], nachteile: [[], []], fazit: evil },
      { typ: "zeitstrahl", einheit: "", ereignisse: [{ zeit: evil, titel: evil, text: evil }] },
      { typ: "gegenueber", sprachen: [evil, "x"], paare: [{ original: evil, uebersetzung: evil }] }]));
    click("Antwort zeigen");
    expect(screen.getAllByText(evil).length).toBeGreaterThanOrEqual(10);
    expect(document.querySelector(".view-card script, .view-card b, .view-card img, .view-card a, .view-card [href]")).toBeNull();
  });

  it("unvollständige Daten fängt BlockGuard je Baustein ab, der Rest der Ansicht bleibt", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const broken = [{ typ: "vergleich", optionen: ["a", "b"] }, { typ: "zeitstrahl" }, { typ: "gegenueber", paare: [] },
      { typ: "lernkarten" }, { typ: "quiz" }, { typ: "anleitung" }] as unknown as Block[];
    card(view("lernen", [...broken, { typ: "text", absaetze: ["Bleibt sichtbar."] }]));
    expect(screen.getAllByRole("alert")).toHaveLength(6);
    expect(screen.getAllByText("Dieser Teil der Ansicht konnte nicht angezeigt werden.")).toHaveLength(6);
    expect(screen.getByText("Bleibt sichtbar.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Schließen (Esc)" })).toBeInTheDocument();
  });

  it("parseItem kennt die Art „lernen“ (und „netz“) und die sechs Bausteine", () => {
    const v = parseItem({ seq: 1, id: "l", art: "lernen", titel: "T", bausteine: ["vergleich", "zeitstrahl", "gegenueber", "lernkarten", "quiz", "anleitung", "netzwerk"].map((typ) => ({ typ })) }) as View;
    expect(v.art).toBe("lernen");
    expect(v.bausteine.map((b) => b.typ)).toEqual(["vergleich", "zeitstrahl", "gegenueber", "lernkarten", "quiz", "anleitung"]);
    expect((parseItem({ seq: 1, id: "n", art: "netz", titel: "T", bausteine: [] }) as View).art).toBe("netz");
  });

  it("die Beispiele der Vorführung sind vollständig: jede neue Ansicht zeigt sich ohne Fehlerhinweis", () => {
    const fresh = DEMO_VIEWS.map((raw, i) => parseItem({ ...raw, seq: i + 1 }) as View)
      .filter((v) => v.bausteine.some((b) => ["vergleich", "zeitstrahl", "gegenueber", "lernkarten", "quiz", "anleitung"].includes(b.typ)));
    expect(fresh.flatMap((v) => v.bausteine.map((b) => b.typ)).sort()).toEqual(["anleitung", "gegenueber", "lernkarten", "quiz", "vergleich", "zeitstrahl"]);
    for (const v of fresh) {
      const r = card(v);
      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.getByRole("heading", { name: v.titel })).toBeInTheDocument();
      r.unmount();
    }
  });
});

describe("Kein Klick sendet etwas", () => {
  it("Karten, Quiz und Anleitung durchklicken lässt die gesendeten Nachrichten unverändert", async () => {
    const sock: { current?: MockSocket } = {};
    const loader = async () => ({ client: new ApiClient({ port: 5000, token: TOKEN }, (u) => (sock.current = new MockSocket(u, TOKEN))) });
    render(<App load={loader} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    sock.current!.show({ id: "lern", art: "lernen", titel: "Üben", bausteine: [CARDS, QUIZ, GUIDE()] });
    await waitFor(() => screen.getByRole("heading", { name: "Üben" }), { timeout: 3000 });
    const pollTypes = new Set(sock.current!.sent.map((m) => (m as { type: string }).type));
    const before = JSON.stringify(sock.current!.sent);

    for (let i = 0; i < 3; i++) { click("Antwort zeigen"); click(i % 2 ? "nochmal" : "gewusst"); }
    click(/Nochmal-Karten üben/); click("Antwort zeigen"); click("gewusst"); click("Alle von vorn");
    for (const q of [["Bern", "Nächste Frage"], ["Rhein", "Ergebnis zeigen"]]) {
      fireEvent.click(screen.getByRole("radio", { name: q[0] })); click("Prüfen"); click(q[1]);
    }
    click("Von vorn");
    click("Weiter"); click("Weiter"); click("Timer starten"); click("Timer abbrechen"); click("Zurück");
    fireEvent.keyDown(document.querySelector(".a-step") as HTMLElement, { key: "ArrowRight" });
    fireEvent.click(screen.getByText("Alle Schritte (4)"));

    expect(JSON.stringify(sock.current!.sent)).toBe(before);                              // nichts dazugekommen
    await new Promise((r) => setTimeout(r, 1200));                                         // auch später nur die üblichen Abfragen
    const later = sock.current!.sent.map((m) => (m as { type: string }).type);
    expect(later.filter((t) => !pollTypes.has(t))).toEqual([]);
    expect(screen.getByRole("heading", { name: "Üben" })).toBeInTheDocument();
  });
});
