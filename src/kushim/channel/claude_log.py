"""Ist der kushim-Channel in Claude Code wirklich an? Prüfung über Claude Codes eigenes MCP-Protokoll (2026-11-23).

Claude Code 2.1.329 schreibt je Sitzung eine Datei nach `%LOCALAPPDATA%/claude-cli-nodejs/Cache/<Ordner>/mcp-logs-kushim/`
(`<Ordner>`: Arbeitsordner, jedes Zeichen außer A-Z, a-z, 0-9 wird "-"). Steht darin "channels feature is not currently
available" und nicht "Channel notifications registered", verwirft Claude Code alles, was kushim schickt: Der Nutzer redet,
aber nichts kommt an. Dann sagt kushim das deutlich (Terminal und einmal per Stimme), statt still zu warten.

Gelesen wird nur die neueste Datei dieser Sitzung, nur ihr Anfang (READ_LIMIT) und nur, ob die zwei Marker vorkommen. Nichts
aus der Datei wird gespeichert, angezeigt oder weitergegeben. Andere Dateien von Claude Code (Verlauf, Terminal) werden nie gelesen.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Callable

SERVER = "kushim"
MARK_OFF = b"channels feature is not currently available"
MARK_ON = b"Channel notifications registered"
READ_LIMIT = 64 * 1024          # die Marker stehen in den ersten Zeilen (Verbindungsaufbau); mehr wird nie gelesen
WAIT = 20.0                     # so lange nach dem Start auf "registered" warten
STEP = 1.0
TERMINAL_HINT = ("Der Sprachkanal ist in Claude Code noch aus: Was du sagst, kommt dort nicht an. "
                 "Siehe README, Abschnitt \"Sprachkanal in Claude Code\".")
SPOKEN_HINT = "Mein Sprachkanal ist noch aus, deine Befehle kommen gerade nicht bei mir an. Im Terminal steht, was zu tun ist."


def project_key(folder: Path) -> str:
    """Ordnername, unter dem Claude Code den Cache eines Arbeitsordners ablegt (C:\\a\\b -> C--a-b)."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(folder))


def log_dir(folder: Path, local_appdata: str | None = None) -> Path | None:
    """Ordner mit den MCP-Protokollen des kushim-Servers für diesen Arbeitsordner; None ohne LOCALAPPDATA."""
    base = local_appdata if local_appdata is not None else os.environ.get("LOCALAPPDATA", "")
    if not base:
        return None
    return Path(base) / "claude-cli-nodejs" / "Cache" / project_key(folder) / f"mcp-logs-{SERVER}"


def _newest(directory: Path, since: float) -> Path | None:
    try:
        files = [p for p in directory.glob("*.jsonl") if p.is_file() and p.stat().st_mtime >= since]
    except OSError:
        return None
    return max(files, key=lambda p: p.stat().st_mtime, default=None)


def markers(path: Path, limit: int = READ_LIMIT) -> tuple[bool, bool]:
    """(aus, an): ob die beiden Marker im Anfang der Datei vorkommen. Liest höchstens `limit` Bytes."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(limit)
    except OSError:
        return False, False
    return MARK_OFF in head, MARK_ON in head


def check(directory: Path | None, since: float, wait: float = WAIT, step: float = STEP,
          clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> str:
    """"on", "off" oder "unknown". Wartet bis `wait` Sekunden auf "registered"; "off" erst, wenn bis dahin nur der Aus-Marker
    da ist. `since`: Startzeit der Sitzung (Dateizeit, time.time), ältere Protokolle zählen nicht."""
    if directory is None:
        return "unknown"
    deadline = clock() + wait
    off = False
    while True:
        newest = _newest(directory, since)
        if newest is not None:
            off, on = markers(newest)
            if on:
                return "on"
        if clock() >= deadline:
            return "off" if off else "unknown"
        sleep(step)
