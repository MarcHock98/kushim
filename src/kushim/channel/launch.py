"""Claude Code mit dem kushim-Channel starten, zeigen und beenden (Roadmap v2 B5).

Gestartet wird `claude --session-id <uuid> --name kushim --strict-mcp-config --mcp-config run/kushim-mcp.json
--dangerously-load-development-channels server:kushim` im freigegebenen Arbeitsordner, unter Windows in einem eigenen
`cmd`-Fenster ("kushim-Claude"), das offen bleibt. `--strict-mcp-config` lädt nur den kushim-Server (keine anderen MCP-Server
oder Konnektoren). Claude zeigt beim Start einen Bestätigungsdialog für den Entwicklungs-Channel; den bestätigt der Nutzer.
Claude Code führt Sitzungen über einen Hintergrund-Dienst aus: Ohne Fenster liefe die Sitzung unsichtbar weiter. Darum merkt
sich kushim die Sitzungs-ID (`run/claude-session.txt`), beendet die Sitzung, wenn das Fenster geschlossen wird oder kushim endet
(`claude stop <id>`), und holt sie auf Wunsch zurück (`claude attach <id>`).
Umgebung: `clean_env()` (keine fremden Schlüssel) plus `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` (keine Telemetrie).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

from ..claude_cli.base import clean_env
from ..procflags import hidden

SERVER_NAME = "kushim"
SESSION_NAME = "kushim"
WINDOW_TITLE = "kushim-Claude"
CONFIG = Path("run") / "kushim-mcp.json"
SESSION_FILE = Path("run") / "claude-session.txt"
CREATE_NEW_CONSOLE = 0x00000010               # Windows: Claude bekommt ein eigenes, sichtbares Terminalfenster
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def mcp_config(python: str = sys.executable) -> dict[str, Any]:
    return {"mcpServers": {SERVER_NAME: {"command": python, "args": ["-m", "kushim.channel"]}}}


def write_mcp_config(root: Path, python: str = sys.executable) -> Path:
    path = root / CONFIG
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(mcp_config(python), indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def read_session(root: Path) -> str | None:
    """Sitzungs-ID der zuletzt gestarteten kushim-Sitzung (nur eine echte UUID, sonst None)."""
    try:
        sid = (root / SESSION_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return sid if _UUID.match(sid) else None


def claude_argv(exe: Path, config: Path, session_id: str) -> list[str]:
    return [str(exe), "--session-id", session_id, "--name", SESSION_NAME, "--strict-mcp-config", "--mcp-config", str(config),
            "--dangerously-load-development-channels", f"server:{SERVER_NAME}"]


def visible(argv: list[str]) -> list[str]:
    """Windows: in einem `cmd`-Fenster, das offen bleibt (auch wenn Claude sich in den Hintergrund-Dienst abkoppelt)."""
    if os.name != "nt":
        return argv
    return ["cmd.exe", "/k", "title", WINDOW_TITLE, "&", *argv]


def claude_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = clean_env(base)
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    return env


def launch(exe: Path, folder: Path, root: Path, popen: Callable[..., Any] = subprocess.Popen) -> Any:
    """Startet Claude Code mit dem Channel im Ordner `folder` in einem eigenen Fenster (bewusst sichtbar: das ist die Oberfläche).
    Gibt den Fensterprozess zurück; seine Sitzungs-ID steht danach in `run/claude-session.txt`."""
    config = write_mcp_config(root)
    sid = str(uuid.uuid4())
    (root / SESSION_FILE).write_text(sid, encoding="utf-8")
    flags = CREATE_NEW_CONSOLE if os.name == "nt" else 0
    return popen(visible(claude_argv(exe, config, sid)), cwd=str(folder), env=claude_env(), creationflags=flags)


def show(exe: Path, root: Path, popen: Callable[..., Any] = subprocess.Popen) -> Any:
    """Holt die laufende kushim-Sitzung von Claude Code in ein sichtbares Fenster zurück. None, wenn keine bekannt ist."""
    sid = read_session(root)
    if sid is None:
        return None
    flags = CREATE_NEW_CONSOLE if os.name == "nt" else 0
    return popen(visible([str(exe), "attach", sid]), env=claude_env(), creationflags=flags)


def stop(exe: Path, root: Path, run: Callable[..., Any] = subprocess.run) -> bool:
    """Beendet die kushim-Sitzung von Claude Code (`claude stop <id>`; der Verlauf bleibt erhalten). True, wenn eine bekannt war."""
    sid = read_session(root)
    if sid is None:
        return False
    try:
        run([str(exe), "stop", sid], capture_output=True, text=True, timeout=20, check=False, env=claude_env(), **hidden())
    except (OSError, subprocess.SubprocessError):
        pass
    (root / SESSION_FILE).unlink(missing_ok=True)
    return True
