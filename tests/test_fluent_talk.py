import threading
import time
from types import SimpleNamespace

import numpy as np

from kushim.safety.killswitch import KillSwitch
from kushim.voice.audio import FRAME, UtteranceCollector
from kushim.voice.bargein import BargeIn
from kushim.voice.dialog import Dialog
from kushim.voice.pipeline import Pipeline
from kushim.voice.talk import TalkLoop
from kushim.voice.tts import Speaker

LOUD = (np.ones(FRAME) * 3000).astype(np.int16)
QUIET = np.zeros(FRAME, dtype=np.int16)


def collector():
    return UtteranceCollector(silence_ms=160, min_ms=80)       # 2 stille Frames beenden


def follow():
    return UtteranceCollector(wait_ms=240, silence_ms=160, min_ms=80)   # 3 Frames Wartezeit


def fires_at(*indexes):
    n = {"i": -1}

    def wake(frame):
        n["i"] += 1
        return n["i"] in indexes
    return wake


class Fake:
    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    def handle(self, pcm):
        self.calls += 1
        return SimpleNamespace(heard="x", reply="y", outcome=self.outcomes.pop(0))


# --- Gespräch ohne Wake Word --------------------------------------------------------------------

def test_follow_up_needs_no_wake_word_and_ends_on_silence(tmp_path):
    p, shown = Fake(["spoken", "spoken"]), []
    frames = [LOUD, LOUD, QUIET, QUIET,          # Frage 1 nach dem Wake Word
              LOUD, LOUD, QUIET, QUIET,          # Frage 2 OHNE Wake Word
              QUIET, QUIET, QUIET,               # Stille: Gespräch endet
              LOUD, LOUD, QUIET, QUIET]          # wieder ohne Wake Word: wird ignoriert
    loop = TalkLoop(frames, p, KillSwitch(tmp_path, []), wake=fires_at(0), new_collector=collector,
                    follow_collector=follow, on_result=lambda r: shown.append(r.outcome))
    assert loop.run() == "ended"
    assert p.calls == 2 and shown == ["spoken", "spoken"]


def test_without_follow_up_the_wake_word_is_needed_every_time(tmp_path):
    p = Fake(["spoken"])
    frames = [LOUD, LOUD, QUIET, QUIET, LOUD, LOUD, QUIET, QUIET]
    TalkLoop(frames, p, KillSwitch(tmp_path, []), wake=fires_at(0), new_collector=collector).run()
    assert p.calls == 1


def test_end_conversation_and_rejected_speaker_do_not_continue(tmp_path):
    for outcome in ("end_conversation", "rejected_speaker", "empty", "halted"):
        p = Fake([outcome])
        frames = [LOUD, LOUD, QUIET, QUIET, LOUD, LOUD, QUIET, QUIET]
        TalkLoop(frames, p, KillSwitch(tmp_path, []), wake=fires_at(0), new_collector=collector,
                 follow_collector=follow).run()
        assert p.calls == 1, outcome


def test_follow_up_flushes_the_mic_so_kushim_does_not_hear_itself(tmp_path):
    p, events = Fake(["spoken"]), []
    frames = [LOUD, LOUD, QUIET, QUIET, QUIET, QUIET, QUIET]
    TalkLoop(frames, p, KillSwitch(tmp_path, []), wake=fires_at(0), first_collector=collector, new_collector=collector,
             follow_collector=follow, flush=lambda: events.append("flush")).run()
    assert events == ["flush"]            # ohne "Ja?" nur das eine Verwerfen vor dem Zuhören im Gespräch


# --- Unterbrechen --------------------------------------------------------------------------------

class SlowPipeline:
    """Antwort läuft, bis interrupt() kommt (wie TTS, das gerade spricht)."""

    def __init__(self):
        self.calls, self.interrupts, self.started = [], 0, threading.Event()
        self._stop = threading.Event()

    def interrupt(self):
        self.interrupts += 1
        self._stop.set()

    def handle(self, pcm):
        self.calls.append(len(pcm))
        if len(self.calls) == 1:
            self.started.set()
            interrupted = self._stop.wait(timeout=5)
            return SimpleNamespace(heard="a", reply="lange Antwort", outcome="interrupted" if interrupted else "spoken")
        return SimpleNamespace(heard="b", reply="neue Antwort", outcome="spoken")


class Paced:
    """Frames, bei denen vor Frame 4 gewartet wird, bis die Antwort läuft (wie ein echtes Mikrofon)."""

    def __init__(self, frames, started):
        self.frames, self.started = frames, started

    def __iter__(self):
        for i, f in enumerate(self.frames):
            if i == 4:
                assert self.started.wait(timeout=5)
            time.sleep(0.002)
            yield f


def test_speaking_over_kushim_interrupts_and_becomes_the_next_question(tmp_path):
    p, shown = SlowPipeline(), []
    frames = [LOUD, LOUD, QUIET, QUIET,                  # Frage 1 (Wake Word bei 0)
              QUIET, QUIET,                              # Antwort läuft
              LOUD, LOUD, LOUD, LOUD, QUIET, QUIET,      # Nutzer spricht dazwischen
              QUIET, QUIET, QUIET, QUIET]
    loop = TalkLoop(Paced(frames, p.started), p, KillSwitch(tmp_path, []), wake=fires_at(0), new_collector=collector,
                    follow_collector=follow, barge=BargeIn(level=1200, min_ms=240, frame_ms=80),
                    on_result=lambda r: shown.append(r.outcome))
    assert loop.run() == "ended"
    assert p.interrupts == 1
    assert shown == ["interrupted", "spoken"]
    assert len(p.calls) == 2 and p.calls[1] >= 3 * FRAME      # der Anfang des Einwurfs ging nicht verloren


def test_quiet_audio_does_not_interrupt(tmp_path):
    p = SlowPipeline()
    p._stop.set()                                    # Antwort endet sofort, ohne dass jemand unterbricht
    frames = [LOUD, LOUD, QUIET, QUIET] + [QUIET] * 6
    loop = TalkLoop(Paced(frames, p.started), p, KillSwitch(tmp_path, []), wake=fires_at(0), new_collector=collector,
                    barge=BargeIn(level=1200, min_ms=240, frame_ms=80))
    loop.run()
    assert p.interrupts == 0


def test_kill_switch_interrupts_a_running_answer(tmp_path):
    from kushim.safety import killswitch
    k = KillSwitch(tmp_path, [])
    p = SlowPipeline()

    class Frames(Paced):
        def __iter__(self):
            for i, f in enumerate(self.frames):
                if i == 4:
                    assert self.started.wait(timeout=5)
                    killswitch.trigger(tmp_path)
                yield f
    loop = TalkLoop(Frames([LOUD, LOUD, QUIET, QUIET, QUIET, QUIET, QUIET], p.started), p, k, wake=fires_at(0),
                    new_collector=collector, barge=BargeIn())
    assert loop.run() == "killed" and p.interrupts == 1


# --- BargeIn -------------------------------------------------------------------------------------

def test_barge_in_needs_sustained_loudness_and_keeps_the_start():
    b = BargeIn(level=1200, min_ms=240, frame_ms=80, preroll_ms=160)
    assert not b.feed(LOUD) and not b.feed(LOUD) and b.feed(LOUD)
    assert len(b.recent()) == 3
    b.reset()
    # ein einzelner Klick (ein lauter Frame) reicht nicht, auch nicht mit kurzen Pausen dazwischen
    assert not b.feed(LOUD) and not b.feed(QUIET) and not b.feed(QUIET) and not b.feed(LOUD)


# --- Pipeline: Unterbrechen und Gesprächsende ----------------------------------------------------

class Eng:
    def synthesize(self, t):
        return t


def make_pipeline(tmp_path, text, chat, played, block=None):
    stopped = []
    dialog = Dialog(lambda: stopped.append(1))
    kill = KillSwitch(tmp_path, [])

    def play(w):
        played.append(w)
        if block is not None:
            block()
    spk = Speaker(Eng(), play, lambda: kill.fired)
    stt = SimpleNamespace(transcribe=lambda pcm: SimpleNamespace(text=text))
    return Pipeline(stt, chat, spk, dialog, kill, None), stopped


PCM = np.zeros(16000, dtype=np.int16)


def test_interrupt_stops_remaining_sentences(tmp_path):
    played, holder = [], {}
    chat = lambda m: iter(["Satz eins. ", "Satz zwei. ", "Satz drei."])
    p, stopped = make_pipeline(tmp_path, "Erzähl mir was", chat, played,
                               block=lambda: holder["p"].interrupt() if len(played) == 1 else None)
    holder["p"] = p
    r = p.handle(PCM)
    assert r.outcome == "interrupted" and played == ["Satz eins."]


def test_interrupt_flag_is_cleared_for_the_next_turn(tmp_path):
    played = []
    p, _ = make_pipeline(tmp_path, "Hallo", lambda m: iter(["Hi."]), played)
    p.interrupt()
    r = p.handle(PCM)
    assert r.outcome == "spoken" and played == ["Hi."]


def test_end_phrase_ends_conversation_without_llm(tmp_path):
    called, played = [], []
    for text in ("Das war's.", "Danke, das war's!", "Tschüss", "Bis später."):
        p, _ = make_pipeline(tmp_path, text, lambda m: called.append(1) or iter([]), played)
        r = p.handle(PCM)
        assert r.outcome == "end_conversation" and r.reply == "Bis gleich."
    assert not called
    p, _ = make_pipeline(tmp_path, "Das war's nicht, erzähl weiter", lambda m: iter(["Okay."]), played)
    assert p.handle(PCM).outcome == "spoken"
