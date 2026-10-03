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


# --- Einschreiben aus langen Aufnahmen (Profil v2) ----------------------------------------------------

def load_wav_16k(path):
    """Liest eine WAV (beliebige Rate, mono oder stereo) und liefert int16 mit 16 kHz."""
    import wave
    with wave.open(str(path), "rb") as w:
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"{path}: nur 16-Bit-WAV unterstützt")
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if rate != 16_000:
        n = int(len(x) * 16_000 / rate)
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
    return x.astype(np.int16)


COHORT_SPEAKERS = 30


def cohort_audio(root, paragraphs, speakers: int = COHORT_SPEAKERS):
    """Fremde/künstliche Vergleichsstimmen für die Schwellenbestimmung: Rauschen plus (wenn das Modell vorhanden
    ist) viele verschiedene Sprecher des Piper-Mehrsprecher-Modells. Gibt Audio (int16, 16 kHz) zurück."""
    out = [(np.random.default_rng(i).normal(size=96_000) * 2000).astype(np.int16) for i in range(3)]
    model = root / "models" / "piper-cohort" / "de_DE-mls-medium.onnx"
    if not model.is_file() or not paragraphs:
        return out
    import io
    import wave
    from piper import PiperVoice, SynthesisConfig
    voice = PiperVoice.load(str(model))
    for sp in range(speakers):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            voice.synthesize_wav(paragraphs[sp % len(paragraphs)], w, syn_config=SynthesisConfig(speaker_id=sp))
        w = wave.open(io.BytesIO(buf.getvalue()))
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
        n = int(len(x) * 16_000 / w.getframerate())
        out.append(np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.int16))
    return out


def window_embeddings(audio, embed):
    from .verify import windows
    out = []
    for seg in windows(np.asarray(audio)):
        e = np.asarray(embed(seg))
        if e.size:
            out.append(e)
    return out


def enroll_from_recordings(paths, embed, cohort_audio, model: str = "", say=print):
    """Baut das Profil v2 aus Aufnahme-Dateien. `cohort_audio`: Liste fremder/künstlicher Audios (int16, 16 kHz)."""
    from .profile import build_profile
    recordings = []
    for p in paths:
        embs = window_embeddings(load_wav_16k(p), embed)
        say(f"  {p.name}: {len(embs)} Stimmabdrücke")
        if embs:
            recordings.append(embs)
    cohort = [e for a in cohort_audio for e in window_embeddings(a, embed)]
    say(f"  Vergleichsstimmen (Kohorte): {len(cohort)} Stimmabdrücke")
    return build_profile(recordings, cohort, model)
