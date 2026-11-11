"""Antwortweg über Claude Code (Roadmap v2 B4): Befehl über die Brücke senden, Quittung sprechen, `sprich`-Antwort vorlesen.

Ersetzt den Platzhalter `not_connected` in der Pipeline. Wartet in kurzen Abständen (POLL Sekunden) auf Claudes Antwort,
damit "abbrechen" und der Notaus schnell greifen. Braucht Claude länger als `patience`, sagt kushim das und liest die
Antwort später von sich aus vor (`announcement`, nur wenn gerade nichts läuft). Claudes Text ist nur zum Vorlesen da.
Freigabe-Anfragen von Claude (C2) werden je einmal angesagt; beantwortet werden sie bis C3 nur im Terminal.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Iterator

from ..channel import speakable
from ..channel.bridge import Bridge
from ..tasks import TaskRegistry

ACK = "Ich geb's an Claude."
NOT_RUNNING = "Claude ist gerade nicht verbunden. Starte kushim zusammen mit Claude."
KILLED = "Der Notaus ist aktiv, ich gebe nichts weiter."
FAILED = "Das konnte ich nicht an Claude geben."
LATE = "Claude arbeitet noch. Ich sag Bescheid, sobald eine Antwort kommt."
LOST = "Die Verbindung zu Claude ist weg."
POLL = 2.0                      # Sekunden je Abruf: so schnell greifen Abbrechen und Notaus
PATIENCE = 180.0                # so lange wartet eine Runde auf Claude, danach kommt die Antwort als Meldung
ANNOUNCE_EVERY = 2.0            # so oft fragt die Schleife im Leerlauf nach verspäteten Antworten
MAX_ANNOUNCED = 200             # gemerkte, schon angesagte Freigabe-Anfragen


class ClaudeChat:
    """Aufrufbar wie ein ChatStream: `chat(messages)` liefert die zu sprechenden Texte."""

    def __init__(self, bridge: Bridge, tasks: TaskRegistry, patience: float = PATIENCE,
                 clock: Callable[[], float] = time.monotonic):
        self.bridge, self.tasks, self.patience, self.clock = bridge, tasks, patience, clock
        self._next_announce = 0.0
        self._announced: list[str] = []         # request_ids, die schon vorgelesen wurden (neueste hinten)

    def permission_notes(self) -> list[str]:
        """Ansagen für neue, noch offene Freigabe-Anfragen; jede nur einmal."""
        notes = []
        for perm in list(self.bridge.permissions):
            if perm.request_id in self._announced:
                continue
            self._announced.append(perm.request_id)
            notes.append(speakable.announce(perm))
        del self._announced[:-MAX_ANNOUNCED]
        return notes

    def __call__(self, messages: list[dict[str, str]], **_: Any) -> Iterator[str]:
        text = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
        status = self.bridge.send(text)
        if status != "ok":
            yield {"not_running": NOT_RUNNING, "kill": KILLED}.get(status, FAILED)
            return
        yield ACK
        deadline = self.clock() + self.patience
        with self.tasks.running("Claude arbeitet", cancel=self.bridge.cancel) as token:     # "abbrechen" sagt es auch Claude
            while not token.cancelled():
                left = deadline - self.clock()
                if left <= 0:
                    yield LATE
                    return
                status, texts = self.bridge.fetch(wait=min(POLL, left))
                if token.cancelled():
                    return
                notes = self.permission_notes()
                if notes:
                    yield " ".join(notes)             # Claude wartet auf die Freigabe; die Runde wartet weiter
                if texts:
                    yield " ".join(texts)
                    return
                if status == "kill":
                    yield KILLED
                    return
                if status == "not_running":
                    yield LOST
                    return

    def announcement(self) -> str | None:
        """Für die Sprachschleife im Leerlauf: eine verspätete oder von Claude selbst gesendete Antwort, sonst None."""
        now = self.clock()
        if now < self._next_announce:
            return None
        self._next_announce = now + ANNOUNCE_EVERY
        if not self.bridge.available():
            return None
        status, texts = self.bridge.fetch(wait=0)
        parts = self.permission_notes() + (texts if status == "ok" else [])
        return " ".join(parts) if parts else None
