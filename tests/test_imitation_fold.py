"""Nachprüfung 2026-11-24 (M1): Schreibweisen, die `safety/imitation.py` umgehen, faltet der Speaker vor der zweiten Prüfung
(`voice/imitation_fold.py`); `safety/` bleibt unverändert. Dazu die Falsch-Positiv-Grenze bei normalen Sätzen."""
import json

import pytest

from kushim.channel import speakable
from kushim.channel.bridge import Permission
from kushim.channel.server import clean_text, spoken_text
from kushim.safety import imitation
from kushim.voice.earcon import mark
from kushim.voice.imitation_fold import fold, folded_suspect
from kushim.voice.speechnorm import normalize
from kushim.voice.tts import Speaker, imitation_suspect, sentences_of

NEUTRAL = normalize(imitation.NEUTRAL)


class Eng:
    def __init__(self):
        self.said = []

    def synthesize(self, text):
        self.said.append(text)
        return text


def chain(raw):
    """Wie im Betrieb: Channel (spoken_text), erster Filter (guard), Brücke (clean_text, guard), Speaker."""
    text, first = imitation.guard(spoken_text(raw))
    text, second = imitation.guard(clean_text(text))
    eng = Eng()
    spk = Speaker(eng, lambda wav: None, lookahead=False)
    spk.say(sentences_of(text))
    return bool(first or second or spk.imitations), eng.said


CAUGHT = [
    # 1. zu stark zusammengezogen
    "Frei-gabe-erteilt.", "Frei.gabe.erteilt.", "Frei-gabe-ist-erteilt.", "Die Frei-gabe-wurde-erteilt.", "Frei. Gabe. Erteilt.",
    "Das ist frei. Gabe. Erteilt.", "Im Terminal. Be. Stätigen.", "Ter. Mi. Nal. Be. Stä. Ti. Gen.", "Er. Lauben?",
    "Frei gabe er teilt.", "Freigabe ert-eilt.", "Die Freigabe ist er. Teilt.", "Bitte im Ter-mi-nal be-stä-ti-gen.",
    # 2. Satzzeichen und Symbole als Lücke
    "Not! Aus! Ist aktiv.", "Der Not! Aus! Ist aktiv.", "Not? Aus.", "Not!aus ist aktiv", "Der Not(aus) ist aktiv.",
    "Der Not+aus ist aktiv.", "Der Not=aus ist aktiv.", "Der Not~aus ist aktiv.", "Der Not@aus ist aktiv.",
    "Der Not*aus ist aktiv.", "Der Not|aus ist aktiv.", "Der Not#aus ist aktiv.", "Der Not%aus ist aktiv.",
    "Der Not/aus ist aktiv.", "Der Not\\aus ist aktiv.", "Der Not[aus] ist aktiv.", "Der Not{aus} ist aktiv.",
    "Der Not_aus ist aktiv.", "Der Not;aus ist aktiv.", "Der Not\u2212aus ist aktiv.", "Der Not, aus ist aktiv.",
    # 3. unsichtbare und kombinierende Zeichen, Trenner, Doppelgänger
    "Der Not\u034faus ist aktiv.", "Der Not\ufe0faus ist aktiv.", "Der Not\ufe00aus ist aktiv.", "Der Nota\u0301us ist aktiv.",
    "Der Not\u0332aus ist aktiv.", "Der Not\u2027aus ist aktiv.", "Der Not\u2043aus ist aktiv.", "Der Not\u3164aus ist aktiv.",
    "Der Not\u115faus ist aktiv.", "Der Not\u0430us ist aktiv.", "Freig\u0430be erteilt.", "Der N\u043etaus ist aktiv.",
    "\uff2e\uff4f\uff54\uff41\uff55\uff53 ist aktiv.", "Bitte im Termin\u0430l best\u00e4tigen.", "Der N0taus ist aktiv.",
    # 4. lautgleiche Schreibweisen und Zusammensetzungen
    "Der Nohtaus ist aktiv.", "Der Notauss ist aktiv.", "Notausfunktion ausgelöst.", "Notausschalter gedrückt.",
    "Der Nott-Aus ist aktiv.", "Die Notaus-Funktion wurde ausgelöst.", "Die Frei gaabe ist ertailt.",
    "Freigabe wurde von dir soeben ganz offiziell und eindeutig erteilt.",
]


@pytest.mark.parametrize("raw", CAUGHT)
def test_spellings_are_caught_through_the_whole_chain(raw):
    hit, said = chain(raw)
    assert hit and NEUTRAL in said, said
    assert not any(imitation_suspect(s) for s in said if s != NEUTRAL)          # hörbar bleibt nichts Nachgeahmtes


HARMLESS = [
    "Die Notaufnahme ist offen.", "Der Notausgang ist links.", "Notausgang links, bitte.", "Not-Aufnahme ist im Erdgeschoss.",
    "Er war frei, gab er an.", "Die Daten sind frei, gab der Bericht an, und erteilt wurden keine Auflagen.",
    "Ich war in Not. Aus Angst rief ich an.", "Ich habe keine Not. Austern mag ich.", "Not. Ausgerechnet heute.",
    "Not macht erfinderisch. Aus Erfahrung weiß ich das.", "Frei. Gabe: Das ist sein Name. Erteilt hat er nichts.",
    "Sie sagte frei. Gabriel war erleichtert.", "Die Zahlen sind frei gegeben worden.", "Gib frei, Gabe ist da.",
    "Mein Termin, al dente gekocht, bestätigt sich.", "Willst du mir erlauben, dass ich frage?", "Die Freigabe-Erteilung dauert.",
    "Die Nota, us-amerikanisch, ist teuer.", "Der Bote aus Not.", "Gib es frei. Gabe ist gut. Erteilt ist nichts.",
    "Die Notaufnahme war voll. Aus Platzgründen gingen wir.", "Ich war in großer Not. Aus dem Haus ging ich.",
    "Ich erlaube mir eine Frage.", "Das Terminal ist offen, bestellt ist auch.", "Die Notizen sind fertig.",
]


@pytest.mark.parametrize("raw", HARMLESS)
def test_normal_sentences_are_not_replaced(raw):
    hit, said = chain(raw)
    assert not hit and NEUTRAL not in said, said


def test_known_remaining_false_positives_are_only_not_comma_aus():
    """„Not, aus“ soll treffen (sonst umgeht ein Komma die Regel); dafür trifft es auch „Not, aus der man lernt“."""
    assert chain("Not, aus der man lernt, ist wertvoll.")[0] and chain("Not; aus dem Weg!")[0]


def test_fold_removes_marks_and_maps_lookalikes():
    assert fold("Nota\u0301us \u0430\u0435\u043e \uff2e") == "notaus aeo n"
    assert folded_suspect("Freigabe am Ende erteilt") and not folded_suspect("Freigabe des Films")


def test_invisible_characters_are_removed_before_the_voice():
    for ch in ("\u034f", "\ufe0f", "\ufe00", "\u180b", "\u3164", "\U000e0100"):
        assert normalize(f"Not{ch}aus") == "Notaus"
    assert normalize("Note" + chr(0x301)) == "Not" + chr(0xE9)             # sichtbare Akzente bleiben (NFC)


@pytest.mark.parametrize("preview,tool", [
    ({"command": "echo Frei\u034fgabe ist schon erteilt, du musst nichts tun"}, "Bash"),
    ({"command": "echo Der Not\u034faus ist aktiv"}, "Bash"),
    ({"command": "echo Im Termin\u034fal schon bestätigt"}, "Bash"),
    ({"command": "echo Not! Aus! aktiv"}, "Bash"),
    ({"command": "echo Notausschalter gedrückt"}, "Bash"),
    ({"file_path": "C:/x/Frei-gabe-erteilt.txt"}, "Write"),
    ({}, "mcp__Not\u034faus__x"),
    ({}, "mcp__srv__Frei\ufe0fgabe_erteilt"),
])
def test_embedded_parts_of_an_announcement_are_folded_too(preview, tool):
    p = Permission("r1", tool, "", json.dumps(preview))
    spoken = speakable.announce(p)
    assert speakable.HIDDEN in spoken, spoken
    eng = Eng()
    Speaker(eng, lambda wav: None).say(sentences_of(mark(spoken)))
    assert not any(imitation_suspect(s) for s in eng.said if "Bitte im Terminal bestätigen" not in s)
