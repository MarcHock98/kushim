"""Transportunabhängiger Kern der Backend-API: Token-Prüfung und Nachrichten-Dispatch.

Der eigentliche WebSocket-Server (nur 127.0.0.1) braucht einen Netzwerk-Import und damit einen
Eintrag in der ALLOWLIST von tests/test_no_egress.py. Das gibt nur der Nutzer frei.
Hier: Default-Deny. Ohne gültiges Token wird nichts ausgeführt, unbekannte Typen werden abgelehnt,
jede Ausnahme im Handler wird zu einer neutralen Fehlerantwort (keine Interna nach außen).
"""
from __future__ import annotations

import hmac
import json
import secrets
from typing import Any, Callable

MAX_MESSAGE_BYTES = 64 * 1024

Handler = Callable[[dict[str, Any]], dict[str, Any]]


class ApiError(Exception):
    """Ein Handler lehnt ab: nur ein kurzer fester Code geht nach außen (z. B. "bad_step"), nie Text oder Pfade."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def new_token() -> str:
    return secrets.token_urlsafe(32)


class ApiCore:
    def __init__(self, token: str):
        if len(token) < 32:
            raise ValueError("Token zu kurz")
        self._token = token
        self._handlers: dict[str, Handler] = {}

    def register(self, msg_type: str, handler: Handler) -> None:
        self._handlers[msg_type] = handler

    def token_ok(self, candidate: Any) -> bool:
        return isinstance(candidate, str) and hmac.compare_digest(
            candidate.encode(), self._token.encode())

    def handle(self, raw: str | bytes) -> str:
        """Verarbeitet eine JSON-Nachricht {"token", "type", ...} und liefert JSON zurück."""
        if len(raw) > MAX_MESSAGE_BYTES:
            return _err("too_large")
        try:
            msg = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return _err("bad_json")
        if not isinstance(msg, dict):
            return _err("bad_json")
        if not self.token_ok(msg.get("token")):
            return _err("unauthorized")
        handler = self._handlers.get(msg.get("type"))
        if handler is None:
            return _err("unknown_type")
        payload = {k: v for k, v in msg.items() if k != "token"}
        try:
            return json.dumps({"ok": True, **handler(payload)})
        except ApiError as e:
            return _err(e.code)
        except Exception:
            return _err("internal")


def _err(code: str) -> str:
    return json.dumps({"ok": False, "error": code})
