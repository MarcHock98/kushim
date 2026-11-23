"""Mikrofonpegel messen und daraus Schwellen vorschlagen (Sprechen, Unterbrechen).

Jedes Mikrofon und jede Verstärkung ist anders. Feste Schwellen passen deshalb oft nicht: Liegt der normale
Sprechpegel unter der Schwelle, überhört kushim den Befehl oder lässt sich nicht unterbrechen.
`kushim voice level` misst Ruhe und Sprechen und schlägt `speech_level` und `barge_in_level` vor.
Es werden nur Pegelzahlen berechnet; Audio wird nicht gespeichert.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

import numpy as np


def frame_rms(frames: Iterable[Any]) -> list[float]:
    return [float(np.sqrt(np.mean(np.asarray(f, dtype=np.int16).astype(np.float64) ** 2))) for f in frames]


@dataclass(frozen=True)
class Suggestion:
    speech_level: float
    barge_in_level: float
    noise_p95: float
    speech_p25: float
    speech_p50: float
    speech_frames: int
    warning: str = ""


def suggest(noise: list[float], speech: list[float]) -> Suggestion:
    """noise: Pegel (RMS je Frame) bei Ruhe; speech: Pegel beim normalen Sprechen. Wirft ValueError ohne brauchbare Daten."""
    if len(noise) < 5 or len(speech) < 10:
        raise ValueError("Zu wenig Messwerte")
    n95 = float(np.percentile(noise, 95))
    floor = max(3 * n95, 60.0)                       # alles darunter ist Rauschen
    voiced = np.array([x for x in speech if x > floor])
    if len(voiced) < 8:
        raise ValueError("Kaum Sprache gemessen: lauter oder näher am Mikrofon sprechen")
    p10, p25, p50 = (float(np.percentile(voiced, q)) for q in (10, 25, 50))
    speech_level = float(min(600.0, max(100.0, 2.5 * n95, 0.8 * p10)))     # deutlich über dem Rauschen, unter leisen Silben
    barge = float(min(3000.0, max(150.0, 1.25 * speech_level, 0.55 * p50)))  # Sprechen über dem Hintergrund, nicht erst laut
    warn = ""
    if floor > speech_level or n95 * 3 > p25:
        warn = "Die Umgebung ist laut (Rauschen nahe am Sprechpegel); Unterbrechen und Satzende werden unzuverlässig."
    return Suggestion(round(speech_level), round(barge), round(n95, 1), round(p25), round(p50), int(len(voiced)), warn)


FRAME_SECONDS = 0.08                 # ein Mikrofon-Frame (1280 Samples bei 16 kHz)
QUIET_FRAMES = 38                    # gut 3 s Ruhe (wie `kushim voice level`)
SPEECH_FRAMES = 75                   # 6 s normales Sprechen
TEST_TIMEOUT = 60.0                  # länger als das ohne Ergebnis (kushim spricht gerade o. ä.): Test endet ohne Vorschlag
COUNTING_PHASES = ("idle", "listening")     # während kushim spricht oder denkt, zählen die Frames nicht (eigene Stimme)


class LevelTest:
    """Pegeltest der Oberfläche (E3b) im Sprachprozess, der das Mikrofon ohnehin hält: kein zweiter Zugriff aufs Mikrofon.

    Die Sprach-Schleife reicht jeden Frame mit ihrer Phase herein (`feed`); hier wird nur die Pegelzahl (RMS) je Frame
    behalten, nie Audio. Ablauf: `start()` -> "quiet" (3 s Ruhe) -> "speak" (6 s Sprechen) -> "done" mit Vorschlag aus
    `suggest` (oder ohne, wenn die Messung nichts taugt). Die API-Threads lesen mit `result()`; alles unter einer Sperre."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._state = "idle"
        self._noise: list[float] = []
        self._speech: list[float] = []
        self._suggestion: dict[str, float] | None = None
        self._started = 0.0

    def start(self) -> None:
        """Startet (oder beginnt neu) mit der Ruhe-Messung."""
        with self._lock:
            self._state, self._noise, self._speech, self._suggestion = "quiet", [], [], None
            self._started = self._clock()

    def feed(self, frame: Any, phase: str = "idle") -> None:
        """Von der Sprach-Schleife je Frame aufgerufen; kostet nichts, solange kein Test läuft."""
        if self._state not in ("quiet", "speak"):
            return
        level = frame_rms([frame])[0] if phase in COUNTING_PHASES else None
        with self._lock:
            self._expire()
            if self._state == "quiet" and level is not None:
                self._noise.append(level)
                if len(self._noise) >= QUIET_FRAMES:
                    self._state = "speak"
            elif self._state == "speak" and level is not None:
                self._speech.append(level)
                if len(self._speech) >= SPEECH_FRAMES:
                    self._finish()

    def _finish(self) -> None:
        try:
            sg = suggest(self._noise, self._speech)
            self._suggestion = {"speech_level": float(sg.speech_level), "barge_in_level": float(sg.barge_in_level)}
        except ValueError:
            self._suggestion = None                  # zu wenig Sprache: ehrlich ohne Vorschlag
        self._state, self._noise, self._speech = "done", [], []

    def _expire(self) -> None:
        if self._state in ("quiet", "speak") and self._clock() - self._started > TEST_TIMEOUT:
            self._state, self._suggestion, self._noise, self._speech = "done", None, [], []

    def result(self) -> dict[str, Any]:
        """{"state", "seconds_left", "suggestion"}; `seconds_left` gilt für den laufenden Abschnitt."""
        with self._lock:
            self._expire()
            if self._state == "quiet":
                left = (QUIET_FRAMES - len(self._noise)) * FRAME_SECONDS
            elif self._state == "speak":
                left = (SPEECH_FRAMES - len(self._speech)) * FRAME_SECONDS
            else:
                left = 0.0
            return {"state": self._state, "seconds_left": round(max(0.0, left), 1),
                    "suggestion": dict(self._suggestion) if self._suggestion else None}
