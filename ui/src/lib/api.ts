// Client für die Backend-API (`kushim serve`): nur ws://127.0.0.1, Token nur im Speicher.
// Die UI führt nichts selbst aus, sie sendet nur Anfragen {type, ...}; das Backend entscheidet.

export interface Credentials { port: number; token: string }
export type ApiReply = { ok: true; [k: string]: unknown } | { ok: false; error: string };

export interface Socket {
  send(data: string): void;
  close(): void;
  onmessage: ((e: { data: unknown }) => void) | null;
  onclose: (() => void) | null;
  onopen: (() => void) | null;
  onerror: (() => void) | null;
}
export type SocketFactory = (url: string) => Socket;

const TIMEOUT_MS = 10_000;

export class ApiClient {
  private sock: Socket | null = null;
  private waiting: Array<(r: ApiReply) => void> = [];
  onDisconnect: () => void = () => {};

  constructor(private creds: Credentials, private make: SocketFactory = (u) => new WebSocket(u) as unknown as Socket) {
    if (!Number.isInteger(creds.port) || creds.port < 1 || creds.port > 65535) throw new Error("bad port");
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      const s = this.make(`ws://127.0.0.1:${this.creds.port}`);   // Host ist fest, nie aus Eingaben
      this.sock = s;
      s.onopen = () => resolve();
      s.onerror = () => reject(new Error("offline"));
      s.onmessage = (e) => {
        const next = this.waiting.shift();           // der Server antwortet in Reihenfolge
        if (!next) return;
        try { next(JSON.parse(String(e.data)) as ApiReply); } catch { next({ ok: false, error: "bad_reply" }); }
      };
      s.onclose = () => {
        this.sock = null;
        this.waiting.splice(0).forEach((w) => w({ ok: false, error: "offline" }));
        this.onDisconnect();
      };
    });
  }

  call(type: string, data: Record<string, unknown> = {}): Promise<ApiReply> {
    const s = this.sock;
    if (!s) return Promise.resolve({ ok: false, error: "offline" });
    return new Promise((resolve) => {
      let done = false;
      const finish = (r: ApiReply) => { if (!done) { done = true; clearTimeout(t); resolve(r); } };
      const t = setTimeout(() => {
        finish({ ok: false, error: "timeout" });
        s.close();                                   // Antworten wären sonst verschoben: neu verbinden
      }, TIMEOUT_MS);
      this.waiting.push(finish);
      s.send(JSON.stringify({ ...data, type, token: this.creds.token }));
    });
  }

  close(): void { this.sock?.close(); }
}
