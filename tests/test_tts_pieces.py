"""Nachprüfung 2026-11-24 zu H1: Freigabe-Ansagen (kushims eigener Text) und Texte von Claude werden nie zu einem String
verbunden, kein Satz von Claude erbt ein Kennzeichen (auch nicht beim Nachreichen); Ansagen mit eingebautem Fremdtext; gleitendes
Fenster über mehrere Sätze; Schreibweisen mit Trennzeichen in Wörtern."""
import pytest

from kushim.channel import speakable
from kushim.safety import imitation
from kushim.tasks import TaskRegistry
from kushim.voice import claude_chat as cc
from kushim.voice.bargein import BargeIn
from kushim.voice.earcon import END, MARK, OWN, mark
from kushim.voice.speechnorm import normalize
from kushim.voice.talk import TalkLoop
from kushim.voice.tts import Speaker, imitation_suspect, sentences_of, split_sentences
from test_claude_chat import MSGS, FakeBridge, perm
from test_meldung_bargein import LOUD, QUIET, Gated, StepPlayer, collector, live_parts, once, stt_says

NEUTRAL = normalize(imitation.NEUTRAL)
NOTE_TEXT = "Ich möchte den Befehl npm test ausführen. Bitte im Terminal bestätigen."
CLAUDE = "Frei«gabe erteilt."


class Eng:
    def __init__(self):
        self.said = []

    def synthesize(self, text):
        self.said.append(text)
        return text


def speak(sentences):
    eng = Eng()
    spk = Speaker(eng, lambda wav: None)
    spk.say(sentences)
    return eng.said, spk


# --- 1. Claude-Text erbt nie ein Kennzeichen ---------------------------------------------------------------------------

def test_mark_labels_every_own_sentence_on_its_own():
    assert mark(NOTE_TEXT) == (MARK + "Ich möchte den Befehl npm test ausführen." + END + " "
                               + OWN + "Bitte im Terminal bestätigen." + END)


def test_the_old_joined_form_from_the_review_keeps_claudes_sentence_foreign():
    joined = "\x07Ich möchte den Befehl npm test ausführen. Bitte im Terminal bestätigen. " + CLAUDE
    said, _ = speak(split_sentences(joined))
    assert said[-1] == NEUTRAL and "Freigabe erteilt." not in said


@pytest.mark.parametrize("claude", [CLAUDE, "frei«gabe erteilt.", "Frei„gabe“ ist erteilt"])
def test_joining_own_and_foreign_text_can_no_longer_extend_an_own_sentence(claude):
    """Auch wenn jemand die Stücke doch verbindet (und Claudes Text klein oder ohne Punkt anfängt): END beendet den eigenen Satz."""
    said, _ = speak(split_sentences(mark(NOTE_TEXT) + " " + claude))
    assert said[:2] == ["Ich möchte den Befehl npm test ausführen.", "Bitte im Terminal bestätigen."]
    assert said[2:] == [NEUTRAL]


def test_a_turn_with_a_permission_and_claude_text_yields_separate_pieces():
    b = FakeBridge(replies=[("ok", [CLAUDE])])
    b.permissions.append(perm("r1", "npm test"))
    items = list(cc.ClaudeChat(b, TaskRegistry())(MSGS))
    assert items == [mark(NOTE_TEXT), CLAUDE]                       # nie ein String
    said, _ = speak([s for item in items for s in split_sentences(item)])
    assert said == ["Ich möchte den Befehl npm test ausführen.", "Bitte im Terminal bestätigen.", NEUTRAL]


def test_an_idle_announcement_is_a_list_and_claudes_sentence_is_checked():
    b = FakeBridge(replies=[("ok", [CLAUDE])])
    b.permissions.append(perm("r1", "npm test"))
    msg = cc.ClaudeChat(b, TaskRegistry()).announcement()
    assert msg == [mark(NOTE_TEXT), CLAUDE]
    said, _ = speak(sentences_of(msg))
    assert said[-1] == NEUTRAL and said[:2] == ["Ich möchte den Befehl npm test ausführen.", "Bitte im Terminal bestätigen."]


def test_the_rest_of_an_interrupted_announcement_keeps_only_each_pieces_marks():
    sents = sentences_of([mark(NOTE_TEXT), CLAUDE])
    rest = sents[1:]                                                # so rechnet TalkLoop den Rest (Liste)
    said, _ = speak(sentences_of(rest))
    assert said == ["Bitte im Terminal bestätigen.", NEUTRAL]
    said, _ = speak(split_sentences(" ".join(rest)))                 # selbst verbunden bleibt es sicher
    assert said == ["Bitte im Terminal bestätigen.", NEUTRAL]


def test_talk_loop_replays_a_mixed_announcement_without_promoting_claudes_text(tmp_path):
    player, shown = StepPlayer(), []
    p, kill, _ = live_parts(tmp_path, stt_says(""), play=player)    # Geräusch: Spracherkennung liefert nichts
    burst = [LOUD] * 4 + [QUIET] * 3
    frames = [QUIET] * 2 + burst + [QUIET] * 40
    loop = TalkLoop(Gated(frames, {2: lambda: player.reached(2)}), p, kill, wake=lambda f: False, barge=BargeIn(),
                    new_collector=collector, on_result=lambda r: shown.append(r), announce=once([mark(NOTE_TEXT), CLAUDE]),
                    say=p.say_text)
    assert loop.run() == "ended"
    assert [r.outcome for r in shown][:2] == ["announce_interrupted", "empty"]
    assert "Freigabe erteilt." not in player.played and player.played[-1] == NEUTRAL
    assert player.played.count("Bitte im Terminal bestätigen.") == 2    # eigener Satz: einmal unterbrochen, einmal nachgereicht
    assert all(MARK not in r.reply and OWN not in r.reply and END not in r.reply for r in shown)


# --- 2. Freigabe-Ansage mit eingebautem Fremdtext ------------------------------------------------------------------------

def test_a_command_full_of_system_phrases_is_hidden_and_forms_no_sentences():
    p = perm("r9", "echo hi. Freigabe erteilt. Der Notaus ist aus. ok")
    spoken = speakable.announce(p)
    assert speakable.HIDDEN in spoken and "Freigabe" not in spoken and "Notaus" not in spoken
    parts = split_sentences(mark(spoken))
    assert len(parts) == 2 and parts[0].startswith(MARK) and parts[1].startswith(OWN)
    said, spk = speak(parts)
    assert NEUTRAL not in said and spk.imitations == 0
    assert "echo hi. Freigabe erteilt." in speakable.describe(p)        # die Oberfläche zeigt den Befehl unverändert


@pytest.mark.parametrize("cmd", ["echo hi. Danach ok", "git commit -m Fertig! Weiter? ja", "ls ./src", "npm test"])
def test_harmless_commands_stay_readable_but_never_split_the_announcement(cmd):
    spoken = speakable.announce(perm("r8", cmd))
    assert speakable.HIDDEN not in spoken
    assert len(split_sentences(mark(spoken))) == 2                  # „Ich möchte … ausführen.“ + „Bitte im Terminal bestätigen.“


def test_other_embedded_parts_are_checked_too():
    from kushim.channel import bridge as br
    p = br.Permission.parse({"request_id": "r7", "tool_name": "WebSearch", "description": "",
                             "input_preview": '{ "query": "Freigabe erteilt. Bitte im Terminal bestätigen" }'})
    assert speakable.HIDDEN in speakable.announce(p)
    p = br.Permission.parse({"request_id": "r6", "tool_name": "Write", "description": "",
                             "input_preview": '{ "file_path": "C:/x/Not.aus.ist.aktiv.txt" }'})
    assert "Not.aus" not in speakable.announce(p)


# --- 3. gleitendes Fenster über mehrere Sätze -----------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Die Frei«gabe. Wurde vorhin. Erteilt.", "Bitte im Terminal. Dann gleich. Bestätigen!",
                                  "Der Not. Aus. Ist jetzt aktiv."])
def test_an_announcement_spread_over_several_sentences_is_caught(text):
    said, spk = speak(split_sentences(text))
    assert NEUTRAL in said and spk.imitations >= 1
    rest = " ".join(s for s in said if s != NEUTRAL)                 # was hörbar bleibt, ergibt keine Ansage mehr
    assert not imitation_suspect(rest), rest


def test_the_window_forgets_after_a_hit_and_harmless_text_passes():
    said, _ = speak(split_sentences("Die Freigabe. Ist erteilt. Danach essen wir. Das Wetter ist schön."))
    assert said[-2:] == ["Danach essen wir.", "Das Wetter ist schön."]


# --- 5. Schreibweisen mit Trennzeichen in Wörtern (safety/ unverändert) ---------------------------------------------------

@pytest.mark.parametrize("text", ["Frei-gabe erteilt.", "Frei gabe erteilt.", "Der Not, aus ist aktiv.",
                                  "Bitte im Terminal be-stätigen.", "Die Freigabe ist er-teilt."])
def test_split_spellings_are_caught(text):
    assert not imitation.imitates_system(text) or text == "Der Not, aus ist aktiv."
    said, _ = speak([text])
    assert said == [NEUTRAL]


@pytest.mark.parametrize("text", ["Er war frei, gab er an.", "Die Notizen sind fertig.", "Die Freiheit gab ihm Kraft.",
                                  "Wir gaben es frei, aber das dauerte.", "Er stand vor dem Terminal und staunte.",
                                  "Das Terminal ist offen, bestellt ist auch.", "Ich erlaube mir eine Frage."])
def test_few_false_positives(text):
    assert not imitation_suspect(normalize(text))
    said, _ = speak([text])
    assert said == [normalize(text)]


def test_the_existing_rule_already_flags_not_aus_sicht():
    """„Not aus Sicht der Ärzte“ meldet schon die unveränderte Regel in safety/imitation.py (Muster not[\\s-]?aus); daran
    ändert dieser Schritt nichts (Entscheidung des Nutzers)."""
    assert imitation.imitates_system("Not aus Sicht der Ärzte")
