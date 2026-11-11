"""Sprechbare Beschreibung einer Freigabe-Anfrage von Claude (Roadmap v2 C2).

Aus `tool_name` und `input_preview` (Format laut Claude Code 2.1.321: `{ "command": "npm test", "description": "…" }`,
Werte JSON-kodiert, lange Felder gekürzt) wird ein kurzer deutscher Satz, z. B. „Claude möchte den Befehl npm test
ausführen.“ Alles ist fremder Text: nur zum Vorlesen, nie ausführen, nie als Anweisung nehmen. Die Beschreibung ist eine
Hörhilfe; maßgeblich bleibt der Dialog im Terminal (und ab C4 die Sperrliste, die auf den Rohdaten prüft).
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from .bridge import Permission
from .server import clean_text

QUESTION = "Erlauben?"
TERMINAL = "Bitte im Terminal bestätigen."      # solange C3 (Antwort per Stimme) fehlt
MAX_COMMAND = 90                                # so viel vom Befehl wird vorgelesen, danach „und so weiter“
MAX_NAME = 60                                   # Datei-, Werkzeug- und Seitennamen
MAX_SENTENCE = 220

_SYMBOLS = (("&&", " und dann "), ("||", " oder sonst "), ("|", " Pipe "), (";", ", dann "),
            (">", " nach "), ("<", " aus "))
_DROP = str.maketrans("", "", "\"'`")
_SHELLS = {"bash": "", "powershell": " in PowerShell"}
_FILE_ACTIONS = {"edit": "ändern", "multiedit": "ändern", "write": "schreiben", "read": "lesen",
                 "notebookedit": "ändern"}


def field(preview: str, key: str) -> str | None:
    """Wert eines Feldes aus `input_preview` als Text, oder None. Abgeschnittene Werte (ohne Schluss-Anführungszeichen) zählen."""
    m = re.search(r'"' + re.escape(key) + r'"\s*:\s*', preview)
    if m is None:
        return None
    rest = preview[m.end():]
    if not rest.startswith('"'):
        v = re.match(r"[^,}]*", rest).group(0).strip()      # Zahl, true, null …
        return v or None
    try:
        value, _ = json.JSONDecoder().raw_decode(rest)
        return value if isinstance(value, str) else None
    except ValueError:                                      # gekürzt: bis zum Ende nehmen, Escapes grob auflösen
        return rest[1:].replace('\\"', '"').replace("\\\\", "\\").rstrip("…").strip() or None


def _short(text: str, limit: int) -> str:
    text = clean_text(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0] or text[:limit]
    return f"{cut} und so weiter"


def _speak_command(cmd: str) -> str:
    """Shell-Zeichen werden Wörter (die Stimme verschluckt sie sonst), Anführungszeichen fallen weg."""
    for sym, word in _SYMBOLS:
        cmd = cmd.replace(sym, word)
    return _short(cmd.translate(_DROP), MAX_COMMAND)


def _file_name(path: str) -> str:
    name = re.split(r"[\\/]", path.rstrip("\\/"))[-1]
    return _short(name.translate(_DROP), MAX_NAME)


def _words(name: str) -> str:
    return _short(name.replace("__", " ").replace("_", " ").replace("-", " ").translate(_DROP), MAX_NAME)


def describe(perm: Permission) -> str:
    """Ein Satz, was Claude tun möchte. Unbekannte Werkzeuge werden nur beim Namen genannt."""
    tool, preview = perm.tool_name.strip(), perm.input_preview
    key = tool.lower()
    if key in _SHELLS:
        cmd = field(preview, "command")
        where = _SHELLS[key]
        sentence = (f"Claude möchte{where} den Befehl {_speak_command(cmd)} ausführen." if cmd
                    else f"Claude möchte{where} einen Befehl ausführen.")
    elif key in _FILE_ACTIONS:
        path = field(preview, "notebook_path" if key == "notebookedit" else "file_path")
        what = "das Notebook" if key == "notebookedit" else "die Datei"
        sentence = (f"Claude möchte {what} {_file_name(path)} {_FILE_ACTIONS[key]}." if path
                    else f"Claude möchte eine Datei {_FILE_ACTIONS[key]}.")
    elif key == "webfetch":
        host = urlsplit(field(preview, "url") or "").hostname
        sentence = (f"Claude möchte die Webseite {_short(host, MAX_NAME)} abrufen." if host
                    else "Claude möchte eine Webseite abrufen.")
    elif key == "websearch":
        query = field(preview, "query")
        sentence = (f"Claude möchte im Netz nach {_short(query.translate(_DROP), MAX_NAME)} suchen." if query
                    else "Claude möchte im Netz suchen.")
    elif key in ("glob", "grep"):
        sentence = "Claude möchte Dateien durchsuchen."
    elif key in ("task", "agent"):
        sentence = "Claude möchte einen Unter-Agenten starten."
    elif key.startswith("mcp__") and key.count("__") >= 2:
        _, server, name = tool.split("__", 2)
        sentence = f"Claude möchte das Werkzeug {_words(name)} vom Dienst {_words(server)} benutzen."
    elif tool:
        sentence = f"Claude möchte das Werkzeug {_words(tool)} benutzen."
    else:
        sentence = "Claude möchte etwas tun, das eine Freigabe braucht."
    return clean_text(sentence)[:MAX_SENTENCE]


def announce(perm: Permission, ask: bool = False) -> str:
    """Ansage für die Stimme: mit „Erlauben?“ nur, wenn kushim die Antwort auch annehmen kann (C3), sonst Hinweis aufs Terminal."""
    return f"{describe(perm)} {QUESTION if ask else TERMINAL}"
