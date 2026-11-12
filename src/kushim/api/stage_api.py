"""API-Typ `stage.get`: Ansichten, die Claude Code zeigen lässt (nur lesen).

Anfrage {"since": N}; Antwort {"items": [...], "last": M}. `items` sind geprüfte Ansichten (stage/schema.py) mit ihrer
Nummer `seq`; eine Ansicht mit `schliessen: true` heißt: abräumen. Bei Notaus liefert die Bridge ohnehin nichts Neues.
"""
from __future__ import annotations

from typing import Any

from ..safety import killswitch
from ..stage.store import ViewStore
from .protocol import ApiCore, ApiError


def register_stage(core: ApiCore, store: ViewStore, root: Any = None) -> None:
    def get(msg: dict[str, Any]) -> dict[str, Any]:
        since = msg.get("since", 0)
        if isinstance(since, bool) or not isinstance(since, int) or since < 0:
            raise ApiError("bad_since")
        if root is not None and killswitch.is_triggered(root):
            store.clear()                                   # Notaus: nichts mehr zeigen
            return {"items": [], "last": store.since(10 ** 12)[1]}
        items, last = store.since(since)
        return {"items": items, "last": last}

    core.register("stage.get", get)
