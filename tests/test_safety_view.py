import json
import time
from types import SimpleNamespace

from kushim.api.protocol import ApiCore, new_token
from kushim.api.safety_view import DETAIL_CHARS, backup_age_days, register_safety_view
from kushim.memory.local import LocalStore
from kushim.safety import killswitch

TOKEN = new_token()


def cfg(**kw):
    base = dict(claude_enabled=False, memory_location="local:" , backup_target="")
    base.update(kw)
    return SimpleNamespace(**base)


def call(core):
    return json.loads(core.handle(json.dumps({"token": TOKEN, "type": "safety.overview"})))


def make(tmp_path, c=None, **kw):
    core = ApiCore(TOKEN)
    register_safety_view(core, c or cfg(memory_location=f"local:{tmp_path / 'vault'}"), tmp_path, **kw)
    return core


def test_default_mode_a_no_kill_money_limit_zero(tmp_path):
    r = call(make(tmp_path))
    assert r["mode"] == "A" and r["kill"] is False and r["money_limit_eur"] == 0.0
    assert r["vault"] == {"where": "local", "exists": False, "open": False}
    assert r["tools_active"] == [] and r["audit"] == [] and r["backup"] == {"configured": False, "age_days": None}


def test_mode_c_and_kill_and_active_tools(tmp_path):
    killswitch.trigger(tmp_path)
    r = call(make(tmp_path, cfg(claude_enabled=True, memory_location="remote:nas")))
    assert r["mode"] == "C" and r["kill"] is True and r["tools_active"] == []
    assert r["vault"]["where"] == "remote"


def test_live_config_object_is_read_fresh_each_call(tmp_path):
    state = {"c": cfg()}
    live = SimpleNamespace(get=lambda: state["c"])
    core = ApiCore(TOKEN)
    register_safety_view(core, live, tmp_path)
    assert call(core)["mode"] == "A"
    state["c"] = cfg(claude_enabled=True)
    assert call(core)["mode"] == "C"


def test_never_exposes_paths_keys_or_tokens(tmp_path):
    r = call(make(tmp_path, cfg(memory_location=f"local:{tmp_path}", backup_target=str(tmp_path / "bak"))))
    text = json.dumps(r)
    assert str(tmp_path) not in text and "token" not in text.lower() and "key" not in text.lower()


def test_audit_tail_is_limited_truncated_and_ordered(tmp_path):
    with LocalStore(tmp_path / "vault", create=True) as store:
        for i in range(60):
            store.audit(f"e{i}", "x" * 500)
        r = call(make(tmp_path, store=store))
    assert len(r["audit"]) == 50 and r["audit"][-1]["event"] == "e59" and r["audit"][0]["event"] == "e10"
    assert all(len(a["detail"]) <= DETAIL_CHARS for a in r["audit"])
    assert r["vault"]["open"] is True and r["vault"]["exists"] is True


def test_failing_store_gives_empty_audit_not_an_error(tmp_path):
    class Broken:
        def audit_tail(self, n):
            raise RuntimeError("zu")
    assert call(make(tmp_path, store=Broken()))["audit"] == []


def test_backup_age(tmp_path):
    assert backup_age_days("", time.time()) is None
    assert backup_age_days(str(tmp_path / "nix"), time.time()) is None
    snap = tmp_path / "vault-20261001-000000"
    snap.mkdir()
    now = snap.stat().st_mtime + 3 * 86400
    assert backup_age_days(str(tmp_path), now) == 3.0


def test_needs_token(tmp_path):
    assert json.loads(make(tmp_path).handle(json.dumps({"type": "safety.overview"})))["error"] == "unauthorized"
