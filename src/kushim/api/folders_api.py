"""API-Typen für die Ordner-Freigabe von Claude: `claude.folder_list|folder_propose|folder_confirm|folder_deny|folder_remove`.

Freigeben ist zweistufig wie jede Außenwirkung: `folder_propose` prüft den Pfad mit denselben Regeln wie `kushim claude add`
(`claude_cli/folders.validate_path`: Git-Repo, nie Laufwerk/Benutzerordner/System/AppData/.ssh/.claude/Vault, keine Verknüpfung) und liefert
nur die Vorschau samt Vorschlags-ID. Erst `folder_confirm` mit `confirm: true` schreibt (einmalig, die Prüfung läuft dabei erneut).
Entziehen (`folder_remove`) ist immer sofort möglich (Anhalten ist sicher), außer ein Claude-Lauf arbeitet gerade in dem Ordner.
Hier steht der Pfad in der Antwort, weil der Nutzer genau diesen Pfad freigibt; sonst zeigen die `claude.*`-Typen nur Namen.
Das LLM hat keinen Zugang (nur die Oberfläche mit Token).
"""
from __future__ import annotations

import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable

from ..claude_cli import folders as cfolders
from .protocol import ApiCore, ApiError

TTL = 120.0
MAX_PENDING = 4


def register_folders(core: ApiCore, load: Callable[[], Any], validate: Callable[[str], Path],
                     busy: Callable[[str], bool] = lambda name: False,
                     audit: Callable[[str, str], None] | None = None,
                     clock: Callable[[], float] = time.monotonic) -> None:
    """`load()` liefert frisch die Konfiguration (mit `claude_folders` und `set_claude_folders`), `validate(pfad)` die Pfadprüfung,
    `busy(name)` sagt, ob gerade ein Lauf in diesem Ordner arbeitet."""
    pending: dict[str, tuple[str, Path, float]] = {}
    lock = threading.Lock()

    def note(event: str, detail: str) -> None:
        if audit is not None:
            try:
                audit(event, detail)
            except Exception:                                          # noqa: BLE001 (Audit darf nie blockieren)
                pass

    def known() -> list[cfolders.Folder]:
        return cfolders.parse(load().claude_folders)

    def listing(_: dict[str, Any]) -> dict[str, Any]:
        return {"folders": [{"name": f.name, "path": str(f.path)} for f in known()]}

    def check(name: Any, raw: Any) -> tuple[str, Path]:
        if not isinstance(name, str) or not isinstance(raw, str) or not raw or len(raw) > 400:
            raise ApiError("bad_request")
        if not cfolders.NAME_RE.fullmatch(name):
            raise ValueError("Der Name darf nur aus Kleinbuchstaben, Ziffern, - und _ bestehen (höchstens 31 Zeichen).")
        if any(f.name == name for f in known()):
            raise ValueError("Diesen Namen gibt es schon.")
        return name, validate(raw)

    def propose(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            name, path = check(payload.get("name"), payload.get("path"))
        except ValueError as e:
            return {"allowed": False, "reason": str(e)}               # Klartext der Prüfung, nichts wird vorgemerkt
        pid = secrets.token_urlsafe(12)
        with lock:
            now = clock()
            for k in [k for k, v in pending.items() if v[2] <= now]:
                del pending[k]
            while len(pending) >= MAX_PENDING:
                pending.pop(next(iter(pending)))
            pending[pid] = (name, path, now + TTL)
        preview = (f"Claude darf in «{path}» arbeiten (Name «{name}»), immer in einem eigenen Worktree und Branch. "
                   "Beim Arbeiten gehen Auftrag und Ausschnitte aus den Dateien an Anthropic.")
        return {"allowed": True, "proposal": pid, "name": name, "preview": preview, "expires_in": TTL}

    def take(payload: dict[str, Any]) -> tuple[str, Path]:
        pid = payload.get("proposal")
        with lock:
            got = pending.pop(pid, None) if isinstance(pid, str) else None      # jede ID gilt genau einmal
        if got is None or got[2] <= clock():
            raise ApiError("unknown_proposal")
        return got[0], got[1]

    def confirm(payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirm") is not True:
            raise ApiError("confirm_required")
        name, path = take(payload)
        try:
            name, path = check(name, str(path))                       # erneut prüfen: zwischen Vorschau und Klick kann sich etwas ändern
            cfg = load()
            cfg.set_claude_folders([f.entry() for f in known()] + [cfolders.Folder(name, path).entry()])
        except ValueError:
            raise ApiError("refused")
        except ApiError:
            raise
        except Exception:                                              # noqa: BLE001 (Datei nicht beschreibbar o. ä.)
            raise ApiError("not_saved")
        note("claude_folder_add", f"name={name}")
        return listing({})

    def deny(payload: dict[str, Any]) -> dict[str, Any]:
        take(payload)
        return {"denied": True}

    def remove(payload: dict[str, Any]) -> dict[str, Any]:
        name = payload.get("name")
        if not isinstance(name, str):
            raise ApiError("bad_request")
        current = known()
        if not any(f.name == name for f in current):
            raise ApiError("not_found")
        if busy(name):
            raise ApiError("in_use")                                   # erst den Lauf stoppen
        try:
            load().set_claude_folders([f.entry() for f in current if f.name != name])
        except Exception:                                              # noqa: BLE001
            raise ApiError("not_saved")
        note("claude_folder_remove", f"name={name}")
        return listing({})

    for t, fn in (("claude.folder_list", listing), ("claude.folder_propose", propose), ("claude.folder_confirm", confirm),
                  ("claude.folder_deny", deny), ("claude.folder_remove", remove)):
        core.register(t, fn)
