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


# --- Responsives Verhalten: Regeln im Stylesheet (Vitest liefert CSS leer, deshalb hier) -----------------------------

CSS = (UI / "src" / "styles" / "app.css").read_text(encoding="utf-8")


def test_css_has_the_three_layout_steps_and_the_two_column_home():
    assert re.search(r'@media \(max-width: 799px\)[\s\S]*?grid-template-areas: "head" "view" "rail"', CSS)       # Leiste unten
    assert re.search(r"@media \(min-width: 1100px\)[\s\S]*?--rail-w: 200px", CSS)                              # Beschriftung neben dem Symbol
    assert re.search(r"@media \(min-width: 1000px\)[\s\S]*?\.home \{ grid-template-columns:", CSS)             # zwei Spalten
    assert re.search(r"@media \(max-width: 599px\)", CSS)                                                       # schmale Telefone


def test_css_cards_and_lists_wrap_by_themselves_and_nothing_has_a_fixed_width():
    assert re.search(r"\.dash \{[^}]*repeat\(auto-fit, minmax\(min\(100%, 340px\), 1fr\)\)", CSS)
    assert re.search(r"\.security \{[^}]*repeat\(auto-fit, minmax\(min\(100%, 360px\), 1fr\)\)", CSS)
    assert re.search(r"\.facts \{[^}]*repeat\(auto-fill, minmax\(min\(100%, 340px\), 1fr\)\)", CSS)
    assert not re.search(r"width: min\(100%, (480|640)px\)", CSS)


def test_css_touch_targets_hidden_elements_and_box_sizing():
    assert re.search(r"button \{[^}]*min-height: var\(--hit\)", CSS)
    assert "[hidden] { display: none !important; }" in CSS
    assert "*, *::before, *::after { box-sizing: border-box; }" in CSS


def test_css_uses_only_tokens_for_colors():
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", CSS)
    for f in (UI / "src").rglob("*.tsx"):
        if ".test." not in f.name:
            assert not re.search(r'["\']#[0-9a-fA-F]{3,8}["\']', f.read_text(encoding="utf-8").replace('|| "#888"', "")), f.name


def test_css_approval_bar_stays_in_view_and_scrolls_inside():
    assert re.search(r"\.approval \{[^}]*position: sticky[^}]*overflow: auto", CSS)


def test_no_emoji_in_the_ui_source():
    emoji = re.compile("[\U0001F300-\U0001FAFF☀-➿⇧]")
    bad = [f.name for f in (UI / "src").rglob("*.tsx") if ".test." not in f.name and emoji.search(f.read_text(encoding="utf-8"))]
    assert not bad, bad
