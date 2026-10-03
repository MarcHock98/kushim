"""Einzige Stelle für Netzwerkzugriff: ausschließlich Loopback (127.0.0.1 / ::1).

Vom Nutzer am 2026-10-03 ausdrücklich freigegeben (ALLOWLIST in tests/test_no_egress.py), nur für
lokale Dienste (Ollama, eigene Backend-API). Jede andere Adresse wird abgelehnt, bevor eine
Verbindung entsteht. Keine Weiterleitungen, keine Proxys, kurze Timeouts.
"""
from __future__ import annotations

import http.client
import json
from typing import Any
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


def request_json(method: str, url: str, payload: Any = None, timeout: float = 30.0) -> Any:
    host, port, path = check_url(url)
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        body = None if payload is None else json.dumps(payload).encode()
        conn.request(method, path, body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = resp.read(MAX_RESPONSE + 1)
        if len(data) > MAX_RESPONSE:
            raise ValueError("Antwort zu groß")
        if resp.status >= 400:
            raise ConnectionError(f"HTTP {resp.status}")
        return json.loads(data) if data else None
    finally:
        conn.close()
