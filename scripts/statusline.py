"""Statuszeile für Claude Code: Modell, Kontext-Füllstand, Abo-Grenzen (und Kosten, falls Claude Code sie liefert).

Claude Code ruft das Skript nach jeder Antwort auf und gibt den Sitzungszustand als JSON über stdin (Felder laut der
eingebauten Beschreibung von Claude Code 2.1.310: `model.display_name`, `context_window.used_percentage`,
`rate_limits.five_hour|seven_day.used_percentage`). Ausgabe: eine Zeile, z. B. "Opus 5.5 · Kontext 42% · 5h 30% · 7d 12%".

Nur Standardbibliothek, kein Netz. Fehlerhafte Eingaben ergeben eine kürzere Zeile, nie einen Absturz.
Eingerichtet wird es mit `py scripts\\claude_setup.py --statusline`.

E2b (Ja des Nutzers 2026-11-23, Weg A): Zusätzlich schreibt das Skript `run/usage.json` für das kleine Fenster, aber NUR, wenn
`session_id` der Eingabe gleich der Sitzungs-ID in `run/claude-session.txt` ist (die Sitzung, die `kushim start` gestartet hat).
Andere Claude-Sitzungen schreiben nichts. Inhalt nur: Modellname (höchstens 40 druckbare Zeichen), Kontext %, 5h %, 7d %
(je 0 bis 100 oder null), Kosten (oder null), Zeitstempel. Atomar, höchstens 1 KB, nie Token oder Pfade. Jeder Fehler dabei
wird still verschluckt: die Statuszeile bleibt genau wie vorher.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

SEP = " · "
ROOT = Path(__file__).resolve().parents[1]
SESSION_FILE = Path("run") / "claude-session.txt"
USAGE_FILE = Path("run") / "usage.json"
MAX_USAGE_BYTES = 1024
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _get(data: Any, *keys: str) -> Any:
    for k in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(k)
    return data


def _clean(text: Any, limit: int = 40) -> str:
    """Nur druckbare Zeichen (keine Steuerzeichen im Terminal), gekürzt."""
    if not isinstance(text, str):
        return ""
    return "".join(c for c in text if c.isprintable())[:limit].strip()


def render(data: Any) -> str:
    parts = []
    model = _clean(_get(data, "model", "display_name")) or _clean(_get(data, "model", "id"))
    if model:
        parts.append(model)
    used = _num(_get(data, "context_window", "used_percentage"))
    if used is not None:
        parts.append(f"Kontext {round(used)}%")
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        pct = _num(_get(data, "rate_limits", key, "used_percentage"))
        if pct is not None:
            parts.append(f"{label} {round(pct)}%")
    cost = _num(_get(data, "cost", "total_cost_usd"))
    if cost is not None:
        parts.append(f"{cost:.2f} USD")
    return SEP.join(parts) or "Claude Code"


def _finite(value: Any, low: float, high: float) -> float | None:
    n = _num(value)
    return n if n is not None and math.isfinite(n) and low <= n <= high else None


def usage(data: Any, now: float | None = None) -> dict[str, Any]:
    """Nur die festen Felder für `run/usage.json` (keine Token, keine Pfade, kein Gesprächstext)."""
    return {"model": _clean(_get(data, "model", "display_name")) or _clean(_get(data, "model", "id")),
            "context_pct": _finite(_get(data, "context_window", "used_percentage"), 0.0, 100.0),
            "five_h_pct": _finite(_get(data, "rate_limits", "five_hour", "used_percentage"), 0.0, 100.0),
            "seven_d_pct": _finite(_get(data, "rate_limits", "seven_day", "used_percentage"), 0.0, 100.0),
            "cost_usd": _finite(_get(data, "cost", "total_cost_usd"), 0.0, 1_000_000.0),
            "stand": int(time.time() if now is None else now)}


def _own_session(root: Path) -> str:
    """Sitzungs-ID aus `run/claude-session.txt` (von `kushim start` geschrieben), nur eine echte UUID, sonst ""."""
    with open(root / SESSION_FILE, "rb") as f:
        sid = f.read(100).decode("utf-8", "replace").strip()
    return sid if _UUID.fullmatch(sid) else ""


def write_usage(data: Any, root: Path | None = None, now: float | None = None) -> bool:
    """Schreibt `run/usage.json` nur für die kushim-Sitzung. True, wenn geschrieben wurde. Legt keine Ordner an."""
    root = ROOT if root is None else root
    sid = _get(data, "session_id")
    if not isinstance(sid, str) or not _UUID.fullmatch(sid):
        return False
    try:
        own = _own_session(root)
    except OSError:
        return False
    if not own or own != sid:
        return False
    raw = json.dumps(usage(data, now), ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(raw) > MAX_USAGE_BYTES:
        return False
    target = root / USAGE_FILE
    tmp = target.with_name(f"usage.{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(raw)
        os.replace(tmp, target)                                         # atomar: nie eine halbe Datei
    finally:
        if tmp.exists():
            tmp.unlink()
    return True


def main() -> int:
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
    except (ValueError, OSError):
        data = {}
    sys.stdout.buffer.write((render(data) + "\n").encode("utf-8"))      # Claude Code liest UTF-8, Windows-Pipes wären cp1252
    sys.stdout.flush()
    try:
        write_usage(data)
    except Exception:                                                   # noqa: BLE001 (die Statuszeile darf nie brechen)
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
