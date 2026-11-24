"""Hintergrundprozesse ohne Konsolenfenster, Prozessbäume beenden, venv-Pfade je Betriebssystem.

Läuft kushim ohne eigene Konsole (`pythonw`, Desktop-Verknüpfung "kushim App"), öffnet Windows für jedes gestartete Konsolenprogramm
(`nvidia-smi`, `taskkill`, die Claude CLI ...) ein eigenes Fenster, das kurz aufpoppt. `hidden()` liefert die
Argumente, die das verhindern; auf anderen Systemen ist es leer. Nur für Prozesse benutzen, die der Nutzer nicht sehen soll
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

CREATE_NO_WINDOW = 0x08000000
KILL_GRACE = 1.0                 # macOS/Linux: so lange nach SIGTERM warten, dann SIGKILL


def hidden() -> dict[str, Any]:
    return {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}


def venv_python(venv: Path) -> Path:
    """Interpreter einer venv: Windows `Scripts/python.exe`, sonst `bin/python`."""
    return venv / "Scripts" / "python.exe" if os.name == "nt" else venv / "bin" / "python"


def venv_site_packages(venv: Path) -> list[Path]:
    """site-packages einer venv: Windows `Lib/site-packages`, sonst `lib/python3.X/site-packages` (alle gefundenen)."""
    if os.name == "nt":
        return [venv / "Lib" / "site-packages"]
    return sorted((venv / "lib").glob("python3*/site-packages"))


def parse_ps(text: str) -> dict[int, list[int]]:
    """Ausgabe von `ps -A -o pid=,ppid=` -> {Eltern-PID: [Kind-PIDs]}. Unlesbare Zeilen werden übersprungen."""
    children: dict[int, list[int]] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            continue
        pid, ppid = int(parts[0]), int(parts[1])
        children.setdefault(ppid, []).append(pid)
    return children


def descendants(pid: int, table: dict[int, list[int]]) -> list[int]:
    """Alle Nachkommen von `pid` (Kinder zuerst nach Ebenen), ohne `pid` selbst; Zyklen werden nicht verfolgt."""
    out: list[int] = []
    seen = {pid}
    level = [pid]
    while level:
        nxt = []
        for p in level:
            for c in table.get(p, ()):
                if c not in seen:
                    seen.add(c)
                    out.append(c)
                    nxt.append(c)
        level = nxt
    return out


def _posix_tree(pid: int, run: Callable[..., Any] = subprocess.run) -> list[int]:
    try:
        out = run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return [pid]
    return [pid, *descendants(pid, parse_ps(out.stdout or ""))]


def _signal_all(pids: list[int], sig: int) -> list[int]:
    alive = []
    for p in pids:
        try:
            os.kill(p, sig)
            alive.append(p)
        except OSError:                              # schon beendet oder nicht unserer
            pass
    return alive


def kill_tree(pid: int) -> None:
    """Beendet einen Prozess samt Kindern. Windows: `taskkill /T` (`terminate()` allein lässt Kinder laufen).
    macOS/Linux: Nachkommen über `ps` (lokales Programm) einsammeln, erst SIGTERM, nach KILL_GRACE SIGKILL.
    Nur für ein selbst gestartetes PID aufrufen."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return
    if pid <= 0:
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15, check=False, **hidden())
        except Exception:
            pass
        return
    try:
        tree = _posix_tree(pid)
        alive = _signal_all(list(reversed(tree)), signal.SIGTERM)       # Kinder zuerst
        end = time.monotonic() + KILL_GRACE
        while alive and time.monotonic() < end:
            time.sleep(0.05)
            alive = [p for p in alive if _exists(p)]
        _signal_all(alive, signal.SIGKILL)
    except Exception:
        pass


def _exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:                                             # eigenes, schon beendetes Kind (Zombie) einsammeln
        done, _ = os.waitpid(pid, os.WNOHANG)
        return done == 0
    except ChildProcessError:
        return True                                  # nicht unser Kind: es läuft noch
    except OSError:
        return False
