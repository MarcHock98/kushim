"""Die zuletzt gezeigten Ansichten (Bühne). Die Bridge legt geprüfte Ansichten ab, die API (`stage.get`) liest sie.

Jede Änderung bekommt eine fortlaufende Nummer (`seq`). Die Oberfläche fragt „alles seit seq N“ ab. Dieselbe `id` ersetzt
die alte Ansicht (live), `schliessen` entfernt sie. Höchstens MAX_VIEWS Ansichten bleiben, älteste fallen weg.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

MAX_VIEWS = 20


class ViewStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()                  # Sprach-Thread schreibt, API-Threads lesen
        self._seq = 0
        self._views: OrderedDict[str, tuple[int, dict[str, Any]]] = OrderedDict()

    def put(self, view: dict[str, Any]) -> int:
        """Legt eine geprüfte Ansicht ab (aus `schema.validate`) und gibt ihre neue Nummer zurück."""
        with self._lock:
            self._seq += 1
            self._views.pop(view["id"], None)
            self._views[view["id"]] = (self._seq, view)
            while len(self._views) > MAX_VIEWS:
                self._views.popitem(last=False)
            return self._seq

    def since(self, seq: int) -> tuple[list[dict[str, Any]], int]:
        """(Ansichten mit Nummer > seq, älteste zuerst; jeweils mit `seq`), letzte vergebene Nummer."""
        with self._lock:
            items = [{"seq": s, **v} for s, v in self._views.values() if s > seq]
            return items, self._seq

    def clear(self) -> None:
        """Notaus: alles vergessen, auch die Nummern laufen weiter (die Oberfläche räumt selbst ab)."""
        with self._lock:
            self._views.clear()
