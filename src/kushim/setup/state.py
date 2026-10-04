"""`run/setup-state.json`: merkt sich nur "übersprungen" bzw. "erledigt" (nicht sensibel, nicht im Git).

Maßgeblich bleiben die echten Fakten (existiert der Vault, gibt es ein Stimmprofil); die Datei verhindert nur,
dass die Oberfläche bei jedem Start wieder nervt. Fehlt sie oder ist sie kaputt, gilt alles als offen.
Geschrieben wird atomar (Temp-Datei, dann ersetzen).
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

STEPS = ("system", "audio_voice", "wake_words", "safety")
VALUES = ("open", "done", "skipped")
FILE = Path("run") / "setup-state.json"


def path(root: Path) -> Path:
    return root / FILE


def load(root: Path) -> dict[str, dict[str, str]]:
    """Je Schritt {"status", "date"}. Unbekanntes, Kaputtes oder Fehlendes wird zu "open"."""
    state = {s: {"status": "open", "date": ""} for s in STEPS}
    try:
        data = json.loads(path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return state
    if not isinstance(data, dict):
        return state
    for step in STEPS:
        entry = data.get(step)
        if isinstance(entry, dict) and entry.get("status") in VALUES:
            state[step] = {"status": entry["status"], "date": str(entry.get("date", ""))[:10]}
    return state


def mark(root: Path, step: str, status: str, today: str | None = None) -> dict[str, dict[str, str]]:
    if step not in STEPS:
        raise ValueError(f"Unbekannter Schritt: {step!r}")
    if status not in VALUES:
        raise ValueError(f"Unbekannter Status: {status!r}")
    state = load(root)
    state[step] = {"status": status, "date": today or date.today().isoformat()}
    p = path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, p)                      # atomar: nie eine halb geschriebene Datei
    return state
