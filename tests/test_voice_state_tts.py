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
