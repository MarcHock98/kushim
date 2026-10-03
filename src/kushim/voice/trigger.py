"""Auslöser für die Sprachaufnahme: Wake Word (openWakeWord, ONNX) und Push-to-Talk (pynput).

Ein Auslöser startet nur das Zuhören. Er ist keine Autorisierung: Sprecherverifikation und
ActionGate gelten danach unverändert.
"""
from __future__ import annotations

import time
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
    def from_openwakeword(cls, wakeword_model: str = "hey_jarvis", **kw) -> "WakeWordDetector":
        """Lädt ein vortrainiertes Modell. Einmalig vorher: `openwakeword.utils.download_models()`.

        ONNX ist auf Windows/Python 3.12 der einzige Pfad (tflite-runtime hat dort keine Wheels).
        """
        from openwakeword.model import Model
        return cls(Model(wakeword_models=[wakeword_model], inference_framework="onnx"), **kw)

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


def key_matches(key: Any, wanted: str) -> bool:
    """Vergleicht eine pynput-Taste mit dem konfigurierten Namen (z. B. 'f9' oder 'a')."""
    name = getattr(key, "name", None)
    if name is not None:
        return name.lower() == wanted.lower()
    char = getattr(key, "char", None)
    return char is not None and char.lower() == wanted.lower()


class PushToTalk:
    """Globaler Listener, der AUSSCHLIESSLICH die konfigurierte Taste auswertet.

    Andere Tasten werden verworfen, nichts wird gespeichert oder geloggt.
    """

    def __init__(self, key: str, on_start: Callable[[TriggerEvent], None],
                 on_stop: Callable[[], None]):
        self.key, self.on_start, self.on_stop = key, on_start, on_stop
        self._down = False
        self._listener = None

    def _press(self, key) -> None:
        if key_matches(key, self.key) and not self._down:  # Auto-Repeat ignorieren
            self._down = True
            self.on_start(TriggerEvent("hotkey"))

    def _release(self, key) -> None:
        if key_matches(key, self.key) and self._down:
            self._down = False
            self.on_stop()

    def start(self) -> None:
        from pynput import keyboard
        self._listener = keyboard.Listener(on_press=self._press, on_release=self._release)
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None
