import pytest

from kushim.safety import killswitch as ks


@pytest.mark.parametrize("text", [
    "Notaus", "Kushim, NOTAUS!", "stopp alles", "Bitte alles stoppen", "Not-Aus", "Not aus jetzt",
    "emergency stop", "kushim stopp", "Sofort Stopp"])
def test_kill_phrases(text):
    assert ks.is_kill_phrase(text)


@pytest.mark.parametrize("text", ["Wie wird das Wetter", "Spiel Musik", "", "stopp die Musik bitte"])
def test_normal_speech_does_not_kill(text):
    assert not ks.is_kill_phrase(text)


def test_marker_roundtrip(tmp_path):
    assert not ks.is_triggered(tmp_path)
    ks.trigger(tmp_path)
    assert ks.is_triggered(tmp_path)
    ks.clear(tmp_path)
    ks.clear(tmp_path)
    assert not ks.is_triggered(tmp_path)


def test_fire_runs_all_actions_even_if_one_fails(tmp_path):
    ran = []

    def bad():
        raise RuntimeError("x")

    k = ks.KillSwitch(tmp_path, [lambda: ran.append(1), bad, lambda: ran.append(2)])
    k.fire()
    assert ran == [1, 2] and ks.is_triggered(tmp_path) and k.fired


def test_poll_reacts_to_external_marker_once(tmp_path):
    ran = []
    k = ks.KillSwitch(tmp_path, [lambda: ran.append(1)])
    assert not k.poll()
    ks.trigger(tmp_path)
    assert k.poll() and k.poll()
    assert ran == [1]


def test_transcript_triggers(tmp_path):
    ran = []
    k = ks.KillSwitch(tmp_path, [lambda: ran.append(1)])
    assert not k.on_transcript("Hallo")
    assert k.on_transcript("Kushim notaus") and ran == [1]


def test_cli_kill_and_resume(tmp_path, monkeypatch):
    from kushim import cli
    root = cli.__file__
    from pathlib import Path
    project = Path(root).resolve().parents[2]
    ks.clear(project)
    try:
        assert cli.main(["kill"]) == 0 and ks.is_triggered(project)
        assert cli.main(["start"]) == 1          # startet nicht bei aktivem Notaus
        assert cli.main(["resume"]) == 0 and not ks.is_triggered(project)
    finally:
        ks.clear(project)


def test_both_name_spellings_trigger_kill():
    assert ks.is_kill_phrase("kushim stopp") and ks.is_kill_phrase("Kushim stop")
