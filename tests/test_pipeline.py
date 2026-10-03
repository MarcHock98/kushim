from types import SimpleNamespace

import numpy as np

from kushim.safety.killswitch import KillSwitch
from kushim.voice.dialog import Dialog, State
from kushim.voice.pipeline import Pipeline
from kushim.voice.speaker import SpeakerVerifier
from kushim.voice.tts import Speaker
from kushim.voice.verify import AudioVerifier


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
    audio_verifier = AudioVerifier(verifier, embed) if verifier is not None else None
    p = Pipeline(FakeSTT(text), chat, spk, dialog, kill, audio_verifier)
    return p, played, dialog, kill


PCM = np.zeros(16000, dtype=np.int16)      # 1 s


def test_normal_turn(tmp_path):
    p, played, dialog, _ = build(tmp_path, "Wie spät ist es")
    r = p.handle(PCM)
    assert r.outcome == "spoken" and played == ["Hallo.", "Wie geht's?"]
    assert dialog.state is State.IDLE and p.history[0]["content"] == "Wie spät ist es"


def test_kill_phrase_skips_llm_and_halts(tmp_path):
    called = []
    p, played, dialog, kill = build(tmp_path, "Kushim Notaus", chat=lambda m: called.append(1) or iter([]))
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


def test_enrolled_but_embedder_gives_nothing_fails_closed(tmp_path):
    v = SpeakerVerifier()
    b = np.ones(8)
    v.enroll([b, b * 1.01, b * 0.99])
    p, played, _, _ = build(tmp_path, "Hallo", verifier=v, embed=lambda pcm: np.zeros(0))
    assert p.handle(PCM).outcome == "rejected_speaker" and not played


def test_too_short_utterance_is_rejected(tmp_path):
    v = SpeakerVerifier()
    base = np.random.default_rng(2).normal(size=32)
    v.enroll([base, base + 0.01, base - 0.01])
    p, played, _, _ = build(tmp_path, "Hallo", verifier=v, embed=lambda pcm: base)
    assert p.handle(np.zeros(4000, dtype=np.int16)).outcome == "rejected_speaker" and not played


def test_empty_transcript(tmp_path):
    p, played, _, _ = build(tmp_path, "")
    assert p.handle(PCM).outcome == "empty" and not played


def test_external_marker_blocks(tmp_path):
    from kushim.safety import killswitch
    p, played, _, _ = build(tmp_path, "Hallo")
    killswitch.trigger(tmp_path)
    assert p.handle(PCM).outcome == "halted" and not played


def test_history_is_bounded(tmp_path):
    seen = []
    p, *_ = build(tmp_path, "Hi", chat=lambda m: seen.append(len(m)) or iter(["Ok."]))
    for _ in range(10):
        p.handle(PCM)
    assert max(seen) <= 7   # System + 6


from kushim.voice.pipeline import strip_wake_words

NAMES = ("hey kushim", "kushim", "kush", "hallo kush", "hi kushim", "kushi")


def test_strip_wake_words():
    s = lambda t: strip_wake_words(t, NAMES)
    assert s("Hey Kushim, schau mir das nach.") == "schau mir das nach."
    assert s("Hey Kuschim schau mir das nach") == "schau mir das nach"        # Whisper schreibt es anders
    assert s("kushim") == "" and s("Hey Kushim.") == "" and s("Hallo Kush!") == ""
    assert s("Hey Kushim hey kushim wie spät ist es") == "wie spät ist es"      # höchstens zweimal
    assert s("Wie spät ist es, Kushim?") == "Wie spät ist es, Kushim?"          # nur am Anfang
    assert s("Kuss mich nicht") == "Kuss mich nicht"                            # ähnliches Wort ist kein Wake Word
    assert strip_wake_words("  Hallo  ", ()) == "Hallo"


def test_pipeline_strips_wake_word_before_llm_and_reports_wake_only(tmp_path):
    seen = []
    p, played, _, _ = build(tmp_path, "Hey Kushim, wie spät ist es?",
                            chat=lambda m: seen.append(m) or iter(["Es ist spät."]))
    p.wake_names = NAMES
    r = p.handle(PCM)
    assert r.outcome == "spoken" and p.history[0]["content"] == "wie spät ist es?"
    p2, played2, _, _ = build(tmp_path, "Hey Kushim.", chat=lambda m: seen.append("nie") or iter([]))
    p2.wake_names = NAMES
    r2 = p2.handle(PCM)
    assert r2.outcome == "wake_only" and r2.heard == "" and not played2 and "nie" not in seen


def test_kill_phrase_after_wake_word_still_kills(tmp_path):
    p, played, _, kill = build(tmp_path, "Hey Kushim, Notaus")
    p.wake_names = NAMES
    assert p.handle(PCM).outcome == "killed" and kill.fired
