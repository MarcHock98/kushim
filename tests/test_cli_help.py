import argparse

from kushim import cli


def top_level_commands():
    captured = {}
    orig = argparse.ArgumentParser.parse_args

    def spy(self, *a, **k):
        for act in self._actions:
            if isinstance(act, argparse._SubParsersAction) and "cmd" not in captured:
                captured["cmd"] = set(act.choices)
        return orig(self, *a, **k)
    argparse.ArgumentParser.parse_args = spy
    try:
        cli.main(["help"])
    finally:
        argparse.ArgumentParser.parse_args = orig
    return captured["cmd"]


def test_help_command_prints_overview_and_returns_zero(capsys):
    assert cli.main(["help"]) == 0
    out = capsys.readouterr().out
    assert "kushim talk" in out and "kushim kill" in out and "NOTAUS" in out


def test_help_lists_every_command_so_it_cannot_drift():
    for name in top_level_commands():
        assert f"kushim {name}" in cli.HELP, f"{name} fehlt in der Hilfe"
