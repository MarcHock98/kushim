"""Live-Ansicht für einen Claude-Lauf: zeigt in einem eigenen Terminalfenster, was Claude gerade tut.

Claude schreibt seine Ereignisse (stream-json) in `run/claude-live.jsonl`; dieses Fenster liest die Datei nur und zeigt sie an. Es hat keine
Rechte über den Lauf: Fenster schließen stoppt nichts (Stoppen: "Stopp Claude", Notaus oder `kushim claude stop`). Text von Claude wird vor der
Anzeige von Steuerzeichen/Escape-Folgen befreit (Terminal-Einschleusung).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from ..web.sanitize import clean_text

LIVE = "run/claude-live.jsonl"


def live_path(root: Path) -> Path:
    return root / LIVE


def last_result(text: str) -> str | None:
    """Die letzte `result`-Zeile eines stream-json-Laufs (gleiche Felder wie das frühere Einzel-JSON) oder None."""
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("type") == "result":
            return line
    return None


def _tool_line(block: dict) -> str:
    name = str(block.get("name", "?"))
    inp = block.get("input") if isinstance(block.get("input"), dict) else {}
    detail = inp.get("command") or inp.get("file_path") or inp.get("path") or inp.get("pattern") or inp.get("description") or ""
    return f"  > {name}: {clean_text(str(detail), 160)}".rstrip(": ")


def format_event(line: str) -> list[str]:
    """Zeilen zur Anzeige für ein Ereignis (leer, wenn es nichts Wichtiges zeigt)."""
    try:
        data = json.loads(line)
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    kind = data.get("type")
    if kind == "system" and data.get("subtype") == "init":
        return ["Claude startet ..."]
    if kind == "assistant":
        msg = data.get("message") if isinstance(data.get("message"), dict) else {}
        out = []
        for block in msg.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and str(block.get("text", "")).strip():
                out.append(str(clean_text(str(block["text"]), 400)))
            elif block.get("type") == "tool_use":
                out.append(_tool_line(block))
        return out
    if kind == "result":
        cost = data.get("total_cost_usd")
        tail = f" (Kosten laut CLI: {cost:.2f} USD, Abo)" if isinstance(cost, (int, float)) else ""
        return ["", "Fertig." + tail if not data.get("is_error") else "Claude meldet einen Fehler."]
    return []


def run_watch(root: Path, out: Callable[[str], None] = print, sleep: Callable[[float], None] = time.sleep,
              state: Callable[[], str] | None = None, poll: float = 0.5, max_idle: float = 7200.0) -> int:
    """Zeigt neue Zeilen, bis der Lauf nicht mehr läuft. `state()` liefert "running" | "waiting" | ... (None = nur Datei lesen)."""
    path = live_path(root)
    pos, idle = 0, 0.0
    out("kushim: Live-Ansicht von Claude. Dieses Fenster nur anzeigen; Schließen stoppt nichts.")
    while idle < max_idle:
        got = False
        if path.exists():
            with path.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(pos)
                chunk = f.read()
                complete = chunk[: chunk.rfind("\n") + 1]          # nur vollständige Zeilen
                pos += len(complete.encode("utf-8"))
            for line in complete.splitlines():
                for text in format_event(line):
                    out(text)
                    got = True
        if state is not None and state() != "running" and not got:
            return 0
        idle = 0.0 if got else idle + poll
        sleep(poll)
    return 0
