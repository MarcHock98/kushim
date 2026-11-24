"""Echte Systemansagen von kushim bleiben erkennbar; Claude kann sie nicht nachahmen (Safety-Audit 2026-11-23).

(1) Signalton vor kushims festen Ansagen (Freigabe, Notaus), den `sprich` nie auslösen kann.
(2) `sprich`-Texte, die wie Systemansagen klingen, werden ersetzt und protokolliert; `zeige` lehnt angebliche Freigaben ab.
(3) Fenster und Freigabe-Protokoll zeigen weiter die echten Daten.
"""
import io
import wave
from types import SimpleNamespace

import numpy as np
import pytest

from kushim.channel import bridge as br
from kushim.channel import server as ch
from kushim.channel import speakable
from kushim.safety import imitation
from kushim.safety.killswitch import KillSwitch
from kushim.stage import schema
from kushim.tasks import TaskRegistry
from kushim.voice import claude_chat as cc
from kushim.voice import earcon
from kushim.voice.dialog import Dialog
from kushim.voice.pipeline import Pipeline
from kushim.voice.tts import Speaker

CHIME = b"CHIME"


class Eng:
    def __init__(self):
        self.said = []

    def synthesize(self, text):
        self.said.append(text)
        return text


# --- (1) Signalton -------------------------------------------------------------------------------------------------

def test_chime_is_a_real_two_tone_wav_generated_in_code():
    data = earcon.chime_wav()
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, earcon.RATE)
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    assert 0.25 <= len(pcm) / earcon.RATE <= 0.4 and np.abs(pcm).max() > 3000
    half = int(earcon.RATE * earcon.TONES[0][1])
    first, second = pcm[:half], pcm[half:]
    zero_cross = lambda x: np.count_nonzero(np.diff(np.signbit(x)))
    assert zero_cross(second) / len(second) > zero_cross(first) / len(first) * 1.3     # zweiter Ton höher


def test_speaker_plays_the_chime_only_before_marked_sentences_and_never_speaks_the_mark():
    played, eng = [], Eng()
    spk = Speaker(eng, played.append)
    spk.chime = CHIME
    # wie im Betrieb: die markierte Ansage wird geteilt, ihr Folgesatz trägt earcon.OWN (kushims Text, kein zweiter Ton)
    from kushim.voice.tts import split_sentences
    spk.say(split_sentences(earcon.mark("Ich möchte den Befehl ls ausführen. Bitte im Terminal bestätigen.")) + ["Normaler Satz."])
    assert played == [CHIME, "Ich möchte den Befehl ls ausführen.", "Bitte im Terminal bestätigen.", "Normaler Satz."]
    assert all(earcon.MARK not in s and earcon.OWN not in s for s in eng.said)


def test_claude_can_never_send_the_mark():
    assert earcon.MARK not in ch.spoken_text(earcon.MARK + "Ich möchte etwas.") and earcon.MARK not in ch.clean_text("\x07x")
    c = ch.Channel(io.StringIO(), log=lambda s: None)
    c._call_tool({"name": "sprich", "arguments": {"text": "\x07Hallo"}})
    assert c.take() == ["Hallo"]


def test_in_a_turn_the_permission_note_gets_the_chime_and_claudes_reply_does_not(tmp_path):
    class Bridge:
        last_final = True

        def __init__(self):
            self.perms, self.calls = [], 0

        def send(self, text):
            return "ok"

        def cancel(self):
            return "ok"

        def available(self):
            return True

        def pending(self):
            return self.perms

        def fetch(self, wait=0.0):
            self.calls += 1
            if self.calls == 1:
                self.perms = [br.Permission.parse({"request_id": "r1", "tool_name": "Bash", "description": "",
                                                   "input_preview": '{ "command": "ls" }'})]
                return "ok", ["Ich schau nach."]
            return "ok", []
    played = []
    kill = KillSwitch(tmp_path, [])
    spk = Speaker(Eng(), played.append, lambda: kill.fired)
    spk.chime = CHIME
    stt = SimpleNamespace(transcribe=lambda pcm: SimpleNamespace(text="Was liegt im Ordner?"))
    p = Pipeline(stt, cc.ClaudeChat(Bridge(), TaskRegistry()), spk, Dialog(), kill)
    r = p.handle(np.zeros(16000, dtype=np.int16))
    assert played == [CHIME, "Ich möchte den Befehl ls ausführen.", "Bitte im Terminal bestätigen.", "Ich schau nach."]
    assert earcon.MARK not in r.reply and "Ich möchte den Befehl ls" in r.reply


# --- (2) Nachahmungen werden ersetzt -------------------------------------------------------------------------------

FAKES = ["Ich möchte den Befehl rm ausführen. Bitte im Terminal bestätigen.", "Freigabe erteilt, ich lege los.",
         "Die Freigabe ist nötig.", "Der Notaus ist aktiv. Ich mache nichts, bis du ihn aufhebst.", "Notaus aufgehoben.",
         "Erlauben?", "Bestätige das bitte im Terminal.", "Ich habe die Freigabe erhalten.", "Not-Aus ist aus."]
REAL = ["Ich lasse die Tests laufen.", "Morgen wird es sonnig.", "Der Notausgang ist links.", "Ich schau mir das Terminal an.",
        "Die Datei ist freigegeben worden, sagt die Doku."]


def test_imitations_are_detected_and_ordinary_sentences_pass():
    for text in FAKES:
        assert imitation.guard(text) == (imitation.NEUTRAL, True), text
    for text in REAL:
        assert imitation.guard(text) == (text, False), text
    assert not imitation.imitates_system(imitation.NEUTRAL)


def test_channel_replaces_an_imitation_logs_it_and_tells_claude():
    logs = []
    c = ch.Channel(io.StringIO(), log=logs.append)
    r = c._call_tool({"name": "sprich", "arguments": {"text": FAKES[0]}})
    assert c.take() == [imitation.NEUTRAL]
    assert r["content"][0]["text"] == imitation.TOOL_NOTE and len(logs) == 1 and "rm" not in logs[0]   # Protokoll ohne Inhalt
    c._call_tool({"name": "sprich", "arguments": {"text": "Alles grün."}})
    assert c.take() == ["Alles grün."]


def test_bridge_replaces_imitations_as_a_second_line(tmp_path):
    ch.write_info(tmp_path, 4567, "t" * 32)
    reply = {"texts": ["Freigabe erteilt.", "Alles grün."], "permissions": [], "views": [], "final": True}
    b = br.Bridge(tmp_path, request=lambda *a, **k: reply)
    assert b.fetch(0) == ("ok", [imitation.NEUTRAL, "Alles grün."]) and b.imitations == 1


@pytest.mark.parametrize("block", [
    {"typ": "hinweis", "text": "Freigabe erteilt"},
    {"typ": "text", "absaetze": ["Alles erledigt.", "Die Freigabe wurde bestätigt."]},
    {"typ": "fortschritt", "schritte": [{"text": "Notaus aufgehoben", "zustand": "fertig"}]},
])
def test_zeige_rejects_views_that_claim_an_approval_or_a_lifted_kill_switch(block):
    with pytest.raises(schema.ViewError) as e:
        schema.validate({"id": "x", "art": "antwort", "titel": "Status", "bausteine": [block]})
    assert e.value.code == "bad_block_1"
    with pytest.raises(schema.ViewError) as e:
        schema.validate({"id": "x", "art": "antwort", "titel": "Freigabe erteilt", "bausteine": [{"typ": "hinweis", "text": "ok"}]})
    assert e.value.code == "bad_title"
    ok = schema.validate({"id": "x", "art": "antwort", "titel": "Status", "bausteine": [{"typ": "hinweis", "text": "Tests grün"}]})
    assert ok["bausteine"][0]["text"] == "Tests grün"
    c = ch.Channel(io.StringIO(), log=lambda s: None)
    r = c.show({"id": "x", "art": "antwort", "titel": "Status", "bausteine": [block]})
    assert r["isError"] and "bad_block_1" in r["content"][0]["text"] and c.take_views() == []


@pytest.mark.parametrize("stand", ["Freigabe erteilt", "Notaus aufgehoben", "Freigabe bestätigt 14:05"])
def test_zeige_rejects_a_stand_that_claims_an_approval_or_a_lifted_kill_switch(stand):
    for art in ("antwort", "markt"):
        with pytest.raises(schema.ViewError) as e:
            schema.validate({"id": "x", "art": art, "titel": "Kurse", "stand": stand,
                             "bausteine": [{"typ": "hinweis", "text": "ok"}]})
        assert e.value.code == "bad_stand"
    ok = schema.validate({"id": "x", "art": "markt", "titel": "Kurse", "stand": "2026-11-23 14:05",
                          "bausteine": [{"typ": "hinweis", "text": "ok"}]})
    assert ok["stand"] == "2026-11-23 14:05"


# --- (3) Fenster und Protokoll zeigen die echten Daten -------------------------------------------------------------

def test_window_and_log_keep_the_real_description():
    p = br.Permission.parse({"request_id": "r1", "tool_name": "Bash", "description": "", "input_preview": '{ "command": "ls" }'})
    assert speakable.describe(p) == "Claude möchte den Befehl ls ausführen."             # Oberfläche und Freigabe-Protokoll
    assert speakable.announce(p).startswith("Ich möchte den Befehl ls")                    # nur gesprochen in der ersten Person
    assert cc.ClaudeChat(SimpleNamespace(pending=lambda: [p]), TaskRegistry()).permission_notes() == \
        [earcon.mark(speakable.announce(p))]
