from types import SimpleNamespace

import numpy as np

from kushim.safety.killswitch import KillSwitch
from kushim.voice.dialog import Dialog, State
from kushim.voice.pipeline import Pipeline
from kushim.voice.tts import Speaker


class FakeSTT:
    def __init__(self, text):
        self.text = text

    def transcribe(self, pcm):
        return SimpleNamespace(text=self.text)


class Eng:
    def synthesize(self, t):
        return t


def build(tmp_path, text, chat=None):
    played, stopped = [], []
    dialog = Dialog(lambda: stopped.append(1))
    kill = KillSwitch(tmp_path, [lambda: stopped.append("kill")])
    chat = chat or (lambda msgs: iter(["Hall", "o. Wie ", "geht's?"]))
    spk = Speaker(Eng(), played.append, lambda: kill.fired)
    p = Pipeline(FakeSTT(text), chat, spk, dialog, kill)
    return p, played, dialog, kill


PCM = np.zeros(16000, dtype=np.int16)      # 1 s


def test_normal_turn(tmp_path):
    p, played, dialog, _ = build(tmp_path, "Wie spät ist es")
    r = p.handle(PCM)
    assert r.outcome == "spoken" and played == ["Hallo.", "Wie geht's?"]
    assert dialog.state is State.IDLE and p.history[0]["content"] == "Wie spät ist es"


def test_kill_phrase_skips_llm_and_halts(tmp_path):
    called = []
    p, played, dialog, kill = build(tmp_path, "Kushim Notaus", chat=lambda m: called.append(1) or iter([]))
    r = p.handle(PCM)
    assert r.outcome == "killed" and not called and not played
    assert kill.fired and dialog.state is State.HALTED
    assert p.handle(PCM).outcome == "halted"


def test_any_voice_is_answered_without_speaker_check(tmp_path):
    p, played, _, _ = build(tmp_path, "Hallo")
    assert p.handle(np.zeros(4000, dtype=np.int16)).outcome == "spoken" and played     # auch kurz, auch fremd


def test_empty_transcript(tmp_path):
    p, played, _, _ = build(tmp_path, "")
    assert p.handle(PCM).outcome == "empty" and not played


def test_external_marker_blocks(tmp_path):
    from kushim.safety import killswitch
    p, played, _, _ = build(tmp_path, "Hallo")
    killswitch.trigger(tmp_path)
    assert p.handle(PCM).outcome == "halted" and not played


def test_history_is_bounded(tmp_path):
    seen = []
    p, *_ = build(tmp_path, "Hi", chat=lambda m: seen.append(len(m)) or iter(["Ok."]))
    for _ in range(10):
        p.handle(PCM)
    assert max(seen) <= 7   # System + 6


from kushim.voice.pipeline import strip_wake_words

NAMES = ("hey kushim", "kushim", "kush", "hallo kush", "hi kushim", "kushi")


def test_strip_wake_words():
    s = lambda t: strip_wake_words(t, NAMES)
    assert s("Hey Kushim, schau mir das nach.") == "schau mir das nach."
    assert s("Hey Kuschim schau mir das nach") == "schau mir das nach"        # Whisper schreibt es anders
    assert s("kushim") == "" and s("Hey Kushim.") == "" and s("Hallo Kush!") == ""
    assert s("Hey Kushim hey kushim wie spät ist es") == "wie spät ist es"      # höchstens zweimal
    assert s("Wie spät ist es, Kushim?") == "Wie spät ist es, Kushim?"          # nur am Anfang
    assert s("Kuss mich nicht") == "Kuss mich nicht"                            # ähnliches Wort ist kein Wake Word
    assert strip_wake_words("  Hallo  ", ()) == "Hallo"


def test_pipeline_strips_wake_word_before_llm_and_reports_wake_only(tmp_path):
    seen = []
    p, played, _, _ = build(tmp_path, "Hey Kushim, wie spät ist es?",
                            chat=lambda m: seen.append(m) or iter(["Es ist spät."]))
    p.wake_names = NAMES
    r = p.handle(PCM)
    assert r.outcome == "spoken" and p.history[0]["content"] == "wie spät ist es?"
    p2, played2, _, _ = build(tmp_path, "Hey Kushim.", chat=lambda m: seen.append("nie") or iter([]))
    p2.wake_names = NAMES
    r2 = p2.handle(PCM)
    assert r2.outcome == "wake_only" and r2.heard == "" and not played2 and "nie" not in seen


def test_kill_phrase_after_wake_word_still_kills(tmp_path):
    p, played, _, kill = build(tmp_path, "Hey Kushim, Notaus")
    p.wake_names = NAMES
    assert p.handle(PCM).outcome == "killed" and kill.fired


def test_whisper_spellings_of_hey_still_count_as_wake_word():
    from kushim.voice.pipeline import strip_wake_words
    names = ["hey kushim", "kushim"]
    assert strip_wake_words("Hej, kushim.", names) == ""                               # Live-Test 2026-11-11
    assert strip_wake_words("Hei Kushim, lass die Tests laufen", names) == "lass die Tests laufen"
    assert strip_wake_words("Hey, wie spät ist es?", names) == "Hey, wie spät ist es?"   # ohne kushim kein Wake Word


def test_whole_messages_are_spoken_at_once_not_held_back_until_the_next_one(tmp_path):
    import threading
    gate = threading.Event()
    played_at = []

    class Chat:
        yields_messages = True

        def __call__(self, messages):
            yield "Ich geb's an Claude."
            self.heard_before_reply = gate.wait(2)         # Claude arbeitet noch: die Quittung muss jetzt schon laufen
            yield "Fertig. Alles grün."
    chat = Chat()
    p, played, _, _ = build(tmp_path, "Lass die Tests laufen", chat=chat)
    p.speaker.play = lambda wav: (played_at.append(wav), gate.set() if wav == "Ich geb's an Claude." else None)
    r = p.handle(PCM)
    assert chat.heard_before_reply is True                 # früher: Quittung erst nach Claudes Antwort (Live-Test 2026-11-11)
    assert played_at == ["Ich geb's an Claude.", "Fertig.", "Alles grün."] and r.outcome == "spoken"


# --- Live-Transkript: Zeile „Du“ direkt nach der Spracherkennung, Status und Grund je Ausstieg

from kushim.voice.transcript import Transcript


def noted(tmp_path, text, chat=None, commands=None):
    p, played, dialog, kill = build(tmp_path, text, chat=chat)
    p.wake_names = NAMES
    p.commands = commands
    p.notes = Transcript()
    return p, played


def only(p):
    items = p.notes.since(0)
    assert len(items) == 1, items
    return items[0]


class Commands:
    def handle(self, text, verified, strong, score=None):
        return "Timer steht." if "timer" in text.lower() else None


class Bridge:
    def __init__(self, status, seen):
        self.status, self.seen = status, seen

    def send(self, text):
        self.seen.append(self.notes.since(0)[-1]["status"])        # Zustand in dem Moment, in dem gesendet wird
        return self.status

    def fetch(self, wait=0.0):
        return "ok", ["Erledigt."]

    def pending(self):
        return []


def test_entry_is_pending_before_the_chat_is_called_and_sent_afterwards(tmp_path):
    seen = []

    def chat(messages):
        seen.append(only(p))
        return iter(["Zehn Uhr."])
    p, _ = noted(tmp_path, "Hey Kushim, wie spät ist es?", chat=chat)
    r = p.handle(PCM)
    assert seen[0]["status"] == "pending" and seen[0]["heard"] == "wie spät ist es?" and seen[0]["raw"] == "Hey Kushim, wie spät ist es?"
    e = only(p)
    assert r.entry == e["id"] and e["status"] == "sent" and e["sent_ts"] is not None and e["reason"] == ""


def test_claude_chat_reports_the_send_status_through_its_hook(tmp_path):
    from kushim.tasks import TaskRegistry
    from kushim.voice.claude_chat import ClaudeChat
    for status, want in (("ok", ("sent", "")), ("not_running", ("dropped", "not_running")), ("kill", ("dropped", "killed")),
                         ("error", ("dropped", "send_failed"))):
        seen = []
        bridge = Bridge(status, seen)
        chat = ClaudeChat(bridge, TaskRegistry())
        p, _ = noted(tmp_path, "Mach die Tests grün", chat=chat)
        bridge.notes = p.notes
        r = p.handle(PCM)
        e = only(p)
        assert seen == ["pending"], status                          # erst nach bridge.send ändert sich der Status
        assert (e["status"], e["reason"]) == want and r.entry == e["id"], status
        assert (e["sent_ts"] is not None) == (status == "ok")


def test_every_early_exit_sets_dropped_with_its_reason(tmp_path):
    cases = [("Hey Kushim.", "wake_only", "wake_only"), ("Hey Kushim, abbrechen", "cancelled", "cancelled"),
             ("Stell einen Timer", "command", "command"), ("das wars", "end_conversation", "end_conversation"),
             ("Beende dich", "shutdown", "shutdown")]
    for text, outcome, reason in cases:
        called = []
        p, _ = noted(tmp_path, text, chat=lambda m: called.append(1) or iter(["x"]), commands=Commands())
        r = p.handle(PCM)
        e = only(p)
        assert r.outcome == outcome and not called, text
        assert (e["status"], e["reason"], e["raw"], r.entry) == ("dropped", reason, text, e["id"]), text


def test_wake_only_keeps_the_raw_text_and_cancel_keeps_the_command(tmp_path):
    p, _ = noted(tmp_path, "Hey Kushim.")
    p.handle(PCM)
    assert (only(p)["heard"], only(p)["raw"]) == ("", "Hey Kushim.")
    p, _ = noted(tmp_path, "Hey Kushim, abbrechen")
    p.handle(PCM)
    assert only(p)["heard"] == "abbrechen"


def test_halted_dialog_drops_with_reason_halted(tmp_path):
    p, _ = noted(tmp_path, "Wie spät ist es")
    p.dialog.triggered = lambda: False
    r = p.handle(PCM)
    assert r.outcome == "halted" and (only(p)["status"], only(p)["reason"]) == ("dropped", "halted")


def test_kill_phrase_leaves_an_entry_without_text(tmp_path):
    p, _ = noted(tmp_path, "Hey Kushim, Notaus")
    r = p.handle(PCM)
    e = only(p)
    assert r.outcome == "killed" and p.kill.fired and r.entry == e["id"]
    assert (e["heard"], e["raw"], e["status"], e["reason"]) == ("", "", "dropped", "killed")


def test_empty_and_already_halted_leave_no_entry(tmp_path):
    p, _ = noted(tmp_path, "")
    assert p.handle(PCM).outcome == "empty" and p.notes.since(0) == []
    from kushim.safety import killswitch
    p, _ = noted(tmp_path, "Hallo")
    killswitch.trigger(tmp_path)
    assert p.handle(PCM).outcome == "halted" and p.notes.since(0) == []


def test_a_failing_chat_marks_send_failed_and_still_raises(tmp_path):
    import pytest

    def chat(messages):
        raise RuntimeError("kaputt")
    p, _ = noted(tmp_path, "Wie spät ist es", chat=chat)
    with pytest.raises(RuntimeError):
        p.handle(PCM)
    assert (only(p)["status"], only(p)["reason"]) == ("dropped", "send_failed")


def test_a_broken_notes_hook_never_disturbs_the_turn(tmp_path):
    class Broken:
        def __getattr__(self, name):
            raise RuntimeError("Anzeige kaputt")
    for text, outcome in (("Wie spät ist es", "spoken"), ("Hey Kushim.", "wake_only"), ("Hey Kushim, Notaus", "killed"),
                          ("abbrechen", "cancelled")):
        (tmp_path / outcome).mkdir()
        p, played = noted(tmp_path / outcome, text)
        p.notes = Broken()
        r = p.handle(PCM)
        assert r.outcome == outcome and r.entry is None, text
    p, played = noted(tmp_path, "Wie spät ist es")
    p.notes.sent = lambda entry: 1 / 0                                  # nur ein Haken wirft
    assert p.handle(PCM).outcome == "spoken" and played and only(p)["status"] == "pending"


def test_try_cancel_during_a_reply_leaves_its_own_dropped_entry(tmp_path):
    p, played = noted(tmp_path, "Hey Kushim, abbrechen")
    assert p.try_cancel(PCM) is True
    e = only(p)
    assert (e["heard"], e["raw"], e["status"], e["reason"], e["reply"]) == ("abbrechen", "Hey Kushim, abbrechen", "dropped",
                                                                             "cancelled", "")
    p, _ = noted(tmp_path, "Wie spät ist es")
    assert p.try_cancel(PCM) is False and p.notes.since(0) == []      # keine Absage: die Runde legt ihren Eintrag selbst an


def test_result_completes_the_same_entry_instead_of_adding_one(tmp_path):
    p, _ = noted(tmp_path, "Wie spät ist es")
    r = p.handle(PCM)
    p.notes.add(r)
    e = only(p)
    assert e["reply"] == "Hallo. Wie geht's?" and e["outcome"] == "spoken" and e["status"] == "sent"


def test_talk_log_gets_no_new_fields(tmp_path):
    import json
    from kushim.voice.talklog import TalkLog
    p, _ = noted(tmp_path, "Wie spät ist es")
    log = TalkLog(tmp_path / "talk.log")
    log.timed(p.handle)(PCM)
    line = json.loads((tmp_path / "talk.log").read_text(encoding="utf-8").splitlines()[-1])
    assert set(line) == {"ts", "event", "heard", "reply", "outcome", "detail", "seconds"}
