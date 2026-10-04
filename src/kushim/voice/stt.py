"""Lokale Spracherkennung (faster-whisper). Läuft vollständig offline.

Das Modell wird nie automatisch geladen/heruntergeladen: `local_files_only=True` verhindert
Netzwerkzugriffe. Das Modell legt der Nutzer vorher selbst ab (siehe `docs/research/stt.md`).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Iterable, Protocol

import numpy as np

SAMPLE_RATE = 16_000


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str
    language_probability: float


# Wortschatz-Hinweis für Whisper (feste Wörter, nichts Persönliches): verbessert die Erkennung von Eigennamen und Befehlen.
VOCAB_HINT = "kushim, Claude, Werkzeuge, Werkzeugliste, Recherche, Notaus, abbrechen."


class _Model(Protocol):
    def transcribe(self, audio: Any, **kw: Any) -> tuple[Iterable[Any], Any]: ...


def add_cuda_dll_dirs() -> None:
    """Windows: cuBLAS/cuDNN aus den NVIDIA-PyPI-Paketen (nvidia-*-cu12) auffindbar machen."""
    import os
    import sys
    if sys.platform != "win32":
        return
    import importlib.util
    spec = importlib.util.find_spec("nvidia")
    for base in (spec.submodule_search_locations or []) if spec else []:
        for sub in ("cublas", "cudnn", "cuda_nvrtc"):
            d = os.path.join(base, sub, "bin")
            if os.path.isdir(d):
                os.add_dll_directory(d)
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")


def to_float32(pcm: Any) -> np.ndarray:
    """int16-PCM (16 kHz, mono) -> float32 in [-1, 1]. float32-Eingaben werden begrenzt."""
    arr = np.asarray(pcm)
    if arr.dtype == np.int16:
        return arr.astype(np.float32) / 32768.0
    return np.clip(arr.astype(np.float32), -1.0, 1.0)


class SpeechToText:
    def __init__(self, model: _Model, language: str | None = "de", beam_size: int = 5):
        self.model, self.language, self.beam_size = model, language, beam_size
        self._lock = threading.Lock()          # Abbruch-Erkennung und Antwort dürfen das Modell nie gleichzeitig benutzen

    @classmethod
    def from_local(cls, model_path: str, device: str = "auto", compute_type: str = "default",
                   device_index: int = 0, **kw) -> "SpeechToText":
        """Lädt ein bereits lokal vorhandenes CTranslate2-Whisper-Modell (Verzeichnis).
        `device_index`: Nummer der Grafikkarte (nur bei device="cuda", siehe gpu.py)."""
        add_cuda_dll_dirs()
        from faster_whisper import WhisperModel
        return cls(WhisperModel(model_path, device=device, device_index=device_index, compute_type=compute_type,
                                local_files_only=True), **kw)

    def transcribe(self, pcm: Any) -> Transcript:
        audio = to_float32(pcm)
        if audio.size == 0:
            return Transcript("", self.language or "", 0.0)
        with self._lock:                                     # die Segmente sind ein Generator: auch sie innerhalb der Sperre lesen
            segments, info = self.model.transcribe(
                audio, language=self.language, beam_size=self.beam_size, vad_filter=True,
                condition_on_previous_text=False, initial_prompt=VOCAB_HINT)
            text = " ".join(s.text.strip() for s in segments).strip()
        return Transcript(text, getattr(info, "language", self.language or ""),
                          float(getattr(info, "language_probability", 0.0)))
