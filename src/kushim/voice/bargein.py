"""Unterbrechen (Barge-in): erkennt, dass der Nutzer spricht, während kushim denkt oder redet.

Reine Logik auf Mikrofon-Frames (Lautstärke). Löst erst nach `min_ms` anhaltender Lautstärke aus, damit ein
Husten oder Klicken nicht reicht. Die ersten Frames der Äußerung bleiben erhalten (`recent`), damit der Anfang
des Satzes nicht fehlt. Ohne Echo-Unterdrückung kann kushim über Lautsprecher sich selbst unterbrechen:
Kopfhörer empfohlen, oder `barge_in = false` / höheres `barge_in_level` in wakewords.toml.
"""
from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np


class BargeIn:
    def __init__(self, level: float = 1200.0, min_ms: int = 320, frame_ms: int = 80, preroll_ms: int = 480):
        self.level = level
        self.need = max(1, round(min_ms / frame_ms))
        self._run = 0
        self._recent: deque[np.ndarray] = deque(maxlen=self.need + max(0, round(preroll_ms / frame_ms)))

    def reset(self) -> None:
        self._run = 0
        self._recent.clear()

    def feed(self, frame: Any) -> bool:
        """True, sobald der Nutzer lange genug laut genug spricht."""
        f = np.asarray(frame, dtype=np.int16)
        self._recent.append(f)
        loud = float(np.sqrt(np.mean(f.astype(np.float64) ** 2))) >= self.level
        self._run = self._run + 1 if loud else max(0, self._run - 1)     # eine kurze Pause wirft nicht alles zurück
        if self._run >= self.need:
            self._run = 0
            return True
        return False

    def recent(self) -> list[np.ndarray]:
        """Die letzten Frames inklusive des auslösenden (für den Anfang der Äußerung)."""
        return list(self._recent)
