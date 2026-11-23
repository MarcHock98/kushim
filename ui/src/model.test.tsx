import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "./App";
import { Model3D } from "./components/stage/Model3D";
import { Plan2D } from "./components/stage/Plan2D";
import { ViewCard } from "./components/stage/ViewCard";
import { ApiClient } from "./lib/api";
import { STATE_VIEW } from "./lib/avatarState";
import { MockSocket } from "./lib/mock";
import {
  allBounds, arcEnds, describeSize, diffScenes, diffText, measureText, objectBounds, planBounds, rotate, type Obj, type PlanBlock, type SceneBlock,
} from "./lib/scene";
import { parseItem, type View } from "./lib/stage";

// 3D-Szene und Plan (Plan docs/ui-p4-plan.md, P4a). Unter jsdom gibt es kein WebGL: der Betrachter zeigt dann Text und Liste.

const TOKEN = "t".repeat(43);
afterEach(cleanup);

const box = (name: string, masse: [number, number, number], position: [number, number, number] = [0, 0, 0], drehung: [number, number, number] = [0, 0, 0]): Obj =>
  ({ form: "box", name, farbe: "arc", masse, position, drehung });
const close = (a: number, b: number) => expect(Math.abs(a - b)).toBeLessThan(1e-9);

const scene = (szenen: SceneBlock["szenen"], extra: Partial<SceneBlock> = {}): SceneBlock =>
  ({ typ: "szene3d", einheit: "cm", hervorheben: [], beschriftungen: [], szenen, ...extra });

describe("Rechenlogik der Szene", () => {
  it("Hüllmaße: Körper an ihrer Position, Zylinder stehen auf y, Linien über ihre Punkte", () => {
    const b = scene([{ name: "s", objekte: [
      box("Brett", [80, 2, 30], [0, 10, 0]),
      { form: "zylinder", name: "Rohr", farbe: "arc", masse: [5, 40], position: [50, 20, 0], drehung: [0, 0, 0] },
      { form: "linie", name: "Achse", farbe: "arc", punkte: [[0, 0, 0], [0, 100, 0]] }] }]);
    const bb = allBounds(b);
    expect(bb.min).toEqual([-40, 0, -15]);
    expect(bb.max).toEqual([55, 100, 15]);
    expect(describeSize(bb, "cm")).toBe("Breite 95 × Höhe 100 × Tiefe 30 cm");
    expect(describeSize(bb, "")).toBe("Breite 95 × Höhe 100 × Tiefe 30 (Einheit unbekannt)");
  });

  it("Drehung: 90 Grad um z macht aus der Breite eine Höhe", () => {
    const o = box("Latte", [100, 2, 4], [0, 0, 0], [0, 0, 90]);
    const bb = objectBounds(o);
    close(bb.max[0] - bb.min[0], 2);
    close(bb.max[1] - bb.min[1], 100);
    const p = rotate([1, 0, 0], [0, 0, 90]);
    close(p[0], 0); close(p[1], 1);
    const q = rotate([0, 1, 0], [90, 0, 0]);
    close(q[1], 0); close(q[2], 1);
  });

  it("Torus, Kugel, Ebene und Kegel haben die richtigen Hüllen", () => {
    expect(objectBounds({ form: "kugel", name: "", farbe: "arc", masse: [5], position: [1, 2, 3], drehung: [0, 0, 0] }).max).toEqual([6, 7, 8]);
    expect(objectBounds({ form: "torus", name: "", farbe: "arc", masse: [5, 1], position: [0, 0, 0], drehung: [0, 0, 0] }).max).toEqual([6, 6, 1]);
    expect(objectBounds({ form: "ebene", name: "", farbe: "arc", masse: [10, 4], position: [0, 0, 0], drehung: [0, 0, 0] }).max).toEqual([5, 2, 0]);
    expect(objectBounds({ form: "kegel", name: "", farbe: "arc", masse: [3, 8], position: [0, 0, 0], drehung: [0, 0, 0] }).min).toEqual([-3, -4, -3]);
  });

  it("Vergleich nennt neu, entfernt und verändert über die Namen, unbenannte Objekte bleiben außen vor", () => {
    const a = [box("A", [1, 1, 1]), box("B", [1, 1, 1]), box("C", [1, 1, 1], [0, 5, 0]), box("", [9, 9, 9])];
    const b = [box("A", [1, 1, 1]), box("C", [1, 1, 1], [0, 9, 0]), box("D", [2, 2, 2]), box("", [7, 7, 7])];
    const d = diffScenes(a, b);
    expect(d).toEqual({ neu: ["D"], weg: ["B"], geaendert: ["C"] });
    expect(diffText(d)).toBe("neu: D; entfernt: B; verändert: C");
    expect(diffText(diffScenes(a, a))).toBe("keine Unterschiede bei benannten Objekten");
  });

  it("Plan: Grenzen, Maßtext rechnet selbst und nennt die Einheit oder ihr Fehlen", () => {
    const els: PlanBlock["elemente"] = [
      { art: "rechteck", ebene: "", x: 0, y: 0, b: 500, h: 400 }, { art: "kreis", ebene: "", x: 100, y: 100, r: 50 },
      { art: "mass", ebene: "", von: [0, -30], bis: [300, 370], text: "" }];
    expect(planBounds(els)).toEqual({ minX: 0, minY: -30, maxX: 500, maxY: 400 });
    expect(measureText(els[2] as Extract<PlanBlock["elemente"][number], { art: "mass" }>, "cm")).toBe("500 cm");
    expect(measureText({ art: "mass", ebene: "", von: [0, 0], bis: [3, 4], text: "" }, "")).toBe("5 (Einheit unbekannt)");
    expect(measureText({ art: "mass", ebene: "", von: [0, 0], bis: [3, 4], text: "Wunschmaß" }, "cm")).toBe("Wunschmaß");
  });

  it("Bogen: Start, Ende und großer Bogen", () => {
    const a = arcEnds(0, 0, 10, 0, 90);
    close(a.start[0], 10); close(a.end[1], 10);
    expect(a.large).toBe(false);
    expect(arcEnds(0, 0, 10, 0, 270).large).toBe(true);
    expect(arcEnds(0, 0, 10, 350, 10).large).toBe(false);                               // über die Nullgrenze
    const arc = (von: number, bis: number) => planBounds([{ art: "bogen", ebene: "", x: 0, y: 0, r: 10, von, bis }]);
    expect(arc(0, 90)).toEqual({ minX: expect.closeTo(0, 9), minY: expect.closeTo(0, 9), maxX: 10, maxY: 10 });   // Viertelkreis, nicht der ganze Kreis
    expect(arc(350, 10).maxX).toBe(10);                                                    // über die Nullgrenze
    expect(arc(0, 270).minY).toBe(-10);                                                    // großer Bogen schließt den unteren Punkt ein
  });
});

const view = (b: View["bausteine"][number], art: View["art"]): View => ({ seq: 1, id: "v1", art, titel: "T", stand: "", bausteine: [b] });
const card = (v: View) => render(<ViewCard view={v} sys={null} sysNo={false} onClose={() => undefined} />);

const SHELF = scene([
  { name: "vorher", objekte: [box("Seite", [2, 180, 30], [-39, 90, 0]), box("Boden 3", [76, 2, 30], [0, 118, 0])] },
  { name: "nachher", objekte: [box("Seite", [2, 180, 30], [-39, 90, 0]), box("Boden 3", [76, 2, 30], [0, 130, 0]), box("Boden 4", [76, 2, 30], [0, 178, 0])] }],
  { hervorheben: ["Boden 4"], beschriftungen: [{ objekt: "Boden 4", text: "neu: oberster Boden" }] });

describe("3D-Szene ohne WebGL (jsdom)", () => {
  it("sagt ehrlich, dass WebGL fehlt, und zeigt Maße, Unterschiede in Worten und die Objektliste", () => {
    card(view(SHELF, "modell"));
    const m = screen.getByRole("region", { name: /3D-Szene: vorher, nachher\. Breite 78 × Höhe 180 × Tiefe 30 cm/ });
    expect(within(m).getByText(/3D braucht WebGL/)).toBeInTheDocument();
    expect(within(m).queryByRole("img")).toBeNull();                                      // kein leeres Bild
    expect(within(m).getByText(/neu: Boden 4; verändert: Boden 3/)).toBeInTheDocument();
    const rows = within(m).getAllByRole("row").slice(1).map((r) => r.textContent);
    expect(rows).toHaveLength(5);
    expect(rows.some((r) => r?.includes("Boden 4") && r.includes("neu: oberster Boden"))).toBe(true);
    expect(m.querySelector("script, a, img, [href]")).toBeNull();
  });

  it("Szenen lassen sich wählen und überblenden; ein Regler reicht auch ohne Maus", () => {
    card(view(SHELF, "modell"));
    const radios = screen.getAllByRole("radio");
    expect(radios.map((r) => (r as HTMLInputElement).checked)).toEqual([false, true]);       // zuerst die letzte (nachher)
    fireEvent.click(radios[0]);
    expect((screen.getAllByRole("radio")[0] as HTMLInputElement).checked).toBe(true);
    const slider = screen.getByLabelText("Überblenden zwischen den Szenen") as HTMLInputElement;
    expect(slider.min).toBe("0"); expect(slider.max).toBe("1");
    fireEvent.change(slider, { target: { value: "0.7" } });
    expect((screen.getAllByRole("radio")[1] as HTMLInputElement).checked).toBe(true);        // über die Mitte gerundet
  });

  it("eine einzelne Szene hat weder Auswahl noch Vergleich; unbenannte Objekte stehen als Strich in der Liste", () => {
    card(view(scene([{ name: "jetzt", objekte: [box("", [1, 1, 1])] }], { einheit: "" }), "modell"));
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByLabelText("Unterschiede zwischen den Szenen")).toBeNull();
    expect(screen.getByText(/Einheit unbekannt/)).toBeInTheDocument();
    expect(screen.getAllByRole("cell").some((c) => c.textContent === "–")).toBe(true);
  });

  it("Namen aus Claude bleiben Text", () => {
    card(view(scene([{ name: "<b>x</b>", objekte: [box("<img src=x onerror=alert(1)>", [1, 1, 1])] }]), "modell"));
    expect(document.querySelector(".v-model b, .v-model img")).toBeNull();
    expect(screen.getAllByText(/<img src=x onerror=alert\(1\)>/).length).toBeGreaterThan(0);
  });

  it("der Betrachter baut sich selbst nie ohne WebGL auf (kein Canvas)", () => {
    const { container } = render(<Model3D b={SHELF} />);
    expect(container.querySelector("canvas")).toBeNull();
  });
});

const PLAN: PlanBlock = { typ: "plan2d", einheit: "cm", ebenen: ["Wände", "Möbel", "Maße"], elemente: [
  { art: "rechteck", ebene: "Wände", x: 0, y: 0, b: 500, h: 400 },
  { art: "linie", ebene: "Wände", von: [200, 0], bis: [200, 120] },
  { art: "bogen", ebene: "Wände", x: 200, y: 0, r: 90, von: 0, bis: 90 },
  { art: "kreis", ebene: "Möbel", x: 380, y: 200, r: 55 },
  { art: "polylinie", ebene: "Möbel", punkte: [[10, 10], [60, 10], [60, 50]], geschlossen: true },
  { art: "text", ebene: "Möbel", x: 345, y: 195, text: "<b>Tisch</b>", groesse: 0 },
  { art: "mass", ebene: "Maße", von: [0, -30], bis: [500, -30], text: "" },
  { art: "linie", ebene: "", von: [0, 0], bis: [1, 1] }] };

describe("Plan", () => {
  it("zeichnet jedes Element als eigenes SVG-Element; Texte und Maße als Text", () => {
    const { container } = render(<Plan2D b={PLAN} />);
    const svg = screen.getByRole("img", { name: /Plan: 8 Elemente in 4 Ebenen, Breite 500, Höhe 430 cm/ });
    expect(svg.querySelectorAll("rect")).toHaveLength(1);
    expect(svg.querySelectorAll("circle")).toHaveLength(1);
    expect(svg.querySelectorAll("polygon")).toHaveLength(1);
    expect(svg.querySelectorAll("path")).toHaveLength(1);
    expect(svg.querySelectorAll("text")).toHaveLength(2);
    expect(within(svg as unknown as HTMLElement).getByText("500 cm")).toBeInTheDocument();                // selbst gerechnete Länge
    expect(within(svg as unknown as HTMLElement).getByText("<b>Tisch</b>")).toBeInTheDocument();          // Text bleibt Text
    expect(container.querySelector("b, script, a, image, foreignObject, [href]")).toBeNull();
    expect(svg.outerHTML).not.toMatch(/NaN|Infinity/);
  });

  it("Ebenen lassen sich ausblenden und einblenden; die Zahl der Elemente steht dabei", () => {
    render(<Plan2D b={PLAN} />);
    const walls = screen.getByRole("checkbox", { name: /Wände/ });
    expect(screen.getByRole("checkbox", { name: /Wände \(3\)/ })).toBeInTheDocument();
    const svg = screen.getByRole("img", { name: /Plan:/ });
    fireEvent.click(walls);
    expect(svg.querySelectorAll("rect")).toHaveLength(0);
    expect(svg.querySelectorAll("circle")).toHaveLength(1);
    fireEvent.click(walls);
    expect(svg.querySelectorAll("rect")).toHaveLength(1);
    expect(screen.getByRole("checkbox", { name: /\(ohne Ebene\)/ })).toBeInTheDocument();
  });

  it("Ebenen unterscheiden sich in Farbe und Strichart, nicht nur in der Farbe", () => {
    render(<Plan2D b={PLAN} />);
    const svg = screen.getByRole("img", { name: /Plan:/ });
    const rect = svg.querySelector("rect")!, circle = svg.querySelector("circle")!;
    expect(rect.getAttribute("stroke")).not.toBe(circle.getAttribute("stroke"));
    expect(rect.getAttribute("stroke-dasharray")).not.toBe(circle.getAttribute("stroke-dasharray"));
  });

  it("Knöpfe zoomen und verschieben die Ansicht, Zurücksetzen stellt sie wieder her", () => {
    render(<Plan2D b={PLAN} />);
    const svg = screen.getByRole("img", { name: /Plan:/ });
    const vb = () => svg.getAttribute("viewBox")!.split(" ").map(Number);
    const start = vb();
    fireEvent.click(screen.getByRole("button", { name: "Näher" }));
    expect(vb()[2]).toBeLessThan(start[2]);
    fireEvent.click(screen.getByRole("button", { name: "Nach links" }));
    expect(vb()[0]).not.toBe(start[0]);
    fireEvent.click(screen.getByRole("button", { name: "Ansicht zurücksetzen" }));
    expect(vb()).toEqual(start);
    fireEvent.keyDown(screen.getByLabelText(/Plan-Ansicht/), { key: "+" });
    expect(vb()[2]).toBeLessThan(start[2]);
  });

  it("ein einzelner Punkt oder eine Linie zeichnet ohne NaN", () => {
    render(<Plan2D b={{ typ: "plan2d", einheit: "", ebenen: [], elemente: [{ art: "text", ebene: "", x: 5, y: 5, text: "Hier", groesse: 0 }] }} />);
    const svg = screen.getByRole("img", { name: /Plan:/ });
    expect(svg.outerHTML).not.toMatch(/NaN|Infinity/);
    expect(screen.getByText(/Einheit unbekannt/, { selector: "p *, p" })).toBeInTheDocument();
  });
});

describe("Formprüfung und Bühne", () => {
  it("kennt die Arten modell und plan und beide Bausteine", () => {
    const v = parseItem({ seq: 1, id: "m", art: "modell", titel: "T", bausteine: [{ typ: "szene3d" }, { typ: "plan2d" }, { typ: "skript" }] }) as View;
    expect(v.art).toBe("modell");
    expect(v.bausteine.map((b) => b.typ)).toEqual(["szene3d", "plan2d"]);
    expect((parseItem({ seq: 1, id: "p", art: "plan", titel: "T", bausteine: [] }) as View).art).toBe("plan");
  });

  it("ein Plan erscheint auf der Bühne wie jede andere Ansicht", async () => {
    const sock: { current?: MockSocket } = {};
    const loader = async () => ({ client: new ApiClient({ port: 5000, token: TOKEN }, (u) => (sock.current = new MockSocket(u, TOKEN))) });
    const app = <App load={loader} />;
    const { rerender } = render(app);
    await waitFor(() => screen.getAllByText(STATE_VIEW.idle.label));
    sock.current!.show({ id: "plan", art: "plan", titel: "Grundriss", bausteine: [PLAN] });
    await waitFor(() => screen.getByRole("img", { name: /Plan: 8 Elemente/ }), { timeout: 3000 });
    expect(screen.getByRole("heading", { name: "Grundriss" })).toBeInTheDocument();
    // Die Ansicht kam aus einer Abfrage (außerhalb von act): waitFor sieht den Commit, bevor React dessen useEffect ausführt,
    // und erst dort hängt der Esc-Listener. React führt offene Effekte vor jeder neuen Arbeit aus: dasselbe Element neu geben.
    rerender(app);
    await act(async () => { fireEvent.keyDown(window, { key: "Escape" }); });
    expect(screen.queryByRole("img", { name: /Plan:/ })).toBeNull();
  });
});


describe("Absicherung gegen kaputte Bausteine", () => {
  it("ein Baustein, der beim Zeichnen scheitert, zeigt einen Hinweis; die übrigen Bausteine bleiben", () => {
    const broken = { typ: "szene3d", einheit: "", hervorheben: [], beschriftungen: [], szenen: [{ name: "s", objekte: [{ form: "box", name: "x", farbe: "arc", masse: [1, 1, 1] }] }] };
    const v: View = { seq: 1, id: "v", art: "modell", titel: "T", stand: "", bausteine: [
      { typ: "hinweis", text: "Bleibt sichtbar." }, broken as unknown as View["bausteine"][number], { typ: "hinweis", text: "Auch das." }] };
    const log = console.error;
    console.error = () => undefined;                                   // React meldet den abgefangenen Fehler laut
    try { card(v); } finally { console.error = log; }
    expect(screen.getByText("Bleibt sichtbar.")).toBeInTheDocument();
    expect(screen.getByText("Auch das.")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("konnte nicht angezeigt werden");
  });
});
