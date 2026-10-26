"""API-Typen für die Freigabe-Leiste: `approvals.get` (offene Freigabe ansehen) und `approvals.decide` (entscheiden).

Läuft im selben Prozess wie die Sprach-Schleife (`kushim talk --ui`), weil nur dort die wartende Freigabe liegt.
Regeln: Die Antwort zeigt den EXAKTEN Vorschautext, den Hash dieses Textes und die Restzeit. Entschieden wird nur für genau
diesen Hash (`digest`), sonst "stale". Erlauben braucht `confirm: true`; Ablehnen ist immer möglich. Es gibt kein "immer erlauben".
Das LLM hat keinen Zugang (nur die Oberfläche mit Token).
"""
from __future__ import annotations

from typing import Any

from ..voice.tool_commands import ToolCommands
from .protocol import ApiCore, ApiError


def register_approvals(core: ApiCore, commands: ToolCommands) -> None:
    def get(_: dict[str, Any]) -> dict[str, Any]:
        return {"pending": commands.pending_view()}

    def decide(payload: dict[str, Any]) -> dict[str, Any]:
        approve, digest = payload.get("approve"), payload.get("digest")
        if not isinstance(approve, bool) or not isinstance(digest, str):
            raise ApiError("bad_request")
        if approve and payload.get("confirm") is not True:
            raise ApiError("confirm_required")
        result = commands.decide(approve, digest)
        if result in ("none", "stale"):
            raise ApiError(result)                       # nichts wartet mehr oder die Vorschau hat sich geändert
        return {"result": result}

    core.register("approvals.get", get)
    core.register("approvals.decide", decide)
