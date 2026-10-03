"""Lokale Sprachausgabe: Satzweises Streaming über eine austauschbare Engine.

Die Engine (Piper/Kokoro o. ä.) wird von außen geliefert; hier liegt nur die Logik.
Satzweise Ausgabe senkt die Latenz bis zum ersten Ton und erlaubt Barge-in zwischen Sätzen.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Iterator, Protocol

_SPLIT = re.compile(r"(?<=[.!?…])\s+")


class Engine(Protocol):
    def synthesize(self, text: str) -> Any: ...


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SPLIT.split(text.strip()) if s.strip()]


def chunk_stream(tokens: Iterable[str]) -> Iterator[str]:
    """Fasst einen LLM-Tokenstrom zu vollständigen Sätzen zusammen."""
    buf = ""
    for tok in tokens:
        buf += tok
        parts = _SPLIT.split(buf)
        for s in parts[:-1]:
            if s.strip():
                yield s.strip()
        buf = parts[-1]
    if buf.strip():
        yield buf.strip()


class Speaker:
    def __init__(self, engine: Engine, play: Callable[[Any], None],
                 should_stop: Callable[[], bool] = lambda: False):
        self.engine, self.play, self.should_stop = engine, play, should_stop

    def say(self, sentences: Iterable[str]) -> int:
        """Spielt Sätze nacheinander; bricht vor jedem Satz ab, wenn `should_stop` (Barge-in/Notaus)."""
        n = 0
        for s in sentences:
            if self.should_stop():
                break
            self.play(self.engine.synthesize(s))
            n += 1
        return n


class PiperEngine:
    """Piper (offline, GPL-3, nur lokale Modelldatei). Liefert WAV-Bytes pro Satz."""

    def __init__(self, voice: Any):
        self.voice = voice

    @classmethod
    def from_local(cls, model_path: str) -> "PiperEngine":
        from piper import PiperVoice
        return cls(PiperVoice.load(model_path))

    def synthesize(self, text: str) -> bytes:
        import io
        import wave
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            self.voice.synthesize_wav(text, w)
        return buf.getvalue()
