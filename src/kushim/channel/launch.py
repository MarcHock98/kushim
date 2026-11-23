"""Claude Code mit dem kushim-Channel starten, zeigen und beenden (Roadmap v2 B5).

Gestartet wird `claude --session-id <uuid> --name kushim --strict-mcp-config --mcp-config run/kushim-mcp.json
--dangerously-load-development-channels server:kushim` im freigegebenen Arbeitsordner, unter Windows in einem eigenen
`cmd`-Fenster ("kushim-Claude"), das offen bleibt. `--strict-mcp-config` lädt nur den kushim-Server (keine anderen MCP-Server
oder Konnektoren). Claude zeigt beim Start einen Bestätigungsdialog für den Entwicklungs-Channel; den bestätigt der Nutzer.
Claude Code führt Sitzungen über einen Hintergrund-Dienst aus: Ohne Fenster liefe die Sitzung unsichtbar weiter. Darum merkt
sich kushim die Sitzungs-ID (`run/claude-session.txt`), beendet die Sitzung, wenn das Fenster geschlossen wird oder kushim endet
(`claude stop <id>`), und holt sie auf Wunsch zurück (`claude attach <id>`).
Umgebung: `clean_env()` (keine fremden Schlüssel) plus `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` (keine Telemetrie) und
`CLAUDE_CODE_GB_DISK_CACHE_WHEN_TELEMETRY_OFF=1` (Channel-Schalter aus dem lokalen Zwischenspeicher, siehe `claude_env`).
Modell und Aufwand: `--model sonnet --effort high` (config.toml [claude] model/effort, fester Satz, leer = Standard).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from collections import deque
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
# Vorab erlaubt (Claude Code 2.1.329: `--allowedTools`, Namen `mcp__<server>__<werkzeug>`): nur Vorlesen und Anzeigen über
# kushim. Kein Platzhalter, kein Bash, kein Schreiben; jedes andere Werkzeug fragt wie gewohnt im Terminal nach.
ALLOWED_TOOLS = (f"mcp__{SERVER_NAME}__sprich", f"mcp__{SERVER_NAME}__zeige")
# `--model` (Aliasse laut 2.1.329: fable, opus, sonnet; haiku im eingebauten Katalog) und `--effort` (low ... max).
# Fester Satz, damit aus config.toml nie ein beliebiges Argument in die Befehlszeile gelangt.
MODELS = ("sonnet", "opus", "haiku", "fable")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_MODEL, DEFAULT_EFFORT = "sonnet", "high"           # Entscheidung des Nutzers 2026-11-23
# Hinweise, die `kushim start` (Hintergrund-Thread) für die Stimme ablegt; die Sprach-Schleife sagt sie im Leerlauf einmal.
NOTICES: "deque[str]" = deque(maxlen=5)
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


def job_id(session_id: str) -> str:
    """Kurze Job-ID, unter der `claude stop`/`attach` eine Hintergrund-Sitzung kennen (erste 8 Zeichen der Sitzungs-ID;
    so in `claude agents --json` von Claude Code 2.1.311 zu sehen). Die volle ID findet `claude stop` nicht."""
    return session_id.split("-")[0]


def check_options(model: str, effort: str) -> tuple[str, str]:
    """Modell und Aufwand aus config.toml [claude] prüfen (fester Satz; leer = Standard von Claude Code). ValueError sonst."""
    model, effort = (model or "").strip().lower(), (effort or "").strip().lower()
    if model and model not in MODELS:
        raise ValueError(f"model {model!r} nicht erlaubt (erlaubt: {', '.join(MODELS)} oder leer)")
    if effort and effort not in EFFORTS:
        raise ValueError(f"effort {effort!r} nicht erlaubt (erlaubt: {', '.join(EFFORTS)} oder leer)")
    return model, effort


def claude_argv(exe: Path, config: Path, session_id: str, model: str = "", effort: str = "") -> list[str]:
    """`--allowedTools` gibt genau die beiden kushim-Werkzeuge frei (Stimme und Anzeige, ohne andere Wirkung). Ohne diese
    Freigabe wartet jedes `sprich` auf eine Rückfrage im Claude-Fenster, und der Nutzer hört nichts. Alles andere fragt weiter.
    `model`/`effort` (geprüft, leer = Standard) wählen Modell und Aufwand der kushim-Sitzung."""
    model, effort = check_options(model, effort)
    options = (["--model", model] if model else []) + (["--effort", effort] if effort else [])
    return [str(exe), "--session-id", session_id, "--name", SESSION_NAME, "--strict-mcp-config", "--mcp-config", str(config),
            *options, "--allowedTools", ",".join(ALLOWED_TOOLS),
            "--dangerously-load-development-channels", f"server:{SERVER_NAME}"]


def visible(argv: list[str]) -> list[str]:
    """Windows: in einem `cmd`-Fenster, das offen bleibt (auch wenn Claude sich in den Hintergrund-Dienst abkoppelt)."""
    if os.name != "nt":
        return argv
    return ["cmd.exe", "/k", "title", WINDOW_TITLE, "&", *argv]


def claude_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = clean_env(base)
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    # Ohne Telemetrie lädt Claude Code keine Funktionsschalter, und der Schalter für Channels gilt als aus ("channels feature
    # is not currently available", alle kushim-Sitzungen bis 2026-11-23). Diese Variable lässt Claude Code die lokal
    # zwischengespeicherten Schalter lesen, ohne Telemetrie einzuschalten (Option b, Entscheidung des Nutzers 2026-11-23;
    # Option a wäre, DISABLE_NONESSENTIAL_TRAFFIC wegzulassen, siehe README).
    env["CLAUDE_CODE_GB_DISK_CACHE_WHEN_TELEMETRY_OFF"] = "1"
    return env


def launch(exe: Path, folder: Path, root: Path, popen: Callable[..., Any] = subprocess.Popen,
           model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT) -> Any:
    """Startet Claude Code mit dem Channel im Ordner `folder` in einem eigenen Fenster (bewusst sichtbar: das ist die Oberfläche).
    Gibt den Fensterprozess zurück; seine Sitzungs-ID steht danach in `run/claude-session.txt`."""
    argv_check = check_options(model, effort)                 # vor jeder Datei-Änderung: ungültige Werte starten nichts
    config = write_mcp_config(root)
    (root / "run" / "channel.json").unlink(missing_ok=True)   # alte Angabe weg: der Channel dieser Sitzung trägt sich als erster ein
    sid = str(uuid.uuid4())
    (root / SESSION_FILE).write_text(sid, encoding="utf-8")
    flags = CREATE_NEW_CONSOLE if os.name == "nt" else 0
    return popen(visible(claude_argv(exe, config, sid, *argv_check)), cwd=str(folder), env=claude_env(), creationflags=flags)


def show(exe: Path, root: Path, popen: Callable[..., Any] = subprocess.Popen) -> Any:
    """Holt die laufende kushim-Sitzung von Claude Code in ein sichtbares Fenster zurück. None, wenn keine bekannt ist."""
    sid = read_session(root)
    if sid is None:
        return None
    flags = CREATE_NEW_CONSOLE if os.name == "nt" else 0
    return popen(visible([str(exe), "attach", job_id(sid)]), env=claude_env(), creationflags=flags)


def stop(exe: Path, root: Path, run: Callable[..., Any] = subprocess.run) -> bool:
    """Beendet die kushim-Sitzung von Claude Code (`claude stop <id>`; der Verlauf bleibt erhalten). True, wenn eine bekannt war."""
    sid = read_session(root)
    if sid is None:
        return False
    try:
        run([str(exe), "stop", job_id(sid)], capture_output=True, text=True, timeout=20, check=False, env=claude_env(), **hidden())
    except (OSError, subprocess.SubprocessError):
        pass
    (root / SESSION_FILE).unlink(missing_ok=True)
    return True
