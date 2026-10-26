"""Der Vault wird von der API in Hintergrund-Threads benutzt: ohne SharedStore scheiterte das still (ProgrammingError)."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from kushim.api.protocol import ApiCore, new_token
from kushim.api.setup_api import register_setup
from kushim.memory.local import LocalStore
from kushim.memory.shared import SharedStore

KEY = "ab" * 32


def make(tmp_path, multithread=True):
    return LocalStore(tmp_path / "vault", create=True, key=KEY, multithread=multithread)


def in_thread(fn):
    out = []

    def run():
        try:
            out.append(fn())
        except Exception as e:                       # noqa: BLE001
            out.append(e)
    t = threading.Thread(target=run)
    t.start()
    t.join()
    return out[0]


def test_plain_store_cannot_be_used_from_another_thread(tmp_path):
    with make(tmp_path, multithread=False) as store:
        assert isinstance(in_thread(lambda: store.audit("x")), Exception)


def test_shared_store_works_from_other_threads_and_in_parallel(tmp_path):
    with SharedStore(make(tmp_path)) as store:
        assert in_thread(lambda: store.audit("einer", "a")) is None
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(lambda i: store.audit(f"e{i}", "x"), range(40)))
        tail = in_thread(lambda: store.audit_tail(200))
        assert len(tail) == 41 and tail[0][1] == "einer"


def test_shared_store_passes_through_other_methods(tmp_path):
    with SharedStore(make(tmp_path)) as store:
        fid = in_thread(lambda: store.add_fact("Milch", "other"))
        assert [f.text for f in in_thread(lambda: store.search_facts("Milch"))] == ["Milch"]
        in_thread(lambda: store.delete_fact(fid))
        assert in_thread(lambda: store.search_facts("Milch")) == []


def test_kill_and_resume_are_really_audited_when_the_api_runs_in_a_worker_thread(tmp_path):
    token = new_token()
    core = ApiCore(token)
    with SharedStore(make(tmp_path)) as store:
        register_setup(core, tmp_path, lambda: "ok", audit=store.audit)
        with ThreadPoolExecutor(1) as pool:         # wie der API-Server: Handler laufen im Executor
            pool.submit(core.handle, json.dumps({"token": token, "type": "safety.kill"})).result()
            pool.submit(core.handle, json.dumps({"token": token, "type": "safety.resume", "confirm": True})).result()
        assert [e for _, e, _ in store.audit_tail(10)] == ["safety_kill", "safety_resume"]


def test_open_store_shared_flag(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from kushim.memory import open_store
    monkeypatch.setattr("kushim.memory.local.get_or_create_key", lambda *a, **k: KEY)
    LocalStore(tmp_path / "v", create=True, key=KEY).close()
    cfg = SimpleNamespace(memory_location=f"local:{tmp_path / 'v'}")
    with open_store(cfg, shared=True) as store:
        assert isinstance(store, SharedStore)
        assert in_thread(lambda: store.audit("ok")) is None
    with open_store(cfg) as plain:
        assert not isinstance(plain, SharedStore)
