import json
import threading
from types import SimpleNamespace

from kushim.api.feedback_api import register_feedback
from kushim.api.protocol import ApiCore, new_token
from kushim.memory.local import LocalStore
from kushim.memory.shared import SharedStore
from kushim.voice.transcript import Transcript

TOKEN = new_token()
KEY = "ef" * 32


def make(tmp_path):
    inner = LocalStore(tmp_path / "v", create=True, key=KEY, multithread=True)
    store = SharedStore(inner)
    tr = Transcript()
    core = ApiCore(TOKEN)
    register_feedback(core, tr, store)
    return core, tr, store, inner


def call(core, **m):
    return json.loads(core.handle(json.dumps({"token": TOKEN, "type": "feedback.add", **m})))


def res(heard="Wie spät ist es?", reply="Es ist zehn Uhr.", outcome="spoken"):
    return SimpleNamespace(heard=heard, reply=reply, outcome=outcome)


def rows(inner, sql):
    return inner.con.execute(sql).fetchall()


def test_nothing_is_stored_without_a_click(tmp_path):
    core, tr, store, inner = make(tmp_path)
    tr.add(res())
    assert inner.counts()["episodes"] == 0 and inner.counts()["feedback"] == 0


def test_rating_stores_question_answer_and_feedback_locally(tmp_path):
    core, tr, store, inner = make(tmp_path)
    tr.add(res())
    assert call(core, entry=1, rating=1) == {"ok": True, "rated": 1, "rating": 1}
    eps = rows(inner, "select id, role, text from episodes order by id")
    assert [(r, t) for _, r, t in eps] == [("user", "Wie spät ist es?"), ("assistant", "Es ist zehn Uhr.")]
    fb = rows(inner, "select episode_id, rating from feedback")
    assert fb == [(eps[1][0], 1)]                                              # hängt an der Antwort


def test_thumbs_down_is_stored_as_minus_one(tmp_path):
    core, tr, store, inner = make(tmp_path)
    tr.add(res())
    call(core, entry=1, rating=-1)
    assert rows(inner, "select rating from feedback") == [(-1,)]


def test_each_entry_can_be_rated_only_once(tmp_path):
    core, tr, store, inner = make(tmp_path)
    tr.add(res())
    call(core, entry=1, rating=1)
    assert call(core, entry=1, rating=-1)["error"] == "already_rated"
    assert inner.counts()["feedback"] == 1


def test_parallel_clicks_store_only_once(tmp_path):
    core, tr, store, inner = make(tmp_path)
    tr.add(res())
    out, gate = [], threading.Barrier(2)

    def go():
        gate.wait()
        out.append(call(core, entry=1, rating=1))
    ts = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(o.get("error", "ok") for o in out) == ["already_rated", "ok"]
    assert inner.counts()["feedback"] == 1


def test_entries_without_a_reply_cannot_be_rated(tmp_path):
    core, tr, store, inner = make(tmp_path)
    tr.add(res("Überweise Geld", "", "rejected_speaker"))
    tr.add(res("Notaus", "", "killed"))
    assert call(core, entry=1, rating=1)["error"] == "not_found"
    assert call(core, entry=2, rating=1)["error"] == "not_found"
    assert call(core, entry=99, rating=1)["error"] == "not_found"
    assert inner.counts()["episodes"] == 0


def test_bad_requests(tmp_path):
    core, tr, store, inner = make(tmp_path)
    tr.add(res())
    for bad in ({"entry": "1", "rating": 1}, {"entry": True, "rating": 1}, {"entry": 1, "rating": 5}, {"entry": 1, "rating": 0},
                {"entry": 1, "rating": True}, {"entry": 1}, {"rating": 1}):
        assert call(core, **bad)["error"] == "bad_request", bad
    assert inner.counts()["feedback"] == 0


def test_audit_names_only_the_rating(tmp_path):
    core, tr, store, inner = make(tmp_path)
    tr.add(res("geheime Frage", "geheime Antwort"))
    call(core, entry=1, rating=1)
    tail = store.audit_tail(5)
    assert tail[-1][1:] == ("feedback", "rating=1") and "geheim" not in json.dumps(tail)


def test_failed_store_gives_neutral_error_and_allows_a_retry(tmp_path):
    class Broken:
        def log_episode(self, *a):
            raise RuntimeError("zu")
    tr = Transcript()
    tr.add(res())
    core = ApiCore(TOKEN)
    register_feedback(core, tr, Broken())
    assert call(core, entry=1, rating=1)["error"] == "unavailable"
    assert call(core, entry=1, rating=1)["error"] == "unavailable"            # nicht fälschlich als bewertet vorgemerkt


def test_works_from_a_worker_thread_and_needs_a_token(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    core, tr, store, inner = make(tmp_path)
    tr.add(res())
    with ThreadPoolExecutor(1) as pool:
        r = pool.submit(core.handle, json.dumps({"token": TOKEN, "type": "feedback.add", "entry": 1, "rating": 1})).result()
    assert json.loads(r)["ok"] is True
    assert json.loads(core.handle(json.dumps({"type": "feedback.add", "entry": 1, "rating": 1})))["error"] == "unauthorized"
