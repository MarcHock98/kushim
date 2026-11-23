"""E2b: `usage.get` liest run/usage.json (von scripts/statusline.py) als fremde Datei."""
import importlib.util
import json
from pathlib import Path

import pytest

from kushim.api import usage_api
from kushim.api.protocol import ApiCore, new_token

ROOT = Path(__file__).resolve().parents[1]
NOW = 1_800_000_000.0
GOOD = {"model": "Opus 5.5", "context_pct": 42.4, "five_h_pct": 30, "seven_d_pct": 12.2, "cost_usd": None, "stand": NOW - 60}
EMPTY = {"available": False, "model": "", "context_pct": None, "five_h_pct": None, "seven_d_pct": None, "cost_usd": None,
         "stand": None, "stale": False}


def api(tmp_path, now=NOW):
    token = new_token()
    core = ApiCore(token)
    usage_api.register_usage(core, tmp_path, clock=lambda: now)

    def call(**kw):
        return json.loads(core.handle(json.dumps({"token": token, "type": "usage.get", **kw})))
    call.core, call.token = core, token
    return call


def write(tmp_path, data):
    p = tmp_path / usage_api.FILE
    p.parent.mkdir(exist_ok=True)
    p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return p


def test_no_file_is_unavailable(tmp_path):
    assert api(tmp_path)() == {"ok": True, **EMPTY}


def test_fresh_file_is_shown_with_stand(tmp_path):
    write(tmp_path, GOOD)
    assert api(tmp_path)() == {"ok": True, "available": True, "model": "Opus 5.5", "context_pct": 42.4, "five_h_pct": 30.0,
                               "seven_d_pct": 12.2, "cost_usd": None, "stand": int(NOW - 60), "stale": False}
    write(tmp_path, {**GOOD, "cost_usd": 1.25, "context_pct": None, "model": ""})
    r = api(tmp_path)()
    assert r["available"] and r["cost_usd"] == 1.25 and r["context_pct"] is None and r["model"] == ""


def test_old_file_is_stale_but_still_shown(tmp_path):
    write(tmp_path, {**GOOD, "stand": NOW - 30 * 60 - 1})
    r = api(tmp_path)()
    assert r["available"] is True and r["stale"] is True
    write(tmp_path, {**GOOD, "stand": NOW - 30 * 60 + 5})
    assert api(tmp_path)()["stale"] is False
    write(tmp_path, {**GOOD, "stand": 1})                                        # sehr alt
    assert api(tmp_path)()["stale"] is True


@pytest.mark.parametrize("bad", [
    {**GOOD, "extra": 1}, {k: v for k, v in GOOD.items() if k != "cost_usd"}, {**GOOD, "model": 5},
    {**GOOD, "model": "x" * 41}, {**GOOD, "model": "Opus\x1b[2J"}, {**GOOD, "model": "Opus\n5"},
    {**GOOD, "context_pct": "42"}, {**GOOD, "context_pct": True}, {**GOOD, "five_h_pct": 101}, {**GOOD, "seven_d_pct": -0.1},
    {**GOOD, "cost_usd": -1}, {**GOOD, "cost_usd": 10 ** 9}, {**GOOD, "cost_usd": "0.3"}, {**GOOD, "stand": "jetzt"},
    {**GOOD, "stand": None}, {**GOOD, "stand": 0}, {**GOOD, "stand": NOW + 3600}, {**GOOD, "stand": True},
    [GOOD], "null", '"Opus"', "{kaputt", "",
    json.dumps(GOOD).replace("42.4", "NaN"), json.dumps(GOOD).replace("42.4", "Infinity"),
    json.dumps(GOOD).replace("30", "1e999"),
])
def test_malformed_files_are_unavailable(tmp_path, bad):
    write(tmp_path, bad)
    assert api(tmp_path)() == {"ok": True, **EMPTY}


def test_huge_or_binary_files_are_unavailable(tmp_path):
    write(tmp_path, json.dumps(GOOD) + " " * 1100)
    assert api(tmp_path)()["available"] is False
    (tmp_path / usage_api.FILE).write_bytes(b"\xff\xfe{}")
    assert api(tmp_path)()["available"] is False
    deep = "[" * 5000 + "]" * 5000
    write(tmp_path, deep[:1000])
    assert api(tmp_path)()["available"] is False


def test_usage_needs_the_token(tmp_path):
    write(tmp_path, GOOD)
    call = api(tmp_path)
    assert json.loads(call.core.handle(json.dumps({"type": "usage.get"}))) == {"ok": False, "error": "unauthorized"}


def test_statusline_output_round_trips_through_the_reader(tmp_path):
    spec = importlib.util.spec_from_file_location("statusline_rt", ROOT / "scripts" / "statusline.py")
    sl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sl)
    sid = "0b9f1c2e-3d4a-4b5c-8d6e-7f8091a2b3c4"
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "claude-session.txt").write_text(sid, encoding="utf-8")
    data = {"session_id": sid, "model": {"display_name": "Sonnet 5"}, "context_window": {"used_percentage": 7},
            "rate_limits": {"five_hour": {"used_percentage": 99.5}}, "cost": {"total_cost_usd": 0.02}}
    assert sl.write_usage(data, tmp_path, now=NOW - 10)
    r = usage_api.read(tmp_path, NOW)
    assert r == {"available": True, "model": "Sonnet 5", "context_pct": 7.0, "five_h_pct": 99.5, "seven_d_pct": None,
                 "cost_usd": 0.02, "stand": int(NOW - 10), "stale": False}


def test_launch_removes_the_usage_of_the_previous_session(tmp_path):
    from kushim.channel import launch
    write(tmp_path, GOOD)
    launch.launch(Path("claude.exe"), tmp_path, tmp_path, popen=lambda *a, **k: None)
    assert not (tmp_path / usage_api.FILE).exists()
    assert launch.read_session(tmp_path) is not None
