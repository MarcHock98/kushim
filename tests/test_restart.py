"""Neustart von `kushim start` auf Befehl: Marke, Befehlszeile, saubere Umgebung."""
from kushim.channel import launch


def test_request_and_consume_the_restart_flag_once(tmp_path):
    assert not launch.restart_requested(tmp_path)
    path = launch.request_restart(tmp_path)
    assert path == tmp_path / launch.RESTART_FILE and path.is_file()
    assert launch.restart_requested(tmp_path)           # gilt einmal und wird dabei gelöscht
    assert not path.exists() and not launch.restart_requested(tmp_path)


def test_restart_argv_repeats_folder_devices_and_ui_choice():
    argv = launch.restart_argv("projekt", mic="USB", out="Kopfhörer", no_ui=True, python="py")
    assert argv[0] == "py" and argv[-7:] == ["start", "projekt", "--mic", "USB", "--out", "Kopfhörer", "--no-ui"]
    plain = launch.restart_argv("projekt", python="py")
    assert plain[-2:] == ["start", "projekt"] and "--no-ui" not in plain and "--mic" not in plain


def test_restart_starts_in_a_new_clean_environment(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")
    seen = {}

    def fake(argv, **kw):
        seen.update(argv=argv, **kw)
        return "fenster"

    assert launch.restart(["kushim", "start"], popen=fake) == "fenster"
    assert seen["argv"] == ["kushim", "start"]
    assert "CLAUDECODE" not in seen["env"] and "CLAUDE_CODE_CHILD_SESSION" not in seen["env"]


def test_restart_command_only_writes_the_flag(tmp_path, monkeypatch, capsys):
    from kushim import cli
    monkeypatch.setattr(launch, "request_restart", lambda root: seen.append(root))
    seen = []
    assert cli.main(["restart"]) == 0 and len(seen) == 1
    assert "Neustart angefordert" in capsys.readouterr().out
