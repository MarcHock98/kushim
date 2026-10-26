import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("claude_setup", ROOT / "scripts" / "claude_setup.py")
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)


def test_merge_settings_keeps_foreign_keys_and_adds_env():
    out = cs.merge_settings({"model": "sonnet", "env": {"X": "1"}, "hooks": {"Stop": []}})
    assert out["model"] == "sonnet" and out["hooks"] == {"Stop": []}
    assert out["env"]["X"] == "1"
    assert out["env"]["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"


def test_merge_rules_appends_once_and_replaces_own_block():
    first = cs.merge_rules("# Meins\nbleibt\n")
    assert first.startswith("# Meins\nbleibt\n") and first.count(cs.BEGIN) == 1
    again = cs.merge_rules(first)
    assert again == first
    old = "a\n" + cs.BEGIN + "\nVERALTET\n" + cs.END + "\nb\n"
    new = cs.merge_rules(old)
    assert "VERALTET" not in new and new.startswith("a\n") and new.endswith("\nb\n")


def test_gitignore_entry_added_once():
    assert cs.ensure_gitignore("") == "graphify-out/\n"
    assert cs.ensure_gitignore(".venv/") == ".venv/\ngraphify-out/\n"
    assert cs.ensure_gitignore("graphify-out/\n") == "graphify-out/\n"


def test_setup_global_writes_backup_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    cs.setup_global(dry=False)
    data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert data["theme"] == "dark" and data["env"]["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert list(tmp_path.glob("settings.json.bak-*"))
    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    cs.setup_global(dry=False)
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == text


def test_dry_run_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    cs.setup_global(dry=True)
    assert list(tmp_path.iterdir()) == []


def test_graphify_never_gets_foreign_api_keys(monkeypatch):
    seen = {}
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "y")
    monkeypatch.setattr(cs.subprocess, "run", lambda cmd, **kw: seen.update(kw["env"]))
    cs.run(["graphify", "update", "."], dry=False)
    assert "GEMINI_API_KEY" not in seen and "OPENAI_API_KEY" not in seen
    assert seen["GRAPHIFY_QUERY_LOG_DISABLE"] == "1"


def test_pinned_version():
    assert cs.GRAPHIFY_PACKAGE == "graphifyy" and cs.GRAPHIFY_VERSION.count(".") == 2


# --- Statuszeile (Z4) ----------------------------------------------------------------------------

sl_spec = importlib.util.spec_from_file_location("statusline", ROOT / "scripts" / "statusline.py")
sl = importlib.util.module_from_spec(sl_spec)
sl_spec.loader.exec_module(sl)

FULL = {"model": {"id": "claude-opus-5-5", "display_name": "Opus 5.5"},
        "context_window": {"used_percentage": 41.6, "remaining_percentage": 58.4},
        "rate_limits": {"five_hour": {"used_percentage": 30, "resets_at": 1}, "seven_day": {"used_percentage": 12.2, "resets_at": 2}}}


def test_statusline_shows_model_context_and_limits():
    assert sl.render(FULL) == "Opus 5.5 · Kontext 42% · 5h 30% · 7d 12%"


def test_statusline_shows_cost_only_when_claude_code_sends_it():
    assert "USD" not in sl.render(FULL)
    assert sl.render({**FULL, "cost": {"total_cost_usd": 0.354}}).endswith("· 0.35 USD")


def test_statusline_is_defensive_against_missing_and_odd_input():
    assert sl.render({}) == "Claude Code"
    assert sl.render(None) == "Claude Code" and sl.render([1, 2]) == "Claude Code"
    odd = {"model": {"display_name": "Op\x1b[31mus"}, "context_window": {"used_percentage": None},
           "rate_limits": {"five_hour": {"used_percentage": True}, "seven_day": "x"}, "cost": {"total_cost_usd": "1"}}
    assert sl.render(odd) == "Op[31mus"                      # kein Steuerzeichen, keine falschen Zahlen
    assert sl.render({"model": {"id": "claude-x"}}) == "claude-x"


def test_statusline_main_reads_stdin_and_never_crashes(monkeypatch, capsys):
    import io
    import sys
    for raw in (json.dumps(FULL).encode(), b"kein json", b""):
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw)))
        assert sl.main() == 0
    out = capsys.readouterr().out.splitlines()
    assert out == ["Opus 5.5 · Kontext 42% · 5h 30% · 7d 12%", "Claude Code", "Claude Code"]


def test_statusline_writes_utf8_bytes_even_where_the_console_is_not_utf8():
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "statusline.py")], input=json.dumps(FULL).encode(),
                       capture_output=True, env={"PYTHONIOENCODING": "cp1252", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")})
    assert r.returncode == 0 and r.stdout.decode("utf-8").strip() == "Opus 5.5 · Kontext 42% · 5h 30% · 7d 12%"


def test_statusline_script_has_no_network_or_file_writes():
    src = (ROOT / "scripts" / "statusline.py").read_text(encoding="utf-8")
    for bad in ("socket", "urllib", "http", "requests", "open(", "write_text", "subprocess"):
        assert bad not in src, bad


def test_merge_statusline_adds_own_and_replaces_only_its_own():
    cmd = cs.statusline_command("C:/py/python.exe", Path("C:/k/scripts/statusline.py"))
    assert cmd == f'"C:/py/python.exe" -I "{Path("C:/k/scripts/statusline.py")}"'
    out, _ = cs.merge_statusline({"model": "sonnet"}, cmd)
    assert out["statusLine"] == {"type": "command", "command": cmd} and out["model"] == "sonnet"
    older = {"statusLine": {"type": "command", "command": '"old" "D:/alt/statusline.py"'}}
    assert cs.merge_statusline(older, cmd)[0]["statusLine"]["command"] == cmd


def test_merge_statusline_never_touches_a_foreign_statusline():
    foreign = {"statusLine": {"type": "command", "command": "~/.claude/meine-zeile.sh"}}
    out, note = cs.merge_statusline(foreign, "x")
    assert out == foreign and "bleibt unverändert" in note


def test_setup_global_writes_statusline_only_when_asked(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    cs.setup_global(dry=False)
    assert "statusLine" not in json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    cs.setup_global(dry=False, statusline=True)
    data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert "statusline.py" in data["statusLine"]["command"] and data["env"]["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
