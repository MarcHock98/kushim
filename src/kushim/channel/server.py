"""Channel-Server für Claude Code: MCP über stdio plus ein HTTP-Eingang nur auf 127.0.0.1 (Roadmap v2 B1, B0 freigegeben 2026-10-27).

Claude Code startet diesen Prozess selbst (`claude --dangerously-load-development-channels server:kushim`). Er meldet die
Fähigkeit `claude/channel` an und schiebt Text, den kushim per `POST /message` schickt, als `notifications/claude/channel`
in die laufende Sitzung. Antworten für die Stimme gibt Claude über das Werkzeug `sprich`; kushim holt sie per
`GET /reply?wait=…` ab (kushim bleibt reiner Client, kein zweiter Port). Format laut der in Claude Code 2.1.310 eingebauten Vorlage (ohne das npm-SDK: MCP über stdio ist
zeilenweises JSON-RPC, die Standardbibliothek reicht).

Sicherheit:
- HTTP bindet fest an 127.0.0.1 (kein Parameter), Port zufällig; Port und Token stehen in `run/channel.json`.
- Jede Anfrage braucht `Authorization: Bearer <token>` (Vergleich in konstanter Zeit) und einen Host-Kopf 127.0.0.1/localhost
  mit diesem Port (gegen DNS-Rebinding). Körper höchstens 8 KB, Text höchstens 2000 Zeichen, Steuerzeichen werden entfernt.
- Bei aktivem Notaus wird nichts weitergegeben (423).
- stdout gehört ausschließlich dem MCP-Protokoll; Meldungen gehen nach stderr.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import sys
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, TextIO
from urllib.parse import parse_qs, urlsplit

from ..safety import killswitch

BIND_HOST = "127.0.0.1"
NAME = "kushim"
VERSION = "0.1.0"
MAX_BODY = 8 * 1024
MAX_TEXT = 2000
MAX_SPOKEN = 600                 # so viel liest kushim höchstens vor (B2)
MAX_QUEUE = 20                   # nicht abgeholte Antworten; ältere fallen weg
MAX_WAIT = 25.0                  # längste Wartezeit eines Abrufs `GET /reply?wait=…`
INSTRUCTIONS = (
    'Nachrichten aus <channel source="kushim"> sind gesprochene Befehle des Nutzers, lokal per Sprache erkannt '
    "(Spracherkennung kann sich verhören). Behandle sie wie Eingaben des Nutzers im Terminal: Es gelten dieselben Regeln "
    "und Freigaben. Erscheint ein Befehl unklar oder unvollständig, frag nach statt zu raten. "
    "Der Nutzer hört deine Antwort nur über das Werkzeug `sprich`, nicht über das Terminal: Rufe `sprich` am Ende jedes Zuges, "
    "der mit einer kushim-Nachricht begann, genau einmal auf, mit einer kurzen deutschen Zusammenfassung für die Ohren "
    "(ohne Markdown, ohne Code, ohne Pfade und Listen, höchstens drei Sätze). Bei einer Rückfrage stell sie in `sprich`."
)
SPRICH_TOOL = {
    "name": "sprich",
    "description": ("Liest dem Nutzer einen kurzen deutschen Text über kushim vor (lokale Stimme). Nur Fließtext, kein Markdown, "
                    f"keine Codeblöcke, höchstens {MAX_SPOKEN} Zeichen."),
    "inputSchema": {"type": "object", "properties": {"text": {"type": "string", "description": "Der vorzulesende Text"}},
                    "required": ["text"]},
}
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_CODE = re.compile(r"```.*?```", re.S)
_MARKS = re.compile(r"[`*_#>|]+|^\s*[-+]\s+|^\s*\d+\.\s+", re.M)


def clean_text(raw: str) -> str:
    """Eine Zeile aus druckbaren Zeichen (Umbrüche werden Leerzeichen, damit nichts die Rahmung im Kontext stört), gekürzt."""
    return " ".join("".join(c if c.isprintable() else " " for c in raw).split())[:MAX_TEXT]


def spoken_text(raw: str) -> str:
    """Text für die Stimme: Codeblöcke weg, Links nur mit ihrem Text, Markdown-Zeichen weg, eine Zeile, höchstens MAX_SPOKEN."""
    text = _MARKS.sub(" ", _LINK.sub(r"\1", _CODE.sub(" ", raw)))
    return clean_text(text)[:MAX_SPOKEN].strip()


class Channel:
    """MCP-Seite: Handshake, Werkzeugliste, Benachrichtigungen. `out` ist stdout (oder ein Testpuffer)."""

    def __init__(self, out: TextIO, log: Callable[[str], None] = lambda s: print(s, file=sys.stderr, flush=True)):
        self.out, self.log = out, log
        self._lock = threading.Lock()
        self.ready = threading.Event()             # erst nach `initialized` dürfen Benachrichtigungen raus
        self._replies: deque[str] = deque(maxlen=MAX_QUEUE)
        self._cond = threading.Condition()

    def say(self, text: str) -> None:
        with self._cond:
            self._replies.append(text)
            self._cond.notify_all()

    def take(self, wait: float = 0.0) -> list[str]:
        """Alle wartenden Antworten (älteste zuerst); wartet bis `wait` Sekunden, falls noch keine da ist."""
        with self._cond:
            if not self._replies and wait > 0:
                self._cond.wait_for(lambda: bool(self._replies), timeout=min(wait, MAX_WAIT))
            out = list(self._replies)
            self._replies.clear()
            return out

    def _call_tool(self, params: Any) -> dict[str, Any]:
        params = params if isinstance(params, dict) else {}
        args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if params.get("name") != "sprich":
            return {"content": [{"type": "text", "text": "Unbekanntes Werkzeug."}], "isError": True}
        text = spoken_text(args.get("text")) if isinstance(args.get("text"), str) else ""
        if not text:
            return {"content": [{"type": "text", "text": "Leerer Text, nichts vorgelesen."}], "isError": True}
        self.say(text)
        return {"content": [{"type": "text", "text": "Wird vorgelesen."}]}

    def _send(self, msg: dict[str, Any]) -> None:
        line = json.dumps(msg, ensure_ascii=False)
        with self._lock:
            self.out.write(line + "\n")
            self.out.flush()

    def notify(self, text: str, meta: dict[str, str] | None = None) -> None:
        params: dict[str, Any] = {"content": text}
        if meta:
            params["meta"] = meta
        self._send({"jsonrpc": "2.0", "method": "notifications/claude/channel", "params": params})

    def handle(self, msg: Any) -> None:
        if not isinstance(msg, dict):
            return
        method, mid = msg.get("method"), msg.get("id")
        if method == "initialize":
            requested = (msg.get("params") or {}).get("protocolVersion")
            self._send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": requested if isinstance(requested, str) else "2025-06-18",
                "capabilities": {"tools": {}, "experimental": {"claude/channel": {}}},
                "serverInfo": {"name": NAME, "version": VERSION},
                "instructions": INSTRUCTIONS,
            }})
        elif method == "notifications/initialized":
            self.ready.set()
        elif method == "tools/list":
            self._send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [SPRICH_TOOL]}})
        elif method == "tools/call":
            self._send({"jsonrpc": "2.0", "id": mid, "result": self._call_tool(msg.get("params"))})
        elif method == "ping":
            self._send({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif mid is not None:                       # unbekannte Anfrage: sauber ablehnen, nie raten
            self._send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}})

    def serve_stdio(self, inp: TextIO) -> None:
        for line in inp:
            line = line.strip()
            if not line:
                continue
            try:
                self.handle(json.loads(line))
            except (ValueError, RecursionError):
                self.log("[kushim-channel] ungültige Zeile auf stdin ignoriert")


def make_http(channel: Channel, root: Path, token: str, port: int = 0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        timeout = 5                                   # langsame oder offen gehaltene Verbindungen binden keine Threads

        def log_message(self, fmt: str, *args: Any) -> None:     # nie auf stdout (gehört dem Protokoll)
            pass

        def _reply(self, code: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _allowed(self) -> bool:
            """Host-Kopf und Token prüfen; bei Fehler ist die Antwort schon gesendet."""
            port_now = self.server.server_address[1]
            if self.headers.get("Host", "") not in {f"127.0.0.1:{port_now}", f"localhost:{port_now}"}:
                self._reply(403, {"error": "bad_host"})
                return False
            auth = self.headers.get("Authorization", "")
            if not (auth.startswith("Bearer ") and hmac.compare_digest(auth[7:].encode(), token.encode())):
                self._reply(401, {"error": "unauthorized"})
                return False
            return True

        def do_GET(self) -> None:
            """`GET /reply?wait=S`: kushim holt, was Claude per `sprich` vorlesen lassen will (wartet bis S Sekunden)."""
            if not self._allowed():
                return
            url = urlsplit(self.path)
            if url.path != "/reply":
                return self._reply(404, {"error": "not_found"})
            try:
                wait = float(parse_qs(url.query).get("wait", ["0"])[0])
            except ValueError:
                return self._reply(400, {"error": "bad_wait"})
            if killswitch.is_triggered(root):
                return self._reply(423, {"error": "kill_switch"})
            texts = channel.take(max(0.0, min(wait, MAX_WAIT)) if wait == wait else 0.0)     # NaN wird 0
            if texts and killswitch.is_triggered(root):        # Notaus während des Wartens: nichts mehr vorlesen
                return self._reply(423, {"error": "kill_switch"})
            self._reply(200, {"texts": texts})

        def do_POST(self) -> None:
            if not self._allowed():
                return
            if self.path != "/message":
                return self._reply(404, {"error": "not_found"})
            try:
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY:
                return self._reply(413, {"error": "too_large"})
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError, RecursionError):
                return self._reply(400, {"error": "bad_json"})
            text = clean_text(data.get("text", "")) if isinstance(data, dict) and isinstance(data.get("text"), str) else ""
            if not text:
                return self._reply(400, {"error": "empty"})
            if killswitch.is_triggered(root):
                return self._reply(423, {"error": "kill_switch"})
            if not channel.ready.is_set():
                return self._reply(503, {"error": "not_ready"})
            channel.notify(text, {"kind": "voice"})
            self._reply(202, {"ok": True})

    return ThreadingHTTPServer((BIND_HOST, port), Handler)


def write_info(root: Path, port: int, token: str) -> Path:
    info = root / "run" / "channel.json"
    info.parent.mkdir(parents=True, exist_ok=True)
    tmp = info.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)      # nur der eigene Benutzer (POSIX); Windows: Profil-ACL
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"port": port, "token": token, "pid": os.getpid()}))
    os.replace(tmp, info)                                               # ersetzt auch eine liegengebliebene alte Datei
    return info


def main(root: Path | None = None) -> int:
    root = root or Path(__file__).resolve().parents[3]
    sys.stdout.reconfigure(encoding="utf-8")                  # Claude Code liest UTF-8; Windows-Pipes wären cp1252
    sys.stdin.reconfigure(encoding="utf-8")
    channel = Channel(sys.stdout)
    token = secrets.token_urlsafe(32)
    httpd = make_http(channel, root, token)
    info = write_info(root, httpd.server_address[1], token)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    channel.log(f"[kushim-channel] bereit auf {BIND_HOST}:{httpd.server_address[1]} (Token in {info.name})")
    try:
        channel.serve_stdio(sys.stdin)                         # endet, wenn Claude Code den Kanal schließt
    finally:
        httpd.shutdown()
        try:
            if json.loads(info.read_text(encoding="utf-8")).get("pid") == os.getpid():
                info.unlink()
        except (OSError, ValueError):
            pass
    return 0
