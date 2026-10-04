"""API-Typen für laufende Aufgaben: ansehen und abbrechen (transportunabhängig, hängen am `ApiCore`).

`tasks.cancel` ist immer erlaubt (mit Token): Abbrechen ist sicher und sperrt nichts (der Notaus ist `safety.kill`).
Es beendet laufende Aufgaben und lehnt offene Freigaben ab. Antworten enthalten nur Namen und Zähler.
"""
from __future__ import annotations

from typing import Any

from ..tasks import TaskRegistry
from .protocol import ApiCore


def register_tasks(core: ApiCore, tasks: TaskRegistry) -> None:
    def listing(_: dict[str, Any]) -> dict[str, Any]:
        return {"tasks": tasks.active(), "pending_approvals": tasks.pending_approvals()}

    def cancel(_: dict[str, Any]) -> dict[str, Any]:
        return {"cancelled": tasks.cancel_all()}

    core.register("tasks.list", listing)
    core.register("tasks.cancel", cancel)
