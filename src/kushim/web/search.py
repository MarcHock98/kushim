"""Ablauf der Web-Recherche: prüfen, Vorschau, Freigabe, einmaliger Abruf, bereinigen. Der Abruf selbst kommt von außen.

Reihenfolge ist sicherheitsrelevant:
  1. Tool muss eingeschaltet UND verfügbar sein (`ToolGate`), sonst "deaktiviert".
  2. Anfrage wird bereinigt und auf Privates geprüft (`guard`), Treffer -> verweigert.
  3. Der Nutzer sieht die exakte Vorschau; `ActionGate` -> `ApprovalQueue` (einmalig, hash-gebunden, läuft ab, Notaus).
  4. Erst nach Freigabe wird abgerufen, und zwar die URL, die sich aus dem FREIGEGEBENEN Vorschautext ergibt.
  5. Treffer werden bereinigt; auffällige (Einschleus-Muster) kommen nicht ans LLM. Aus Treffern entsteht nie eine Aktion.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..safety.approvals import Approval, ApprovalQueue
from ..safety.gate import ActionGate, ActionRequest, Decision
from ..safety.rules import Harm
from ..tools.registry import WEB_SEARCH, ToolGate, ToolRegistry
from . import guard, wikipedia
from .sanitize import Source, injection_flags, quote_for_llm

ACTION = WEB_SEARCH.name
_PREFIX = f"Websuche bei {wikipedia.HOST}: «"


class WebDenied(Exception):
    """Abruf nicht erlaubt (keine gültige Freigabe, abgelaufen, Notaus, Tool aus)."""


def preview_text(query: str) -> str:
    return f"{_PREFIX}{query}»\nGesendet wird nur dieser Suchtext. Es werden keine weiteren Daten übertragen."


def query_from_preview(description: str) -> str:
    """Holt die Anfrage aus dem (freigegebenen) Vorschautext zurück. ValueError bei fremdem Format."""
    first = description.split("\n", 1)[0]
    if not (first.startswith(_PREFIX) and first.endswith("»")):
        raise ValueError("Vorschau hat ein fremdes Format")
    return first[len(_PREFIX):-1]


def web_reviewer(spec, req: ActionRequest) -> set[Harm]:
    """Zweite, unabhängige Prüfung im Gate: dieselbe Heuristik auf die Anfrage aus dem Vorschautext."""
    try:
        return guard.query_harms(query_from_preview(req.description))
    except ValueError:
        return {Harm.PRIVACY}                      # Format nicht erkennbar: lieber verweigern


@dataclass
class Proposal:
    decision: Decision
    reason: str = ""
    approval: Approval | None = None
    preview: str = ""

    @property
    def approval_id(self) -> str:
        return self.approval.id if self.approval else ""


@dataclass
class Outcome:
    question: str
    sources: list[Source] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)       # Titel von Quellen, die nicht ans LLM gingen (auffällig)
    context: str = ""                                      # fertiger, gekennzeichneter Zitat-Block fürs LLM


class WebSearch:
    def __init__(self, queue: ApprovalQueue, fetch: Callable[[str], str],
                 audit: Callable[[str, str], None] = lambda event, text: None):
        self.queue, self.fetch, self.audit = queue, fetch, audit

    def propose(self, query: str, speaker_verified: bool, user_initiated: bool = True) -> Proposal:
        """Schritt 1 bis 3. Bei ASK enthält das Ergebnis die Vorschau und die Freigabe-Nummer für UI/Sprache."""
        try:
            q = guard.validate(query)
        except ValueError as e:
            return Proposal(Decision.DENY, str(e))
        why = guard.reasons(q)
        if why:
            self.audit("web_query_blocked", ", ".join(why))             # nie der Text selbst
            return Proposal(Decision.DENY, "Die Anfrage " + why[0] + " und geht deshalb nicht hinaus.")
        text = preview_text(q)
        req = ActionRequest(ACTION, text, speaker_verified=speaker_verified, user_initiated=user_initiated)
        decision, approval = self.queue.submit(req)
        if decision is not Decision.ASK or approval is None:
            return Proposal(decision, "Nicht erlaubt (Werkzeug aus, Sprecher unbekannt oder Notaus).")
        return Proposal(Decision.ASK, preview=text, approval=approval)

    def execute(self, approval_id: str) -> Outcome:
        """Schritt 4 und 5. Nur mit gültiger, noch nicht benutzter Freigabe."""
        req = self.queue.take(approval_id)
        if req is None:
            raise WebDenied("Keine gültige Freigabe (abgelehnt, abgelaufen, benutzt oder Notaus).")
        query = query_from_preview(req.description)
        if guard.reasons(query):                                        # nochmals, kurz vor dem Abruf
            raise WebDenied("Anfrage nicht erlaubt.")
        url = wikipedia.check_url(wikipedia.build_url(query))           # feste Grenze: nur diese Domain und dieser Pfad
        self.audit("web_fetch", f"{wikipedia.HOST}: {len(query)} Zeichen")
        hits = wikipedia.parse(self.fetch(url))
        out = Outcome(question=query)
        for h in hits:
            if injection_flags(h.raw):
                out.skipped.append(h.title)                              # auffällig: nicht an das LLM
            else:
                out.sources.append(Source(h.title, h.url, h.extract))
        out.context = quote_for_llm(query, out.sources) if out.sources else ""
        return out


def make_search(registry: ToolRegistry, fetch: Callable[[str], str], ttl: float = 60.0, audit=None) -> WebSearch:
    """Setzt Gate, Hülle und Warteschlange zusammen. `audit(event, text)` ist optional (z. B. MemoryStore.audit)."""
    gate = ActionGate([WEB_SEARCH.spec], reviewer=web_reviewer)
    queue = ApprovalQueue(ToolGate(gate, registry), ttl=ttl)
    return WebSearch(queue, fetch, audit or (lambda event, text: None))
