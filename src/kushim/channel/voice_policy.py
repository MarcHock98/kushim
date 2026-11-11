"""Sperrliste für Freigaben per Stimme (Roadmap v2 C4).

Prüft die Rohdaten der Anfrage (`tool_name`, `input_preview`), nie den Ansagetext. Gibt einen Grund zurück, wenn eine
Anfrage NICHT per Stimme erlaubt werden darf; dann bleibt nur der Dialog im Terminal. Im Zweifel gesperrt:
- nur Shell-Befehle und Datei-Werkzeuge, alles andere (Web, MCP, Agenten, Unbekanntes) nie per Stimme;
- Shell: Löschen, Überschreiben, Push und andere Git-Befehle, die Arbeit vernichten, alles mit Netz oder Installation,
  Einstellungen, System, Prozesse beenden, versteckte Ausführung (`-c`, `eval`, `$(…)`), Pfade außerhalb des Ordners
  (`..`, `~`, Laufwerke), Geheimnisse (`.env`, `.ssh`, Tokens);
- Dateien: nur innerhalb des Arbeitsordners von Claude, nie in `.git`, `.claude`, Einstellungs- oder Schlüsseldateien
  und nie an kushims eigenen Sicherheitsregeln.
Die Liste ist bewusst grob: Ein falscher Treffer kostet nur einen Blick ins Terminal, ein fehlender kann schaden.
"""
from __future__ import annotations

import os
import re
from pathlib import Path, PurePath

from .bridge import Permission
from .speakable import field

SHELLS = {"bash", "powershell"}
FILE_TOOLS = {"edit": "file_path", "multiedit": "file_path", "write": "file_path", "read": "file_path",
              "notebookedit": "notebook_path"}

# Befehlsnamen (klein, ohne Pfad und Endung), die nie per Stimme freigegeben werden.
BLOCKED_COMMANDS = {
    # Löschen, Verschieben, Überschreiben
    "rm", "rmdir", "del", "erase", "rd", "remove-item", "ri", "shred", "unlink", "truncate", "mv", "move", "move-item",
    "mi", "ren", "rename", "rename-item", "rni", "clear-content", "clc", "set-content", "sc", "out-file", "tee",
    "tee-object", "dd", "format", "diskpart", "mkfs", "fsutil", "cipher", "robocopy", "xcopy", "cp", "copy", "copy-item",
    "cpi", "ln", "install", "add-content", "ac", "tar", "unzip", "7z", "expand-archive", "compress-archive",
    # Netz, Daten senden, Herunterladen, Installieren
    "curl", "wget", "invoke-webrequest", "iwr", "invoke-restmethod", "irm", "start-bitstransfer", "bitsadmin", "certutil",
    "scp", "sftp", "ssh", "rsync", "ftp", "tftp", "nc", "ncat", "netcat", "telnet", "socat", "gh", "hub", "az", "aws", "gcloud",
    "kubectl", "docker", "podman", "send-mailmessage", "mail", "sendmail", "pip", "pip3", "pipx", "uv", "poetry", "conda",
    "npx", "bunx", "pnpm", "yarn", "bun", "winget", "choco", "scoop", "apt", "apt-get", "brew", "cargo", "go", "gem",
    "install-module", "install-package", "twine",
    # Einstellungen, Rechte, System
    "setx", "reg", "regedit", "set-itemproperty", "sp", "new-itemproperty", "remove-itemproperty", "chmod", "chown",
    "icacls", "takeown", "attrib", "set-executionpolicy", "netsh", "schtasks", "bcdedit", "sc.exe", "set-service",
    "new-service", "set-acl", "shutdown", "restart-computer", "stop-computer", "logoff", "taskkill", "kill", "pkill",
    "killall", "stop-process", "spps", "sudo", "runas", "su", "start-process", "saps", "start", "env", "printenv", "set",
    "export", "claude", "kushim", "mklink", "new-item", "ni", "crontab",
    # versteckte Ausführung
    "eval", "exec", "iex", "invoke-expression", "invoke-command", "icm", "xargs", "source", ".", "bash", "sh", "zsh",
    "cmd", "powershell", "pwsh", "wsl", "nohup", "sudoedit",
}
# Programme, bei denen erst ein Argument gefährlich macht.
INLINE_CODE = {"python": {"-c"}, "python3": {"-c"}, "py": {"-c"}, "node": {"-e", "--eval", "-p", "--print"},
               "perl": {"-e", "-E", "-i", "-pi"}, "ruby": {"-e"}, "deno": {"eval"}, "sed": {"-i", "--in-place"}}
PYTHON_MODULES_ALLOWED = {"pytest", "unittest", "mypy", "ruff", "flake8", "pylint", "pyflakes", "compileall", "py_compile",
                          "black", "isort"}
GIT_BLOCKED = {"push", "clean", "rm", "mv", "reset", "restore", "checkout", "switch", "rebase", "filter-branch",
               "filter-repo", "update-ref", "reflog", "gc", "prune", "config", "remote", "fetch", "pull", "clone",
               "submodule", "worktree", "send-email", "request-pull", "am", "apply", "cherry-pick", "revert", "merge",
               "tag", "notes", "replace", "credential", "lfs", "archive", "bundle", "daemon", "http-backend"}
GIT_FLAGS_BLOCKED = {"branch": {"-d", "-D", "--delete", "-m", "-M", "--move", "-f", "--force"},
                     "stash": {"drop", "clear", "pop"},
                     "commit": {"--amend", "--no-verify", "-n"}}
NPM_ALLOWED = {"test", "t", "ls", "list", "outdated", "--version", "-v"}
NPM_SCRIPTS = re.compile(r"(test|build|lint|typecheck|check|dev)(:[\w:-]+)?")

_SEGMENT = re.compile(r"&&|\|\||[;|&\n]")
_SECRET = re.compile(r"(^|[\\/\s\"'=])(\.env\b|\.ssh\b|\.aws\b|\.gnupg\b|id_rsa|id_ed25519|\.pem\b|\.key\b|credentials|"
                     r"secret|token|passw|vault|keyring|\.netrc|\.npmrc|\.pypirc)", re.I)
_OUTSIDE = re.compile(r"(^|[\s\"'=])(\.\.([\\/]|\s|$)|~|[a-zA-Z]:|/|\\|\$env:|\$home\b|%[a-z_]+%|\$\{?HOME)", re.I)
_SAFE_REDIRECT = re.compile(r"(?<!\S)(2>&1|[12]?>\s*/dev/null|[12]?>\s*nul|[12]?>\s*\$null)(?!\S)", re.I)

PROTECTED_PARTS = {".git", ".claude", ".ssh", ".gnupg", ".aws", ".vscode", ".idea", "node_modules", "run"}
PROTECTED_NAMES = re.compile(r"^(\.env.*|\.mcp\.json|config\.toml|wakewords\.toml|settings(\.local)?\.json|"
                             r".*\.(pem|key|pfx|p12|kdbx)|id_[a-z0-9]+|\.netrc|\.npmrc|\.pypirc|\.gitconfig|"
                             r"test_no_egress\.py|STOP)$", re.I)
PROTECTED_DIRS = (("src", "kushim", "safety"),)        # kushims eigene Sicherheitsregeln


def _name(token: str) -> str:
    base = re.split(r"[\\/]", token)[-1].lower()
    return re.sub(r"\.(exe|cmd|bat|ps1|com)$", "", base)


def _tokens(segment: str) -> list[str]:
    toks = [t.strip("\"'") for t in segment.split()]
    while toks and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", toks[0]):       # FOO=bar befehl
        toks.pop(0)
    return [t for t in toks if t]


def shell_reason(cmd: str) -> str | None:
    """Grund, warum dieser Befehl nicht per Stimme erlaubt wird, oder None."""
    if not cmd.strip() or not cmd.replace("\n", " ").isprintable():
        return "leerer oder unlesbarer Befehl"
    if "`" in cmd or "$(" in cmd or "<(" in cmd or ">(" in cmd or "${" in cmd:
        return "versteckte Ausführung"
    if _SECRET.search(cmd):
        return "Geheimnisse"
    cmd = _SAFE_REDIRECT.sub(" ", cmd)              # 2>&1, > /dev/null, > nul: harmlos, und `&` soll nicht trennen
    if ">" in cmd:
        return "schreibt in eine Datei"
    if _OUTSIDE.search(cmd):
        return "Pfad außerhalb des Arbeitsordners"
    for segment in _SEGMENT.split(cmd):
        toks = _tokens(segment)
        if not toks:
            continue
        name, args = _name(toks[0]), toks[1:]
        lower = [a.lower() for a in args]
        if name in BLOCKED_COMMANDS:
            return f"gesperrter Befehl {name}"
        if name in INLINE_CODE and any(a in INLINE_CODE[name] or a.startswith(("-i", "--in-place")) and name in ("sed", "perl")
                                       for a in args):
            return "versteckte Ausführung oder Ändern an Ort und Stelle"
        if name in ("python", "python3", "py") and "-m" in args:
            i = args.index("-m")
            if i + 1 >= len(args) or args[i + 1].lower() not in PYTHON_MODULES_ALLOWED:
                return "python -m nur für Test- und Prüfwerkzeuge"
        if name == "npm":
            ok = bool(args) and (lower[0] in NPM_ALLOWED or
                                 lower[0] in ("run", "run-script") and len(args) > 1 and NPM_SCRIPTS.fullmatch(lower[1]))
            if not ok:
                return "npm nur für test, build, lint und check"
        if name == "git":
            sub = next((a for a in lower if not a.startswith("-")), "")
            if any(a.startswith("-c") or a.startswith("--git-dir") or a.startswith("--work-tree") or a == "-C" for a in args[:2]):
                return "git mit geänderten Einstellungen"
            if sub in GIT_BLOCKED:
                return f"git {sub}"
            if set(lower) & GIT_FLAGS_BLOCKED.get(sub, set()) or (sub == "stash" and len(lower) > 1 and lower[1] not in ("list", "show", "push")):
                return f"git {sub} mit gefährlicher Option"
            if "--force" in lower or "-f" in lower:
                return "git mit --force"
    return None


def _inside(path: Path, folder: Path) -> bool:
    try:
        Path(os.path.normcase(str(path))).relative_to(Path(os.path.normcase(str(folder))))
        return True
    except ValueError:
        return False


def file_reason(raw: str, folder: Path | None) -> str | None:
    """Grund, warum diese Datei nicht per Stimme freigegeben wird, oder None."""
    if folder is None:
        return "Arbeitsordner unbekannt"
    if not raw.strip() or "\x00" in raw:
        return "kein Pfad"
    p = Path(raw)
    if not p.is_absolute():
        p = folder / p
    try:
        resolved = p.resolve(strict=False)          # löst .. und Verknüpfungen auf (soweit vorhanden)
        base = folder.resolve(strict=True)
    except (OSError, RuntimeError):
        return "Pfad nicht prüfbar"
    if not _inside(resolved, base) or resolved == base:
        return "außerhalb des Arbeitsordners"
    rel = PurePath(os.path.relpath(resolved, base))
    parts = [x.lower() for x in rel.parts]
    if set(parts[:-1]) & PROTECTED_PARTS or parts[0] in PROTECTED_PARTS:
        return "geschützter Ordner"
    if PROTECTED_NAMES.match(rel.name):
        return "geschützte Datei"
    for prot in PROTECTED_DIRS:
        if tuple(parts[:len(prot)]) == prot:
            return "kushims Sicherheitsregeln"
    return None


def blocked(perm: Permission, folder: Path | None) -> str | None:
    """None nur, wenn die Anfrage per Stimme freigegeben werden darf; sonst der Grund."""
    key = perm.tool_name.strip().lower()
    if key in SHELLS:
        cmd = field(perm.input_preview, "command")
        return shell_reason(cmd) if cmd else "kein Befehl"
    if key in FILE_TOOLS:
        path = field(perm.input_preview, FILE_TOOLS[key])
        return file_reason(path, folder) if path else "kein Pfad"
    return "Werkzeug nur im Terminal"
