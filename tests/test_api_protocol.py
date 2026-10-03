import json

import pytest

from kushim.api.protocol import ApiCore, new_token

TOKEN = new_token()


def core():
    c = ApiCore(TOKEN)
    c.register("ping", lambda m: {"pong": True})
    c.register("boom", lambda m: 1 / 0)
    c.register("echo", lambda m: {"has_token": "token" in m})
    return c


def call(c, **msg):
    return json.loads(c.handle(json.dumps(msg)))


def test_short_token_rejected():
    with pytest.raises(ValueError):
        ApiCore("abc")


def test_valid_call():
    assert call(core(), token=TOKEN, type="ping") == {"ok": True, "pong": True}


@pytest.mark.parametrize("tok", [None, "", "x" * 43, 123, ["a"]])
def test_bad_token_denied(tok):
    assert call(core(), token=tok, type="ping") == {"ok": False, "error": "unauthorized"}


def test_missing_token_denied_before_type_check():
    assert call(core(), type="nope")["error"] == "unauthorized"


def test_unknown_type_denied():
    assert call(core(), token=TOKEN, type="nope")["error"] == "unknown_type"


def test_handler_error_is_neutral():
    r = call(core(), token=TOKEN, type="boom")
    assert r == {"ok": False, "error": "internal"}


def test_token_not_passed_to_handler():
    assert call(core(), token=TOKEN, type="echo")["has_token"] is False


@pytest.mark.parametrize("raw", ["not json", "[1]", "null", b"\xff\xfe"])
def test_malformed_input(raw):
    assert json.loads(core().handle(raw))["error"] == "bad_json"


def test_oversized_message():
    assert json.loads(core().handle("x" * 70_000))["error"] == "too_large"
