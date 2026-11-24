import json
from types import SimpleNamespace

from kushim.api.protocol import ApiCore, new_token
from kushim.api.transcript_api import register_transcript
from kushim.voice.transcript import MAX_CHARS, MAX_ENTRIES, Transcript

TOKEN = new_token()


def res(heard="hallo", reply="hi", outcome="spoken"):
    return SimpleNamespace(heard=heard, reply=reply, outcome=outcome)


def api(t):
    core = ApiCore(TOKEN)
    register_transcript(core, t)
    return lambda **m: json.loads(core.handle(json.dumps({"token": TOKEN, **m})))


def test_records_spoken_results_in_order_with_ids():
    t = Transcript(clock=lambda: 5.0)
    t.add(res("a", "b"))
    t.add(res("c", "d", "command"))
    assert [(e["id"], e["heard"], e["reply"], e["outcome"]) for e in t.since(0)] == [(1, "a", "b", "spoken"), (2, "c", "d", "command")]
    assert [e["id"] for e in t.since(1)] == [2]


def test_rejected_speaker_leaves_no_text():
    t = Transcript()
    t.add(res("Überweise 500 Euro", "", "rejected_speaker"))
    e = t.since(0)[0]
    assert e["heard"] == "" and e["reply"] == "" and e["outcome"] == "rejected_speaker"


def test_kill_phrase_text_and_empty_results_are_not_kept():
    t = Transcript()
    t.add(res("Notaus", "", "killed"))
    for o in ("empty", "wake_only", "halted"):
        t.add(res("", "", o))
    assert [e["outcome"] for e in t.since(0)] == ["killed"] and t.since(0)[0]["heard"] == ""


def test_bounded_in_count_and_length():
    t = Transcript()
    for i in range(MAX_ENTRIES + 10):
        t.add(res("x" * (MAX_CHARS + 50), "y"))
    items = t.since(0)
    assert len(items) == MAX_ENTRIES and len(items[0]["heard"]) == MAX_CHARS and items[-1]["id"] == MAX_ENTRIES + 10


def test_never_written_to_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    t = Transcript()
    t.add(res("geheim", "auch geheim"))
    assert list(tmp_path.iterdir()) == []


def test_api_returns_new_entries_and_last_id_and_validates_since():
    t = Transcript()
    call = api(t)
    assert call(type="transcript.get") == {"ok": True, "entries": [], "last": 0}
    t.add(res("a", "b"))
    r = call(type="transcript.get", since=0)
    assert r["last"] == 1 and r["entries"][0]["heard"] == "a"
    assert call(type="transcript.get", since=1) == {"ok": True, "entries": [], "last": 1}
    for bad in (-1, "0", True, 1.5, None):
        assert call(type="transcript.get", since=bad)["error"] == "bad_request"


def test_api_needs_token():
    core = ApiCore(TOKEN)
    register_transcript(core, Transcript())
    assert json.loads(core.handle(json.dumps({"type": "transcript.get"})))["error"] == "unauthorized"


# --- Zeile „Du“ direkt nach der Spracherkennung: pending -> sent/dropped, rev steigt bei jeder Änderung

FIELDS = {"id", "rev", "heard", "raw", "ts", "status", "reason", "sent_ts", "reply", "outcome", "unspoken"}


def turn(entry, heard="wie spät ist es", reply="Zehn Uhr.", outcome="spoken"):
    return SimpleNamespace(heard=heard, reply=reply, outcome=outcome, entry=entry)


def test_heard_creates_a_pending_entry_with_all_fields():
    t = Transcript(clock=lambda: 7.0)
    i = t.heard("Hey Kushim, wie spät ist es", "wie spät ist es")
    e = t.get(i)
    assert set(e) == FIELDS
    assert e == {"id": i, "rev": 1, "heard": "wie spät ist es", "raw": "Hey Kushim, wie spät ist es", "ts": 7.0,
                 "status": "pending", "reason": "", "sent_ts": None, "reply": "", "outcome": "", "unspoken": 0}


def test_pending_to_sent_then_reply_raises_rev_and_keeps_the_id():
    now = [1.0]
    t = Transcript(clock=lambda: now[0])
    i = t.heard("kushim wie spät", "wie spät")
    now[0] = 2.5
    assert t.sent(i) is True
    e = t.get(i)
    assert (e["status"], e["sent_ts"], e["ts"], e["rev"]) == ("sent", 2.5, 1.0, 2)
    t.add(turn(i))
    e = t.get(i)
    assert (e["id"], e["rev"], e["reply"], e["outcome"], e["status"]) == (i, 3, "Zehn Uhr.", "spoken", "sent")
    assert len(t.since(0)) == 1                                       # ergänzt, nicht angehängt


def test_since_rev_returns_each_changed_entry_exactly_once():
    t = Transcript()
    a = t.heard("a", "a")
    b = t.heard("b", "b")
    last = max(e["rev"] for e in t.since(0))
    assert t.since(last) == []
    t.sent(a)
    changed = t.since(last)
    assert [e["id"] for e in changed] == [a] and changed[0]["status"] == "sent"
    assert t.since(changed[0]["rev"]) == []
    t.drop(b, "command")
    assert [(e["id"], e["status"], e["reason"]) for e in t.since(changed[0]["rev"])] == [(b, "dropped", "command")]


def test_api_last_is_the_highest_rev_and_updates_come_again():
    t = Transcript()
    call = api(t)
    i = t.heard("kushim hallo", "hallo")
    r = call(type="transcript.get", since=0)
    assert r["last"] == 1 and r["entries"][0]["status"] == "pending"
    t.sent(i)
    r = call(type="transcript.get", since=1)
    assert r["last"] == 2 and [(e["id"], e["status"]) for e in r["entries"]] == [(i, "sent")]
    assert call(type="transcript.get", since=2) == {"ok": True, "entries": [], "last": 2}


def test_only_pending_entries_change_status():
    t = Transcript()
    i = t.heard("x", "x")
    assert t.drop(i, "wake_only") is True
    assert t.sent(i) is False and t.drop(i, "send_failed") is False
    assert t.get(i)["reason"] == "wake_only" and t.get(i)["rev"] == 2
    assert t.sent(999) is False and t.drop(True, "x") is False


def test_killed_entry_has_no_text_even_after_the_result():
    t = Transcript()
    i = t.heard("", "", "killed")
    t.add(turn(i, heard="Kushim Notaus", reply="", outcome="killed"))
    e = t.get(i)
    assert (e["heard"], e["raw"], e["status"], e["reason"], e["outcome"]) == ("", "", "dropped", "killed", "killed")


def test_wake_only_is_shown_with_the_raw_text_and_never_redacted():
    t = Transcript()
    i = t.heard("Hey Kushim.", "", "wake_only")
    e = t.get(i)
    assert (e["heard"], e["raw"], e["status"], e["reason"]) == ("", "Hey Kushim.", "dropped", "wake_only")


def test_empty_and_halted_without_text_are_still_skipped():
    t = Transcript()
    for o in ("empty", "halted", "wake_only"):
        t.add(SimpleNamespace(heard="", reply="", outcome=o))
    assert t.since(0) == []


def test_result_for_an_entry_that_fell_out_is_not_added_again():
    t = Transcript()
    first = t.heard("alt", "alt")
    for _ in range(MAX_ENTRIES):
        t.heard("neu", "neu")
    t.add(turn(first))
    assert len(t.since(0)) == MAX_ENTRIES and t.get(first) is None


def test_new_fields_are_bounded_too():
    t = Transcript()
    for _ in range(MAX_ENTRIES + 5):
        t.heard("r" * (MAX_CHARS + 9), "h" * (MAX_CHARS + 9))
    items = t.since(0)
    assert len(items) == MAX_ENTRIES and len(items[0]["raw"]) == MAX_CHARS and len(items[0]["heard"]) == MAX_CHARS
    t.add(turn(items[-1]["id"], reply="y" * (MAX_CHARS + 9)))
    assert len(t.get(items[-1]["id"])["reply"]) == MAX_CHARS


def test_entries_without_an_id_get_a_status_from_the_outcome():
    t = Transcript()
    t.add(res("a", "b", "spoken"))
    t.add(res("c", "d", "command"))
    t.add(res("", "", "rejected_speaker"))
    got = [(e["status"], e["reason"], e["raw"], e["sent_ts"]) for e in t.since(0)]
    assert got == [("sent", "", "", None), ("dropped", "command", "", None), ("dropped", "", "", None)]


def test_new_fields_never_touch_the_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import builtins
    opened = []
    real_open = builtins.open
    monkeypatch.setattr(builtins, "open", lambda *a, **k: opened.append(a) or real_open(*a, **k))
    t = Transcript()
    i = t.heard("Hey Kushim, geheim", "geheim")
    t.sent(i)
    t.add(turn(i, reply="auch geheim"))
    t.drop(t.heard("x", "x"), "command")
    t.since(0)
    assert opened == [] and list(tmp_path.iterdir()) == []
