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
    argv = launch.claude_argv(EXE, Path("C:/k/run/kushim-mcp.json"), "sid")
    assert argv == [str(EXE), "--session-id", "sid", "--name", "kushim", "--strict-mcp-config", "--mcp-config",
                    str(Path("C:/k/run/kushim-mcp.json")), "--allowedTools", "mcp__kushim__sprich,mcp__kushim__zeige",
                    "--dangerously-load-development-channels", "server:kushim"]
    assert not any("skip-permissions" in a or "bypass" in a.lower() for a in argv)


def test_argv_pre_allows_exactly_the_two_kushim_tools_and_nothing_broader():
    argv = launch.claude_argv(EXE, Path("C:/k/run/kushim-mcp.json"), "sid")
    flags = [a for a in argv if a.lower().replace("-", "").startswith(("allowedtools", "allowtools", "tools", "permission"))
             or "dangerously-skip" in a or a.startswith("--allow")]
    assert flags == ["--allowedTools"]                                         # genau eine Freigabe-Angabe, kein Modus
    allowed = argv[argv.index("--allowedTools") + 1].split(",")
    assert allowed == ["mcp__kushim__sprich", "mcp__kushim__zeige"]
    assert not any(ch in a for a in allowed for ch in "*?() ")                  # kein Platzhalter, kein Muster, kein Leerzeichen
    lowered = " ".join(argv).lower()
    assert not any(t in lowered for t in ("bash", "powershell", "write", "edit", "webfetch", "mcp__kushim__*"))
    assert "--disallowedTools" not in argv and "--permission-mode" not in argv


def test_env_drops_foreign_keys_and_turns_telemetry_off():
    env = launch.claude_env({"PATH": "p", "ANTHROPIC_API_KEY": "x", "OPENAI_API_KEY": "y", "KUSHIM_X": "z",
                             "CLAUDE_CODE_OAUTH_TOKEN": "keep"})
    assert env == {"PATH": "p", "CLAUDE_CODE_OAUTH_TOKEN": "keep", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                   "CLAUDE_CODE_GB_DISK_CACHE_WHEN_TELEMETRY_OFF": "1"}          # Option b: Telemetrie bleibt aus


def test_model_and_effort_go_into_argv_only_from_the_fixed_set():
    argv = launch.claude_argv(EXE, Path("C:/k/run/kushim-mcp.json"), "sid", model="sonnet", effort="high")
    assert argv[argv.index("--model") + 1] == "sonnet" and argv[argv.index("--effort") + 1] == "high"
    assert argv.count("--model") == 1 and argv.count("--effort") == 1
    assert argv[argv.index("--allowedTools") + 1] == "mcp__kushim__sprich,mcp__kushim__zeige"   # bleibt genau die zwei
    assert argv[-2:] == ["--dangerously-load-development-channels", "server:kushim"]
    assert "--model" not in launch.claude_argv(EXE, Path("c.json"), "sid", model="", effort="")  # leer = Standard von Claude Code
    only_effort = launch.claude_argv(EXE, Path("c.json"), "sid", model="", effort="max")
    assert "--model" not in only_effort and only_effort[only_effort.index("--effort") + 1] == "max"
    assert launch.check_options(" Opus ", "XHIGH") == ("opus", "xhigh")
    for model, effort in (("gpt-5", ""), ("sonnet --dangerously-skip-permissions", ""), ("", "ultra"), ("", "high;rm"),
                          ("claude-sonnet-5-5", "")):
        with pytest.raises(ValueError):
            launch.claude_argv(EXE, Path("c.json"), "sid", model=model, effort=effort)
    assert launch.MODELS == ("sonnet", "opus", "haiku", "fable") and launch.EFFORTS == ("low", "medium", "high", "xhigh", "max")


def test_config_claude_model_and_effort_defaults_and_overrides(tmp_path):
    from kushim.config import Config
    assert (Config.load(tmp_path / "fehlt.toml").claude_model, Config.load(tmp_path / "fehlt.toml").claude_effort) == ("sonnet", "high")
    p = tmp_path / "config.toml"
    p.write_text('[claude]\nfolders = []\n', encoding="utf-8")
    assert (Config.load(p).claude_model, Config.load(p).claude_effort) == ("sonnet", "high")       # ohne Angabe: Standard
    p.write_text('[claude]\nmodel = "Opus"\neffort = ""\n', encoding="utf-8")
    c = Config.load(p)
    assert (c.claude_model, c.claude_effort) == ("opus", "") and launch.check_options(c.claude_model, c.claude_effort) == ("opus", "")
    p.write_text('[claude]\nmodel = 5\neffort = "wild"\n', encoding="utf-8")
    c = Config.load(p)
    with pytest.raises(ValueError):
        launch.check_options(c.claude_model, "")
    with pytest.raises(ValueError):
        launch.check_options("", c.claude_effort)


def test_example_config_documents_model_and_effort():
    import tomllib
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "config.example.toml").read_text(encoding="utf-8"))
    assert data["claude"]["model"] == "sonnet" and data["claude"]["effort"] == "high"
    assert launch.check_options(data["claude"]["model"], data["claude"]["effort"]) == ("sonnet", "high")


def test_launch_opens_claude_in_the_folder(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(launch.os, "name", "nt")
    launch.launch(EXE, tmp_path / "proj", tmp_path, popen=lambda argv, **kw: seen.update(argv=argv, **kw))
    assert seen["cwd"] == str(tmp_path / "proj") and seen["creationflags"] == launch.CREATE_NEW_CONSOLE
    assert seen["argv"][:5] == ["cmd.exe", "/k", "title", "kushim-Claude", "&"]                 # Fenster bleibt sichtbar
    assert seen["argv"][-1] == "server:kushim" and seen["env"]["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert seen["env"]["CLAUDE_CODE_GB_DISK_CACHE_WHEN_TELEMETRY_OFF"] == "1"
    a = seen["argv"]
    assert a[a.index("--model") + 1] == "sonnet" and a[a.index("--effort") + 1] == "high"     # Standard: Sonnet, Aufwand hoch
    sid = launch.read_session(tmp_path)
    assert (tmp_path / "run" / "kushim-mcp.json").exists() and sid and seen["argv"][seen["argv"].index("--session-id") + 1] == sid


def test_stop_and_show_use_the_stored_session_id(tmp_path, monkeypatch):
    monkeypatch.setattr(launch.os, "name", "nt")
    assert launch.stop(EXE, tmp_path, run=lambda *a, **k: None) is False                  # nichts bekannt: nichts tun
    assert launch.show(EXE, tmp_path, popen=lambda *a, **k: 1) is None
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "claude-session.txt").write_text("kein-uuid; rm -rf /", encoding="utf-8")
    assert launch.read_session(tmp_path) is None                                           # nur echte UUIDs
    sid = "060815a8-c2ba-4013-a557-1cce18e7d315"
    (tmp_path / "run" / "claude-session.txt").write_text(sid, encoding="utf-8")
    shown, ran = {}, {}
    launch.show(EXE, tmp_path, popen=lambda argv, **kw: shown.update(argv=argv, **kw))
    assert shown["argv"][-3:] == [str(EXE), "attach", "060815a8"] and shown["creationflags"] == launch.CREATE_NEW_CONSOLE
    assert launch.stop(EXE, tmp_path, run=lambda argv, **kw: ran.update(argv=argv, **kw)) is True
    assert ran["argv"] == [str(EXE), "stop", "060815a8"] and ran["creationflags"] == 0x08000000      # stoppen ohne Fenster
    assert launch.read_session(tmp_path) is None


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
    for var in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "APPDATA", "LOCALAPPDATA",
                "CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION"):          # Tests laufen evtl. selbst in Claude Code
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
    launched, talked, stopped = [], [], []
    window = Window()
    options = []
    monkeypatch.setattr(launch, "launch", lambda exe, folder, root, **kw: launched.append((exe, folder)) or options.append(kw) or window)
    monkeypatch.setattr(launch, "stop", lambda exe, root: stopped.append(exe) or True)
    monkeypatch.setattr(cli, "_main", lambda argv: talked.append(argv) or 0)
    return SimpleNamespace(proj=proj, cfg=cfgfile, launched=launched, talked=talked, stopped=stopped, window=window, mp=monkeypatch,
                           options=options)


class Window:
    """Gefälschtes Claude-Fenster: läuft, bis `close()` gerufen wird."""

    def __init__(self):
        import threading
        self.closed, self.pid = threading.Event(), 4242

    def wait(self):
        self.closed.wait()

    def poll(self):
        return 0 if self.closed.is_set() else None

    def close(self):
        self.closed.set()


def start(env, *argv, no_ui=False):
    from kushim.config import Config
    args = SimpleNamespace(folder=None, mic=None, out=None, ui=False, no_ui=no_ui)
    for a in argv:
        args.folder = a
    return cli._start(args, Config.load(env.cfg), env.proj.parent)


def test_start_launches_claude_in_the_only_folder_then_talks(env, capsys):
    env.mp.setattr(cli, "kill_tree", lambda pid: env.window.close(), raising=False)
    import kushim.procflags as pf
    env.mp.setattr(pf, "kill_tree", lambda pid: env.window.close())
    assert start(env) == 0
    assert env.launched == [(EXE, env.proj.resolve())]
    assert env.talked == [["talk", "--ui"]]                                            # Standard: mit Oberfläche
    assert env.stopped == [EXE] and env.window.closed.is_set()                           # kushim endet: Claude und Fenster auch
    out = capsys.readouterr().out
    assert "Entwicklungs-Channel bestätigen" in out and "beendet sich alles" in out
    assert env.options == [{"model": "sonnet", "effort": "high"}] and "Modell sonnet, Aufwand high" in out


def test_start_refuses_an_unknown_model_from_config_before_launching(env, capsys):
    env.cfg.write_text(env.cfg.read_text(encoding="utf-8") + 'model = "gpt-5"\n', encoding="utf-8")
    assert start(env) == 2 and env.launched == [] and env.talked == []
    assert "[claude] in config.toml" in capsys.readouterr().out


def test_channel_watch_warns_once_in_terminal_and_by_voice_only_when_off(tmp_path, capsys):
    import threading
    from kushim.channel import claude_log
    launch.NOTICES.clear()
    done = threading.Event()
    assert cli._watch_channel(tmp_path, 0.0, done, check=lambda d, since: "on") == "on"
    assert cli._watch_channel(tmp_path, 0.0, done, check=lambda d, since: "unknown") == "unknown"
    assert capsys.readouterr().out == "" and cli._notice() is None
    assert cli._watch_channel(tmp_path, 0.0, done, check=lambda d, since: "off") == "off"
    assert claude_log.TERMINAL_HINT in capsys.readouterr().out
    from kushim.voice import earcon
    assert cli._notice() == earcon.mark(claude_log.SPOKEN_HINT) and cli._notice() is None   # genau einmal, mit Signalton
    assert "claude" not in claude_log.SPOKEN_HINT.lower() and claude_log.SPOKEN_HINT.startswith("Mein ")
    done.set()                                                                          # kushim endet schon: nichts mehr sagen
    assert cli._watch_channel(tmp_path, 0.0, done, check=lambda d, since: "off") == "off" and cli._notice() is None
    def boom(d, since):
        raise OSError("kaputt")
    assert cli._watch_channel(tmp_path, 0.0, threading.Event(), check=boom) == "unknown"


def test_closing_the_claude_window_ends_kushim(env, capsys):
    import time
    import kushim.procflags as pf
    env.mp.setattr(pf, "kill_tree", lambda pid: None)

    def talk(argv):                                                                     # Zuhören läuft, bis es unterbrochen wird
        env.window.close()                                                              # Nutzer schließt das Claude-Fenster
        try:
            for _ in range(100):                                                        # kurze Schritte wie die Mikrofonschleife
                time.sleep(0.05)
        except KeyboardInterrupt:
            return 0
        return 99
    env.mp.setattr(cli, "_main", talk)
    assert start(env) == 0 and env.stopped == [EXE]
    assert "Claude-Fenster geschlossen" in capsys.readouterr().out


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


def test_start_refuses_inside_a_claude_code_session_and_says_why(env, capsys):
    env.mp.setenv("CLAUDE_CODE_CHILD_SESSION", "1")
    assert start(env) == 1 and env.launched == [] and env.talked == []
    assert "Channels are not currently available" in capsys.readouterr().out
    assert cli._inside_claude_session({"CLAUDECODE": "1"}) and not cli._inside_claude_session({})


def test_start_without_ui_on_request(env, capsys):
    import kushim.procflags as pf
    env.mp.setattr(pf, "kill_tree", lambda pid: env.window.close())
    assert start(env, no_ui=True) == 0
    assert env.talked == [["talk"]]


def test_ui_window_opens_once_the_api_is_ready_and_not_after_the_end(tmp_path, capsys):
    import threading
    from kushim import appstart
    done, procs, opened = threading.Event(), [], []
    cli._open_ui_window(tmp_path, done, procs)                                          # App nicht gebaut: nur Hinweis
    assert procs == [] and "nicht gebaut" in capsys.readouterr().out
    exe = appstart.ui_path(tmp_path)
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    class Window:
        def wait(self):
            return 0
    window, closed = Window(), []
    cli._open_ui_window(tmp_path, done, procs, popen=lambda a, **k: opened.append(a) or window,
                        wait=lambda root, since, alive: True, on_close=lambda: closed.append(1))
    assert opened == [[str(exe)]] and procs == [window]
    assert closed == [1]                                                                # Nutzer schließt das Fenster: alles endet
    done.set()
    cli._open_ui_window(tmp_path, done, procs, popen=lambda a, **k: opened.append(a), wait=lambda root, since, alive: False)
    assert len(opened) == 1 and "nicht verbinden" not in capsys.readouterr().out


def test_closing_by_kushim_itself_does_not_trigger_the_shutdown_again(tmp_path):
    import threading
    from kushim import appstart
    exe = appstart.ui_path(tmp_path)
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    done, closed = threading.Event(), []

    class Window:
        def wait(self):
            done.set()                                                                  # kushim endet und schließt das Fenster
            return 0
    cli._open_ui_window(tmp_path, done, [], popen=lambda a, **k: Window(), wait=lambda root, since, alive: True,
                        on_close=lambda: closed.append(1))
    assert closed == []


# --- Neustart-Pfad in `_start` (Audit M2, N1). Alles gemockt: Fenster, Claude, Talk und Popen starten nichts echt. ---

@pytest.fixture
def restart_env(env):
    """`_start` mit gemocktem Neustart: `launch.restart` und `_thread.interrupt_main` zeichnen nur auf."""
    import _thread
    import threading
    import kushim.procflags as pf
    env.mp.setattr(pf, "kill_tree", lambda pid: env.window.close())
    interrupted = threading.Event()
    env.mp.setattr(_thread, "interrupt_main", interrupted.set)
    restarts = []
    env.mp.setattr(launch, "restart", lambda argv, popen=None: restarts.append(argv) or "neues Fenster")
    env.mp.setattr(cli, "_watch_channel", lambda *a, **k: "unknown")
    env.mp.setattr(cli, "_pause", lambda: env.paused.append(1))
    env.mp.delenv(launch.RESTARTED_ENV, raising=False)
    env.interrupted, env.restarts, env.paused = interrupted, restarts, []
    yield env
    env.window.close()                                                                 # Hilfs-Threads sicher beenden


def _talk_that_asks_for_restart(env):
    """Zuhören läuft; währenddessen sagt der Nutzer `kushim restart`. Ende wie echt: KeyboardInterrupt aus watch_restart."""
    def talk(argv):
        launch.request_restart(env.proj.parent)
        if not env.interrupted.wait(5.0):
            return 99
        raise KeyboardInterrupt
    return talk


def test_start_deletes_an_old_restart_flag_and_does_not_restart_for_it(restart_env, capsys):
    env = restart_env
    flag = env.proj.parent / launch.RESTART_FILE
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("restart", encoding="utf-8")                                       # Marke aus einem früheren Lauf
    seen = []
    env.mp.setattr(cli, "_main", lambda argv: seen.append(flag.exists()) or 0)
    assert start(env, no_ui=True) == 0
    assert seen == [False]                                                             # schon vor dem Zuhören gelöscht
    assert env.restarts == [] and not env.interrupted.is_set()
    out = capsys.readouterr().out
    assert "Neustart angefordert" not in out and "neuen Fenster neu" not in out


def test_start_without_a_restart_request_ends_without_restart(restart_env):
    env = restart_env
    assert start(env, no_ui=True) == 0 and env.talked == [["talk"]]
    assert env.restarts == []


def test_restart_flag_set_during_the_run_restarts_after_cleanup(restart_env, capsys):
    env = restart_env
    env.mp.setattr(cli, "_main", _talk_that_asks_for_restart(env))
    with pytest.raises(KeyboardInterrupt):
        start(env, "proj", no_ui=True)
    assert env.stopped == [EXE] and env.window.closed.is_set()                         # erst aufgeräumt
    assert len(env.restarts) == 1
    argv = env.restarts[0]
    assert isinstance(argv, list) and argv[-3:] == ["start", "proj", "--no-ui"]
    assert not (env.proj.parent / launch.RESTART_FILE).exists()                        # Marke verbraucht
    out = capsys.readouterr().out
    assert "Neustart angefordert" in out and "startet in einem neuen Fenster neu" in out
    assert out.index("Claude-Sitzung beendet") < out.index("startet in einem neuen Fenster neu")


def test_no_restart_while_the_kill_switch_is_active(restart_env, capsys):
    env = restart_env
    state = {"on": False}
    env.mp.setattr(killswitch, "is_triggered", lambda root: state["on"])

    def talk(argv):                                                                    # Neustart gewünscht, dann Notaus
        launch.request_restart(env.proj.parent)
        assert env.interrupted.wait(5.0)
        state["on"] = True
        raise KeyboardInterrupt
    env.mp.setattr(cli, "_main", talk)
    with pytest.raises(KeyboardInterrupt):
        start(env, no_ui=True)
    assert env.restarts == []
    assert "neuen Fenster neu" not in capsys.readouterr().out


def test_an_oserror_during_restart_is_reported(restart_env, capsys):
    env = restart_env

    def broken(argv, popen=None):
        raise OSError("python.exe nicht gefunden")
    env.mp.setattr(launch, "restart", broken)
    env.mp.setattr(cli, "_main", _talk_that_asks_for_restart(env))
    with pytest.raises(KeyboardInterrupt):
        start(env, no_ui=True)
    out = capsys.readouterr().out
    assert "Neustart nicht möglich: python.exe nicht gefunden" in out
    assert "startet in einem neuen Fenster neu" not in out


def test_restarted_start_keeps_the_window_open_after_an_early_abort(restart_env, capsys):
    """Audit N1: scheitert ein durch Neustart erzeugtes `kushim start` früh, wartet es auf eine Taste."""
    env = restart_env
    env.mp.setenv(launch.RESTARTED_ENV, "1")
    env.mp.setattr(killswitch, "is_triggered", lambda root: True)
    assert start(env) == 1 and env.paused == [1]
    assert "Notaus ist aktiv" in capsys.readouterr().out
    import os
    assert launch.RESTARTED_ENV not in os.environ                                      # gilt nur für diesen Prozess
    env.mp.setenv(launch.RESTARTED_ENV, "1")
    env.mp.setattr(killswitch, "is_triggered", lambda root: False)
    env.mp.setattr(base, "auth_status", lambda exe: Auth(False))
    assert start(env) == 1 and env.paused == [1, 1]                                    # nicht angemeldet


def test_restarted_start_shows_an_unexpected_error_before_closing(restart_env, capsys):
    env = restart_env
    env.mp.setenv(launch.RESTARTED_ENV, "1")

    def boom():
        raise RuntimeError("kaputt")
    env.mp.setattr(base, "find_claude", boom)
    assert start(env) == 1 and env.paused == [1]
    assert "RuntimeError: kaputt" in capsys.readouterr().err


def test_normal_start_does_not_wait_for_a_key(restart_env):
    env = restart_env
    env.mp.setattr(killswitch, "is_triggered", lambda root: True)
    assert start(env) == 1 and env.paused == []                                        # ohne Neustart: wie bisher
    env.mp.setattr(killswitch, "is_triggered", lambda root: False)
    env.mp.setenv(launch.RESTARTED_ENV, "1")
    assert start(env, no_ui=True) == 0 and env.paused == []                            # erfolgreicher Lauf: keine Pause
    env.mp.setattr(base, "find_claude", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(RuntimeError):
        start(env)                                                                     # ohne Kennzeichen: Fehler wie bisher


def test_pause_never_uses_a_shell(monkeypatch):
    import subprocess as sp
    import os as _os
    def no(*a, **k):
        raise AssertionError("keine Shell")
    monkeypatch.setattr(_os, "system", no)
    monkeypatch.setattr(sp, "run", no)
    monkeypatch.setattr(sp, "Popen", no)
    try:
        import msvcrt
        monkeypatch.setattr(msvcrt, "getch", lambda: b"x")
    except ImportError:
        monkeypatch.setattr("builtins.input", lambda prompt="": "")
    cli._pause()
