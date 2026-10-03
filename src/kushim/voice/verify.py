"""Prüfung einer ganzen Äußerung gegen das Stimmprofil, auch bei langer Spracheingabe.

- Kurze Äußerungen (bis 4 s): ein Embedding. Unter 0,8 s wird abgelehnt (zu unzuverlässig).
- Lange Äußerungen: Fenster von 3 s (Schritt 1,5 s); Median der Fensterwerte muss die Schwelle erreichen UND
  mindestens 60 % der Fenster. So kann eine fremde Stimme nicht einfach "mitreden", und Husten oder eine
  Pause in einem Fenster macht einen echten Befehl nicht ungültig.
- "stark" verifiziert (für Änderungen, z. B. Wake Words): angenommen, mindestens 1,5 s lang und mindestens
  Schwelle plus Abstand. Schwache Treffer reichen nur für harmlose Antworten.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

RATE = 16_000
MIN_SECONDS = 0.8
STRONG_SECONDS = 1.5
LONG_AFTER = 4.0
WINDOW, HOP = 3.0, 1.5
MIN_FRACTION = 0.6


@dataclass(frozen=True)
class AudioVerdict:
    accepted: bool
    strong: bool
    score: float
    seconds: float
    windows: int = 1
    reason: str = ""


def windows(audio: np.ndarray, rate: int = RATE, win: float = WINDOW, hop: float = HOP,
            min_energy: float = 150.0) -> list[np.ndarray]:
    """Zerlegt Audio in überlappende Fenster; fast stille Fenster werden verworfen."""
    w, h = int(win * rate), int(hop * rate)
    if len(audio) <= w:
        return [audio]
    out = []
    for start in range(0, len(audio) - w + 1, h):
        seg = audio[start:start + w]
        if float(np.sqrt(np.mean(seg.astype(np.float64) ** 2))) >= min_energy:
            out.append(seg)
    tail = audio[-w:]
    if (len(audio) - w) % h and float(np.sqrt(np.mean(tail.astype(np.float64) ** 2))) >= min_energy:
        out.append(tail)
    return out or [audio[:w]]


class AudioVerifier:
    """`profile` braucht `.verify(embedding) -> .score`, `.threshold`, `.margin` (optional) und `.enrolled`."""

    def __init__(self, profile: Any, embed: Callable[[Any], Any]):
        self.profile, self.embed = profile, embed

    @property
    def enrolled(self) -> bool:
        return bool(getattr(self.profile, "enrolled", False))

    def check(self, pcm: Any, min_seconds: float = MIN_SECONDS) -> AudioVerdict:
        a = np.asarray(pcm)
        seconds = a.size / RATE
        if seconds < min_seconds:
            return AudioVerdict(False, False, 0.0, seconds, 0, "zu kurz")
        segs = [a] if seconds <= LONG_AFTER else windows(a)
        scores = []
        for s in segs:
            e = np.asarray(self.embed(s))
            scores.append(self.profile.verify(e).score if e.size else 0.0)
        thr = float(self.profile.threshold)
        margin = float(getattr(self.profile, "margin", 0.1))
        if len(segs) == 1:
            score, ok = scores[0], scores[0] >= thr
        else:
            score = float(np.median(scores))
            ok = score >= thr and float(np.mean([s >= thr for s in scores])) >= MIN_FRACTION
        # Die Hürde für "stark" liegt höchstens in der Mitte zwischen Schwelle und 1,0, sonst wäre sie bei hoher
        # Schwelle (z. B. 0,9 plus Abstand 0,1 = 1,0) nie erreichbar.
        strong_thr = min(thr + margin, thr + (1.0 - thr) / 2)
        strong = ok and seconds >= STRONG_SECONDS and score >= strong_thr
        return AudioVerdict(ok, strong, float(score), seconds, len(segs), "ok" if ok else "Stimme passt nicht")
