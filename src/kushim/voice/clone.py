"""Eigene Stimme als Sprachausgabe (Klon): Voraussetzungen prüfen, Referenz wählen, Engine bauen.

Alles lokal: Der Klon läuft in einem Kindprozess im eigenen venv (tools/chatterbox) ohne Netz (siehe scripts/clone_worker.py); die Aufnahmen
unter voice-data/clone/ werden nur gelesen. Einschalten per `[voice] clone = true` in config.toml (nur der Nutzer). Fehlt etwas, bleibt Piper.
"""
from __future__ import annotations

import wave
from pathlib import Path
from typing import Any, Callable

from .tts import CloneEngine, FallbackEngine

TARGET_SECONDS = 10.0                       # Chatterbox klont am besten aus etwa 10 Sekunden sauberer Sprache


def paths(root: Path) -> dict[str, Path]:
    base = root / "tools" / "chatterbox"
    return {"python": base / "venv" / "Scripts" / "python.exe", "worker": root / "scripts" / "clone_worker.py", "hf": base / "hf",
            "recordings": root / "voice-data" / "clone", "tmp": root / "run" / "clone"}


def _seconds(p: Path) -> float:
    try:
        with wave.open(str(p), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except (wave.Error, OSError, EOFError):
        return 0.0


def pick_reference(recordings: Path, override: str = "") -> Path | None:
    """Die Aufnahme, die der Ziellänge am nächsten kommt (mindestens 3 s); mit `override` genau diese Datei."""
    if override:
        p = Path(override)
        return p if p.is_file() else None
    best, best_gap = None, 1e9
    for p in sorted(recordings.glob("*.wav")):
        sec = _seconds(p)
        if sec >= 3.0 and abs(sec - TARGET_SECONDS) < best_gap:
            best, best_gap = p, abs(sec - TARGET_SECONDS)
    return best


def missing(root: Path, override: str = "") -> str:
    """"" wenn alles da ist, sonst der Grund (in Klartext)."""
    p = paths(root)
    if not p["python"].is_file():
        return "Die Klon-Umgebung fehlt (tools/chatterbox)."
    if not p["hf"].is_dir() or not any(p["hf"].rglob("*.safetensors")):
        return "Das Klon-Modell ist nicht geladen (einmalig: scripts/clone_fetch.py)."
    if pick_reference(p["recordings"], override) is None:
        return "Keine brauchbare Aufnahme in voice-data/clone."
    return ""


def build(root: Path, piper: Any, override: str = "", device: str = "cuda",
          on_note: Callable[[str], None] = lambda s: None) -> Any:
    """Klon mit Piper als Ersatz; fehlt etwas, gibt es nur Piper (mit Hinweis)."""
    why = missing(root, override)
    if why:
        on_note(f"Eigene Stimme nicht verfügbar, Piper bleibt: {why}")
        return piper
    p = paths(root)
    ref = pick_reference(p["recordings"], override)
    engine = CloneEngine(str(p["python"]), str(p["worker"]), str(ref), str(p["tmp"]), device=device)
    return FallbackEngine(engine, piper, lambda w: on_note(f"Eigene Stimme fiel aus, Piper übernimmt: {w}"))
