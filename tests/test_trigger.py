import pytest
from types import SimpleNamespace

from kushima.voice import WakeWordDetector, resolve_wake_words


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


def test_resolve_pretrained_words(tmp_path):
    assert resolve_wake_words(["hey_jarvis", " alexa "], tmp_path) == ["hey_jarvis", "alexa"]


def test_resolve_custom_model_only_from_wakewords_dir(tmp_path):
    d = tmp_path / "models" / "wakewords"
    d.mkdir(parents=True)
    (d / "hey_kushima.onnx").write_bytes(b"x")
    out = resolve_wake_words(["hey_kushima.onnx"], tmp_path)
    assert out == [str((d / "hey_kushima.onnx").resolve())]


@pytest.mark.parametrize("bad", ["", "unbekannt", "../evil.onnx", "C:/x/evil.onnx", "sub/evil.onnx",
                                 "fehlt.onnx"])
def test_resolve_rejects_unknown_or_foreign_paths(tmp_path, bad):
    (tmp_path / "models" / "wakewords").mkdir(parents=True)
    with pytest.raises(ValueError):
        resolve_wake_words([bad], tmp_path)


def test_resolve_needs_at_least_one(tmp_path):
    with pytest.raises(ValueError):
        resolve_wake_words([], tmp_path)


def test_any_of_several_words_triggers():
    class Multi:
        def predict(self, frame):
            return {"hey_jarvis": 0.1, "alexa": 0.9}

    d = WakeWordDetector(Multi(), threshold=0.6, hits=1)
    ev = d.process(None)
    assert ev is not None and ev.source == "wake"
