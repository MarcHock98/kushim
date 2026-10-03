import wave

import numpy as np

from kushim.voice import recorder
from kushim.voice.recorder import FRAME, RATE, check_take, load_paragraphs, record_session

LOUD = (np.ones(FRAME) * 5000).astype(np.int16)
QUIET = np.zeros(FRAME, dtype=np.int16)


def take_frames(n_loud=40, n_quiet=30):
    return [LOUD] * n_loud + [QUIET] * n_quiet      # 3,2 s Sprache, dann 2,4 s Stille


def test_paragraphs_parsed_from_real_text():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    paras = load_paragraphs(root)
    assert len(paras) == 10 and paras[0].startswith("Hallo, schön, dass du da bist")


def test_check_take_flags_problems():
    assert check_take(np.zeros(RATE * 3, dtype=np.int16)).problems       # leise
    assert "zu kurz" in check_take((np.ones(RATE // 2) * 5000).astype(np.int16)).problems
    assert any("übersteuert" in p for p in check_take((np.ones(RATE * 3) * 32500).astype(np.int16)).problems)
    assert not check_take((np.ones(RATE * 3) * 5000).astype(np.int16)).problems


def test_session_saves_wavs_and_skips_existing(tmp_path):
    out = tmp_path / "voice-data" / "clone"
    msgs = []
    frames = iter(take_frames() * 2)
    n = record_session(out, frames, say=msgs.append, paragraphs=["Eins.", "Zwei."], root=tmp_path)
    assert n == 2
    with wave.open(str(out / "01.wav")) as w:
        assert w.getframerate() == RATE and w.getnchannels() == 1 and w.getnframes() > RATE * 2
    again = record_session(out, iter([]), say=msgs.append, paragraphs=["Eins.", "Zwei."], root=tmp_path)
    assert again == 0 and any("schon vorhanden" in m for m in msgs)


def test_bad_takes_are_retried_then_skipped(tmp_path):
    out = tmp_path / "c"
    frames = iter([QUIET] * 500)         # niemand spricht
    msgs = []
    n = record_session(out, frames, say=msgs.append, paragraphs=["Eins."], root=tmp_path)
    assert n == 0 and not (out / "01.wav").exists() and any("übersprungen" in m for m in msgs)


def test_flush_called_before_each_take(tmp_path):
    calls = []
    record_session(tmp_path / "c", iter(take_frames() * 2), say=lambda m: None,
                   paragraphs=["A.", "B."], root=tmp_path, flush=lambda: calls.append(1))
    assert len(calls) == 2


# --- manuelle Steuerung per Enter --------------------------------------------------------------

import wave as _wave

from kushim.voice.recorder import EnterController, record_manual


class FakeEvent:
    """Wird nach `after` Abfragen gesetzt (= Nutzer drückt Enter)."""

    def __init__(self, after=None):
        self.after, self.n = after, 0

    def is_set(self):
        self.n += 1
        return self.after is not None and self.n > self.after

    def wait(self):
        pass


class FakeController:
    def __init__(self, stop_after=40, keeps=(True,), log=None):
        self.stop_after, self.keeps, self.log = stop_after, list(keeps), log if log is not None else []

    def wait_start(self):
        self.log.append("start")

    def stop_event(self):
        self.log.append("stop_event")
        return FakeEvent(self.stop_after)

    def finish(self, ev):
        self.log.append("finish")

    def keep(self):
        self.log.append("keep?")
        return self.keeps.pop(0) if self.keeps else True


def loud_frames(log=None):
    while True:
        if log is not None:
            log.append("frame")
        yield LOUD


def test_manual_take_runs_until_enter_and_trims_key_clicks():
    log = []
    ctl = FakeController(stop_after=40, log=log)
    audio = record_manual(loud_frames(log), ctl, flush=lambda: log.append("flush"))
    # vor dem ersten Frame müssen wait_start und das Leeren des Puffers passiert sein
    assert log.index("start") < log.index("frame") and log.index("flush") < log.index("frame")
    assert "finish" in log
    assert len(audio) == 41 * FRAME - int(0.15 * RATE) - int(0.40 * RATE)


def test_manual_session_saves_and_supports_redo(tmp_path):
    out = tmp_path / "voice-data" / "clone"
    ctl = FakeController(stop_after=40, keeps=[False, True])
    msgs = []
    n = record_session(out, loud_frames(), say=msgs.append, paragraphs=["Eins."], root=tmp_path, controller=ctl)
    assert n == 1 and (out / "01.wav").exists() and any("verworfen" in m for m in msgs)
    with _wave.open(str(out / "01.wav")) as w:
        assert w.getframerate() == RATE and w.getnframes() > 2 * RATE


def test_manual_take_that_is_too_short_is_retried_not_saved(tmp_path):
    out = tmp_path / "c"
    ctl = FakeController(stop_after=3)                    # nur ein paar Frames, dann Enter
    msgs = []
    n = record_session(out, loud_frames(), say=msgs.append, paragraphs=["Eins."], root=tmp_path, controller=ctl)
    assert n == 0 and not (out / "01.wav").exists() and any("zu kurz" in m for m in msgs)


def test_manual_take_stops_at_maximum_length_and_waits_for_enter():
    log = []
    ctl = FakeController(stop_after=None, log=log)         # Nutzer drückt nie Enter
    audio = record_manual(loud_frames(), ctl, flush=lambda: None)
    assert log.count("finish") == 1
    assert 119 <= len(audio) / RATE <= 121


def test_enter_controller_reads_answers():
    answers = iter(["", "", "r", "", " R "])
    c = EnterController(ask=lambda prompt: next(answers), say=lambda m: None)
    c.wait_start()
    ev = c.stop_event()
    assert ev.wait(2)                                      # Thread hat das zweite Enter gelesen
    assert c.keep() is False and c.keep() is True and c.keep() is False
