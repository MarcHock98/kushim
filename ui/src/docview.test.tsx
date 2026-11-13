import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ViewCard } from "./components/stage/ViewCard";
import { parseItem, type Block, type View } from "./lib/stage";

// Dateitext und Änderungen auf der Bühne (Plan docs/ui-p3b-plan.md, Weg A): kushim liest selbst keine Dateien.

afterEach(cleanup);

const view = (bausteine: Block[]): View => ({ seq: 1, id: "v1", art: "dokument", titel: "Übersicht", stand: "", bausteine });
const card = (v: View) => render(<ViewCard view={v} sys={null} sysNo={false} onClose={() => undefined} />);
const onlyClose = () => expect(within(document.querySelector(".view-card") as HTMLElement).getAllByRole("button").map((b) => b.getAttribute("aria-label")))
  .toEqual(["Schließen (Esc)"]);

const CODE = ["def rechne(a, b):", "    if a > b:", "        return a", "", "    return b"];

describe("Dokument", () => {
  it("zeigt Name, Ausschnitt, nummerierte Zeilen mit Einrückung und die Gliederung", () => {
    card(view([{ typ: "dokument", name: "src/rechnen.py", ausschnitt: "Zeilen 1 bis 5", zeilen: CODE, gliederung: ["rechne(a, b)"] }]));
    const doc = screen.getByRole("region", { name: "Datei src/rechnen.py" });
    expect(within(doc).getByText("src/rechnen.py").tagName).toBe("CODE");
    expect(within(doc).getByText(/Zeilen 1 bis 5/)).toBeInTheDocument();
    const lines = [...doc.querySelectorAll(".d-line")];
    expect(lines).toHaveLength(5);
    expect(lines[2].textContent).toBe("3        return a\n");                      // Nummer, ein Leerzeichen Abstand, Einrückung bleibt
    expect(lines[3].textContent).toBe("4\n");                                       // Leerzeile bleibt eine Zeile
    expect(within(doc).getByRole("navigation", { name: "Gliederung" })).toHaveTextContent("rechne(a, b)");
    expect(doc.querySelector(".d-no")).toHaveAttribute("aria-hidden", "true");     // Vorleser lesen den Code, nicht die Nummern
  });

  it("ohne Gliederung gibt es keine leere Spalte", () => {
    card(view([{ typ: "dokument", name: "a.txt", ausschnitt: "", zeilen: ["x"], gliederung: [] }]));
    expect(screen.queryByRole("navigation", { name: "Gliederung" })).toBeNull();
  });

  it("der Inhalt bleibt Text: kein Element aus Eingaben, kein Link, nichts anklickbar außer Schließen", () => {
    card(view([{ typ: "dokument", name: "boese.html", ausschnitt: "", gliederung: ["<b>x</b>"],
      zeilen: ["<script>alert(1)</script>", "<a href=\"https://boese.example\">klick</a>", "<img src=x onerror=alert(1)>"] }]));
    const doc = screen.getByRole("region", { name: "Datei boese.html" });
    expect(doc.querySelector("script, a, img, b, [href]")).toBeNull();
    expect(doc.textContent).toContain("<script>alert(1)</script>");
    expect(doc.textContent).toContain("<a href=\"https://boese.example\">klick</a>");
    onlyClose();
  });

  it("die Nummern sind gleich breit, auch bei mehr als neun Zeilen", () => {
    card(view([{ typ: "dokument", name: "a.txt", ausschnitt: "", gliederung: [], zeilen: Array.from({ length: 12 }, (_, i) => `z${i + 1}`) }]));
    const nos = [...document.querySelectorAll(".d-no")].map((n) => n.textContent);
    expect(nos[0]).toBe(" 1");
    expect(nos[11]).toBe("12");
  });
});

describe("Änderung", () => {
  const change: Block = { typ: "aenderung", name: "src/rechnen.py", zusammenfassung: "Leere Eingaben liefern jetzt 0.", bloecke: [
    { kopf: "rechne", zeilen: [{ art: "gleich", text: "def rechne(a, b):" }, { art: "neu", text: "    if a is None:" },
      { art: "neu", text: "        return 0" }, { art: "weg", text: "    return a + b" }] },
    { kopf: "", zeilen: [{ art: "neu", text: "# Ende" }] }] };

  it("zählt neue und entfernte Zeilen und nennt die Zusammenfassung", () => {
    card(view([change]));
    const box = screen.getByRole("region", { name: "Änderung an src/rechnen.py" });
    expect(within(box).getByText(/3 neu, 1 entfernt/)).toBeInTheDocument();
    expect(within(box).getByText("Leere Eingaben liefern jetzt 0.")).toBeInTheDocument();
    expect(within(box).getByText("rechne")).toBeInTheDocument();
  });

  it("Plus und Minus stehen als Zeichen mit Wort, nicht nur als Farbe", () => {
    card(view([change]));
    const rows = [...document.querySelectorAll(".d-line")];
    const mark = (i: number) => rows[i].querySelector(".d-mark") as HTMLElement;
    expect([0, 1, 2, 3].map((i) => mark(i).textContent)).toEqual([" ", "+", "+", "-"]);
    expect([0, 1, 3].map((i) => mark(i).getAttribute("aria-label"))).toEqual(["unverändert", "neu", "entfernt"]);
    expect(rows[1]).toHaveClass("d-neu");
    expect(rows[3]).toHaveClass("d-weg");
    expect(rows[3].textContent).toBe("-    return a + b\n");
  });

  it("trägt den festen Hinweis, dass Claude Code entscheidet, und hat keine Knöpfe zum Anwenden", () => {
    card(view([change]));
    expect(screen.getByText("Anzeige von Claude. Ob die Änderung geschrieben wird, entscheidest du in Claude Code.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /anwenden|schreiben|übernehmen|apply/i })).toBeNull();
    onlyClose();
  });

  it("der feste Hinweis steht nur bei Änderungen, nicht beim Dokument", () => {
    card(view([{ typ: "dokument", name: "a.txt", ausschnitt: "", zeilen: ["x"], gliederung: [] }]));
    expect(screen.queryByText(/entscheidest du in Claude Code/)).toBeNull();
  });
});

describe("Formprüfung", () => {
  it("kennt die Art dokument und beide Bausteine", () => {
    const v = parseItem({ seq: 1, id: "d", art: "dokument", titel: "T", bausteine: [{ typ: "dokument" }, { typ: "aenderung" }, { typ: "skript" }] }) as View;
    expect(v.art).toBe("dokument");
    expect(v.bausteine.map((b) => b.typ)).toEqual(["dokument", "aenderung"]);
  });
});
