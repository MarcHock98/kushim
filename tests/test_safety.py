from kushim.safety import (ActionGate, ActionRequest, ActionSpec, Decision, Harm, Risk)

SPECS = [
    ActionSpec("read_note", Risk.READ),
    ActionSpec("draft_mail", Risk.REVERSIBLE),
    ActionSpec("send_mail", Risk.IRREVERSIBLE, external_effect=True, affects_third_parties=True),
    ActionSpec("transfer_money", Risk.FORBIDDEN, costs_money=True),
    ActionSpec("buy", Risk.IRREVERSIBLE, external_effect=True, costs_money=True),
]
ok_reviewer = lambda spec, req: set()


def req(action, **kw):
    kw.setdefault("speaker_verified", True)
    kw.setdefault("user_initiated", True)
    return ActionRequest(action, "Vorschau", **kw)


def gate(**kw):
    kw.setdefault("reviewer", ok_reviewer)
    return ActionGate(SPECS, **kw)


def test_read_is_allowed():
    assert gate().check(req("read_note")).decision is Decision.ALLOW


def test_unknown_action_denied():
    assert gate().check(req("format_disk")).decision is Decision.DENY


def test_forbidden_always_denied():
    assert gate().check(req("transfer_money")).decision is Decision.DENY


def test_harm_flag_denies():
    assert gate().check(req("draft_mail", harms={Harm.PSYCHOLOGICAL})).decision is Decision.DENY


def test_reviewer_harm_denies():
    g = gate(reviewer=lambda s, r: {Harm.THIRD_PARTY})
    assert g.check(req("send_mail")).decision is Decision.DENY


def test_reviewer_missing_or_crashing_fails_closed():
    assert gate(reviewer=None).check(req("draft_mail")).decision is Decision.DENY

    def boom(s, r):
        raise RuntimeError

    assert gate(reviewer=boom).check(req("draft_mail")).decision is Decision.DENY


def test_money_default_limit_zero():
    assert gate().check(req("buy", amount=1.0)).decision is Decision.DENY
    assert gate(max_amount=10).check(req("buy", amount=5.0)).decision is Decision.ASK
    assert gate(max_amount=10).check(req("buy", amount=50.0)).decision is Decision.DENY


def test_unverified_speaker_or_not_user_initiated_denied():
    assert gate().check(req("send_mail", speaker_verified=False)).decision is Decision.DENY
    assert gate().check(req("send_mail", user_initiated=False)).decision is Decision.DENY


def test_external_actions_need_confirmation():
    assert gate().check(req("send_mail")).decision is Decision.ASK


def test_kill_switch():
    g = gate()
    g.kill()
    assert g.check(req("read_note")).decision is Decision.DENY
    g.resume()
    assert g.check(req("read_note")).decision is Decision.ALLOW
