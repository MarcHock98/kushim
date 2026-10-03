import pytest

from kushim.safety.approvals import ApprovalQueue, Status
from kushim.safety.gate import ActionGate, ActionRequest, ActionSpec, Decision, Risk

SPECS = [ActionSpec("read_note", Risk.READ),
         ActionSpec("send_mail", Risk.IRREVERSIBLE, external_effect=True, affects_third_parties=True)]


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def setup(clock=None):
    gate = ActionGate(SPECS, reviewer=lambda s, r: set())
    q = ApprovalQueue(gate, ttl=60, clock=clock or Clock())
    return gate, q


def mail(desc="Mail an Anna: Hallo"):
    return ActionRequest("send_mail", desc, speaker_verified=True, user_initiated=True)


def test_only_ask_is_queued():
    _, q = setup()
    d, a = q.submit(ActionRequest("read_note", "x"))
    assert d is Decision.ALLOW and a is None
    d, a = q.submit(ActionRequest("unknown", "x"))
    assert d is Decision.DENY and a is None
    d, a = q.submit(ActionRequest("send_mail", "x"))   # nicht verifiziert
    assert d is Decision.DENY and a is None
    assert q.pending() == []


def test_approve_then_take_once():
    _, q = setup()
    _, a = q.submit(mail())
    assert q.take(a.id) is None                      # noch nicht freigegeben
    assert q.approve(a.id, a.digest)
    assert q.take(a.id).action == "send_mail"
    assert q.take(a.id) is None                      # einmalig
    assert a.status is Status.USED


def test_wrong_digest_rejected():
    _, q = setup()
    _, a = q.submit(mail())
    assert not q.approve(a.id, "0" * 64)
    assert a.status is Status.PENDING


def test_changed_description_invalidates():
    _, q = setup()
    _, a = q.submit(mail())
    assert q.approve(a.id, a.digest)
    a.request.description = "Mail an Chef: Kündigung"
    assert q.take(a.id) is None


def test_deny_blocks():
    _, q = setup()
    _, a = q.submit(mail())
    assert q.deny(a.id)
    assert not q.approve(a.id, a.digest) and q.take(a.id) is None


def test_expiry():
    c = Clock()
    _, q = setup(c)
    _, a = q.submit(mail())
    c.t = 61
    assert q.pending() == [] and not q.approve(a.id, a.digest)
    assert a.status is Status.EXPIRED


def test_approved_but_expired_not_taken():
    c = Clock()
    _, q = setup(c)
    _, a = q.submit(mail())
    q.approve(a.id, a.digest)
    c.t = 61
    assert q.take(a.id) is None


def test_kill_switch_blocks_approve_and_take():
    gate, q = setup()
    _, a = q.submit(mail())
    gate.kill()
    assert not q.approve(a.id, a.digest)
    gate.resume()
    assert q.approve(a.id, a.digest)
    gate.kill()
    assert q.take(a.id) is None


def test_unknown_id():
    _, q = setup()
    assert not q.approve("nope", "x") and not q.deny("nope") and q.take("nope") is None
