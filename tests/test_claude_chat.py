"""Antwortweg über Claude Code in der Sprachkette (src/kushim/voice/claude_chat.py, Roadmap v2 B4)."""
import io
import json
import threading
from collections import deque

from kushim.channel import bridge as br
from kushim.channel import server as ch
from kushim.tasks import TaskRegistry
from kushim.voice import claude_chat as cc
from kushim.voice import earcon

M = earcon.MARK                      # Signalton vor kushims eigenen Ansagen


def ask(cmd):
    """Freigabe-Ansage, wie kushim sie kennzeichnet (jeder Satz einzeln)."""
    return earcon.mark(f"Ich möchte den Befehl {cmd} ausführen. Bitte im Terminal bestätigen.")

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
    assert b.sent == ["Mach die Tests grün"] and out == ["Erledigt.", "Alles grün."]               # getrennte Stücke; keine feste Quittung mehr
    assert b.fetches == [cc.POLL, cc.POLL] and tasks.active() == []                  # Aufgabe ist danach wieder weg


def test_honest_messages_when_claude_is_missing_killed_or_broken():
    for status, msg in (("not_running", cc.NOT_RUNNING), ("kill", earcon.mark(cc.KILLED)), ("error", cc.FAILED)):
        b = FakeBridge(send=status)
        assert list(cc.ClaudeChat(b, TaskRegistry())(MSGS)) == [msg] and b.fetches == []
    assert list(cc.ClaudeChat(FakeBridge(replies=[("kill", [])]), TaskRegistry())(MSGS)) == [earcon.mark(cc.KILLED)]   # Systemansage: mit Signalton
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
    assert chat.announcement() == ["Fertig nach langer Arbeit."]
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
    assert list(chat(MSGS)) == [ask("npm test")]
    b.fetch = lambda wait=0.0: ("ok", ["Tests laufen durch."])
    assert chat.announcement() == ["Tests laufen durch."]                             # die Anfrage wird nicht wiederholt


def test_idle_announcement_reads_new_permission_requests_once():
    clock = Clock()
    b = FakeBridge()
    chat = cc.ClaudeChat(b, TaskRegistry(), clock=clock)
    b.permissions.extend([perm("r1", "ls"), perm("r2", "git status")])
    assert chat.announcement() == [ask("ls"), ask("git status")]                 # getrennte Stücke, nie ein String
    clock.t += cc.ANNOUNCE_EVERY
    assert chat.announcement() is None                                              # schon angesagt
    clock.t += cc.ANNOUNCE_EVERY
    b.replies = [("ok", ["Fertig."])]
    b.permissions.append(perm("r3", "pwd"))
    assert chat.announcement() == [ask("pwd"), "Fertig."]


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
        assert chat.announcement() == [ask("npm test")]
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
    assert chat.announcement() == ["Doch noch: morgen wird es sonnig."]


def test_cancel_still_reaches_claude_after_silent_and_late_until_a_result_arrives():
    """Safety-Audit 2026-11-23: Nach SILENT oder LATE arbeitet Claude vielleicht weiter; "abbrechen" muss es weiter erreichen."""
    for patience, ending in ((cc.PATIENCE, cc.SILENT), (10, cc.LATE)):
        clock = Clock()
        b = FakeBridge()
        silent_then(clock, b, 10_000)
        tasks = TaskRegistry()
        chat = cc.ClaudeChat(b, tasks, patience=patience, clock=clock)
        assert list(chat(MSGS))[-1] == ending
        assert tasks.active() == [cc.TASK_NAME] and chat.request_open()            # Runde vorbei, Anfrage noch offen
        assert tasks.cancel_all() == [cc.TASK_NAME] and b.cancels == 1              # kind="cancel" geht an Claude
        assert tasks.active() == [] and not chat.request_open()                     # danach ehrlich: nichts läuft mehr
    assert "abbrechen" in cc.SILENT and "noch einmal" not in cc.SILENT


def test_the_open_request_closes_with_the_result_the_late_result_or_the_kill_switch():
    clock = Clock()
    b = FakeBridge(replies=[("ok", ["Fertig."])])
    tasks = TaskRegistry()
    chat = cc.ClaudeChat(b, tasks, clock=clock)
    assert list(chat(MSGS)) == ["Fertig."] and tasks.active() == []                 # Ergebnis in der Runde
    silent_then(clock, b, 10_000)
    list(chat(MSGS))
    assert chat.request_open()
    clock.t += cc.ANNOUNCE_EVERY
    b.last_final = False
    b.fetch = lambda wait=0.0: ("ok", ["Ich bin halb durch."])
    assert chat.announcement() == ["Ich bin halb durch."] and chat.request_open()      # nur Zwischenstand: bleibt offen
    clock.t += cc.ANNOUNCE_EVERY
    b.last_final = True
    b.fetch = lambda wait=0.0: ("ok", ["Jetzt fertig."])
    assert chat.announcement() == ["Jetzt fertig."] and not chat.request_open() and tasks.active() == []
    silent_then(clock, b, 10_000)
    list(chat(MSGS))
    clock.t += cc.ANNOUNCE_EVERY
    b.fetch = lambda wait=0.0: ("kill", [])
    chat.announcement()
    assert not chat.request_open()                                                  # Notaus: nichts mehr offen


def test_a_new_request_replaces_the_old_open_one():
    clock = Clock()
    b = FakeBridge()
    tasks = TaskRegistry()
    chat = cc.ClaudeChat(b, tasks, clock=clock)
    for _ in range(3):
        silent_then(clock, b, 10_000)
        list(chat(MSGS))
    assert tasks.active() == [cc.TASK_NAME]


def test_pipeline_cancel_after_silent_confirms_and_tells_claude(tmp_path):
    from types import SimpleNamespace
    import numpy as np
    from kushim.safety.killswitch import KillSwitch
    from kushim.voice import pipeline as pl
    from kushim.voice.dialog import Dialog
    from kushim.voice.tts import Speaker
    clock = Clock()
    b = FakeBridge()
    silent_then(clock, b, 10_000)
    tasks = TaskRegistry()
    heard = {"text": "Recherchiere das bitte gründlich."}
    played = []
    kill = KillSwitch(tmp_path, [])
    stt = SimpleNamespace(transcribe=lambda pcm: SimpleNamespace(text=heard["text"]))
    p = pl.Pipeline(stt, cc.ClaudeChat(b, tasks, clock=clock), Speaker(SimpleNamespace(synthesize=lambda t: t), played.append),
                    Dialog(), kill, tasks=tasks)
    pcm = np.zeros(16000, dtype=np.int16)
    assert p.handle(pcm).reply.endswith(cc.SILENT)
    heard["text"] = "Abbrechen."
    r = p.handle(pcm)
    assert r.outcome == "cancelled" and r.reply == pl.CANCEL_REPLY and b.cancels == 1      # nicht „Es läuft nichts …“
    assert p.handle(pcm).reply == pl.NOTHING_REPLY                                          # jetzt stimmt es


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
