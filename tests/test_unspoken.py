"""Vermerk „nicht gesprochen“ im Verlauf: Feld `unspoken` im Live-Transkript und die Zählung über `Speaker.on_unspoken`.

Nur eine Zahl je Eintrag, nur im Arbeitsspeicher; der bisherige Haken (Hinweis, talk.log) läuft unverändert weiter."""
import json
import re
import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from kushim.api.protocol import ApiCore, new_token
from kushim.api.transcript_api import register_transcript
from kushim.safety.killswitch import KillSwitch
from kushim.voice.dialog import Dialog
from kushim.voice.pipeline import Pipeline
from kushim.voice.transcript import MAX_UNSPOKEN, Transcript, track_unspoken
from kushim.voice.tts import Speaker

PCM = np.zeros(16000, dtype=np.int16)
SRC = Path(__file__).resolve().parents[1] / "src" / "kushim"


def turn(entry, reply="Zehn Uhr.", outcome="spoken", **extra):
    return SimpleNamespace(heard="wie spät", reply=reply, outcome=outcome, entry=entry, **extra)


# --- Feld im Transkript

def test_new_entries_start_with_zero_and_the_result_sets_the_count():
    t = Transcript()
    i = t.heard("Hey Kushim, wie spät", "wie spät")
    assert t.get(i)["unspoken"] == 0
    t.sent(i)
    t.add(turn(i, unspoken=2))
    e = t.get(i)
    assert (e["reply"], e["outcome"], e["unspoken"], e["rev"]) == ("Zehn Uhr.", "spoken", 2, 3)


def test_results_without_the_field_or_without_a_reply_stay_at_zero():
    t = Transcript()
    a = t.heard("a", "a")
    t.add(turn(a))                                                   # älteres Ergebnis ohne `unspoken`
    b = t.heard("b", "b")
    t.add(turn(b, reply="", outcome="halted", unspoken=3))           # keine Antwort: nichts blieb ungesprochen
    c = t.heard("c", "c")
    t.add(turn(c, reply="geheim", outcome="rejected_speaker", unspoken=1))   # abgelehnte Stimme: kein Text, kein Vermerk
    assert [t.get(x)["unspoken"] for x in (a, b, c)] == [0, 0, 0]


@pytest.mark.parametrize("bad", [True, False, -1, 1.5, "2", None, [1]])
def test_odd_counts_become_zero(bad):
    t = Transcript()
    i = t.heard("x", "x")
    t.add(turn(i, unspoken=bad))
    assert t.get(i)["unspoken"] == 0


def test_the_count_is_capped():
    t = Transcript()
    i = t.heard("x", "x")
    t.add(turn(i, unspoken=10 ** 12))
    assert t.get(i)["unspoken"] == MAX_UNSPOKEN


def test_entries_without_an_id_carry_the_count_too():
    t = Transcript()
    t.add(SimpleNamespace(heard="a", reply="b", outcome="spoken", unspoken=1))
    t.add(SimpleNamespace(heard="c", reply="d", outcome="command"))
    assert [e["unspoken"] for e in t.since(0)] == [1, 0]


def test_api_returns_the_field():
    token = new_token()
    core = ApiCore(token)
    t = Transcript()
    register_transcript(core, t)
    i = t.heard("x", "x")
    t.add(turn(i, unspoken=4))
    r = json.loads(core.handle(json.dumps({"token": token, "type": "transcript.get", "since": 0})))
    assert r["ok"] is True and r["entries"][0]["unspoken"] == 4


# --- Zählung je Runde

class FakeSpeaker:
    def __init__(self):
        self.notes = []
        self.on_unspoken = lambda text: self.notes.append(text)


def test_counts_unspoken_sentences_of_the_round_and_keeps_the_old_hook():
    spk = FakeSpeaker()
    rounds = [2, 0, 1]

    def handle(pcm):
        n = rounds.pop(0)
        for k in range(n):
            spk.on_unspoken(f"Satz {k}.")
        return SimpleNamespace(reply="x", outcome="spoken")
    run = track_unspoken(spk, handle)
    assert [run(PCM).unspoken for _ in range(3)] == [2, 0, 1]       # je Runde neu
    assert spk.notes == ["Satz 0.", "Satz 1.", "Satz 0."]           # bisheriger Hinweis unverändert, mit Text


def test_announcements_outside_the_round_are_not_counted():
    spk = FakeSpeaker()
    track_unspoken(spk, lambda pcm: SimpleNamespace())
    spk.on_unspoken("Meldung.")                                     # außerhalb einer Runde: kein Zähler, Hinweis bleibt
    assert spk.notes == ["Meldung."]


def test_other_threads_do_not_count_into_the_round():
    spk = FakeSpeaker()

    def handle(pcm):
        other = threading.Thread(target=lambda: spk.on_unspoken("Meldung aus der Schleife."))
        other.start()
        other.join()
        spk.on_unspoken("Satz der Runde.")
        return SimpleNamespace()
    r = track_unspoken(spk, handle)(PCM)
    assert r.unspoken == 1 and len(spk.notes) == 2


def test_errors_pass_through_and_the_next_round_starts_at_zero():
    spk = FakeSpeaker()
    calls = []

    def handle(pcm):
        spk.on_unspoken("a")
        if not calls:
            calls.append(1)
            raise RuntimeError("kaputt")
        return SimpleNamespace()
    run = track_unspoken(spk, handle)
    with pytest.raises(RuntimeError):
        run(PCM)
    assert run(PCM).unspoken == 1


def test_a_result_that_takes_no_attributes_is_returned_unchanged():
    spk = FakeSpeaker()
    assert track_unspoken(spk, lambda pcm: (1, 2))(PCM) == (1, 2)


# --- Mit echter Pipeline und echtem Speaker: die Stimme fällt aus, die Antwort kommt nur als Text

class BrokenVoice:
    def synthesize(self, text):
        raise RuntimeError("Stimme aus")


class Voice:
    def synthesize(self, text):
        return text


def build(tmp_path, engine, reply):
    played, shown = [], []
    kill = KillSwitch(tmp_path, [])
    spk = Speaker(engine, played.append, lambda: kill.fired)
    spk.on_unspoken = lambda text: shown.append(f"Ohne Stimme: {text}")     # wie build_live: Hinweis mit Text
    stt = SimpleNamespace(transcribe=lambda pcm: SimpleNamespace(text="Wie spät ist es"))
    p = Pipeline(stt, lambda msgs: iter([reply]), spk, Dialog(lambda: None), kill)
    p.notes = Transcript()
    return p, played, shown


def test_pipeline_marks_the_entry_when_the_voice_is_out(tmp_path):
    p, played, shown = build(tmp_path, BrokenVoice(), "Es ist zehn. Der Kaffee ist fertig.")
    r = track_unspoken(p.speaker, p.handle)(PCM)
    p.notes.add(r)
    e = p.notes.since(0)[0]
    assert (e["reply"], e["unspoken"]) == ("Es ist zehn. Der Kaffee ist fertig.", 2)
    assert played == [] and shown == ["Ohne Stimme: Es ist zehn.", "Ohne Stimme: Der Kaffee ist fertig."]


def test_pipeline_with_a_working_voice_has_no_mark(tmp_path):
    p, played, shown = build(tmp_path, Voice(), "Es ist zehn.")
    r = track_unspoken(p.speaker, p.handle)(PCM)
    p.notes.add(r)
    assert p.notes.since(0)[0]["unspoken"] == 0 and played and shown == []


def test_talk_log_gets_no_new_field(tmp_path):
    from kushim.voice.talklog import TalkLog
    p, _, _ = build(tmp_path, BrokenVoice(), "Es ist zehn.")
    log = TalkLog(tmp_path / "talk.log")
    track_unspoken(p.speaker, log.timed(p.handle))(PCM)
    line = json.loads((tmp_path / "talk.log").read_text(encoding="utf-8").splitlines()[-1])
    assert set(line) == {"ts", "event", "heard", "reply", "outcome", "detail", "seconds"}


def test_counting_never_touches_the_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import builtins
    import os
    opened = []
    real_open = builtins.open
    monkeypatch.setattr(builtins, "open", lambda *a, **k: opened.append(a) or real_open(*a, **k))
    monkeypatch.setattr(os, "replace", lambda *a, **k: opened.append(a))
    spk = FakeSpeaker()

    def handle(pcm):
        spk.on_unspoken("geheim")
        return SimpleNamespace(heard="x", reply="geheim", outcome="spoken", entry=None)
    t = Transcript()
    t.add(track_unspoken(spk, handle)(PCM))
    t.since(0)
    assert opened == [] and list(tmp_path.iterdir()) == []


# --- Verdrahtung in cli.py (talk.py und tts.py bleiben unberührt)

def test_cli_wraps_handle_after_the_talk_log():
    cli = (SRC / "cli.py").read_text(encoding="utf-8")
    timed = cli.index("pipeline.handle = talklog.timed(")
    tracked = cli.index("pipeline.handle = track_unspoken(pipeline.speaker, pipeline.handle)")
    assert timed < tracked                                          # außen: talk.log bekommt kein neues Feld
    assert len(re.findall(r"track_unspoken\(", cli)) == 1
