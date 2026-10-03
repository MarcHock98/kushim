"""ActionGate: jede Aktion der KI läuft hier durch. Default-Deny, Fail-Closed.

Entscheidungsreihenfolge (die erste zutreffende gewinnt):
  1. Notaus aktiv                         -> DENY
  2. Aktion nicht registriert (unbekannt) -> DENY
  3. Aktion dauerhaft gesperrt            -> DENY
  4. Schaden gemeldet (Aktion/Prüfer)     -> DENY
  5. Prüfer nötig, aber nicht verfügbar   -> DENY (fail closed)
  6. Geld-/Kostenlimit überschritten      -> DENY
  7. Sprecher nicht verifiziert           -> DENY
  8. Umkehrbarkeit/Dritte/Außenwirkung    -> ASK (Vorschau + Bestätigung)
  9. sonst (nur Lesen, lokal)             -> ALLOW
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from ..memory.store import MemoryStore
from .rules import Harm


class Risk(str, Enum):
    READ = "lesen"                  # nur lokal lesen, keine Wirkung
    REVERSIBLE = "umkehrbar"        # z.B. Entwurf, Papierkorb
    IRREVERSIBLE = "unumkehrbar"    # z.B. endgültig löschen, senden
    FORBIDDEN = "gesperrt"          # nie erlaubt (Zahlungen, Überweisungen, ...)


class Decision(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True)
class ActionSpec:
    name: str
    risk: Risk
    external_effect: bool = False    # wirkt nach außen (Mail, Netz, Geräte)
    affects_third_parties: bool = False
    costs_money: bool = False


@dataclass
class ActionRequest:
    action: str
    description: str                 # exakte Vorschau, wird dem Nutzer gezeigt
    amount: float = 0.0              # Geld/Kosten in EUR
    speaker_verified: bool = False
    user_initiated: bool = False
    harms: set[Harm] = field(default_factory=set)


@dataclass
class Verdict:
    decision: Decision
    reason: str


# Prüfer (z.B. zweiter lokaler Modellaufruf): liefert gemeldete Schäden oder wirft bei Ausfall.
Reviewer = Callable[[ActionSpec, ActionRequest], set[Harm]]


class ActionGate:
    def __init__(self, specs: list[ActionSpec], reviewer: Reviewer | None = None,
                 max_amount: float = 0.0, audit: MemoryStore | None = None):
        self.specs = {s.name: s for s in specs}
        self.reviewer = reviewer
        self.max_amount = max_amount        # Standard 0: Geld nie ohne Anpassung durch den Nutzer
        self.audit = audit
        self.killed = False

    def kill(self) -> None:
        """Notaus: blockiert alles bis `resume()` durch den Nutzer."""
        self.killed = True

    def resume(self) -> None:
        self.killed = False

    def _done(self, req: ActionRequest, v: Verdict) -> Verdict:
        if self.audit:
            self.audit.audit(f"action_{v.decision.value}", f"{req.action}: {v.reason}")
        return v

    def check(self, req: ActionRequest) -> Verdict:
        deny = lambda why: self._done(req, Verdict(Decision.DENY, why))
        if self.killed:
            return deny("Notaus aktiv")
        spec = self.specs.get(req.action)
        if spec is None:
            return deny("Unbekannte Aktion (Default-Deny)")
        if spec.risk is Risk.FORBIDDEN:
            return deny("Aktion ist dauerhaft gesperrt")
        if req.harms:
            return deny("Möglicher Schaden: " + ", ".join(h.value for h in req.harms))

        needs_review = spec.risk is not Risk.READ or spec.external_effect
        if needs_review:
            if self.reviewer is None:
                return deny("Kein Prüfer verfügbar (Fail-Closed)")
            try:
                found = self.reviewer(spec, req)
            except Exception:
                return deny("Prüfer ausgefallen (Fail-Closed)")
            if found:
                return deny("Prüfer meldet Schaden: " + ", ".join(h.value for h in found))

        if spec.costs_money or req.amount > 0:
            if req.amount > self.max_amount:
                return deny(f"Betrag {req.amount} über Limit {self.max_amount}")
        if spec.risk is not Risk.READ and not req.speaker_verified:
            return deny("Sprecher nicht verifiziert")
        if not req.user_initiated and (spec.external_effect or spec.risk is not Risk.READ):
            return deny("Nicht vom Nutzer ausgelöst")

        if spec.risk is not Risk.READ or spec.external_effect or spec.affects_third_parties:
            return self._done(req, Verdict(Decision.ASK, "Bestätigung durch den Nutzer nötig"))
        return self._done(req, Verdict(Decision.ALLOW, "Nur Lesen, lokal"))
