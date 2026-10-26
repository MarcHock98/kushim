"""API-Typen für die Gedächtnis-Ansicht: `memory.search` (nur lesen), `memory.update` und `memory.delete` (beide nur mit `confirm: true`).

Der Vault bleibt der einzige Speicher; hier gibt es keinen eigenen Zugriff, nur den übergebenen `MemoryStore`
(im Sprachprozess ein `SharedStore`, weil die API in Threads läuft). Löschen ist endgültig und braucht `confirm: true`;
die Oberfläche bietet davor 10 Sekunden zum Rückgängigmachen an (dann wird noch gar nicht gelöscht). Das Audit nennt nur die ID,
nie den Text. Das LLM hat keinen Zugang (nur die Oberfläche mit Token). Beim Bearbeiten gilt der Eintrag danach als vom Nutzer bestätigt; das Audit nennt nur die ID.
"""
from __future__ import annotations

from typing import Any

from ..memory.store import MemoryStore
from .protocol import ApiCore, ApiError

MAX_RESULTS = 100
MAX_QUERY = 200
MAX_TEXT = 2000
KINDS = ("preference", "decision", "person", "routine", "other")


def register_memory(core: ApiCore, store: MemoryStore) -> None:
    def search(payload: dict[str, Any]) -> dict[str, Any]:
        query = payload.get("query", "")
        limit = payload.get("limit", 50)
        if not isinstance(query, str) or len(query) > MAX_QUERY or isinstance(limit, bool) or not isinstance(limit, int):
            raise ApiError("bad_request")
        try:
            facts = store.search_facts(query, max(1, min(limit, MAX_RESULTS)))
        except Exception:                                  # noqa: BLE001 (nie Interna nach außen)
            raise ApiError("unavailable")
        return {"facts": [{"id": f.id, "text": f.text[:MAX_TEXT], "kind": f.kind, "source": f.source, "created": f.created}
                          for f in facts]}

    def delete(payload: dict[str, Any]) -> dict[str, Any]:
        fid = payload.get("id")
        if isinstance(fid, bool) or not isinstance(fid, int) or fid < 0:
            raise ApiError("bad_request")
        if payload.get("confirm") is not True:
            raise ApiError("confirm_required")
        try:
            store.delete_fact(fid)
            store.audit("memory_delete", f"id={fid}")
        except Exception:                                  # noqa: BLE001
            raise ApiError("unavailable")
        return {"deleted": fid}

    def update(payload: dict[str, Any]) -> dict[str, Any]:
        fid, text, kind = payload.get("id"), payload.get("text"), payload.get("kind")
        if isinstance(fid, bool) or not isinstance(fid, int) or fid < 0 or not isinstance(text, str):
            raise ApiError("bad_request")
        text = " ".join("".join(ch if ch.isprintable() else " " for ch in text).split())
        if not text or len(text) > MAX_TEXT or not (kind is None or kind in KINDS):
            raise ApiError("bad_request")
        if payload.get("confirm") is not True:
            raise ApiError("confirm_required")                 # überschreibt den alten Text endgültig
        try:
            found = store.update_fact(fid, text, kind)
            if found:
                store.audit("memory_update", f"id={fid}")
        except Exception:                                      # noqa: BLE001
            raise ApiError("unavailable")
        if not found:
            raise ApiError("not_found")
        return {"updated": fid}

    core.register("memory.search", search)
    core.register("memory.update", update)
    core.register("memory.delete", delete)
