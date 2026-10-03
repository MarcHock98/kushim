"""Freigabe-Warteschlange: ASK-Entscheidungen des ActionGate warten auf die Bestätigung des Nutzers.

- Nur ASK-Verdicts werden eingereiht (ALLOW/DENY nie).
- Eine Freigabe gilt für genau eine Aktion, einmal, und nur für den gezeigten Vorschautext
  (Hash-Bindung: wird die Beschreibung nachträglich geändert, verfällt die Freigabe).
- Abgelaufen, abgelehnt oder bei Notaus: keine Ausführung (fail closed).
"""
from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .gate import ActionGate, ActionRequest, Decision


class Status(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    USED = "used"


def _digest(req: ActionRequest) -> str:
    return hashlib.sha256(f"{req.action}\x00{req.description}\x00{req.amount}".encode()).hexdigest()


@dataclass
class Approval:
    id: str
    request: ActionRequest
    digest: str
    expires_at: float
    status: Status = Status.PENDING


class ApprovalQueue:
    def __init__(self, gate: ActionGate, ttl: float = 120.0,
                 clock: Callable[[], float] = time.monotonic):
        self.gate, self.ttl, self._clock = gate, ttl, clock
        self._items: dict[str, Approval] = {}

    def submit(self, req: ActionRequest) -> tuple[Decision, Approval | None]:
        """Prüft über das Gate. Nur bei ASK entsteht ein wartender Eintrag."""
        verdict = self.gate.check(req)
        if verdict.decision is not Decision.ASK:
            return verdict.decision, None
        item = Approval(secrets.token_urlsafe(12), req, _digest(req), self._clock() + self.ttl)
        self._items[item.id] = item
        return Decision.ASK, item

    def pending(self) -> list[Approval]:
        self._expire()
        return [i for i in self._items.values() if i.status is Status.PENDING]

    def approve(self, approval_id: str, shown_digest: str) -> bool:
        """Freigabe durch den Nutzer; `shown_digest` ist der Hash der angezeigten Vorschau."""
        self._expire()
        item = self._items.get(approval_id)
        if (item is None or item.status is not Status.PENDING or self.gate.killed
                or shown_digest != item.digest or _digest(item.request) != item.digest):
            return False
        item.status = Status.APPROVED
        return True

    def deny(self, approval_id: str) -> bool:
        item = self._items.get(approval_id)
        if item is None or item.status is not Status.PENDING:
            return False
        item.status = Status.DENIED
        return True

    def take(self, approval_id: str) -> ActionRequest | None:
        """Einmalige Entnahme zur Ausführung. Erneut prüfen, damit Notaus/Änderungen greifen."""
        self._expire()
        item = self._items.get(approval_id)
        if (item is None or item.status is not Status.APPROVED or self.gate.killed
                or _digest(item.request) != item.digest):
            return None
        item.status = Status.USED
        return item.request

    def _expire(self) -> None:
        now = self._clock()
        for i in self._items.values():
            if i.status in (Status.PENDING, Status.APPROVED) and now >= i.expires_at:
                i.status = Status.EXPIRED
