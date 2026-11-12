"""Gesprächsprotokoll (src/kushim/voice/talklog.py)."""
import json
from types import SimpleNamespace

import pytest

from kushim.voice import talklog as tl


def lines(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def test_results_are_written_with_text_outcome_detail_and_duration(tmp_path):
    log = tl.TalkLog(tmp_path / "run" / "talk.log")
    handle = log.timed(lambda pcm: SimpleNamespace(heard="Lass die Tests laufen", reply="Ich geb's an Claude.",
                                                   outcome="spoken", detail=""))
    log.write("wake")
    handle(b"\x00")
    rows = lines(tmp_path / "run" / "talk.log")
    assert [r["event"] for r in rows] == ["wake", "result"]
    assert rows[1]["heard"] == "Lass die Tests laufen" and rows[1]["outcome"] == "spoken" and rows[1]["seconds"] >= 0


def test_rejected_speaker_keeps_the_score_detail(tmp_path):
    log = tl.TalkLog(tmp_path / "talk.log")
    log.timed(lambda pcm: SimpleNamespace(heard="Hallo", reply="", outcome="rejected_speaker",
                                          detail="Ähnlichkeit 0.62 (Schwelle 0.79), 1.2 s"))(None)
    row = lines(tmp_path / "talk.log")[0]
    assert row["outcome"] == "rejected_speaker" and "0.62" in row["detail"]


def test_errors_are_logged_and_still_raised(tmp_path):
    log = tl.TalkLog(tmp_path / "talk.log")

    def boom(pcm):
        raise RuntimeError("CUDA weg")
    with pytest.raises(RuntimeError):
        log.timed(boom)(None)
    assert lines(tmp_path / "talk.log")[0] == {**lines(tmp_path / "talk.log")[0], "event": "error", "where": "pipeline"}


def test_text_is_one_line_and_bounded_and_rotation_keeps_one_old_file(tmp_path, monkeypatch):
    p = tmp_path / "talk.log"
    log = tl.TalkLog(p)
    log.write("note", text="a\nb\r\n" + "x" * 2000)
    row = lines(p)[0]
    assert "\n" not in row["text"] and len(row["text"]) <= tl.MAX_TEXT
    monkeypatch.setattr(tl, "MAX_BYTES", 10)
    log.write("note", text="neu")
    assert (tmp_path / "talk.log.1").exists() and lines(p)[0]["text"] == "neu"


def test_write_errors_never_break_anything(tmp_path):
    blocker = tmp_path / "datei"
    blocker.write_text("x")
    tl.TalkLog(blocker / "talk.log").write("note", text="geht nicht")         # Elternpfad ist eine Datei
