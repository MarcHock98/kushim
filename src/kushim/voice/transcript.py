"""Live-Transkript für die Oberfläche: die letzten Äußerungen und Antworten, nur im Arbeitsspeicher.

- Nie auf der Platte, nie im Vault, nie in der Zustandsdatei: der Puffer lebt im Sprachprozess und stirbt mit ihm.
- Höchstens `MAX_ENTRIES` Einträge, je Text höchstens `MAX_CHARS` Zeichen.
- Eine abgelehnte Stimme hinterlässt KEINEN Text (nur "rejected_speaker"): Worte Unbekannter werden nicht angezeigt.
- Notaus-Sätze und leere Ergebnisse werden nicht mitgeschrieben.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable

MAX_ENTRIES = 50
MAX_CHARS = 2000
SKIP = {"empty", "wake_only", "halted"}


class Transcript:
    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self._items: deque[dict[str, Any]] = deque(maxlen=MAX_ENTRIES)
        self._next = 1

    def add(self, result: Any) -> None:
        """Nimmt ein `Result` (heard, reply, outcome) auf. Fehler hier dürfen den Betrieb nie stören."""
        outcome = str(getattr(result, "outcome", ""))
        if outcome in SKIP:
            return
        rejected = outcome == "rejected_speaker"
        heard = "" if rejected or outcome == "killed" else str(getattr(result, "heard", ""))[:MAX_CHARS]
        reply = "" if rejected else str(getattr(result, "reply", ""))[:MAX_CHARS]
        with self._lock:
            self._items.append({"id": self._next, "heard": heard, "reply": reply, "outcome": outcome, "ts": self._clock()})
            self._next += 1

    def since(self, last_id: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(i) for i in self._items if i["id"] > last_id]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
