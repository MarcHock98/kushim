"""Statische Prüfung: kein Netzwerkcode außerhalb der Allowlist (Modus A schützen)."""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "kushim"
FORBIDDEN = {"requests", "httpx", "urllib3", "aiohttp", "socket", "ftplib", "smtplib", "imaplib",
             "http.client", "urllib.request", "anthropic", "openai", "websockets", "paramiko"}
# Zentrale, geprüfte Stellen. Neue Einträge nur mit ausdrücklicher Nutzerfreigabe.
# net/loopback.py: vom Nutzer am 2026-10-03 freigegeben, nur Loopback (127.0.0.1/::1).
# net/web.py: vom Nutzer am 2026-10-04 freigegeben ("erstelle eine Websuche mit net/web.py, keine Downloads erlauben"):
#   nur HTTPS-GET zu fester Domain-Liste, nur Text/JSON, nie auf die Platte (siehe die Tests unten).
ALLOWLIST: set[str] = {"net/loopback.py", "net/web.py"}


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


def test_allowlist_is_exactly_the_two_approved_modules():
    assert ALLOWLIST == {"net/loopback.py", "net/web.py"}


def test_loopback_module_has_no_other_network_imports():
    mods = set(imports(SRC / "net" / "loopback.py"))
    assert mods <= {"__future__", "http.client", "json", "typing", "urllib.parse"}


# --- net/web.py: Grenzen sind gesperrt (Freigabe 2026-10-04, keine Downloads) -------------------------------------

WEB = SRC / "net" / "web.py"


def test_web_module_has_only_the_approved_imports():
    assert set(imports(WEB)) <= {"__future__", "http.client", "ssl", "typing", "urllib.parse"}


def test_web_module_is_pinned_to_the_approved_domain_path_and_content_type():
    import importlib
    web = importlib.import_module("kushim.net.web")
    assert web.ALLOWED_HOSTS == frozenset({"de.wikipedia.org"})
    assert web.ALLOWED_PATHS == frozenset({"/w/api.php"})
    assert web.ALLOWED_CONTENT_TYPES == frozenset({"application/json"})
    assert web.MAX_BYTES <= 1_000_000 and web.TIMEOUT <= 10.0


def test_web_module_can_never_write_files_so_no_downloads_are_possible():
    tree = ast.parse(WEB.read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    forbidden = {"open", "write", "write_text", "write_bytes", "shutil", "tempfile", "urlretrieve", "mkdir", "makedirs",
                 "unlink", "remove", "rename", "replace", "Path", "os", "subprocess", "system", "popen"}
    assert not (names & forbidden), names & forbidden
    assert not {m for m in imports(WEB) if m.split(".")[0] in {"os", "shutil", "pathlib", "tempfile", "subprocess", "io"}}


def test_only_web_search_code_calls_the_web_module():
    users = [f.relative_to(SRC).as_posix() for f in SRC.rglob("*.py")
             if f.name != "web.py" and "net.web" in f.read_text(encoding="utf-8").replace("from .net import web", "net.web")]
    assert set(users) <= {"cli.py"}, users          # Aufrufer nur der CLI-Befehl `kushim search`, nie Tools oder das LLM direkt
