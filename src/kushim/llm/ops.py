"""Sprachmodelle laden und entfernen, immer mit Vorschau und Freigabe (Plan: docs/ui-llm-plan.md, Modellwechsel Teil 2).

- Laden (`llm.pull`): Ollama (nur Loopback) holt das Modell aus der Ollama-Bibliothek (registry.ollama.ai). Dabei verlässt ein Modellname den PC und
  mehrere GB kommen herein. Nur Modelle der offiziellen Bibliothek (`name:tag`, kein `/`, keine Fremd-Registrys) und nur bei fehlendem Modell.
- Entfernen (`llm.remove`): nie das aktive Modell, nie das vorherige ("Zurück") und nie das letzte installierte; kushim löscht selbst keine Dateien,
  Ollama löscht über seine Schnittstelle.
Beides: verifizierter Sprecher, Vorschau mit Hash-Bindung (ApprovalQueue), einmalig, Ablauf, Notaus. Nichts davon per Sprachmodell oder Web-Inhalt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..config import Config
from ..net.loopback import request_json
from ..safety.approvals import Approval, ApprovalQueue
from ..safety.gate import ActionGate, ActionRequest, ActionSpec, Decision, Risk
from ..safety.rules import Harm
from . import manage
from .ollama import DEFAULT_URL, validate_model

PULL = ActionSpec("llm.pull", Risk.REVERSIBLE, external_effect=True)     # lädt aus dem Netz (über Ollama), rückgängig mit Entfernen
REMOVE = ActionSpec("llm.remove", Risk.IRREVERSIBLE)                      # löscht ein Modell (wieder ladbar, aber Zeit und Daten)
_LIBRARY = re.compile(r"[a-z0-9][a-z0-9._-]{0,60}:[A-Za-z0-9][A-Za-z0-9._-]{0,40}")
PULL_TIMEOUT = 4 * 3600.0


class OpsError(Exception):
    pass


@dataclass
class Proposal:
    decision: Decision
    reason: str = ""
    preview: str = ""
    approval: Approval | None = None
    kind: str = ""
    model: str = ""

    @property
    def approval_id(self) -> str:
        return self.approval.id if self.approval else ""


def library_name(name: str) -> str:
    """Nur `name:tag` der offiziellen Ollama-Bibliothek (nie `hf.co/...`, nie `nutzer/modell`, immer mit Tag)."""
    name = validate_model(name)
    if not _LIBRARY.fullmatch(name):
        raise ValueError("Nur Modelle der offiziellen Ollama-Bibliothek mit Tag (z. B. qwen3.5:9b), keine Fremd-Registrys.")
    return name


def pull_preview(model: str) -> str:
    return (f"Ollama (lokal) lädt das Sprachmodell «{model}» aus der Ollama-Bibliothek (registry.ollama.ai). Gesendet wird nur der Modellname; "
            f"es kommen mehrere GB auf deinen PC (Ordner models/ollama). Das aktive Modell bleibt unverändert, bis du es mit kushim llm set wechselst.")


def remove_preview(model: str) -> str:
    return (f"Das Sprachmodell «{model}» wird von Ollama (lokal) gelöscht. Es gibt keine Rückgabe, nur erneutes Laden (kostet Zeit und Download). "
            f"Nicht gelöscht werden das aktive und das vorherige Modell.")


def _model_from_preview(description: str) -> str:
    m = re.search(r"«([^»]+)»", description)
    return m.group(1) if m else ""


class ModelOps:
    def __init__(self, cfg: Config, root: Path, base_url: str = DEFAULT_URL, request: Callable[..., Any] = request_json,
                 audit: Callable[[str, str], None] = lambda event, text: None, ttl: float = 120.0):
        self.cfg, self.root, self.base_url, self.request, self.audit = cfg, root, base_url, request, audit
        gate = ActionGate([PULL, REMOVE], reviewer=self._reviewer)
        self.gate = gate
        self.queue = ApprovalQueue(gate, ttl=ttl)

    # --- unabhängige Prüfung (läuft im Gate, nicht nur beim Vorschlag)
    def _reviewer(self, spec: ActionSpec, req: ActionRequest) -> set[Harm]:
        model = _model_from_preview(req.description)
        try:
            if spec.name == "llm.pull":
                library_name(model)
            elif spec.name == "llm.remove":
                if self.remove_blocked(model):
                    return {Harm.LONG_TERM}
            else:
                return {Harm.LONG_TERM}
        except ValueError:
            return {Harm.PRIVACY if spec.name == "llm.pull" else Harm.LONG_TERM}
        return set()

    def remove_blocked(self, model: str) -> str:
        """"" = darf entfernt werden, sonst der Grund."""
        try:
            model = validate_model(model)
        except ValueError as e:
            return str(e)
        if not manage.is_installed(self.root, model):
            return "Dieses Modell ist nicht installiert."
        if model == self.cfg.llm_model:
            return "Das aktive Modell wird nie entfernt. Erst wechseln: kushim llm set <modell>."
        if model == manage.load_previous(self.root):
            return "Das vorherige Modell (für „Zurück“) wird nicht entfernt."
        if len(manage.scan_manifests(self.root)) <= 1:
            return "Das letzte installierte Modell wird nie entfernt."
        return ""

    def propose_pull(self, name: str, speaker_verified: bool, user_initiated: bool = True) -> Proposal:
        try:
            model = library_name(name)
        except ValueError as e:
            return Proposal(Decision.DENY, reason=str(e))
        if manage.is_installed(self.root, model):
            return Proposal(Decision.DENY, reason=f"{model} ist schon installiert.")
        return self._submit(PULL.name, pull_preview(model), "pull", model, speaker_verified, user_initiated)

    def propose_remove(self, name: str, speaker_verified: bool, user_initiated: bool = True) -> Proposal:
        why = self.remove_blocked(name)
        if why:
            return Proposal(Decision.DENY, reason=why)
        model = validate_model(name)
        return self._submit(REMOVE.name, remove_preview(model), "remove", model, speaker_verified, user_initiated)

    def _submit(self, action: str, preview: str, kind: str, model: str, verified: bool, user_initiated: bool) -> Proposal:
        decision, approval = self.queue.submit(ActionRequest(action, preview, speaker_verified=verified, user_initiated=user_initiated))
        if decision is Decision.ASK and approval is not None:
            return Proposal(Decision.ASK, preview=preview, approval=approval, kind=kind, model=model)
        return Proposal(decision, reason="Nicht erlaubt (Sprecher unbekannt, Prüfer oder Notaus).")

    def approve(self, p: Proposal) -> bool:
        return bool(p.approval) and self.queue.approve(p.approval_id, p.approval.digest)

    def deny(self, p: Proposal) -> bool:
        return bool(p.approval) and self.queue.deny(p.approval_id)

    def execute(self, p: Proposal) -> str:
        """Nur mit gültiger, noch nicht benutzter Freigabe; der Modellname kommt aus dem FREIGEGEBENEN Text, nicht aus einem gemerkten Wert."""
        req = self.queue.take(p.approval_id)
        if req is None:
            raise OpsError("Keine gültige Freigabe (abgelehnt, abgelaufen, benutzt oder Notaus).")
        model = _model_from_preview(req.description)
        if req.action == PULL.name:
            library_name(model)
            expected = pull_preview(model)
        elif req.action == REMOVE.name:
            if self.remove_blocked(model):
                raise OpsError(self.remove_blocked(model))
            expected = remove_preview(model)
        else:
            raise OpsError("Unbekannte Aktion.")
        if expected != req.description:
            raise OpsError("Die Freigabe passt nicht zu dem, was laufen würde.")
        self.audit("llm_" + req.action.split(".")[1], model)
        try:
            if req.action == PULL.name:
                self.request("POST", f"{self.base_url}/api/pull", {"model": model, "stream": False}, timeout=PULL_TIMEOUT)
                return f"{model} ist geladen." if manage.is_installed(self.root, model) else f"{model}: Ollama meldete Erfolg, Manifest nicht gefunden."
            self.request("DELETE", f"{self.base_url}/api/delete", {"model": model}, timeout=60.0)
            return f"{model} ist entfernt."
        except (OSError, ConnectionError, ValueError) as e:
            raise OpsError(f"Ollama hat das nicht ausgeführt ({type(e).__name__}). Läuft Ollama? (kushim start)")
