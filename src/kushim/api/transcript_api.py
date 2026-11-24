"""API-Typ `transcript.get`: Einträge des Live-Transkripts, die sich seit `since` geändert haben (nur lesen, nur im Speicher
des Sprachprozesses).

Läuft mit `kushim talk --ui`. `since` ist eine Änderungsnummer (`rev`), keine id. Antwort:
{"entries": [{id, rev, heard, raw, ts, status, reason, sent_ts, reply, outcome, unspoken}], "last": höchste rev der Antwort (sonst
since)}. `unspoken`: Zahl der Sätze der Antwort, die nur als Text kamen (Stimme aus), sonst 0.
Ein Eintrag kommt mehrfach, wenn er sich ändert (erst `pending`, dann `sent` oder `dropped`, dann mit Antwort); die UI führt
nach `id` zusammen. `id` bleibt stabil (Feedback hängt daran). Texte sind Anzeigetext und werden von der UI nie als HTML
oder Anweisung behandelt.
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
        return {"entries": entries, "last": max((e["rev"] for e in entries), default=since)}

    core.register("transcript.get", get)
