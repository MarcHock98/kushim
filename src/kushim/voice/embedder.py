"""Stimm-Embedding lokal (sherpa-onnx, WeSpeaker CAM++), komplett offline.

Das Modell wird nie heruntergeladen: der Aufrufer gibt einen lokalen Pfad an. Aus Audio entsteht nur
ein Zahlenvektor; die Aufnahme selbst wird weder gespeichert noch weitergegeben.
"""
from __future__ import annotations

from typing import Any

import numpy as np

SAMPLE_RATE = 16_000
MIN_SECONDS = 0.8        # kürzere Äußerungen liefern unzuverlässige Embeddings


class SherpaEmbedder:
    def __init__(self, extractor: Any):
        self._ex = extractor

    @classmethod
    def from_local(cls, model_path: str, threads: int = 2) -> "SherpaEmbedder":
        import sherpa_onnx
        cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=model_path, num_threads=threads,
                                                          provider="cpu")
        if not cfg.validate():
            raise FileNotFoundError(f"Sprecher-Modell unbrauchbar: {model_path}")
        return cls(sherpa_onnx.SpeakerEmbeddingExtractor(cfg))

    def __call__(self, pcm: Any) -> np.ndarray:
        """int16 oder float32 (16 kHz, mono) -> Embedding. Zu kurzes Audio -> leerer Vektor (wird abgelehnt)."""
        a = np.asarray(pcm)
        x = a.astype(np.float32) / 32768.0 if a.dtype == np.int16 else a.astype(np.float32)
        if x.size < int(MIN_SECONDS * SAMPLE_RATE):
            return np.zeros(0, dtype=np.float32)
        stream = self._ex.create_stream()
        stream.accept_waveform(sample_rate=SAMPLE_RATE, waveform=x)
        stream.input_finished()
        if not self._ex.is_ready(stream):
            return np.zeros(0, dtype=np.float32)
        return np.asarray(self._ex.compute(stream), dtype=np.float32)
