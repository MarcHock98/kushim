"""API-Typen für die Freigabe-Leiste: `approvals.get` (offene Freigaben von Claude Code ansehen) und `approvals.decide`.

Läuft im selben Prozess wie die Sprach-Schleife (`kushim talk --ui`), weil nur dort die Brücke zu Claude Code und ihre offenen
Anfragen (`Bridge.permissions`) liegen. Die Oberfläche ist hier der Nutzer (mit API-Token) und sieht den genauen Text wie im
Terminal; deshalb darf sie jede Anfrage erlauben oder ablehnen (anders als der Sprachweg C3 mit seiner strengen Liste).
Regeln wie bei der alten Leiste: Die Antwort zeigt den EXAKTEN Text und dessen Hash (`digest`). Entschieden wird nur mit
`request_id` und passendem Hash, sonst "stale"; unbekannte Anfrage = "none". Erlauben braucht `confirm: true`, Ablehnen nicht.
Kein "immer erlauben". Bei aktivem Notaus wird nichts entschieden ("kill"). Alle Texte sind fremd: nur anzeigen.
Die UI führt nichts aus: `Bridge.answer` meldet die Entscheidung nur an Claude Code, das selbst handelt.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
from pathlib import Path
from typing import Any, Callable

from ..channel.bridge import Bridge, Permission
from ..channel.speakable import PREVIEW_LIMIT, describe
from ..safety import killswitch
from .protocol import ApiCore, ApiError

MAX_OPEN = 20


def digest_of(p: Permission) -> str:
    """Hash genau des angezeigten Textes (samt Anfrage-Nummer): ändert sich etwas, passt die alte Zusage nicht mehr."""
    raw = json.dumps([p.request_id, p.tool_name, p.description, p.input_preview], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _snapshot(bridge: Bridge) -> list[Permission]:
    """Kopie der offenen Anfragen; die Sprach-Schleife darf gleichzeitig anhängen oder entfernen (Sperre in der Brücke)."""
    return bridge.pending()


def truncated(p: Permission) -> bool:
    """Ist die Vorschau gekürzt (Claude Code: „…“/„⋯ elided ⋯“, oder am Längenlimit der Brücke)? Dann zeigt die Oberfläche
    nicht alles, was ausgeführt würde: Erlauben nur im Terminal, Ablehnen geht."""
    preview = p.input_preview
    return "…" in preview or "⋯" in preview or "elided" in preview or len(preview) >= PREVIEW_LIMIT


def _summary(p: Permission) -> str:
    try:
        return describe(p)
    except Exception:                              # noqa: BLE001 (die Hörhilfe darf die Anzeige nie verhindern)
        return ""


def register_approvals(core: ApiCore, bridge: Bridge, root: Path | None = None,
                       on_decision: Callable[[dict[str, str]], None] | None = None,
                       audit: Callable[[str, str], None] | None = None) -> None:
    """`on_decision({"request_id", "tool", "result", "source": "ui"})` wird nach jedem Entscheidungsversuch gerufen
    (result: "allow"/"deny" bei Erfolg, sonst der Fehlerstatus der Brücke); Fehler darin bleiben ohne Wirkung."""
    lock = threading.Lock()                        # zwei Klicks gleichzeitig: nur einer entscheidet

    def killed() -> bool:
        return root is not None and killswitch.is_triggered(root)

    def get(_: dict[str, Any]) -> dict[str, Any]:
        if killed():
            return {"pending": []}
        items = [{"request_id": p.request_id, "tool_name": p.tool_name, "description": p.description,
                  "input_preview": p.input_preview, "digest": digest_of(p), "summary": _summary(p),
                  "truncated": truncated(p)}
                 for p in _snapshot(bridge)[:MAX_OPEN]]
        return {"pending": items}

    def decide(payload: dict[str, Any]) -> dict[str, Any]:
        rid, approve, digest = payload.get("request_id"), payload.get("approve"), payload.get("digest")
        if not isinstance(rid, str) or not isinstance(approve, bool) or not isinstance(digest, str):
            raise ApiError("bad_request")
        if approve and payload.get("confirm") is not True:
            raise ApiError("confirm_required")
        if killed():
            raise ApiError("kill")
        with lock:
            perm = next((p for p in _snapshot(bridge) if p.request_id == rid), None)
            if perm is None:
                raise ApiError("none")
            if not hmac.compare_digest(digest.encode("utf-8", "replace"), digest_of(perm).encode()):
                raise ApiError("stale")
            if approve and truncated(perm):
                raise ApiError("terminal_only")    # nicht alles sichtbar: Erlauben nur im Terminal
            behavior = "allow" if approve else "deny"
            status = bridge.answer(rid, behavior)
        result = behavior if status == "ok" else status
        if audit is not None:
            try:
                audit("approval", f"ui {result}")      # nie der fremde Text
            except Exception:                          # noqa: BLE001
                pass
        if on_decision is not None:                    # C5: gleiche Begriffe wie der Sprachweg
            try:
                on_decision({"request_id": rid, "tool": perm.tool_name, "what": _summary(perm), "source": "ui",
                             "result": {"allow": "allowed", "deny": "denied", "unknown": "gone"}.get(result, result)})
            except Exception:                          # noqa: BLE001
                pass
        if status == "ok":
            return {"result": behavior}
        raise ApiError({"unknown": "none", "kill": "kill"}.get(status, "unavailable"))

    core.register("approvals.get", get)
    core.register("approvals.decide", decide)
