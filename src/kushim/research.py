"""Recherche: Claude zuerst (bessere Websuche), Wikipedia als Ersatz. Eine Vorschau, eine Freigabe, beide möglichen Ziele sichtbar.

Reihenfolge (sicherheitsrelevant):
  1. Nur Text, den der Nutzer selbst gesagt/getippt hat, darf eine Recherche anstoßen (`Untrusted` wird abgelehnt).
  2. Prüfer (web/guard.py): nichts Privates in der Anfrage, sonst verweigert.
  3. Aktiv sein muss `claude.research` (Modus C, CLI angemeldet) und/oder `web.search`. Sonst nichts.
  4. Eine Vorschau nennt jedes mögliche Ziel (Claude/Anthropic; falls Claude ausfällt Wikipedia) und den exakten Suchtext.
     Freigabe einmalig und hash-gebunden (`ApprovalQueue`). Abrechnung über ein API-Konto statt Abo wird vom Geldlimit 0 gestoppt.
  5. Claude (minimaler Modus, nur WebSearch/WebFetch) -> bei Fehler/Timeout/Limit Ersatz über Wikipedia, aber NUR wenn die
     freigegebene Vorschau den Ersatz ausdrücklich nannte.
  6. Antworten sind `Untrusted`: nur anzeigen/sprechen, nie als Befehl lesen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .claude_cli.ask import BUDGET_USD, Answer
from .claude_cli.base import SUBSCRIPTION, Auth
from .privacy import EgressDenied, EgressGate
from .safety.approvals import Approval, ApprovalQueue
from .safety.gate import ActionGate, ActionRequest, Decision
from .safety.rules import Harm
from .tools.registry import CLAUDE_RESEARCH, WEB_SEARCH, ToolGate, ToolRegistry
from .web import guard
from .web.sanitize import Untrusted
from .web.search import Outcome as WikiOutcome
from .tasks import TaskRegistry
from .web.search import WebDenied, WebSearch

ACTION = CLAUDE_RESEARCH.name
_HEAD = "Recherche über Claude (Anthropic): «"
_FALLBACK_LINE = "Falls Claude nicht antwortet, wird stattdessen Wikipedia (de.wikipedia.org) mit demselben Suchtext gefragt."
CANCELLED = "Abgebrochen."
_REASONS = {"timeout": "Zeitüberschreitung", "limit": "Nutzungslimit erreicht", "not_logged_in": "nicht angemeldet",
            "budget": "Budget aufgebraucht", "error": "Fehler", "empty": "leere Antwort", "too_large": "Antwort zu groß",
            "not_installed": "Claude CLI nicht gefunden"}


def preview_text(query: str, method: str, fallback: bool) -> str:
    login = "Abo (claude.ai)" if method == SUBSCRIPTION else "API-Konto (kann Geld kosten)"
    lines = [f"{_HEAD}{query}»",
             "Claude darf nur im Internet suchen und lesen (keine Dateien, keine Befehle). Der Suchtext geht an Anthropic.",
             f"Anmeldung: {login}."]
    if fallback:
        lines.append(_FALLBACK_LINE)
    return "\n".join(lines)


def query_from_preview(description: str) -> str:
    first = description.split("\n", 1)[0]
    if not (first.startswith(_HEAD) and first.endswith("»")):
        raise ValueError("Vorschau hat ein fremdes Format")
    return first[len(_HEAD):-1]


def reviewer(spec, req: ActionRequest) -> set[Harm]:
    """Zweite, unabhängige Prüfung im Gate: dieselbe Heuristik auf die Anfrage aus dem Vorschautext."""
    try:
        return guard.query_harms(query_from_preview(req.description))
    except ValueError:
        return {Harm.PRIVACY}


@dataclass
class Proposal:
    decision: Decision
    route: str = ""                      # "claude" oder "wikipedia"
    reason: str = ""
    preview: str = ""
    approval: Approval | None = None
    inner: object = None                 # Wikipedia-Vorschlag, wenn Claude gar nicht infrage kommt

    @property
    def approval_id(self) -> str:
        return self.approval.id if self.approval else ""


@dataclass
class Outcome:
    kind: str                            # "claude" | "wikipedia" | "none"
    answer: Untrusted = Untrusted("")    # Antwort von Claude (nur anzeigen/sprechen)
    wiki: WikiOutcome | None = None      # Quellen von Wikipedia (Zusammenfassung über web/answer.py)
    note: str = ""                       # z. B. "Claude nicht verfügbar (Zeitüberschreitung), Ersatz: Wikipedia"
    cost_usd: float = 0.0
    skipped: list[str] = field(default_factory=list)


class Research:
    def __init__(self, registry: ToolRegistry, ask: Callable[[str, Callable[[], bool]], Answer], wiki: WebSearch | None,
                 auth: Callable[[], Auth], egress: EgressGate, audit: Callable[[str, str], None] = lambda event, text: None,
                 ttl: float = 120.0, tasks: TaskRegistry | None = None):
        """`egress`: das EgressGate (Modus A/C). Der Claude-Aufruf läuft IMMER durch `egress.send`; ist Modus C aus, geht nichts raus,
        auch wenn das Tool fälschlich als aktiv gälte (zweite, unabhängige Sperre)."""
        self.registry, self.ask, self.wiki, self.auth, self.audit, self.egress = registry, ask, wiki, auth, audit, egress
        gate = ActionGate([CLAUDE_RESEARCH.spec], reviewer=reviewer, max_amount=0.0)       # Geldlimit 0: nur Abo
        self.queue = ApprovalQueue(ToolGate(gate, registry), ttl=ttl)
        self.tasks = tasks if tasks is not None else TaskRegistry()      # gemeinsam mit der Pipeline: "abbrechen" beendet alles Laufende
        self.tasks.add_queue(self.queue)                                  # offene Freigaben werden beim Abbrechen abgelehnt
        if wiki is not None:
            self.tasks.add_queue(wiki.queue)

    def propose(self, query: str, speaker_verified: bool, user_initiated: bool = True) -> Proposal:
        if isinstance(query, Untrusted):
            self.audit("research_blocked", "Anfrage stammte aus Web-Inhalten")
            return Proposal(Decision.DENY, reason="Inhalte aus dem Internet dürfen keine Recherche auslösen.")
        try:
            q = guard.validate(query)
        except ValueError as e:
            return Proposal(Decision.DENY, reason=str(e))
        why = guard.reasons(q)
        if why:
            self.audit("research_blocked", ", ".join(why))                  # nie der Text selbst
            return Proposal(Decision.DENY, reason="Die Anfrage " + why[0] + " und geht deshalb nicht hinaus.")
        claude_on = self.registry.is_active(CLAUDE_RESEARCH.name)
        wiki_on = self.wiki is not None and self.registry.is_active(WEB_SEARCH.name)
        auth = self.auth() if claude_on else Auth(False)
        if claude_on and auth.logged_in:
            text = preview_text(q, auth.method, fallback=wiki_on)
            amount = 0.0 if auth.subscription else BUDGET_USD
            decision, approval = self.queue.submit(ActionRequest(ACTION, text, amount=amount, speaker_verified=speaker_verified,
                                                                 user_initiated=user_initiated))
            if decision is Decision.ASK and approval is not None:
                return Proposal(Decision.ASK, "claude", preview=text, approval=approval)
            reason = ("Abrechnung über ein API-Konto ist gesperrt (Geldlimit 0)." if not auth.subscription
                      else "Nicht erlaubt (Sprecher unbekannt oder Notaus).")
            return Proposal(decision, reason=reason)
        if wiki_on:                                                          # Claude nicht nutzbar: direkt Wikipedia
            inner = self.wiki.propose(q, speaker_verified, user_initiated)
            return Proposal(inner.decision, "wikipedia", inner.reason, inner.preview, inner.approval, inner)
        return Proposal(Decision.DENY, reason="Keine Recherche aktiv. Einschalten: kushim tools enable claude.research oder web.search")

    def approve(self, proposal: Proposal) -> bool:
        """Freigabe durch den Nutzer für genau den gezeigten Vorschautext (je nach Weg in der richtigen Warteschlange)."""
        queue = self.wiki.queue if proposal.route == "wikipedia" and self.wiki is not None else self.queue
        return bool(proposal.approval) and queue.approve(proposal.approval_id, proposal.approval.digest)

    def deny(self, proposal: Proposal) -> bool:
        queue = self.wiki.queue if proposal.route == "wikipedia" and self.wiki is not None else self.queue
        return bool(proposal.approval) and queue.deny(proposal.approval_id)

    def execute(self, proposal: Proposal) -> Outcome:
        """Nur mit gültiger, noch nicht benutzter Freigabe. Wirft WebDenied sonst. Läuft als abbrechbare Aufgabe ("abbrechen")."""
        if proposal.route == "wikipedia":
            with self.tasks.running("Recherche über Wikipedia") as tok:
                wiki = self.wiki.execute(proposal.approval_id)
            return Outcome("none", note=CANCELLED) if tok.cancelled() else Outcome("wikipedia", wiki=wiki)
        req = self.queue.take(proposal.approval_id)
        if req is None:
            raise WebDenied("Keine gültige Freigabe (abgelehnt, abgelaufen, benutzt oder Notaus).")
        query = query_from_preview(req.description)
        if guard.reasons(query):
            raise WebDenied("Anfrage nicht erlaubt.")
        self.audit("claude_research", f"{len(query)} Zeichen")
        with self.tasks.running("Recherche über Claude") as tok:
            try:
                result = self.egress.send("claude-cli", query, user_initiated=req.user_initiated,
                                          transport=lambda q: self.ask(q, tok.cancelled))
            except EgressDenied as e:
                raise WebDenied(str(e))
        if tok.cancelled() or result.reason == "cancelled":                 # Nutzer hat abgebrochen: kein Ersatzweg
            self.audit("research_cancelled", "")
            return Outcome("none", note=CANCELLED, cost_usd=result.cost_usd)
        if result.ok:
            return Outcome("claude", answer=result.text, cost_usd=result.cost_usd)
        reason = _REASONS.get(result.reason, "Fehler")
        fallback_allowed = _FALLBACK_LINE in req.description and self.wiki is not None     # nur wenn die Freigabe es nannte
        if fallback_allowed:
            self.audit("research_fallback", reason)
            with self.tasks.running("Recherche über Wikipedia") as tok2:
                wiki = self.wiki.fallback_fetch(query)
            if tok2.cancelled():
                return Outcome("none", note=CANCELLED, cost_usd=result.cost_usd)
            return Outcome("wikipedia", wiki=wiki, note=f"Claude nicht verfügbar ({reason}), Ersatz: Wikipedia",
                           cost_usd=result.cost_usd)
        return Outcome("none", note=f"Claude nicht verfügbar ({reason}); kein Ersatz freigegeben.", cost_usd=result.cost_usd)
