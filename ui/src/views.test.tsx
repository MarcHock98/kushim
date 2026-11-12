import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "./App";
import { ViewCard } from "./components/stage/ViewCard";
import { ApiClient } from "./lib/api";
import { STATE_VIEW } from "./lib/avatarState";
import { MockSocket } from "./lib/mock";
import { parseItem, type Block, type View } from "./lib/stage";

// Ansichten, die Claude über `zeige` schickt (Plan docs/ui-p2-plan.md, Abschnitt 5).

const TOKEN = "t".repeat(43);
afterEach(cleanup);

const view = (art: View["art"], bausteine: Block[], extra: Partial<View> = {}): View =>
  ({ seq: 1, id: "v1", art, titel: "Titel", stand: "", bausteine, ...extra });
const card = (v: View) => render(<ViewCard view={v} sys={null} sysNo={false} onClose={() => undefined} />);

async function open() {
  const sock: { current?: MockSocket } = {};
  const loader = async () => ({
    client: new ApiClient({ port: 5000, token: TOKEN }, (u) => (sock.current = new MockSocket(u, TOKEN))),
  });
  render(<App load={loader} />);
  await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
  return sock;
}
const heading = (name: string) => waitFor(() => screen.getByRole("heading", { name }), { timeout: 3000 });

describe("Ansichten je Art", () => {
  it("antwort: Text und Liste, Eingaben bleiben Text (kein HTML)", () => {
    card(view("antwort", [
      { typ: "text", absaetze: ["Erster Absatz.", "<b>fett</b> <img src=x onerror=alert(1)>"] },
      { typ: "liste", punkte: ["eins", "zwei"], nummeriert: true },
    ]));
    expect(screen.getByText("Erster Absatz.")).toBeInTheDocument();
    expect(screen.getByText(/<b>fett<\/b>/)).toBeInTheDocument();
    expect(document.querySelector(".view-card b, .view-card img")).toBeNull();
    expect(document.querySelectorAll("ol.v-list li")).toHaveLength(2);
  });

  it("rechnung: nummerierte Schritte, Formel mit KaTeX, Ergebnis mit Wort", async () => {
    card(view("rechnung", [
      { typ: "formel", tex: "x^2 = 9" },
      { typ: "schritte", schritte: [{ text: "Wurzel ziehen", tex: "x = \\sqrt{9}" }, { text: "Ausrechnen", tex: "" }] },
      { typ: "ergebnis", text: "x ist drei", tex: "x = 3" },
    ]));
    expect(document.querySelectorAll(".v-steps > li")).toHaveLength(2);
    expect(screen.getByText("Ergebnis")).toBeInTheDocument();
    expect(screen.getByText("x ist drei")).toBeInTheDocument();
    await waitFor(() => expect(document.querySelectorAll(".katex").length).toBeGreaterThanOrEqual(3), { timeout: 5000 });
    expect(screen.queryByText(/Formel fehlerhaft/)).toBeNull();
  });

  it("eine fehlerhafte Formel erscheint als Rohtext mit dem Wort „Formel fehlerhaft“", async () => {
    card(view("rechnung", [{ typ: "formel", tex: "\\frac{1" }]));
    await waitFor(() => screen.getByText(/Formel fehlerhaft/), { timeout: 5000 });
    expect(document.querySelector(".tex")!.textContent).toContain("\\frac{1");
    expect(document.querySelector(".katex")).toBeNull();
  });

  it("eine Formel kann keinen Link und kein HTML einschleusen (trust: false)", async () => {
    card(view("rechnung", [
      { typ: "formel", tex: "\\href{javascript:alert(1)}{klick}" },
      { typ: "formel", tex: "\\htmlClass{boese}{x} + \\url{file:///c:/geheim}" },
      { typ: "formel", tex: "a + b" },
    ]));
    await waitFor(() => expect(document.querySelector(".katex")).not.toBeNull(), { timeout: 5000 });
    await new Promise((r) => setTimeout(r, 200));
    expect(document.querySelector(".view-card a, .view-card [href], .view-card .boese, .view-card script, .view-card img")).toBeNull();
  });

  it("markt: Kennzahlen mit Wort für die Richtung, Stand, Tabelle und der feste Hinweis", () => {
    card(view("markt", [
      { typ: "kennzahlen", werte: [
        { name: "Kurs", wert: 1234.5, einheit: "EUR", aenderung: "+1,2 %", richtung: "auf" },
        { name: "Vortag", wert: "1.220", einheit: "", aenderung: "", richtung: "ab" },
      ] },
      { typ: "tabelle", spalten: ["Tag", "Schluss"], zeilen: [["Mo", 1220], ["Di", 1234.5]] },
    ], { stand: "12.11.2026 18:00" }));
    expect(screen.getByText(/steigt/)).toBeInTheDocument();
    expect(screen.getByText(/fällt/)).toBeInTheDocument();
    expect(screen.getByText(/Stand: 12\.11\.2026 18:00/)).toBeInTheDocument();
    expect(screen.getByText("Nur zur Information, keine Anlageberatung.")).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader")).toHaveLength(2);
    expect(document.querySelectorAll("td.num")).toHaveLength(2);
  });

  it("markt ohne Stand sagt das ausdrücklich", () => {
    card(view("markt", [{ typ: "hinweis", text: "Daten verzögert." }]));
    expect(screen.getByText("Stand: unbekannt")).toBeInTheDocument();
    expect(screen.getByText("Nur zur Information, keine Anlageberatung.")).toBeInTheDocument();
  });

  it("der Hinweis zur Anlageberatung steht nur bei markt", () => {
    card(view("antwort", [{ typ: "text", absaetze: ["Hallo."] }]));
    expect(screen.queryByText(/Anlageberatung/)).toBeNull();
    expect(screen.queryByText("Stand: unbekannt")).toBeNull();
  });

  it("recherche: Aussagen mit Quellennummern, Widerspruchs-Kasten, Quellen als Text ohne Link", () => {
    card(view("recherche", [
      { typ: "text", absaetze: ["Zusammenfassung."] },
      { typ: "aussagen", aussagen: [{ text: "Aussage A", quellen: [1, 2] }, { text: "Aussage B", quellen: [] }] },
      { typ: "widerspruch", aussagen: [{ text: "Quelle 1 sagt ja", quellen: [1] }, { text: "Quelle 2 sagt nein", quellen: [2] }] },
      { typ: "quellen", quellen: [{ nr: 1, titel: "Erste Quelle", adresse: "https://beispiel.example/a" }, { nr: 2, titel: "Zweite Quelle", adresse: "" }] },
    ]));
    expect(screen.getByLabelText("Quellen 1, 2")).toHaveTextContent("[1] [2]");
    const box = screen.getByRole("note");
    expect(within(box).getByText("Quellen widersprechen sich")).toBeInTheDocument();
    expect(within(box).getByText(/Quelle 2 sagt nein/)).toBeInTheDocument();
    const aside = screen.getByRole("complementary", { name: "Quellen" });
    expect(within(aside).getByText(/Erste Quelle/)).toBeInTheDocument();
    expect(within(aside).getByText("https://beispiel.example/a").tagName).toBe("CODE");
    expect(document.querySelector(".view-card a")).toBeNull();
    expect(document.querySelector(".view-main .v-sources")).toBeNull();          // Quellen stehen nur in der Seitenspalte
  });
});

describe("Diagramm", () => {
  const points = (el: Element) => el.getAttribute("points")!.trim().split(" ");

  it("Linie: genau die gelieferten Punkte, Reihen unterscheiden sich auch in der Strichart, Legende mit Namen", () => {
    card(view("markt", [{ typ: "diagramm", form: "linie", x_titel: "Tag", y_titel: "Kurs", reihen: [
      { name: "Aktie", punkte: [[1, 10], [2, 12], [3, 11]] },
      { name: "Index", punkte: [[1, 9], [2, 9.5], [3, 10]] },
    ] }]));
    const svg = screen.getByRole("img", { name: "Diagramm: Kurs über Tag, Aktie, Index" });
    const lines = svg.querySelectorAll("polyline");
    expect(lines).toHaveLength(2);
    expect(points(lines[0])).toHaveLength(3);
    expect(points(lines[0]).every((p) => /^\d+(\.\d+)?,\d+(\.\d+)?$/.test(p))).toBe(true);
    expect(lines[0].getAttribute("stroke-dasharray") ?? "").not.toBe(lines[1].getAttribute("stroke-dasharray"));
    const legend = document.querySelector(".chart-legend")!;
    expect(legend.textContent).toContain("Aktie");
    expect(legend.textContent).toContain("Index");
  });

  it("Balken: ein Balken je Punkt, Kategorien als Beschriftung", () => {
    card(view("markt", [{ typ: "diagramm", form: "balken", x_titel: "", y_titel: "Umsatz", reihen: [
      { name: "2026", punkte: [["Q1", 4], ["Q2", 6], ["Q3", -1]] },
    ] }]));
    const svg = screen.getByRole("img", { name: "Diagramm: Umsatz, 2026" });
    expect(svg.querySelectorAll("rect")).toHaveLength(3);
    expect(svg.querySelector("polyline")).toBeNull();
    for (const q of ["Q1", "Q2", "Q3"]) expect(within(svg as unknown as HTMLElement).getByText(q)).toBeInTheDocument();
  });

  it("kein Punkt liegt außerhalb des Gitters, auch wenn der höchste Wert keine runde Zahl ist", () => {
    card(view("markt", [{ typ: "diagramm", form: "linie", x_titel: "", y_titel: "Punkte", reihen: [
      { name: "DAX", punkte: [[9, 19260], [10, 19310], [14, 19420.5]] }] }]));
    const svg = document.querySelector(".chart svg")!;
    const gridY = [...svg.querySelectorAll("line.chart-grid")].map((l) => Number(l.getAttribute("y1")));
    const ys = points(svg.querySelector("polyline")!).map((p) => Number(p.split(",")[1]));
    expect(Math.min(...ys)).toBeGreaterThanOrEqual(Math.min(...gridY));
    expect(Math.max(...ys)).toBeLessThanOrEqual(Math.max(...gridY));
    const title = [...svg.querySelectorAll("text.chart-title")].find((e) => e.textContent === "Punkte")!;
    expect(Number(title.getAttribute("y"))).toBeLessThan(Math.min(...gridY) - 10);     // Titel überdeckt die oberste Zahl nicht
  });

  it("ein einzelner Punkt oder gleiche Werte zeichnen ohne NaN", () => {
    card(view("markt", [{ typ: "diagramm", form: "linie", x_titel: "", y_titel: "", reihen: [{ name: "A", punkte: [[5, 7]] }] }]));
    expect(document.querySelector(".chart svg")!.outerHTML).not.toMatch(/NaN|Infinity/);
  });
});

describe("Formprüfung (parseItem)", () => {
  it("übergeht Fremdes und kürzt Titel, Stand und die Zahl der Bausteine", () => {
    expect(parseItem(null)).toBeNull();
    expect(parseItem({ seq: 1, id: "a", art: "werbung", titel: "x", bausteine: [] })).toBeNull();
    expect(parseItem({ seq: "1", id: "a", art: "antwort", titel: "x", bausteine: [] })).toBeNull();
    expect(parseItem({ seq: 1, id: "a".repeat(41), art: "antwort", titel: "x", bausteine: [] })).toBeNull();
    expect(parseItem({ seq: 2, id: "a", schliessen: true })).toEqual({ seq: 2, id: "a", schliessen: true });
    const v = parseItem({ seq: 3, id: "a", art: "antwort", titel: "t".repeat(200), stand: "s".repeat(80),
      bausteine: [{ typ: "html", code: "<b>" }, "text", ...Array.from({ length: 20 }, () => ({ typ: "hinweis", text: "h" }))] }) as View;
    expect(v.titel).toHaveLength(120);
    expect(v.stand).toHaveLength(40);
    expect(v.bausteine).toHaveLength(12);
    expect(v.bausteine.every((b) => b.typ === "hinweis")).toBe(true);
  });
});

describe("Bühne mit Ansichten", () => {
  const show = (sock: { current?: MockSocket }, id: string, titel: string, text = "Inhalt") =>
    sock.current!.show({ id, art: "antwort", titel, bausteine: [{ typ: "text", absaetze: [text] }] });

  it("dieselbe id ersetzt den Inhalt (Live-Update), ohne zweiten Reiter", async () => {
    const sock = await open();
    show(sock, "r1", "Recherche läuft", "Erster Stand");
    await heading("Recherche läuft");
    show(sock, "r1", "Recherche fertig", "Zweiter Stand");
    await heading("Recherche fertig");
    expect(screen.queryByText("Erster Stand")).toBeNull();
    expect(screen.getByText("Zweiter Stand")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(document.querySelectorAll("article.view-card")).toHaveLength(1);
  });

  it("mehrere Ansichten: die neueste ist offen, die übrigen als Reiter (höchstens 5), ein Klick wechselt", async () => {
    const sock = await open();
    show(sock, "a", "Erste");
    await heading("Erste");
    show(sock, "b", "Zweite");
    await heading("Zweite");
    const tabs = within(screen.getByRole("tablist", { name: "Gezeigte Ansichten" })).getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Erste", "Zweite"]);
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
    await act(async () => { fireEvent.click(tabs[0]); });
    await heading("Erste");
    for (const n of [3, 4, 5, 6, 7]) show(sock, `x${n}`, `Nummer ${n}`);
    await heading("Nummer 7");
    expect(within(screen.getByRole("tablist")).getAllByRole("tab")).toHaveLength(5);
  });

  it("Claude kann eine Ansicht wieder schließen", async () => {
    const sock = await open();
    show(sock, "a", "Erste");
    await heading("Erste");
    sock.current!.stageSeq += 1;
    sock.current!.stage = [{ id: "a", schliessen: true, seq: sock.current!.stageSeq }];
    await waitFor(() => expect(document.querySelector("article.view-card")).toBeNull(), { timeout: 3000 });
    expect(screen.getByRole("region", { name: "Gespräch" })).toHaveAttribute("data-mode", "dialog");
  });

  it("die Übersicht listet Gezeigtes, „Zeigen“ öffnet es wieder auf der Bühne", async () => {
    const sock = await open();
    show(sock, "a", "Erste");
    await heading("Erste");
    await act(async () => { fireEvent.keyDown(window, { key: "Escape" }); });
    expect(document.querySelector("article.view-card")).toBeNull();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Übersicht" })); });
    const list = screen.getByRole("region", { name: "Gezeigt" });
    expect(within(list).getByText(/Erste/)).toBeInTheDocument();
    await act(async () => { fireEvent.click(within(list).getByRole("button", { name: "Zeigen" })); });
    await heading("Erste");
    expect(screen.getByRole("region", { name: "Gespräch" })).toHaveAttribute("data-mode", "zeige");
  });
});
