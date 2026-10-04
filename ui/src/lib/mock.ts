// Gefälschtes Backend für Entwicklung und Tests (kein Netz). Antwortet wie `ApiCore`: Token zuerst, neutrale Fehler.
import type { Socket } from "./api";

export class MockSocket implements Socket {
  onmessage: Socket["onmessage"] = null;
  onclose: Socket["onclose"] = null;
  onopen: Socket["onopen"] = null;
  onerror: Socket["onerror"] = null;
  kill = false;
  voice: { active: boolean; state: string; level: number } = { active: false, state: "idle", level: 0 };
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
    else if (msg.type === "safety.kill") { this.kill = true; reply = { ok: true, kill: true }; }
    else if (msg.type === "safety.resume") reply = { ok: true, kill: (this.kill = false) };
    else reply = { ok: false, error: "unknown_type" };
    queueMicrotask(() => this.onmessage?.({ data: JSON.stringify(reply) }));
  }

  close(): void { queueMicrotask(() => this.onclose?.()); }
}
