"""Stimmprofil im verschlüsselten Vault (nur Zahlenvektor, keine Aufnahme).

Das Profil ist biometrisch und gehört ausschließlich in den Vault (`MemoryStore.set_profile`),
nie in Dateien, Logs oder Slack. Leerer Wert bedeutet: kein Profil.
"""
from __future__ import annotations

import base64
import json

import numpy as np

from ..memory.store import MemoryStore
from .speaker import SpeakerVerifier

KEY = "voiceprint"


def save(store: MemoryStore, verifier: SpeakerVerifier, model: str) -> None:
    vec = verifier.profile_vector()
    if vec is None:
        raise ValueError("Kein Profil zum Speichern")
    payload = {"model": model, "dim": int(vec.size), "threshold": float(verifier.threshold),
               "vec": base64.b64encode(vec.astype(np.float32).tobytes()).decode()}
    store.set_profile(KEY, json.dumps(payload))
    store.audit("voiceprint_saved", f"model={model} dim={vec.size}")


def load(store: MemoryStore, default_threshold: float = 0.6) -> SpeakerVerifier | None:
    raw = store.get_profile().get(KEY, "")
    if not raw:
        return None
    try:
        data = json.loads(raw)
        vec = np.frombuffer(base64.b64decode(data["vec"]), dtype=np.float32)
        if vec.size != int(data["dim"]):
            return None
    except (ValueError, KeyError, TypeError):
        return None                 # kaputtes Profil: lieber kein Profil als ein falsches
    v = SpeakerVerifier(threshold=float(data.get("threshold", default_threshold)))
    v.set_profile_vector(vec)
    return v


def clear(store: MemoryStore) -> None:
    store.set_profile(KEY, "")
    store.audit("voiceprint_cleared", "")
