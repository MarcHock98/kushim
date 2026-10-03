"""Aktive Wake Words im verschlüsselten Vault (`profile`-Tabelle), per Sprachbefehl änderbar.

Vorrang beim Start von `kushima talk`: Kommandozeile > Vault (per Sprache gesetzt) > Konfiguration.
Gespeichert werden nur Namen vortrainierter Wörter; beim Laden wird erneut geprüft.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..memory.store import MemoryStore
from .trigger import resolve_wake_words

KEY = "wake_words"


def load(store: MemoryStore, root: Path) -> list[str] | None:
    raw = store.get_profile().get(KEY, "")
    if not raw:
        return None
    try:
        words = json.loads(raw)
        if not isinstance(words, list) or not all(isinstance(w, str) for w in words):
            return None
        resolve_wake_words(words, root)       # unbekannte/ungültige Einträge: Liste verwerfen
        return words
    except (ValueError, TypeError):
        return None


def save(store: MemoryStore, words: list[str], root: Path) -> None:
    resolve_wake_words(words, root)            # nie etwas Ungeprüftes speichern
    store.set_profile(KEY, json.dumps(words))
    store.audit("wake_words_changed", ",".join(words))
