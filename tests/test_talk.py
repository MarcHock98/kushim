from types import SimpleNamespace

import numpy as np
import pytest

from kushim.safety import killswitch
from kushim.safety.killswitch import KillSwitch
from kushim.voice.audio import FRAME, UtteranceCollector
from kushim.voice.talk import TalkLoop

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


def test_needs_exactly_one_trigger(tmp_path):
    k = KillSwitch(tmp_path, [])
    with pytest.raises(ValueError):
        TalkLoop([], FakePipeline(), k)
    with pytest.raises(ValueError):
        TalkLoop([], FakePipeline(), k, wake=lambda f: True, ptt_down=lambda: True)


def test_wake_word_flow(tmp_path):
    k = KillSwitch(tmp_path, [])
    p = FakePipeline()
    frames = [QUIET, QUIET, LOUD, LOUD, QUIET, QUIET, QUIET]
    loud_first = iter([False, False, True])           # Wake bei Frame 3
    loop = TalkLoop(frames, p, k, wake=lambda f: next(loud_first, False), new_collector=collector)
    assert loop.run() == "ended"
    assert p.calls == [3 * FRAME]


def test_wake_without_speech_does_not_call_pipeline(tmp_path):
    k = KillSwitch(tmp_path, [])
    p = FakePipeline()
    fired = iter([True])
    loop = TalkLoop([QUIET] * 40, p, k, wake=lambda f: next(fired, False),
                    new_collector=lambda: UtteranceCollector(max_ms=240))
    loop.run()
    assert p.calls == []          # Max-Länge erreicht ohne Sprache: nichts senden


def test_kill_marker_stops_loop(tmp_path):
    k = KillSwitch(tmp_path, [])
    killswitch.trigger(tmp_path)
    assert TalkLoop([QUIET] * 5, FakePipeline(), k, wake=lambda f: True).run() == "killed"


def test_kill_phrase_result_stops_loop(tmp_path):
    k = KillSwitch(tmp_path, [])
    p = FakePipeline(outcome="killed")
    state = iter([True])
    loop = TalkLoop([LOUD, LOUD, QUIET, QUIET, QUIET, LOUD], p, k, wake=lambda f: next(state, False),
                    new_collector=collector)
    assert loop.run() == "killed" and len(p.calls) == 1


def test_push_to_talk_records_while_held(tmp_path):
    k = KillSwitch(tmp_path, [])
    p = FakePipeline()
    held = iter([True, True, True, False])            # gedrückt für 3 Abfragen, dann losgelassen
    loop = TalkLoop([LOUD, LOUD, LOUD, QUIET, QUIET], p, k, ptt_down=lambda: next(held, False),
                    new_collector=collector)
    assert loop.run() == "ended" and len(p.calls) == 1
