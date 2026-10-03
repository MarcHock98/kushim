from types import SimpleNamespace

from kushim.voice import PushToTalk, WakeWordDetector, key_matches


class FakeModel:
    def __init__(self, scores):
        self.scores = iter(scores)

    def predict(self, frame):
        return {"hey_jarvis": next(self.scores)}


def detector(scores, **kw):
    t = [0.0]
    d = WakeWordDetector(FakeModel(scores), clock=lambda: t[0], **kw)
    return d, t


def test_needs_consecutive_hits():
    d, _ = detector([0.9, 0.1, 0.9, 0.9], hits=2)
    assert [d.process(None) for _ in range(4)][-1] is not None
    d, _ = detector([0.9, 0.1, 0.9, 0.1], hits=2)
    assert all(d.process(None) is None for _ in range(4))


def test_below_threshold_never_fires():
    d, _ = detector([0.3] * 10)
    assert all(d.process(None) is None for _ in range(10))


def test_cooldown_blocks_retrigger():
    d, t = detector([0.9] * 8, hits=1, cooldown=2.0)
    assert d.process(None) is not None
    t[0] = 1.0
    assert d.process(None) is None
    t[0] = 2.5
    assert d.process(None) is not None


def test_key_matches():
    assert key_matches(SimpleNamespace(name="f9"), "F9")
    assert key_matches(SimpleNamespace(char="K"), "k")
    assert not key_matches(SimpleNamespace(name="f8"), "f9")
    assert not key_matches(SimpleNamespace(char=None), "f9")


def test_push_to_talk_only_reacts_to_its_key_and_ignores_repeat():
    events = []
    p = PushToTalk("f9", lambda e: events.append(("start", e.source)), lambda: events.append("stop"))
    other, key = SimpleNamespace(name="a"), SimpleNamespace(name="f9")
    p._press(other)
    p._press(key)
    p._press(key)      # Auto-Repeat
    p._release(other)
    p._release(key)
    assert events == [("start", "hotkey"), "stop"]
