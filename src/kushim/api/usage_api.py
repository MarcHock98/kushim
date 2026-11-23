"""API-Typ `usage.get`: Verbrauch der kushim-Sitzung von Claude Code für das kleine Fenster (E2b, nur lesen).

Quelle ist `run/usage.json`, geschrieben von `scripts/statusline.py`, und zwar nur für die Sitzung, die `kushim start` gestartet
hat (`session_id` gleich `run/claude-session.txt`). Die Datei gilt als FREMD (Claude könnte im kushim-Ordner schreiben):
höchstens 1 KB, genau die bekannten Felder, Modellname nur druckbar und höchstens 40 Zeichen, Prozente 0 bis 100 oder null,
Kosten endlich und nicht negativ oder null, Zeitstempel nicht in der Zukunft. Alles andere ergibt `available: false`.
Antwort: {available, model, context_pct, five_h_pct, seven_d_pct, cost_usd, stand, stale}; `stale` ab 30 min Alter.
Kein Netz, keine Token, keine Pfade.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Callable

from .protocol import ApiCore

FILE = Path("run") / "usage.json"
MAX_BYTES = 1024
STALE_SECONDS = 30 * 60
FUTURE_SLACK = 300.0                     # Uhren dürfen leicht abweichen; weiter in der Zukunft = ungültig
MAX_COST = 1_000_000.0
FIELDS = ("model", "context_pct", "five_h_pct", "seven_d_pct", "cost_usd", "stand")
PCT_FIELDS = ("context_pct", "five_h_pct", "seven_d_pct")
EMPTY = {"available": False, "model": "", "context_pct": None, "five_h_pct": None, "seven_d_pct": None,
         "cost_usd": None, "stand": None, "stale": False}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("keine Zahl")
    return float(value)


def read(root: Path, now: float | None = None) -> dict[str, Any]:
    """Liest und prüft `run/usage.json`; bei jedem Fehler `available: false` (nie eine Ausnahme)."""
    now = time.time() if now is None else now
    try:
        with open(root / FILE, "rb") as f:
            raw = f.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return dict(EMPTY)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict) or set(data) != set(FIELDS):
            return dict(EMPTY)
        model = data["model"]
        if not isinstance(model, str) or len(model) > 40 or not all(c.isprintable() for c in model):
            return dict(EMPTY)
        out: dict[str, Any] = {"available": True, "model": model}
        for key in PCT_FIELDS:
            v = data[key]
            if v is not None:
                v = _number(v)
                if not 0.0 <= v <= 100.0:
                    return dict(EMPTY)
            out[key] = v
        cost = data["cost_usd"]
        if cost is not None:
            cost = _number(cost)
            if not 0.0 <= cost <= MAX_COST:
                return dict(EMPTY)
        out["cost_usd"] = cost
        stand = _number(data["stand"])
        if stand is None or stand <= 0 or stand > now + FUTURE_SLACK:
            return dict(EMPTY)
        out["stand"] = int(stand)
        out["stale"] = now - stand > STALE_SECONDS
        return out
    except (OSError, ValueError, TypeError, UnicodeDecodeError, RecursionError):
        return dict(EMPTY)


def register_usage(core: ApiCore, root: Path, clock: Callable[[], float] = time.time) -> None:
    def get(_: dict[str, Any]) -> dict[str, Any]:
        return read(root, clock())

    core.register("usage.get", get)
