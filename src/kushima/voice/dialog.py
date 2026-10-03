"""Gesprächszustand mit Barge-in: Sprechen des Nutzers unterbricht die Ausgabe sofort.

Reine Zustandslogik ohne Audio/Netz. Ein Notaus (`halt`) sperrt alle Übergänge außer `reset`.
"""
from __future__ import annotations

from enum import Enum
from typing import Callable


class State(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    HALTED = "halted"


class Dialog:
    def __init__(self, on_stop_speaking: Callable[[], None] = lambda: None):
        self.state = State.IDLE
        self._stop_speaking = on_stop_speaking

    def triggered(self) -> bool:
        """Wake Word/Hotkey/Sprache erkannt. Beim Sprechen = Barge-in."""
        if self.state is State.HALTED:
            return False
        if self.state is State.SPEAKING:
            self._stop_speaking()
        self.state = State.LISTENING
        return True

    def utterance_done(self) -> bool:
        return self._move(State.LISTENING, State.THINKING)

    def reply_ready(self) -> bool:
        return self._move(State.THINKING, State.SPEAKING)

    def speech_done(self) -> bool:
        return self._move(State.SPEAKING, State.IDLE)

    def halt(self) -> None:
        if self.state is State.SPEAKING:
            self._stop_speaking()
        self.state = State.HALTED

    def reset(self) -> None:
        self.state = State.IDLE

    def _move(self, src: State, dst: State) -> bool:
        if self.state is not src:
            return False
        self.state = dst
        return True
