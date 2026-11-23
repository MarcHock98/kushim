"""Gesprächsfluss mit Claude als kushims Gehirn: Anzeige-Zustand beim Warten, Füllwort und Antwort (Live-Test 2026-11-23).

Fehler damals: Das Fenster zeigte "ich spreche", obwohl nichts zu hören war. Ursache: Die Pipeline setzte SPEAKING
(`reply_ready`) vor dem Warten auf die erste `sprich`-Antwort. Jetzt gilt SPEAKING nur, solange wirklich Ton läuft.
"""
import threading
from types import SimpleNamespace

import numpy as np

from kushim.safety.killswitch import KillSwitch
from kushim.tasks import TaskRegistry
from kushim.voice import claude_chat as cc
from kushim.voice import statefile
from kushim.voice.dialog import Dialog, State
from kushim.voice.pipeline import Pipeline
from kushim.voice.tts import Speaker

PCM = np.zeros(16000, dtype=np.int16)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Eng:
    def synthesize(self, text):
        return text


def build(tmp_path, fetch_script):
    """Echte Pipeline, echter ClaudeChat, echter Dialog und echte Zustandsdatei; nur Brücke, Stimme und Uhr sind Attrappen."""
    clock = Clock()
    changes, during_play, during_fetch = [], [], []
    publisher = statefile.StatePublisher(tmp_path)
    back_to_thinking = threading.Event()

    def on_change(state):
        changes.append(state)
        publisher.phase(state.value)
        if state is State.THINKING and State.SPEAKING in changes:
            back_to_thinking.set()
    dialog = Dialog(on_change=on_change)
    kill = KillSwitch(tmp_path, [])

    def play(wav):
        during_play.append((wav, dialog.state, statefile.read(tmp_path)["state"]))

    speaker = Speaker(Eng(), play, lambda: kill.fired)
    calls = {"n": 0}

    class Bridge:
        last_final = True

        def send(self, text):
            return "ok"

        def cancel(self):
            return "ok"

        def pending(self):
            return []

        def available(self):
            return True

        def fetch(self, wait=0.0):
            calls["n"] += 1
            step = fetch_script(calls["n"], back_to_thinking)
            during_fetch.append((calls["n"], dialog.state, statefile.read(tmp_path)["state"]))
            clock.t += wait
            return "ok", step

    chat = cc.ClaudeChat(Bridge(), TaskRegistry(), clock=clock)
    stt = SimpleNamespace(transcribe=lambda pcm: SimpleNamespace(text="Wie wird das Wetter morgen?"))
    pipeline = Pipeline(stt, chat, speaker, dialog, kill)
    return pipeline, changes, during_play, during_fetch


def test_waiting_is_thinking_filler_and_reply_are_speaking_and_the_end_is_idle(tmp_path):
    def script(n, back_to_thinking):
        if n == 3:                                     # erst nach dem Füllwort antwortet Claude
            assert back_to_thinking.wait(5)            # Füllwort ist zu Ende gespielt: wieder "denkt"
            return ["Morgen wird es sonnig."]
        return []

    pipeline, changes, during_play, during_fetch = build(tmp_path, script)
    r = pipeline.handle(PCM)
    assert r.outcome == "spoken" and r.reply == f"{cc.FILLERS[0]} Morgen wird es sonnig."
    # warten -> denkt; Füllwort -> spricht; wieder warten -> denkt; Antwort -> spricht; fertig -> Leerlauf
    assert changes == [State.LISTENING, State.THINKING, State.SPEAKING, State.THINKING, State.SPEAKING, State.THINKING,
                       State.IDLE]
    assert [(n, s) for n, s, _ in during_fetch] == [(1, State.THINKING), (2, State.THINKING), (3, State.THINKING)]
    assert all(shown == "thinking" for _, _, shown in during_fetch)        # so steht es auch in voice-state.json
    assert during_play == [(cc.FILLERS[0], State.SPEAKING, "speaking"), ("Morgen wird es sonnig.", State.SPEAKING, "speaking")]
    assert statefile.read(tmp_path)["state"] == "idle"


def test_a_quick_reply_never_shows_speaking_before_the_audio(tmp_path):
    pipeline, changes, during_play, during_fetch = build(tmp_path, lambda n, ev: ["Hallo! Schön, dass du da bist."])
    assert pipeline.handle(PCM).outcome == "spoken"
    assert during_fetch[0][1] is State.THINKING and during_fetch[0][2] == "thinking"
    assert [w for w, *_ in during_play] == ["Hallo!", "Schön, dass du da bist."]
    assert all(s is State.SPEAKING for _, s, _ in during_play)
    assert changes[:2] == [State.LISTENING, State.THINKING] and changes[-1] is State.IDLE
    assert changes.count(State.SPEAKING) == 2                               # je Satz, dazwischen kurz wieder "denkt"


def test_interrupt_while_waiting_goes_to_listening_and_plays_nothing(tmp_path):
    holder = {}

    def script(n, ev):
        if n == 1:
            holder["p"].interrupt()                    # Nutzer spricht, während kushim noch wartet
        return []

    pipeline, changes, during_play, _ = build(tmp_path, script)
    holder["p"] = pipeline
    r = pipeline.handle(PCM)
    assert r.outcome == "interrupted" and during_play == [] and State.SPEAKING not in changes
    assert pipeline.dialog.state is State.LISTENING


def test_dialog_playing_and_played_restore_the_previous_state_and_respect_halt():
    d = Dialog()
    d.triggered(); d.utterance_done()
    prev = d.playing()
    assert prev is State.THINKING and d.state is State.SPEAKING
    d.played(prev)
    assert d.state is State.THINKING
    prev = d.playing()
    d.triggered()                                      # Unterbrechen während der Wiedergabe
    d.played(prev)
    assert d.state is State.LISTENING                  # bleibt beim Zuhören, nicht zurück zu "denkt"
    d.halt()
    assert d.playing() is None and d.state is State.HALTED
    d.played(None)
    assert d.state is State.HALTED
    assert not d.reply_done()                          # Notaus bleibt
