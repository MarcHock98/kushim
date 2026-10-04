"""API-Typ `transcript.get`: neue Einträge des Live-Transkripts seit `since` (nur lesen, nur im Speicher des Sprachprozesses).

Läuft mit `kushim talk --ui`. Antwort: {"entries": [{id, heard, reply, outcome, ts}], "last": id}. Texte sind Anzeigetext
und werden von der UI nie als HTML oder Anweisung behandelt.
"""
from __future__ import annotations

from typing import Any

from ..voice.transcript import Transcript
from .protocol import ApiCore, ApiError


def register_transcript(core: ApiCore, transcript: Transcript) -> None:
    def get(payload: dict[str, Any]) -> dict[str, Any]:
        since = payload.get("since", 0)
        if isinstance(since, bool) or not isinstance(since, int) or since < 0:
            raise ApiError("bad_request")
        entries = transcript.since(since)
        return {"entries": entries, "last": entries[-1]["id"] if entries else since}

    core.register("transcript.get", get)
