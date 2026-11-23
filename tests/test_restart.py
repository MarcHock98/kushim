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
    assert "shell" not in seen and isinstance(seen["argv"], list)                 # keine Shell, Argumente als Liste


def test_restart_keeps_kushims_own_environment_but_not_the_claude_markers(monkeypatch):
    """Audit M1: KUSHIM_CONFIG und KUSHIM_VAULT_KEY überleben den Neustart (clean_env ist nur für Claude gedacht)."""
    monkeypatch.setenv("KUSHIM_CONFIG", r"D:\kushim\config.toml")
    monkeypatch.setenv("KUSHIM_VAULT_KEY", "geheim")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")
    seen = {}
    launch.restart(["kushim", "start"], popen=lambda argv, **kw: seen.update(kw))
    env = seen["env"]
    assert env["KUSHIM_CONFIG"] == r"D:\kushim\config.toml" and env["KUSHIM_VAULT_KEY"] == "geheim"
    assert "CLAUDECODE" not in env and "CLAUDE_CODE_CHILD_SESSION" not in env
    assert env[launch.RESTARTED_ENV] == "1"                                         # Kennzeichen für den neuen Prozess (N1)
    import os
    assert os.environ["CLAUDECODE"] == "1" and launch.RESTARTED_ENV not in os.environ   # die eigene Umgebung bleibt unberührt


def test_claude_environment_stays_filtered(monkeypatch):
    """Die Umgebung für Claude (claude_env, von `_start` über launch.launch benutzt) filtert weiter KUSHIM_* und Schlüssel."""
    monkeypatch.setenv("KUSHIM_CONFIG", "x")
    monkeypatch.setenv("KUSHIM_VAULT_KEY", "geheim")
    monkeypatch.setenv(launch.RESTARTED_ENV, "1")
    env = launch.claude_env()
    assert "KUSHIM_CONFIG" not in env and "KUSHIM_VAULT_KEY" not in env and launch.RESTARTED_ENV not in env


def test_restart_command_only_writes_the_flag(tmp_path, monkeypatch, capsys):
    from kushim import cli
    monkeypatch.setattr(launch, "request_restart", lambda root: seen.append(root))
    seen = []
    assert cli.main(["restart"]) == 0 and len(seen) == 1
    assert "Neustart angefordert" in capsys.readouterr().out
