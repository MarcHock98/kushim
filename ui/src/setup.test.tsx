import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { ApiClient } from "./lib/api";
import { MockSocket } from "./lib/mock";

/** E3 Setup-Assistent (docs/ui-e2e3-plan.md, Abschnitt 5) gegen das gefälschte Backend. */

const TOKEN = "t".repeat(43);
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

type Sock = { current?: MockSocket };
type Msg = Record<string, unknown> & { type: string };

async function start(prep?: (m: MockSocket) => void, first = true): Promise<Sock> {
  const sock: Sock = {};
  const loader = async () => ({
    client: new ApiClient({ port: 5000, token: TOKEN }, (u) => {
      sock.current = new MockSocket(u, TOKEN);
      if (first) sock.current.firstStart();
      prep?.(sock.current);
      return sock.current;
    }),
  });
  render(<App load={loader} />);
  if (first) await screen.findByRole("heading", { name: "1. Systemcheck" }, { timeout: 3000 });
  return sock;
}

const sent = (s: Sock, type?: string) => (s.current!.sent as Msg[]).filter((m) => !type || m.type === type);
const wiz = () => within(screen.getByRole("region", { name: "Einrichtung" }));
const nav = () => within(screen.getByRole("navigation", { name: "Schritte der Einrichtung" }));
const stepBtn = (title: string) => nav().getByRole("button", { name: new RegExp(`^${title}, `) });
const click = async (el: HTMLElement) => { await act(async () => { fireEvent.click(el); }); };
async function goto(title: string, n: number) {
  await click(stepBtn(title));
  await screen.findByRole("heading", { name: `${n}. ${title}` });
}
const voiceOn = (m: MockSocket) => { m.voice = { active: true, state: "idle", level: 0.42 }; };

const WRITES = ["setup.skip", "setup.reopen", "setup.done", "audio.set", "voice.level_test", "voice.level_apply", "wake.set"];
const ALLOWED = new Set([
  // was das Fenster ohnehin abfragt
  "safety.status", "voice.state", "approvals.get", "transcript.get", "safety.overview", "stage.get",
  // Setup-Vertrag
  "setup.status", "setup.checks", "audio.devices", "audio.get", "voice.level_result", "wake.get", ...WRITES,
  "claude.folder_list", "claude.folder_propose", "claude.folder_confirm", "claude.folder_deny", "claude.folder_remove",
]);

/** Token-ähnliche Zeichenketten in Textknoten und Attributwerten des Fensters (SVG-Pfade ausgenommen: nur Zahlen und Befehle). */
function tokenLike(): string[] {
  const bad = /[A-Za-z0-9_\-+/=]{32,}/;
  const hits: string[] = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) if (bad.test(n.nodeValue ?? "")) hits.push(n.nodeValue ?? "");
  for (const el of Array.from(document.body.querySelectorAll("*"))) {
    for (const a of Array.from(el.attributes)) if (a.name !== "d" && bad.test(a.value)) hits.push(`${a.name}=${a.value}`);
  }
  return hits;
}

async function walk() {
  const titles = ["Systemcheck", "Claude", "Mikrofon", "Wake Words", "Arbeitsordner", "Sicherheit"];
  for (let i = 1; i < titles.length; i++) {
    await click(wiz().getByRole("button", { name: "Weiter" }));
    await screen.findByRole("heading", { name: `${i + 1}. ${titles[i]}` });
  }
}

describe("Setup-Assistent: Erststart und Rahmen", () => {
  it("erscheint beim ersten Start mit sechs Schritten, Status als Wort und Fokus auf der Überschrift", async () => {
    const s = await start();
    expect(sent(s, "setup.status").length).toBeGreaterThan(0);
    const items = nav().getAllByRole("listitem");
    expect(items).toHaveLength(6);
    for (const it of items) expect(it).toHaveTextContent("offen");
    expect(stepBtn("Systemcheck")).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("heading", { name: "1. Systemcheck" })).toHaveFocus();
    expect(wiz().getByText("Schritt 1 von 6")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "NOTAUS" })).toBeInTheDocument();     // Notaus bleibt sichtbar
  });

  it("erscheint nicht, wenn nichts offen ist; über Sicherheit, Einrichtung lässt er sich öffnen", async () => {
    const s = await start(undefined, false);
    await waitFor(() => expect(sent(s, "setup.status").length).toBe(1));
    expect(screen.queryByRole("region", { name: "Einrichtung" })).toBeNull();
    await click(screen.getByRole("button", { name: "Sicherheit" }));
    await click(await screen.findByRole("button", { name: "Einrichtung öffnen" }));
    expect(await screen.findByRole("heading", { name: "1. Systemcheck" })).toBeInTheDocument();
    for (const it of nav().getAllByRole("listitem")) expect(it).toHaveTextContent("erledigt");
  });

  it("Weiter, Zurück, Pfeiltasten in der Schrittliste; Fertig schließt; Tasten mit Strg bleiben dem Browser", async () => {
    await start();
    expect(wiz().getByRole("button", { name: "Zurück" })).toBeDisabled();
    await click(wiz().getByRole("button", { name: "Weiter" }));
    expect(await screen.findByRole("heading", { name: "2. Claude" })).toHaveFocus();
    await click(wiz().getByRole("button", { name: "Zurück" }));
    await screen.findByRole("heading", { name: "1. Systemcheck" });
    const first = stepBtn("Systemcheck");
    first.focus();
    await act(async () => { fireEvent.keyDown(first, { key: "ArrowDown" }); });
    await screen.findByRole("heading", { name: "2. Claude" });
    expect(stepBtn("Claude")).toHaveFocus();
    await act(async () => { fireEvent.keyDown(stepBtn("Claude"), { key: "ArrowDown", ctrlKey: true }); });
    expect(screen.getByRole("heading", { name: "2. Claude" })).toBeInTheDocument();
    await act(async () => { fireEvent.keyDown(stepBtn("Claude"), { key: "End" }); });
    await screen.findByRole("heading", { name: "6. Sicherheit" });
    await act(async () => { fireEvent.keyDown(stepBtn("Sicherheit"), { key: "Home" }); });
    await screen.findByRole("heading", { name: "1. Systemcheck" });
    await act(async () => { fireEvent.keyDown(stepBtn("Systemcheck"), { key: "End" }); });
    await click(wiz().getByRole("button", { name: "Fertig" }));
    expect(screen.queryByRole("region", { name: "Einrichtung" })).toBeNull();
  });

  it("Überspringen: Folge steht als Satz da, setup.skip mit confirm, ruhige Zeile; Wieder aufnehmen sendet setup.reopen", async () => {
    const s = await start();
    expect(wiz().getByText("Wenn du überspringst: Kein Gedächtnis. Notaus und Sicherheitsregeln gelten weiter.")).toBeInTheDocument();
    await click(wiz().getByRole("button", { name: "Überspringen" }));
    await screen.findByRole("heading", { name: "2. Claude" });
    expect(sent(s, "setup.skip")[0]).toMatchObject({ step: "system", confirm: true });
    expect(stepBtn("Systemcheck")).toHaveTextContent("übersprungen");
    expect(nav().getByText("Systemcheck und Vault: Kein Gedächtnis. Notaus und Sicherheitsregeln gelten weiter.")).toBeInTheDocument();
    await goto("Systemcheck", 1);
    expect(wiz().getByText(/^Übersprungen\. Kein Gedächtnis/)).toBeInTheDocument();
    await click(wiz().getByRole("button", { name: "Wieder aufnehmen" }));
    expect(sent(s, "setup.reopen")[0]).toMatchObject({ step: "system", confirm: true });
    await waitFor(() => expect(stepBtn("Systemcheck")).toHaveTextContent("offen"));
  });

  it("nach dem Schließen zeigt das Fenster für übersprungene Schritte eine ruhige Zeile mit dem Weg zum Nachholen", async () => {
    await start();
    await goto("Wake Words", 4);
    await click(wiz().getByRole("button", { name: "Überspringen" }));
    await screen.findByRole("heading", { name: "5. Arbeitsordner" });
    await click(wiz().getByRole("button", { name: "Schließen" }));
    expect(await screen.findByText("Eingeschränkt: Wake Words: Es gelten die Standard-Wörter aus der Vorlage.")).toBeInTheDocument();
    expect(screen.getByText("Nachholen unter Sicherheit, Einrichtung.")).toBeInTheDocument();
  });

  it("wartet im kleinen Fenster (Klasse an .app) und kommt im großen mit demselben Schritt zurück", async () => {
    await start();
    await click(wiz().getByRole("button", { name: "Weiter" }));
    await screen.findByRole("heading", { name: "2. Claude" });
    const app = document.querySelector(".app")!;
    await act(async () => { app.classList.add("is-compact"); });
    await waitFor(() => expect(screen.queryByRole("region", { name: "Einrichtung" })).toBeNull());
    await act(async () => { app.classList.remove("is-compact"); });
    expect(await screen.findByRole("heading", { name: "2. Claude" })).toBeInTheDocument();
  });
});

describe("Setup-Assistent: Schritte lesen und schreiben", () => {
  it("Systemcheck: Liste mit Wort und Hinweis; Vault nur als Terminal-Hinweis, kein Knopf zum Anlegen", async () => {
    const s = await start();
    await waitFor(() => expect(sent(s, "setup.checks").length).toBeGreaterThan(0));
    const list = await screen.findByText("Vault vorhanden");
    const row = list.closest("li")!;
    expect(row).toHaveTextContent("nicht in Ordnung");
    expect(row).toHaveTextContent("kushim memory init im eigenen Terminal");
    expect(within(row).queryByRole("button")).toBeNull();
    expect(screen.getByText("GPU-Bibliotheken (cuBLAS/cuDNN)").closest("li")).toHaveTextContent("in Ordnung");
    expect(screen.queryByText("In Claude Code angemeldet")).toBeNull();           // Claude hat einen eigenen Schritt
    expect(sent(s).filter((m) => WRITES.includes(m.type))).toEqual([]);
  });

  it("Claude: installiert, Version, angemeldet; Anmelden nur als Terminal-Hinweis", async () => {
    const s = await start();
    await goto("Claude", 2);
    expect(await screen.findByText("Claude Code mindestens 2.1.234 (ist 2.1.240)")).toBeInTheDocument();
    const auth = screen.getByText("In Claude Code angemeldet").closest("li")!;
    expect(auth).toHaveTextContent("nicht in Ordnung");
    expect(auth).toHaveTextContent("claude auth login im eigenen Terminal");
    expect(screen.queryByText("Vault vorhanden")).toBeNull();
    const before = sent(s, "setup.checks").length;
    await click(wiz().getByRole("button", { name: "Erneut prüfen" }));
    expect(sent(s, "setup.checks").length).toBe(before + 1);
    expect(sent(s).filter((m) => WRITES.includes(m.type))).toEqual([]);
  });

  it("Mikrofon: Gerätelisten, Pegel live mit Zahl, Wahl speichern mit confirm und Neustart-Satz", async () => {
    const s = await start(voiceOn);
    await goto("Mikrofon", 3);
    const mic = await screen.findByLabelText("Mikrofon");
    await waitFor(() => within(mic).getByRole("option", { name: "Headset-Mikrofon (Jabra Evolve 65)" }));
    expect(within(screen.getByLabelText("Lautsprecher")).getByRole("option", { name: "Kopfhörer (Jabra Evolve 65)" })).toBeInTheDocument();
    expect(within(mic).getByRole("option", { name: "Systemstandard" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("meter", { name: "Mikrofonpegel" })).toHaveAttribute("aria-valuenow", "42"));
    expect(screen.getByText("42 %")).toBeInTheDocument();
    expect(wiz().getByRole("button", { name: "Auswahl speichern" })).toBeDisabled();       // nichts geändert
    fireEvent.change(mic, { target: { value: "Headset-Mikrofon (Jabra Evolve 65)" } });
    await click(wiz().getByRole("button", { name: "Auswahl speichern" }));
    expect(sent(s, "audio.set")[0]).toMatchObject({ mic: "Headset-Mikrofon (Jabra Evolve 65)", out: "", confirm: true });
    expect(await screen.findByText("Gilt ab dem nächsten Start von kushim.")).toBeInTheDocument();
    expect(screen.getByText("Auswahl gespeichert.")).toBeInTheDocument();
    await click(wiz().getByRole("button", { name: "Mikrofon passt" }));
    expect(sent(s, "setup.done")[0]).toMatchObject({ step: "audio_voice", confirm: true });
    await waitFor(() => expect(stepBtn("Mikrofon")).toHaveTextContent("erledigt"));
  });

  it("Pegeltest: still sein, sprechen (Countdown als Wort), Vorschlag, Übernehmen mit confirm", async () => {
    let clock = 1_000_000;
    const s = await start((m) => { voiceOn(m); m.now = () => clock; });
    await goto("Mikrofon", 3);
    await waitFor(() => expect(screen.getByRole("meter", { name: "Mikrofonpegel" })).toHaveAttribute("aria-valuenow", "42"));
    await click(wiz().getByRole("button", { name: "Pegeltest starten" }));
    expect(sent(s, "voice.level_test")[0]).toMatchObject({ confirm: true });
    expect(await screen.findByText("Bitte still sein … 3", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(wiz().getByRole("button", { name: "Pegeltest starten" })).toBeDisabled();
    clock += 3000;
    expect(await screen.findByText("Jetzt sprechen … 6", {}, { timeout: 3000 })).toBeInTheDocument();
    clock += 6500;
    expect(await screen.findByText("Vorschlag: Sprechen ab 240, Unterbrechen ab 320.", {}, { timeout: 3000 })).toBeInTheDocument();
    await click(wiz().getByRole("button", { name: "Übernehmen" }));
    expect(sent(s, "voice.level_apply")[0]).toMatchObject({ speech_level: 240, barge_in_level: 320, confirm: true });
    expect(await screen.findByText("Pegel übernommen.")).toBeInTheDocument();
    expect(screen.getByText("Gilt ab dem nächsten Start von kushim.")).toBeInTheDocument();
  });

  it("ohne Sprachdienst: Satz statt Test, beide Tests aus; die Geräteliste geht trotzdem", async () => {
    const s = await start((m) => { m.voiceUnavailable = true; });
    await goto("Mikrofon", 3);
    expect(await screen.findByText("Starte kushim mit Sprache, dann geht der Test.")).toBeInTheDocument();
    expect(wiz().getByRole("button", { name: "Pegeltest starten" })).toBeDisabled();
    expect(screen.getByText("kein Signal")).toBeInTheDocument();
    await waitFor(() => within(screen.getByLabelText("Mikrofon")).getByRole("option", { name: "Mikrofon (USB Audio Device)" }));
    await goto("Wake Words", 4);
    expect(await screen.findByText("Starte kushim mit Sprache, dann geht der Test.")).toBeInTheDocument();
    expect(wiz().getByRole("button", { name: "Wake Word testen" })).toBeDisabled();
    expect(sent(s, "voice.level_test")).toEqual([]);
  });

  it("Pegeltest meldet „unavailable“, obwohl der Sprachdienst läuft: derselbe Satz, Test aus", async () => {
    const s = await start((m) => { voiceOn(m); m.levelUnavailable = true; });
    await goto("Mikrofon", 3);
    await waitFor(() => expect(screen.getByRole("meter", { name: "Mikrofonpegel" })).toHaveAttribute("aria-valuenow", "42"));
    expect(screen.queryByText("Starte kushim mit Sprache, dann geht der Test.")).toBeNull();
    await click(wiz().getByRole("button", { name: "Pegeltest starten" }));
    expect(sent(s, "voice.level_test")).toHaveLength(1);
    expect(await screen.findByText("Starte kushim mit Sprache, dann geht der Test.", { selector: ".setup-text" })).toBeInTheDocument();
    expect(wiz().getByRole("button", { name: "Pegeltest starten" })).toBeDisabled();
  });

  it("Wake Words: Schalter, Prüfung beim Hinzufügen (leer, zu lang, doppelt, 13.), letztes aktives bleibt an, Speichern mit confirm", async () => {
    const s = await start();
    await goto("Wake Words", 4);
    await screen.findByText("hey kushim");
    expect(sent(s, "wake.get").length).toBe(1);
    const input = screen.getByLabelText("Neues Wake Word");
    const add = async (v: string) => {
      fireEvent.change(input, { target: { value: v } });
      await click(wiz().getByRole("button", { name: "Hinzufügen" }));
    };
    await add("   ");
    expect(screen.getByText("Bitte ein Wort eingeben.")).toBeInTheDocument();
    await add("a".repeat(41));
    expect(screen.getByText("Zu lang: höchstens 40 Zeichen.")).toBeInTheDocument();
    await add("Hey   Kushim");
    expect(screen.getByText("„hey kushim“ steht schon in der Liste.")).toBeInTheDocument();
    await add("abc1");
    expect(screen.getByText("Nur Buchstaben und Leerzeichen, höchstens vier Wörter.")).toBeInTheDocument();
    for (const w of ["computer", "jarvis", "hallo du", "hey du", "servus", "moin kushim"]) await add(w);
    expect(screen.getByText("12 von 12, 12 aktiv")).toBeInTheDocument();
    await add("noch eins");
    expect(screen.getByText("Höchstens 12 Wake Words. Entferne erst eines.")).toBeInTheDocument();
    // alle bis auf eines entfernen bzw. ausschalten
    for (const w of ["kushim", "kush", "hallo kush", "hi kushim", "kushi", "computer", "jarvis", "hallo du", "hey du", "servus"]) {
      await click(screen.getByRole("button", { name: `Entfernen: ${w}` }));
    }
    const sw = (p: string) => within(screen.getByText(p).closest("li")!).getByRole("switch");
    await click(sw("moin kushim"));
    expect(sw("moin kushim")).not.toBeChecked();
    await click(sw("hey kushim"));                                                   // das letzte aktive
    expect(screen.getByText("Mindestens ein Wake Word muss aktiv bleiben.")).toBeInTheDocument();
    expect(sw("hey kushim")).toBeChecked();
    await click(screen.getByRole("button", { name: "Entfernen: hey kushim" }));
    expect(screen.getByText("hey kushim")).toBeInTheDocument();
    expect(sent(s, "wake.set")).toEqual([]);                                         // bis hier nur Entwurf
    await click(wiz().getByRole("button", { name: "Wake Words speichern" }));
    expect(sent(s, "wake.set")[0]).toMatchObject({ confirm: true, words: [{ phrase: "hey kushim", enabled: true }, { phrase: "moin kushim", enabled: false }] });
    expect(await screen.findByText("Gilt ab dem nächsten Start von kushim.")).toBeInTheDocument();
    expect(screen.getByText("Wake Words gespeichert.")).toBeInTheDocument();
    await click(wiz().getByRole("button", { name: "Wörter passen" }));
    expect(sent(s, "setup.done")[0]).toMatchObject({ step: "wake_words", confirm: true });
  });

  it("Wake-Word-Test: erkannt, sobald der Zähler steigt", async () => {
    const s = await start(voiceOn);
    await goto("Wake Words", 4);
    await waitFor(() => expect(wiz().getByRole("button", { name: "Wake Word testen" })).toBeEnabled());
    await click(wiz().getByRole("button", { name: "Wake Word testen" }));
    expect(await screen.findByText("Sag jetzt ein Wake Word … 10")).toBeInTheDocument();
    s.current!.wake("hey kushim");
    expect(await screen.findByText("erkannt: hey kushim")).toBeInTheDocument();
    expect(sent(s).filter((m) => WRITES.includes(m.type))).toEqual([]);              // der Test sendet nichts Schreibendes
  });

  it("Wake-Word-Test: nichts erkannt in 10 s", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await start(voiceOn);
    await goto("Wake Words", 4);
    await waitFor(() => expect(wiz().getByRole("button", { name: "Wake Word testen" })).toBeEnabled());
    await click(wiz().getByRole("button", { name: "Wake Word testen" }));
    await screen.findByText("Sag jetzt ein Wake Word … 10");
    await act(async () => { await vi.advanceTimersByTimeAsync(10_500); });
    expect(await screen.findByText("nichts erkannt in 10 s")).toBeInTheDocument();
  });

  it("Arbeitsordner: vorhandener FolderManager, Freigabe nur mit Vorschau und confirm", async () => {
    const s = await start();
    await goto("Arbeitsordner", 5);
    fireEvent.change(await screen.findByLabelText("Name (klein, ohne Leerzeichen)"), { target: { value: "proj" } });
    fireEvent.change(screen.getByLabelText("Pfad zum Git-Ordner"), { target: { value: "C:/projekte/proj" } });
    await click(screen.getByRole("button", { name: "Freigabe-Vorschau ansehen" }));
    await click(await screen.findByRole("button", { name: "Erlauben" }));
    expect(sent(s, "claude.folder_confirm")[0]).toMatchObject({ confirm: true, proposal: "f1" });
    expect(await screen.findByText("Ordner freigegeben.")).toBeInTheDocument();
  });

  it("Sicherheit: Regeln, NOTAUS und Strg+Umschalt+K erklärt; „verstanden“ sendet setup.done, nie safety.kill", async () => {
    const s = await start();
    await goto("Sicherheit", 6);
    expect(wiz().getByText(/steht oben rechts in jedem Fenster/)).toBeInTheDocument();
    expect(wiz().getByText(/nur im Claude-Terminal oder in der Freigabe-Leiste/)).toBeInTheDocument();
    expect(wiz().getByText("Strg")).toBeInTheDocument();
    await click(wiz().getByRole("button", { name: "verstanden" }));
    expect(sent(s, "setup.done")[0]).toMatchObject({ step: "safety", confirm: true });
    await waitFor(() => expect(stepBtn("Sicherheit")).toHaveTextContent("erledigt"));
    expect(sent(s, "safety.kill")).toEqual([]);
  });
});

describe("Setup-Assistent: Sicherheit", () => {
  it("bei aktivem Notaus sind alle schreibenden Bedienelemente aus, mit Wort; Blättern geht weiter", async () => {
    const s = await start((m) => { m.kill = true; voiceOn(m); });
    expect(await screen.findByText("Gesperrt: Notaus aktiv. Ändern geht erst nach dem Aufheben.")).toBeInTheDocument();
    expect(wiz().getByRole("button", { name: "Überspringen" })).toBeDisabled();
    expect(wiz().getByRole("button", { name: "Weiter" })).toBeEnabled();
    await goto("Mikrofon", 3);
    fireEvent.change(screen.getByLabelText("Mikrofon"), { target: { value: "" } });
    expect(wiz().getByRole("button", { name: "Auswahl speichern" })).toBeDisabled();
    expect(wiz().getByRole("button", { name: "Pegeltest starten" })).toBeDisabled();
    expect(wiz().getByRole("button", { name: "Mikrofon passt" })).toBeDisabled();
    await goto("Wake Words", 4);
    await screen.findByText("hey kushim");
    expect(wiz().getByRole("button", { name: "Wake Words speichern" })).toBeDisabled();
    expect(wiz().getByRole("button", { name: "Wörter passen" })).toBeDisabled();
    await goto("Arbeitsordner", 5);
    expect(await screen.findByLabelText("Name (klein, ohne Leerzeichen)")).toBeDisabled();
    await goto("Sicherheit", 6);
    expect(wiz().getByRole("button", { name: "verstanden" })).toBeDisabled();
    expect(sent(s).filter((m) => WRITES.includes(m.type))).toEqual([]);
  });

  it("Notaus während des Assistenten: Knöpfe gehen sofort aus; lehnt das Backend mit „kill“ ab, steht es da", async () => {
    const s = await start(voiceOn);
    await goto("Sicherheit", 6);
    await click(screen.getByRole("button", { name: "NOTAUS" }));
    expect(await screen.findByText("Gesperrt: Notaus aktiv. Ändern geht erst nach dem Aufheben.")).toBeInTheDocument();
    expect(wiz().getByRole("button", { name: "verstanden" })).toBeDisabled();
    expect(sent(s, "setup.done")).toEqual([]);
  });

  it("nach dem bestätigten Aufheben des Notaus sind die Knöpfe wieder an", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    await start((m) => { m.kill = true; });
    expect(await screen.findByText("Gesperrt: Notaus aktiv. Ändern geht erst nach dem Aufheben.")).toBeInTheDocument();
    await click(await screen.findByRole("button", { name: "Notaus aufheben" }));
    await waitFor(() => expect(screen.queryByText(/^Gesperrt: Notaus aktiv/)).toBeNull(), { timeout: 3000 });
    expect(wiz().getByRole("button", { name: "Überspringen" })).toBeEnabled();
  });

  it("weiß das Fenster noch nichts vom Notaus, lehnt das Backend mit „kill“ ab und das steht da", async () => {
    const s = await start();
    await goto("Sicherheit", 6);
    s.current!.kill = true;                                                          // gerade erst ausgelöst (z. B. im Terminal)
    await click(wiz().getByRole("button", { name: "verstanden" }));
    expect(sent(s, "setup.done")[0]).toMatchObject({ step: "safety", confirm: true });
    expect(await screen.findByText("Notaus ist aktiv. Nichts wurde geändert.")).toBeInTheDocument();
    expect(stepBtn("Sicherheit")).toHaveTextContent("offen");
  });

  it("Gerätenamen und Wake Words mit <script> bleiben Text; Token-ähnliches erscheint nie im Fenster", async () => {
    const evil = "<script>alert(1)</script>";
    const secret = "sk-ant-" + "A1b2C3d4".repeat(6);
    await start((m) => {
      voiceOn(m);
      m.devices = { inputs: [evil], outputs: ["<img src=x onerror=alert(1)>"] };
      m.words = [{ phrase: "<script>x</script>", enabled: true }, { phrase: "hey kushim", enabled: true }];
      m.checks = [...m.checks, { id: "extra", label: "Prüfpunkt", ok: false, hint: `Token ${secret} gefunden` }];
    });
    expect(await screen.findByText(/Token \[verborgen\] gefunden/)).toBeInTheDocument();
    await goto("Mikrofon", 3);
    expect(await screen.findByRole("option", { name: evil })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "<img src=x onerror=alert(1)>" })).toBeInTheDocument();
    await goto("Wake Words", 4);
    expect(await screen.findByText("<script>x</script>")).toBeInTheDocument();
    expect(document.querySelectorAll("script, img[src='x']")).toHaveLength(0);
    const html = document.body.innerHTML;
    expect(html).not.toContain(TOKEN);
    expect(html).not.toContain(secret);
    expect(tokenLike()).toEqual([]);
  });

  it("Rundgang: nur die gelisteten Typen, Schreibendes immer mit confirm, kein Speichern im Browser, kein Token im DOM", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const s = await start(voiceOn);
    await walk();
    await click(wiz().getByRole("button", { name: "Überspringen" }));               // letzter Schritt: überspringen schließt
    expect(screen.queryByRole("region", { name: "Einrichtung" })).toBeNull();
    await click(screen.getByRole("button", { name: "Sicherheit" }));
    await click(await screen.findByRole("button", { name: "Einrichtung öffnen" }));
    await screen.findByRole("heading", { name: /^\d\. / });
    const types = new Set(sent(s).map((m) => m.type));
    for (const t of types) expect(ALLOWED, t).toContain(t);
    for (const m of sent(s).filter((x) => WRITES.includes(x.type))) expect(m.confirm, m.type).toBe(true);
    expect(setItem).not.toHaveBeenCalled();
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    expect(document.body.innerHTML).not.toContain(TOKEN);
    expect(tokenLike()).toEqual([]);
  });
});
