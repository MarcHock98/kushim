import json
import time
from types import SimpleNamespace

import numpy as np

from kushim.api.protocol import ApiCore, new_token
from kushim.api.voice_api import register_voice
from kushim.safety.killswitch import KillSwitch
from kushim.voice import statefile
from kushim.voice.audio import FRAME, UtteranceCollector
from kushim.voice.dialog import Dialog, State
from kushim.voice.talk import TalkLoop

LOUD = (np.ones(FRAME) * 3000).astype(np.int16)
QUIET = np.zeros(FRAME, dtype=np.int16)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def data(tmp_path):
    return json.loads((tmp_path / statefile.FILE).read_text(encoding="utf-8"))


def test_publisher_writes_state_and_clamped_level(tmp_path):
    clock = Clock()
    pub = statefile.StatePublisher(tmp_path, clock=clock)
    pub.phase("listening", 7.0)
    assert data(tmp_path)["state"] == "listening" and data(tmp_path)["level"] == 1.0
    assert statefile.read(tmp_path, now=clock()) == {"active": True, "state": "listening", "level": 1.0}


def test_publisher_throttles_but_writes_state_changes_at_once(tmp_path):
    clock = Clock()
    pub = statefile.StatePublisher(tmp_path, clock=clock)
    pub.phase("idle", 0.1)
    first = data(tmp_path)["ts"]
    clock.t += 0.05
    pub.phase("idle", 0.9)                                    # zu früh: nicht geschrieben
    assert data(tmp_path)["ts"] == first
    pub.phase("speaking", 0.9)                                # Zustandswechsel: sofort
    assert data(tmp_path)["state"] == "speaking"


def test_alarm_then_asking_priority_and_halted_wins(tmp_path):
    clock, pending = Clock(), {"n": 0}
    pub = statefile.StatePublisher(tmp_path, pending=lambda: pending["n"], clock=clock)
    pending["n"] = 1
    pub.phase("thinking")
    assert data(tmp_path)["state"] == "asking"
    pub.alarm()
    assert data(tmp_path)["state"] == "alarm"
    clock.t += statefile.ALARM_SECONDS + 1
    pub.phase("thinking")
    assert data(tmp_path)["state"] == "asking"
    pub.phase("halted")
    assert data(tmp_path)["state"] == "halted"


def test_alarm_is_never_shown_as_message_text(tmp_path):
    pub = statefile.StatePublisher(tmp_path, clock=Clock())
    pub.alarm()
    assert set(data(tmp_path)) == {"state", "level", "ts"}     # kein Text, kein Audio


def test_stale_file_means_no_voice_service(tmp_path):
    clock = Clock()
    statefile.StatePublisher(tmp_path, clock=clock).phase("speaking", 0.5)
    assert statefile.read(tmp_path, now=clock() + statefile.MAX_AGE + 1)["active"] is False


def test_reader_does_not_trust_the_file(tmp_path):
    p = tmp_path / statefile.FILE
    p.parent.mkdir()
    now = time.time()
    for bad in ('', 'nope', '[]', '{}', json.dumps({"state": "root", "level": 0, "ts": now}),
                json.dumps({"state": "idle", "level": "x", "ts": now}),
                json.dumps({"state": "idle", "level": True, "ts": now}),
                json.dumps({"state": "idle", "level": 0, "ts": "now"})):
        p.write_text(bad, encoding="utf-8")
        assert statefile.read(tmp_path)["active"] is False, bad
    p.write_text(json.dumps({"state": "idle", "level": 5, "ts": now}), encoding="utf-8")
    assert statefile.read(tmp_path) == {"active": True, "state": "idle", "level": 1.0}


def test_no_file_is_inactive(tmp_path):
    assert statefile.read(tmp_path) == {"active": False, "state": "idle", "level": 0.0}


def test_frame_level_is_a_number_between_zero_and_one():
    assert statefile.frame_level(QUIET) == 0.0
    assert 0.0 < statefile.frame_level(LOUD) <= 1.0
    assert statefile.frame_level(np.zeros(0, dtype=np.int16)) == 0.0


def test_api_voice_state_needs_token_and_returns_only_numbers_and_names(tmp_path):
    token = new_token()
    core = ApiCore(token)
    register_voice(core, tmp_path)
    assert json.loads(core.handle(json.dumps({"type": "voice.state"})))["error"] == "unauthorized"
    statefile.StatePublisher(tmp_path).phase("listening", 0.4)
    reply = json.loads(core.handle(json.dumps({"token": token, "type": "voice.state"})))
    assert reply == {"ok": True, "active": True, "state": "listening", "level": 0.4}


def test_dialog_reports_changes_and_a_failing_listener_never_breaks_it():
    seen = []
    d = Dialog(on_change=seen.append)
    d.triggered(); d.utterance_done(); d.reply_ready(); d.speech_done()
    assert seen == [State.LISTENING, State.THINKING, State.SPEAKING, State.IDLE]

    def boom(_):
        raise RuntimeError("x")
    d2 = Dialog(on_change=boom)
    assert d2.triggered() and d2.state is State.LISTENING


def test_talk_loop_phases_follow_the_conversation(tmp_path):
    phases = []

    class Pipe:
        dialog = Dialog()

        def handle(self, pcm):
            return SimpleNamespace(heard="x", reply="y", outcome="spoken")

    n = {"i": -1}

    def wake(frame):
        n["i"] += 1
        return n["i"] == 0

    loop = TalkLoop([LOUD, LOUD, QUIET, QUIET, QUIET], Pipe(), KillSwitch(tmp_path, []), wake=wake,
                    new_collector=lambda: UtteranceCollector(silence_ms=160, min_ms=80),
                    on_frame=lambda f, p: phases.append(p))
    loop.run()
    assert phases[0] == "idle" and "listening" in phases


def test_a_failing_on_frame_never_stops_the_loop(tmp_path):
    def boom(frame, phase):
        raise RuntimeError("x")
    loop = TalkLoop([QUIET] * 3, SimpleNamespace(dialog=Dialog()), KillSwitch(tmp_path, []),
                    wake=lambda f: False, on_frame=boom)
    assert loop.run() == "ended"
