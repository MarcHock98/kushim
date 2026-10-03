import io
import wave

import numpy as np
import pytest

from kushim.voice import audio
from kushim.voice.audio import FRAME, UtteranceCollector

LOUD = (np.ones(FRAME) * 3000).astype(np.int16)
QUIET = np.zeros(FRAME, dtype=np.int16)


def test_collects_until_silence_after_speech():
    c = UtteranceCollector(silence_ms=240, min_ms=80)   # 3 stille Frames
    done = [c.feed(f) for f in [LOUD, LOUD, QUIET, QUIET, QUIET]]
    assert done == [False, False, False, False, True]
    assert len(c.audio()) == 5 * FRAME and c.heard_speech


def test_silence_alone_ends_only_by_max_length():
    c = UtteranceCollector(silence_ms=160, max_ms=800)      # 10 Frames Maximum
    results = [c.feed(QUIET) for _ in range(10)]
    assert results == [False] * 9 + [True] and not c.heard_speech


def test_max_length_cuts_off():
    c = UtteranceCollector(max_ms=240)
    assert [c.feed(LOUD) for _ in range(3)] == [False, False, True]


def test_speech_resets_quiet_counter():
    c = UtteranceCollector(silence_ms=240, min_ms=80)
    seq = [LOUD, QUIET, QUIET, LOUD, QUIET, QUIET]
    assert not any(c.feed(f) for f in seq)


def test_find_device_none_means_default():
    assert audio.find_device(None, "input") is None
    assert audio.find_device("", "output") is None


def test_find_device_unknown_raises():
    with pytest.raises(LookupError):
        audio.find_device("gibt-es-nicht-xyz", "input")


def test_wav_roundtrip_helper_format():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050); w.writeframes(b"\0\0" * 10)
    with wave.open(io.BytesIO(buf.getvalue())) as w:
        assert w.getframerate() == 22050


def test_collector_gives_up_when_nobody_speaks():
    c = UtteranceCollector(wait_ms=240, max_ms=10_000)      # 3 Frames Wartezeit
    assert [c.feed(QUIET) for _ in range(3)] == [False, False, True] and not c.heard_speech
