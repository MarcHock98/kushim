"""API-Typ `dashboard.get`: Übersicht für die Oberfläche (nur lesen): laufende Timer, Aufgaben, Freigaben, letzte Recherchen.

Alles stammt aus dem Sprachprozess (`kushim talk --ui`) und lebt nur im Arbeitsspeicher beziehungsweise in `run/timers.json`.
Antworten enthalten nur Anzeigetext (Web-Antworten bleiben Daten, die UI zeigt sie nie als HTML und öffnet keine Links von selbst).
Keine Pfade, Schlüssel oder Notizinhalte. Das LLM hat keinen Zugang (nur die Oberfläche mit Token).
"""
from __future__ import annotations

import time
from typing import Any, Callable

from ..tasks import TaskRegistry
from ..timers import TimerStore
from ..voice.tool_commands import ToolCommands
from .protocol import ApiCore


def register_dashboard(core: ApiCore, commands: ToolCommands, timers: TimerStore, tasks: TaskRegistry,
                       clock: Callable[[], float] = time.time) -> None:
    def get(_: dict[str, Any]) -> dict[str, Any]:
        now = clock()
        try:
            due = sorted(timers.list(), key=lambda t: t.due)
        except Exception:                                  # noqa: BLE001
            due = []
        return {
            "timers": [{"id": t.id, "label": t.label, "due_in": round(t.due - now, 1)} for t in due],
            "tasks": tasks.active(),
            "pending_approvals": tasks.pending_approvals(),
            "results": list(commands.recent_results)[::-1],      # neueste zuerst
        }

    core.register("dashboard.get", get)
