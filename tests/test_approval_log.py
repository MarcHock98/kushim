"""Freigabe-Protokoll (src/kushim/channel/approval_log.py, Roadmap v2 C5)."""
import json
import threading
from collections import deque

from kushim.channel import approval_log as al
from kushim.channel.bridge import Permission
from kushim.memory.local import LocalStore

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


def test_start_warns_when_the_token_folder_is_inside_claudes_work_folder(tmp_path):
    from kushim import cli
    kushim_root, other = tmp_path / "kushim", tmp_path / "proj"
    (kushim_root / "run").mkdir(parents=True)
    other.mkdir()
    assert cli._token_dir_inside(kushim_root, kushim_root)          # Claude arbeitet im kushim-Repo selbst
    assert cli._token_dir_inside(kushim_root, tmp_path)
    assert not cli._token_dir_inside(kushim_root, other)
