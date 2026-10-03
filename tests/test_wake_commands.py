from types import SimpleNamespace

import numpy as np
import pytest

from kushim.config import Config
from kushim.memory import open_store
from kushim.safety.killswitch import KillSwitch
from kushim.voice import wakewords_store
from kushim.voice.dialog import Dialog
from kushim.voice.pipeline import Pipeline
from kushim.voice.speaker import SpeakerVerifier
from kushim.voice.tts import Speaker
from kushim.voice.wake_commands import WakeWordCommands, parse


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def make(words=("hey_jarvis",)):
    state = {"words": list(words)}
    saved = []
    clock = Clock()
    cmds = WakeWordCommands(lambda: list(state["words"]),
                            lambda new: (state.__setitem__("words", list(new)), saved.append(list(new))),
                            clock=clock)
    return cmds, state, saved, clock


@pytest.mark.parametrize("text,action,word", [
    ("Füge das Wake Word Alexa hinzu", "add", "alexa"),
    ("Bitte aktiviere als Wake Word hey Mycroft", "add", "hey_mycroft"),
    ("Entferne das Wake Word Jarvis", "remove", "hey_jarvis"),
    ("Lösche das Weckwort Timer", "remove", "timer"),
    ("Welche Wake Words sind aktiv", "list", None),
])
def test_parse(text, action, word):
    p = parse(text)
    assert p is not None and p.action == action and p.word == word


@pytest.mark.parametrize("text", ["Wie wird das Wetter", "Spiel Musik", "Füge Milch zur Einkaufsliste hinzu", ""])
def test_normal_speech_is_not_a_command(text):
    assert parse(text) is None


def test_unknown_word_needs_training_and_is_never_added():
    cmds, state, saved, _ = make()
    answer = cmds.handle("Füge das Wake Word Computer hinzu", verified=True)
    assert "noch nicht" in answer and "computer" in answer.lower()
    assert saved == [] and state["words"] == ["hey_jarvis"]


def test_unverified_speaker_is_refused():
    cmds, _, saved, _ = make()
    assert "deine Stimme" in cmds.handle("Füge das Wake Word Alexa hinzu", verified=False)
    assert saved == []


def test_add_needs_voice_confirmation():
    cmds, state, saved, _ = make()
    q = cmds.handle("Füge das Wake Word Alexa hinzu", verified=True)
    assert "Alexa hinzufügen" in q and saved == []             # noch nichts geändert
    assert "Erledigt" in cmds.handle("Ja", verified=True)
    assert saved == [["hey_jarvis", "alexa"]]


def test_no_or_other_answer_cancels():
    for reply in ("Nein", "Vielleicht", "Wie spät ist es"):
        cmds, _, saved, _ = make()
        cmds.handle("Füge das Wake Word Alexa hinzu", verified=True)
        assert "Abgebrochen" in cmds.handle(reply, verified=True)
        assert saved == []


def test_confirmation_by_other_voice_is_refused():
    cmds, _, saved, _ = make()
    cmds.handle("Füge das Wake Word Alexa hinzu", verified=True)
    assert "Abgebrochen" in cmds.handle("Ja", verified=False)
    assert saved == []


def test_confirmation_expires():
    cmds, _, saved, clock = make()
    cmds.handle("Füge das Wake Word Alexa hinzu", verified=True)
    clock.t = 61
    assert "abgelaufen" in cmds.handle("Ja", verified=True)
    assert saved == []


def test_last_wake_word_cannot_be_removed():
    cmds, _, saved, _ = make(["hey_jarvis"])
    assert "einzige" in cmds.handle("Entferne das Wake Word Jarvis", verified=True)
    assert saved == []


def test_remove_one_of_two():
    cmds, _, saved, _ = make(["hey_jarvis", "alexa"])
    cmds.handle("Entferne das Wake Word Alexa", verified=True)
    cmds.handle("Ja", verified=True)
    assert saved == [["hey_jarvis"]]


def test_duplicate_and_missing_and_list():
    cmds, _, _, _ = make(["hey_jarvis", "alexa"])
    assert "schon aktiv" in cmds.handle("Füge das Wake Word Alexa hinzu", verified=True)
    assert "gar nicht aktiv" in cmds.handle("Entferne das Wake Word Timer", verified=True)
    assert "hey Jarvis" in cmds.handle("Welche Wake Words sind aktiv", verified=True)


def test_store_roundtrip_and_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("KUSHIM_VAULT_KEY", "ab" * 32)
    cfg = Config(path=tmp_path / "c.toml", memory_location=f"local:{tmp_path / 'v'}")
    with open_store(cfg, create=True) as s:
        assert wakewords_store.load(s, tmp_path) is None
        wakewords_store.save(s, ["hey_jarvis", "alexa"], tmp_path)
        assert wakewords_store.load(s, tmp_path) == ["hey_jarvis", "alexa"]
        with pytest.raises(ValueError):
            wakewords_store.save(s, ["../evil.onnx"], tmp_path)
        s.set_profile(wakewords_store.KEY, '["unbekannt"]')
        assert wakewords_store.load(s, tmp_path) is None


# --- Integration in die Pipeline -------------------------------------------------------------

class FakeSTT:
    def __init__(self, text):
        self.text = text

    def transcribe(self, pcm):
        return SimpleNamespace(text=self.text)


class Eng:
    def synthesize(self, t):
        return t


def pipeline(tmp_path, text, verified):
    said, llm_calls = [], []
    base = np.random.default_rng(0).normal(size=32)
    v = SpeakerVerifier()
    v.enroll([base, base + 0.01, base - 0.01])
    cmds, *_ = make()
    kill = KillSwitch(tmp_path, [])
    p = Pipeline(FakeSTT(text), lambda m: llm_calls.append(1) or iter(["x."]),
                 Speaker(Eng(), said.append), Dialog(), kill, v,
                 (lambda pcm: base) if verified else (lambda pcm: -base), commands=cmds)
    return p, said, llm_calls


def test_pipeline_answers_command_without_llm(tmp_path):
    p, said, llm = pipeline(tmp_path, "Füge das Wake Word Alexa hinzu", verified=True)
    r = p.handle(np.zeros(16000, dtype=np.int16))
    assert r.outcome == "command" and "Alexa" in said[0] and not llm


def test_pipeline_command_from_stranger_is_rejected_before_commands(tmp_path):
    p, said, llm = pipeline(tmp_path, "Füge das Wake Word Alexa hinzu", verified=False)
    assert p.handle(np.zeros(16000, dtype=np.int16)).outcome == "rejected_speaker"
    assert not said and not llm


def test_pipeline_normal_question_still_goes_to_llm(tmp_path):
    p, said, llm = pipeline(tmp_path, "Wie spät ist es", verified=True)
    assert p.handle(np.zeros(16000, dtype=np.int16)).outcome == "spoken" and llm
