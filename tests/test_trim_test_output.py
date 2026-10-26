"""Hook, der lange Testausgaben kürzt (scripts/trim_test_output.py, Roadmap Z5)."""
import importlib.util
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("trim_test_output", ROOT / "scripts" / "trim_test_output.py")
tt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tt)
cs_spec = importlib.util.spec_from_file_location("claude_setup", ROOT / "scripts" / "claude_setup.py")
cs = importlib.util.module_from_spec(cs_spec)
cs_spec.loader.exec_module(cs)


@pytest.mark.parametrize("cmd", ["pytest -q", ".venv/Scripts/python -m pytest -q tests/test_x.py", "python3 -m pytest",
                                 "npm test", "npm run test", "npx vitest run", "cargo test", "pytest"])
def test_simple_test_runs_are_recognised(cmd):
    assert tt.is_simple_test_run(cmd)


@pytest.mark.parametrize("cmd", ["pytest -q | tail -5", "pytest > out.txt", "pytest && rm -rf x", "pytest; ls", "pytest `x`",
                                 "pytest $(cat f)", "echo pytest", "git status", "npm install", "pytest\nrm x", "pytest & x"])
def test_everything_else_is_left_alone(cmd):
    assert not tt.is_simple_test_run(cmd)


def event(cmd, tool="Bash"):
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"command": cmd, "description": "Tests"}}


def test_hook_rewrites_only_the_command_and_never_grants_permission():
    r = tt.hook_reply(event("pytest -q"), python="C:/py/python.exe", script=Path("C:/k/scripts/trim_test_output.py"))
    out = r["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse" and "permissionDecision" not in out and set(r) == {"hookSpecificOutput"}
    assert out["updatedInput"]["description"] == "Tests"
    assert out["updatedInput"]["command"] == ('set -o pipefail; pytest -q 2>&1 | "C:/py/python.exe" -I '
                                              '"C:/k/scripts/trim_test_output.py" --filter')


def test_hook_ignores_other_tools_other_commands_and_junk():
    for e in (event("git status"), event("pytest", tool="Read"), {"tool_name": "Bash"}, {"tool_name": "Bash", "tool_input": "x"},
              None, [], {"tool_name": "Bash", "tool_input": {"command": 5}}):
        assert tt.hook_reply(e) is None


def test_short_output_stays_whole_and_long_output_keeps_errors_and_the_end():
    short = [f"z{i}" for i in range(tt.KEEP_ALL)]
    assert tt.trim(short) == short
    long = [f"tests/test_a.py::test_{i} PASSED" if i % 50 else f"zeile {i}" for i in range(500)]
    long[100] = "FAILED tests/test_b.py::test_x - AssertionError"
    long[101] = "E   assert 1 == 2"
    long[-1] = "1 failed, 499 passed in 3.2s"
    out = tt.trim(long)
    assert out[0].startswith("[gekürzt: 500 Zeilen") and len(out) <= 1 + tt.MAX_HITS + 1 + tt.TAIL
    assert "FAILED tests/test_b.py::test_x - AssertionError" in out and "E   assert 1 == 2" in out
    assert out[-1] == "1 failed, 499 passed in 3.2s"


def test_main_as_hook_and_as_filter(monkeypatch, capsys):
    def run(raw, argv):
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw)))
        return tt.main(argv)
    assert run(json.dumps(event("pytest -q")).encode(), []) == 0
    assert "--filter" in json.loads(capsys.readouterr().out)["hookSpecificOutput"]["updatedInput"]["command"]
    assert run(json.dumps(event("ls")).encode(), []) == 0 and capsys.readouterr().out == ""
    assert run(b"kein json", []) == 0 and capsys.readouterr().out == ""
    assert run("ä\nö\n".encode(), ["--filter"]) == 0 and capsys.readouterr().out == "ä\nö\n"


def git_bash():
    """Die Shell, die Claude Code unter Windows nutzt (Git Bash); nie die WSL-bash aus System32 (kennt keine C:/-Pfade)."""
    git = shutil.which("git")
    if sys.platform == "win32":
        for up in (Path(git).resolve().parents if git else []):          # git.exe liegt in cmd/ oder mingw64/bin/
            if (up / "bin" / "bash.exe").exists():
                return str(up / "bin" / "bash.exe")
        return None
    return shutil.which("bash")


@pytest.mark.skipif(git_bash() is None, reason="Git Bash fehlt")
def test_wrapped_command_keeps_the_exit_code_and_trims_in_a_real_shell():
    py = Path(sys.executable).as_posix()
    noisy = f'"{py}" -c "import sys; [print(i) for i in range(300)]; print(\'FAILED x\'); sys.exit(3)"'
    r = subprocess.run([git_bash(), "-c", tt.wrap(noisy, python=sys.executable)], capture_output=True)
    lines = r.stdout.decode("utf-8").splitlines()
    assert r.returncode == 3                               # pipefail: der Testlauf bestimmt den Exit-Code, nicht der Filter
    assert lines[0].startswith("[gekürzt: 301 Zeilen") and lines[-1] == "FAILED x" and len(lines) < 40


def test_script_has_no_network_or_file_writes():
    src = (ROOT / "scripts" / "trim_test_output.py").read_text(encoding="utf-8")
    for bad in ("socket", "urllib", "http", "requests", "open(", "write_text", "subprocess"):
        assert bad not in src, bad


def test_setup_adds_the_hook_once_and_keeps_foreign_hooks():
    foreign = {"matcher": "Write", "hooks": [{"type": "command", "command": "prettier"}]}
    data = {"hooks": {"PreToolUse": [foreign], "Stop": [{"hooks": []}]}, "model": "sonnet"}
    once = cs.merge_test_hook(data, '"py" -I "C:/k/scripts/trim_test_output.py"')
    twice = cs.merge_test_hook(once, '"py2" -I "C:/k/scripts/trim_test_output.py"')
    pre = twice["hooks"]["PreToolUse"]
    assert pre[0] == foreign and len(pre) == 2 and pre[1]["matcher"] == "Bash"
    assert pre[1]["hooks"][0]["command"].startswith('"py2"') and twice["hooks"]["Stop"] == [{"hooks": []}]
    assert twice["model"] == "sonnet" and data["hooks"]["PreToolUse"] == [foreign]          # Eingabe unverändert


def test_setup_global_writes_the_hook_only_when_asked(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    cs.setup_global(dry=False)
    assert "hooks" not in json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    cs.setup_global(dry=False, test_hook=True)
    hooks = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    assert len(hooks) == 1 and "trim_test_output.py" in hooks[0]["hooks"][0]["command"]
