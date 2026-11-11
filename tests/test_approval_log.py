"""Freigabe-Protokoll (src/kushim/channel/approval_log.py, Roadmap v2 C5)."""
import json
import threading
from collections import deque

from kushim.channel import approval_log as al
from kushim.channel.bridge import Permission
from kushim.memory.local import LocalStore
from kushim.voice import permission_voice as pv

KEY = "ab" * 32
YES = "Ja, das erlaube ich."


def opener(tmp_path):
    LocalStore(tmp_path / "v", create=True, key=KEY).close()
    return lambda: LocalStore(tmp_path / "v", key=KEY)


def test_entries_land_in_the_vault_and_read_back(tmp_path):
    log = al.ApprovalLog(opener(tmp_path))
    log({"request_id": "r1", "tool": "Bash", "what": "Claude möchte den Befehl npm test ausführen.", "result": "allowed",
         "source": "voice", "verified": True, "strong": True, "score": 0.83456})
    log({"request_id": "r2", "tool": "Write", "what": "x", "result": "terminal_only", "source": "voice", "reason": "nur Terminal"})
    with LocalStore(tmp_path / "v", key=KEY) as store:
        rows = al.recent(store)
        store.audit("anderes", "nicht dabei")
        assert len(al.recent(store)) == 2
    assert [r["result"] for r in rows] == ["allowed", "terminal_only"]
    assert rows[0]["score"] == 0.835 and rows[0]["strong"] is True and rows[1]["reason"] == "nur Terminal"
    line = al.format_row(rows[0])
    assert "Stimme" in line and "erlaubt" in line and "(0.83, stark)" in line and "npm test" in line


def test_only_known_fields_short_text_no_audio_no_raw_input():
    entry = al.sanitize({"request_id": "r1", "tool": "Bash", "what": "a\nb\x1b[2J" + "x" * 500, "result": "allowed",
                         "audio": b"\x00\x01", "pcm": [1, 2], "input_preview": "{ geheim }", "score": 7.0,
                         "verified": "yes", "strong": True})
    assert set(entry) == {"request_id", "tool", "what", "result", "strong"}
    assert entry["what"].isprintable() and len(entry["what"]) <= 240


def test_a_broken_vault_never_breaks_the_answer_and_is_counted(tmp_path):
    def broken():
        raise OSError("Vault gesperrt")
    log = al.ApprovalLog(broken)
    log({"result": "allowed"})
    assert log.failures == 1


def test_writes_from_another_thread_work(tmp_path):
    log = al.ApprovalLog(opener(tmp_path))
    t = threading.Thread(target=log, args=({"request_id": "r1", "result": "asked", "source": "voice"},))
    t.start()
    t.join()
    assert log.failures == 0
    with LocalStore(tmp_path / "v", key=KEY) as store:
        assert al.recent(store)[0]["result"] == "asked"


def test_broken_entries_are_skipped_when_reading(tmp_path):
    with LocalStore(tmp_path / "v", create=True, key=KEY) as store:
        store.audit(al.EVENT, "kein json")
        store.audit(al.EVENT, json.dumps([1, 2]))
        store.audit(al.EVENT, json.dumps({"result": "allowed", "evil": "x"}))
        assert al.recent(store) == [{"ts": al.recent(store)[0]["ts"], "result": "allowed"}]


class FakeBridge:
    def __init__(self):
        self.permissions, self.answers = deque(), []

    def answer(self, rid, behavior):
        self.answers.append((rid, behavior))
        return "ok"


def test_the_whole_voice_flow_is_protocolled(tmp_path):
    log = al.ApprovalLog(opener(tmp_path))
    t = {"now": 0.0}
    v = pv.PermissionVoice(FakeBridge(), blocked=lambda p: None, clock=lambda: t["now"], on_decision=log)
    ok = Permission.parse({"request_id": "r1", "tool_name": "Bash", "description": "", "input_preview": '{ "command": "npm test" }'})
    long = Permission.parse({"request_id": "r2", "tool_name": "Bash", "description": "", "input_preview": '{ "command": "x…'})
    v.offer(ok)
    v.handle("ja", verified=True, strong=False, score=0.71)
    v.handle(YES, verified=True, strong=True, score=0.9)
    v.offer(long)
    v.offer(ok)
    t["now"] += pv.ASK_TTL + 1
    assert not v.awaiting
    with LocalStore(tmp_path / "v", key=KEY) as store:
        rows = al.recent(store)
    assert [r["result"] for r in rows] == ["asked", "weak", "allowed", "terminal_only", "asked", "timeout"]
    assert rows[1]["score"] == 0.71 and rows[2]["score"] == 0.9 and rows[3]["reason"] == "unvollständig"
    assert all(r["source"] == "voice" and r["what"].startswith("Claude möchte") for r in rows)
