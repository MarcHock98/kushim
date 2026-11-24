"""macOS-Unterstützung: Terminal-Fenster (termwin), Prozessbäume beenden, Pfade je System, Schutzordner, Channel-Protokoll."""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

from kushim import procflags, termwin
from kushim.channel import claude_log, launch
from kushim.claude_cli import folders as cfolders
from kushim.stage import schema

posix_only = pytest.mark.skipif(os.name == "nt", reason="nur macOS/Linux")


# --- procflags ----------------------------------------------------------------------------------------------------------

def test_venv_paths_follow_the_platform(tmp_path, monkeypatch):
    monkeypatch.setattr(procflags.os, "name", "posix")
    assert procflags.venv_python(tmp_path) == tmp_path / "bin" / "python"
    site = tmp_path / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    assert procflags.venv_site_packages(tmp_path) == [site]
    monkeypatch.setattr(procflags.os, "name", "nt")
    assert procflags.venv_python(tmp_path) == tmp_path / "Scripts" / "python.exe"
    assert procflags.venv_site_packages(tmp_path) == [tmp_path / "Lib" / "site-packages"]


def test_parse_ps_and_descendants_collect_the_whole_tree_without_loops():
    table = procflags.parse_ps("  10     1\n  11    10\n  12    11\n  13    10\n  99     1\nkaputt\n  10    12\n")
    assert sorted(procflags.descendants(10, table)) == [11, 12, 13]           # 99 gehört nicht dazu, Zyklus 12->10 endet
    assert procflags.descendants(99, table) == []


@posix_only
def test_kill_tree_ends_a_real_process_and_its_child():
    code = "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); time.sleep(60)"
    parent = subprocess.Popen([sys.executable, "-c", code])
    try:
        end = time.monotonic() + 10
        kids: list[int] = []
        while time.monotonic() < end and not kids:
            kids = procflags.descendants(parent.pid, procflags.parse_ps(
                subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True).stdout))
            time.sleep(0.05)
        assert kids, "Kindprozess nicht gestartet"
        procflags.kill_tree(parent.pid)
        parent.wait(timeout=5)
        for k in kids:
            with pytest.raises(OSError):
                os.kill(k, 0)
    finally:
        if parent.poll() is None:
            parent.kill()


def test_kill_tree_ignores_nonsense_pids():
    procflags.kill_tree(None)          # type: ignore[arg-type]
    procflags.kill_tree(0)
    procflags.kill_tree(-5)


# --- termwin: Startdatei ------------------------------------------------------------------------------------------------

def test_script_quotes_every_part_and_contains_no_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("KUSHIM_VAULT_KEY", "geheim123")
    folder = tmp_path / "mein ordner; rm -rf ~"
    text = termwin.script_text("kushim-claude", "kushim-Claude", folder, ["/x/claude", "--name", "a'b"], "claude", tmp_path,
                               python="/v/bin/python")
    assert text.startswith("#!/bin/sh\n") and "geheim123" not in text
    last = text.strip().splitlines()[-1]
    assert last.startswith("exec ")
    argv = shlex.split(last[len("exec "):])
    assert argv[:4] == ["/v/bin/python", "-P", "-m", "kushim.termwin"]          # -P: nichts aus dem Arbeitsordner importieren
    assert argv[argv.index("--cwd") + 1] == str(folder) and argv[argv.index("--env") + 1] == "claude"
    assert argv[argv.index("--") + 1:] == ["/x/claude", "--name", "a'b"]


def test_script_rejects_unknown_env_kind_and_bad_names(tmp_path):
    with pytest.raises(ValueError):
        termwin.script_text("x", "t", tmp_path, ["a"], "alles", tmp_path)
    with pytest.raises(ValueError):
        termwin.open_window(tmp_path, "../boese", "t", ["a"], tmp_path, "claude", run=lambda *a, **k: None)


def test_title_is_reduced_to_safe_characters(tmp_path):
    text = termwin.script_text("w", "a$(b)`c`\x1b]", tmp_path, ["x"], "plain", tmp_path)
    title_line = text.splitlines()[1]
    assert "$(" not in title_line and "`" not in title_line and "\x1b]" not in title_line.split("printf")[1].split("'", 2)[2]


def test_open_window_writes_a_private_command_file_and_calls_open(tmp_path):
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")
    win = termwin.open_window(tmp_path, "kushim-claude", "kushim-Claude", ["/x/claude"], tmp_path, "claude", run=run)
    cmd = tmp_path / "run" / "kushim-claude.command"
    assert calls == [["open", "-a", "Terminal", str(cmd)]]
    assert cmd.is_file() and (cmd.stat().st_mode & 0o777) == 0o700
    assert isinstance(win, termwin.TerminalWindow)


def test_open_window_failure_raises_and_removes_the_file(tmp_path):
    with pytest.raises(OSError):
        termwin.open_window(tmp_path, "w", "t", ["x"], tmp_path, "plain",
                            run=lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "nope"))
    assert not (tmp_path / "run" / "w.command").exists()


# --- termwin: Fenster beobachten ----------------------------------------------------------------------------------------

class Clock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


def test_window_is_open_while_the_helper_pid_lives(tmp_path):
    clock, alive = Clock(), {"v": True}
    pid_file = tmp_path / "w.pid"
    win = termwin.TerminalWindow(pid_file, since=clock(), clock=clock, sleep=clock.sleep, alive=lambda pid: alive["v"])
    assert win.pid is None and win.poll() is None                     # Terminal startet noch
    pid_file.write_text("4242")
    os.utime(pid_file, (clock() + 1, clock() + 1))
    assert win.pid == 4242 and win.poll() is None
    alive["v"] = False
    assert win.poll() == 0 and win.wait() == 0


def test_window_that_never_starts_counts_as_closed(tmp_path):
    clock = Clock()
    win = termwin.TerminalWindow(tmp_path / "w.pid", since=clock(), start_timeout=5, clock=clock, sleep=clock.sleep,
                                 alive=lambda pid: True)
    assert win.wait() == 1 and win.pid is None


def test_stale_pid_file_from_an_earlier_window_is_ignored(tmp_path):
    clock = Clock()
    pid_file = tmp_path / "w.pid"
    pid_file.write_text("777")
    os.utime(pid_file, (clock() - 100, clock() - 100))
    win = termwin.TerminalWindow(pid_file, since=clock(), clock=clock, sleep=clock.sleep, alive=lambda pid: True)
    assert win.pid is None and win.poll() is None


def test_wait_with_timeout_raises(tmp_path):
    clock = Clock()
    win = termwin.TerminalWindow(tmp_path / "w.pid", since=clock(), clock=clock, sleep=clock.sleep, alive=lambda p: True)
    with pytest.raises(subprocess.TimeoutExpired):
        win.wait(timeout=1)


# --- termwin: Helfer im Fenster -----------------------------------------------------------------------------------------

def test_helper_writes_pid_removes_command_file_and_builds_the_claude_env_itself(tmp_path, monkeypatch):
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "kushim-claude.command").write_text("x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fremd")
    monkeypatch.setenv("KUSHIM_VAULT_KEY", "geheim")
    seen = {}

    class P:
        def wait(self):
            seen["pid_during"] = (tmp_path / "run" / "kushim-claude.pid").read_text()
            return 7

    def popen(cmd, cwd, env):
        seen.update(cmd=cmd, cwd=cwd, env=env)
        return P()
    rc = termwin.helper_main(["--run", "kushim-claude", "--root", str(tmp_path), "--env", "claude", "--cwd", "/proj", "--",
                              "/x/claude", "--name", "kushim"], popen=popen, wait_close=lambda: None)
    assert rc == 7 and seen["cmd"] == ["/x/claude", "--name", "kushim"] and seen["cwd"] == "/proj"
    assert seen["pid_during"] == str(os.getpid())
    env = seen["env"]
    assert "ANTHROPIC_API_KEY" not in env and "KUSHIM_VAULT_KEY" not in env
    assert env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert not (tmp_path / "run" / "kushim-claude.command").exists()
    assert not (tmp_path / "run" / "kushim-claude.pid").exists()          # Fenster zu: PID-Datei weg


def test_helper_restart_env_marks_the_restart_and_drops_claude_markers(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    seen = {}

    class P:
        def wait(self):
            return 0
    termwin.helper_main(["--run", "kushim-restart", "--root", str(tmp_path), "--env", "restart", "--cwd", str(tmp_path), "--",
                         "py", "start"], popen=lambda cmd, cwd, env: seen.update(env=env) or P(), wait_close=lambda: None)
    assert seen["env"][launch.RESTARTED_ENV] == "1" and "CLAUDECODE" not in seen["env"]


def test_helper_survives_a_missing_program(tmp_path):
    def popen(*a, **k):
        raise FileNotFoundError("claude")
    rc = termwin.helper_main(["--run", "w", "--root", str(tmp_path), "--env", "plain", "--cwd", str(tmp_path), "--", "nix"],
                             popen=popen, wait_close=lambda: None)
    assert rc == 127


# --- launch: macOS-Zweig ------------------------------------------------------------------------------------------------

def test_launch_on_macos_opens_a_terminal_window_with_the_claude_argv(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(launch.termwin, "is_mac", lambda: True)
    monkeypatch.setattr(launch.termwin, "open_window",
                        lambda root, name, title, argv, cwd, env_kind: opened.append((name, title, argv, cwd, env_kind)) or "win")
    folder = tmp_path / "proj"
    folder.mkdir()
    assert launch.launch(Path("/x/claude"), folder, tmp_path) == "win"
    name, title, argv, cwd, env_kind = opened[0]
    sid = launch.read_session(tmp_path)
    assert name == "kushim-claude" and title == launch.WINDOW_TITLE and cwd == folder and env_kind == "claude"
    assert argv[0] == "/x/claude" and sid in argv and "--dangerously-load-development-channels" in argv


def test_show_and_restart_on_macos_use_terminal_windows(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(launch.termwin, "is_mac", lambda: True)
    monkeypatch.setattr(launch.termwin, "open_window",
                        lambda root, name, title, argv, cwd, env_kind: opened.append((root, name, argv, env_kind)) or "w")
    (tmp_path / "run").mkdir()
    (tmp_path / launch.SESSION_FILE).write_text("12345678-1234-1234-1234-123456789abc")
    assert launch.show(Path("/x/claude"), tmp_path) == "w"
    assert launch.restart(["py", "start"], root=tmp_path) == "w"
    assert opened[0][1:] == ("kushim-attach", ["/x/claude", "attach", "12345678"], "claude")
    assert opened[1] == (tmp_path, "kushim-restart", ["py", "start"], "restart")


def test_injected_popen_keeps_the_old_path_even_on_macos(tmp_path, monkeypatch):
    monkeypatch.setattr(launch.termwin, "is_mac", lambda: True)
    monkeypatch.setattr(launch.termwin, "open_window", lambda *a, **k: pytest.fail("kein Terminal in Tests"))
    folder = tmp_path / "proj"
    folder.mkdir()
    got = launch.launch(Path("/x/claude"), folder, tmp_path, popen=lambda argv, **kw: ("popen", argv))
    assert got[0] == "popen"


# --- Pfade: Channel-Protokoll, Konfiguration, Schutzordner, Ansichten -----------------------------------------------------

def test_claude_cache_dir_per_platform(tmp_path):
    home = Path("/Users/someone")
    assert claude_log.cache_base("darwin", {}, home) == home / "Library" / "Caches" / "claude-cli-nodejs"
    assert claude_log.cache_base("linux", {}, home) == home / ".cache" / "claude-cli-nodejs"
    assert claude_log.cache_base("linux", {"XDG_CACHE_HOME": "/c"}, home) == Path("/c") / "claude-cli-nodejs"
    assert claude_log.cache_base("win32", {"LOCALAPPDATA": "D:/L"}, home) == Path("D:/L") / "claude-cli-nodejs" / "Cache"
    assert claude_log.cache_base("win32", {}, home) is None


def test_macos_project_key_matches_claude_codes_folder_names():
    assert claude_log.project_key(Path("/Users/Marc.Hock/private/kushim")) == "-Users-Marc-Hock-private-kushim"


def test_config_path_on_macos_uses_application_support(monkeypatch, tmp_path):
    from kushim import config
    monkeypatch.delenv("KUSHIM_CONFIG", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.sys, "platform", "darwin")
    assert config.config_path() == Path.home() / "Library" / "Application Support" / "kushim" / "config.toml"


@posix_only
def test_library_and_system_folders_are_protected_on_macos(tmp_path):
    home = tmp_path / "home"
    (home / "Library" / "Projekt").mkdir(parents=True)
    with pytest.raises(ValueError, match="geschützten Bereich"):
        cfolders.validate_path(home / "Library" / "Projekt", home=home)
    roots = {str(p) for p in cfolders.forbidden_roots(home)}
    assert {"/System", "/Library", "/usr", "/etc"} <= roots
    ok = tmp_path / "projekte" / "a"
    (ok / ".git").mkdir(parents=True)
    assert cfolders.validate_path(ok, home=home) == ok.resolve()      # Temp-Ordner (/private/var/...) bleiben erlaubt


def test_deep_nesting_is_too_large_regardless_of_the_c_recursion_limit():
    v: list = []
    for _ in range(schema.MAX_DEPTH + 5):
        v = [v]
    assert schema._too_deep(v) and not schema._too_deep([[{"a": [1]}]])
    with pytest.raises(schema.ViewError) as e:
        schema.validate({"id": "x", "art": "antwort", "titel": "T", "bausteine": [], "tief": v})
    assert e.value.code == "too_large"
