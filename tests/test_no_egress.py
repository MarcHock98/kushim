"""Statische Prüfung: kein Netzwerkcode außerhalb der Allowlist (Modus A schützen)."""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "kushim"
FORBIDDEN = {"requests", "httpx", "urllib3", "aiohttp", "socket", "ftplib", "smtplib", "imaplib",
             "http.client", "urllib.request", "anthropic", "openai", "websockets", "paramiko"}
# Zentrale, geprüfte Stellen. Neue Einträge nur mit ausdrücklicher Nutzerfreigabe.
# net/loopback.py: vom Nutzer am 2026-10-03 freigegeben, nur Loopback (127.0.0.1/::1).
ALLOWLIST: set[str] = {"net/loopback.py"}


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


def test_allowlist_is_only_the_loopback_module():
    assert ALLOWLIST == {"net/loopback.py"}


def test_loopback_module_has_no_other_network_imports():
    mods = set(imports(SRC / "net" / "loopback.py"))
    assert mods <= {"__future__", "http.client", "json", "typing", "urllib.parse"}
