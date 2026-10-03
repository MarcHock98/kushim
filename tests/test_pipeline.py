from types import SimpleNamespace

import numpy as np

from kushima.safety.killswitch import KillSwitch
from kushima.voice.dialog import Dialog, State
from kushima.voice.pipeline import Pipeline
from kushima.voice.speaker import SpeakerVerifier
from kushima.voice.tts import Speaker


class FakeSTT:
    def __init__(self, text):
        self.text = text

    def transcribe(self, pcm):
        return SimpleNamespace(text=self.text)


class Eng:
    def synthesize(self, t):
        return t


def build(tmp_path, text, chat=None, verifier=None, embed=None):
    played, stopped = [], []
    dialog = Dialog(lambda: stopped.append(1))
    kill = KillSwitch(tmp_path, [lambda: stopped.append("kill")])
    chat = chat or (lambda msgs: iter(["Hall", "o. Wie ", "geht's?"]))
    spk = Speaker(Eng(), played.append, lambda: kill.fired)
    p = Pipeline(FakeSTT(text), chat, spk, dialog, kill, verifier, embed)
    return p, played, dialog, kill


PCM = np.zeros(1600, dtype=np.int16)


def test_normal_turn(tmp_path):
    p, played, dialog, _ = build(tmp_path, "Wie spät ist es")
    r = p.handle(PCM)
    assert r.outcome == "spoken" and played == ["Hallo.", "Wie geht's?"]
    assert dialog.state is State.IDLE and p.history[0]["content"] == "Wie spät ist es"


def test_kill_phrase_skips_llm_and_halts(tmp_path):
    called = []
    p, played, dialog, kill = build(tmp_path, "Kushima Notaus", chat=lambda m: called.append(1) or iter([]))
    r = p.handle(PCM)
    assert r.outcome == "killed" and not called and not played
    assert kill.fired and dialog.state is State.HALTED
    assert p.handle(PCM).outcome == "halted"


def test_kill_works_even_for_unknown_speaker(tmp_path):
    v = SpeakerVerifier()
    base = np.random.default_rng(0).normal(size=32)
    v.enroll([base + 0.01, base - 0.01, base])
    p, _, _, kill = build(tmp_path, "stopp alles", verifier=v, embed=lambda pcm: -base)
    assert p.handle(PCM).outcome == "killed" and kill.fired


def test_unknown_speaker_gets_no_answer(tmp_path):
    v = SpeakerVerifier()
    base = np.random.default_rng(1).normal(size=32)
    v.enroll([base, base + 0.01, base - 0.01])
    called = []
    p, played, _, _ = build(tmp_path, "Hallo", chat=lambda m: called.append(1) or iter(["x."]),
                            verifier=v, embed=lambda pcm: -base)
    assert p.handle(PCM).outcome == "rejected_speaker" and not called and not played


def test_enrolled_but_no_embedder_fails_closed(tmp_path):
    v = SpeakerVerifier()
    b = np.ones(8)
    v.enroll([b, b * 1.01, b * 0.99])
    p, played, _, _ = build(tmp_path, "Hallo", verifier=v, embed=None)
    assert p.handle(PCM).outcome == "rejected_speaker" and not played


def test_empty_transcript(tmp_path):
    p, played, _, _ = build(tmp_path, "")
    assert p.handle(PCM).outcome == "empty" and not played


def test_external_marker_blocks(tmp_path):
    from kushima.safety import killswitch
    p, played, _, _ = build(tmp_path, "Hallo")
    killswitch.trigger(tmp_path)
    assert p.handle(PCM).outcome == "halted" and not played


def test_history_is_bounded(tmp_path):
    seen = []
    p, *_ = build(tmp_path, "Hi", chat=lambda m: seen.append(len(m)) or iter(["Ok."]))
    for _ in range(10):
        p.handle(PCM)
    assert max(seen) <= 7   # System + 6
