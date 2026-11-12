"""Freigaben per Stimme (src/kushim/voice/permission_voice.py, Roadmap v2 C3)."""
from collections import deque

from kushim.channel import speakable
from kushim.channel.bridge import Permission
from kushim.voice import permission_voice as pv

YES = "Ja, das erlaube ich."


def perm(rid="r1", cmd="npm test", tool="Bash", preview=None):
    return Permission.parse({"request_id": rid, "tool_name": tool, "description": "",
                             "input_preview": preview if preview is not None else '{ "command": "%s" }' % cmd})


class FakeBridge:
    def __init__(self, status="ok"):
        self.permissions, self.answers, self.status = deque(), [], status

    def answer(self, rid, behavior):
        self.answers.append((rid, behavior))
        return self.status


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def allow_all(p):
    return None


def voice(bridge=None, blocked=allow_all, clock=None, log=None):
    return pv.PermissionVoice(bridge or FakeBridge(), blocked=blocked, clock=clock or Clock(),
                              on_decision=(log.append if log is not None else lambda d: None))


def test_strong_yes_allows_exactly_the_asked_request_once():
    b, log = FakeBridge(), []
    v = voice(b, log=log)
    assert v.offer(perm()) == "Claude möchte den Befehl npm test ausführen. Erlauben? " + pv.HOW
    assert v.awaiting
    assert v.handle(YES, verified=True, strong=True) == pv.ALLOWED
    assert b.answers == [("r1", "allow")] and not v.awaiting
    assert v.handle(YES, verified=True, strong=True) is None                         # nichts mehr offen: geht an Claude
    what = "Claude möchte den Befehl npm test ausführen."
    assert log == [{"request_id": "r1", "tool": "Bash", "what": what, "result": "asked", "source": "voice"},
                   {"request_id": "r1", "tool": "Bash", "what": what, "result": "allowed", "source": "voice",
                    "verified": True, "strong": True, "score": None}]


def test_weak_or_unverified_yes_never_sends_anything():
    b = FakeBridge()
    v = voice(b)
    v.offer(perm())
    assert v.handle("ja", verified=True, strong=False) == pv.NEED_STRONG and v.awaiting       # darf es nochmal sagen
    assert v.handle(YES, verified=False, strong=False) == pv.NEED_VOICE and not v.awaiting
    assert b.answers == []


def test_no_silence_and_timeout_send_nothing_and_leave_the_terminal_open():
    b, clock = FakeBridge(), Clock()
    v = voice(b, clock=clock)
    v.offer(perm())
    assert v.handle("Nein, lieber nicht", verified=True, strong=True) == pv.NOT_SENT and not v.awaiting
    v.offer(perm("r2"))
    clock.t += pv.ASK_TTL + 1                                                        # Stille bis zum Zeitablauf
    assert not v.awaiting and v.handle(YES, verified=True, strong=True) is None
    assert b.answers == []


def test_unclear_sentences_are_not_an_answer_and_go_on_to_claude():
    b = FakeBridge()
    v = voice(b)
    v.offer(perm())
    for text in ("Wie spät ist es?", "Ja, aber nicht jetzt", "Ja ja ja ja ja ja ja ja", "Erlaube es nicht"):
        assert v.handle(text, verified=True, strong=True) in (None, pv.NOT_SENT)
    assert b.answers == []


def test_incomplete_or_blocked_requests_are_only_announced_for_the_terminal():
    v = voice()
    long_cmd = perm(cmd="python -m pytest " + "tests/test_x.py " * 10)
    truncated = perm(preview='{ "command": "rm -rf build && ech…')
    mcp = perm(tool="mcp__x__send", preview="{ }")
    for p in (long_cmd, truncated, mcp):
        assert v.offer(p).endswith(speakable.TERMINAL) and not v.awaiting
    blocked = voice(blocked=lambda p: "gesperrt")
    assert blocked.offer(perm()).endswith(speakable.TERMINAL) and not blocked.awaiting


def test_without_a_blocklist_everything_is_blocked():
    v = pv.PermissionVoice(FakeBridge())
    assert v.offer(perm()).endswith(speakable.TERMINAL) and not v.awaiting


def test_a_newer_request_replaces_the_question():
    b = FakeBridge()
    v = voice(b)
    v.offer(perm("r1"))
    v.offer(perm("r2", preview='{ "command": "x…'))                                   # neue, nicht fragbare Anfrage
    assert not v.awaiting and v.handle(YES, verified=True, strong=True) is None
    v.offer(perm("r3"))
    v.handle(YES, verified=True, strong=True)
    assert b.answers == [("r3", "allow")]


def test_blocklist_is_checked_again_right_before_allowing():
    b, verdict = FakeBridge(), {"r": None}
    v = voice(b, blocked=lambda p: verdict["r"])
    v.offer(perm())
    verdict["r"] = "inzwischen gesperrt"
    assert v.handle(YES, verified=True, strong=True) == speakable.TERMINAL and b.answers == []


def test_honest_replies_when_the_channel_answers_differently():
    for status, msg in (("unknown", pv.GONE), ("kill", pv.KILLED), ("not_running", pv.FAILED), ("error", pv.FAILED)):
        v = voice(FakeBridge(status))
        v.offer(perm())
        assert v.handle(YES, verified=True, strong=True) == msg


def test_yes_and_no_words():
    assert pv.is_yes("Ja, das erlaube ich.") and pv.is_yes("Ja, erlauben!") and pv.is_yes("Das erlaube ich") and pv.is_yes("Ja.")
    assert not pv.is_yes("Nein") and not pv.is_yes("ja nicht") and not pv.is_yes("") and not pv.is_yes("Mach weiter")
    for text in ("Ja, was macht der Befehl genau?", "Klar, lösch auch den Rest", "Ok aber nur lesen",       # Audit H3
                 "Halt, auf keinen Fall, ja", "Ja? Wirklich?", "Hey kushim, ja, bring mir Kaffee", "Okay", "Klar", "Jawohl"):
        assert not pv.is_yes(text), text
    assert pv.is_no("Halt, auf keinen Fall") and pv.is_no("Moment mal")
    assert pv.is_no("Nein danke") and pv.is_no("Stopp") and not pv.is_no("Ja, das erlaube ich")


def test_a_failing_log_never_blocks_the_answer():
    def boom(d):
        raise RuntimeError("Platte voll")
    v = pv.PermissionVoice(FakeBridge(), blocked=allow_all, clock=Clock(), on_decision=boom)
    v.offer(perm())
    assert v.handle(YES, verified=True, strong=True) == pv.ALLOWED


def test_nothing_can_be_allowed_by_voice_any_more(tmp_path):
    from kushim.voice.talk import approval_policy
    policy = approval_policy(tmp_path)
    assert approval_policy(None)(perm()) == "keine Sprecher-Prüfung"
    assert policy(perm()) == "keine Sprecher-Prüfung"
    v = voice(blocked=policy)
    assert v.offer(perm()).endswith(speakable.TERMINAL) and not v.awaiting
    assert v.handle(YES, verified=False, strong=False) is None
