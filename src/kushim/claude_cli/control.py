"""Claude steuern (Entwicklungs-Modus): Start und Antwort NUR nach Vorschau und Freigabe; Status, Stopp und Ergebnis sind frei.

Reihenfolge (sicherheitsrelevant):
  1. Nur Text des Nutzers darf etwas anstoßen (`Untrusted`, also Web- oder Claude-Text, wird abgelehnt).
  2. Ordner muss freigegeben sein (folders.py); Anmeldung nötig; API-Konto statt Abo wird vom Geldlimit 0 gestoppt.
  3. Prüfer: keine Schlüssel/IBAN/Kartennummern im Auftrag (er geht samt Projektauszügen an Anthropic).
  4. Vorschau mit allem, was passiert; Freigabe einmalig und hash-gebunden. Beim Ausführen wird die Vorschau aus den gemerkten Angaben
     neu berechnet und mit dem FREIGEGEBENEN Text verglichen: es läuft exakt das, was der Nutzer gesehen hat.
  5. Der Aufruf geht durch das EgressGate (Modus A sperrt, auch wenn das Tool fälschlich als aktiv gälte).
Stark verifizierte Stimme oder UI/CLI sind Sache des Aufrufers (`speaker_verified`).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from ..privacy import EgressDenied, EgressGate
from ..safety.approvals import Approval, ApprovalQueue
from ..safety.gate import ActionGate, ActionRequest, Decision
from ..safety.rules import Harm
from ..tasks import TaskRegistry
from ..tools.registry import CLAUDE_CODE, ToolGate, ToolRegistry
from ..web import guard
from ..web.sanitize import Untrusted
from . import dev
from .base import Auth
from .folders import Folder, resolve
from .session import ClaudeSessions, SessionError, State

ACTION = CLAUDE_CODE.name
MAX_TASK = 1000
_SECRET_WORDS = ("IBAN", "Kartennummer", "schlüsselähnlich")


def normalize_task(text: str) -> str:
    return " ".join(str(text).split())[:MAX_TASK]


def secret_reasons(task: str) -> list[str]:
    return [r for r in guard.reasons(task) if any(k in r for k in _SECRET_WORDS)]


def dev_reviewer(spec, req: ActionRequest) -> set[Harm]:
    """Zweite, unabhängige Prüfung im Gate: Der Auftrag aus dem Vorschautext darf keine Geheimnisse enthalten."""
    for line in req.description.splitlines():
        if line.startswith("Auftrag: «") and line.endswith("»"):
            return {Harm.PRIVACY} if secret_reasons(line[len("Auftrag: «"):-1]) else set()
    return {Harm.PRIVACY}                                           # Format nicht erkennbar: lieber verweigern


@dataclass
class Proposal:
    decision: Decision
    reason: str = ""
    preview: str = ""
    approval: Approval | None = None
    kind: str = ""                                                  # "start" oder "answer"
    folder: Folder | None = None
    task: str = ""
    allow: tuple[str, ...] = ()

    @property
    def approval_id(self) -> str:
        return self.approval.id if self.approval else ""


class Control:
    def __init__(self, registry: ToolRegistry, sessions: ClaudeSessions, egress: EgressGate, auth: Callable[[], Auth],
                 folders: Callable[[], list[Folder]], audit: Callable[[str, str], None] = lambda event, text: None,
                 ttl: float = 120.0, tasks: TaskRegistry | None = None):
        self.registry, self.sessions, self.egress, self.auth, self.folders, self.audit = registry, sessions, egress, auth, folders, audit
        gate = ActionGate([CLAUDE_CODE.spec], reviewer=dev_reviewer, max_amount=0.0)
        self.queue = ApprovalQueue(ToolGate(gate, registry), ttl=ttl)
        self.tasks = tasks if tasks is not None else sessions.tasks
        self.tasks.add_queue(self.queue)                           # "abbrechen" lehnt offene Freigaben ab

    # --- Vorschlag (Start oder Antwort)
    def _submit(self, preview: str, auth: Auth, speaker_verified: bool, user_initiated: bool, **info) -> Proposal:
        amount = 0.0 if auth.subscription else dev.BUDGET_USD
        decision, approval = self.queue.submit(ActionRequest(ACTION, preview, amount=amount, speaker_verified=speaker_verified,
                                                             user_initiated=user_initiated))
        if decision is Decision.ASK and approval is not None:
            return Proposal(Decision.ASK, preview=preview, approval=approval, **info)
        reason = ("Abrechnung über ein API-Konto ist gesperrt (Geldlimit 0)." if not auth.subscription
                  else "Nicht erlaubt (Werkzeug aus, Sprecher nicht verifiziert oder Notaus).")
        return Proposal(decision, reason=reason)

    def propose_start(self, task: str, folder_name: str | None, speaker_verified: bool, user_initiated: bool = True) -> Proposal:
        if isinstance(task, Untrusted):
            self.audit("claude_blocked", "Auftrag stammte aus Web- oder Claude-Inhalten")
            return Proposal(Decision.DENY, reason="Inhalte aus dem Internet oder von Claude dürfen keinen Claude-Lauf auslösen.")
        known = self.folders()
        if not known:
            return Proposal(Decision.DENY, reason="Kein Ordner freigegeben. Hinzufügen: kushim claude add <name> <pfad>")
        folder = resolve(known, folder_name)
        if folder is None:
            return Proposal(Decision.DENY, reason="Ordner unbekannt. Freigegeben: " + ", ".join(f.name for f in known))
        text = normalize_task(task) or dev.DEFAULT_TASK
        if secret_reasons(text):
            self.audit("claude_blocked", ", ".join(secret_reasons(text)))                 # nie der Text selbst
            return Proposal(Decision.DENY, reason="Der Auftrag " + secret_reasons(text)[0] + " und geht deshalb nicht hinaus.")
        auth = self.auth()
        if not auth.logged_in:
            return Proposal(Decision.DENY, reason="In der Claude CLI nicht angemeldet (claude auth login).")
        preview = dev.preview_text(folder.name, text, "(wird beim Start vergeben)", auth.method, self.sessions.budget,
                                   int(self.sessions.timeout_min))
        return self._submit(preview, auth, speaker_verified, user_initiated, kind="start", folder=folder, task=text)

    def propose_answer(self, text: str, allow: Iterable[str], speaker_verified: bool, user_initiated: bool = True) -> Proposal:
        if isinstance(text, Untrusted):
            self.audit("claude_blocked", "Antwort stammte aus Web- oder Claude-Inhalten")
            return Proposal(Decision.DENY, reason="Inhalte aus dem Internet oder von Claude dürfen keinen Claude-Zug auslösen.")
        st = self.sessions.state()
        if st is None or st.status != "waiting":
            return Proposal(Decision.DENY, reason="Es wartet keine Claude-Sitzung auf eine Antwort.")
        answer = normalize_task(text)
        if not answer:
            return Proposal(Decision.DENY, reason="Die Antwort ist leer.")
        if secret_reasons(answer):
            self.audit("claude_blocked", ", ".join(secret_reasons(answer)))
            return Proposal(Decision.DENY, reason="Die Antwort " + secret_reasons(answer)[0] + " und geht deshalb nicht hinaus.")
        allow = tuple(allow)
        bad = [p for p in allow if p not in st.offers]
        if bad:
            return Proposal(Decision.DENY, reason=f"«{bad[0]}» wurde nicht angeboten und darf nicht erlaubt werden.")
        auth = self.auth()
        if not auth.logged_in:
            return Proposal(Decision.DENY, reason="In der Claude CLI nicht angemeldet (claude auth login).")
        preview = dev.preview_text(st.folder, answer, st.worktree, auth.method, self.sessions.budget, int(self.sessions.timeout_min),
                                   resume=True, extra_allowed=allow)
        return self._submit(preview, auth, speaker_verified, user_initiated, kind="answer", task=answer, allow=allow,
                            folder=Folder(st.folder, Path(st.folder_path)))

    # --- Freigabe und Ausführen
    def approve(self, p: Proposal) -> bool:
        return bool(p.approval) and self.queue.approve(p.approval_id, p.approval.digest)

    def deny(self, p: Proposal) -> bool:
        return bool(p.approval) and self.queue.deny(p.approval_id)

    def execute(self, p: Proposal) -> State:
        """Nur mit gültiger, noch nicht benutzter Freigabe. Wirft SessionError sonst."""
        req = self.queue.take(p.approval_id)
        if req is None:
            raise SessionError("Keine gültige Freigabe (abgelehnt, abgelaufen, benutzt oder Notaus).")
        auth = self.auth()
        if p.kind == "start":
            expected = dev.preview_text(p.folder.name, p.task, "(wird beim Start vergeben)", auth.method, self.sessions.budget,
                                        int(self.sessions.timeout_min))
            transport = lambda task: self.sessions.start(p.folder, task)
        else:
            st = self.sessions.state()
            expected = dev.preview_text(st.folder if st else "", p.task, st.worktree if st else "", auth.method, self.sessions.budget,
                                        int(self.sessions.timeout_min), resume=True, extra_allowed=p.allow)
            transport = lambda text: self.sessions.answer(text, p.allow)
        if expected != req.description:                              # das Freigegebene weicht von dem ab, was laufen würde
            raise SessionError("Die Freigabe passt nicht mehr zu dem, was laufen würde. Bitte neu vorschlagen.")
        self.audit("claude_dev_" + p.kind, f"{p.folder.name if p.folder else ''}: {len(p.task)} Zeichen")
        try:
            return self.egress.send("claude-cli", p.task, user_initiated=req.user_initiated, transport=transport)
        except EgressDenied as e:
            raise SessionError(str(e))
