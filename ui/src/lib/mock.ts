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
    else if (msg.type === "claude.folders") reply = { ok: true, folders: this.folders };
    else if (msg.type === "claude.status") reply = { ok: true, session: this.session };
    else if (msg.type === "claude.review") reply = { ok: true, review: null };
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
