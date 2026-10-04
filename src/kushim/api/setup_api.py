"""API-Typen für den Setup-Assistenten und den Notaus (transportunabhängig, hängen am `ApiCore`).

Erster Schnitt (siehe docs/ui-setup-plan.md): Status der vier Schritte, Überspringen/Wiedereröffnen/Bestätigen,
Geräteliste, Notaus auslösen und bewusst aufheben. Noch nicht hier: Vault anlegen, Aufnahme-Sitzung, Wake Words
ändern (kommen mit eigener Freigabe-Logik).

Regeln: Antworten enthalten nur Zustände und Namen, nie Schlüssel, Token, Pfade oder Audio. Fehler sind kurze feste
Codes (`ApiError`). Der Notaus lässt sich immer auslösen; Aufheben braucht `confirm: true`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..llm.ollama import DEFAULT_MODEL
from ..safety import killswitch
from ..setup import state as setup_state
from ..setup import status as setup_status
from .protocol import ApiCore, ApiError


def _step(payload: dict[str, Any]) -> str:
    step = payload.get("step")
    if not isinstance(step, str) or step not in setup_state.STEPS:
        raise ApiError("bad_step")
    return step


def register_setup(core: ApiCore, root: Path, vault_state: Callable[[], str],
                   list_devices: Callable[[], dict[str, list[str]]] | None = None,
                   llm_model: str = DEFAULT_MODEL) -> None:
    """Hängt `setup.*`, `audio.devices` und `safety.*` an den Kern."""

    def overview() -> dict[str, Any]:
        steps = setup_status.compute(root, vault_state, llm_model)
        return {"steps": [{"step": s.step, "title": s.title, "status": s.status, "detail": s.detail} for s in steps],
                "first_start": setup_status.first_start(steps),
                "restricted": setup_status.restricted_notes(steps),
                "kill": setup_status.kill_active(root)}

    def status(_: dict[str, Any]) -> dict[str, Any]:
        return overview()

    def skip(payload: dict[str, Any]) -> dict[str, Any]:
        setup_state.mark(root, _step(payload), "skipped")
        return overview()

    def reopen(payload: dict[str, Any]) -> dict[str, Any]:
        setup_state.mark(root, _step(payload), "open")
        return overview()

    def done(payload: dict[str, Any]) -> dict[str, Any]:
        step = _step(payload)
        if step not in setup_status.MANUAL_DONE:      # die anderen Schritte ergeben sich aus echten Fakten
            raise ApiError("not_allowed")
        setup_state.mark(root, step, "done")
        return overview()

    def devices(_: dict[str, Any]) -> dict[str, Any]:
        if list_devices is None:
            raise ApiError("unavailable")
        try:
            found = list_devices()
        except Exception:
            raise ApiError("unavailable")
        return {"inputs": [str(n) for n in found.get("inputs", [])], "outputs": [str(n) for n in found.get("outputs", [])]}

    def kill_status(_: dict[str, Any]) -> dict[str, Any]:
        return {"kill": killswitch.is_triggered(root)}

    def kill(_: dict[str, Any]) -> dict[str, Any]:
        killswitch.trigger(root)                      # immer erlaubt: Anhalten ist sicher
        return {"kill": True}

    def resume(payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirm") is not True:        # bewusster Schritt, nie versehentlich
            raise ApiError("confirm_required")
        killswitch.clear(root)
        return {"kill": False}

    for name, fn in (("setup.status", status), ("setup.skip", skip), ("setup.reopen", reopen), ("setup.done", done),
                     ("audio.devices", devices), ("safety.status", kill_status), ("safety.kill", kill),
                     ("safety.resume", resume)):
        core.register(name, fn)
