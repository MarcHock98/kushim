"""Lokale Sprachausgabe: Satzweises Streaming über eine austauschbare Engine.

Die Engine (Piper/Kokoro o. ä.) wird von außen geliefert; hier liegt nur die Logik.
Satzweise Ausgabe senkt die Latenz bis zum ersten Ton und erlaubt Barge-in zwischen Sätzen.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Iterator, Protocol


_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def prefetch(source: Iterable[str], stop: Callable[[], bool] = lambda: False, size: int = 2) -> Iterator[str]:
    """Erzeugt Sätze in einem Hintergrund-Thread vor, damit das LLM während der Wiedergabe weiterschreibt.

    Bei `stop()` (Notaus, Unterbrechen) endet der Strom sofort, auch wenn das LLM gerade noch an einem Satz schreibt."""
    import queue
    import threading
    q: queue.Queue = queue.Queue(maxsize=size)
    END, ERR = object(), object()

    def work():
        try:
            for item in source:
                while True:
                    if stop():
                        return
                    try:
                        q.put(item, timeout=0.1)
                        break
                    except queue.Full:
                        continue
            q.put(END)
        except Exception as e:           # noqa: BLE001 (Fehler an den Verbraucher weiterreichen)
            q.put((ERR, e))

    threading.Thread(target=work, daemon=True).start()
    while True:
        try:
            item = q.get(timeout=0.1)
        except queue.Empty:
            if stop():                   # Erzeuger hängt noch im LLM: nicht auf ihn warten
                return
            continue
        if item is END:
            return
        if isinstance(item, tuple) and item and item[0] is ERR:
            raise item[1]
        yield item


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
        # Nur Anzeige und Barge-in: direkt vor und nach jeder echten Wiedergabe (nicht während auf den Satz gewartet wird)
        self.on_play_start: Callable[[], Any] = lambda: None
        self.on_play_end: Callable[[Any], None] = lambda token: None

    def say(self, sentences: Iterable[str]) -> int:
        """Spielt Sätze nacheinander; bricht vor jedem Satz ab, wenn `should_stop` (Barge-in/Notaus)."""
        n = 0
        for s in sentences:
            if self.should_stop():
                break
            wav = self.engine.synthesize(s)
            if self.should_stop():          # während der Synthese unterbrochen
                break
            token = self.on_play_start()
            try:
                if self.should_stop():      # zwischen Synthese und Zustandswechsel unterbrochen: nichts mehr abspielen
                    break
                self.play(wav)
            finally:
                self.on_play_end(token)
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
