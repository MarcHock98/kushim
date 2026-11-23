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


def level(rms):
    return (np.ones(FRAME) * rms).astype(np.int16)


def frames_until_fire(b, frames, speaking):
    for i, f in enumerate(frames):
        if b.feed(f, speaking=speaking[i] if isinstance(speaking, list) else speaking):
            return i
    return None


NOTAUS_FRAMES = 7                                             # ein klar gesprochenes „Notaus“: 560 ms


def defaults_barge():
    from kushim.voice import wakeconfig as wc
    s = wc.Settings()
    return BargeIn(level=s.barge_in_level, min_ms=s.barge_in_ms, echo_guard=s.echo_schutz, echo_factor=s.echo_factor,
                   echo_ignore_ms=s.echo_ignore_ms)


def test_defaults_a_spoken_notaus_during_playback_always_interrupts():
    """Safety-Audit 2026-11-23: Mit den Standardwerten darf kein gesprochener Notaus verschluckt werden."""
    from kushim.voice import wakeconfig as wc
    s = wc.Settings()
    assert s.barge_in_ms == 240 and s.echo_schutz is False                     # empfindlich, ohne Echo-Schutz
    for lvl in (s.barge_in_level * 1.6, 400, 1500, 4000):
        for before in range(0, 12):                                            # mitten im Satz, am Satzanfang, gleich zu Beginn
            b = defaults_barge()
            b.reset()
            frames = [QUIET] * before + [level(lvl)] * NOTAUS_FRAMES
            speaking = [True] * len(frames)
            assert frames_until_fire(b, frames, speaking) is not None, (lvl, before)
    # am Anfang eines neuen Satzes (kurze Pause davor) und während des Füllworts „Moment.“ (etwa 640 ms)
    b = defaults_barge()
    speaking = [True] * 4 + [False] * 2 + [True] * NOTAUS_FRAMES
    assert frames_until_fire(b, [QUIET] * 6 + [level(1500)] * NOTAUS_FRAMES, speaking) is not None
    b = defaults_barge()
    assert frames_until_fire(b, [level(400)] * 8, [True] * 8) is not None


def test_echo_guard_is_opt_in_and_still_lets_a_loud_notaus_through():
    from kushim.voice import bargein
    on = lambda: BargeIn(level=250, min_ms=240, echo_guard=True, echo_factor=2.0, echo_ignore_ms=400)
    ignore = round(400 / 80)
    # Echo über Lautsprecher knapp über barge_in_level: mit Echo-Schutz still, ohne würde es unterbrechen
    echo = [level(400)] * 20
    assert frames_until_fire(on(), echo, True) is None
    assert frames_until_fire(BargeIn(level=250, min_ms=240), echo, True) == 2
    # ein Notaus über echo_factor × barge_in_level greift überall nach der einen Sperrzeit am Anfang der Runde
    for before in range(ignore, ignore + 12):
        b = on()
        frames = [QUIET] * before + [level(600)] * NOTAUS_FRAMES
        assert frames_until_fire(b, frames, [True] * len(frames)) is not None, before
    assert bargein.ECHO_FACTOR == 2.0 and bargein.ECHO_IGNORE_MS == 400


def test_echo_guard_ignore_window_does_not_restart_at_every_sentence():
    b = BargeIn(level=250, min_ms=240, echo_guard=True, echo_factor=2.0, echo_ignore_ms=400, echo_tail_ms=0)
    # Satz 1 (8 Frames), Pause (Synthese), Satz 2 beginnt mit einem Notaus: keine neue Sperrzeit, er greift sofort
    speaking = [True] * 8 + [False] * 2 + [True] * NOTAUS_FRAMES
    frames = [QUIET] * 10 + [level(600)] * NOTAUS_FRAMES
    assert frames_until_fire(b, frames, speaking) == 10 + 2
    b.reset()                                                                  # neue Runde: die Sperrzeit gilt wieder einmal
    assert frames_until_fire(b, [level(600)] * 8, [True] * 8) == 5 + 2


def test_echo_guard_tail_after_playback_still_needs_the_higher_level():
    b = BargeIn(level=250, min_ms=240, echo_guard=True, echo_tail_ms=320)
    speaking = [True] * 8 + [False] * 20
    frames = [QUIET] * 8 + [level(400)] * 20                 # Nachhall nach dem letzten Satz, etwas über der Schwelle
    assert frames_until_fire(b, frames, speaking) == 8 + 4 + 2
    b2 = BargeIn(level=250, min_ms=240, echo_guard=True, echo_tail_ms=0)
    assert frames_until_fire(b2, frames, speaking) == 8 + 2
    assert frames_until_fire(BargeIn(level=250, min_ms=240), frames, speaking) == 8 + 2      # ohne Echo-Schutz: kein Nachlauf


def test_short_noise_while_waiting_does_not_interrupt_but_speech_does():
    b = BargeIn(level=250, min_ms=240)
    noise = [level(800), QUIET, QUIET, level(800), QUIET, QUIET, QUIET] * 3
    assert frames_until_fire(b, noise, False) is None         # Klopfen, Stuhl, Tastatur: einzelne Stöße
    b.reset()
    assert frames_until_fire(b, [level(800)] * 6, False) == 2


def test_echo_settings_roundtrip_and_bounds(tmp_path):
    from dataclasses import replace
    import pytest
    from kushim.voice import wakeconfig as wc
    cfg = wc.WakeConfig(settings=replace(wc.Settings(), echo_schutz=True, echo_factor=3.0, echo_ignore_ms=200))
    wc.save(tmp_path, cfg)
    s = wc.load(tmp_path).settings
    assert (s.echo_schutz, s.echo_factor, s.echo_ignore_ms) == (True, 3.0, 200)
    for bad in (replace(wc.Settings(), echo_factor=0.5), replace(wc.Settings(), echo_ignore_ms=5000)):
        with pytest.raises(ValueError):
            wc.save(tmp_path, wc.WakeConfig(settings=bad))


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
    return Pipeline(stt, chat, spk, dialog, kill), stopped


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


# --- Vorlauf, Hinweise, Pegel --------------------------------------------------------------------

def test_preroll_brings_the_words_spoken_during_detection_lag(tmp_path):
    p, notes = Fake(["spoken"]), []
    # Befehl beginnt VOR dem Auslösen des Wake Words (Detektor ist spät) und wird danach nur noch leise Stille
    frames = [QUIET, LOUD, LOUD, LOUD, QUIET, QUIET, QUIET, QUIET]
    seen = {}

    class P(Fake):
        def handle(self, pcm):
            seen["frames"] = len(pcm) // FRAME
            return super().handle(pcm)
    p = P(["spoken"])
    loop = TalkLoop(frames, p, KillSwitch(tmp_path, []), wake=fires_at(3), first_collector=collector, new_collector=collector,
                    preroll_frames=4, on_note=notes.append)
    assert loop.run() == "ended"
    assert p.calls == 1 and seen["frames"] >= 5 and not notes     # ohne Vorlauf wäre es "Ja?" gewesen


def test_without_preroll_the_late_detector_loses_the_command_and_says_ja(tmp_path):
    p, events, notes = Fake(["spoken"]), [], []
    frames = [QUIET, LOUD, LOUD, LOUD] + [QUIET] * 30
    TalkLoop(frames, p, KillSwitch(tmp_path, []), wake=fires_at(3), first_collector=lambda: UtteranceCollector(wait_ms=160),
             new_collector=lambda: UtteranceCollector(wait_ms=160), ack=lambda: events.append("ack"),
             on_note=notes.append).run()
    assert events == ["ack"] and p.calls == 0 and notes and "kein Befehl" in notes[0]


def test_preroll_is_dropped_when_no_wake_word_fires(tmp_path):
    p = Fake([])
    made = []
    TalkLoop([LOUD] * 20, p, KillSwitch(tmp_path, []), wake=lambda f: False,
             first_collector=lambda: made.append(1) or collector(), preroll_frames=4).run()
    assert p.calls == 0 and made == []


def test_notes_explain_why_ja_came_after_wake_only(tmp_path):
    notes, events = [], []
    p = Fake(["wake_only"])
    frames = [QUIET, LOUD, LOUD, QUIET, QUIET, QUIET, QUIET, QUIET]
    TalkLoop(frames, p, KillSwitch(tmp_path, []), wake=fires_at(0), first_collector=collector, new_collector=collector,
             ack=lambda: events.append("ack"), on_note=notes.append).run()
    assert events == ["ack"]


def test_collector_preload_and_peak():
    c = UtteranceCollector(silence_ms=160, min_ms=80)
    c.preload([QUIET, LOUD])
    assert c.heard_speech and c.peak >= 3000 and len(c.audio()) == 2 * FRAME
    assert not c.feed(LOUD)                                   # preload beendet nie von selbst


def test_level_suggestion_matches_a_quiet_headset_voice():
    from kushim.voice.levels import suggest
    noise = [5.0] * 40
    speech = [5.0] * 10 + [200, 250, 300, 440, 500, 450, 700, 900, 400, 350, 600, 480, 300, 280, 260, 800]   # wie die echten Messwerte
    s = suggest(noise, speech)
    assert 100 <= s.speech_level <= 300 and 150 <= s.barge_in_level <= 600
    assert s.barge_in_level >= 1.25 * s.speech_level - 1 and not s.warning


def test_level_suggestion_rejects_missing_speech_and_warns_in_noise():
    import pytest
    from kushim.voice.levels import suggest
    with pytest.raises(ValueError):
        suggest([5.0] * 40, [5.0] * 40)
    with pytest.raises(ValueError):
        suggest([5.0] * 3, [300.0] * 40)
    loud_room = suggest([500.0] * 40, [1700, 1800, 1900, 2000, 2100, 1900, 1800, 1700, 2200, 2000, 1900, 1950])
    assert loud_room.warning


def test_settings_new_fields_roundtrip_and_bounds(tmp_path):
    from dataclasses import replace
    import pytest
    from kushim.voice import wakeconfig as wc
    cfg = wc.WakeConfig(settings=replace(wc.Settings(), speech_level=180.0, barge_in_level=350.0, preroll_seconds=1.5))
    wc.save(tmp_path, cfg)
    s = wc.load(tmp_path).settings
    assert (s.speech_level, s.barge_in_level, s.preroll_seconds) == (180.0, 350.0, 1.5)
    assert wc.Settings().barge_in_level == 250.0 and wc.Settings().speech_level == 200.0 and wc.Settings().barge_in_ms == 240
    for bad in (replace(wc.Settings(), speech_level=10.0), replace(wc.Settings(), preroll_seconds=9.0)):
        with pytest.raises(ValueError):
            wc.save(tmp_path, wc.WakeConfig(settings=bad))


def test_shutdown_phrase_ends_everything_without_llm(tmp_path):
    called, played = [], []
    for text in ("Beende dich.", "Kushim beenden", "Exit"):
        p, _ = make_pipeline(tmp_path, text, lambda m: called.append(1) or iter([]), played)
        r = p.handle(PCM)
        assert r.outcome == "shutdown" and r.reply == "Okay, ich beende mich."
    assert not called
    p, _ = make_pipeline(tmp_path, "Beende Claude", lambda m: iter(["Okay."]), played)
    assert p.handle(PCM).outcome == "spoken"                       # nur Claude: nicht kushim selbst


def test_talk_loop_returns_shutdown(tmp_path):
    p = Fake(["shutdown"])
    frames = [LOUD, LOUD, QUIET, QUIET, LOUD, LOUD, QUIET, QUIET]
    assert TalkLoop(frames, p, KillSwitch(tmp_path, []), wake=fires_at(0), new_collector=collector,
                    follow_collector=follow).run() == "shutdown"
    assert p.calls == 1
