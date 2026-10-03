from types import SimpleNamespace

import numpy as np

from kushim.voice.stt import SpeechToText, to_float32


class FakeModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio, **kw):
        self.calls.append((audio, kw))
        segs = [SimpleNamespace(text=" Hallo "), SimpleNamespace(text="Welt ")]
        return iter(segs), SimpleNamespace(language="de", language_probability=0.97)


def test_int16_is_normalised():
    out = to_float32(np.array([0, 16384, -32768], dtype=np.int16))
    assert out.dtype == np.float32
    assert np.allclose(out, [0.0, 0.5, -1.0])


def test_float_input_is_clipped():
    out = to_float32(np.array([2.0, -3.0, 0.25]))
    assert np.allclose(out, [1.0, -1.0, 0.25])


def test_transcribe_joins_segments_and_passes_options():
    m = FakeModel()
    t = SpeechToText(m, language="de").transcribe(np.ones(1600, dtype=np.int16))
    assert t.text == "Hallo Welt"
    assert t.language == "de" and t.language_probability == 0.97
    kw = m.calls[0][1]
    assert kw["language"] == "de" and kw["vad_filter"] is True


def test_empty_audio_skips_model():
    m = FakeModel()
    t = SpeechToText(m).transcribe(np.array([], dtype=np.int16))
    assert t.text == "" and not m.calls


def test_from_local_passes_device_and_card_to_whisper(monkeypatch):
    import sys
    import types
    seen = {}

    class FakeWhisper:
        def __init__(self, path, **kw):
            seen.update(kw, path=path)
    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeWhisper))
    SpeechToText.from_local("m", device="cuda", compute_type="float16", device_index=2, language="de")
    assert seen["device"] == "cuda" and seen["device_index"] == 2 and seen["local_files_only"] is True
    SpeechToText.from_local("m")
    assert seen["device_index"] == 0
