"""API-Typ `feedback.add`: Daumen hoch/runter auf eine Antwort (Feedback-Log als spätere Trainingsdaten, nur lokal im Vault).

Nur auf ausdrücklichen Klick des Nutzers: Erst dann werden Frage und Antwort dieses einen Eintrags aus dem Arbeitsspeicher-Transkript als
Episoden im Vault abgelegt und die Bewertung daran gehängt. Ohne Klick wird nie etwas gespeichert. Pro Eintrag nur eine Bewertung.
Nur Einträge mit Antworttext sind bewertbar (nie abgelehnte Stimmen, Notaus oder leere Ergebnisse). Das Audit nennt nur die Bewertung.
Wichtig für später: Bewertungen dürfen nie Regeln oder Berechtigungen ändern, das Lernen (Bandit) bekommt Sicherheitsverletzungen immer negativ.
"""
from __future__ import annotations

import threading
from typing import Any

from ..memory.store import MemoryStore
from ..voice.transcript import Transcript
from .protocol import ApiCore, ApiError

SESSION = "ui-feedback"


def register_feedback(core: ApiCore, transcript: Transcript, store: MemoryStore) -> None:
    rated: set[int] = set()
    lock = threading.Lock()

    def add(payload: dict[str, Any]) -> dict[str, Any]:
        entry, rating = payload.get("entry"), payload.get("rating")
        if isinstance(entry, bool) or not isinstance(entry, int) or isinstance(rating, bool) or rating not in (1, -1):
            raise ApiError("bad_request")
        item = transcript.get(entry)
        if item is None or not item["reply"]:
            raise ApiError("not_found")
        with lock:
            if entry in rated:
                raise ApiError("already_rated")
            rated.add(entry)                                     # zuerst vormerken: zwei gleichzeitige Klicks speichern nur einmal
        try:
            if item["heard"]:
                store.log_episode("user", item["heard"], SESSION)
            ep = store.log_episode("assistant", item["reply"], SESSION)
            store.add_feedback(ep, rating, "")
            store.audit("feedback", f"rating={rating}")
        except Exception:                                        # noqa: BLE001 (nie Interna nach außen)
            with lock:
                rated.discard(entry)
            raise ApiError("unavailable")
        return {"rated": entry, "rating": rating}

    core.register("feedback.add", add)
