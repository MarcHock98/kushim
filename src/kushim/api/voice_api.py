"""API-Typ `voice.state`: Zustand und Pegel der Sprach-Pipeline für Avatar und Statuszeile (nur lesen).

Antwort: {"active", "state", "level"}. Kein Audio, kein Text. Läuft kein Sprachdienst, ist `active` false.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..voice import statefile
from .protocol import ApiCore


def register_voice(core: ApiCore, root: Path) -> None:
    def state(_: dict[str, Any]) -> dict[str, Any]:
        return statefile.read(root)

    core.register("voice.state", state)
