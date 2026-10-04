"""API-Typen für Claude (Entwicklungs-Modus): `claude.folders|status|stop|start|answer|approve|deny|review`.

Transportunabhängig, hängen am `ApiCore` (nur die Oberfläche mit Token, das LLM hat keinen Zugang). Start und Antwort sind zweistufig:
`claude.start`/`claude.answer` liefern nur die Vorschau samt `proposal`-ID, gestartet wird erst mit `claude.approve` (`confirm: true`),
einmalig und über `Control` (Vorschau-Vergleich, EgressGate). Status, Stopp und Ergebnis sind frei. Antworten enthalten keine
Pfade außer dem Namen des Ordners; Claudes Text steht nur als Anzeigetext (`Untrusted` bleibt Daten) in `review`. Fehler sind feste Codes.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from ..safety.gate import Decision
from ..claude_cli.control import Control, Proposal
from ..claude_cli.session import SessionError, State
from .protocol import ApiCore, ApiError

MAX_PENDING = 8


def _state(st: State | None) -> dict[str, Any]:
    if st is None:
        return {"session": None}
    return {"session": {"id": st.id, "folder": st.folder, "branch": st.branch, "turn": st.turn, "status": st.status,
                        "cost_usd": round(st.cost_usd, 4), "seconds": round(st.seconds, 1), "offers": list(st.offers),
                        "denied": list(st.denied), "error": st.error, "updated": st.updated}}


def register_claude(core: ApiCore, control: Control, clock: Callable[[], float] = time.monotonic) -> None:
    pending: dict[str, Proposal] = {}

    def propose(p: Proposal) -> dict[str, Any]:
        if p.decision is not Decision.ASK or p.approval is None:
            return {"allowed": False, "reason": p.reason}
        pending[p.approval_id] = p
        for old in list(pending)[:-MAX_PENDING]:                       # nie unbegrenzt viele offene Vorschläge
            control.deny(pending.pop(old))
        return {"allowed": True, "proposal": p.approval_id, "kind": p.kind, "preview": p.preview}

    def folders(_: dict[str, Any]) -> dict[str, Any]:
        return {"folders": [f.name for f in control.folders()]}

    def status(_: dict[str, Any]) -> dict[str, Any]:
        return _state(control.sessions.state())

    def stop(_: dict[str, Any]) -> dict[str, Any]:
        return {"stopped": control.sessions.stop()}

    def start(payload: dict[str, Any]) -> dict[str, Any]:
        task, folder = payload.get("task", ""), payload.get("folder")
        if not isinstance(task, str) or not (folder is None or isinstance(folder, str)):
            raise ApiError("bad_request")
        return propose(control.propose_start(task, folder, speaker_verified=True))      # die UI ist der Nutzer (Token)

    def answer(payload: dict[str, Any]) -> dict[str, Any]:
        text, allow = payload.get("text"), payload.get("allow", [])
        if not isinstance(text, str) or not isinstance(allow, list) or not all(isinstance(a, str) for a in allow):
            raise ApiError("bad_request")
        return propose(control.propose_answer(text, allow, speaker_verified=True))

    def _take(payload: dict[str, Any]) -> Proposal:
        pid = payload.get("proposal")
        if not isinstance(pid, str) or pid not in pending:
            raise ApiError("unknown_proposal")
        return pending.pop(pid)                                          # jede ID gilt genau einmal

    def approve(payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirm") is not True:
            raise ApiError("confirm_required")
        p = _take(payload)
        if not control.approve(p):
            raise ApiError("not_approved")                              # abgelaufen, abgebrochen oder Notaus
        try:
            return _state(control.execute(p))
        except SessionError:
            raise ApiError("refused")

    def deny(payload: dict[str, Any]) -> dict[str, Any]:
        return {"denied": control.deny(_take(payload))}

    def review(_: dict[str, Any]) -> dict[str, Any]:
        res = control.sessions.result()
        if res is None:
            return {"review": None}
        st, rv, ov = res
        return {**_state(st), "review": {
            "branch": rv.branch, "files": [{"status": s, "path": p} for s, p in rv.files], "protected": list(rv.protected),
            "uncommitted": rv.uncommitted, "shortstat": rv.shortstat, "base_unchanged": rv.base_unchanged, "error": rv.error,
            "overview": {"done": str(ov.done), "question": str(ov.question), "facts": list(ov.facts),
                         "next_steps": [str(n) for n in ov.next_steps], "permission_questions": list(ov.permission_questions),
                         "denied": list(ov.denied), "structured": ov.structured}}}

    for name, fn in (("claude.folders", folders), ("claude.status", status), ("claude.stop", stop), ("claude.start", start),
                     ("claude.answer", answer), ("claude.approve", approve), ("claude.deny", deny), ("claude.review", review)):
        core.register(name, fn)
