"""Mehrere Sprachbefehls-Gruppen hintereinander (Wake Words, Werkzeuge): die erste, die den Satz versteht, antwortet.

Wartet eine Gruppe auf eine Bestätigung ("ja"/"nein"), bekommt SIE den nächsten Satz zuerst, damit ein "ja" nie bei der falschen Gruppe landet.
"""
from __future__ import annotations

from typing import Any


class CommandChain:
    def __init__(self, handlers: list[Any]):
        self.handlers = list(handlers)

    @property
    def awaiting(self) -> bool:
        return any(getattr(h, "awaiting", False) for h in self.handlers)

    def handle(self, text: str, verified: bool, strong: bool = True) -> str | None:
        for h in self.handlers:
            if getattr(h, "awaiting", False):
                return h.handle(text, verified, strong)
        for h in self.handlers:
            answer = h.handle(text, verified, strong)
            if answer is not None:
                return answer
        return None

    def announcement(self) -> str | None:
        """Meldung von sich aus (z. B. Claude ist fertig), falls eine Gruppe eine hat."""
        for h in self.handlers:
            fn = getattr(h, "announcement", None)
            if fn is not None:
                msg = fn()
                if msg:
                    return msg
        return None
