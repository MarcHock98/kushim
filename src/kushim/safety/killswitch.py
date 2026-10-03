"""Notaus: Marker-Datei (Windows-Verknüpfung/CLI) und Sprachbefehl.

Beide Wege sind absichtlich ohne Sprecherverifikation und ohne LLM: Anhalten ist immer sicher.
Im Zweifel lieber einmal zu oft anhalten (Fehlalarm ist harmlos, ein verpasster Notaus nicht).
Aufheben geht nur bewusst: `clear()` durch den Nutzer (CLI `kushim resume`), nie per Sprache.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Callable

MARKER = Path("run") / "KILL"

# Wörter/Wendungen, die den Notaus auslösen (nach Normalisierung, als Token-Folge).
_PHRASES = [("notaus",), ("not", "aus"), ("stopp", "alles"), ("stop", "alles"),
            ("alles", "stoppen"), ("alles", "anhalten"), ("emergency", "stop"),
            ("kushim", "stopp"), ("kushim", "stop"), ("sofort", "stopp")]


def _tokens(text: str) -> list[str]:
    t = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return re.findall(r"[a-z]+", t)


def is_kill_phrase(text: str) -> bool:
    toks = _tokens(text)
    for ph in _PHRASES:
        n = len(ph)
        if any(tuple(toks[i:i + n]) == ph for i in range(len(toks) - n + 1)):
            return True
    return False


def marker_path(root: Path) -> Path:
    return root / MARKER


def trigger(root: Path) -> Path:
    p = marker_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("KILL", encoding="utf-8")
    return p


def is_triggered(root: Path) -> bool:
    return marker_path(root).exists()


def clear(root: Path) -> None:
    marker_path(root).unlink(missing_ok=True)


class KillSwitch:
    """Bündelt die Aktionen, die beim Notaus laufen (Gate sperren, Ausgabe stoppen, Dienste beenden)."""

    def __init__(self, root: Path, actions: list[Callable[[], None]]):
        self.root, self.actions = root, actions
        self.fired = False

    def fire(self) -> None:
        trigger(self.root)
        self._run()

    def _run(self) -> None:
        self.fired = True
        for a in self.actions:
            try:
                a()
            except Exception:
                pass            # ein fehlschlagender Schritt darf die anderen nie verhindern

    def poll(self) -> bool:
        """Marker (z. B. von der Verknüpfung gesetzt) prüfen; einmalig auslösen."""
        if is_triggered(self.root) and not self.fired:
            self._run()
        return self.fired

    def on_transcript(self, text: str) -> bool:
        if is_kill_phrase(text):
            self.fire()
            return True
        return False
