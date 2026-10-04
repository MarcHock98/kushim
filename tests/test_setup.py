import json
import os

import pytest

from kushim.api.protocol import ApiCore, new_token
from kushim.api.setup_api import register_setup
from kushim.doctor import Check
from kushim.safety import killswitch
from kushim.setup import state, status

OK = [Check("a", True)]
BAD = [Check("Whisper-Modell", False), Check("Ollama", False), Check("Piper-Stimme", False), Check("Vault-Paket", False)]


def steps(tmp_path, vault="kein-vault", checks=OK):
    return {s.step: s for s in status.compute(tmp_path, lambda: vault, checks=checks)}


# --- Zustandsdatei -------------------------------------------------------------------------------

def test_missing_or_broken_state_means_everything_open(tmp_path):
    assert all(v["status"] == "open" for v in state.load(tmp_path).values())
    p = state.path(tmp_path)
    p.parent.mkdir(parents=True)
    for junk in ("{kaputt", "[]", '{"system": "x"}', '{"system": {"status": "hacked"}}', ""):
        p.write_text(junk, encoding="utf-8")
        assert all(v["status"] == "open" for v in state.load(tmp_path).values()), junk


def test_mark_roundtrip_is_atomic_and_validated(tmp_path):
    state.mark(tmp_path, "wake_words", "skipped", today="2026-10-04")
    assert state.load(tmp_path)["wake_words"] == {"status": "skipped", "date": "2026-10-04"}
    assert not list(state.path(tmp_path).parent.glob("*.tmp"))          # keine Reste der atomaren Ablöse
    for bad in (("nope", "done"), ("system", "weird")):
        with pytest.raises(ValueError):
            state.mark(tmp_path, *bad)
    state.mark(tmp_path, "system", "open")
    assert state.load(tmp_path)["wake_words"]["status"] == "skipped"     # andere Schritte bleiben


def test_unknown_steps_in_file_are_ignored(tmp_path):
    p = state.path(tmp_path)
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"evil": {"status": "done"}, "safety": {"status": "done", "date": "2026-10-04"}}), encoding="utf-8")
    loaded = state.load(tmp_path)
    assert set(loaded) == set(state.STEPS) and loaded["safety"]["status"] == "done"


# --- Status aus Fakten ---------------------------------------------------------------------------

def test_fresh_install_is_a_first_start(tmp_path):
    s = steps(tmp_path)
    assert [x.status for x in s.values()] == ["open"] * 4
    assert status.first_start(list(s.values()))
    assert "Kein Vault" in s["system"].detail


def test_facts_win_over_remembered_skip(tmp_path):
    state.mark(tmp_path, "audio_voice", "skipped")
    assert steps(tmp_path, vault="ok")["audio_voice"].status == "done"
    assert steps(tmp_path, vault="kein-profil")["audio_voice"].status == "skipped"


def test_system_step_needs_checks_and_vault(tmp_path):
    assert steps(tmp_path, vault="kein-profil")["system"].status == "done"
    assert steps(tmp_path, vault="kein-vault")["system"].status == "open"
    bad = steps(tmp_path, vault="ok", checks=BAD)["system"]
    assert bad.status == "open" and "Whisper-Modell" in bad.detail and bad.detail.endswith("...")


def test_manual_steps_need_confirmation_and_derive_from_wake_file(tmp_path):
    assert steps(tmp_path)["safety"].status == "open"
    state.mark(tmp_path, "safety", "done")
    assert steps(tmp_path)["safety"].status == "done"
    (tmp_path / "wakewords.toml").write_text("", encoding="utf-8")
    assert steps(tmp_path)["wake_words"].status == "done"


def test_skipping_everything_ends_first_start_and_explains_limits(tmp_path):
    for step in state.STEPS:
        state.mark(tmp_path, step, "skipped")
    s = list(steps(tmp_path).values())
    assert not status.first_start(s)
    notes = status.restricted_notes(s)
    assert len(notes) == 4 and any("Sprechen bleibt gesperrt" in n for n in notes)
    assert all("Sicherheitsregel" not in n or "bleiben" in n or "gelten" in n for n in notes)


# --- API -----------------------------------------------------------------------------------------

@pytest.fixture()
def api(tmp_path):
    token = new_token()
    core = ApiCore(token)
    register_setup(core, tmp_path, lambda: "kein-profil",
                   list_devices=lambda: {"inputs": ["Mikro A", "Mikro B"], "outputs": ["Box"]})

    def call(type_, **kw):
        return json.loads(core.handle(json.dumps({"token": token, "type": type_, **kw})))
    call.core, call.token = core, token
    return call


def test_api_requires_token_and_is_default_deny(api, tmp_path):
    for t in ("setup.status", "safety.kill", "safety.resume", "audio.devices"):
        assert json.loads(api.core.handle(json.dumps({"type": t}))) == {"ok": False, "error": "unauthorized"}
        assert json.loads(api.core.handle(json.dumps({"token": "x" * 40, "type": t}))) == {"ok": False, "error": "unauthorized"}
    assert not killswitch.is_triggered(tmp_path)                       # ohne Token nichts passiert
    assert api("setup.mach_alles")["error"] == "unknown_type"


def test_status_skip_reopen_done(api, tmp_path):
    r = api("setup.status")
    assert r["ok"] and r["first_start"] and [s["step"] for s in r["steps"]] == list(state.STEPS)
    r = api("setup.skip", step="wake_words")
    assert next(s for s in r["steps"] if s["step"] == "wake_words")["status"] == "skipped" and r["restricted"]
    r = api("setup.reopen", step="wake_words")
    assert next(s for s in r["steps"] if s["step"] == "wake_words")["status"] == "open"
    r = api("setup.done", step="safety")
    assert next(s for s in r["steps"] if s["step"] == "safety")["status"] == "done"


def test_api_validates_steps_and_forbids_faking_fact_steps(api):
    for bad in ("", "../x", None, 3, ["system"]):
        assert api("setup.skip", step=bad) == {"ok": False, "error": "bad_step"}
    assert api("setup.skip") == {"ok": False, "error": "bad_step"}
    for fact_step in ("system", "audio_voice"):                         # nicht per API "erledigt" behaupten
        assert api("setup.done", step=fact_step) == {"ok": False, "error": "not_allowed"}


def test_devices_names_only_and_unavailable_is_neutral(api, tmp_path):
    assert api("audio.devices") == {"ok": True, "inputs": ["Mikro A", "Mikro B"], "outputs": ["Box"]}
    token = new_token()
    core = ApiCore(token)

    def boom():
        raise RuntimeError("C:\\geheim\\pfad kaputt")
    register_setup(core, tmp_path, lambda: "ok", list_devices=boom)
    out = core.handle(json.dumps({"token": token, "type": "audio.devices"}))
    assert json.loads(out) == {"ok": False, "error": "unavailable"} and "geheim" not in out


def test_kill_always_works_resume_needs_confirmation(api, tmp_path):
    assert api("safety.status")["kill"] is False
    assert api("safety.kill") == {"ok": True, "kill": True} and killswitch.is_triggered(tmp_path)
    assert api("setup.status")["kill"] is True
    for unsure in ({}, {"confirm": "true"}, {"confirm": 1}, {"confirm": False}):
        assert api("safety.resume", **unsure) == {"ok": False, "error": "confirm_required"}
        assert killswitch.is_triggered(tmp_path)
    assert api("safety.resume", confirm=True) == {"ok": True, "kill": False} and not killswitch.is_triggered(tmp_path)


def test_responses_never_contain_paths_or_secrets(api, tmp_path):
    token = api.token
    blob = json.dumps([api("setup.status"), api("audio.devices"), api("safety.status"), api("setup.skip", step="system")])
    assert str(tmp_path) not in blob and token not in blob
    for word in ("key", "schlüssel", "vault_id", "hexkey", "password"):
        assert word not in blob.lower().replace("keine", "")


def test_unexpected_handler_error_stays_neutral(tmp_path):
    token = new_token()
    core = ApiCore(token)

    def explode():
        raise OSError(os.fspath(tmp_path))
    register_setup(core, tmp_path, explode)
    out = core.handle(json.dumps({"token": token, "type": "setup.status"}))
    assert json.loads(out) == {"ok": False, "error": "internal"} and str(tmp_path) not in out
