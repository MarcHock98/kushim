"""Einschreiben der eigenen Stimme: 5 Sätze vorlesen -> Embeddings -> Profil mit kalibrierter Schwelle.

Aufnahmen bleiben im Speicher und werden nach dem Embedding verworfen. Gespeichert wird nur der
Mittelwert-Vektor (siehe voiceprint.py, verschlüsselter Vault).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterator

import numpy as np

from .speaker import SpeakerVerifier, calibrate_threshold

SENTENCES = [
    "Guten Morgen, ich bin es, und ich möchte, dass nur meine Stimme Befehle auslösen darf.",
    "Heute scheint die Sonne über Würzburg, aber am Nachmittag soll es regnen.",
    "Bitte erinnere mich morgen um halb acht an den Termin beim Zahnarzt.",
    "Zwölf Zitronen, sechzehn Äpfel und fünfundzwanzig Kirschen liegen auf dem Tisch.",
    "Das Wetter, die Musik und die Lichter im Wohnzimmer kann kushim gern steuern, aber nur auf meinen Wunsch.",
]


@dataclass
class EnrollResult:
    verifier: SpeakerVerifier
    threshold: float
    mean_similarity: float
    used: int


def enroll(record: Callable[[], Any], embed: Callable[[Any], Any], say: Callable[[str], None] = print,
           attempts_per_sentence: int = 2) -> EnrollResult:
    """`record()` liefert pro Aufruf eine Äußerung (int16 16 kHz), `embed` das Embedding."""
    embeddings = []
    for i, sentence in enumerate(SENTENCES, 1):
        for attempt in range(attempts_per_sentence):
            say(f"[{i}/{len(SENTENCES)}] Bitte vorlesen: {sentence}")
            emb = np.asarray(embed(record()))
            if emb.size:
                embeddings.append(emb)
                break
            say("Zu kurz oder nichts gehört, bitte noch einmal.")
    if len(embeddings) < 3:
        raise RuntimeError("Zu wenige brauchbare Aufnahmen (mindestens 3 nötig)")
    units = [e / np.linalg.norm(e) for e in embeddings]
    sims = [float(np.dot(units[i], units[j])) for i in range(len(units)) for j in range(i + 1, len(units))]
    verifier = SpeakerVerifier(threshold=calibrate_threshold(embeddings), min_enroll=3)
    verifier.enroll(embeddings)
    return EnrollResult(verifier, verifier.threshold, float(np.mean(sims)), len(embeddings))


def frames_recorder(frames: Iterator[Any]) -> Callable[[], Any]:
    from .audio import record_utterance
    return lambda: record_utterance(frames)
