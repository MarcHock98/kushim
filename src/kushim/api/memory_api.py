"""API-Typen für die Gedächtnis-Ansicht: `memory.search` (nur lesen) und `memory.delete` (nur mit `confirm: true`).

Der Vault bleibt der einzige Speicher; hier gibt es keinen eigenen Zugriff, nur den übergebenen `MemoryStore`
(im Sprachprozess ein `SharedStore`, weil die API in Threads läuft). Löschen ist endgültig und braucht `confirm: true`;
die Oberfläche bietet davor 10 Sekunden zum Rückgängigmachen an (dann wird noch gar nicht gelöscht). Das Audit nennt nur die ID,
nie den Text. Das LLM hat keinen Zugang (nur die Oberfläche mit Token). Bearbeiten gibt es (noch) nicht.
"""
from __future__ import annotations

from typing import Any

from ..memory.store import MemoryStore
from .protocol import ApiCore, ApiError

MAX_RESULTS = 100
MAX_QUERY = 200
MAX_TEXT = 2000


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

    core.register("memory.search", search)
    core.register("memory.delete", delete)
