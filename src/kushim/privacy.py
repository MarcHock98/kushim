"""Egress-Gate. Modus A: nichts verlässt den PC. Modus C: Claude nur auf Befehl mit Vorschau+Bestätigung.

Jeder ausgehende Request an einen externen Dienst MUSS durch `EgressGate.send` laufen.
"""
from __future__ import annotations

from typing import Callable

from .memory.store import MemoryStore


class EgressDenied(Exception):
    pass


class EgressGate:
    def __init__(self, enabled: bool, confirm: Callable[[str, str], bool], audit: MemoryStore | None = None):
        """confirm(destination, payload) zeigt dem Nutzer EXAKT den ausgehenden Text."""
        self.enabled = enabled
        self.confirm = confirm
        self.audit = audit

    def _log(self, event: str, dest: str, payload: str) -> None:
        if self.audit:
            self.audit.audit(event, f"{dest}: {len(payload)} Zeichen")

    def send(self, destination: str, payload: str, user_initiated: bool,
             transport: Callable[[str], str]) -> str:
        if not self.enabled:
            self._log("egress_blocked_disabled", destination, payload)
            raise EgressDenied("Modus A aktiv: externe Dienste sind abgeschaltet.")
        if not user_initiated:
            # Nie automatisch: Inhalte aus Web/Mail/Dateien dürfen keinen Abfluss auslösen.
            self._log("egress_blocked_not_user_initiated", destination, payload)
            raise EgressDenied("Nur auf ausdrücklichen Befehl des verifizierten Nutzers erlaubt.")
        if not self.confirm(destination, payload):
            self._log("egress_declined", destination, payload)
            raise EgressDenied("Vom Nutzer abgelehnt.")
        self._log("egress_sent", destination, payload)
        return transport(payload)
