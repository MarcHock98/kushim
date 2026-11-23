"""Unterbrechen (Barge-in): erkennt, dass der Nutzer spricht, während kushim denkt oder redet.

Reine Logik auf Mikrofon-Frames (Lautstärke). Löst erst nach `min_ms` anhaltender Lautstärke aus, damit ein
Husten oder Klicken nicht reicht. Die ersten Frames der Äußerung bleiben erhalten (`recent`), damit der Anfang
des Satzes nicht fehlt. Ohne Echo-Unterdrückung kann kushim über Lautsprecher sich selbst unterbrechen. Darum
(Live-Test 2026-11-23, mehrere Runden "unterbrochen"):
- die ersten `echo_ignore_ms` nach dem Start jeder eigenen Wiedergabe zählen nie (Einschwingen von Lautsprecher und Raum),
- solange kushim spricht und `echo_tail_ms` danach (Nachhall, Puffer des Mikrofons) muss der Pegel `echo_factor`-mal so hoch
  sein wie sonst.
Kopfhörer bleiben die beste Lösung; mit Lautsprechern `barge_in_level` erhöhen oder `barge_in = false` in wakewords.toml.
"""
from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np

ECHO_IGNORE_MS = 400            # nach dem Start eigener Wiedergabe: so lange zählt gar nichts
ECHO_TAIL_MS = 320              # nach dem Ende eigener Wiedergabe: so lange gilt noch die erhöhte Schwelle
ECHO_FACTOR = 2.0               # Schwelle während eigener Wiedergabe: so viel lauter als sonst


class BargeIn:
    def __init__(self, level: float = 1200.0, min_ms: int = 320, frame_ms: int = 80, preroll_ms: int = 480,
                 echo_ignore_ms: int = ECHO_IGNORE_MS, echo_tail_ms: int = ECHO_TAIL_MS, echo_factor: float = ECHO_FACTOR):
        self.level = level
        self.need = max(1, round(min_ms / frame_ms))
        self.ignore_frames = max(0, round(echo_ignore_ms / frame_ms))
        self.tail_frames = max(0, round(echo_tail_ms / frame_ms))
        self.echo_factor = max(1.0, echo_factor)
        self._run = 0
        self._recent: deque[np.ndarray] = deque(maxlen=self.need + max(0, round(preroll_ms / frame_ms)))
        self._was_speaking = False
        self._ignore = 0
        self._tail = 0

    def reset(self) -> None:
        self._run = 0
        self._recent.clear()
        self._was_speaking = False
        self._ignore = self._tail = 0

    def threshold(self, speaking: bool = False) -> float:
        """Pegel, ab dem ein Frame als Sprechen des Nutzers zählt (während eigener Wiedergabe höher)."""
        return self.level * (self.echo_factor if speaking or self._tail > 0 else 1.0)

    def feed(self, frame: Any, speaking: bool = False) -> bool:
        """True, sobald der Nutzer lange genug laut genug spricht. `speaking`: kushim spielt gerade selbst Ton ab."""
        f = np.asarray(frame, dtype=np.int16)
        self._recent.append(f)
        if speaking and not self._was_speaking:
            self._ignore = self.ignore_frames         # eigene Wiedergabe beginnt: ihr Anfang ist nie der Nutzer
        elif self._was_speaking and not speaking:
            self._tail = self.tail_frames             # eigene Wiedergabe endet: Nachhall noch streng behandeln
        self._was_speaking = speaking
        if self._ignore > 0:
            self._ignore -= 1
            return False
        level = self.threshold(speaking)
        if not speaking and self._tail > 0:
            self._tail -= 1
        loud = float(np.sqrt(np.mean(f.astype(np.float64) ** 2))) >= level
        self._run = self._run + 1 if loud else max(0, self._run - 1)     # eine kurze Pause wirft nicht alles zurück
        if self._run >= self.need:
            self._run = 0
            return True
        return False

    def recent(self) -> list[np.ndarray]:
        """Die letzten Frames inklusive des auslösenden (für den Anfang der Äußerung)."""
        return list(self._recent)
