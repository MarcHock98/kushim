// Gefälschtes Backend für Entwicklung und Tests (kein Netz). Antwortet wie `ApiCore`: Token zuerst, neutrale Fehler.
import type { Socket } from "./api";

export class MockSocket implements Socket {
  onmessage: Socket["onmessage"] = null;
  onclose: Socket["onclose"] = null;
  onopen: Socket["onopen"] = null;
  onerror: Socket["onerror"] = null;
  kill = false;
  voice: { active: boolean; state: string; level: number } = { active: false, state: "idle", level: 0 };
  pending: { request_id: string; tool_name: string; description: string; input_preview: string; digest: string; summary: string;
    truncated?: boolean }[] = [];
  entries: { id: number; heard: string; reply: string; outcome: string }[] = [];
  folders: string[] = [];
  overview: Record<string, unknown> = {
    kill: false, tools_active: [], vault: { where: "local", exists: true, open: true },
    backup: { configured: true, age_days: 2 }, money_limit_eur: 0, audit: [],
  };
  facts: { id: number; text: string; kind: string; source: string; created: number }[] = [];
  deleted: number[] = [];
  system: Record<string, unknown> | null = {          // Beispielwerte; null = Dienst kennt system.stats nicht
    cpu: { percent: 34 }, memory: { percent: 61, used_gb: 9.8, total_gb: 16 },
    gpu: { percent: 22, vram_used_mb: 3100, vram_total_mb: 8192, temp_c: 58 },
    disk: { percent: 41, used_gb: 412, total_gb: 1000 }, battery: { present: false, percent: null, on_ac: null },
    net: { down_mbit: 42.1, up_mbit: 8.3 }, system: { os: "Windows 11", uptime_s: 568800 }, warn_at: 80,
  };
  stage: Record<string, unknown>[] = [];                // Ansichten wie von Claude über `zeige` (mit seq)
  stageSeq = 0;
  /** Wie Claudes Werkzeug `zeige`: legt eine Ansicht ab, die die Oberfläche über stage.get abholt. */
  show(view: Record<string, unknown>): void {
    this.stageSeq += 1;
    this.stage = [...this.stage.filter((v) => v.id !== view.id), { ...view, seq: this.stageSeq }];
  }
  dash: Record<string, unknown> = { timers: [], tasks: [], pending_approvals: 0, results: [] };
  folderProposal: { name: string; path: string } | null = null;
  rated = new Set<number>();
  ratings: { entry: number; rating: number }[] = [];
  sent: unknown[] = [];

  constructor(public url: string, private token = "t".repeat(43), private fail = false) {
    queueMicrotask(() => (this.fail ? this.onerror?.() : this.onopen?.()));
  }

  /** Vorführung im Browser (`?mock&demo`): erst ein reines Gespräch (Kern bleibt groß), dann zeigt „Claude“ der Reihe nach
   *  Rechnung, Markt, Recherche und Systemzustand. Nur Mock, Beispieldaten. */
  demo(): void {
    const turn = (at: number, heard: string, reply: string, view?: Record<string, unknown>) => {
      const steps: [string, number][] = [["listening", 0.6], ["thinking", 0], ["speaking", 0.7], ["idle", 0]];
      steps.forEach(([state, level], i) => setTimeout(() => {
        this.voice = { active: true, state, level };
        if (state === "speaking") {
          this.entries.push({ id: this.entries.length + 1, heard, reply, outcome: "spoken" });
          if (view) this.show(view);
        }
      }, at + i * 2500));
    };
    turn(2000, "Wie wird das Wetter morgen?", "Morgen 11 Grad, ab Nachmittag leichter Regen.");
    turn(13000, "Löse x² minus 5x plus 6 gleich 0.", "Die Lösungen sind 2 und 3.", DEMO_VIEWS[0]);
    turn(24000, "Wie steht der DAX?", "Der DAX liegt bei 19.420 Punkten.", DEMO_VIEWS[1]);
    turn(35000, "Was weiß man über Koffein und Schlaf?", "Ich habe drei Quellen zusammengefasst.", DEMO_VIEWS[2]);
    turn(46000, "Wie ist die Systemauslastung?", "Ich zeige dir den Systemzustand.", DEMO_VIEWS[3]);
    turn(57000, "Mach die Tests grün und plane meinen Dienstag.", "Ich arbeite den Plan ab.", {
      ...DEMO_VIEWS[4], bausteine: [...(DEMO_VIEWS[4].bausteine as unknown[]),
        { typ: "countdown", titel: "Tee zieht", ende: new Date(Date.now() + 4 * 60000).toISOString() }] });
    turn(68000, "Was schreibt Anna, und antworte ihr.", "Hier die Mail und mein Entwurf.", DEMO_VIEWS[5]);
    turn(79000, "Lies mir rechnen.py und gib mir eine Übersicht.", "Zwei Funktionen, neu ist die Prüfung auf leere Eingaben.", DEMO_VIEWS[6]);
    turn(90000, "Zeig mir das Regal in 3D, vorher und nachher.", "Hier ist das Regal, der neue Boden ist hervorgehoben.", DEMO_VIEWS[7]);
    turn(101000, "Zeichne den Grundriss vom Wohnzimmer.", "Hier ist der Grundriss mit Maßen.", DEMO_VIEWS[8]);
    turn(112000, "Bahn oder Auto nach Hamburg?", "Hier der Vergleich.", DEMO_VIEWS[9]);
    turn(123000, "Wie ging die Geschichte des Buchdrucks?", "Hier die wichtigsten Daten.", DEMO_VIEWS[10]);
    turn(134000, "Übersetze mir ein paar Sätze ins Arabische.", "Hier sind die Sätze.", DEMO_VIEWS[11]);
    turn(145000, "Ich will Hauptstädte üben.", "Hier sind Karten und ein kurzes Quiz.", DEMO_VIEWS[12]);
    turn(156000, "Wie backe ich Pfannkuchen?", "Hier die Anleitung Schritt für Schritt.", DEMO_VIEWS[13]);
    turn(167000, "Wie läuft eine Bestellung ab?", "Hier der Ablauf.", DEMO_VIEWS[14]);
    turn(178000, "Zeig mir den Aufbau der Firma.", "Hier das Organigramm.", DEMO_VIEWS[15]);
    turn(189000, "Sammle Ideen für den Urlaub.", "Hier die Mindmap.", DEMO_VIEWS[16]);
    turn(200000, "Zeig mir, wie ein Pendel schwingt.", "Hier ein Pendel mit einem Meter Länge.", DEMO_VIEWS[17]);
    turn(211000, "Wie fliegt ein schräg geworfener Ball?", "Hier der Wurf unter 45 Grad.", DEMO_VIEWS[18]);
    turn(222000, "Wie bewegen sich Teilchen in einem Gas?", "Hier ein Gas mit 60 Teilchen.", DEMO_VIEWS[19]);
  }

  send(data: string): void {
    const msg = JSON.parse(data) as { type?: string; token?: string };
    this.sent.push(msg);
    let reply: unknown;
    if (msg.token !== this.token) reply = { ok: false, error: "unauthorized" };
    else if (msg.type === "safety.status") reply = { ok: true, kill: this.kill };
    else if (msg.type === "voice.state") reply = { ok: true, ...this.voice };
    else if (msg.type === "transcript.get") {
      const since = (msg as { since?: number }).since ?? 0;
      const entries = this.entries.filter((e) => e.id > since);
      reply = { ok: true, entries, last: entries.length ? entries[entries.length - 1].id : since };
    }
    else if (msg.type === "safety.overview") reply = { ok: true, ...this.overview, kill: this.kill };
    else if (msg.type === "memory.search") {
      const q = ((msg as { query?: string }).query ?? "").toLowerCase();
      reply = { ok: true, facts: this.facts.filter((f) => !this.deleted.includes(f.id) && f.text.toLowerCase().includes(q)) };
    }
    else if (msg.type === "memory.update") {
      const m = msg as { id?: number; text?: string; kind?: string; confirm?: boolean };
      const f = this.facts.find((x) => x.id === m.id);
      if (m.confirm !== true) reply = { ok: false, error: "confirm_required" };
      else if (!f) reply = { ok: false, error: "not_found" };
      else { f.text = m.text ?? f.text; f.kind = m.kind ?? f.kind; f.source = "user"; reply = { ok: true, updated: m.id }; }
    }
    else if (msg.type === "memory.delete") {
      const m = msg as { id?: number; confirm?: boolean };
      if (m.confirm !== true) reply = { ok: false, error: "confirm_required" };
      else { this.deleted.push(m.id ?? -1); reply = { ok: true, deleted: m.id }; }
    }
    else if (msg.type === "system.stats" && this.system) reply = { ok: true, ...this.system };
    else if (msg.type === "stage.get") {
      const since = (msg as { since?: number }).since ?? 0;
      reply = { ok: true, items: this.kill ? [] : this.stage.filter((v) => (v.seq as number) > since), last: this.stageSeq };
    }
    else if (msg.type === "dashboard.get") reply = { ok: true, ...this.dash };
    else if (msg.type === "claude.folder_list") reply = { ok: true, folders: this.folders.map((n) => ({ name: n, path: `C:/proj/${n}` })) };
    else if (msg.type === "claude.folder_propose") {
      const m = msg as { name?: string; path?: string };
      if (m.path === "C:/Windows") reply = { ok: true, allowed: false, reason: "Dieser Ordner liegt in einem geschützten Bereich (System, AppData, .ssh, .claude)." };
      else { this.folderProposal = { name: m.name ?? "", path: m.path ?? "" }; reply = { ok: true, allowed: true, proposal: "f1", name: m.name, preview: `Claude darf in «${m.path}» arbeiten (Name «${m.name}»)`, expires_in: 120 }; }
    }
    else if (msg.type === "claude.folder_confirm") {
      const m = msg as { proposal?: string; confirm?: boolean };
      if (m.confirm !== true) reply = { ok: false, error: "confirm_required" };
      else if (m.proposal !== "f1" || !this.folderProposal) reply = { ok: false, error: "unknown_proposal" };
      else { this.folders.push(this.folderProposal.name); this.folderProposal = null; reply = { ok: true, folders: this.folders.map((n) => ({ name: n, path: "x" })) }; }
    }
    else if (msg.type === "claude.folder_deny") { this.folderProposal = null; reply = { ok: true, denied: true }; }
    else if (msg.type === "claude.folder_remove") {
      const n = (msg as { name?: string }).name ?? "";
      this.folders = this.folders.filter((x) => x !== n);
      reply = { ok: true, folders: this.folders.map((x) => ({ name: x, path: "x" })) };
    }
    else if (msg.type === "feedback.add") {
      const m = msg as { entry?: number; rating?: number };
      if (this.rated.has(m.entry ?? -1)) reply = { ok: false, error: "already_rated" };
      else { this.rated.add(m.entry ?? -1); this.ratings.push({ entry: m.entry ?? -1, rating: m.rating ?? 0 }); reply = { ok: true, rated: m.entry, rating: m.rating }; }
    }
    else if (msg.type === "approvals.get") reply = { ok: true, pending: this.pending };
    else if (msg.type === "approvals.decide") {
      const m = msg as { request_id?: string; digest?: string; approve?: boolean; confirm?: boolean };
      const p = this.pending.find((x) => x.request_id === m.request_id);
      if (this.kill) reply = { ok: false, error: "kill" };
      else if (!p) reply = { ok: false, error: "none" };
      else if (m.digest !== p.digest) reply = { ok: false, error: "stale" };
      else if (m.approve && m.confirm !== true) reply = { ok: false, error: "confirm_required" };
      else { this.pending = this.pending.filter((x) => x !== p); reply = { ok: true, result: m.approve ? "allow" : "deny" }; }
    }
    else if (msg.type === "safety.kill") { this.kill = true; reply = { ok: true, kill: true }; }
    else if (msg.type === "safety.resume") reply = { ok: true, kill: (this.kill = false) };
    else reply = { ok: false, error: "unknown_type" };
    queueMicrotask(() => this.onmessage?.({ data: JSON.stringify(reply) }));
  }

  close(): void { queueMicrotask(() => this.onclose?.()); }
}

/** Beispiel-Ansichten für die Vorführung (erfundene Beispielwerte, nur im Mock). */
export const DEMO_VIEWS: Record<string, unknown>[] = [
  { id: "mathe-1", art: "rechnung", titel: "Quadratische Gleichung", bausteine: [
    { typ: "formel", tex: "x^2 - 5x + 6 = 0" },
    { typ: "schritte", schritte: [
      { text: "Mitternachtsformel mit a = 1, b = -5, c = 6", tex: "x_{1,2} = \\frac{5 \\pm \\sqrt{25 - 24}}{2}" },
      { text: "Wurzel ausrechnen", tex: "x_{1,2} = \\frac{5 \\pm 1}{2}" },
      { text: "Beide Lösungen", tex: "x_1 = 3,\\quad x_2 = 2" } ] },
    { typ: "ergebnis", tex: "x \\in \\{2,\\, 3\\}" } ] },
  { id: "dax", art: "markt", titel: "DAX heute (Beispielwerte)", stand: "12.11.2026 14:05", bausteine: [
    { typ: "kennzahlen", werte: [
      { name: "DAX", wert: 19420.5, einheit: "Pkt", aenderung: "+0,8 %", richtung: "auf" },
      { name: "MDAX", wert: 26110, einheit: "Pkt", aenderung: "-0,3 %", richtung: "ab" },
      { name: "Euro in Dollar", wert: 1.0721, aenderung: "±0,0 %", richtung: "gleich" } ] },
    { typ: "diagramm", form: "linie", x_titel: "Uhrzeit", y_titel: "Punkte", reihen: [
      { name: "DAX", punkte: [["09:00", 19260], ["10:00", 19310], ["11:00", 19280], ["12:00", 19350], ["13:00", 19390], ["14:00", 19420.5]] } ] },
    { typ: "tabelle", spalten: ["Titel", "Kurs", "Änderung"], zeilen: [["SAP", 231.4, "+1,9 %"], ["Siemens", 188, "+0,6 %"], ["BASF", 44.1, "-1,2 %"]] } ] },
  { id: "koffein", art: "recherche", titel: "Koffein und Schlaf", bausteine: [
    { typ: "text", absaetze: ["Kurz: Koffein am Nachmittag kann den Schlaf verkürzen; wie stark, ist von Mensch zu Mensch verschieden."] },
    { typ: "aussagen", aussagen: [
      { text: "Koffein wirkt mehrere Stunden nach.", quellen: [1, 2] },
      { text: "Später Konsum verkürzt bei vielen die Schlafdauer.", quellen: [1, 3] } ] },
    { typ: "widerspruch", aussagen: [{ text: "Wie viele Stunden Abstand nötig sind, geben die Quellen unterschiedlich an.", quellen: [2, 3] }] },
    { typ: "quellen", quellen: [
      { nr: 1, titel: "Übersichtsarbeit (Beispiel)", adresse: "beispiel.org/schlaf" },
      { nr: 2, titel: "Ratgeber (Beispiel)", adresse: "beispiel.org/koffein" },
      { nr: 3, titel: "Studie (Beispiel)" } ] } ] },
  { id: "system", art: "antwort", titel: "Systemzustand", bausteine: [{ typ: "systemzustand" }] },
  { id: "auftrag", art: "auftrag", titel: "Tests grün machen (Beispiel)", bausteine: [
    { typ: "fortschritt", hinweis: "Zwei Tests sind noch rot.", schritte: [
      { text: "Tests laufen lassen", zustand: "fertig" }, { text: "Ursache im Schema finden", zustand: "fertig" },
      { text: "Fehler beheben", zustand: "laeuft" }, { text: "Alte Ausgabe löschen", zustand: "fehler" },
      { text: "Committen", zustand: "offen" } ] },
    { typ: "zeitplan", tag: "Dienstag, 17. November", termine: [
      { von: "09:00", bis: "10:00", titel: "Team-Runde", ort: "Büro" }, { von: "09:30", bis: "11:00", titel: "Zahnarzt", ort: "" },
      { von: "13:00", bis: "14:30", titel: "Projektplanung", ort: "Video" } ] },
    { typ: "aufgaben", punkte: [{ text: "Milch kaufen", erledigt: true }, { text: "Paket abholen", erledigt: false }] } ] },
  { id: "mail", art: "mail", titel: "Mail von Anna (Beispiel)", bausteine: [
    { typ: "mail", von: "Anna Beispiel <anna@beispiel.org>", an: "", betreff: "Treffen am Dienstag", datum: "12.11.2026 09:14",
      zusammenfassung: "Anna fragt, ob das Treffen am Dienstag um 13 Uhr passt.",
      absaetze: ["Hallo,", "passt dir Dienstag um 13 Uhr für die Projektplanung? Ich würde den Raum buchen.", "Viele Grüße, Anna"] },
    { typ: "mail-entwurf", an: "anna@beispiel.org", cc: "", betreff: "Re: Treffen am Dienstag",
      absaetze: ["Hallo Anna,", "Dienstag um 13 Uhr passt. Bitte buch den Raum.", "Viele Grüße"] } ] },
  { id: "datei", art: "dokument", titel: "Übersicht: rechnen.py (Beispiel)", bausteine: [
    { typ: "text", absaetze: ["Die Datei hat zwei Funktionen: eine rechnet, eine formatiert. Neu gegenüber gestern ist nur die Prüfung auf leere Eingaben."] },
    { typ: "dokument", name: "src/rechnen.py", ausschnitt: "Zeilen 1 bis 12", gliederung: ["rechne(a, b)", "formatiere(wert)"], zeilen: [
      "def rechne(a, b):", "    if a is None or b is None:", "        return 0", "    return max(a, b)", "",
      "def formatiere(wert):", "    return f\"{wert:.2f}\"", "", "if __name__ == \"__main__\":", "    print(formatiere(rechne(2, 3)))" ] },
    { typ: "aenderung", name: "src/rechnen.py", zusammenfassung: "Leere Eingaben liefern jetzt 0 statt eines Fehlers.", bloecke: [
      { kopf: "rechne", zeilen: [
        { art: "gleich", text: "def rechne(a, b):" }, { art: "neu", text: "    if a is None or b is None:" },
        { art: "neu", text: "        return 0" }, { art: "weg", text: "    return a + b" }, { art: "neu", text: "    return max(a, b)" } ] } ] } ] },
  { id: "regal", art: "modell", titel: "Regal, vorher und nachher (Beispiel)", bausteine: [
    { typ: "szene3d", einheit: "cm", hervorheben: ["Boden 4", "Boden 3"], beschriftungen: [{ objekt: "Boden 4", text: "neu: oberster Boden" }, { objekt: "Rückwand", text: "neu: stabilisiert" }], szenen: [
      { name: "vorher", objekte: [
        { form: "box", name: "Seite links", masse: [2, 180, 30], position: [-39, 90, 0], drehung: [0, 0, 0], farbe: "text" },
        { form: "box", name: "Seite rechts", masse: [2, 180, 30], position: [39, 90, 0], drehung: [0, 0, 0], farbe: "text" },
        { form: "box", name: "Boden 1", masse: [76, 2, 30], position: [0, 2, 0], drehung: [0, 0, 0], farbe: "amber" },
        { form: "box", name: "Boden 2", masse: [76, 2, 30], position: [0, 60, 0], drehung: [0, 0, 0], farbe: "amber" },
        { form: "box", name: "Boden 3", masse: [76, 2, 30], position: [0, 118, 0], drehung: [0, 0, 0], farbe: "amber" } ] },
      { name: "nachher", objekte: [
        { form: "box", name: "Seite links", masse: [2, 180, 30], position: [-39, 90, 0], drehung: [0, 0, 0], farbe: "text" },
        { form: "box", name: "Seite rechts", masse: [2, 180, 30], position: [39, 90, 0], drehung: [0, 0, 0], farbe: "text" },
        { form: "box", name: "Boden 1", masse: [76, 2, 30], position: [0, 2, 0], drehung: [0, 0, 0], farbe: "amber" },
        { form: "box", name: "Boden 2", masse: [76, 2, 30], position: [0, 60, 0], drehung: [0, 0, 0], farbe: "amber" },
        { form: "box", name: "Boden 3", masse: [76, 2, 30], position: [0, 130, 0], drehung: [0, 0, 0], farbe: "amber" },
        { form: "box", name: "Boden 4", masse: [76, 2, 30], position: [0, 178, 0], drehung: [0, 0, 0], farbe: "arc" },
        { form: "box", name: "Rückwand", masse: [76, 176, 1], position: [0, 90, -15], drehung: [0, 0, 0], farbe: "gedaempft" } ] } ] } ] },
  { id: "grundriss", art: "plan", titel: "Grundriss Wohnzimmer (Beispiel)", bausteine: [
    { typ: "plan2d", einheit: "cm", ebenen: ["Wände", "Möbel", "Maße"], elemente: [
      { art: "rechteck", ebene: "Wände", x: 0, y: 0, b: 500, h: 400 },
      { art: "linie", ebene: "Wände", von: [200, 0], bis: [200, 120] },
      { art: "bogen", ebene: "Wände", x: 200, y: 0, r: 90, von: 0, bis: 90 },
      { art: "rechteck", ebene: "Möbel", x: 30, y: 250, b: 200, h: 90 },
      { art: "kreis", ebene: "Möbel", x: 380, y: 200, r: 55 },
      { art: "text", ebene: "Möbel", x: 60, y: 285, text: "Sofa" },
      { art: "text", ebene: "Möbel", x: 345, y: 195, text: "Tisch" },
      { art: "mass", ebene: "Maße", von: [0, -30], bis: [500, -30] },
      { art: "mass", ebene: "Maße", von: [530, 0], bis: [530, 400], text: "4 m (Wunsch)" } ] } ] },
  // P6a: Vergleich, Zeitstrahl, Gegenüberstellung, Lernkarten, Quiz, Anleitung (vollständig wie nach der Backend-Prüfung)
  { id: "vergleich", art: "antwort", titel: "Bahn oder Auto nach Hamburg (Beispiel)", bausteine: [
    { typ: "vergleich", optionen: ["Bahn", "Auto", "Fernbus"], kriterien: [
      { name: "Fahrzeit", werte: ["3:40 h", "4:50 h", "6:10 h"] },
      { name: "Kosten in Euro", werte: [59.9, 92, 24.99] },
      { name: "Arbeiten unterwegs", werte: ["gut", "nein", "eingeschränkt"] } ],
      vorteile: [["schnell", "arbeiten möglich"], ["flexibel vor Ort"], ["günstig"]],
      nachteile: [["Verspätungen möglich"], ["Stau", "Parkplatzsuche"], []],
      fazit: "Für eine Tagesreise allein ist die Bahn am bequemsten." } ] },
  { id: "zeitstrahl", art: "recherche", titel: "Geschichte des Buchdrucks (Beispiel)", bausteine: [
    { typ: "zeitstrahl", einheit: "Jahren nach Christus", ereignisse: [
      { zeit: "um 1450", titel: "Gutenberg druckt mit beweglichen Lettern", text: "In Mainz entsteht ein Verfahren mit Metall-Lettern." },
      { zeit: "1455", titel: "Gutenberg-Bibel fertig", text: "" },
      { zeit: "1501", titel: "Ende der Inkunabelzeit", text: "Frühdrucke bis 1500 heißen Inkunabeln." },
      { zeit: "1811", titel: "Schnellpresse von Koenig", text: "Dampfbetrieben, viel schneller als die Handpresse." } ] } ] },
  { id: "uebersetzung", art: "antwort", titel: "Sätze für die Reise (Beispiel)", bausteine: [
    { typ: "gegenueber", sprachen: ["Deutsch", "Arabisch"], paare: [
      { original: "Guten Morgen", uebersetzung: "صباح الخير" },
      { original: "Danke", uebersetzung: "شكرا" },
      { original: "Wo ist der Bahnhof?", uebersetzung: "أين محطة القطار؟" } ] } ] },
  { id: "lernen", art: "lernen", titel: "Hauptstädte üben (Beispiel)", bausteine: [
    { typ: "lernkarten", karten: [
      { frage: "Hauptstadt von Portugal?", antwort: "Lissabon" },
      { frage: "Hauptstadt von Kanada?", antwort: "Ottawa" },
      { frage: "Hauptstadt von Australien?", antwort: "Canberra" } ] },
    { typ: "quiz", fragen: [
      { frage: "Welche Stadt ist die Hauptstadt der Schweiz?", optionen: ["Zürich", "Bern", "Genf"], richtig: 1,
        erklaerung: "Bern ist Bundesstadt und Sitz der Regierung." },
      { frage: "Welcher Fluss fließt durch Wien?", optionen: ["Donau", "Rhein", "Elbe", "Moldau"], richtig: 0, erklaerung: "" } ] } ] },
  { id: "anleitung", art: "lernen", titel: "Pfannkuchen backen (Beispiel)", bausteine: [
    { typ: "anleitung", aktuell: 0, schritte: [
      { titel: "Zutaten bereitstellen", text: "250 g Mehl, 3 Eier, 500 ml Milch, eine Prise Salz.", sekunden: 0 },
      { titel: "Teig rühren", text: "Alles glatt rühren, bis keine Klümpchen mehr da sind.", sekunden: 0 },
      { titel: "Teig ruhen lassen", text: "Den Teig abgedeckt ruhen lassen.", sekunden: 300 },
      { titel: "Ausbacken", text: "Wenig Fett in die Pfanne, je Seite etwa eine Minute.", sekunden: 60 } ] } ] },
  // P6b: Diagramme (Ablauf mit Entscheidung und Rückweg, Organigramm, Mindmap), vollständig wie nach der Backend-Prüfung
  { id: "ablauf", art: "netz", titel: "Bestellung bearbeiten (Beispiel)", bausteine: [
    { typ: "netz", form: "ablauf", knoten: [
      { id: "s", text: "Bestellung eingegangen", art: "start" },
      { id: "p", text: "Ware auf Lager?", art: "entscheidung" },
      { id: "v", text: "Ware versenden", art: "schritt" },
      { id: "n", text: "Ware nachbestellen", art: "schritt" },
      { id: "w", text: "Lieferung abwarten", art: "" },
      { id: "r", text: "Rechnung schicken", art: "schritt" },
      { id: "e", text: "Fertig", art: "ende" } ],
    kanten: [
      { von: "s", bis: "p", text: "" }, { von: "p", bis: "v", text: "ja" }, { von: "p", bis: "n", text: "nein" },
      { von: "n", bis: "w", text: "" }, { von: "w", bis: "p", text: "erneut prüfen" },
      { von: "v", bis: "r", text: "" }, { von: "r", bis: "e", text: "" } ] } ] },
  { id: "organigramm", art: "netz", titel: "Aufbau der Firma (Beispiel)", bausteine: [
    { typ: "netz", form: "baum", knoten: [
      { id: "gf", text: "Geschäftsführung", art: "" }, { id: "ve", text: "Vertrieb", art: "" }, { id: "en", text: "Entwicklung", art: "" },
      { id: "vw", text: "Verwaltung", art: "" }, { id: "in", text: "Innendienst", art: "" }, { id: "au", text: "Außendienst", art: "" },
      { id: "so", text: "Software", art: "" }, { id: "hw", text: "Hardware", art: "" }, { id: "te", text: "Test und Qualität", art: "" },
      { id: "pe", text: "Personal", art: "" }, { id: "bu", text: "Buchhaltung", art: "" } ],
    kanten: [
      { von: "gf", bis: "ve", text: "" }, { von: "gf", bis: "en", text: "" }, { von: "gf", bis: "vw", text: "" },
      { von: "ve", bis: "in", text: "" }, { von: "ve", bis: "au", text: "" },
      { von: "en", bis: "so", text: "" }, { von: "en", bis: "hw", text: "" }, { von: "en", bis: "te", text: "" },
      { von: "vw", bis: "pe", text: "" }, { von: "vw", bis: "bu", text: "" } ] } ] },
  { id: "mindmap", art: "netz", titel: "Urlaub planen (Beispiel)", bausteine: [
    { typ: "netz", form: "mindmap", knoten: [
      { id: "u", text: "Urlaub planen", art: "" },
      { id: "z", text: "Reiseziel", art: "" }, { id: "z1", text: "Strand", art: "" }, { id: "z2", text: "Berge", art: "" },
      { id: "b", text: "Budget", art: "" }, { id: "b1", text: "Flug", art: "" }, { id: "b2", text: "Unterkunft", art: "" },
      { id: "p", text: "Packliste", art: "" }, { id: "p1", text: "Kleidung", art: "" }, { id: "p2", text: "Ausweis und Karten", art: "" },
      { id: "t", text: "Termine", art: "" }, { id: "t1", text: "Urlaubsantrag", art: "" } ],
    kanten: [
      { von: "u", bis: "z", text: "" }, { von: "z", bis: "z1", text: "" }, { von: "z", bis: "z2", text: "" },
      { von: "u", bis: "b", text: "" }, { von: "b", bis: "b1", text: "" }, { von: "b", bis: "b2", text: "" },
      { von: "u", bis: "p", text: "" }, { von: "p", bis: "p1", text: "" }, { von: "p", bis: "p2", text: "" },
      { von: "u", bis: "t", text: "" }, { von: "t", bis: "t1", text: "" } ] } ] },
  // P5a: Simulationen (Pendel, Wurf, Gas), genau wie nach der Backend-Prüfung: alle Felder mit Standardwerten, stand "" und schliessen false
  { id: "pendel", art: "simulation", titel: "Pendel, 1 m (Beispiel)", stand: "", schliessen: false, bausteine: [
    { typ: "simulation", modell: "pendel", parameter: { laenge: 1, winkel: 30, anfangsgeschwindigkeit: 0, daempfung: 0, g: 9.81 },
      laufzeit: 30, tempo: 0, spur: true, beschreibung: "Ein Fadenpendel ohne Reibung, losgelassen bei 30 Grad." } ] },
  { id: "wurf", art: "simulation", titel: "Schräger Wurf (Beispiel)", stand: "", schliessen: false, bausteine: [
    { typ: "simulation", modell: "wurf", parameter: { geschwindigkeit: 20, winkel: 45, hoehe: 1.5, g: 9.81, luftwiderstand: 0 },
      laufzeit: 30, tempo: 0, spur: true, beschreibung: "Ein Ball, aus 1,5 m Höhe mit 20 m/s unter 45 Grad geworfen, ohne Luftwiderstand." } ] },
  { id: "gas", art: "simulation", titel: "Gas im Kasten (Beispiel)", stand: "", schliessen: false, bausteine: [
    { typ: "simulation", modell: "gas",
      parameter: { anzahl: 60, kasten: [100, 60], radius: 1.5, geschwindigkeit: 0.5, schwerkraft: 0, stoesse: true, startwert: 7 },
      laufzeit: 30, tempo: 0, spur: true, beschreibung: "60 gleich schnelle Teilchen stoßen sich; die Geschwindigkeiten verteilen sich mit der Zeit." } ] },
];
