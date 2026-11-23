"""Antwortweg über Claude Code in der Sprachkette (src/kushim/voice/claude_chat.py, Roadmap v2 B4)."""
import io
import json
import threading
from collections import deque

from kushim.channel import bridge as br
from kushim.channel import server as ch
from kushim.tasks import TaskRegistry
from kushim.voice import claude_chat as cc

MSGS = [{"role": "system", "content": "egal"}, {"role": "user", "content": "alt"},
        {"role": "assistant", "content": "x"}, {"role": "user", "content": "Mach die Tests grün"}]


class FakeBridge:
    def __init__(self, send="ok", replies=(), available=True):
        self.sent, self._send, self.replies, self._available, self.fetches = [], send, list(replies), available, []
        self.permissions = deque()

    def pending(self):
        return list(self.permissions)

    def available(self):
        return self._available

    def cancel(self):
        self.cancels = getattr(self, "cancels", 0) + 1
        return "ok"

    def send(self, text):
        self.sent.append(text)
        return self._send

    def fetch(self, wait=0.0):
        self.fetches.append(wait)
        return self.replies.pop(0) if self.replies else ("ok", [])


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_sends_only_the_last_user_text_acknowledges_and_speaks_the_reply():
    b = FakeBridge(replies=[("ok", []), ("ok", ["Erledigt.", "Alles grün."])])
    tasks = TaskRegistry()
    out = list(cc.ClaudeChat(b, tasks)(MSGS))
    assert b.sent == ["Mach die Tests grün"] and out == ["Erledigt. Alles grün."]                    # keine feste Quittung mehr
    assert b.fetches == [cc.POLL, cc.POLL] and tasks.active() == []                  # Aufgabe ist danach wieder weg


def test_honest_messages_when_claude_is_missing_killed_or_broken():
    for status, msg in (("not_running", cc.NOT_RUNNING), ("kill", cc.KILLED), ("error", cc.FAILED)):
        b = FakeBridge(send=status)
        assert list(cc.ClaudeChat(b, TaskRegistry())(MSGS)) == [msg] and b.fetches == []
    assert list(cc.ClaudeChat(FakeBridge(replies=[("kill", [])]), TaskRegistry())(MSGS)) == [cc.KILLED]
    assert list(cc.ClaudeChat(FakeBridge(replies=[("not_running", [])]), TaskRegistry())(MSGS)) == [cc.LOST]


def test_waiting_is_a_cancellable_task_and_cancel_stops_quietly():
    tasks = TaskRegistry()
    b = FakeBridge()
    gen = cc.ClaudeChat(b, tasks)(MSGS)
    b.fetch = lambda wait=0.0: (tasks.cancel_all(), ("ok", []))[1]                   # Nutzer sagt "abbrechen" während des Wartens
    assert list(gen) == [] and tasks.active() == []
    assert b.cancels == 1                                                           # Claude bekommt die Abbruch-Nachricht


def test_long_work_ends_the_turn_with_a_note_and_the_reply_comes_later():
    clock = Clock()
    b = FakeBridge()

    def slow_fetch(wait=0.0):
        clock.t += wait
        return "ok", []
    b.fetch = slow_fetch
    chat = cc.ClaudeChat(b, TaskRegistry(), patience=10, clock=clock)
    assert list(chat(MSGS)) == [cc.FILLERS[0], cc.LATE]
    b.fetch = lambda wait=0.0: ("ok", ["Fertig nach langer Arbeit."])
    assert chat.announcement() == "Fertig nach langer Arbeit."
    assert chat.announcement() is None                                              # gedrosselt: höchstens alle 2 s
    clock.t += cc.ANNOUNCE_EVERY
    b.fetch = lambda wait=0.0: ("ok", [])
    assert chat.announcement() is None


def test_announcement_does_nothing_without_a_channel():
    b = FakeBridge(available=False)
    assert cc.ClaudeChat(b, TaskRegistry()).announcement() is None and b.fetches == []


def test_through_the_real_channel(tmp_path):
    out = io.StringIO()
    c = ch.Channel(out, log=lambda s: None)
    c.ready.set()
    httpd = ch.make_http(c, tmp_path, "t" * 32)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    ch.write_info(tmp_path, httpd.server_address[1], "t" * 32)
    try:
        threading.Timer(0.3, lambda: c.say("Die Tests sind grün.")).start()        # Claude ruft sprich auf
        spoken = list(cc.ClaudeChat(br.Bridge(tmp_path), TaskRegistry())(MSGS))
        assert spoken == ["Die Tests sind grün."]
        assert json.loads(out.getvalue().splitlines()[-1])["params"]["content"] == "Mach die Tests grün"
    finally:
        httpd.shutdown()


def perm(rid, cmd):
    return br.Permission.parse({"request_id": rid, "tool_name": "Bash", "description": "",
                                "input_preview": '{ "command": "%s" }' % cmd})


def test_a_permission_request_ends_the_turn_so_the_loop_can_listen_and_the_reply_comes_later():
    clock = Clock()
    b = FakeBridge()
    replies = [("ok", []), ("ok", [])]

    def fetch(wait=0.0):
        if len(replies) == 1:
            b.permissions.append(perm("r1", "npm test"))                           # Claude fragt im Terminal nach
        return replies.pop(0)
    b.fetch = fetch
    chat = cc.ClaudeChat(b, TaskRegistry(), clock=clock)
    assert list(chat(MSGS)) == ["Ich möchte den Befehl npm test ausführen. Bitte im Terminal bestätigen."]
    b.fetch = lambda wait=0.0: ("ok", ["Tests laufen durch."])
    assert chat.announcement() == "Tests laufen durch."                             # die Anfrage wird nicht wiederholt


def test_idle_announcement_reads_new_permission_requests_once():
    clock = Clock()
    b = FakeBridge()
    chat = cc.ClaudeChat(b, TaskRegistry(), clock=clock)
    b.permissions.extend([perm("r1", "ls"), perm("r2", "git status")])
    assert chat.announcement() == ("Ich möchte den Befehl ls ausführen. Bitte im Terminal bestätigen. "
                                   "Ich möchte den Befehl git status ausführen. Bitte im Terminal bestätigen.")
    clock.t += cc.ANNOUNCE_EVERY
    assert chat.announcement() is None                                              # schon angesagt
    clock.t += cc.ANNOUNCE_EVERY
    b.replies = [("ok", ["Fertig."])]
    b.permissions.append(perm("r3", "pwd"))
    assert chat.announcement() == "Ich möchte den Befehl pwd ausführen. Bitte im Terminal bestätigen. Fertig."


def test_through_the_real_channel_a_permission_request_is_spoken(tmp_path):
    out = io.StringIO()
    c = ch.Channel(out, log=lambda s: None)
    c.ready.set()
    httpd = ch.make_http(c, tmp_path, "t" * 32)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    ch.write_info(tmp_path, httpd.server_address[1], "t" * 32)
    try:
        c.permission_request({"request_id": "abcde", "tool_name": "Bash", "description": "Run tests",
                              "input_preview": '{ "command": "npm test", "description": "Run tests" }'})
        chat = cc.ClaudeChat(br.Bridge(tmp_path), TaskRegistry())
        assert chat.announcement() == "Ich möchte den Befehl npm test ausführen. Bitte im Terminal bestätigen."
    finally:
        httpd.shutdown()


def test_claude_says_its_plan_first_and_the_result_follows_in_the_same_turn():
    b = FakeBridge()
    steps = [("ok", ["Ich lasse die Tests laufen."], False), ("ok", [], True), ("ok", ["Alles grün."], True)]

    def fetch(wait=0.0):
        status, texts, final = steps.pop(0)
        b.last_final = final
        return status, texts
    b.fetch = fetch
    assert list(cc.ClaudeChat(b, TaskRegistry())(MSGS)) == ["Ich lasse die Tests laufen.", "Alles grün."]


def silent_then(clock, b, reply_at_call, reply="Fertig."):
    calls = {"n": 0, "said_at": []}

    def fetch(wait=0.0):
        clock.t += wait
        calls["n"] += 1
        b.last_final = True
        return ("ok", [reply]) if calls["n"] == reply_at_call else ("ok", [])
    b.fetch = fetch
    return calls


def test_short_filler_only_if_claude_stays_silent_for_a_while():
    clock = Clock()
    b = FakeBridge()
    silent_then(clock, b, 7)
    chat = cc.ClaudeChat(b, TaskRegistry(), clock=clock)
    gen = chat(MSGS)
    first = next(gen)
    assert first == cc.FILLERS[0] and clock.t == cc.FILLER_AFTER                    # pünktlich nach 2,5 s, nicht erst nach 4 s
    out = [first, *gen]
    assert out == [cc.FILLERS[0], "Fertig."] and out.count(cc.FILLERS[0]) == 1        # höchstens einmal je Runde
    assert cc.FILLER_AFTER == 2.5


def test_a_turn_without_any_sprich_ends_with_a_short_first_person_line_and_a_late_reply_still_comes():
    clock = Clock()
    b = FakeBridge()
    silent_then(clock, b, 10_000)                                                    # Claude sagt nie etwas
    chat = cc.ClaudeChat(b, TaskRegistry(), clock=clock)
    assert list(chat(MSGS)) == [cc.FILLERS[0], cc.SILENT]
    assert cc.SILENT_AFTER <= clock.t < cc.SILENT_AFTER + cc.POLL + 0.01             # nach 25 s, nicht erst nach 180 s
    clock.t += cc.ANNOUNCE_EVERY
    b.fetch = lambda wait=0.0: ("ok", ["Doch noch: morgen wird es sonnig."])
    assert chat.announcement() == "Doch noch: morgen wird es sonnig."


def test_after_a_zwischenstand_long_work_is_not_cut_off_by_the_silence_guard():
    clock = Clock()
    b = FakeBridge()
    calls = {"n": 0}

    def fetch(wait=0.0):
        clock.t += wait
        calls["n"] += 1
        b.last_final = calls["n"] != 1
        return ("ok", ["Ich lasse die Tests laufen."]) if calls["n"] == 1 else ("ok", ["Alles grün."]) if clock.t >= 60 else ("ok", [])
    b.fetch = fetch
    assert list(cc.ClaudeChat(b, TaskRegistry(), clock=clock)(MSGS)) == ["Ich lasse die Tests laufen.", "Alles grün."]


def test_fillers_rotate_deterministically_across_turns():
    clock = Clock()
    b = FakeBridge()
    chat = cc.ClaudeChat(b, TaskRegistry(), clock=clock)
    said = []
    for _ in range(4):
        silent_then(clock, b, 3)
        said.append(list(chat(MSGS))[0])
    assert said == [cc.FILLERS[0], cc.FILLERS[1], cc.FILLERS[2], cc.FILLERS[0]]


def test_no_filler_when_claude_answers_quickly_or_says_its_plan_first():
    clock = Clock()
    b = FakeBridge()
    silent_then(clock, b, 1, "Hallo, schön dich zu hören.")                          # erstes sprich nach 2 s
    assert list(cc.ClaudeChat(b, TaskRegistry(), clock=clock)(MSGS)) == ["Hallo, schön dich zu hören."]
    steps = [("ok", ["Ich schau in die Tests."], False), ("ok", [], False), ("ok", [], False), ("ok", ["Alles grün."], True)]

    def fetch(wait=0.0):
        clock.t += wait
        status, texts, final = steps.pop(0)
        b.last_final = final
        return status, texts
    b.fetch = fetch
    assert list(cc.ClaudeChat(b, TaskRegistry(), clock=clock)(MSGS)) == ["Ich schau in die Tests.", "Alles grün."]


def test_nothing_kushim_says_by_itself_mentions_claude_or_forwarding():
    from kushim.channel import speakable
    from kushim.voice import pipeline, talk
    texts = [*cc.FILLERS, cc.NOT_RUNNING, cc.KILLED, cc.FAILED, cc.LATE, cc.LOST, cc.SILENT, talk.ACK_TEXT, pipeline.CANCEL_REPLY,
             pipeline.NOTHING_REPLY, pipeline.END_REPLY, pipeline.SHUTDOWN_REPLY,
             speakable.announce(perm("r1", "npm test")), speakable.announce(perm("r2", "ls"), ask=True)]
    for text in texts:
        low = text.lower()
        assert "claude" not in low and "weiter" not in low and "geb's" not in low and "gebe " not in low, text
    assert all(len(f.split()) <= 3 for f in cc.FILLERS)                              # kurz und natürlich
