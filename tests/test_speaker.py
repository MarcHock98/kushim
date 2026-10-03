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
