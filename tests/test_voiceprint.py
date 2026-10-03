from pathlib import Path

import numpy as np
import pytest

from kushim.config import Config
from kushim.memory import open_store
from kushim.voice import voiceprint
from kushim.voice.embedder import SherpaEmbedder
from kushim.voice.speaker import SpeakerVerifier

KEY = "ab" * 32


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("KUSHIM_VAULT_KEY", KEY)


def store(tmp_path):
    cfg = Config(path=tmp_path / "config.toml", memory_location=f"local:{tmp_path / 'v'}")
    return open_store(cfg, create=True)


def enrolled(seed=0):
    base = np.random.default_rng(seed).normal(size=512)
    v = SpeakerVerifier()
    v.enroll([base + 0.01, base - 0.01, base])
    return v, base


def test_roundtrip_in_vault(tmp_path):
    v, base = enrolled()
    with store(tmp_path) as s:
        assert voiceprint.load(s) is None
        voiceprint.save(s, v, "test-model")
    with open_store(Config(path=tmp_path / "c.toml", memory_location=f"local:{tmp_path / 'v'}")) as s2:
        v2 = voiceprint.load(s2)
        assert v2 is not None and v2.verify(base).accepted
        assert not v2.verify(-base).accepted


def test_profile_is_not_plaintext_in_vault_file(tmp_path):
    v, _ = enrolled()
    with store(tmp_path) as s:
        voiceprint.save(s, v, "m")
    raw = (tmp_path / "v" / "memory.db").read_bytes()
    assert b"voiceprint" not in raw and b"dim" not in raw


def test_clear_and_corrupt_profile_mean_no_profile(tmp_path):
    v, _ = enrolled()
    with store(tmp_path) as s:
        voiceprint.save(s, v, "m")
        voiceprint.clear(s)
        assert voiceprint.load(s) is None
        s.set_profile(voiceprint.KEY, "{kaputt")
        assert voiceprint.load(s) is None
        s.set_profile(voiceprint.KEY, '{"model":"m","dim":999,"vec":"AAAA"}')
        assert voiceprint.load(s) is None


def test_save_without_profile_raises(tmp_path):
    with store(tmp_path) as s:
        with pytest.raises(ValueError):
            voiceprint.save(s, SpeakerVerifier(), "m")


class FakeStream:
    def __init__(self):
        self.wave = None

    def accept_waveform(self, sample_rate, waveform):
        self.wave = waveform

    def input_finished(self):
        pass


class FakeExtractor:
    def create_stream(self):
        return FakeStream()

    def is_ready(self, s):
        return s.wave is not None

    def compute(self, s):
        return [float(np.mean(s.wave))] * 4


def test_embedder_rejects_too_short_audio_and_normalises_int16():
    e = SherpaEmbedder(FakeExtractor())
    assert e(np.zeros(1000, dtype=np.int16)).size == 0
    out = e(np.full(16000, 16384, dtype=np.int16))
    assert out.shape == (4,) and np.allclose(out, 0.5)


def test_real_model_if_present():
    root = Path(__file__).resolve().parents[1]
    model = root / "models" / "speaker" / "wespeaker_en_voxceleb_CAM++_LM.onnx"
    piper = root / "models" / "piper" / "de_DE-thorsten-high.onnx"
    if not model.exists() or not piper.exists():
        pytest.skip("Modelle nicht vorhanden")
    import io
    import wave

    from kushim.voice.tts import PiperEngine
    eng = PiperEngine.from_local(str(piper))

    def pcm16k(text):
        w = wave.open(io.BytesIO(eng.synthesize(text)))
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
        n = int(len(x) * 16000 / w.getframerate())
        return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.int16)

    emb = SherpaEmbedder.from_local(str(model))
    a = emb(pcm16k("Heute scheint die Sonne über Würzburg, aber am Nachmittag soll es regnen."))
    b = emb(pcm16k("Bitte erinnere mich morgen um halb acht an den Termin beim Zahnarzt."))
    assert a.size == 512 and b.size == 512      # Smoke-Test; Kalibrierung geht nur mit echter Stimme
