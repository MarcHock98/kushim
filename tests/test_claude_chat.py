"""Antwortweg über Claude Code in der Sprachkette (src/kushim/voice/claude_chat.py, Roadmap v2 B4)."""
import io
import json
import threading

from kushim.channel import bridge as br
from kushim.channel import server as ch
from kushim.tasks import TaskRegistry
from kushim.voice import claude_chat as cc

MSGS = [{"role": "system", "content": "egal"}, {"role": "user", "content": "alt"},
        {"role": "assistant", "content": "x"}, {"role": "user", "content": "Mach die Tests grün"}]


class FakeBridge:
    def __init__(self, send="ok", replies=(), available=True):
        self.sent, self._send, self.replies, self._available, self.fetches = [], send, list(replies), available, []

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
    assert b.sent == ["Mach die Tests grün"] and out == [cc.ACK, "Erledigt. Alles grün."]
    assert b.fetches == [cc.POLL, cc.POLL] and tasks.active() == []                  # Aufgabe ist danach wieder weg


def test_honest_messages_when_claude_is_missing_killed_or_broken():
    for status, msg in (("not_running", cc.NOT_RUNNING), ("kill", cc.KILLED), ("error", cc.FAILED)):
        b = FakeBridge(send=status)
        assert list(cc.ClaudeChat(b, TaskRegistry())(MSGS)) == [msg] and b.fetches == []
    assert list(cc.ClaudeChat(FakeBridge(replies=[("kill", [])]), TaskRegistry())(MSGS)) == [cc.ACK, cc.KILLED]
    assert list(cc.ClaudeChat(FakeBridge(replies=[("not_running", [])]), TaskRegistry())(MSGS)) == [cc.ACK, cc.LOST]


def test_waiting_is_a_cancellable_task_and_cancel_stops_quietly():
    tasks = TaskRegistry()
    b = FakeBridge()
    gen = cc.ClaudeChat(b, tasks)(MSGS)
    assert next(gen) == cc.ACK
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
    assert list(chat(MSGS)) == [cc.ACK, cc.LATE]
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
        assert spoken == [cc.ACK, "Die Tests sind grün."]
        assert json.loads(out.getvalue().splitlines()[-1])["params"]["content"] == "Mach die Tests grün"
    finally:
        httpd.shutdown()
