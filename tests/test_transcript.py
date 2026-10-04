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
