"""Prüfung 2026-11-24: lange Abschnitte (Kokoro höchstens 510 Phoneme), Satzteilung nach Kontext, Satz-Cache für Mehrsatz-Texte,
Abbruch bei Fehlern in der Wiedergabe, Zählung bei Sätzen ohne Stimme."""
import re

import pytest

from kushim.voice import claude_chat as cc
from kushim.voice import pipeline as pl
from kushim.voice.earcon import mark
from kushim.voice.speechnorm import normalize
from kushim.voice.talk import cached_texts
from kushim.voice.tts import (LONG_SPLIT, SentenceCache, Speaker, TTSUnavailable, split_long, split_sentences,
                              speech_pieces)

LIST_630 = "Die Liste - " + " - ".join(f"Punkt {w} mit einer kurzen Beschreibung ohne Komma"
                                           for w in ("eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun",
                                                     "zehn", "elf"))
REPEAT = " ".join(["Die Tests laufen jetzt und ich melde mich gleich wieder bei dir"] * 6) + "."


def words(text):
    return re.findall(r"[\wäöüÄÖÜß]+", text)


# --- Satzteilung nach Kontext ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,parts", [
    ("Das war seit 2020. Danach kam mehr.", ["Das war seit 2020.", "Danach kam mehr."]),
    ("Wir treffen uns am 3. Danach sehen wir weiter.", ["Wir treffen uns am 3.", "Danach sehen wir weiter."]),
    ("Das ist zum 2. Mal so. Gut.", ["Das ist zum 2. Mal so.", "Gut."]),
    ("Am 3. Tag regnet es. Gut.", ["Am 3. Tag regnet es.", "Gut."]),
    ("Nimm Vitamin C. Du wirst sehen.", ["Nimm Vitamin C.", "Du wirst sehen."]),
    ("Das ist Plan B. Dann geht es los.", ["Das ist Plan B.", "Dann geht es los."]),
    ("Nimm z. B. Äpfel. Gut.", ["Nimm z. B. Äpfel.", "Gut."]),
    ("Herr A. Müller ruft an. Ja.", ["Herr A. Müller ruft an.", "Ja."]),
    ("J. R. Tolkien schrieb das. Ja.", ["J. R. Tolkien schrieb das.", "Ja."]),
    ("Er wohnt in der Hauptstr. 5 im Erdgeschoss. Gut.", ["Er wohnt in der Hauptstr. 5 im Erdgeschoss.", "Gut."]),
    ("Offen Mo. bis Fr. ab neun. Gut.", ["Offen Mo. bis Fr. ab neun.", "Gut."]),
    ("Vom 1. bis 3. Mai ist zu. Gut.", ["Vom 1. bis 3. Mai ist zu.", "Gut."]),
])
def test_split_by_context(text, parts):
    assert split_sentences(text) == parts


def test_ordinal_at_sentence_end_after_the_split_reads_as_day():
    assert normalize("Wir treffen uns am 3.") == "Wir treffen uns am dritten."
    assert normalize("Das war seit 2020.") == "Das war seit zweitausendzwanzig."


# --- lange Abschnitte --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [LIST_630, REPEAT, "a" * 700, "Wort " * 200, ("Satzteil, " * 60).strip()],
                         ids=["liste-630", "wiederholung-x6", "ein-wort", "nur-leerzeichen", "viele-kommas"])
def test_split_long_keeps_every_word_and_respects_the_limit(text):
    pieces = split_long(normalize(text))
    assert all(0 < len(p) <= LONG_SPLIT for p in pieces), [len(p) for p in pieces]
    assert "".join(words(" ".join(pieces))) == "".join(words(normalize(text)))     # nichts abgeschnitten, nichts doppelt


def test_split_long_prefers_punctuation_dashes_and_conjunctions():
    text = normalize(LIST_630)
    assert len(text) > 600
    pieces = split_long(text)
    assert len(pieces) >= 3 and all(p.endswith(",") for p in pieces[:-1])        # an den Strichen, als kurze Pause
    rep = split_long(normalize(REPEAT))
    assert any(p.startswith("und ") for p in rep[1:])                             # vor „und“


def test_speaker_never_sends_more_than_the_limit_to_the_voice():
    said = []
    spk = Speaker(type("E", (), {"synthesize": lambda self, t: said.append(t) or t})(), lambda wav: None)
    assert spk.say([LIST_630, REPEAT]) == 2                          # zwei Sätze, jeweils in mehreren Stücken
    assert len(said) >= 5 and max(map(len, said)) <= LONG_SPLIT
    assert words(" ".join(said)) == words(normalize(LIST_630)) + words(normalize(REPEAT))


def test_client_refuses_to_cut_text_silently():
    from kushim.voice.ttsworker import MAX_TEXT, KokoroWorker
    w = KokoroWorker(lambda p: ["x"])
    with pytest.raises(TTSUnavailable, match="zu lang"):
        w.synthesize("a" * (MAX_TEXT + 1))


# --- Satz-Cache für Mehrsatz-Konstanten ------------------------------------------------------------------------------------

class Eng:
    def __init__(self):
        self.said = []

    def synthesize(self, text):
        self.said.append(text)
        return text


def test_cache_warms_each_sentence_of_multi_sentence_constants_with_the_speaker_keys():
    eng = Eng()
    cache = SentenceCache(eng, cached_texts())
    cache.warm()
    warmed = list(eng.said)
    for const in (cc.SILENT, cc.FAILED, cc.NOT_RUNNING, cc.LOST, cc.KILLED, cc.LATE, pl.NOTHING_REPLY):
        assert all(normalize(s) in cache.fixed for s in split_sentences(const)), const
    spk = Speaker(cache, lambda wav: None)
    for const in (cc.SILENT, cc.FAILED, cc.NOT_RUNNING, cc.LOST, mark(cc.KILLED), cc.LATE):     # KILLED nur mit Signalton
        spk.say(split_sentences(const))
        spk.say(split_sentences(const)[1:] or [const])               # auch als erster Satz eines `say`
    assert eng.said == warmed                                         # alles kam aus dem Cache


def test_speech_pieces_are_the_same_for_cache_and_speaker():
    s = normalize("Das dauert etwas länger, ich melde mich gleich, sobald alles fertig ist, versprochen.")
    assert speech_pieces(s, True) != speech_pieces(s, False)
    eng = Eng()
    cache = SentenceCache(eng, [s])
    assert set(speech_pieces(s, True)) | set(speech_pieces(s, False)) <= cache.fixed


# --- Wiedergabe-Fehler und Zählung -------------------------------------------------------------------------------------

def test_an_error_while_playing_cancels_the_lookahead_and_propagates():
    class Cancelling(Eng):
        cancels = 0

        def cancel(self):
            Cancelling.cancels += 1
    eng = Cancelling()

    def play(wav):
        raise OSError("Gerät weg")
    with pytest.raises(OSError):
        Speaker(eng, play).say(["Eins.", "Zwei.", "Drei."])
    assert Cancelling.cancels == 1


def test_resuming_an_interrupted_announcement_is_not_shifted_by_text_only_sentences():
    """Satz 2 hat keine Stimme (nur Text), beim Satz 3 wird unterbrochen: nachgereicht wird ab Satz 3, nicht ab Satz 2."""
    flag = {"stop": False}

    class Half(Eng):
        def synthesize(self, text):
            if text == "Zwei.":
                raise TTSUnavailable("weg")
            return super().synthesize(text)
    played = []

    def play(wav):
        played.append(wav)
        if wav == "Drei.":
            flag["stop"] = True                                   # Unterbrechen mitten in Satz 3
    n = Speaker(Half(), play, lambda: flag["stop"]).say(split_sentences("Eins. Zwei. Drei. Vier."))
    done = max(0, n - 1)                                          # so rechnet TalkLoop den Rest
    assert split_sentences("Eins. Zwei. Drei. Vier.")[done:] == ["Drei.", "Vier."]
