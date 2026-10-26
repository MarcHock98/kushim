"""Statische Prüfung: kein Netzwerkcode außerhalb der Allowlist (Modus A schützen)."""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "kushim"
FORBIDDEN = {"requests", "httpx", "urllib3", "aiohttp", "socket", "ftplib", "smtplib", "imaplib",
             "http.client", "urllib.request", "anthropic", "openai", "websockets", "paramiko"}
# Zentrale, geprüfte Stellen. Neue Einträge nur mit ausdrücklicher Nutzerfreigabe.
# net/loopback.py: vom Nutzer am 2026-10-03 freigegeben, nur Loopback (127.0.0.1/::1).
# net/web.py (Websuche, Freigabe 2026-10-04) ist mit Roadmap v2 A2 am 2026-10-26 entfernt: kushim selbst geht nie ins Internet.
# net/server.py: vom Nutzer am 2026-10-04 freigegeben ("Transport freigeben"): WebSocket-Server nur auf 127.0.0.1,
#   nur Standardbibliothek (asyncio), siehe die Tests unten.
ALLOWLIST: set[str] = {"net/loopback.py", "net/server.py"}


def imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_no_network_imports_outside_allowlist():
    bad = []
    for f in SRC.rglob("*.py"):
        rel = f.relative_to(SRC).as_posix()
        if rel in ALLOWLIST:
            continue
        for mod in imports(f):
            if mod in FORBIDDEN or mod.split(".")[0] in FORBIDDEN:
                bad.append(f"{rel}: {mod}")
    assert not bad, "Netzwerk-Importe außerhalb der Allowlist:\n" + "\n".join(bad)


def test_allowlist_is_exactly_the_approved_modules():
    assert ALLOWLIST == {"net/loopback.py", "net/server.py"}


def test_loopback_module_has_no_other_network_imports():
    mods = set(imports(SRC / "net" / "loopback.py"))
    assert mods <= {"__future__", "http.client", "json", "typing", "urllib.parse"}


# --- Kein Internet-Modul mehr (Roadmap v2 A2, 2026-10-26) --------------------------------------------------------

def test_there_is_no_internet_module_and_nobody_imports_one():
    assert not (SRC / "net" / "web.py").exists() and not (SRC / "web").exists()
    users = [f.relative_to(SRC).as_posix() for f in SRC.rglob("*.py")
             if "net.web" in f.read_text(encoding="utf-8").replace("from .net import web", "net.web")
             or "import ssl" in f.read_text(encoding="utf-8")]
    assert users == [], users


# --- Claude CLI: nur an einer Stelle gefunden und gestartet, Rechteumgehung nie im Aufruf ---------------------------

def test_claude_executable_is_only_located_in_one_module():
    users = [f.relative_to(SRC).as_posix() for f in SRC.rglob("*.py")
             if 'which("claude")' in f.read_text(encoding="utf-8") or "which('claude')" in f.read_text(encoding="utf-8")]
    assert users == ["claude_cli/base.py"], users


def test_permission_bypass_flags_appear_only_inside_the_forbidden_flags_lists():
    bad = ("--dangerously-skip-permissions", "bypassPermissions")
    for f in SRC.rglob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        allowed = set()
        for node in ast.walk(tree):                      # Zeichenketten innerhalb von `FORBIDDEN_FLAGS = (...)` sind die Verbotsliste
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "FORBIDDEN_FLAGS" for t in node.targets):
                allowed |= {id(n) for n in ast.walk(node.value)}
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) and node.body:
                first = node.body[0]                     # Erklärtexte (Docstrings) sind kein Code
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    allowed.add(id(first.value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and any(b in node.value for b in bad):
                assert id(node) in allowed, f"{f.relative_to(SRC).as_posix()}: Rechteumgehung außerhalb der Verbotsliste: {node.value[:60]}"


def test_no_code_starts_claude_runs_on_its_own():
    """Die alte Steuerung (`ClaudeSessions.start/answer`, Roadmap v2 A4) ist entfernt: kushim startet keine Claude-Läufe selbst."""
    assert not (SRC / "claude_cli" / "session.py").exists() and not (SRC / "claude_cli" / "control.py").exists()
    callers = {}
    for f in SRC.rglob("*.py"):
        rel = f.relative_to(SRC).as_posix()
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("start", "answer"):
                owner = node.func.value
                name = owner.attr if isinstance(owner, ast.Attribute) else getattr(owner, "id", "")
                if name == "sessions":
                    callers.setdefault(rel, set()).add(node.func.attr)
    assert callers == {}, callers


# --- net/server.py: nur Loopback, nur Standardbibliothek (Freigabe 2026-10-04) ---------------------------------------

SERVER = SRC / "net" / "server.py"


def test_server_module_has_only_stdlib_imports_and_no_network_packages():
    mods = set(imports(SERVER))
    assert mods <= {"__future__", "asyncio", "base64", "hashlib", "json", "struct", "threading", "typing",
                    "..api.protocol", "api.protocol"} | {m for m in mods if m.startswith("..")}, mods
    assert not {m for m in mods if m.split(".")[0] in FORBIDDEN}


def test_server_binds_only_to_the_fixed_loopback_address():
    import importlib
    srv = importlib.import_module("kushim.net.server")
    assert srv.BIND_HOST == "127.0.0.1"
    import inspect
    assert "host" not in inspect.signature(srv.LocalServer.__init__).parameters
    src = SERVER.read_text(encoding="utf-8")
    assert "0.0.0.0" not in src and '"::"' not in src and src.count("start_server(") == 1
    assert "BIND_HOST" in src.split("start_server(")[1].split(")")[0]


def test_only_cli_or_launcher_start_the_server():
    users = [f.relative_to(SRC).as_posix() for f in SRC.rglob("*.py")
             if f.name != "server.py" and "LocalServer" in f.read_text(encoding="utf-8")]
    assert set(users) <= {"cli.py", "launcher.py"}, users
