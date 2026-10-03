import numpy as np
import pytest

from kushima.voice.enrollment import SENTENCES, enroll

BASE = np.random.default_rng(7).normal(size=64)


def make_recorder(shorts=()):
    state = {"i": -1}

    def record():
        state["i"] += 1
        return None if state["i"] in shorts else state["i"]
    return record


def embed(x):
    if x is None:
        return np.zeros(0)
    return BASE + np.random.default_rng(100 + x).normal(size=64) * 0.05


def test_enroll_builds_profile_and_threshold():
    said = []
    res = enroll(make_recorder(), embed, say=said.append)
    assert res.used == len(SENTENCES) == len(said)
    assert res.verifier.verify(BASE).accepted
    assert not res.verifier.verify(-BASE).accepted
    assert 0.5 <= res.threshold <= 0.75 and res.mean_similarity > 0.9


def test_short_recording_is_retried():
    said = []
    res = enroll(make_recorder(shorts={0}), embed, say=said.append)
    assert res.used == len(SENTENCES)
    assert any("noch einmal" in m for m in said)


def test_too_few_samples_fail():
    with pytest.raises(RuntimeError):
        enroll(lambda: None, embed, say=lambda m: None)
