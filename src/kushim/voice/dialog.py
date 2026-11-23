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
    def __init__(self, on_stop_speaking: Callable[[], None] = lambda: None,
                 on_change: Callable[[State], None] = lambda s: None):
        self._state = State.IDLE
        self._stop_speaking = on_stop_speaking
        self._on_change = on_change              # nur Anzeige (Oberfläche), darf nie stören

    @property
    def state(self) -> State:
        return self._state

    @state.setter
    def state(self, new: State) -> None:
        changed = new is not self._state
        self._state = new
        if changed:
            try:
                self._on_change(new)
            except Exception:                    # noqa: BLE001
                pass

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

    def reply_done(self) -> bool:
        """Antwort fertig: aus Denken oder Sprechen zurück in den Leerlauf (Unterbrochen/Notaus bleiben, wie sie sind)."""
        return self._move(State.THINKING, State.IDLE) or self._move(State.SPEAKING, State.IDLE)

    def playing(self) -> State | None:
        """Ton läuft jetzt wirklich (je Satz direkt vor der Wiedergabe): SPEAKING. Gibt den vorigen Zustand zurück, damit
        `played` danach dorthin zurückkehrt (z. B. Denken, während auf den nächsten Satz gewartet wird). Beim Notaus: None."""
        if self.state is State.HALTED:
            return None
        prev = self.state
        self.state = State.SPEAKING
        return prev

    def played(self, prev: State | None) -> None:
        """Wiedergabe eines Satzes ist zu Ende: zurück zum vorigen Zustand, falls nichts anderes (Unterbrechen, Notaus) dazwischenkam."""
        if prev is not None and self.state is State.SPEAKING:
            self.state = prev if prev is not State.SPEAKING else State.IDLE

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
