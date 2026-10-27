"""Einzige Stelle für Netzwerkzugriff: ausschließlich Loopback (127.0.0.1 / ::1).

Vom Nutzer am 2026-10-03 ausdrücklich freigegeben (ALLOWLIST in tests/test_no_egress.py), nur für
lokale Dienste (heute: der kushim-Channel für Claude Code, siehe `bridge.py`). Jede andere Adresse wird abgelehnt, bevor eine
Verbindung entsteht. Keine Weiterleitungen, keine Proxys, kurze Timeouts.
"""
from __future__ import annotations

import http.client
import json
from typing import Any, Iterator
from urllib.parse import urlsplit

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
MAX_RESPONSE = 8 * 1024 * 1024


class NotLoopback(Exception):
    pass


def check_url(url: str) -> tuple[str, int, str]:
    u = urlsplit(url)
    if u.scheme != "http" or u.hostname not in LOOPBACK_HOSTS or u.username or u.password:
        raise NotLoopback(f"Nur http auf Loopback erlaubt: {u.scheme}://{u.hostname}")
    host = "127.0.0.1" if u.hostname == "localhost" else u.hostname   # kein DNS
    path = (u.path or "/") + (f"?{u.query}" if u.query else "")
    return host, u.port or 80, path


class HttpError(ConnectionError):
    """Antwort mit Fehlerstatus; `status` erlaubt dem Aufrufer, z. B. Notaus (423) von Fehlern zu unterscheiden."""

    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status = status


def request_json(method: str, url: str, payload: Any = None, timeout: float = 30.0,
                 headers: dict[str, str] | None = None) -> Any:
    host, port, path = check_url(url)
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        body = None if payload is None else json.dumps(payload).encode()
        conn.request(method, path, body=body, headers={"Content-Type": "application/json", **(headers or {})})
        resp = conn.getresponse()
        data = resp.read(MAX_RESPONSE + 1)
        if len(data) > MAX_RESPONSE:
            raise ValueError("Antwort zu groß")
        if resp.status >= 400:
            raise HttpError(resp.status)
        return json.loads(data) if data else None
    finally:
        conn.close()


MAX_LINE = 1024 * 1024


def stream_json_lines(method: str, url: str, payload: Any = None, timeout: float = 60.0) -> Iterator[Any]:
    """Wie request_json, liefert aber zeilenweise JSON (NDJSON), z. B. Ollama-Streaming."""
    host, port, path = check_url(url)
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        body = None if payload is None else json.dumps(payload).encode()
        conn.request(method, path, body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        if resp.status >= 400:
            raise ConnectionError(f"HTTP {resp.status}")
        while True:
            line = resp.readline(MAX_LINE + 1)
            if not line:
                return
            if len(line) > MAX_LINE:
                raise ValueError("Zeile zu groß")
            if line.strip():
                yield json.loads(line)
    finally:
        conn.close()
