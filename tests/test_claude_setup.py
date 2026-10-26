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
