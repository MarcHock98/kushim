"""Audio-Ein-/Ausgabe (sounddevice, lokal) und Äußerungs-Erfassung.

Mikrofon und Lautsprecher werden nur geöffnet, wenn der Code ausdrücklich `frames()` bzw.
`play_wav()` aufruft. Es wird nichts mitgeschnitten oder gespeichert; Audio bleibt im Speicher.
Die Gerätewahl erfolgt per Namensteil (z. B. "Arctis 5 Chat"), sonst Systemstandard.
"""
from __future__ import annotations

import io
import wave
from typing import Any, Iterator

import numpy as np

SAMPLE_RATE = 16_000
FRAME = 1280            # 80 ms, passend zu openWakeWord


def find_device(name_part: str | None, kind: str) -> int | None:
    """kind: "input" | "output". Gibt den ersten passenden Index (WASAPI/MME egal) oder None."""
    if not name_part:
        return None
    import sounddevice as sd
    key = f"max_{kind}_channels"
    for i, d in enumerate(sd.query_devices()):
        if name_part.lower() in d["name"].lower() and d[key] > 0:
            return i
    raise LookupError(f"Kein {kind}-Gerät mit '{name_part}'")


class Mic:
    """Mikrofon als Frame-Iterator. `flush()` verwirft Gepuffertes (z. B. nach einer Sprachausgabe,
    damit kushim sich nicht selbst zuhört)."""

    def __init__(self, device: int | None = None, rate: int = SAMPLE_RATE, frame: int = FRAME):
        self.device, self.rate, self.frame = device, rate, frame
        self._stream: Any = None

    def flush(self) -> None:
        if self._stream is not None and self._stream.read_available:
            self._stream.read(self._stream.read_available)

    def __iter__(self) -> Iterator[np.ndarray]:
        import sounddevice as sd
        with sd.InputStream(samplerate=self.rate, channels=1, dtype="int16", blocksize=self.frame,
                            device=self.device) as stream:
            self._stream = stream
            try:
                while True:
                    data, _overflow = stream.read(self.frame)
                    yield data[:, 0].copy()
            finally:
                self._stream = None


def play_wav(data: bytes, device: int | None = None) -> None:
    import sounddevice as sd
    with wave.open(io.BytesIO(data)) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        rate = w.getframerate()
    sd.play(pcm, rate, device=device)
    sd.wait()


def stop_playback() -> None:
    import sounddevice as sd
    sd.stop()


def record_utterance(frames: Iterator[Any], collector: "UtteranceCollector | None" = None) -> np.ndarray:
    """Liest Frames, bis eine Äußerung vollständig ist (oder die Wartezeit ohne Sprache abläuft)."""
    c = collector or UtteranceCollector()
    for f in frames:
        if c.feed(f):
            break
    return c.audio() if c.heard_speech else np.zeros(0, dtype=np.int16)


class UtteranceCollector:
    """Sammelt Frames nach dem Auslöser, bis Stille folgt oder die Maximaldauer erreicht ist."""

    def __init__(self, silence_ms: int = 800, max_ms: int = 15_000, min_ms: int = 300,
                 energy_threshold: float = 500.0, wait_ms: int = 5_000,
                 rate: int = SAMPLE_RATE, frame: int = FRAME):
        n = lambda ms: max(1, round(ms / (frame / rate * 1000)))
        self.silence_frames, self.max_frames, self.min_frames = n(silence_ms), n(max_ms), n(min_ms)
        self.wait_frames = n(wait_ms)    # so lange auf den Sprechbeginn warten
        self.threshold = energy_threshold
        self._frames: list[np.ndarray] = []
        self._quiet = 0
        self._heard_speech = False
        self.peak = 0.0                  # lautester Frame (RMS), nur zur Diagnose

    def feed(self, frame: Any) -> bool:
        """True, sobald die Äußerung vollständig ist."""
        f = np.asarray(frame, dtype=np.int16)
        self._frames.append(f)
        rms = float(np.sqrt(np.mean(f.astype(np.float64) ** 2)))
        self.peak = max(self.peak, rms)
        loud = rms >= self.threshold
        if loud:
            self._heard_speech, self._quiet = True, 0
        else:
            self._quiet += 1
        if len(self._frames) >= self.max_frames:
            return True
        if not self._heard_speech and len(self._frames) >= self.wait_frames:
            return True
        return self._heard_speech and self._quiet >= self.silence_frames \
            and len(self._frames) >= self.min_frames

    def preload(self, frames: Any) -> None:
        """Frames von VOR dem Start voranstellen (Vorlauf). Beendet die Äußerung nie von selbst."""
        for frame in frames:
            f = np.asarray(frame, dtype=np.int16)
            self._frames.append(f)
            rms = float(np.sqrt(np.mean(f.astype(np.float64) ** 2)))
            self.peak = max(self.peak, rms)
            if rms >= self.threshold:
                self._heard_speech, self._quiet = True, 0
            else:
                self._quiet += 1

    def audio(self) -> np.ndarray:
        return np.concatenate(self._frames) if self._frames else np.zeros(0, dtype=np.int16)

    @property
    def heard_speech(self) -> bool:
        return self._heard_speech
