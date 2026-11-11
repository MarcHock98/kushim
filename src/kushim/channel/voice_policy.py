"""Was per Stimme freigegeben werden darf (Roadmap v2 C4, nach dem Safety-Audit 2026-11-11 als Erlaubt-Liste).

Prüft die Rohdaten der Anfrage (`tool_name`, `input_preview`), nie den Ansagetext. Gibt einen Grund zurück, wenn eine
Anfrage NICHT per Stimme erlaubt werden darf; dann bleibt nur der Dialog im Terminal. Eine Sperrliste für Shell-Befehle
ließ sich im Audit leicht umgehen (Schleifen, `python -Bc`, .NET-Aufrufe, Optionen vor `git push`); darum gilt:
- Shell: nur ein einzelner, einfacher Befehl aus einer festen Erlaubt-Liste (Tests, Prüfwerkzeuge, lesendes Git), nur
  einfache Zeichen (keine Anführungszeichen, Pipes, Umleitungen, Variablen, Platzhalter, absoluten Pfade, kein `..`).
- Dateien: nur Lesen, nur im Arbeitsordner von Claude, nie Geheimnisse oder geschützte Ordner. Schreiben und Ändern
  nie per Stimme (der Inhalt wird nicht vorgelesen; eine geschriebene Datei kann später Code ausführen).
- Alles andere (Web, MCP, Agenten, Unbekanntes) nie per Stimme. Ohne bekannten Arbeitsordner gar nichts.
Ein falsches Nein kostet nur einen Blick ins Terminal, ein falsches Ja kann schaden.
"""
from __future__ import annotations

import os
import re
from pathlib import Path, PurePath, PureWindowsPath

from .bridge import Permission
from .speakable import field

SHELLS = {"bash", "powershell"}
READ_TOOLS = {"read": "file_path"}

_SAFE_CHARS = re.compile(r"[A-Za-z0-9 _./=,+:-]+")          # kein @: `pytest @datei` liest Optionen aus einer Datei
_PYTHONS = {"python", "python3", "py", ".venv/scripts/python", ".venv/scripts/python.exe", ".venv/bin/python",
            "venv/scripts/python", "venv/scripts/python.exe", "venv/bin/python"}
_PY_MODULES = {"pytest", "unittest", "mypy", "flake8", "pylint", "compileall"}
_NPM_SCRIPT = re.compile(r"(test|build|lint|typecheck|check)(:[a-z0-9-]+)?")
# Lesendes Git mit einer Erlaubt-Liste der Optionen je Unterbefehl (Audit: Abkürzungen wie --ext-d, Ausgabe in Dateien).
_SUMMARY = {"--stat", "--shortstat", "--numstat", "--name-only", "--name-status", "--no-patch", "-s"}
_GIT_OPTS = {
    "status": {"-s", "--short", "-b", "--branch", "--porcelain"},
    "log": {"--oneline", "--graph", "--decorate", "--all", "--reverse", "--first-parent", "--no-merges"} | _SUMMARY,
    "show": {"--oneline"} | _SUMMARY,
    "diff": {"--cached", "--staged"} | _SUMMARY,
    "rev-parse": {"--abbrev-ref", "--short", "--show-toplevel"},
    "ls-files": {"-m", "--modified", "-o", "--others", "--exclude-standard"},
}
_GIT_PATCH = {"show", "diff"}           # zeigen Dateiinhalte: nur mit Zusammenfassung oder ausdrücklichen Pfaden nach `--`
_GIT_COUNT = re.compile(r"-[0-9]+|-n[0-9]+|--max-count=[0-9]+")
_GIT_BRANCH_FLAGS = {"--list", "-a", "--all", "-v", "-vv", "-r", "--show-current"}
_PYTEST_FLAGS = {"-q", "-qq", "-v", "-vv", "-x", "-s", "-k", "-m", "--lf", "--ff", "--last-failed", "--failed-first",
                 "--tb=short", "--tb=line", "--tb=no", "--tb=long", "--co", "--collect-only", "-rA", "-ra", "--no-header",
                 "--maxfail=1", "--durations=10", "--strict-markers"}
_SECRET = re.compile(r"(^|[\\/._-])(env|ssh|aws|gnupg|id_[a-z0-9]+|pem|key|pfx|p12|kdbx|credentials?|secrets?|tokens?|"
                     r"passw\w*|vault|keyring|netrc|npmrc|pypirc|gitconfig)([\\/._-]|$)", re.I)
PROTECTED_PARTS = {".git", ".claude", ".ssh", ".gnupg", ".aws", ".vscode", ".idea", "run"}


def _is_path_arg(tok: str) -> bool:
    return not tok.startswith("-")


def _plain_path(tok: str) -> bool:
    """Relativer Pfad im Ordner: kein absoluter Pfad, kein `..`, kein Laufwerk, keine Geheimnisse."""
    return (not tok.startswith("/") and ":" not in tok and ".." not in tok.split("/")
            and not _SECRET.search(tok))


def _pytest_args(args: list[str]) -> str | None:
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-k", "-m"):
            if i + 1 >= len(args) or args[i + 1].startswith("-"):
                return "pytest -k/-m ohne Ausdruck"
            i += 2
            continue
        if a.startswith("-"):
            if a not in _PYTEST_FLAGS:
                return f"pytest-Option {a} nur im Terminal"
        elif not _plain_path(a):
            return "Pfad außerhalb des Arbeitsordners"
        i += 1
    return None


def shell_reason(cmd: str) -> str | None:
    """Grund, warum dieser Befehl nicht per Stimme erlaubt wird, oder None (nur Befehle aus der Erlaubt-Liste)."""
    if not cmd or not _SAFE_CHARS.fullmatch(cmd):
        return "nur einfache Befehle ohne Sonderzeichen"
    toks = cmd.split()
    if not toks:
        return "leerer Befehl"
    name, args = toks[0].lower(), toks[1:]
    if name == "pytest":
        return _pytest_args(args)
    if name in _PYTHONS:
        if len(args) >= 2 and args[0] == "-m" and args[1] in _PY_MODULES:
            if args[1] == "pytest":
                return _pytest_args(args[2:])
            return None if all(_is_path_arg(a) and _plain_path(a) or a in ("-q", "-v") for a in args[2:]) \
                else "Option nur im Terminal"
        return "python nur mit -m pytest, unittest oder Prüfwerkzeugen"
    if name == "npm":
        if args in (["test"], ["t"]) or (len(args) == 2 and args[0] in ("run", "run-script") and _NPM_SCRIPT.fullmatch(args[1])):
            return None
        return "npm nur test, build, lint, typecheck und check, ohne Zusätze"
    if name == "git":
        if not args:
            return "git ohne Unterbefehl"
        sub, rest = args[0].lower(), args[1:]
        if sub == "branch":
            return None if all(a in _GIT_BRANCH_FLAGS for a in rest) else "git branch nur zum Anzeigen"
        if sub not in _GIT_OPTS:
            return f"git {sub} nur im Terminal"
        paths, after_sep = [], False
        for a in rest:
            if a == "--" and not after_sep:
                after_sep = True
            elif a.startswith("-") and not after_sep:
                if a not in _GIT_OPTS[sub] and not (sub == "log" and _GIT_COUNT.fullmatch(a)):
                    return f"git-Option {a} nur im Terminal"
            elif a.startswith("-") or not _plain_path(a):           # „master..HEAD“ ist erlaubt, „../x“ nicht
                return "Pfad außerhalb des Arbeitsordners"
            elif after_sep:
                paths.append(a)
        if sub in _GIT_PATCH and not set(rest) & _SUMMARY:
            # Inhalte nur für einzelne Dateien mit Endung („src/app.py“), nie für Ordner wie „.“ oder „src“ (Audit N1)
            if not paths or not all(re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*\.[A-Za-z0-9]+", a.split("/")[-1]) for a in paths):
                return f"git {sub} zeigt Inhalte: nur mit --stat oder einzelnen Dateien"
        return None
    if name in ("ls", "dir", "pwd") and all(_plain_path(a) for a in args if _is_path_arg(a)) \
            and all(a in ("-l", "-la", "-a", "-al", "-lh") for a in args if not _is_path_arg(a)):
        return None
    return f"{name} nur im Terminal"


def _inside(path: Path, folder: Path) -> bool:
    try:
        Path(os.path.normcase(str(path))).relative_to(Path(os.path.normcase(str(folder))))
        return True
    except ValueError:
        return False


def file_reason(raw: str, folder: Path | None) -> str | None:
    """Grund, warum diese Datei nicht per Stimme gelesen werden darf, oder None."""
    if folder is None:
        return "Arbeitsordner unbekannt"
    if not raw.strip() or not raw.isprintable():
        return "kein Pfad"
    if re.search(r"[~%$*?\"<>|]", raw) or ":" in raw[2:] or re.match(r"^[A-Za-z]:(?![\\/])", raw):
        return "ungewöhnlicher Pfad (Stream, Variable oder Laufwerk)"
    if len(raw) >= 2 and raw[0] in "\\/" and raw[1] in "\\/" or PureWindowsPath(raw).drive[:1] in ("\\", "/"):
        return "Netzpfad"                           # \\host, //host, /\host: nie anfassen (kein SMB-Zugriff beim Prüfen)
    if raw.rstrip() != raw or raw.endswith("."):
        return "ungewöhnlicher Pfad"
    p = Path(raw)
    if not p.is_absolute():
        p = folder / p
    lexical, base_lex = Path(os.path.normpath(p)), Path(os.path.normpath(folder))
    if not _inside(lexical, base_lex) or os.path.normcase(str(lexical)) == os.path.normcase(str(base_lex)):
        return "außerhalb des Arbeitsordners"       # rein lexikalisch, ohne Dateisystem oder Netz
    try:
        resolved = lexical.resolve(strict=False)    # erst jetzt (lokal, im Ordner): Verknüpfungen auflösen
        base = folder.resolve(strict=True)
    except (OSError, RuntimeError):
        return "Pfad nicht prüfbar"
    if not _inside(resolved, base) or resolved == base:
        return "außerhalb des Arbeitsordners"
    rel = PurePath(os.path.relpath(resolved, base))
    if {x.lower() for x in rel.parts} & PROTECTED_PARTS:
        return "geschützter Ordner"
    if _SECRET.search(rel.as_posix()) or rel.name.lower() in ("stop", "config.toml", "wakewords.toml", ".mcp.json"):
        return "geschützte Datei"
    return None


def blocked(perm: Permission, folder: Path | None) -> str | None:
    """None nur, wenn die Anfrage per Stimme freigegeben werden darf; sonst der Grund."""
    if folder is None:
        return "Arbeitsordner unbekannt"
    key = perm.tool_name.strip().lower()
    if key in SHELLS:
        cmd = field(perm.input_preview, "command")
        return shell_reason(cmd) if cmd else "kein Befehl"
    if key in READ_TOOLS:
        path = field(perm.input_preview, READ_TOOLS[key])
        return file_reason(path, folder) if path else "kein Pfad"
    return "Werkzeug nur im Terminal"
