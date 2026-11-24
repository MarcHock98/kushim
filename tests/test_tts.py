"""Sprachausgabe-Logik (voice/tts.py): Satzteilung mit Abkürzungsschutz, Speaker mit Vorausrechnen (Fake-Engine), Rückfall auf
Text plus Hinweiston, Satz-Cache, prefetch."""
import threading
import time

import pytest

from kushim.voice.earcon import MARK, hint_wav
from kushim.voice.tts import (SentenceCache, Speaker, TTSCancelled, TTSUnavailable, chunk_stream, split_first,
                              split_sentences)

# --- Satzteilung ---------------------------------------------------------------------------------------------------------

SPLITS = [
    ("Hallo Welt. Wie geht's? Gut!", ["Hallo Welt.", "Wie geht's?", "Gut!"]),
    ("  ", []),
    ("Das kostet ca. 5 Euro. Danach gehen wir.", ["Das kostet ca. 5 Euro.", "Danach gehen wir."]),
    ("Prof. Klein kommt. Er bleibt.", ["Prof. Klein kommt.", "Er bleibt."]),
    ("Das ist z. B. ein Test. Ja.", ["Das ist z. B. ein Test.", "Ja."]),
    ("Das ist z.B. Obst. Ja.", ["Das ist z.B. Obst.", "Ja."]),
    ("Am 3. Mai ist es so weit. Gut.", ["Am 3. Mai ist es so weit.", "Gut."]),
    ("Stell sie auf die 2. Schiene. Fertig.", ["Stell sie auf die 2. Schiene.", "Fertig."]),
    ("Es sind 5. Danach gehen wir.", ["Es sind 5.", "Danach gehen wir."]),
    ("A. Müller ruft an. Ja.", ["A. Müller ruft an.", "Ja."]),
    ("Es ist der 14.05.2026. Morgen auch.", ["Es ist der 14.05.2026.", "Morgen auch."]),
    ("Hmm... na gut. Weiter.", ["Hmm... na gut.", "Weiter."]),
    ("Backe 45 Min. Danach ruhen lassen.", ["Backe 45 Min. Danach ruhen lassen."]),
    ("Er sagte: „Komm.“ Dann ging er.", ["Er sagte: „Komm.“", "Dann ging er."]),
    ("Was? Nein. 3 Leute kommen.", ["Was?", "Nein.", "3 Leute kommen."]),
    ("Das ist Version 2.1. Sie läuft.", ["Das ist Version 2.1.", "Sie läuft."]),
    ("Ende ohne Punkt", ["Ende ohne Punkt"]),
]


@pytest.mark.parametrize("text,parts", SPLITS, ids=[s[0][:25] or "leer" for s in SPLITS])
def test_split_sentences_protects_abbreviations_dates_and_ordinals(text, parts):
    assert split_sentences(text) == parts


def test_chunk_stream_yields_complete_sentences():
    toks = ["Hal", "lo. Wie ", "geht", "'s? Gut"]
    assert list(chunk_stream(toks)) == ["Hallo.", "Wie geht's?", "Gut"]


def test_chunk_stream_waits_for_the_next_character_before_cutting_an_abbreviation():
    toks = ["Das ist z.", " B. ein Te", "st. Und", " dann am 3.", " Mai fertig."]
    assert list(chunk_stream(toks)) == ["Das ist z. B. ein Test.", "Und dann am 3. Mai fertig."]


@pytest.mark.parametrize("sentence,parts", [
    ("Kurz, knapp.", ["Kurz, knapp."]),
    ("Es ist vierzehn Uhr fünfunddreißig, draußen sind es neun Grad Celsius und es regnet.",
     ["Es ist vierzehn Uhr fünfunddreißig,", "draußen sind es neun Grad Celsius und es regnet."]),
    ("Ja, das mache ich gleich und sage dir danach Bescheid, sobald alles fertig ist.",
     ["Ja, das mache ich gleich und sage dir danach Bescheid,", "sobald alles fertig ist."]),
    ("Der Wert liegt bei 1,5 und bei 2,5 und bei 3,5 und bei 4,5 und bei 5,5 und mehr.",
     ["Der Wert liegt bei 1,5 und bei 2,5 und bei 3,5 und bei 4,5 und bei 5,5 und mehr."]),
    ("Ein sehr langer Satz ohne jedes Komma der einfach immer weiter und weiter geht bis zum Ende.",
     ["Ein sehr langer Satz ohne jedes Komma der einfach immer weiter und weiter geht bis zum Ende."]),
])
def test_split_first_at_a_comma_only_when_long(sentence, parts):
    assert split_first(sentence) == parts


# --- Speaker mit Fake-Engine ---------------------------------------------------------------------------------------------

class Eng:
    """Gibt den Text als „Audio“ zurück und merkt sich Aufrufe; optional mit Verzögerung oder Fehlern."""

    def __init__(self, delay=0.0, fail=(), cancelled=()):
        self.said, self.delay, self.fail, self.cancelled, self.cancels = [], delay, set(fail), set(cancelled), 0
        self.lock = threading.Lock()

    def synthesize(self, text):
        with self.lock:
            self.said.append(text)
        if self.delay:
            time.sleep(self.delay)
        if text in self.fail:
            raise TTSUnavailable("Stimme weg")
        if text in self.cancelled:
            raise TTSCancelled("abgebrochen")
        return text.upper()

    def cancel(self):
        self.cancels += 1


def test_speaker_plays_all_and_counts_sentences():
    out, played = [], []
    spk = Speaker(Eng(), out.append)
    spk.on_played = lambda: played.append(1)
    assert spk.say(["a.", "b."]) == 2
    assert out == ["A.", "B."] and len(played) == 2


def test_speaker_stops_on_barge_in_and_cancels_the_lookahead():
    out, flag, eng = [], {"stop": False}, Eng()

    def play(x):
        out.append(x)
        flag["stop"] = True

    assert Speaker(eng, play, lambda: flag["stop"]).say(["a.", "b.", "c."]) == 1
    assert out == ["A."] and eng.cancels == 1


def test_speaker_computes_the_next_sentence_while_the_current_one_plays():
    eng, seen = Eng(), {}

    def play(x):
        if x == "EINS.":
            deadline = time.monotonic() + 2
            while "Zwei." not in eng.said and time.monotonic() < deadline:
                time.sleep(0.005)
            seen["ahead"] = "Zwei." in eng.said        # Satz 2 wird gerechnet, während Satz 1 noch läuft
    assert Speaker(eng, play).say(["Eins.", "Zwei.", "Drei."]) == 3
    assert seen["ahead"] is True


def test_lookahead_hides_the_synthesis_time_of_the_next_sentence():
    eng = Eng(delay=0.15)

    def play(x):
        time.sleep(0.15)                                # Wiedergabe so lang wie die Synthese
    t0 = time.monotonic()
    Speaker(eng, play).say(["Eins.", "Zwei.", "Drei.", "Vier."])
    ahead = time.monotonic() - t0
    t0 = time.monotonic()
    Speaker(eng, play, lookahead=False).say(["Eins.", "Zwei.", "Drei.", "Vier."])
    serial = time.monotonic() - t0
    assert ahead < serial - 0.25                        # vier Sätze: rund 0,75 s statt 1,2 s


def test_speaker_does_not_wait_for_a_slow_source_when_stopped():
    release, flag = threading.Event(), {"stop": False}

    def source():
        yield "Eins."
        release.wait(timeout=5)                         # LLM schreibt noch
        yield "Zwei."
    out = []

    def play(x):
        out.append(x)
        threading.Timer(0.1, lambda: flag.__setitem__("stop", True)).start()
    t0 = time.monotonic()
    assert Speaker(Eng(), play, lambda: flag["stop"]).say(source()) == 1
    assert time.monotonic() - t0 < 1.0 and out == ["EINS."]
    release.set()


def test_chime_only_before_marked_sentences_and_mark_never_reaches_the_engine():
    eng, out = Eng(), []
    spk = Speaker(eng, out.append)
    spk.chime = "CHIME"
    spk.say([MARK + "Ich möchte etwas ausführen.", "Normal."])
    assert out == ["CHIME", "ICH MÖCHTE ETWAS AUSFÜHREN.", "NORMAL."]
    assert all(MARK not in s for s in eng.said)


def test_speaker_normalizes_text_for_the_voice():
    eng = Eng()
    Speaker(eng, lambda x: None).say(["Es ist 14:35 Uhr.", "Akku 87 %."])
    assert eng.said == ["Es ist vierzehn Uhr fünfunddreißig.", "Akku siebenundachtzig Prozent."]


def test_long_first_sentence_is_split_at_a_comma_but_counts_once():
    eng, played = Eng(), []
    spk = Speaker(eng, lambda x: None)
    spk.on_played = lambda: played.append(1)
    first = "Es ist vierzehn Uhr fünfunddreißig, draußen sind es neun Grad Celsius und es regnet."
    second = "Das ist ein zweiter Satz, der lang genug ist, um sonst auch geteilt zu werden, aber nicht wird."
    assert spk.say([first, second]) == 2 and len(played) == 2
    assert eng.said == ["Es ist vierzehn Uhr fünfunddreißig,", "draußen sind es neun Grad Celsius und es regnet.", second]


def test_chime_comes_only_before_the_first_part_of_a_split_sentence():
    out = []
    spk = Speaker(Eng(), out.append)
    spk.chime = "CHIME"
    spk.say([MARK + "Ich möchte den Befehl ausführen, der die Dateien im Ordner neu sortiert und prüft."])
    assert out[0] == "CHIME" and out.count("CHIME") == 1 and len(out) == 3


def test_voice_failure_gives_hint_tone_and_text_never_silence():
    out, shown = [], []
    eng = Eng(fail={"Zwei.", "Drei."})
    spk = Speaker(eng, out.append)
    spk.hint = "HINT"
    spk.on_unspoken = shown.append
    assert spk.say(["Eins.", "Zwei.", "Drei."]) == 3                # geliefert: 1 gesprochen, 2 und 3 als Text
    assert out == ["EINS.", "HINT"] and shown == ["Zwei.", "Drei."]  # Hinweiston einmal, dann Text


def test_total_voice_failure_shows_the_original_text():
    out, shown = [], []
    spk = Speaker(Eng(fail={"Es ist vierzehn Uhr."}), out.append)
    spk.hint = hint_wav()
    spk.on_unspoken = shown.append
    assert spk.say([MARK + "Es ist 14:00 Uhr."]) == 1                 # als Text geliefert
    assert out == [spk.hint] and shown == ["Es ist 14:00 Uhr."]      # Originaltext ohne Steuerzeichen


def test_display_errors_never_break_the_output():
    spk = Speaker(Eng(fail={"Eins."}), lambda x: None)
    spk.on_unspoken = lambda text: 1 / 0
    spk.on_played = lambda: 1 / 0
    assert spk.say(["Eins.", "Zwei."]) == 2


def test_cancelled_synthesis_ends_quietly_without_hint():
    out, shown = [], []
    spk = Speaker(Eng(cancelled={"Zwei."}), out.append)
    spk.hint, spk.on_unspoken = "HINT", shown.append
    assert spk.say(["Eins.", "Zwei.", "Drei."]) == 1
    assert out == ["EINS."] and shown == []


def test_source_errors_still_reach_the_caller():
    def bad():
        yield "Eins."
        raise RuntimeError("LLM kaputt")
    with pytest.raises(RuntimeError, match="LLM kaputt"):
        Speaker(Eng(), lambda x: None).say(bad())


def test_play_start_and_end_hooks_wrap_each_playback():
    events = []
    spk = Speaker(Eng(), lambda x: events.append(("play", x)))
    spk.on_play_start = lambda: events.append(("start",)) or "tok"
    spk.on_play_end = lambda tok: events.append(("end", tok))
    spk.say(["a.", "b."])
    assert events == [("start",), ("play", "A."), ("end", "tok"), ("start",), ("play", "B."), ("end", "tok")]


def test_serial_mode_behaves_the_same():
    out, shown = [], []
    spk = Speaker(Eng(fail={"b."}), out.append, lookahead=False)
    spk.hint, spk.on_unspoken = "HINT", shown.append
    assert spk.say(["a.", "b.", "c."]) == 3 and out == ["A.", "HINT", "C."] and shown == ["b."]


# --- Satz-Cache ----------------------------------------------------------------------------------------------------------

def test_cache_keeps_only_fixed_code_texts():
    eng = Eng()
    cache = SentenceCache(eng, ["Ja?", "Moment.", "Okay, abgebrochen."])
    assert cache.synthesize("Ja?") == "JA?" and cache.synthesize("Ja?") == "JA?"
    assert eng.said == ["Ja?"]                                       # einmal gerechnet
    cache.synthesize("Fremder Satz.")
    cache.synthesize("Fremder Satz.")
    assert eng.said.count("Fremder Satz.") == 2                      # nie gespeichert
    assert cache.cached("Fremder Satz.") is None and cache.cached("Ja?") == "JA?"


def test_cache_matches_marked_and_normalized_text():
    eng = Eng()
    cache = SentenceCache(eng, ["Der Notaus ist aktiv."])
    cache.synthesize(MARK + "Der Notaus ist aktiv.")
    cache.synthesize("Der Notaus ist aktiv.")
    assert eng.said == ["Der Notaus ist aktiv."]


def test_cache_warms_in_order_and_stops_on_errors_or_request():
    eng = Eng()
    assert SentenceCache(eng, ["Ja?", "Moment.", "Ja?"]).warm() == 2 and eng.said == ["Ja?", "Moment."]
    eng = Eng(fail={"Moment."})
    assert SentenceCache(eng, ["Ja?", "Moment.", "Bis gleich."]).warm() == 1 and "Bis gleich." not in eng.said
    eng = Eng()
    assert SentenceCache(eng, ["Ja?", "Moment."]).warm(stop=lambda: True) == 0 and eng.said == []


def test_cache_does_not_store_failures_and_passes_cancel_on():
    eng = Eng(fail={"Ja?"})
    cache = SentenceCache(eng, ["Ja?"])
    with pytest.raises(TTSUnavailable):
        cache.synthesize("Ja?")
    assert cache.cached("Ja?") is None
    cache.cancel()
    assert eng.cancels == 1


def test_build_live_caches_only_constants_from_the_code():
    from kushim.voice import claude_chat as cc
    from kushim.voice import pipeline as pl
    from kushim.voice.talk import ACK_TEXT, cached_texts
    texts = cached_texts()
    assert texts[0] == ACK_TEXT == "Ja?"
    assert set(cc.FILLERS) <= set(texts) and pl.CANCEL_REPLY in texts and pl.END_REPLY in texts
    assert all(isinstance(t, str) and t for t in texts)


# --- prefetch ------------------------------------------------------------------------------------------------------------

def test_prefetch_keeps_order_and_propagates_errors():
    from kushim.voice.tts import prefetch
    assert list(prefetch(iter(["a", "b", "c"]))) == ["a", "b", "c"]

    def bad():
        yield "x"
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        list(prefetch(bad()))


def test_prefetch_stops_when_requested():
    from kushim.voice.tts import prefetch

    def endless():
        i = 0
        while True:
            yield str(i)
            i += 1

    flag = {"stop": False}
    it = prefetch(endless(), stop=lambda: flag["stop"])
    assert next(it) == "0"
    flag["stop"] = True      # Erzeuger-Thread beendet sich, kein Hängen


def test_prefetch_ends_when_stopped_even_if_the_llm_is_still_writing():
    from kushim.voice.tts import prefetch
    release, stop = threading.Event(), threading.Event()

    def slow_source():
        yield "Satz eins."
        release.wait(timeout=10)              # LLM schreibt noch am nächsten Satz
        yield "Satz zwei."
    got, t0 = [], time.time()
    gen = prefetch(slow_source(), stop=stop.is_set)
    got.append(next(gen))
    threading.Timer(0.3, stop.set).start()    # Nutzer unterbricht
    got.extend(gen)                           # darf nicht hängen bleiben
    release.set()
    assert got == ["Satz eins."] and time.time() - t0 < 3
