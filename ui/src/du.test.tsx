import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { cleanText, clockText, KILLED_TEXT, MAX_TEXT, mergeEntries, parseEntry, Transcript, whenText, type Entry } from "./components/Transcript";
import { ApiClient } from "./lib/api";
import { STATE_VIEW } from "./lib/avatarState";
import { MockSocket, transcriptEntry, type MockEntry } from "./lib/mock";

// Die Stildatei als Text (Vitest lädt CSS ohne Inhalt): nur lesen, im Test, aus dem eigenen Ordner.
const nodeFs = "node:fs";
const { readFileSync } = (await import(/* @vite-ignore */ nodeFs)) as { readFileSync(p: string, enc: string): string };
const css = readFileSync("src/styles/app.css", "utf-8").replace(/\r\n/g, "\n");   // Vitest läuft im Ordner ui

// Zeilen „Du“ mit aufklappbaren Erkennungsdetails: erscheinen nach der Spracherkennung, vor der Antwort; nur Ansicht, keine Wirkung.

const TOKEN = "t".repeat(43);
const TS = 1_790_000_000;
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const entry = (p: Partial<MockEntry> & { id: number }): Entry => parseEntry(transcriptEntry({ ts: TS, ...p }))!;
const youRows = () => screen.queryAllByRole("button", { name: /^Du: / });

function loaderWith(sock: { current?: MockSocket }, setup: (m: MockSocket) => void = () => {}) {
  return async () => ({
    client: new ApiClient({ port: 5000, token: TOKEN }, (u) => {
      sock.current = new MockSocket(u, TOKEN);
      setup(sock.current);
      return sock.current;
    }),
  });
}
async function startApp(sock: { current?: MockSocket }, setup?: (m: MockSocket) => void) {
  render(<App load={loaderWith(sock, setup)} />);
  await waitFor(() => expect(screen.getAllByText(STATE_VIEW.idle.label).length).toBeGreaterThan(0));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Übersicht" })); });
}
const log = () => within(screen.getByRole("list", { name: "Verlauf" }));

describe("Zeile „Du“ im Verlauf (App)", () => {
  it("erscheint direkt nach der Erkennung mit „wartet“, vor der Antwort; Updates ersetzen die Zeile, nichts doppelt", async () => {
    const sock: { current?: MockSocket } = {};
    await startApp(sock);
    await waitFor(() => screen.getByText(/Noch nichts gesagt/));
    const id = sock.current!.hear("Hey kushim, wie spät ist es?", "wie spät ist es?");
    await waitFor(() => expect(youRows()).toHaveLength(1), { timeout: 3000 });
    expect(youRows()[0]).toHaveAccessibleName(expect.stringMatching(/^Du: wie spät ist es\?, wartet, \d\d:\d\d:\d\d$/));
    expect(document.querySelector(".bubble.bot")).toBeNull();                                // noch keine kushim-Zeile
    sock.current!.change(id, { status: "sent", sent_ts: Date.now() / 1000 });
    await waitFor(() => expect(youRows()[0]).toHaveAccessibleName(expect.stringContaining(", gesendet, ")), { timeout: 3000 });
    sock.current!.change(id, { reply: "Zehn Uhr.", outcome: "spoken" });
    await waitFor(() => log().getByText("Zehn Uhr."), { timeout: 3000 });
    expect(youRows()).toHaveLength(1);
    expect(log().getAllByRole("listitem")).toHaveLength(1);
    const n = sock.current!.sent.length;
    await waitFor(() => {                                                                      // die nächste Abfrage nach der Antwort
      const gets = sock.current!.sent.slice(n).filter((m) => (m as { type: string }).type === "transcript.get") as { since: number }[];
      expect(gets.length).toBeGreaterThan(0);
      expect(gets[gets.length - 1].since).toBe(sock.current!.revSeq);                         // since ist die höchste rev
    }, { timeout: 3000 });
    expect(youRows()).toHaveLength(1);                                                         // nichts doppelt, auch danach
  }, 15_000);                                                    // drei echte Abfragen im Sekundentakt nacheinander, plus Start

  it("der Aufklappzustand bleibt, wenn der Eintrag per rev aktualisiert wird", async () => {
    const sock: { current?: MockSocket } = {};
    await startApp(sock);
    const id = sock.current!.hear("kushim, mach das Licht an", "mach das Licht an");
    await waitFor(() => expect(youRows()).toHaveLength(1), { timeout: 3000 });
    await act(async () => { fireEvent.click(youRows()[0]); });
    expect(youRows()[0]).toHaveAttribute("aria-expanded", "true");
    sock.current!.change(id, { status: "sent", sent_ts: Date.now() / 1000 });
    await waitFor(() => screen.getByText(/^gesendet um \d\d:\d\d:\d\d$/), { timeout: 3000 });
    expect(youRows()).toHaveLength(1);
    expect(youRows()[0]).toHaveAttribute("aria-expanded", "true");
  });

  it("keine Wirkung: Aufklappen sendet nichts, speichert nichts, kein fetch, kein WebSocket", async () => {
    const fetchSpy = vi.fn();
    const wsSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    vi.stubGlobal("WebSocket", wsSpy);
    const store = [vi.spyOn(Storage.prototype, "setItem"), vi.spyOn(Storage.prototype, "getItem"),
      vi.spyOn(Storage.prototype, "removeItem")];
    const sock: { current?: MockSocket } = {};
    await startApp(sock, (m) => { m.entries = [transcriptEntry({ id: 1, heard: "Wie spät?", reply: "Zehn Uhr.", ts: TS })]; });
    await waitFor(() => expect(youRows()).toHaveLength(1), { timeout: 3000 });
    const actions = () => sock.current!.sent.filter((m) => !["safety.status", "voice.state", "approvals.get", "transcript.get",
      "safety.overview", "stage.get", "usage.get", "dashboard.get", "claude.folder_list", "memory.search", "setup.status",
      "setup.checks"].includes((m as { type: string }).type));
    const before = JSON.stringify(actions());
    const row = youRows()[0];
    await act(async () => {
      fireEvent.click(row);
      fireEvent.keyDown(row, { key: "Escape" });
      fireEvent.keyDown(row, { key: "Enter" });
      fireEvent.keyDown(row, { key: " " });
      fireEvent.click(row);
    });
    expect(JSON.stringify(actions())).toBe(before);
    for (const s of store) expect(s).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(wsSpy).not.toHaveBeenCalled();
  });
});

describe("Zeile „Du“ (Baustein)", () => {
  it("Klick schaltet aria-expanded; Enter und Leertaste bleiben dem nativen Knopf; Esc klappt zu, mit Strg nicht", async () => {
    render(<Transcript entries={[entry({ id: 1, heard: "Wie spät ist es?", raw: "Hey kushim, wie spät ist es?" })]} />);
    const row = youRows()[0];
    expect(row.tagName).toBe("BUTTON");
    expect(row).toHaveAttribute("type", "button");                    // Enter und Leertaste lösen beim nativen Knopf den Klick aus
    expect(row).toHaveAttribute("aria-expanded", "false");
    const panel = document.getElementById(row.getAttribute("aria-controls")!)!;
    expect(panel.tagName).toBe("DL");
    expect(panel).not.toBeVisible();
    expect(fireEvent.keyDown(row, { key: "Enter" })).toBe(true);      // nicht abgefangen (kein preventDefault)
    expect(fireEvent.keyDown(row, { key: " " })).toBe(true);
    fireEvent.click(row);
    expect(row).toHaveAttribute("aria-expanded", "true");
    expect(panel).toBeVisible();
    expect(fireEvent.keyDown(row, { key: "Escape", ctrlKey: true })).toBe(true);     // Strg/Alt/Meta gehören dem Browser
    expect(fireEvent.keyDown(row, { key: "Escape", altKey: true })).toBe(true);
    expect(fireEvent.keyDown(row, { key: "Escape", metaKey: true })).toBe(true);
    expect(row).toHaveAttribute("aria-expanded", "true");
    expect(fireEvent.keyDown(row, { key: "Escape" })).toBe(false);    // zugeklappt und verbraucht
    expect(row).toHaveAttribute("aria-expanded", "false");
    expect(fireEvent.keyDown(row, { key: "Escape" })).toBe(true);     // zu: Esc bleibt für andere (z. B. Bühne)
  });

  it("zeigt Zeit, Statuswort mit Symbol, Details mit Grund, rohem Text und dem Text an Claude", () => {
    render(<Transcript entries={[entry({ id: 1, heard: "wie spät ist es?", raw: "Hey kushim, wie spät ist es?", sent_ts: TS + 1 })]} />);
    const row = youRows()[0];
    expect(row).toHaveAccessibleName(`Du: wie spät ist es?, gesendet, ${clockText(TS)}`);
    expect(within(row).getByText(`Du · ${clockText(TS)}`)).toHaveClass("who");
    const chip = within(row).getByText("gesendet");
    expect(chip.querySelector("svg[aria-hidden='true']")).not.toBeNull();
    fireEvent.click(row);
    const dl = document.getElementById(row.getAttribute("aria-controls")!)!;
    const pairs = [...dl.querySelectorAll("dt")].map((dt) => [dt.textContent, dt.nextElementSibling?.textContent]);
    expect(pairs).toEqual([["Erkannt um", whenText(TS)], ["Status", `gesendet um ${clockText(TS + 1)}`],
      ["Erkannt (roh)", "Hey kushim, wie spät ist es?"], ["An Claude", "wie spät ist es?"]]);
  });

  it("verworfene Einträge: Abbruch, nur Weckwort, Notaus (rot, fester Text) und unbekannter Grund", () => {
    render(<Transcript entries={[
      entry({ id: 1, heard: "abbrechen", raw: "Hey kushim, abbrechen", status: "dropped", reason: "cancelled", outcome: "" }),
      entry({ id: 2, heard: "", raw: "Hey kushim.", status: "dropped", reason: "wake_only", outcome: "" }),
      entry({ id: 3, heard: "", raw: "", status: "dropped", reason: "killed", outcome: "killed" }),
      entry({ id: 4, heard: "Licht an", raw: "Licht an", status: "dropped", reason: "neu_im_backend", outcome: "" }),
    ]} />);
    const rows = youRows();
    expect(rows.map((r) => r.getAttribute("aria-label")?.replace(/, \d\d:\d\d:\d\d$/, ""))).toEqual([
      "Du: abbrechen, verworfen", "Du: Hey kushim., verworfen", `Du: ${KILLED_TEXT}, verworfen`, "Du: Licht an, verworfen"]);
    expect(within(rows[2]).getByText("verworfen")).toHaveClass("is-alarm");
    expect(within(rows[0]).getByText("verworfen")).not.toHaveClass("is-alarm");
    const grund = (r: HTMLElement) => {
      fireEvent.click(r);
      const dl = document.getElementById(r.getAttribute("aria-controls")!)!;
      return [...dl.querySelectorAll("dt")].find((d) => d.textContent === "Grund")?.nextElementSibling?.textContent;
    };
    expect(rows.map(grund)).toEqual(["Abbruch", "Nur Weckwort, kein Befehl", "Notaus", "unbekannt"]);
    expect(screen.queryByText("An Claude")).toBeNull();                                     // nichts davon ging an Claude
    expect(screen.getByText("Notaus ausgelöst.")).toBeInTheDocument();                      // kushim-Zeile beim Notaus wie bisher
  });

  it("Steuer- und Richtungszeichen fallen weg, lange Texte werden gekürzt, HTML bleibt Text", () => {
    const evil = `<b>fett</b>\u202Egnirts\u0007\nzweite Zeile ${"x".repeat(5000)}`;
    render(<Transcript entries={[entry({ id: 1, heard: evil, raw: evil })]} />);
    const text = document.querySelector(".you-text")!.textContent!;
    expect(text.startsWith("<b>fett</b>gnirts zweite Zeile x")).toBe(true);
    expect(Array.from(text)).toHaveLength(MAX_TEXT);
    expect(document.querySelector(".you-row b")).toBeNull();
    expect(/[\u0000-\u001f\u202e]/.test(text)).toBe(false);
    expect(cleanText("a\u200Fb\u2028c")).toBe("ab c");
  });

  it("die Backend-id steht nie in id, class oder style; die Daumen bleiben getrennt an der kushim-Zeile", () => {
    render(<Transcript entries={[entry({ id: 4242, heard: "Hallo", reply: "Hi." })]} onRate={() => {}} />);
    fireEvent.click(youRows()[0]);
    for (const el of document.querySelectorAll("*")) {
      for (const a of ["id", "class", "style"]) expect(el.getAttribute(a) ?? "").not.toContain("4242");
    }
    expect(youRows()[0].querySelector("button")).toBeNull();                                // keine verschachtelten Knöpfe
    expect(document.querySelector(".bubble.bot")!.querySelectorAll("button")).toHaveLength(2);
    expect(document.querySelectorAll("[aria-live]")).toHaveLength(0);                       // kein aria-live je Zeile
  });

  it("herausgefallene Einträge werden aus dem Aufklappzustand entfernt", () => {
    const list = [1, 2, 3, 4].map((id) => entry({ id, heard: `Satz ${id}` }));
    const { rerender } = render(<Transcript entries={list} />);
    fireEvent.click(screen.getByRole("button", { name: /^Du: Satz 1,/ }));
    rerender(<Transcript entries={[...list, entry({ id: 5, heard: "Satz 5" })]} />);        // Satz 1 fällt heraus (höchstens 4)
    expect(screen.queryByRole("button", { name: /^Du: Satz 1,/ })).toBeNull();
    rerender(<Transcript entries={list} />);                                                 // kommt er zurück, ist er zu
    expect(screen.getByRole("button", { name: /^Du: Satz 1,/ })).toHaveAttribute("aria-expanded", "false");
  });
});

describe("Zusammenführen und Prüfen", () => {
  it("ersetzt nach id nur mit höherer rev, hängt nie doppelt an, höchstens 20", () => {
    const a = entry({ id: 1, rev: 1, status: "pending", heard: "a" });
    const a2 = entry({ id: 1, rev: 3, heard: "a" });
    const b = entry({ id: 2, rev: 2, heard: "b" });
    expect(mergeEntries([a], [b, a2]).map((e) => [e.id, e.rev, e.status])).toEqual([[1, 3, "sent"], [2, 2, "sent"]]);
    expect(mergeEntries([a2], [a])[0].rev).toBe(3);                                          // alter Stand überschreibt nicht
    const many = Array.from({ length: 25 }, (_, i) => entry({ id: i + 1, heard: "x" }));
    expect(mergeEntries([], many).map((e) => e.id)).toEqual(many.slice(-20).map((e) => e.id));
  });

  it("parseEntry: ohne gültige id nichts, unbekannter Status bleibt „unbekannt“, Grund nur als kurzer Code", () => {
    expect(parseEntry({ heard: "x" })).toBeNull();
    expect(parseEntry({ id: -1 })).toBeNull();
    const e = parseEntry({ id: 3, status: "geheim", reason: "<script>", ts: "bald" })!;
    expect([e.status, e.reason, e.ts, e.rev]).toEqual(["unknown", "?", null, 3]);
    render(<Transcript entries={[{ ...e, heard: "Hallo" }]} />);
    expect(youRows()[0]).toHaveAccessibleName("Du: Hallo, unbekannt, unbekannt");
  });

  it("whenText zeigt an einem anderen Tag das Datum", () => {
    const now = new Date(TS * 1000);
    expect(whenText(TS, now)).toBe(clockText(TS));
    expect(whenText(TS - 86400, now)).toMatch(/^\d\d\.\d\d\. \d\d:\d\d:\d\d$/);
    expect(whenText(TS - 400 * 86400, now)).toMatch(/^\d\d\.\d\d\.\d{4} \d\d:\d\d:\d\d$/);
  });
});

describe("Kleines Fenster", () => {
  it("zeigt „Du: … · Statuswort“, pending sofort ohne kushim-Zeile, kein Aufklappen", async () => {
    const sock: { current?: MockSocket } = {};
    render(<App load={loaderWith(sock, (m) => { m.voice = { active: true, state: "idle", level: 0 }; })} />);
    await waitFor(() => expect(screen.getAllByText(STATE_VIEW.idle.label).length).toBeGreaterThan(0));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Klein" })); });
    const box = () => within(screen.getByRole("region", { name: "Kleines Fenster" }));
    const id = sock.current!.hear("Hey kushim, wie spät ist es?", "wie spät ist es?");
    const you = await box().findByText("Du: wie spät ist es? · wartet", undefined, { timeout: 3000 });
    expect(you).toHaveAttribute("title", expect.stringMatching(/^Erkannt \d\d:\d\d:\d\d, wartet$/));
    expect(box().queryByText(/^kushim:/)).toBeNull();
    expect(screen.getByRole("region", { name: "Kleines Fenster" }).querySelector("[aria-expanded]")).toBeNull();
    sock.current!.change(id, { status: "sent", sent_ts: Date.now() / 1000, reply: "Zehn Uhr.", outcome: "spoken" });
    await box().findByText("Du: wie spät ist es? · gesendet", undefined, { timeout: 3000 });
    expect(box().getByText("kushim: Zehn Uhr.")).toBeInTheDocument();
  });
});

describe("Breiten (CSS)", () => {
  const block = (sel: string, src = css) => src.match(new RegExp(`${sel.replace(/[.[\]"=]/g, "\\$&")} \\{([^}]*)\\}`))?.[1] ?? "";
  it("375 px: eine Spalte, Chip bricht um, Label über dem Wert; keine festen Breiten", () => {
    expect(block(".you-details")).toContain("display: grid");
    expect(block(".you-details")).not.toContain("grid-template-columns");
    expect(block(".you-head")).toContain("flex-wrap: wrap");
    expect(block(".you-row")).toContain("min-height: var(--hit)");
    expect(block(".you-row")).toContain("border-left: 3px solid var(--amber)");
    for (const sel of [".you-row", ".you-head", ".you-chip", ".you-text", ".you-details", ".you-details dd"]) {
      expect(block(sel)).not.toMatch(/(^|[^-])width: \d+px/);
    }
    expect(block(".you-text")).toContain("overflow-wrap: anywhere");
    expect(block(".you-details dd")).toContain("overflow-wrap: anywhere");
  });
  it("ab 800 px (auch 1440 px) zwei Spalten max-content 1fr; Chevron ohne Bewegung bei reduzierter Bewegung", () => {
    const wide = css.match(/@media \(min-width: 800px\) \{\s*\.you-details \{([^}]*)\}/)?.[1] ?? "";
    expect(wide).toContain("grid-template-columns: max-content 1fr");
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\) \{ \.you-chev \{ transition: none; \} \}/);
    expect(block(".you-chev")).toContain("transition: transform var(--t-fast)");
  });
  it("Chevron: zu ohne Drehung (▾), auf um die waagrechte Achse gedreht (▴), nie seitlich; bei weniger Bewegung nur das Endbild", () => {
    render(<Transcript entries={[entry({ id: 1, heard: "Hallo" })]} />);
    const row = youRows()[0];
    const chev = row.querySelector(".you-chev")!;
    expect(chev).not.toHaveClass("is-open");
    expect(block(".you-chev")).not.toContain("transform:");                  // zu: das Symbol zeigt von sich aus nach unten
    expect(chev.querySelector("path")).toHaveAttribute("d", "M6 9l6 6 6-6");
    fireEvent.click(row);
    expect(chev).toHaveClass("is-open");
    expect(block(".you-chev.is-open")).toBe(" transform: rotateX(180deg); ");    // ▴, auch jedes Zwischenbild zeigt nie nach links
    expect(css).not.toMatch(/\.you-chev[^{]*\{[^}]*rotate\(/);                // keine Drehung in der Ebene (läuft über 90°)
    expect(css).not.toMatch(/prefers-reduced-motion[^{]*\{[^}]*\.you-chev\.is-open/);   // Endbild bleibt auch ohne Bewegung
    fireEvent.click(row);
    expect(chev).not.toHaveClass("is-open");
  });
});
