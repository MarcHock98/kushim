import io
import wave
from pathlib import Path

import numpy as np
import pytest

from kushim.voice.trigger import CombinedDetector, KwsDetector, TriggerEvent
from kushim.voice.wakebuild import KWS_DIR, build_detector
from kushim.voice.wakeconfig import WakeConfig, WakeWord

ROOT = Path(__file__).resolve().parents[1]
FRAME = np.zeros(1280, dtype=np.int16)


class FakeStream:
    def __init__(self):
        self.fed = 0


class FakeSpotter:
    """Liefert nach `fire_after` Frames ein Ergebnis."""

    def __init__(self, fire_at=()):
        self.fire_at, self.frames, self.resets, self._ready, self._result = set(fire_at), 0, 0, 0, ""

    def create_stream(self):
        return FakeStream()

    def is_ready(self, stream):
        return self._ready > 0

    def decode_stream(self, stream):
        self._ready -= 1

    def get_result(self, stream):
        r, self._result = self._result, ""
        return r

    def reset_stream(self, stream):
        self.resets += 1

    # vom Detektor aufgerufen
    def feed(self, stream):
        self.frames += 1
        if self.frames in self.fire_at:
            self._ready, self._result = 1, "kushim"


class FeedingStream(FakeStream):
    def __init__(self, spotter):
        super().__init__()
        self.spotter = spotter

    def accept_waveform(self, rate, wave_):
        assert rate == 16000 and wave_.dtype == np.float32 and np.abs(wave_).max() <= 1.0
        self.spotter.feed(self)


def spotter_with_stream(fire_at):
    s = FakeSpotter(fire_at)
    s.create_stream = lambda: FeedingStream(s)
    return s


def test_keyword_lines_format():
    lines = KwsDetector.keyword_lines([("hey kushim", 0.25, 1.5)], lambda t: ["▁HE", "Y", "▁K"])
    assert lines == ["▁HE Y ▁K :1.5 #0.25 @hey_kushim"]


def test_event_on_result_and_cooldown():
    t = [0.0]
    d = KwsDetector(spotter_with_stream({2, 3, 9}), cooldown=2.0, clock=lambda: t[0])
    assert d.process(FRAME) is None
    ev = d.process(FRAME)
    assert isinstance(ev, TriggerEvent) and ev.source == "wake"
    assert d.process(FRAME) is None                  # Cooldown: zweiter Treffer wird verschluckt
    t[0] = 5.0                                       # Cooldown abgelaufen
    results = [d.process(FRAME) for _ in range(6)]   # Frames 4 bis 9
    assert results[:5] == [None] * 5 and results[5] is not None   # Treffer bei Frame 9 löst wieder aus


def test_float_and_int16_input_are_accepted():
    d = KwsDetector(spotter_with_stream(set()))
    d.process(np.zeros(1280, dtype=np.float32))
    d.process(np.zeros(1280, dtype=np.int16))


def test_combined_runs_every_detector_each_frame():
    seen = []

    class D:
        def __init__(self, name, hit):
            self.name, self.hit = name, hit

        def process(self, frame):
            seen.append(self.name)
            return TriggerEvent("wake") if self.hit else None

    c = CombinedDetector([D("a", False), D("b", True), D("c", False)])
    assert c.process(FRAME) is not None and seen == ["a", "b", "c"]
    with pytest.raises(ValueError):
        CombinedDetector([])


def test_build_detector_fails_clearly_without_kws_model(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_detector(WakeConfig(words=(WakeWord("kushim"),)), tmp_path)


# --- echtes Modell (nur wenn vorhanden) -----------------------------------------------------

def _pcm(engine, text):
    w = wave.open(io.BytesIO(engine.synthesize(text)))
    x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    n = int(len(x) * 16000 / w.getframerate())
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.int16)


def _count(det, pcm):
    pcm = np.concatenate([pcm, np.zeros(16000, dtype=np.int16)])
    return sum(det.process(pcm[i:i + 1280]) is not None for i in range(0, len(pcm) - 1279, 1280))


@pytest.mark.skipif(not (ROOT / KWS_DIR / "bpe.model").exists()
                    or not (ROOT / "models" / "piper" / "de_DE-thorsten-high.onnx").exists(),
                    reason="Modelle nicht vorhanden")
def test_real_model_blockwise_like_the_microphone(tmp_path):
    from kushim.voice.tts import PiperEngine
    eng = PiperEngine.from_local(str(ROOT / "models" / "piper" / "de_DE-thorsten-high.onnx"))
    cfg = WakeConfig(words=(WakeWord("hey kushim"), WakeWord("kushim")))
    (tmp_path / "models").mkdir()
    # echtes Modell aus dem Projekt benutzen, aber Keyword-Datei in tmp_path schreiben
    det = KwsDetector.from_model(ROOT / KWS_DIR, [(w.name, 0.25, 1.5) for w in cfg.words],
                                 tmp_path / "kw.txt")
    positives = sum(_count(KwsDetector.from_model(ROOT / KWS_DIR, [(w.name, 0.25, 1.5) for w in cfg.words],
                                                  tmp_path / "kw.txt"), _pcm(eng, t))
                    for t in ("hey kushim", "kushim, wie spät ist es?", "hey kushim!"))
    assert positives >= 1                           # synthetisch: mindestens einer von drei wird erkannt
    quiet = _count(det, _pcm(eng, "Guten Morgen, ich möchte heute noch einkaufen gehen und danach Kaffee trinken."))
    assert quiet == 0
    assert _count(det, (np.random.default_rng(0).normal(size=80000) * 2000).astype(np.int16)) == 0
