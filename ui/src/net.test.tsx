import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { ViewCard } from "./components/stage/ViewCard";
import { ApiClient } from "./lib/api";
import { STATE_VIEW } from "./lib/avatarState";
import { layoutNet, wrapText } from "./lib/layout";
import { DEMO_VIEWS, MockSocket } from "./lib/mock";
import { parseItem, type Block, type NetBlock, type View } from "./lib/stage";

// P6b (docs/ui-p6-plan.md, Abschnitt 4): Diagramm `netz` als eigenes SVG mit Zoom, Verschieben und einer Liste für Vorleser.
// Kernregel wie bei P6a: Bedienen ändert nur die Anzeige im Fenster und sendet nie etwas.

vi.mock("./lib/layout", async (orig) => {
  const m = await orig<typeof import("./lib/layout")>();
  return { ...m, layoutNet: vi.fn(m.layoutNet) };
});

const TOKEN = "t".repeat(43);
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.mocked(layoutNet).mockClear(); });

type Art = NetBlock["knoten"][number]["art"];
const k = (id: string, text = id, art: Art = "") => ({ id, text, art });
const e = (von: string, bis: string, text = "") => ({ von, bis, text });
const net = (form: NetBlock["form"], knoten: NetBlock["knoten"], kanten: NetBlock["kanten"]): NetBlock => ({ typ: "netz", form, knoten, kanten });
const view = (bausteine: Block[], extra: Partial<View> = {}): View => ({ seq: 1, id: "n1", art: "netz", titel: "Titel", stand: "", bausteine, ...extra });
const card = (v: View) => render(<ViewCard view={v} sys={null} sysNo={false} onClose={() => undefined} />);
const btn = (name: string | RegExp) => screen.getByRole("button", { name });
const click = (name: string | RegExp) => fireEvent.click(btn(name));
const svg = () => document.querySelector("svg.n-svg") as SVGSVGElement;
const size = () => [Number(svg().getAttribute("width")), Number(svg().getAttribute("height"))];
const shift = () => svg().style.transform;
const frame = () => screen.getByRole("group", { name: /Diagramm-Fläche/ });
const items = (sel: string) => [...document.querySelectorAll(sel)].map((li) => li.textContent);

const FLOW = net("ablauf", [k("s", "Start", "start"), k("p", "Prüfen", "entscheidung"), k("j", "Ja"), k("n", "Nein", "schritt"), k("x", "Ende", "ende")],
  [e("s", "p"), e("p", "j", "ok"), e("p", "n"), e("j", "x"), e("n", "s", "nochmal")]);
const TREE = net("baum", [k("gf", "Leitung"), k("a", "Vertrieb"), k("b", "Technik"), k("a1", "Innendienst"), k("b1", "Software"), k("b2", "Hardware")],
  [e("gf", "a"), e("gf", "b"), e("a", "a1"), e("b", "b1"), e("b", "b2", "neu")]);
const MIND = net("mindmap", [k("m", "Mitte"), k("x", "Ast 1"), k("y", "Ast 2"), k("z", "Ast 3"), k("x1", "Zweig")],
  [e("m", "x"), e("m", "y"), e("m", "z"), e("x", "x1")]);
const star = (form: NetBlock["form"], n = 60) =>
  net(form, Array.from({ length: n }, (_, i) => k(`n${i}`, i ? `Knoten ${i}` : "Wurzel", i ? "" : form === "ablauf" ? "start" : "")),
    Array.from({ length: n - 1 }, (_, i) => e("n0", `n${i + 1}`)));

describe("Zeichnen", () => {
  it.each([["ablauf", FLOW], ["baum", TREE], ["mindmap", MIND]] as const)("%s: jeder Knoten ein Kasten, jede Kante eine Linie mit Pfeil", (_, b) => {
    card(view([b]));
    const s = svg();
    expect(s.querySelectorAll(".n-node")).toHaveLength(b.knoten.length);
    expect(s.querySelectorAll("polyline.n-edge")).toHaveLength(b.kanten.length);
    expect(s.getAttribute("viewBox")).toMatch(/^0 0 \d+(\.\d)? \d+(\.\d)?$/);
    expect(s.getAttribute("aria-hidden")).toBe("true");
    const marker = s.querySelector("defs marker")!;
    expect(marker.querySelector("path")).not.toBeNull();
    for (const l of s.querySelectorAll("polyline")) expect(l.getAttribute("marker-end")).toBe(`url(#${marker.id})`);
    expect(s.outerHTML).not.toMatch(/NaN|Infinity/);
    for (const t of b.knoten) expect(within(s as unknown as HTMLElement).getByText(t.text)).toBeInTheDocument();
  });

  it("Formen zeigen die Art: Kapsel für Start, doppelte Kapsel für Ende, Raute für Entscheidung, Kasten für Schritt", () => {
    card(view([FLOW]));
    const s = svg();
    const startRect = s.querySelector(".n-start rect.n-shape")!;
    expect(Number(startRect.getAttribute("rx"))).toBeCloseTo(Number(startRect.getAttribute("height")) / 2, 0);
    expect(s.querySelector(".n-start .n-inner")).toBeNull();
    expect(s.querySelector(".n-ende .n-inner")).not.toBeNull();
    expect(s.querySelector(".n-entscheidung polygon.n-shape")!.getAttribute("points")!.split(" ")).toHaveLength(4);
    expect(s.querySelectorAll(".n-schritt rect.n-shape")).toHaveLength(2);                 // „Ja“ mit art "" und „Nein“ mit schritt
    const list = items(".n-flat > li");
    expect(list.some((t) => t!.startsWith("Start (Start)"))).toBe(true);
    expect(list.some((t) => t!.startsWith("Prüfen (Entscheidung)"))).toBe(true);
    expect(list.some((t) => t!.startsWith("Ende (Ende)"))).toBe(true);
    expect(list.some((t) => /^Ja \(/.test(t!))).toBe(false);                               // Schritt ohne Zusatzwort
  });

  it("Kantenbeschriftungen stehen als Text an der Linie; Rückwärtskanten sind gestrichelt (Klasse), nicht nur andersfarbig", () => {
    card(view([FLOW]));
    expect([...svg().querySelectorAll(".n-label")].map((t) => t.textContent).sort()).toEqual(["nochmal", "ok"]);
    expect(svg().querySelectorAll(".n-label-bg")).toHaveLength(2);
    expect(svg().querySelectorAll("polyline.n-back")).toHaveLength(1);
  });

  it("Text bleibt Text: <script> und <b> stehen wörtlich da, kein HTML, keine Links, keine Bilder", () => {
    const evil = "<script>x</script>";                                                    // passt in eine Zeile
    const long = "<script>alert(1)</script><b>x</b><img src=x onerror=alert(1)>";         // wird umbrochen, bleibt Text
    card(view([net("ablauf", [k("a", evil, "start"), k("b", long)], [e("a", "b", evil)])]));
    expect(screen.getAllByText(evil).length).toBeGreaterThanOrEqual(3);                   // Kasten, Beschriftung, Liste
    const tspans = [...svg().querySelectorAll('[data-id="b"] tspan')].map((t) => t.textContent);
    expect(tspans.length).toBeGreaterThan(1);
    expect(tspans).toEqual(wrapText(long));                                                // Zeilen genau aus der Anordnung
    expect(screen.getAllByText(long).length).toBeGreaterThanOrEqual(1);                   // ungekürzt in der Liste
    expect(document.querySelector(".view-card script, .view-card b, .view-card img, .view-card a, .view-card [href], .view-card foreignObject, .view-card image")).toBeNull();
  });

  it("die Anordnung läuft einmal je Datenstand, nicht bei jedem Zoom", () => {
    const v = view([FLOW]);
    const r = card(v);
    expect(layoutNet).toHaveBeenCalledTimes(1);
    expect(vi.mocked(layoutNet).mock.calls[0][1].map((n) => n.art)).toEqual(["start", "entscheidung", undefined, "schritt", "ende"]);   // "" -> nicht angegeben
    click("Vergrößern"); click("Verkleinern"); fireEvent.keyDown(frame(), { key: "+" });
    expect(layoutNet).toHaveBeenCalledTimes(1);
    r.rerender(<ViewCard view={{ ...v, seq: 2, bausteine: [TREE] }} sys={null} sysNo={false} onClose={() => undefined} />);
    expect(layoutNet).toHaveBeenCalledTimes(2);
    expect(svg().querySelectorAll(".n-node")).toHaveLength(TREE.knoten.length);
  });

  it("art \"\" heißt Schritt: Kasten, kein Zusatzwort", () => {
    card(view([net("ablauf", [k("a", "Eins"), k("b", "Zwei")], [e("a", "b")])]));
    expect(svg().querySelectorAll(".n-schritt")).toHaveLength(2);
    expect(items(".n-flat > li")).toEqual(["Eins führt zu Zwei", "Zwei führt nicht weiter"]);
  });

  it("ein Diagramm mit 60 Knoten zeichnet in jeder Form vollständig und ohne NaN", () => {
    for (const form of ["ablauf", "baum", "mindmap"] as const) {
      const b = star(form);
      const r = card(view([b]));
      expect(svg().querySelectorAll(".n-node")).toHaveLength(60);
      expect(svg().querySelectorAll(".n-edge")).toHaveLength(59);
      expect(svg().outerHTML).not.toMatch(/NaN|Infinity/);
      expect(document.querySelectorAll(form === "ablauf" ? ".n-flat > li" : ".n-tree li")).toHaveLength(60);
      r.unmount();
    }
  });
});

describe("Zoom und Verschieben", () => {
  it("klein: startet in Originalgröße, Zoom bleibt in Grenzen, Einpassen stellt den Start her", () => {
    card(view([FLOW]));
    const l = layoutNet("ablauf", FLOW.knoten.map((n) => ({ ...n, art: n.art || undefined })), FLOW.kanten);
    const [w0, h0] = size();
    expect(w0).toBeCloseTo(l.width, 0);                                                    // passt: Maßstab 1, nicht vergrößert
    expect(screen.getByText("Maßstab 100 %")).toBeInTheDocument();
    click("Vergrößern");
    expect(size()[0]).toBeGreaterThan(w0);
    expect(size()[1]).toBeGreaterThan(h0);
    for (let i = 0; i < 20; i++) click("Vergrößern");
    expect(size()[0]).toBeCloseTo(l.width * 3, 0);                                         // höchstens 300 %
    expect(btn("Vergrößern")).toHaveAttribute("aria-disabled", "true");
    for (let i = 0; i < 40; i++) click("Verkleinern");
    expect(size()[0]).toBeCloseTo(l.width * 0.5, 0);                                       // mindestens 50 %
    expect(btn("Verkleinern")).toHaveAttribute("aria-disabled", "true");
    click("Einpassen");
    expect(size()[0]).toBeCloseTo(w0, 0);
    expect(btn("Nach links")).toHaveAttribute("aria-disabled", "true");                   // passt ganz: nichts zu verschieben
  });

  it("sehr breit (Stern mit 60 Knoten): Start lesbar statt winzig, Verschieben ändert den Ausschnitt, Einpassen zeigt alles", () => {
    card(view([star("baum")]));
    const W = Number(svg().getAttribute("viewBox")!.split(" ")[2]);
    expect(W).toBeGreaterThan(5000);
    expect(size()[0]).toBeCloseTo(W * 0.75, 0);                                            // nicht auf die Breite gequetscht
    expect(screen.getByText(/Größer als die Fläche/)).toBeInTheDocument();
    const t0 = shift();
    expect(t0).toMatch(/^translate\(-?\d+(\.\d)?px, -?\d+(\.\d)?px\)$/);
    click("Nach rechts");
    expect(shift()).not.toBe(t0);
    click("Nach links");
    expect(shift()).toBe(t0);
    for (let i = 0; i < 200; i++) click("Nach links");                                     // Rand: bleibt am Diagramm
    expect(shift()).toMatch(/^translate\(0px, /);
    expect(btn("Nach links")).toHaveAttribute("aria-disabled", "true");
    click("Einpassen");
    expect(size()[0]).toBeLessThanOrEqual(720);
    expect(size()[0]).toBeGreaterThan(700);                                                // ganz sichtbar in 718 px Breite
    expect(screen.queryByText(/Größer als die Fläche/)).toBeNull();
    for (let i = 0; i < 10; i++) click("Verkleinern");
    expect(size()[0]).toBeGreaterThanOrEqual(W * 0.02 - 1);                                // untere Grenze
  });

  it("Mindmap startet mittig; Tastatur: Plus, Minus, Null und Pfeiltasten auf der fokussierbaren Fläche", () => {
    card(view([star("mindmap")]));
    const f = frame();
    expect(f.tabIndex).toBe(0);
    const [w0] = size(), t0 = shift();
    const ty = Number(/, (-?[\d.]+)px/.exec(t0)![1]);
    expect(ty).toBeLessThan(0);                                                            // nicht oben angeheftet: Wurzel in der Mitte
    fireEvent.keyDown(f, { key: "+" });
    expect(size()[0]).toBeGreaterThan(w0);
    fireEvent.keyDown(f, { key: "-" });
    fireEvent.keyDown(f, { key: "-" });
    expect(size()[0]).toBeLessThan(w0);
    fireEvent.keyDown(f, { key: "0" });
    const fit = size()[0];
    expect(fit).toBeLessThan(w0);
    fireEvent.keyDown(f, { key: "+" }); fireEvent.keyDown(f, { key: "+" }); fireEvent.keyDown(f, { key: "+" }); fireEvent.keyDown(f, { key: "+" });
    const t1 = shift();
    fireEvent.keyDown(f, { key: "ArrowDown" });
    expect(shift()).not.toBe(t1);
    fireEvent.keyDown(f, { key: "ArrowUp" });
    expect(shift()).toBe(t1);
    fireEvent.keyDown(f, { key: "ArrowRight" });
    expect(shift()).not.toBe(t1);
    fireEvent.keyDown(f, { key: "Home" });
    expect(size()[0]).toBe(fit);
  });

  it("alle Bedienelemente sind echte Knöpfe mit Text; Ziehen verschiebt zusätzlich", () => {
    card(view([star("ablauf")]));
    const names = within(screen.getByRole("group", { name: "Ansicht des Diagramms" })).getAllByRole("button").map((b) => b.textContent);
    expect(names).toEqual(["Vergrößern", "Verkleinern", "Einpassen", "Nach links", "Nach rechts", "Nach oben", "Nach unten"]);
    const t0 = shift();
    fireEvent.pointerDown(frame(), { clientX: 100, clientY: 50, pointerId: 1 });
    fireEvent.pointerMove(frame(), { clientX: 40, clientY: 50, pointerId: 1 });
    fireEvent.pointerUp(frame(), { pointerId: 1 });
    expect(svg().outerHTML).not.toMatch(/NaN/);
    expect(Number(/translate\((-?[\d.]+)px/.exec(shift())![1])).toBeCloseTo(Number(/translate\((-?[\d.]+)px/.exec(t0)![1]) - 60, 0);
  });
});

describe("Liste für Vorleser", () => {
  it("Ablauf: jeder Knoten genau einmal mit allen Zielen, Beschriftungen in Worten, Rückweg als „zurück zu“", () => {
    card(view([FLOW]));
    const details = document.querySelector("details.n-list") as HTMLDetailsElement;
    expect(details.open).toBe(false);                                                      // eingeklappt, aber im DOM
    expect(within(details).getByText(/Als Liste zeigen/)).toBeInTheDocument();
    expect(items(".n-flat > li")).toEqual([
      "Start (Start) führt zu Prüfen",
      "Prüfen (Entscheidung) führt zu Ja (Beschriftung: ok) und Nein",
      "Ja führt zu Ende",
      "Nein führt zurück zu Start (Beschriftung: nochmal)",
      "Ende (Ende) führt nicht weiter"].sort((a, b) => FLOW_ORDER(a) - FLOW_ORDER(b)));
  });

  it("Ablauf mit reinem Kreis (ohne Start) und Schleife auf sich selbst endet und nennt jede Kante", () => {
    card(view([net("ablauf", [k("a", "A"), k("b", "B"), k("c", "C")], [e("a", "b"), e("b", "c"), e("c", "a", "wieder"), e("b", "b")])]));
    const list = items(".n-flat > li");
    expect(list).toHaveLength(3);
    expect(list.filter((t) => /zurück zu/.test(t!))).toHaveLength(2);
    expect(list.join(" | ")).toMatch(/B führt zu C und zurück zu sich selbst/);
    expect(list.join(" | ")).toMatch(/C führt zurück zu A \(Beschriftung: wieder\)/);
  });

  it("Baum: echte verschachtelte Liste ab der Wurzel, jeder Knoten einmal", () => {
    card(view([TREE]));
    const root = document.querySelectorAll(".n-tree > li");
    expect(root).toHaveLength(1);
    expect(root[0].querySelector(".n-name")!.textContent).toBe("Leitung");
    expect([...root[0].querySelectorAll(":scope > ul > li > .n-name")].map((n) => n.textContent)).toEqual(["Vertrieb", "Technik"]);
    const technik = [...document.querySelectorAll(".n-tree li")].find((li) => li.querySelector(".n-name")!.textContent === "Technik")!;
    expect([...technik.querySelectorAll(":scope > ul > li")].map((li) => li.textContent)).toEqual(["Software", "Hardware (Beschriftung: neu)"]);
    expect(document.querySelectorAll(".n-tree li")).toHaveLength(TREE.knoten.length);
    expect(svg().querySelector(".n-root")!.textContent).toBe("Leitung");
  });

  it("Mindmap: Mitte als Wurzel der Liste; eine Kante zu einem schon genannten Knoten steht in Worten", () => {
    card(view([net("mindmap", MIND.knoten, [...MIND.kanten, e("x1", "y", "passt zu")])]));
    expect(document.querySelector(".n-tree > li > .n-name")!.textContent).toBe("Mitte");
    expect(document.querySelectorAll(".n-tree li")).toHaveLength(MIND.knoten.length);
    expect(screen.getByText(", führt auch zu Ast 2 (Beschriftung: passt zu)")).toBeInTheDocument();
  });
});

describe("Kaputte Daten", () => {
  it("leere Knotenliste oder fehlende Felder: kurzer Hinweis statt leerer Fläche", () => {
    card(view([net("ablauf", [], []), { typ: "netz" } as unknown as Block, { typ: "netz", form: "baum", knoten: "x", kanten: null } as unknown as Block,
      { typ: "text", absaetze: ["Bleibt sichtbar."] }]));
    expect(screen.getAllByText("Diagramm kann nicht gezeigt werden.")).toHaveLength(3);
    expect(document.querySelector("svg.n-svg")).toBeNull();
    expect(screen.getByText("Bleibt sichtbar.")).toBeInTheDocument();
  });

  it("Kante zu unbekanntem Knoten und doppelte id: der Rest zeichnet, das Fehlende steht in Worten da", () => {
    card(view([net("ablauf", [k("a", "A"), k("b", "B"), k("a", "Doppelt")], [e("a", "b"), e("a", "zz"), e("qq", "b")])]));
    expect(svg().querySelectorAll(".n-node")).toHaveLength(2);
    expect(svg().querySelectorAll(".n-edge")).toHaveLength(1);
    expect(screen.getByText("Nicht gezeigt: 1 Knoten ohne eindeutige id und 2 Verbindungen zu unbekannten Knoten.")).toBeInTheDocument();
  });

  it("schlimmere Fälle fängt der Baustein oder BlockGuard ab, das Fenster bleibt nie leer", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const broken = [
      { typ: "netz", form: "ablauf", knoten: [null, 5, { id: 3 }], kanten: [null] },
      { typ: "netz", form: "mindmap", knoten: [{ id: "a", text: null, art: "quatsch" }], kanten: [{ von: "a", bis: "a" }] },
      { typ: "netz", form: "kreis", knoten: [{ id: "a", text: "A" }], kanten: "x" },
    ] as unknown as Block[];
    card(view([...broken, { typ: "text", absaetze: ["Bleibt sichtbar."] }]));
    const shown = document.querySelectorAll(".v-net").length + screen.queryAllByRole("alert").length;
    expect(shown).toBe(3);
    expect(screen.getByText("Bleibt sichtbar.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Titel" })).toBeInTheDocument();
    expect(document.body.innerHTML).not.toMatch(/NaN/);
  });
});

describe("Vorführung und Bühne", () => {
  it("parseItem kennt den Baustein netz", () => {
    const v = parseItem({ seq: 1, id: "n", art: "netz", titel: "T", bausteine: [{ typ: "netz" }, { typ: "graph" }] }) as View;
    expect(v.bausteine.map((b) => b.typ)).toEqual(["netz"]);
  });

  it("die drei Beispiele (Ablauf, Baum, Mindmap) zeigen sich ohne Fehlerhinweis, der Ablauf mit Entscheidung, Rückweg und Beschriftungen", () => {
    const fresh = DEMO_VIEWS.map((raw, i) => parseItem({ ...raw, seq: i + 1 }) as View).filter((v) => v.bausteine.some((b) => b.typ === "netz"));
    expect(fresh.map((v) => (v.bausteine[0] as NetBlock).form)).toEqual(["ablauf", "baum", "mindmap"]);
    for (const v of fresh) {
      const r = card(v);
      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.queryByText(/Nicht gezeigt|kann nicht gezeigt/)).toBeNull();
      expect(svg().querySelectorAll(".n-node")).toHaveLength((v.bausteine[0] as NetBlock).knoten.length);
      if ((v.bausteine[0] as NetBlock).form === "ablauf") {
        expect(svg().querySelector(".n-entscheidung")).not.toBeNull();
        expect(svg().querySelectorAll(".n-back")).toHaveLength(1);
        expect(svg().querySelectorAll(".n-label").length).toBeGreaterThanOrEqual(3);
      }
      if ((v.bausteine[0] as NetBlock).form === "mindmap") expect((v.bausteine[0] as NetBlock).knoten.length).toBeGreaterThanOrEqual(12);
      r.unmount();
    }
  });
});

describe("Kein Klick sendet etwas", () => {
  it("Zoom, Einpassen, Verschieben, Tasten, Ziehen und die Liste lassen die gesendeten Nachrichten unverändert und speichern nichts", async () => {
    const store = vi.spyOn(Storage.prototype, "setItem");
    const sock: { current?: MockSocket } = {};
    const loader = async () => ({ client: new ApiClient({ port: 5000, token: TOKEN }, (u) => (sock.current = new MockSocket(u, TOKEN))) });
    render(<App load={loader} />);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    sock.current!.show({ id: "netz", art: "netz", titel: "Ablauf", bausteine: [star("ablauf", 30)] });
    await waitFor(() => screen.getByRole("heading", { name: "Ablauf" }), { timeout: 3000 });
    const pollTypes = new Set(sock.current!.sent.map((m) => (m as { type: string }).type));
    const before = JSON.stringify(sock.current!.sent);

    for (const name of ["Vergrößern", "Verkleinern", "Einpassen", "Nach links", "Nach rechts", "Nach oben", "Nach unten", "Vergrößern", "Nach rechts"]) click(name);
    for (const key of ["+", "-", "0", "Home", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "="]) fireEvent.keyDown(frame(), { key });
    fireEvent.pointerDown(frame(), { clientX: 10, clientY: 10, pointerId: 1 });
    fireEvent.pointerMove(frame(), { clientX: 60, clientY: 30, pointerId: 1 });
    fireEvent.pointerUp(frame(), { pointerId: 1 });
    fireEvent.wheel(frame(), { deltaY: -100, ctrlKey: true });
    fireEvent.click(screen.getByText(/Als Liste zeigen/));

    expect(JSON.stringify(sock.current!.sent)).toBe(before);                              // nichts dazugekommen
    expect(store).not.toHaveBeenCalled();
    await new Promise((r) => setTimeout(r, 1200));                                         // auch später nur die üblichen Abfragen
    const later = sock.current!.sent.map((m) => (m as { type: string }).type);
    expect(later.filter((t) => !pollTypes.has(t))).toEqual([]);
    expect(screen.getByRole("heading", { name: "Ablauf" })).toBeInTheDocument();
  });
});

/** Lesereihenfolge des kleinen Ablaufs (oben nach unten, links nach rechts), aus der echten Anordnung. */
function FLOW_ORDER(item: string): number {
  const l = layoutNet("ablauf", FLOW.knoten.map((n) => ({ ...n, art: n.art || undefined })), FLOW.kanten);
  const order = [...l.boxes].sort((p, q) => p.y - q.y || p.x - q.x).map((b) => FLOW.knoten.find((n) => n.id === b.id)!.text);
  return order.findIndex((t) => item.startsWith(`${t} `));
}
