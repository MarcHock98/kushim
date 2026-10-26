"""Hintergrundprozesse ohne Konsolenfenster.

Läuft kushim ohne eigene Konsole (`pythonw`, Desktop-Verknüpfung "kushim App"), öffnet Windows für jedes gestartete Konsolenprogramm
(`git`, `nvidia-smi`, `taskkill`, `ollama`, die Claude CLI ...) ein eigenes Fenster, das kurz aufpoppt. `hidden()` liefert die
Argumente, die das verhindern; auf anderen Systemen ist es leer. Nur für Prozesse benutzen, die der Nutzer nicht sehen soll
(das bewusst geöffnete Live-Fenster `kushim claude watch` bleibt davon ausgenommen).
"""
from __future__ import annotations

import os
from typing import Any

CREATE_NO_WINDOW = 0x08000000


def hidden() -> dict[str, Any]:
    return {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}
