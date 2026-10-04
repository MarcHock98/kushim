"""Statische Regeln für die Oberfläche (ui/): kein Netz außer ws://127.0.0.1, keine Rechte, keine Geheimnisse im Speicher."""
import json
import re
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "ui"
SRC = [p for p in (UI / "src").rglob("*") if p.suffix in {".ts", ".tsx"} and ".test." not in p.name]


def test_no_network_apis_except_the_local_websocket_client():
    bad = re.compile(r"\b(fetch|XMLHttpRequest|EventSource|sendBeacon|innerHTML|dangerouslySetInnerHTML|localStorage|sessionStorage|indexedDB)\b")
    hits = [f"{p.name}: {m.group(0)}" for p in SRC for m in bad.finditer(p.read_text(encoding="utf-8"))]
    assert not hits, hits


def test_only_loopback_websocket_urls_in_source():
    urls = {u for p in SRC for u in re.findall(r"(?:wss?|https?)://[^\s\"'`)]+", p.read_text(encoding="utf-8"))}
    assert all(u.startswith("ws://127.0.0.1") for u in urls), urls


def test_csp_allows_only_self_and_loopback_websocket():
    conf = json.loads((UI / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    csp = conf["app"]["security"]["csp"]
    assert "default-src 'self'" in csp and "connect-src ws://127.0.0.1:*" in csp
    assert "http://" not in csp.replace("http://ipc.localhost", "") and "https:" not in csp and "*" not in csp.replace(":*", "")
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert "default-src 'self'" in html and not re.search(r"(src|href)=[\"']https?://", html)


def test_tauri_capabilities_are_minimal():
    cap = json.loads((UI / "src-tauri" / "capabilities" / "default.json").read_text(encoding="utf-8"))
    assert cap["permissions"] == ["core:default"]


def test_rust_part_has_no_network_or_process_code():
    rs = (UI / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    assert not re.search(r"std::net|std::process|Command::new|reqwest|hyper|tokio::net|fs::write|remove_file", rs)
    toml = (UI / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    assert not re.search(r"reqwest|hyper|tauri-plugin", toml)
