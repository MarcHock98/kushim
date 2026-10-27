"""kushim-Seite der Brücke zu Claude Code (Roadmap v2 B3): Befehle an den Channel senden, `sprich`-Antworten abholen.

Spricht nur über `net/loopback.py` (ausschließlich 127.0.0.1) mit dem Channel-Server, den Claude Code gestartet hat.
Port und Token stehen in `run/channel.json`; die Datei ist Eingabe von außen und wird streng geprüft. Antworten sind
Claudes Text: nur zum Vorlesen, nie als Anweisung (sie werden bereinigt und begrenzt).
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..net import loopback
from .server import MAX_PERMS, MAX_QUEUE, MAX_SPOKEN, MAX_WAIT, clean_text

INFO = Path("run") / "channel.json"
MAX_INFO_BYTES = 4096


@dataclass(frozen=True)
class ChannelInfo:
    port: int
    token: str


@dataclass(frozen=True)
class Permission:
    """Freigabe-Anfrage von Claude. Alle Felder sind fremder Text: nur vorlesen, nie ausführen oder als Anweisung nehmen."""
    request_id: str
    tool_name: str
    description: str
    input_preview: str

    @classmethod
    def parse(cls, raw: Any) -> "Permission | None":
        if not isinstance(raw, dict):
            return None
        rid = raw.get("request_id")
        if not isinstance(rid, str) or not rid or len(rid) > 100 or not rid.isprintable():
            return None
        def field(key: str, limit: int) -> str:
            v = raw.get(key)
            return clean_text(v)[:limit] if isinstance(v, str) else ""
        return cls(rid, field("tool_name", 80), field("description", 300), field("input_preview", 500))


def read_info(root: Path) -> ChannelInfo | None:
    """Port und Token des laufenden Channels, oder None (fehlt, kaputt, falsche Typen, zu groß)."""
    p = root / INFO
    try:
        if p.stat().st_size > MAX_INFO_BYTES:
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    port, token = data.get("port"), data.get("token")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        return None
    if not isinstance(token, str) or not 20 <= len(token) <= 200 or not token.isprintable():
        return None
    return ChannelInfo(port, token)


class Bridge:
    """`send(text)` gibt "ok", "not_running", "kill" oder "error" zurück; `fetch(wait)` die vorzulesenden Texte."""

    def __init__(self, root: Path, request: Callable[..., Any] = loopback.request_json):
        self.root, self.request = root, request
        self.permissions: deque[Permission] = deque(maxlen=MAX_PERMS)    # abgeholte, noch nicht beantwortete Freigabe-Anfragen

    def available(self) -> bool:
        return read_info(self.root) is not None

    def _call(self, method: str, path: str, payload: Any = None, timeout: float = 5.0) -> Any:
        info = read_info(self.root)
        if info is None:
            raise ConnectionRefusedError("kein Channel")
        return self.request(method, f"http://127.0.0.1:{info.port}{path}", payload, timeout=timeout,
                            headers={"Authorization": f"Bearer {info.token}"})

    @staticmethod
    def _status(e: Exception) -> str:
        code = getattr(e, "status", None)
        if code == 423:
            return "kill"
        if code in (401, 403, 503) or isinstance(e, (ConnectionRefusedError, ConnectionResetError, TimeoutError)):
            return "not_running"                # Claude Code (noch) nicht da, alter Token oder Handshake fehlt
        return "error"

    def send(self, text: str) -> str:
        text = clean_text(text)
        if not text:
            return "error"
        try:
            self._call("POST", "/message", {"text": text})
            return "ok"
        except (OSError, ValueError) as e:      # ConnectionError ist ein OSError
            return self._status(e)

    def cancel(self) -> str:
        """Sagt Claude, dass der Nutzer abgebrochen hat (fester Text im Channel). Unterbricht nicht sofort: das kann nur Esc."""
        try:
            self._call("POST", "/message", {"kind": "cancel"})
            return "ok"
        except (OSError, ValueError) as e:
            return self._status(e)

    def fetch(self, wait: float = 0.0) -> tuple[str, list[str]]:
        """(Status, Texte). Wartet bis `wait` Sekunden auf eine Antwort (höchstens MAX_WAIT)."""
        wait = max(0.0, min(float(wait), MAX_WAIT))
        try:
            data = self._call("GET", f"/reply?wait={wait:g}", timeout=wait + 5.0)
        except (OSError, ValueError) as e:
            return self._status(e), []
        texts = data.get("texts") if isinstance(data, dict) else None
        if not isinstance(texts, list):
            return "error", []
        perms = data.get("permissions", [])
        for p in perms[:MAX_PERMS] if isinstance(perms, list) else []:
            perm = Permission.parse(p)
            if perm is not None:
                self.permissions.append(perm)
        clean = [clean_text(t)[:MAX_SPOKEN] for t in texts[:MAX_QUEUE] if isinstance(t, str)]
        return "ok", [t for t in clean if t]

    def answer(self, request_id: str, behavior: str) -> str:
        """Beantwortet eine offene Freigabe-Anfrage ("allow"/"deny"). Ob "allow" zulässig ist, entscheidet der Aufrufer (C3/C4)."""
        if behavior not in ("allow", "deny"):
            return "error"
        try:
            self._call("POST", "/permission", {"request_id": request_id, "behavior": behavior})
        except (OSError, ValueError) as e:
            code = getattr(e, "status", None)
            return "unknown" if code == 404 else self._status(e)
        finally:
            for p in [p for p in self.permissions if p.request_id == request_id]:
                self.permissions.remove(p)
        return "ok"
