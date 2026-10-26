"""API-Typ `safety.overview`: Sicherheitsstatus für die Oberfläche (nur lesen).

Zeigt: Modus A/C, Notaus, aktive Werkzeuge, Vault (lokal/Netz, vorhanden, offen), Backup-Alter, Geldlimit, letzte
Audit-Einträge. Nie Pfade, Schlüssel, Token oder Stimmprofile; Audit-Details sind auf 160 Zeichen gekürzt. Das LLM hat keinen Zugang.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from ..memory.store import MemoryStore
from ..memory.vault import is_vault, parse_location, resolve_local
from ..safety import killswitch
from .protocol import ApiCore

AUDIT_LIMIT = 50
DETAIL_CHARS = 160


def backup_age_days(target: str, now: float) -> float | None:
    """Alter der neuesten Sicherung in Tagen; None, wenn keine gefunden wird oder das Ziel nicht lesbar ist."""
    if not target:
        return None
    try:
        base = resolve_local(target)
        snaps = [p.stat().st_mtime for p in base.glob("vault-*") if p.is_dir()]
    except OSError:
        return None
    return round((now - max(snaps)) / 86400, 2) if snaps else None


def register_safety_view(core: ApiCore, live: Any, root: Path, registry: Any = None,
                         store: MemoryStore | None = None, money_limit: float = 0.0,
                         clock: Callable[[], float] = time.time) -> None:
    def overview(_: dict[str, Any]) -> dict[str, Any]:
        cfg = live.get() if hasattr(live, "get") else live
        scheme, rest = parse_location(cfg.memory_location)
        try:
            exists = scheme == "local" and is_vault(resolve_local(rest))
        except OSError:
            exists = False
        now = clock()
        audit: list[dict[str, Any]] = []
        if store is not None:
            try:
                audit = [{"ts": t, "event": e, "detail": d[:DETAIL_CHARS]} for t, e, d in store.audit_tail(AUDIT_LIMIT)]
            except Exception:                             # noqa: BLE001 (Anzeige darf nie stören)
                audit = []
        tools = None
        if registry is not None:
            tools = [name for name in registry.tools if registry.is_active(name)]
        return {
            "mode": "C" if cfg.claude_enabled else "A",
            "kill": killswitch.is_triggered(root),
            "tools_active": tools,
            "vault": {"where": "local" if scheme == "local" else "remote", "exists": exists, "open": store is not None},
            "backup": {"configured": bool(cfg.backup_target), "age_days": backup_age_days(cfg.backup_target, now)},
            "money_limit_eur": money_limit,
            "audit": audit,
        }

    core.register("safety.overview", overview)
