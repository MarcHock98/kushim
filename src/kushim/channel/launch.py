"""Claude Code mit dem kushim-Channel starten (Roadmap v2 B5): MCP-Konfiguration schreiben, Befehl bauen, eigenes Fenster.

Gestartet wird `claude --strict-mcp-config --mcp-config run/kushim-mcp.json --dangerously-load-development-channels
server:kushim` im freigegebenen Arbeitsordner. `--strict-mcp-config` lädt nur den kushim-Server (keine anderen MCP-Server oder
Konnektoren). Claude zeigt beim Start einen Bestätigungsdialog für den Entwicklungs-Channel; den bestätigt der Nutzer selbst.
Umgebung: `clean_env()` (keine fremden Schlüssel) plus `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` (keine Telemetrie).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from ..claude_cli.base import clean_env

SERVER_NAME = "kushim"
CONFIG = Path("run") / "kushim-mcp.json"
CREATE_NEW_CONSOLE = 0x00000010               # Windows: Claude bekommt ein eigenes, sichtbares Terminalfenster


def mcp_config(python: str = sys.executable) -> dict[str, Any]:
    return {"mcpServers": {SERVER_NAME: {"command": python, "args": ["-m", "kushim.channel"]}}}


def write_mcp_config(root: Path, python: str = sys.executable) -> Path:
    path = root / CONFIG
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(mcp_config(python), indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def claude_argv(exe: Path, config: Path) -> list[str]:
    return [str(exe), "--strict-mcp-config", "--mcp-config", str(config),
            "--dangerously-load-development-channels", f"server:{SERVER_NAME}"]


def claude_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = clean_env(base)
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    return env


def launch(exe: Path, folder: Path, root: Path, popen: Callable[..., Any] = subprocess.Popen) -> Any:
    """Startet Claude Code mit dem Channel im Ordner `folder` in einem eigenen Fenster (bewusst sichtbar: das ist die Oberfläche)."""
    config = write_mcp_config(root)
    flags = CREATE_NEW_CONSOLE if os.name == "nt" else 0
    return popen(claude_argv(exe, config), cwd=str(folder), env=claude_env(), creationflags=flags)
