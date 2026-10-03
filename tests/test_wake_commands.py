from types import SimpleNamespace

import numpy as np
import pytest

from kushim.safety.killswitch import KillSwitch
from kushim.voice import wakeconfig
from kushim.voice.dialog import Dialog
from kushim.voice.pipeline import Pipeline
from kushim.voice.speaker import SpeakerVerifier
from kushim.voice.tts import Speaker
from kushim.voice.wake_commands import WakeWordCommands, parse
from kushim.voice.wakeconfig import Settings, WakeConfig, WakeWord


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def make(tmp_path, words=("hey kushim",)):
    wakeconfig.save(tmp_path, WakeConfig(Settings(), tuple(WakeWord(w) for w in words)))
    clock = Clock()
    return WakeWordCommands(tmp_path, clock=clock), clock


def names(tmp_path):
    return [w.name for w in wakeconfig.load(tmp_path).enabled()]


@pytest.mark.parametrize("text,action,word", [
    ("Füge das Wake Word Alexa hinzu", "add", "alexa"),
    ("Bitte aktiviere als Wake Word hey Mycroft", "add", "hey_mycroft"),
    ("Entferne das Wake Word Jarvis", "remove", "hey_jarvis"),
    ("Lösche das Weckwort Timer", "remove", "timer"),
    ("Welche Wake Words sind aktiv", "list", None),
])
def test_parse_known_words(text, action, word):
    p = parse(text)
    assert p is not None and p.action == action and p.word == word


def test_parse_free_phrase():
    p = parse("Füge das Wake Word hallo Kushim hinzu")
    assert p.action == "add" and p.word is None and p.unknown == "hallo kushim"


@pytest.mark.parametrize("text", ["Wie wird das Wetter", "Spiel Musik", "Füge Milch zur Einkaufsliste hinzu", ""])
def test_normal_speech_is_not_a_command(text):
    assert parse(text) is None


def test_unverified_speaker_is_refused(tmp_path):
    cmds, _ = make(tmp_path)
    assert "deine Stimme" in cmds.handle("Füge das Wake Word Alexa hinzu", verified=False)
    assert names(tmp_path) == ["hey kushim"]


def test_add_known_word_needs_confirmation_and_writes_central_file(tmp_path):
    cmds, _ = make(tmp_path)
    q = cmds.handle("Füge das Wake Word Alexa hinzu", verified=True)
    assert "Alexa hinzufügen" in q and names(tmp_path) == ["hey kushim"]      # noch nichts geändert
    assert "Erledigt" in cmds.handle("Ja", verified=True)
    cfg = wakeconfig.load(tmp_path)
    assert [(w.name, w.engine) for w in cfg.enabled()] == [("hey kushim", "kws"), ("alexa", "openwakeword")]
    assert (tmp_path / "wakewords.toml").is_file()


def test_add_free_phrase_as_kws(tmp_path):
    cmds, _ = make(tmp_path)
    cmds.handle("Füge das Wake Word Computer hinzu", verified=True)
    cmds.handle("Ja", verified=True)
    assert [(w.name, w.engine) for w in wakeconfig.load(tmp_path).words][-1] == ("computer", "kws")


@pytest.mark.parametrize("phrase", ["ab", "eins zwei drei vier fünf sechs"])
def test_too_short_or_too_long_phrase_is_not_stored(tmp_path, phrase):
    cmds, _ = make(tmp_path)
    answer = cmds.handle(f"Füge das Wake Word {phrase} hinzu", verified=True)
    assert "Welches Wort" in answer
    assert cmds.handle("Ja", verified=True) is None                    # es wartet nichts auf Bestätigung
    assert names(tmp_path) == ["hey kushim"]


@pytest.mark.parametrize("reply", ["Nein", "Vielleicht", "Wie spät ist es"])
def test_no_or_other_answer_cancels(tmp_path, reply):
    cmds, _ = make(tmp_path)
    cmds.handle("Füge das Wake Word Alexa hinzu", verified=True)
    assert "Abgebrochen" in cmds.handle(reply, verified=True)
    assert names(tmp_path) == ["hey kushim"]


def test_confirmation_by_other_voice_is_refused(tmp_path):
    cmds, _ = make(tmp_path)
    cmds.handle("Füge das Wake Word Alexa hinzu", verified=True)
    assert "Abgebrochen" in cmds.handle("Ja", verified=False)
    assert names(tmp_path) == ["hey kushim"]


def test_confirmation_expires(tmp_path):
    cmds, clock = make(tmp_path)
    cmds.handle("Füge das Wake Word Alexa hinzu", verified=True)
    clock.t = 61
    assert "abgelaufen" in cmds.handle("Ja", verified=True)
    assert names(tmp_path) == ["hey kushim"]


def test_last_wake_word_cannot_be_removed(tmp_path):
    cmds, _ = make(tmp_path, ["hey kushim"])
    assert "einzige" in cmds.handle("Entferne das Wake Word hey Kushim", verified=True)
    assert names(tmp_path) == ["hey kushim"]


def test_remove_one_of_two(tmp_path):
    cmds, _ = make(tmp_path, ["hey kushim", "kushim"])
    cmds.handle("Entferne das Wake Word hey Kushim", verified=True)
    cmds.handle("Ja", verified=True)
    assert names(tmp_path) == ["kushim"]


def test_duplicate_missing_and_list(tmp_path):
    cmds, _ = make(tmp_path, ["hey kushim", "kushim"])
    assert "schon aktiv" in cmds.handle("Füge das Wake Word hey Kushim hinzu", verified=True)
    assert "gar nicht aktiv" in cmds.handle("Entferne das Wake Word Timer", verified=True)
    assert "hey kushim" in cmds.handle("Welche Wake Words sind aktiv", verified=True)


def test_broken_config_file_is_reported(tmp_path):
    (tmp_path / "wakewords.toml").write_text("das ist [kein toml", encoding="utf-8")
    cmds = WakeWordCommands(tmp_path)
    assert "fehlerhaft" in cmds.handle("Welche Wake Words sind aktiv", verified=True)


# --- Integration in die Pipeline ------------------------------------------------------------

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
    cmds, _ = make(tmp_path)
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
