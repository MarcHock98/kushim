import os
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
# Testaudio: einmalig mit der früheren Piper-Stimme (thorsten-high) erzeugt, 16 kHz, 16 bit, mono (tests/data/kws, < 1 MB).
# Feste Dateien statt Synthese bei jedem Lauf: keine Stimme im Test nötig und jedes Mal dasselbe Signal.
DATA = Path(__file__).resolve().parent / "data" / "kws"
MODELS = Path(os.environ.get("KUSHIM_MODELS_ROOT") or ROOT)       # Modelle liegen nicht im Git (auch nicht im Worktree)
POSITIVE = ("pos1.wav", "pos2.wav", "pos3.wav", "pos4.wav", "pos5.wav", "pos6.wav", "pos7.wav", "pos8.wav")


def _pcm(name):
    with wave.open(str(DATA / name)) as w:
        assert w.getframerate() == 16000 and w.getsampwidth() == 2 and w.getnchannels() == 1
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def _count(det, pcm):
    pcm = np.concatenate([pcm, np.zeros(16000, dtype=np.int16)])
    return sum(det.process(pcm[i:i + 1280]) is not None for i in range(0, len(pcm) - 1279, 1280))


def test_kws_fixtures_are_small_wavs():
    files = sorted(DATA.glob("*.wav"))
    assert {f.name for f in files} == set(POSITIVE) | {"neg1.wav"}
    assert sum(f.stat().st_size for f in files) < 1_000_000
    assert all(len(_pcm(f.name)) > 8000 for f in files)


@pytest.mark.skipif(not (MODELS / KWS_DIR / "bpe.model").exists(), reason="KWS-Modell nicht vorhanden")
def test_real_model_blockwise_like_the_microphone(tmp_path):
    cfg = WakeConfig(words=(WakeWord("hey kushim"), WakeWord("kushim")))
    (tmp_path / "models").mkdir()
    # echtes Modell aus dem Projekt benutzen, aber Keyword-Datei in tmp_path schreiben
    det = KwsDetector.from_model(MODELS / KWS_DIR, [(w.name, 0.15, 2.0) for w in cfg.words],
                                 tmp_path / "kw.txt")
    positives = sum(_count(KwsDetector.from_model(MODELS / KWS_DIR, [(w.name, 0.15, 2.0) for w in cfg.words],
                                                  tmp_path / "kw.txt"), _pcm(name))
                    for name in POSITIVE)
    # Die Erkennungsrate lag mit synthetischer Stimme bei rund 60 %; mindestens ein Treffer ist die feste Untergrenze.
    assert positives >= 1
    quiet = _count(det, _pcm("neg1.wav"))
    assert quiet == 0
    assert _count(det, (np.random.default_rng(0).normal(size=80000) * 2000).astype(np.int16)) == 0
