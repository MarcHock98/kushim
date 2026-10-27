"""`kushim start`: Claude Code mit dem kushim-Channel starten (Roadmap v2 B5)."""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from kushim import cli
from kushim.channel import launch
from kushim.claude_cli import base
from kushim.claude_cli.base import Auth
from kushim.doctor import claude_checks
from kushim.safety import killswitch

EXE = Path("C:/fake/claude.exe")


def test_mcp_config_names_only_the_kushim_channel_server(tmp_path):
    cfg = launch.mcp_config("C:/py/python.exe")
    assert cfg == {"mcpServers": {"kushim": {"command": "C:/py/python.exe", "args": ["-m", "kushim.channel"]}}}
    path = launch.write_mcp_config(tmp_path, "C:/py/python.exe")
    assert path == tmp_path / "run" / "kushim-mcp.json" and json.loads(path.read_text(encoding="utf-8")) == cfg


def test_argv_loads_only_the_kushim_server_as_development_channel():
    argv = launch.claude_argv(EXE, Path("C:/k/run/kushim-mcp.json"))
    assert argv == [str(EXE), "--strict-mcp-config", "--mcp-config", str(Path("C:/k/run/kushim-mcp.json")),
                    "--dangerously-load-development-channels", "server:kushim"]
    assert not any("skip-permissions" in a or "bypass" in a.lower() for a in argv)


def test_env_drops_foreign_keys_and_turns_telemetry_off():
    env = launch.claude_env({"PATH": "p", "ANTHROPIC_API_KEY": "x", "OPENAI_API_KEY": "y", "KUSHIM_X": "z",
                             "CLAUDE_CODE_OAUTH_TOKEN": "keep"})
    assert env == {"PATH": "p", "CLAUDE_CODE_OAUTH_TOKEN": "keep", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}


def test_launch_opens_claude_in_the_folder(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(launch.os, "name", "nt")
    launch.launch(EXE, tmp_path / "proj", tmp_path, popen=lambda argv, **kw: seen.update(argv=argv, **kw))
    assert seen["cwd"] == str(tmp_path / "proj") and seen["creationflags"] == launch.CREATE_NEW_CONSOLE
    assert seen["argv"][-1] == "server:kushim" and seen["env"]["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert (tmp_path / "run" / "kushim-mcp.json").exists()


@pytest.mark.parametrize("out,expected", [("2.1.311 (Claude Code)\n", (2, 1, 311)), ("1.0.71", (1, 0, 71)),
                                          ("kaputt", None), ("", None)])
def test_version_parsing(out, expected):
    run = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")
    assert base.version(EXE, run=run) == expected


def test_version_when_the_cli_cannot_run():
    def boom(argv, **kw):
        raise OSError("weg")
    assert base.version(EXE, run=boom) is None


def test_doctor_claude_checks():
    ok = claude_checks(lambda: EXE, lambda e: (2, 1, 311), lambda e: True, (2, 1, 234))
    assert [c.ok for c in ok] == [True, True, True] and "ist 2.1.311" in ok[1].name
    old = claude_checks(lambda: EXE, lambda e: (2, 1, 100), lambda e: False, (2, 1, 234))
    assert [c.ok for c in old] == [True, False, False] and "claude update" in old[1].hint
    assert [c.ok for c in claude_checks(lambda: None, None, None, (2, 1, 234))] == [False]


# --- CLI ------------------------------------------------------------------------------------------

@pytest.fixture
def env(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    for var in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.delenv(var, raising=False)
    cfgfile = tmp_path / "config.toml"
    cfgfile.write_text(f'[memory]\nlocation = "local:{(tmp_path / "vault").as_posix()}"\n'
                       f'[claude]\nfolders = ["proj|{proj.as_posix()}"]\n', encoding="utf-8")
    monkeypatch.setenv("KUSHIM_CONFIG", str(cfgfile))
    monkeypatch.setattr(base, "find_claude", lambda: EXE)
    monkeypatch.setattr(base, "version", lambda exe: (2, 1, 311))
    monkeypatch.setattr(base, "auth_status", lambda exe: Auth(True, "claude.ai"))
    from kushim.claude_cli import folders as cfolders
    real = cfolders.validate_path                                               # pytest arbeitet unter AppData (dort zu Recht gesperrt)
    monkeypatch.setattr(cfolders, "validate_path", lambda raw, vault: real(raw, vault, home=tmp_path / "home"))
    launched, talked = [], []
    monkeypatch.setattr(launch, "launch", lambda exe, folder, root: launched.append((exe, folder)))
    monkeypatch.setattr(cli, "_main", lambda argv: talked.append(argv) or 0)
    return SimpleNamespace(proj=proj, cfg=cfgfile, launched=launched, talked=talked, mp=monkeypatch)


def start(env, *argv):
    from kushim.config import Config
    args = SimpleNamespace(folder=None, mic=None, out=None, ui=False)
    for a in argv:
        args.folder = a
    return cli._start(args, Config.load(env.cfg), env.proj.parent)


def test_start_launches_claude_in_the_only_folder_then_talks(env, capsys):
    assert start(env) == 0
    assert env.launched == [(EXE, env.proj.resolve())] and env.talked == [["talk"]]
    assert "Entwicklungs-Channel bestätigen" in capsys.readouterr().out


def test_start_refuses_without_claude_old_version_login_or_folder(env):
    env.mp.setattr(base, "find_claude", lambda: None)
    assert start(env) == 1
    env.mp.setattr(base, "find_claude", lambda: EXE)
    env.mp.setattr(base, "version", lambda exe: (2, 1, 200))
    assert start(env) == 1
    env.mp.setattr(base, "version", lambda exe: (2, 1, 311))
    env.mp.setattr(base, "auth_status", lambda exe: Auth(False))
    assert start(env) == 1
    env.mp.setattr(base, "auth_status", lambda exe: Auth(True, "claude.ai"))
    assert start(env, "gibtsnicht") == 2
    assert env.launched == [] and env.talked == []


def test_start_refuses_while_the_kill_switch_is_active(env):
    killswitch.trigger(env.proj.parent)
    assert start(env) == 1 and env.launched == []
