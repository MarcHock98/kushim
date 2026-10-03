from types import SimpleNamespace

import numpy as np

from kushima.safety import killswitch
from kushima.safety.killswitch import KillSwitch
from kushima.voice.audio import FRAME, UtteranceCollector
from kushima.voice.talk import TalkLoop

LOUD = (np.ones(FRAME) * 3000).astype(np.int16)
QUIET = np.zeros(FRAME, dtype=np.int16)


class FakePipeline:
    def __init__(self, outcome="spoken"):
        self.calls, self.outcome = [], outcome

    def handle(self, pcm):
        self.calls.append(len(pcm))
        return SimpleNamespace(heard="x", reply="y", outcome=self.outcome)


def collector():
    return UtteranceCollector(silence_ms=160, min_ms=80)   # 2 stille Frames


def fires_at(*indexes):
    """Wake-Detektor, der bei den n-ten Aufrufen auslöst."""
    n = {"i": -1}

    def wake(frame):
        n["i"] += 1
        return n["i"] in indexes
    return wake


def test_wake_word_flow_with_ack_and_flush(tmp_path):
    k = KillSwitch(tmp_path, [])
    p, events = FakePipeline(), []
    frames = [QUIET, QUIET, LOUD, LOUD, QUIET, QUIET, QUIET]
    loop = TalkLoop(frames, p, k, wake=fires_at(2), new_collector=collector,
                    ack=lambda: events.append("ack"), flush=lambda: events.append("flush"))
    assert loop.run() == "ended"
    assert events == ["ack", "flush"]          # Quittung, dann Puffer verwerfen
    assert p.calls == [3 * FRAME]


def test_only_wake_word_gets_ack_but_no_pipeline_call(tmp_path):
    k = KillSwitch(tmp_path, [])
    p, events = FakePipeline(), []
    loop = TalkLoop([QUIET] * 40, p, k, wake=fires_at(0), ack=lambda: events.append("ack"),
                    new_collector=lambda: UtteranceCollector(wait_ms=240))
    loop.run()
    assert events == ["ack"] and p.calls == []


def test_nothing_before_wake_word_reaches_pipeline_or_collector(tmp_path):
    k = KillSwitch(tmp_path, [])
    p, made = FakePipeline(), []
    loop = TalkLoop([LOUD] * 30, p, k, wake=lambda f: False,
                    new_collector=lambda: made.append(1) or collector())
    assert loop.run() == "ended" and p.calls == [] and made == []


def test_kill_marker_stops_loop(tmp_path):
    k = KillSwitch(tmp_path, [])
    killswitch.trigger(tmp_path)
    assert TalkLoop([QUIET] * 5, FakePipeline(), k, wake=lambda f: True).run() == "killed"


def test_kill_phrase_result_stops_loop(tmp_path):
    k = KillSwitch(tmp_path, [])
    p = FakePipeline(outcome="killed")
    loop = TalkLoop([LOUD, LOUD, QUIET, QUIET, QUIET, LOUD], p, k, wake=fires_at(0),
                    new_collector=collector)
    assert loop.run() == "killed" and len(p.calls) == 1
