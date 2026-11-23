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


RUST_COMMANDS = ["api_info", "set_compact", "set_always_on_top", "grow_for_approval", "attention"]


def test_rust_commands_are_a_fixed_list_and_never_take_focus():
    """E2 (docs/ui-e2e3-plan.md, Abschnitt 3): genau diese Befehle, nur das eigene Fenster, nie Fokus holen, nichts Neues öffnen."""
    rs = (UI / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    handler = re.findall(r"generate_handler!\[([^\]]*)\]", rs)
    assert len(handler) == 1 and [c.strip() for c in handler[0].split(",") if c.strip()] == RUST_COMMANDS, handler
    assert sorted(re.findall(r"#\[tauri::command\]\s*fn (\w+)", rs)) == sorted(RUST_COMMANDS)
    assert not re.search(r"set_focus|unminimize|WebviewWindowBuilder|WindowBuilder|\.show\(\)|set_fullscreen|set_ignore_cursor_events|eval\(", rs)


def test_ui_calls_only_the_known_rust_commands_and_never_focuses_the_window():
    calls = {m for p in SRC for m in re.findall(r"\binvoke(?:<[^>]*>)?\(\s*[\"'](\w+)[\"']", p.read_text(encoding="utf-8"))}
    calls |= {m for p in SRC for m in re.findall(r"\bwindowCommand\(\s*[\"'](\w+)[\"']", p.read_text(encoding="utf-8"))}
    assert calls and calls <= set(RUST_COMMANDS), calls
    wrapper = (UI / "src" / "lib" / "windowCmd.ts").read_text(encoding="utf-8")
    union = re.search(r"export type WindowCommand = ([^;]+);", wrapper)
    assert union and sorted(re.findall(r'"(\w+)"', union.group(1))) == sorted(RUST_COMMANDS[1:]), union
    hits = [p.name for p in SRC if re.search(r"\bwindow\.focus\(|getCurrentWindow|getCurrentWebviewWindow|setFocus", p.read_text(encoding="utf-8"))]
    assert not hits, hits


def test_invoke_only_in_the_window_wrapper_and_the_api_info_loader():
    """Tauri-Aufrufe nur an zwei Stellen: `windowCmd.ts` (Fensterbefehle, nacheinander) und der Loader in `App.tsx` (`api_info`).
    Kein direkter Griff auf `__TAURI_INTERNALS__` (nur die Abfrage, ob es Tauri gibt) und kein globales `__TAURI__`."""
    users = sorted(p.name for p in SRC if re.search(r"\binvoke\b", p.read_text(encoding="utf-8")))
    assert users == ["App.tsx", "windowCmd.ts"], users
    app = (UI / "src" / "App.tsx").read_text(encoding="utf-8")
    assert re.findall(r"\binvoke(?:<[^>]*>)?\(\s*[\"'](\w+)[\"']", app) == ["api_info"]
    assert not re.search(r"\binvoke(?:<[^>]*>)?\(\s*[^\"'\s]", app)                  # in App.tsx nie ein berechneter Befehlsname
    for p in SRC:
        text = p.read_text(encoding="utf-8")
        uses = len(re.findall(r"__TAURI_INTERNALS__", text))
        checks = len(re.findall(r"[\"']__TAURI_INTERNALS__[\"'] in window\b", text))
        assert uses == checks, p.name                                                  # nur „gibt es Tauri?“, nie .invoke o. Ä.
        assert uses == 0 or p.name in {"App.tsx", "windowCmd.ts"}, p.name
        assert "__TAURI__" not in text, p.name


# --- Responsives Verhalten: Regeln im Stylesheet (Vitest liefert CSS leer, deshalb hier) -----------------------------

CSS = (UI / "src" / "styles" / "app.css").read_text(encoding="utf-8")


def test_css_has_the_three_layout_steps_and_the_two_column_show_mode():
    assert re.search(r'@media \(max-width: 799px\)[\s\S]*?grid-template-areas: "head" "view" "rail"', CSS)       # Leiste unten
    assert re.search(r"@media \(min-width: 1100px\)[\s\S]*?--rail-w: 200px", CSS)                              # Beschriftung neben dem Symbol
    assert re.search(r'@media \(min-width: 1000px\)[\s\S]*?\.stage\[data-mode="zeige"\] \{ grid-template-columns:', CSS)  # Zeige-Modus: Kern | Inhalt
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

def test_katex_is_only_used_in_one_place_and_never_trusts_the_formula():
    users = [p.name for p in SRC if "katex" in p.read_text(encoding="utf-8")]
    assert users == ["Tex.tsx"], users                     # Formeln laufen nur über die eine Komponente
    src = (UI / "src" / "components" / "stage" / "Tex.tsx").read_text(encoding="utf-8")
    calls = [l for l in src.splitlines() if "katex.render(" in l]
    assert calls and all("trust: false" in l for l in calls), calls
    assert "trust: true" not in src and "renderToString" not in src   # kein HTML-Text, keine Links aus Formeln


def test_no_code_from_strings_no_workers_no_webassembly():
    """P5 (docs/ui-p5-plan.md, Abschnitte 2 und 9): Claude schickt nur Modellnamen und Zahlen, nie Code. Darum gibt es in der
    Oberfläche keinen Weg, Text auszuführen, keinen Worker und kein WebAssembly."""
    bad = re.compile(r"\beval\s*\(|\bnew\s+Function\b|\bFunction\s*\(|\bWebAssembly\b|\bnew\s+(?:Shared)?Worker\b|\bimportScripts\b")
    hits = [f"{p.name}: {m.group(0)}" for p in SRC for m in bad.finditer(p.read_text(encoding="utf-8"))]
    assert not hits, hits


def test_no_worker_import_through_a_bundler_suffix():
    """Auch über das Bündelwerkzeug darf kein Worker entstehen: kein `?worker`, `?sharedworker` oder `?worker&inline` im Import."""
    suffix = re.compile(r"[\"'`][^\"'`\n]*\?[\w&=-]*\b(?:shared)?worker\b", re.IGNORECASE)
    for sample in ('import W from "./w.ts?worker"', "import W from './w.ts?sharedworker'", 'import W from "./w.ts?worker&inline"', 'import W from "./w.ts?url&worker"'):
        assert suffix.search(sample), sample                      # die Regel selbst erkennt die Formen
    for sample in ('const a = x?.worker', 'const a = "worker"', 'import W from "./worker.ts"'):
        assert not suffix.search(sample), sample
    hits = [f"{p.name}: {m.group(0)}" for p in SRC for m in suffix.finditer(p.read_text(encoding="utf-8"))]
    assert not hits, hits


def test_shader_material_only_in_the_core():
    users = sorted(p.name for p in SRC if "ShaderMaterial" in p.read_text(encoding="utf-8"))
    assert users == ["Core3D.tsx"], users                 # keine Shader aus Ansichten, nur der feste Kern


def test_physics_has_no_unseeded_randomness():
    src = (UI / "src" / "lib" / "physics.ts").read_text(encoding="utf-8")
    assert "Math.random" not in src                       # Zufall nur mit Startwert (gleiche Eingabe, gleiche Simulation)
    chem = UI / "src" / "lib" / "chem.ts"                 # P5b, sobald es die Datei gibt
    assert not chem.exists() or "Math.random" not in chem.read_text(encoding="utf-8")


def test_csp_never_allows_eval_wasm_blob_or_workers():
    conf = json.loads((UI / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    html = (UI / "index.html").read_text(encoding="utf-8")
    meta = re.search(r'http-equiv="Content-Security-Policy"\s+content="([^"]*)"', html)
    assert meta, "CSP-Meta fehlt in index.html"
    for csp in (conf["app"]["security"]["csp"], meta.group(1)):
        for word in ("unsafe-eval", "wasm-unsafe-eval", "blob:", "worker-src"):
            assert word not in csp, (word, csp)


def test_the_view_card_does_not_share_a_class_with_the_main_area():
    card = (UI / "src" / "components" / "stage" / "ViewCard.tsx").read_text(encoding="utf-8")
    assert "className={`view-card view-${view.art}`}" in card and "className={`view " not in card
    assert ".view-card {" in CSS and CSS.count(chr(10) + ".view {") == 1     # .view gehört nur dem Hauptbereich (Scrollen)
