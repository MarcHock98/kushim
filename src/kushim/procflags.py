"""Hintergrundprozesse ohne Konsolenfenster.

Läuft kushim ohne eigene Konsole (`pythonw`, Desktop-Verknüpfung "kushim App"), öffnet Windows für jedes gestartete Konsolenprogramm
(`nvidia-smi`, `taskkill`, die Claude CLI ...) ein eigenes Fenster, das kurz aufpoppt. `hidden()` liefert die
Argumente, die das verhindern; auf anderen Systemen ist es leer. Nur für Prozesse benutzen, die der Nutzer nicht sehen soll
"""
from __future__ import annotations

import os
import subprocess
from typing import Any

CREATE_NO_WINDOW = 0x08000000


def hidden() -> dict[str, Any]:
    return {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}


def kill_tree(pid: int) -> None:
    """Beendet einen Prozess samt Kindern (`taskkill /T`); `terminate()` allein lässt Kinder unter Windows laufen.
    Nur für ein selbst gestartetes PID aufrufen."""
    if os.name != "nt":
        return
    try:
        subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True, timeout=15, check=False, **hidden())
    except Exception:
        pass
