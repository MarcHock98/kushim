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


def test_update_needs_confirm_and_changes_nothing_without_it(tmp_path):
    core, store = make(tmp_path)
    fid = store.add_fact("Ich trinke gern Tee", "preference", source="auto", confidence=0.4)
    assert call(core, type="memory.update", id=fid, text="Ich trinke gern Kaffee")["error"] == "confirm_required"
    assert [f.text for f in store.search_facts("Tee")] == ["Ich trinke gern Tee"]


def test_update_changes_text_marks_it_confirmed_and_audits_only_the_id(tmp_path):
    core, store = make(tmp_path)
    fid = store.add_fact("Ich trinke gern Tee", "preference", source="auto", confidence=0.4)
    r = call(core, type="memory.update", id=fid, text="  Ich trinke   gern\x07 Kaffee ", kind="routine", confirm=True)
    assert r == {"ok": True, "updated": fid}
    f = store.search_facts("Kaffee")[0]
    assert (f.text, f.kind, f.source, f.confidence) == ("Ich trinke gern Kaffee", "routine", "user", 1.0)
    tail = store.audit_tail(5)
    assert tail[-1][1:] == ("memory_update", f"id={fid}") and "Kaffee" not in json.dumps(tail)


def test_update_without_kind_keeps_the_kind(tmp_path):
    core, store = make(tmp_path)
    fid = store.add_fact("Mia", "person")
    call(core, type="memory.update", id=fid, text="Mia, die Katze", confirm=True)
    assert store.search_facts("Katze")[0].kind == "person"


def test_update_unknown_id_and_bad_input(tmp_path):
    core, store = make(tmp_path)
    assert call(core, type="memory.update", id=999, text="x", confirm=True)["error"] == "not_found"
    fid = store.add_fact("a")
    for bad in ({"id": "1", "text": "x"}, {"id": True, "text": "x"}, {"id": fid, "text": 5}, {"id": fid, "text": "   "},
                {"id": fid, "text": "x" * 2001}, {"id": fid, "text": "x", "kind": "root"}):
        assert call(core, type="memory.update", confirm=True, **bad)["error"] == "bad_request", bad
    assert store.search_facts("a")[0].text == "a"


def test_update_from_a_worker_thread(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    core, store = make(tmp_path)
    fid = store.add_fact("alt")
    with ThreadPoolExecutor(1) as pool:
        r = pool.submit(core.handle, json.dumps({"token": TOKEN, "type": "memory.update", "id": fid, "text": "neu", "confirm": True})).result()
    assert json.loads(r)["ok"] is True and store.search_facts("neu")


def test_store_without_update_support_gives_a_neutral_error(tmp_path):
    class Old:
        def update_fact(self, *a):
            raise NotImplementedError
        def audit(self, *a):
            pass
    core = ApiCore(TOKEN)
    register_memory(core, Old())
    assert call(core, type="memory.update", id=1, text="x", confirm=True)["error"] == "unavailable"
