"""Mikrofonpegel messen und daraus Schwellen vorschlagen (Sprechen, Unterbrechen).

Jedes Mikrofon und jede Verstärkung ist anders. Feste Schwellen passen deshalb oft nicht: Liegt der normale
Sprechpegel unter der Schwelle, überhört kushim den Befehl oder lässt sich nicht unterbrechen.
`kushim voice level` misst Ruhe und Sprechen und schlägt `speech_level` und `barge_in_level` vor.
Es werden nur Pegelzahlen berechnet; Audio wird nicht gespeichert.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

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
