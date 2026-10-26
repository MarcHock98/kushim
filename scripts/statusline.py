"""Statuszeile für Claude Code: Modell, Kontext-Füllstand, Abo-Grenzen (und Kosten, falls Claude Code sie liefert).

Claude Code ruft das Skript nach jeder Antwort auf und gibt den Sitzungszustand als JSON über stdin (Felder laut der
eingebauten Beschreibung von Claude Code 2.1.310: `model.display_name`, `context_window.used_percentage`,
`rate_limits.five_hour|seven_day.used_percentage`). Ausgabe: eine Zeile, z. B. "Opus 5.5 · Kontext 42% · 5h 30% · 7d 12%".

Nur Standardbibliothek, kein Netz, schreibt keine Dateien. Fehlerhafte Eingaben ergeben eine kürzere Zeile, nie einen Absturz.
Eingerichtet wird es mit `py scripts\\claude_setup.py --statusline`.
"""
from __future__ import annotations

import json
import sys
from typing import Any

SEP = " · "


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


def main() -> int:
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
    except (ValueError, OSError):
        data = {}
    sys.stdout.buffer.write((render(data) + "\n").encode("utf-8"))      # Claude Code liest UTF-8, Windows-Pipes wären cp1252
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
