"""API-Typen für den Modellwechsel (transportunabhängig, hängen am `ApiCore`). Siehe docs/ui-llm-plan.md.

`llm.get` (aktuelles und vorheriges Modell), `llm.list` (installiert, mit Größe wenn Ollama läuft), `llm.probe`,
`llm.set` (Probe, dann erst speichern), `llm.rollback`. Laden und Entfernen gibt es hier noch nicht (eigene Freigabe).
Antworten ohne Pfade; Fehler als feste Codes. `on_change(model)` ist der Haken für den Austausch zur Laufzeit zwischen
zwei Antworten (später an die Pipeline angeschlossen).
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from ..config import Config
from ..llm import manage
from ..llm.ollama import validate_model
from .protocol import ApiCore, ApiError


def register_llm(core: ApiCore, cfg: Config, root: Path,
                 probe_fn: Callable[[str], manage.Probe] = manage.probe,
                 installed_fn: Callable[[Path], list[manage.ModelInfo]] = manage.installed,
                 on_change: Callable[[str], None] = lambda model: None) -> None:
    def name_of(payload: dict[str, Any]) -> str:
        raw = payload.get("model")
        if not isinstance(raw, str):
            raise ApiError("bad_request")
        try:
            return validate_model(raw)
        except ValueError:
            raise ApiError("bad_name")

    def get(_: dict[str, Any]) -> dict[str, Any]:
        return {"model": cfg.llm_model, "previous": manage.load_previous(root),
                "installed": manage.is_installed(root, cfg.llm_model)}

    def listing(_: dict[str, Any]) -> dict[str, Any]:
        models = installed_fn(root)
        return {"models": [{"name": m.name, "size_mb": m.size_mb, "active": m.name == cfg.llm_model} for m in models]}

    def probe(payload: dict[str, Any]) -> dict[str, Any]:
        name = name_of(payload)
        if not manage.is_installed(root, name):
            raise ApiError("not_installed")
        return {"model": name, "probe": asdict(probe_fn(name))}

    def done(result: manage.Switch) -> dict[str, Any]:
        if result.switched:
            on_change(result.model)
        return result.as_dict()

    def set_model(payload: dict[str, Any]) -> dict[str, Any]:
        return done(manage.activate(cfg, root, name_of(payload), probe_fn))

    def back(_: dict[str, Any]) -> dict[str, Any]:
        return done(manage.rollback(cfg, root, probe_fn))

    for name, fn in (("llm.get", get), ("llm.list", listing), ("llm.probe", probe), ("llm.set", set_model),
                     ("llm.rollback", back)):
        core.register(name, fn)
