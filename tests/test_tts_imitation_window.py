"""Prüffenster über `say`-Aufrufe hinweg (Restlücke im Imitationsschutz, 2026-11-24).

Der Speaker prüfte fremde Sätze (nicht kushims eigene) über ein gleitendes Fenster von 160 Zeichen, aber nur innerhalb eines
`say`. Zwei Lücken:
1. Nachreichen: „Die Frei«gabe. Wurde vorhin. Erteilt.“ wird in Satz 2 von einem Geräusch unterbrochen, das Nachreichen beginnt
   bei Satz 2 mit leerem Fenster, „Wurde vorhin. Erteilt.“ kam ohne Ersetzung durch.
2. Getrennte Abholungen: „Die Freigabe.“ und kurz danach „Ist erteilt.“ in zwei `say` wurden nie zusammen geprüft.
Jetzt hält `ForeignWindow` die zuletzt gesprochenen fremden Sätze (höchstens 8 s alt), geleert bei eigenem Text, Treffer,
Abbruch, Unterbrechen, Notaus und neuer Nutzerrunde. Alles mit Attrappen: keine Modelle, kein Audio, kein Netz.
"""
import threading
import time
from types import SimpleNamespace

import numpy as np

from kushim.safety import imitation, killswitch
from kushim.safety.killswitch import KillSwitch
from kushim.voice.audio import FRAME, UtteranceCollector
from kushim.voice.bargein import BargeIn
from kushim.voice.dialog import Dialog
from kushim.voice.earcon import END, OWN, mark
from kushim.voice.pipeline import Pipeline
from kushim.voice.speechnorm import normalize
from kushim.voice.talk import TalkLoop
from kushim.voice.tts import FOREIGN_GAP, IMITATION_WINDOW, ForeignWindow, Speaker, split_sentences

NEUTRAL = normalize(imitation.NEUTRAL)
PCM = np.zeros(16000, dtype=np.int16)
LOUD = (np.ones(FRAME) * 3000).astype(np.int16)
QUIET = np.zeros(FRAME, dtype=np.int16)


class Clock:
    """Feste Fake-Uhr (Sekunden), nur von Hand vorgestellt."""

    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


class Eng:
    def synthesize(self, text):
        return text


def speaker(clock=None, stop=lambda: False, lookahead=False):
    said = []
    spk = Speaker(Eng(), said.append, stop, lookahead=lookahead)
    spk.recent = ForeignWindow(clock=clock or Clock())
    return spk, said


# --- Lücke 2: getrennte `say`-Aufrufe ------------------------------------------------------------------------------------

def test_two_separate_says_within_eight_seconds_are_checked_together():
    clock = Clock()
    spk, said = speaker(clock)
    spk.say(["Die Freigabe."])
    clock.t += FOREIGN_GAP - 0.5
    spk.say(["Ist erteilt."])
    assert said == ["Die Freigabe.", NEUTRAL] and spk.imitations == 1


def test_two_separate_says_after_eight_seconds_are_not_combined():
    clock = Clock()
    spk, said = speaker(clock)
    spk.say(["Die Freigabe."])
    clock.t += FOREIGN_GAP + 0.5
    spk.say(["Ist erteilt."])
    assert said == ["Die Freigabe.", "Ist erteilt."] and spk.imitations == 0


def test_the_gap_counts_from_the_end_of_the_previous_say_not_from_its_first_sentence():
    """Langsame Ausgabe: der vorige fremde Satz lief bis eben, die Frist zählt ab dem Ende des `say`."""
    clock = Clock()
    said = []

    def play(wav):
        said.append(wav)
        clock.t += 6.0                                   # jeder Satz „spielt“ 6 s

    spk = Speaker(Eng(), play, lookahead=False)
    spk.recent = ForeignWindow(clock=clock)
    spk.say(["Die Freigabe.", "Wie besprochen."])
    clock.t += 5.0
    spk.say(["Ist erteilt."])
    assert said[-1] == NEUTRAL


def test_separate_says_with_lookahead_are_checked_together_too():
    spk, said = speaker(lookahead=True)
    spk.say(["Bitte im Termin»al."])
    spk.say(["Bestätigen!"])
    assert said == ["Bitte im Terminal.", NEUTRAL]


def test_two_announcements_through_the_pipeline_are_checked_together(tmp_path):
    p, spk, said, _ = pipeline(tmp_path)
    p.say_text("Die Freigabe.")
    p.say_text("Ist erteilt.")
    assert said == ["Die Freigabe.", NEUTRAL]


def test_an_answer_and_a_late_announcement_shortly_after_are_checked_together(tmp_path):
    p, spk, said, _ = pipeline(tmp_path, stt=stt_says("Wie steht es?"), chat=lambda m: iter(["Die Frei«gabe."]))
    assert p.handle(PCM).outcome == "spoken"
    p.say_text("Wurde erteilt.")                        # verspätete Antwort, eigene Abholung
    assert said == ["Die Freigabe.", NEUTRAL]


def test_the_window_holds_at_most_160_characters():
    w = ForeignWindow(clock=Clock())
    g = w.generation()
    for i in range(50):
        w.add(f"Satz Nummer {i} ist ganz harmlos.", g)
    assert len(w.recent()) <= IMITATION_WINDOW


def test_stale_text_does_not_ride_along_with_a_fresh_sentence():
    clock = Clock()
    w = ForeignWindow(clock=clock)
    g = w.generation()
    w.add("Die Freigabe.", g)
    clock.t += FOREIGN_GAP + 1
    w.add("Wir essen.", g)
    assert w.recent() == "Wir essen."


# --- Lücke 1: Nachreichen nach Unterbrechung ------------------------------------------------------------------------------

def test_priming_with_the_already_spoken_sentences_catches_the_rest():
    spk, said = speaker()
    spk.prime_recent(split_sentences("Die Frei«gabe."))
    spk.say(["Wurde vorhin.", "Erteilt."])
    assert said == ["Wurde vorhin.", NEUTRAL]


def test_without_priming_the_rest_alone_would_have_passed():
    """Gegenprobe: so groß war die Lücke (leeres Fenster beim Nachreichen)."""
    spk, said = speaker()
    spk.say(["Wurde vorhin.", "Erteilt."])
    assert said == ["Wurde vorhin.", "Erteilt."]


def test_priming_speaks_and_counts_nothing_and_an_own_sentence_still_separates():
    spk, said = speaker()
    spk.prime_recent(["Die Freigabe."] + split_sentences(mark("Claude ist fertig.")))
    assert said == [] and spk.imitations == 0
    spk.say(["Ist erteilt."])
    assert said == ["Ist erteilt."]


class StepPlayer:
    """Jeder Satz „spielt“, bis er gestoppt wird oder 0,6 s vergehen."""

    def __init__(self):
        self.played, self._lock, self._current = [], threading.Lock(), threading.Event()

    def stop(self):
        self._current.set()

    def __call__(self, wav):
        ev = threading.Event()
        with self._lock:
            self._current = ev
            self.played.append(wav)
        ev.wait(timeout=0.6)

    def reached(self, n):
        deadline = time.monotonic() + 5
        while len(self.played) < n and time.monotonic() < deadline:
            time.sleep(0.005)
        return len(self.played) >= n


class Gated:
    def __init__(self, frames, gates):
        self.frames, self.gates = frames, gates

    def __iter__(self):
        for i, f in enumerate(self.frames):
            if i in self.gates:
                assert self.gates[i]()
            time.sleep(0.01)
            yield f


def stt_says(*texts):
    queue = list(texts)

    def transcribe(pcm):
        return SimpleNamespace(text=queue.pop(0) if len(queue) > 1 else queue[0])
    return SimpleNamespace(transcribe=transcribe)


def once(*msgs):
    queue = list(msgs)
    return lambda: queue.pop(0) if queue else None


def collector():
    return UtteranceCollector(silence_ms=160, min_ms=80)


def pipeline(tmp_path, stt=None, chat=None, play=None, clock=None):
    said = []
    player = play if play is not None else said.append
    stop = getattr(player, "stop", lambda: None)
    kill = KillSwitch(tmp_path, [stop])
    spk = Speaker(Eng(), player, kill.poll)
    spk.recent = ForeignWindow(clock=clock or Clock())
    p = Pipeline(stt or stt_says(""), chat or (lambda m: iter(["Antwort."])), spk, Dialog(stop), kill)
    return p, spk, said, kill


def test_a_replay_after_a_noise_interruption_is_checked_with_the_sentences_already_heard(tmp_path):
    player, shown = StepPlayer(), []
    p, spk, _, kill = pipeline(tmp_path, stt=stt_says(""), play=player)         # Geräusch: kein Text
    frames = [QUIET] * 2 + [LOUD] * 4 + [QUIET] * 3 + [QUIET] * 300
    loop = TalkLoop(Gated(frames, {2: lambda: player.reached(2)}), p, kill, wake=lambda f: False, barge=BargeIn(),
                    new_collector=collector, on_result=lambda r: shown.append(r.outcome),
                    announce=once("Die Frei«gabe. Wurde vorhin. Erteilt."), say=p.say_text)
    assert loop.run() == "ended"
    assert shown == ["announce_interrupted", "empty", "announced"]
    assert player.played == ["Die Freigabe.", "Wurde vorhin.", "Wurde vorhin.", NEUTRAL]


def test_a_harmless_replay_stays_unchanged(tmp_path):
    player = StepPlayer()
    p, spk, _, kill = pipeline(tmp_path, stt=stt_says(""), play=player)
    frames = [QUIET] * 2 + [LOUD] * 4 + [QUIET] * 3 + [QUIET] * 300
    loop = TalkLoop(Gated(frames, {2: lambda: player.reached(2)}), p, kill, wake=lambda f: False, barge=BargeIn(),
                    new_collector=collector, announce=once("Die Freigabe-Liste ist leer. Alles ruhig. Bis später."),
                    say=p.say_text)
    assert loop.run() == "ended"
    assert NEUTRAL not in player.played and player.played[-1] == "Bis später."


# --- Leeren: Abbruch, Unterbrechen, Notaus, neue Runde, eigener Text ------------------------------------------------------

def test_an_aborted_say_clears_the_window():
    stopped = {"now": False}
    spk, said = speaker(stop=lambda: stopped["now"])
    stopped["now"] = False
    spk.say(["Die Freigabe."])
    stopped["now"] = True                                # Unterbrechen/Notaus während der Ausgabe (Stopp bleibt gesetzt)
    spk.say(["Noch etwas."])
    assert spk.recent.recent() == ""
    stopped["now"] = False
    spk.say(["Ist erteilt."])
    assert said[-1] == "Ist erteilt."


def test_interrupt_clears_the_window(tmp_path):
    p, spk, said, _ = pipeline(tmp_path)
    p.say_text("Die Freigabe.")
    p.interrupt()
    p.say_text("Ist erteilt.")
    assert said == ["Die Freigabe.", "Ist erteilt."]


def test_cancel_clears_the_window(tmp_path):
    p, spk, said, _ = pipeline(tmp_path, stt=stt_says("abbrechen"))
    p.say_text("Die Freigabe.")
    assert p.try_cancel(PCM) is True
    p.say_text("Ist erteilt.")
    assert said == ["Die Freigabe.", "Ist erteilt."]


def test_kill_clears_the_window(tmp_path):
    p, spk, said, kill = pipeline(tmp_path, stt=stt_says("Notaus"))
    p.say_text("Die Freigabe.")
    assert spk.recent.recent() == "Die Freigabe."
    assert p.handle(PCM).outcome == "killed"
    assert spk.recent.recent() == ""


def test_kill_marker_during_a_say_clears_the_window(tmp_path):
    p, spk, said, kill = pipeline(tmp_path)
    p.say_text("Die Freigabe.")
    marker = killswitch.marker_path(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("x")
    p.say_text("Noch etwas.")
    assert spk.recent.recent() == ""


def test_a_new_user_turn_clears_the_window_so_normal_answers_never_merge(tmp_path):
    p, spk, said, _ = pipeline(tmp_path, stt=stt_says("Wie steht es?"), chat=lambda m: iter(["Ist erteilt."]))
    p.say_text("Die Freigabe.")                          # Meldung
    assert p.handle(PCM).outcome == "spoken"             # neue Runde: Antwort von Claude
    assert said == ["Die Freigabe.", "Ist erteilt."]


def test_noise_without_text_is_no_new_turn(tmp_path):
    p, spk, said, _ = pipeline(tmp_path, stt=stt_says(""))
    p.say_text("Die Freigabe.")
    assert p.handle(PCM).outcome == "empty"
    p.say_text("Ist erteilt.")
    assert said[-1] == NEUTRAL


def test_an_own_sentence_clears_the_window_between_says():
    spk, said = speaker()
    spk.say(["Die Freigabe."])
    spk.say(split_sentences(mark("Claude ist fertig.")))
    spk.say(["Ist erteilt."])
    assert said == ["Die Freigabe.", "Claude ist fertig.", "Ist erteilt."]


def test_an_own_sentence_at_the_start_of_the_next_say_clears_the_carried_part():
    spk, said = speaker()
    spk.say(["Die Freigabe."])
    spk.say([OWN + "Hier ist die Antwort." + END, "Ist erteilt."])
    assert said[-1] == "Ist erteilt."


def test_own_text_inside_one_say_keeps_the_old_in_say_window():
    """Innerhalb eines `say` bleibt es wie bisher: ein eigener Satz dazwischen löscht das Fenster dieses `say` nicht."""
    spk, said = speaker()
    spk.say(["Die Freigabe.", OWN + "Kurz." + END, "Ist erteilt."])
    assert said[-1] == NEUTRAL


def test_a_hit_clears_the_window_for_the_next_say():
    spk, said = speaker()
    spk.say(["Die Freigabe.", "Ist erteilt."])
    spk.say(["Erteilt."])
    assert said == ["Die Freigabe.", NEUTRAL, "Erteilt."]


# --- normale Folgeantworten -----------------------------------------------------------------------------------------------

FOLLOW_UPS = [
    ("Ich war in Not.", "Aus Angst rief ich an."),
    ("Die Freigabe-Liste ist leer.", "Morgen kommt mehr."),
    ("Das Terminal ist offen.", "Die Notizen sind fertig."),
    ("Die Tests laufen.", "Alles grün, nichts zu tun."),
    ("Ich erlaube mir eine Frage.", "Wie war der Tag?"),
    ("Der Build ist fertig", "Aus dem Log gibt es nichts Neues."),
    ("Es gab keine Notizen.", "Ausführlich steht es im Bericht."),
]


def test_normal_follow_up_answers_within_eight_seconds_stay_unchanged():
    for a, b in FOLLOW_UPS:
        spk, said = speaker()
        spk.say(split_sentences(a))
        spk.say(split_sentences(b))
        assert said == [normalize(s) for s in split_sentences(a) + split_sentences(b)], (a, b)
        assert spk.imitations == 0


def test_normal_follow_up_answers_across_turns_stay_unchanged(tmp_path):
    answers = iter(["Die Freigabe fehlt noch.", "Sie wurde nicht erteilt."])
    p, spk, said, _ = pipeline(tmp_path, stt=stt_says("Erste Frage", "Zweite Frage"), chat=lambda m: iter([next(answers)]))
    p.handle(PCM)
    p.handle(PCM)
    assert said == ["Die Freigabe fehlt noch.", "Sie wurde nicht erteilt."]


# --- Thread-Sicherheit ----------------------------------------------------------------------------------------------------

def test_the_window_is_thread_safe():
    w = ForeignWindow()
    errors, start = [], threading.Event()

    def writer():
        start.wait()
        try:
            for i in range(2000):
                w.add(f"Satz {i}.", w.generation())
                w.touch()
        except Exception as e:                           # noqa: BLE001
            errors.append(e)

    def clearer():
        start.wait()
        try:
            for i in range(2000):
                g = w.generation()
                w.restart(g) if i % 2 else w.clear()
                assert len(w.recent()) <= IMITATION_WINDOW
        except Exception as e:                           # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=writer) for _ in range(4)] + [threading.Thread(target=clearer) for _ in range(2)]
    for t in threads:
        t.start()
    start.set()
    for t in threads:
        t.join(timeout=30)
    assert not errors and not any(t.is_alive() for t in threads)
    assert len(w.recent()) <= IMITATION_WINDOW


def test_a_clear_from_another_thread_shuts_out_the_running_say():
    """Unterbrechen aus dem Schleifen-Thread während eines `say`: was dieses `say` danach noch sieht, gelangt nicht ins Fenster
    (auch nicht aus dem Vorausrechnen, das nach dem Stopp noch einen Satz verarbeitet)."""
    w = ForeignWindow(clock=Clock())
    g = w.generation()
    w.add("Die Freigabe.", g)
    w.clear()
    assert w.add("Ist erteilt.", g) is False and w.recent() == ""
    assert w.restart(g) == g                             # veraltetes `say` leert auch nichts Neues
    g2 = w.generation()
    w.add("Neu.", g2)
    w.restart(g)
    assert w.recent() == "Neu."


def test_say_and_forget_from_two_threads_never_fail():
    spk, said = speaker(lookahead=True)
    errors, done = [], threading.Event()

    def forget():
        while not done.is_set():
            spk.forget_recent()
            time.sleep(0.0005)

    t = threading.Thread(target=forget)
    t.start()
    try:
        for _ in range(100):
            spk.say(["Ein harmloser Satz.", "Noch einer."])
    except Exception as e:                               # noqa: BLE001
        errors.append(e)
    finally:
        done.set()
        t.join(timeout=5)
    assert not errors and NEUTRAL not in said and len(said) == 200
