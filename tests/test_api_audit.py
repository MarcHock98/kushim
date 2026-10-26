import json

from kushim.api.protocol import ApiCore, new_token
from kushim.api.setup_api import register_setup
from kushim.safety import killswitch

TOKEN = new_token()


def make(tmp_path, audit):
    core = ApiCore(TOKEN)
    register_setup(core, tmp_path, lambda: "ok", audit=audit)
    return core


def call(core, **msg):
    return json.loads(core.handle(json.dumps({"token": TOKEN, **msg})))


def test_kill_and_resume_are_audited_without_details(tmp_path):
    seen = []
    core = make(tmp_path, lambda e, d: seen.append((e, d)))
    assert call(core, type="safety.kill")["kill"] is True
    assert call(core, type="safety.resume", confirm=True)["kill"] is False
    assert seen == [("safety_kill", "api"), ("safety_resume", "api")]


def test_audit_failure_never_blocks_the_kill_switch(tmp_path):
    def broken(e, d):
        raise RuntimeError("vault zu")
    core = make(tmp_path, broken)
    assert call(core, type="safety.kill") == {"ok": True, "kill": True}
    assert killswitch.is_triggered(tmp_path)


def test_resume_without_confirm_is_not_audited(tmp_path):
    seen = []
    core = make(tmp_path, lambda e, d: seen.append(e))
    call(core, type="safety.kill")
    assert call(core, type="safety.resume")["error"] == "confirm_required"
    assert seen == ["safety_kill"]
