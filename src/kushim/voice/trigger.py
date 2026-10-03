"""Auslöser für die Sprachaufnahme: ausschließlich Wake Words (openWakeWord, ONNX, lokal).

Vor dem Wake Word läuft das Mikrofonsignal nur durch dieses kleine lokale Erkennungsmodell: keine
Spracherkennung, kein LLM, keine Speicherung. Ein Auslöser startet nur das Zuhören. Er ist keine
Autorisierung: Sprecherverifikation und ActionGate gelten danach unverändert.
"""
from __future__ import annotations

import time
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class TriggerEvent:
    source: str          # "wake" | "hotkey"
    score: float = 1.0


class _Model(Protocol):
    def predict(self, frame: Any) -> dict[str, float]: ...


class WakeWordDetector:
    """Wertet 16-kHz-int16-Frames (z. B. 1280 Samples = 80 ms) aus.

    Auslösen erst nach `hits` aufeinanderfolgenden Frames über `threshold` (weniger Fehlalarme),
    danach `cooldown` Sekunden Ruhe.
    """

    def __init__(self, model: _Model, threshold: float = 0.6, hits: int = 2,
                 cooldown: float = 2.0, clock: Callable[[], float] = time.monotonic):
        self.model, self.threshold, self.hits, self.cooldown = model, threshold, hits, cooldown
        self._clock = clock
        self._streak = 0
        self._quiet_until = 0.0

    @classmethod
    def from_openwakeword(cls, wakeword_models: list[str] | str = "hey_jarvis", **kw) -> "WakeWordDetector":
        """Lädt ein oder mehrere Modelle (vortrainierte Namen oder .onnx-Dateien aus models/wakewords).

        Einmalig vorher: `openwakeword.utils.download_models()`. ONNX ist auf Windows/Python 3.12
        der einzige Pfad (tflite-runtime hat dort keine Wheels). Es löst aus, sobald EIN Wort passt.
        """
        from openwakeword.model import Model
        names = [wakeword_models] if isinstance(wakeword_models, str) else list(wakeword_models)
        if not names:
            raise ValueError("Mindestens ein Wake Word nötig")
        return cls(Model(wakeword_models=names, inference_framework="onnx"), **kw)

    def process(self, frame: Any) -> TriggerEvent | None:
        now = self._clock()
        scores = self.model.predict(frame)
        best = max(scores.values(), default=0.0)
        if now < self._quiet_until:
            self._streak = 0
            return None
        self._streak = self._streak + 1 if best >= self.threshold else 0
        if self._streak >= self.hits:
            self._streak = 0
            self._quiet_until = now + self.cooldown
            return TriggerEvent("wake", float(best))
        return None


PRETRAINED = {"alexa", "hey_mycroft", "hey_jarvis", "hey_rhasspy", "timer", "weather"}


def resolve_wake_words(names: list[str], root: Path) -> list[str]:
    """Prüft die Wake-Word-Liste: vortrainierte Namen oder .onnx-Dateien nur aus `models/wakewords/`.

    Beliebige Pfade werden abgelehnt (kein Laden fremder Dateien über die Konfiguration).
    """
    if not names:
        raise ValueError("Mindestens ein Wake Word nötig")
    allowed_dir = (root / "models" / "wakewords").resolve()
    out: list[str] = []
    for raw in names:
        n = raw.strip()
        if n in PRETRAINED:
            out.append(n)
            continue
        f = (allowed_dir / n).resolve() if not n.endswith(".onnx") or "/" not in n.replace("\\", "/") else None
        if f is None or f.suffix != ".onnx" or allowed_dir not in f.parents or not f.is_file():
            raise ValueError(f"Unbekanntes Wake Word: {n!r} (erlaubt: {sorted(PRETRAINED)} oder "
                             f".onnx in models/wakewords/)")
        out.append(str(f))
    return out
