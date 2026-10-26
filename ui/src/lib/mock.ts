// Gefälschtes Backend für Entwicklung und Tests (kein Netz). Antwortet wie `ApiCore`: Token zuerst, neutrale Fehler.
import type { Socket } from "./api";

export class MockSocket implements Socket {
  onmessage: Socket["onmessage"] = null;
  onclose: Socket["onclose"] = null;
  onopen: Socket["onopen"] = null;
  onerror: Socket["onerror"] = null;
  kill = false;
  voice: { active: boolean; state: string; level: number } = { active: false, state: "idle", level: 0 };
  pending: { kind: string; preview: string; digest: string; expires_in: number; sends_data_out: boolean } | null = null;
  entries: { id: number; heard: string; reply: string; outcome: string }[] = [];
  folders: string[] = [];
  session: unknown = null;
  proposals = new Map<string, string>();
  overview: Record<string, unknown> = {
    mode: "A", kill: false, tools_active: [], vault: { where: "local", exists: true, open: true },
    backup: { configured: true, age_days: 2 }, money_limit_eur: 0, audit: [],
  };
  facts: { id: number; text: string; kind: string; source: string; created: number }[] = [];
  deleted: number[] = [];
  dash: Record<string, unknown> = { timers: [], tasks: [], pending_approvals: 0, results: [] };
  review: unknown = null;
  diffText = "";
  folderProposal: { name: string; path: string } | null = null;
  rated = new Set<number>();
  ratings: { entry: number; rating: number }[] = [];
  sent: unknown[] = [];

  constructor(public url: string, private token = "t".repeat(43), private fail = false) {
    queueMicrotask(() => (this.fail ? this.onerror?.() : this.onopen?.()));
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
    else if (msg.type === "dashboard.get") reply = { ok: true, ...this.dash };
    else if (msg.type === "claude.folders") reply = { ok: true, folders: this.folders };
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
    else if (msg.type === "claude.status") reply = { ok: true, session: this.session };
    else if (msg.type === "claude.review") reply = { ok: true, review: this.review };
    else if (msg.type === "claude.diff") {
      const p = (msg as { path?: string }).path ?? "";
      const known = ((this.review as { files?: { path: string }[] } | null)?.files ?? []).some((f) => f.path === p);
      reply = known ? { ok: true, path: p, diff: this.diffText, truncated: false, protected: p.startsWith("src/kushim/safety/") }
                    : { ok: false, error: "not_changed" };
    }
    else if (msg.type === "claude.start") {
      const m = msg as { task?: string };
      if (/IBAN/.test(m.task ?? "")) reply = { ok: true, allowed: false, reason: "Enthält eine IBAN." };
      else { this.proposals.set("p1", m.task ?? ""); reply = { ok: true, allowed: true, proposal: "p1", kind: "start", preview: `Auftrag: «${m.task}»`, expires_in: 90 }; }
    }
    else if (msg.type === "claude.approve") {
      const m = msg as { proposal?: string; confirm?: boolean };
      if (m.confirm !== true) reply = { ok: false, error: "confirm_required" };
      else if (!m.proposal || !this.proposals.delete(m.proposal)) reply = { ok: false, error: "unknown_proposal" };
      else { this.session = { id: "s", folder: "kushim", branch: "b", turn: 1, status: "running", cost_usd: 0, seconds: 1, error: "" }; reply = { ok: true, session: this.session }; }
    }
    else if (msg.type === "claude.deny") reply = { ok: true, denied: this.proposals.delete((msg as { proposal?: string }).proposal ?? "") };
    else if (msg.type === "claude.answer") {
      const m = msg as { text?: string; allow?: string[] };
      this.proposals.set("p2", m.text ?? "");
      const extra = m.allow && m.allow.length ? ` Erlaubt: ${m.allow.join(", ")}` : "";
      reply = { ok: true, allowed: true, proposal: "p2", kind: "answer", preview: `Antwort: «${m.text}».${extra}`, expires_in: 60 };
    }
    else if (msg.type === "claude.stop") { this.session = null; reply = { ok: true, stopped: true }; }
    else if (msg.type === "feedback.add") {
      const m = msg as { entry?: number; rating?: number };
      if (this.rated.has(m.entry ?? -1)) reply = { ok: false, error: "already_rated" };
      else { this.rated.add(m.entry ?? -1); this.ratings.push({ entry: m.entry ?? -1, rating: m.rating ?? 0 }); reply = { ok: true, rated: m.entry, rating: m.rating }; }
    }
    else if (msg.type === "approvals.get") reply = { ok: true, pending: this.pending };
    else if (msg.type === "approvals.decide") {
      const m = msg as { digest?: string };
      if (!this.pending) reply = { ok: false, error: "none" };
      else if (m.digest !== this.pending.digest) reply = { ok: false, error: "stale" };
      else { this.pending = null; this.voice = { ...this.voice, state: "idle" }; reply = { ok: true, result: "started" }; }
    }
    else if (msg.type === "safety.kill") { this.kill = true; reply = { ok: true, kill: true }; }
    else if (msg.type === "safety.resume") reply = { ok: true, kill: (this.kill = false) };
    else reply = { ok: false, error: "unknown_type" };
    queueMicrotask(() => this.onmessage?.({ data: JSON.stringify(reply) }));
  }

  close(): void { queueMicrotask(() => this.onclose?.()); }
}
