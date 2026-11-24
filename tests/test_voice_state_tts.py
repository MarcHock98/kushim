"""Feld `tts` in run/voice-state.json: Zustand der Sprachausgabe für die Oberfläche (loading|ready|cpu|failed|off)."""
import json

import pytest

from kushim.voice import statefile


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.mark.parametrize("state", statefile.TTS_STATES)
def test_publisher_writes_every_tts_state_at_once(tmp_path, state):
    clock = Clock()
    pub = statefile.StatePublisher(tmp_path, clock=clock)
    pub.tts(state)
    assert statefile.read(tmp_path, now=clock())["tts"] == state


def test_unknown_tts_state_becomes_off_on_both_sides(tmp_path):
    clock = Clock()
    pub = statefile.StatePublisher(tmp_path, clock=clock)
    pub.tts("gpu-und-noch-was")
    assert statefile.read(tmp_path, now=clock())["tts"] == "off"
    for bad in ("CPU", 1, None, ["ready"], {"x": 1}, "ready\n"):
        (tmp_path / statefile.FILE).write_text(json.dumps({"state": "idle", "level": 0, "ts": clock(), "tts": bad}), encoding="utf-8")
        assert statefile.read(tmp_path, now=clock())["tts"] == "off", bad


def test_old_files_without_the_field_and_stale_files_read_as_off(tmp_path):
    clock = Clock()
    (tmp_path / "run").mkdir()
    (tmp_path / statefile.FILE).write_text(json.dumps({"state": "idle", "level": 0, "ts": clock()}), encoding="utf-8")
    assert statefile.read(tmp_path, now=clock())["tts"] == "off"
    statefile.StatePublisher(tmp_path, clock=clock).tts("ready")
    assert statefile.read(tmp_path, now=clock() + statefile.MAX_AGE + 1) == {
        "active": False, "state": "idle", "level": 0.0, "wake_count": 0, "wake_last": "", "tts": "off"}


def test_tts_state_survives_phase_updates(tmp_path):
    clock = Clock()
    pub = statefile.StatePublisher(tmp_path, clock=clock)
    pub.tts("cpu")
    clock.t += 1
    pub.phase("listening", 0.5)
    r = statefile.read(tmp_path, now=clock())
    assert r["tts"] == "cpu" and r["state"] == "listening"


def test_nothing_is_written_after_clear(tmp_path):
    """Prüfung 2026-11-24: Das Beenden des Workers meldete „off“ NACH clear() und schrieb so ein frisches Lebenszeichen;
    appstart hielt den Sprachdienst danach noch 5 s für laufend."""
    clock = Clock()
    pub = statefile.StatePublisher(tmp_path, clock=clock)
    pub.phase("idle")
    pub.clear()
    pub.tts("off")
    pub.phase("idle")
    pub.wake("kushim")
    pub.alarm()
    assert not (tmp_path / statefile.FILE).exists()
    assert statefile.read(tmp_path, now=clock())["active"] is False


def test_talk_closes_the_voice_before_clearing_the_heartbeat():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "src" / "kushim" / "cli.py").read_text(encoding="utf-8")
    body = src[src.index("reason = loop.run()"):]
    assert body.index("tts.on_state = lambda state: None") < body.index("tts.close()") < body.index("publisher.clear()")
