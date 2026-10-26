"""Freigabe-Leiste (API): exakte Vorschau, Hash-Bindung, Bestätigung nötig, nie doppelt, Ergebnis wird angesagt."""
import json
import threading
from types import SimpleNamespace

from kushim.api.approvals_api import register_approvals
from kushim.api.protocol import ApiCore, new_token
from kushim.voice.tool_commands import ToolCommands, _Pending

TOKEN = new_token()


class Q:
    def remaining(self, item):
        return 42.0


class Owner:
    queue = Q()

    def __init__(self, ok=True):
        self.calls, self.ok, self.done = [], ok, threading.Event()

    def approve(self, p):
        self.calls.append("approve")
        return self.ok

    def deny(self, p):
        self.calls.append("deny")

    def execute(self, p):
        self.calls.append("execute")
        self.done.set()
        return SimpleNamespace(kind="wikipedia", answer="", wiki=None, note="Nichts gefunden")


def make(kind="research", control=False, ok=True):
    owner = Owner(ok)
    cmds = ToolCommands(SimpleNamespace(), SimpleNamespace(), owner, owner if control else Owner(), SimpleNamespace(on_finish=None),
                        lambda w: "", lambda: [])
    proposal = SimpleNamespace(approval=SimpleNamespace(id="a1", digest="h" * 64), preview="Suchtext: Eiffelturm", route="claude", task="t")
    cmds._pending = _Pending(kind, proposal, control=control)
    core = ApiCore(TOKEN)
    register_approvals(core, cmds)
    return core, cmds, owner


def call(core, **msg):
    return json.loads(core.handle(json.dumps({"token": TOKEN, **msg})))


def test_get_shows_exact_preview_digest_and_remaining_time():
    core, _, _ = make()
    r = call(core, type="approvals.get")
    assert r["pending"] == {"kind": "research", "preview": "Suchtext: Eiffelturm", "digest": "h" * 64,
                            "expires_in": 42.0, "sends_data_out": True}


def test_get_without_pending_is_null():
    core, cmds, _ = make()
    cmds._pending = None
    assert call(core, type="approvals.get") == {"ok": True, "pending": None}


def test_approve_needs_confirm_and_nothing_runs_without_it():
    core, cmds, owner = make()
    assert call(core, type="approvals.decide", approve=True, digest="h" * 64)["error"] == "confirm_required"
    assert owner.calls == [] and cmds.awaiting


def test_approve_with_matching_digest_runs_once_and_announces():
    core, cmds, owner = make()
    assert call(core, type="approvals.decide", approve=True, confirm=True, digest="h" * 64) == {"ok": True, "result": "started"}
    assert owner.done.wait(5)
    assert owner.calls == ["approve", "execute"] and not cmds.awaiting
    assert cmds.announcement() == "Nichts gefunden"
    assert call(core, type="approvals.decide", approve=True, confirm=True, digest="h" * 64)["error"] == "none"   # nie doppelt


def test_changed_preview_is_stale_and_stays_pending():
    core, cmds, owner = make()
    r = call(core, type="approvals.decide", approve=True, confirm=True, digest="x" * 64)
    assert r == {"ok": False, "error": "stale"} and cmds.awaiting and owner.calls == []


def test_deny_needs_no_confirm_and_runs_nothing():
    core, cmds, owner = make()
    assert call(core, type="approvals.decide", approve=False, digest="h" * 64) == {"ok": True, "result": "denied"}
    assert owner.calls == ["deny"] and not cmds.awaiting


def test_expired_approval_is_announced_not_executed():
    core, cmds, owner = make(ok=False)
    call(core, type="approvals.decide", approve=True, confirm=True, digest="h" * 64)
    for _ in range(100):
        if cmds.awaiting is False and owner.calls:
            break
    assert cmds._announcements.get(timeout=5) == "Die Freigabe ist abgelaufen."
    assert "execute" not in owner.calls


def test_bad_requests_and_missing_token():
    core, _, _ = make()
    assert call(core, type="approvals.decide", approve="yes", digest="h")["error"] == "bad_request"
    assert call(core, type="approvals.decide", approve=True)["error"] == "bad_request"
    assert json.loads(core.handle(json.dumps({"type": "approvals.get"})))["error"] == "unauthorized"


def test_control_proposals_also_go_through_the_same_path():
    core, _, owner = make(kind="start", control=True)
    call(core, type="approvals.decide", approve=True, confirm=True, digest="h" * 64)
    assert owner.done.wait(5) and owner.calls == ["approve", "execute"]
