"""API-Typen für die Werkzeug-Verwaltung (transportunabhängig, hängen am `ApiCore`).

`tools.list` zeigt Name, Titel, Beschreibung, ob Daten nach außen gehen, ob das Tool verfügbar und ob es aktiv ist.
`tools.set` schaltet ein (nur mit `confirm: true`) oder aus (immer sofort). Antworten enthalten keine Pfade oder Schlüssel;
Fehler sind kurze feste Codes. Das LLM hat keinen Zugang zu diesen Typen (nur die Oberfläche mit Token).
"""
from __future__ import annotations

from typing import Any, Callable

from ..tools.registry import ToolNotAllowed, ToolRegistry
from .protocol import ApiCore, ApiError


def register_tools(core: ApiCore, registry: ToolRegistry, persist: Callable[[list[str]], None]) -> None:
    def listing() -> dict[str, Any]:
        out = []
        for t in registry.tools.values():
            why = t.available()
            out.append({"name": t.name, "title": t.title, "description": t.description,
                        "sends_data_out": t.sends_data_out, "available": not why, "reason": why,
                        "enabled": registry.is_enabled(t.name), "active": registry.is_active(t.name)})
        return {"tools": out}

    def tools_list(_: dict[str, Any]) -> dict[str, Any]:
        return listing()

    def tools_set(payload: dict[str, Any]) -> dict[str, Any]:
        name, on = payload.get("name"), payload.get("enabled")
        if not isinstance(name, str) or not isinstance(on, bool):
            raise ApiError("bad_request")
        try:
            registry.set_enabled(name, on, confirmed=payload.get("confirm") is True, persist=persist)
        except ToolNotAllowed as e:
            raise ApiError(e.code)
        except Exception:                      # z. B. Konfigurationsdatei nicht beschreibbar: Zustand bleibt unverändert
            raise ApiError("not_saved")
        return listing()

    core.register("tools.list", tools_list)
    core.register("tools.set", tools_set)
