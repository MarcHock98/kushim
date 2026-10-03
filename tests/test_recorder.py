import wave

import numpy as np

from kushima.voice import recorder
from kushima.voice.recorder import FRAME, RATE, check_take, load_paragraphs, record_session

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
