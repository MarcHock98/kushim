"""Unterbrechen (Barge-in): erkennt, dass der Nutzer spricht, während kushim denkt oder redet.

Reine Logik auf Mikrofon-Frames (Lautstärke). Löst erst nach `min_ms` anhaltender Lautstärke aus, damit ein
Husten oder Klicken nicht reicht. Die ersten Frames der Äußerung bleiben erhalten (`recent`), damit der Anfang
des Satzes nicht fehlt.

Sicherheit geht vor: Über diesen Weg kommt auch ein gesprochenes „Notaus“ oder „abbrechen“ an, während kushim redet. Eine
Fehlauslösung ist harmlos, ein überhörter Notaus nicht (safety/killswitch.py). Darum ist der Standard empfindlich und ohne
Echo-Schutz (Safety-Audit 2026-11-23).

Echo-Schutz (`echo_guard`, in wakewords.toml `echo_schutz = true`, nur für Lautsprecher gedacht):
- solange kushim spricht und `echo_tail_ms` danach muss der Pegel `echo_factor`-mal so hoch sein wie sonst,
- die ersten `echo_ignore_ms` der ersten eigenen Wiedergabe einer Runde zählen nicht (nur einmal je Runde, `reset`), nicht bei
  jedem Satz neu.
Ein Notaus, der lauter ist als `echo_factor × level`, greift auch dann; in der kurzen Sperrzeit am Anfang nicht (dafür gibt es
die Notaus-Verknüpfung). Kopfhörer bleiben die beste Lösung.
"""
from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np

ECHO_FACTOR = 2.0               # Echo-Schutz: Schwelle während eigener Wiedergabe so viel höher
ECHO_IGNORE_MS = 400            # Echo-Schutz: so lange zählt am Anfang der ersten Wiedergabe einer Runde nichts
ECHO_TAIL_MS = 320              # Echo-Schutz: nach dem Ende eigener Wiedergabe gilt die erhöhte Schwelle noch so lange


class BargeIn:
    # Standardwerte wie in wakeconfig (barge_in_level 250, barge_in_ms 240): empfindlich, ein überhörter Notaus wiegt schwerer.
    def __init__(self, level: float = 250.0, min_ms: int = 240, frame_ms: int = 80, preroll_ms: int = 480,
                 echo_guard: bool = False, echo_factor: float = ECHO_FACTOR, echo_ignore_ms: int = ECHO_IGNORE_MS,
                 echo_tail_ms: int = ECHO_TAIL_MS):
        self.level = level
        self.need = max(1, round(min_ms / frame_ms))
        self.echo_guard = echo_guard
        self.echo_factor = max(1.0, echo_factor)
        self.ignore_frames = max(0, round(echo_ignore_ms / frame_ms))
        self.tail_frames = max(0, round(echo_tail_ms / frame_ms))
        self._run = 0
        self._recent: deque[np.ndarray] = deque(maxlen=self.need + max(0, round(preroll_ms / frame_ms)))
        self._was_speaking = False
        self._ignore = 0
        self._tail = 0
        self._ignored_this_turn = False
        self.last_rms = 0.0             # Pegel des zuletzt gesehenen Frames (für talk.log beim Auslösen, nur eine Zahl)

    def reset(self) -> None:
        """Neue Runde (kushim beginnt zu antworten)."""
        self._run = 0
        self._recent.clear()
        self._was_speaking = False
        self._ignore = self._tail = 0
        self._ignored_this_turn = False

    def threshold(self, speaking: bool = False) -> float:
        """Pegel, ab dem ein Frame als Sprechen des Nutzers zählt (mit Echo-Schutz während eigener Wiedergabe höher)."""
        if self.echo_guard and (speaking or self._tail > 0):
            return self.level * self.echo_factor
        return self.level

    def feed(self, frame: Any, speaking: bool = False) -> bool:
        """True, sobald der Nutzer lange genug laut genug spricht. `speaking`: kushim spielt gerade selbst Ton ab."""
        f = np.asarray(frame, dtype=np.int16)
        self._recent.append(f)
        if self.echo_guard:
            if speaking and not self._was_speaking and not self._ignored_this_turn:
                self._ignore, self._ignored_this_turn = self.ignore_frames, True     # nur einmal je Runde
            elif self._was_speaking and not speaking:
                self._tail = self.tail_frames
            self._was_speaking = speaking
            if self._ignore > 0:
                self._ignore -= 1
                return False
        level = self.threshold(speaking)
        if self.echo_guard and not speaking and self._tail > 0:
            self._tail -= 1
        self.last_rms = float(np.sqrt(np.mean(f.astype(np.float64) ** 2))) if f.size else 0.0
        loud = self.last_rms >= level
        self._run = self._run + 1 if loud else max(0, self._run - 1)     # eine kurze Pause wirft nicht alles zurück
        if self._run >= self.need:
            self._run = 0
            return True
        return False

    def recent(self) -> list[np.ndarray]:
        """Die letzten Frames inklusive des auslösenden (für den Anfang der Äußerung)."""
        return list(self._recent)
