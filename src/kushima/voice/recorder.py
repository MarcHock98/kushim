"""Aufnahme der eigenen Stimme für den Stimmklon (Teil B aus docs/voice-recording-text.md).

Alles bleibt lokal: WAV-Dateien (24 kHz, mono) unter `voice-data/clone/` (git-ignoriert). Nichts wird
hochgeladen. Pro Absatz eine Datei; vorhandene werden übersprungen (`redo=True` überschreibt).
"""
from __future__ import annotations

import re
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

import numpy as np

from .audio import UtteranceCollector

RATE = 24_000
FRAME = 1920                     # 80 ms bei 24 kHz
MIN_SECONDS, QUIET_PEAK, CLIP_PEAK = 2.0, 1500, 32000
TEXT_FILE = Path("docs") / "voice-recording-text.md"


def load_paragraphs(root: Path) -> list[str]:
    """Absätze aus Teil B: Zeilen der Form `**N.** Text`."""
    text = (root / TEXT_FILE).read_text(encoding="utf-8")
    part_b = text.split("## Teil B", 1)[1].split("## Teil C", 1)[0]
    return [m.group(2).strip() for m in re.finditer(r"^\*\*(\d+)\.\*\*\s+(.+)$", part_b, flags=re.M)]


@dataclass
class TakeInfo:
    seconds: float
    peak: int
    problems: list[str]


def check_take(audio: np.ndarray) -> TakeInfo:
    sec = audio.size / RATE
    peak = int(np.max(np.abs(audio))) if audio.size else 0
    problems = []
    if sec < MIN_SECONDS:
        problems.append("zu kurz")
    if peak < QUIET_PEAK:
        problems.append("zu leise (näher ans Mikrofon oder Pegel erhöhen)")
    if peak >= CLIP_PEAK:
        problems.append("übersteuert (leiser sprechen oder Abstand vergrößern)")
    return TakeInfo(sec, peak, problems)


def save_wav(path: Path, audio: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(np.asarray(audio, dtype=np.int16).tobytes())


def take_collector() -> UtteranceCollector:
    # Längere Pausen erlaubt (Absätze mit Denkpausen), bis 60 s, 10 s auf den Sprechbeginn warten
    return UtteranceCollector(silence_ms=1500, max_ms=60_000, min_ms=500, wait_ms=10_000,
                              rate=RATE, frame=FRAME)


def record_session(out_dir: Path, frames: Iterator[Any], redo: bool = False,
                   say: Callable[[str], None] = print, paragraphs: list[str] | None = None,
                   root: Path | None = None, flush: Callable[[], None] = lambda: None) -> int:
    root = root or out_dir.parents[1]
    paras = paragraphs if paragraphs is not None else load_paragraphs(root)
    saved = 0
    for i, para in enumerate(paras, 1):
        path = out_dir / f"{i:02d}.wav"
        if path.exists() and not redo:
            say(f"[{i}/{len(paras)}] schon vorhanden, überspringe")
            continue
        for attempt in range(3):
            say(f"\n[{i}/{len(paras)}] Bitte vorlesen (Pause vorher, dann sprechen):\n{para}")
            flush()                      # Gepuffertes (Vorlesezeit, eigene Ausgabe) verwerfen
            c = take_collector()
            for f in frames:
                if c.feed(f):
                    break
            audio = c.audio() if c.heard_speech else np.zeros(0, dtype=np.int16)
            info = check_take(audio)
            if info.problems:
                say(f"  Aufnahme {info.seconds:.1f} s, Pegel {info.peak}: " + ", ".join(info.problems)
                    + (" – noch einmal." if attempt < 2 else " – übersprungen."))
                continue
            save_wav(path, audio)
            say(f"  gespeichert: {path.name} ({info.seconds:.1f} s, Pegel {info.peak})")
            saved += 1
            break
    say(f"\nFertig: {saved} neue Aufnahmen in {out_dir}")
    return saved
