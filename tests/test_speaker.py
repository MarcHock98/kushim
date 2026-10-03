import numpy as np
import pytest

from kushim.voice.speaker import SpeakerVerifier

RNG = np.random.default_rng(0)
BASE = RNG.normal(size=64)


def near(noise=0.1):
    return BASE + RNG.normal(size=64) * noise


def enrolled():
    v = SpeakerVerifier()
    v.enroll([near() for _ in range(4)])
    return v


def test_no_profile_rejects():
    assert not SpeakerVerifier().verify(BASE).accepted


def test_same_speaker_accepted():
    assert enrolled().verify(near()).accepted


def test_other_speaker_rejected():
    assert not enrolled().verify(RNG.normal(size=64)).accepted


@pytest.mark.parametrize("bad", [np.zeros(64), np.full(64, np.nan), np.ones(8), []])
def test_invalid_embedding_rejected(bad):
    assert not enrolled().verify(bad).accepted


def test_enroll_needs_enough_valid_samples():
    with pytest.raises(ValueError):
        SpeakerVerifier().enroll([near(), near()])
    with pytest.raises(ValueError):
        SpeakerVerifier().enroll([near(), near(), np.zeros(64)])


def test_calibrate_threshold_is_clamped():
    from kushim.voice.speaker import MAX_THRESHOLD, MIN_THRESHOLD, calibrate_threshold
    base = np.random.default_rng(3).normal(size=64)
    tight = [base + np.random.default_rng(i).normal(size=64) * 0.05 for i in range(4)]
    loose = [np.random.default_rng(10 + i).normal(size=64) for i in range(4)]
    assert calibrate_threshold(tight) == MAX_THRESHOLD
    assert calibrate_threshold(loose) == MIN_THRESHOLD
    assert calibrate_threshold([]) == MAX_THRESHOLD


def test_profile_vector_roundtrip():
    v = SpeakerVerifier()
    assert v.profile_vector() is None
    base = np.random.default_rng(4).normal(size=16)
    v.set_profile_vector(base)
    assert v.verify(base).accepted
    with pytest.raises(ValueError):
        v.set_profile_vector(np.zeros(16))
