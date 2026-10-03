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


class KwsDetector:
    """Freie Schlüsselwörter ohne Training (sherpa-onnx KeywordSpotter, offenes Vokabular).

    Wie bei den anderen Detektoren sieht diese Komponente das Mikrofonsignal vor dem Wake Word, speichert
    nichts und ist kein Sprachmodell: sie erkennt nur die eingestellten Wörter. Nach einem Treffer gilt
    `cooldown` Sekunden Ruhe. Bekannte Schwäche: Wörter mit gleichem Anfang ("kush", "kushim") lassen sich
    nicht sicher unterscheiden; jeder Treffer löst aus, der gemeldete Name kann der kürzere sein.
    """

    def __init__(self, spotter: Any, cooldown: float = 2.0, clock: Callable[[], float] = time.monotonic):
        self.spotter, self.cooldown, self._clock = spotter, cooldown, clock
        self._stream = spotter.create_stream()
        self._quiet_until = 0.0

    @staticmethod
    def keyword_lines(words: list[tuple[str, float, float]], encode: Callable[[str], list[str]]) -> list[str]:
        """words: (Wort, Schwelle, boost). Zeile: `▁K U SH IM :boost #schwelle @Name`."""
        return [" ".join(encode(w.upper())) + f" :{boost} #{thr} @{w.replace(' ', '_')}"
                for w, thr, boost in words]

    @classmethod
    def from_model(cls, model_dir: Path, words: list[tuple[str, float, float]], keywords_file: Path,
                   cooldown: float = 2.0, threads: int = 2) -> "KwsDetector":
        import sentencepiece as spm
        import sherpa_onnx
        sp = spm.SentencePieceProcessor(model_file=str(model_dir / "bpe.model"))
        keywords_file.parent.mkdir(parents=True, exist_ok=True)
        keywords_file.write_text(
            "\n".join(cls.keyword_lines(words, lambda t: sp.encode(t, out_type=str))) + "\n", encoding="utf-8")
        suffix = "epoch-12-avg-2-chunk-16-left-64.int8.onnx"
        spotter = sherpa_onnx.KeywordSpotter(
            tokens=str(model_dir / "tokens.txt"), encoder=str(model_dir / f"encoder-{suffix}"),
            decoder=str(model_dir / f"decoder-{suffix}"), joiner=str(model_dir / f"joiner-{suffix}"),
            keywords_file=str(keywords_file), num_threads=threads, provider="cpu")
        return cls(spotter, cooldown=cooldown)

    def process(self, frame: Any) -> TriggerEvent | None:
        import numpy as np
        x = np.asarray(frame)
        x = x.astype(np.float32) / 32768.0 if x.dtype == np.int16 else x.astype(np.float32)
        self._stream.accept_waveform(16000, x)
        hit = None
        while self.spotter.is_ready(self._stream):
            self.spotter.decode_stream(self._stream)
            result = self.spotter.get_result(self._stream)
            if result:
                self.spotter.reset_stream(self._stream)
                hit = result
        now = self._clock()
        if hit and now >= self._quiet_until:
            self._quiet_until = now + self.cooldown
            return TriggerEvent("wake", 1.0)
        return None


class CombinedDetector:
    """Schickt jeden Frame durch alle Detektoren (jeder behält seinen Zustand); der erste Treffer zählt."""

    def __init__(self, detectors: list[Any]):
        if not detectors:
            raise ValueError("Mindestens ein Detektor nötig")
        self.detectors = detectors

    def process(self, frame: Any) -> TriggerEvent | None:
        event = None
        for d in self.detectors:
            e = d.process(frame)
            event = event or e
        return event


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
