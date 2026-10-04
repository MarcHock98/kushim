import json

from kushim.api.memory_api import MAX_RESULTS, register_memory
from kushim.api.protocol import ApiCore, new_token
from kushim.memory.local import LocalStore
from kushim.memory.shared import SharedStore

TOKEN = new_token()
KEY = "cd" * 32


def make(tmp_path):
    store = SharedStore(LocalStore(tmp_path / "v", create=True, key=KEY, multithread=True))
    core = ApiCore(TOKEN)
    register_memory(core, store)
    return core, store


def call(core, **m):
    return json.loads(core.handle(json.dumps({"token": TOKEN, **m})))


def test_search_lists_newest_first_and_filters(tmp_path):
    core, store = make(tmp_path)
    store.add_fact("Ich trinke gern Tee", "preference")
    store.add_fact("Meine Katze heißt Mia", "person")
    r = call(core, type="memory.search", query="")
    assert [f["text"] for f in r["facts"]] == ["Meine Katze heißt Mia", "Ich trinke gern Tee"]
    assert set(r["facts"][0]) == {"id", "text", "kind", "source", "created"}
    assert [f["kind"] for f in call(core, type="memory.search", query="Tee")["facts"]] == ["preference"]


def test_search_validates_and_caps_the_limit(tmp_path):
    core, store = make(tmp_path)
    for i in range(MAX_RESULTS + 20):
        store.add_fact(f"fakt {i}")
    assert len(call(core, type="memory.search", limit=10_000)["facts"]) == MAX_RESULTS
    for bad in ({"query": 5}, {"query": "x" * 201}, {"limit": "5"}, {"limit": True}):
        assert call(core, type="memory.search", **bad)["error"] == "bad_request"


def test_delete_needs_confirm_and_is_audited_without_the_text(tmp_path):
    core, store = make(tmp_path)
    fid = store.add_fact("geheimer Text")
    assert call(core, type="memory.delete", id=fid)["error"] == "confirm_required"
    assert len(store.search_facts("geheim")) == 1                                   # nichts gelöscht
    assert call(core, type="memory.delete", id=fid, confirm=True) == {"ok": True, "deleted": fid}
    assert store.search_facts("geheim") == []
    tail = store.audit_tail(5)
    assert tail[-1][1:] == ("memory_delete", f"id={fid}") and "geheim" not in json.dumps(tail)


def test_delete_rejects_bad_ids(tmp_path):
    core, _ = make(tmp_path)
    for bad in ("1", True, -1, 1.5, None):
        assert call(core, type="memory.delete", id=bad, confirm=True)["error"] == "bad_request"


def test_needs_token(tmp_path):
    core, _ = make(tmp_path)
    assert json.loads(core.handle(json.dumps({"type": "memory.search"})))["error"] == "unauthorized"


def test_works_from_worker_threads(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    core, store = make(tmp_path)
    store.add_fact("a")
    with ThreadPoolExecutor(2) as pool:
        r = pool.submit(core.handle, json.dumps({"token": TOKEN, "type": "memory.search"})).result()
    assert json.loads(r)["ok"] is True
