// Ansichten, die Claude Code über `zeige` schickt (Plan docs/ui-p2-plan.md). Das Backend prüft sie zweimal
// (src/kushim/stage/schema.py); hier nur eine leichte Formprüfung, damit die Oberfläche nie an Fremdem zerbricht.
// Alles bleibt Text: kein HTML, keine Links, keine Bilder.

export type Art = "antwort" | "rechnung" | "markt" | "recherche" | "auftrag" | "mail" | "dokument" | "modell" | "plan" | "lernen" | "netz";
type Cell = string | number;
export type Block =
  | { typ: "text"; absaetze: string[] }
  | { typ: "liste"; punkte: string[]; nummeriert: boolean }
  | { typ: "formel"; tex: string }
  | { typ: "schritte"; schritte: { text: string; tex: string }[] }
  | { typ: "ergebnis"; text: string; tex: string }
  | { typ: "kennzahlen"; werte: { name: string; wert: Cell; einheit: string; aenderung: string; richtung: "" | "auf" | "ab" | "gleich" }[] }
  | { typ: "tabelle"; spalten: string[]; zeilen: Cell[][] }
  | { typ: "diagramm"; form: "linie" | "balken"; x_titel: string; y_titel: string; reihen: { name: string; punkte: [Cell, number][] }[] }
  | { typ: "aussagen" | "widerspruch"; aussagen: { text: string; quellen: number[] }[] }
  | { typ: "quellen"; quellen: { nr: number; titel: string; adresse: string }[] }
  | { typ: "hinweis"; text: string }
  | { typ: "systemzustand" }
  | { typ: "fortschritt"; schritte: { text: string; zustand: "offen" | "laeuft" | "fertig" | "fehler" }[]; hinweis: string }
  | { typ: "aufgaben"; punkte: { text: string; erledigt: boolean }[] }
  | { typ: "zeitplan"; tag: string; termine: { von: string; bis: string; titel: string; ort: string }[] }
  | { typ: "mail"; von: string; an: string; betreff: string; datum: string; zusammenfassung: string; absaetze: string[] }
  | { typ: "mail-entwurf"; an: string; cc: string; betreff: string; absaetze: string[] }
  | { typ: "countdown"; titel: string; ende: string }
  | { typ: "dokument"; name: string; ausschnitt: string; zeilen: string[]; gliederung: string[] }
  | { typ: "szene3d"; einheit: string; hervorheben: string[]; beschriftungen: { objekt: string; text: string }[];
      szenen: { name: string; objekte: ({ form: "linie"; name: string; farbe: string; punkte: [number, number, number][] } | { form: "box" | "kugel" | "zylinder" | "kegel" | "torus" | "ebene"; name: string; farbe: string; masse: number[]; position: [number, number, number]; drehung: [number, number, number] })[] }[] }
  | { typ: "plan2d"; einheit: string; ebenen: string[]; elemente: ({ art: "linie"; ebene: string; von: [number, number]; bis: [number, number] } | { art: "mass"; ebene: string; von: [number, number]; bis: [number, number]; text: string } | { art: "polylinie"; ebene: string; punkte: [number, number][]; geschlossen: boolean } | { art: "rechteck"; ebene: string; x: number; y: number; b: number; h: number } | { art: "kreis"; ebene: string; x: number; y: number; r: number } | { art: "bogen"; ebene: string; x: number; y: number; r: number; von: number; bis: number } | { art: "text"; ebene: string; x: number; y: number; text: string; groesse: number })[] }
  | { typ: "aenderung"; name: string; zusammenfassung: string; bloecke: { kopf: string; zeilen: { art: "gleich" | "neu" | "weg"; text: string }[] }[] }
  // P6a (docs/ui-p6-plan.md): Vergleich, Zeitstrahl, Gegenüberstellung; Lernkarten, Quiz, Anleitung. Indizes zählen ab 0.
  // Das Backend füllt Vorgaben: leere Listen je Option, "" für fehlende Texte, sekunden 0 = kein Timer, aktuell 0.
  | { typ: "vergleich"; optionen: string[]; kriterien: { name: string; werte: Cell[] }[]; vorteile: string[][]; nachteile: string[][]; fazit: string }
  | { typ: "zeitstrahl"; ereignisse: { zeit: string; titel: string; text: string }[]; einheit: string }
  | { typ: "gegenueber"; sprachen: [string, string]; paare: { original: string; uebersetzung: string }[] }
  | { typ: "lernkarten"; karten: { frage: string; antwort: string }[] }
  | { typ: "quiz"; fragen: { frage: string; optionen: string[]; richtig: number; erklaerung: string }[] }
  | { typ: "anleitung"; schritte: { titel: string; text: string; sekunden: number }[]; aktuell: number }
  // P6b: Diagramm aus Knoten und Kanten. `art: ""` heißt „nicht angegeben“ (Schritt), `text: ""` an einer Kante heißt ohne Beschriftung.
  | { typ: "netz"; form: "ablauf" | "baum" | "mindmap"; knoten: { id: string; text: string; art: "" | "start" | "ende" | "entscheidung" | "schritt" }[];
      kanten: { von: string; bis: string; text: string }[] };
export type NetBlock = Extract<Block, { typ: "netz" }>;

export interface View { seq: number; id: string; art: Art; titel: string; stand: string; bausteine: Block[] }
export type StageItem = View | { seq: number; id: string; schliessen: true };

const ARTEN = ["antwort", "rechnung", "markt", "recherche", "auftrag", "mail", "dokument", "modell", "plan", "lernen", "netz"];
const TYPEN = ["text", "liste", "formel", "schritte", "ergebnis", "kennzahlen", "tabelle", "diagramm", "aussagen", "widerspruch",
  "quellen", "hinweis", "systemzustand", "fortschritt", "aufgaben", "zeitplan", "mail", "mail-entwurf", "countdown", "dokument", "aenderung", "szene3d", "plan2d",
  "vergleich", "zeitstrahl", "gegenueber", "lernkarten", "quiz", "anleitung", "netz"];
const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

/** Ein Eintrag aus `stage.get`; `null`, wenn er nicht passt (dann wird er übergangen). */
export function parseItem(raw: unknown): StageItem | null {
  if (!isObj(raw) || typeof raw.seq !== "number" || typeof raw.id !== "string" || raw.id.length > 40) return null;
  if (raw.schliessen === true) return { seq: raw.seq, id: raw.id, schliessen: true };
  if (typeof raw.art !== "string" || !ARTEN.includes(raw.art) || typeof raw.titel !== "string" || !Array.isArray(raw.bausteine)) return null;
  const bausteine = raw.bausteine.filter((b): b is Block => isObj(b) && typeof b.typ === "string" && TYPEN.includes(b.typ)).slice(0, 12);
  return { seq: raw.seq, id: raw.id, art: raw.art as Art, titel: raw.titel.slice(0, 120),
    stand: typeof raw.stand === "string" ? raw.stand.slice(0, 40) : "", bausteine };
}

export const ART_LABEL: Record<Art, string> = { antwort: "Antwort", rechnung: "Rechnung", markt: "Markt", recherche: "Recherche",
  auftrag: "Auftrag", mail: "Mail", dokument: "Datei", modell: "3D-Modell", plan: "Plan", lernen: "Lernen", netz: "Diagramm" };
export const hasSystem = (v: View | null | undefined) => !!v?.bausteine.some((b) => b.typ === "systemzustand");
