import json

import pytest

from kushim import cli
from kushim.api.protocol import ApiCore, new_token
from kushim.api.tools_api import register_tools
from kushim.config import Config
from kushim.safety.gate import ActionGate, ActionRequest, ActionSpec, Decision, Risk
from kushim.tools.registry import WEB_SEARCH, ToolInfo, ToolGate, ToolNotAllowed, ToolRegistry, default_tools

LOCAL = ToolInfo("demo.local", "Demo lokal", "Liest nur lokal.", ActionSpec("demo.local", Risk.READ), sends_data_out=False)
OUTER = ToolInfo("demo.outer", "Demo außen", "Fragt etwas im Netz.", ActionSpec("demo.outer", Risk.READ, external_effect=True),
                 sends_data_out=True)
BLOCKED = ToolInfo("demo.blocked", "Demo gesperrt", "Noch nicht freigegeben.", ActionSpec("demo.blocked", Risk.READ),
                   sends_data_out=False, available=lambda: "Voraussetzung fehlt")


def registry(enabled=()):
    return ToolRegistry([LOCAL, OUTER, BLOCKED], enabled)


# --- Registry ------------------------------------------------------------------------------------

def test_everything_is_off_by_default():
    r = registry()
    assert r.enabled_names() == [] and not any(r.is_active(n) for n in r.tools)
    assert ToolRegistry(default_tools()).enabled_names() == []


def test_unknown_names_in_the_enabled_list_are_ignored_not_widened():
    r = registry(["demo.local", "tippfehler", "*", "all"])
    assert r.enabled_names() == ["demo.local"]


def test_enabling_needs_confirmation_and_availability():
    r, saved = registry(), []
    with pytest.raises(ToolNotAllowed) as e:
        r.set_enabled("demo.local", True, persist=saved.append)
    assert e.value.code == "confirm_required" and not r.is_enabled("demo.local") and saved == []
    with pytest.raises(ToolNotAllowed) as e:
        r.set_enabled("demo.blocked", True, confirmed=True, persist=saved.append)
    assert e.value.code == "not_available" and saved == []
    with pytest.raises(ToolNotAllowed) as e:
        r.set_enabled("gibt.es.nicht", True, confirmed=True)
    assert e.value.code == "bad_tool"
    r.set_enabled("demo.local", True, confirmed=True, persist=saved.append)
    assert r.is_active("demo.local") and saved == [["demo.local"]]


def test_disabling_always_works_without_confirmation():
    r = registry(["demo.local", "demo.outer"])
    r.set_enabled("demo.local", False)
    assert r.enabled_names() == ["demo.outer"]
    r.set_enabled("demo.local", False)                          # nochmal: kein Fehler


def test_a_failing_save_leaves_the_state_unchanged():
    r = registry()

    def boom(names):
        raise OSError("Platte voll")
    with pytest.raises(OSError):
        r.set_enabled("demo.local", True, confirmed=True, persist=boom)
    assert not r.is_enabled("demo.local")


def test_enabled_but_unavailable_is_not_active():
    r = registry(["demo.blocked"])
    assert r.is_enabled("demo.blocked") and not r.is_active("demo.blocked")


def test_web_search_is_available_but_off_until_the_user_confirms():
    assert not ToolRegistry(default_tools()).is_active("web.search")                       # Standard: aus
    r = ToolRegistry(default_tools())
    with pytest.raises(ToolNotAllowed) as e:
        r.set_enabled("web.search", True)                                                  # ohne Bestätigung nie
    assert e.value.code == "confirm_required" and not r.is_enabled("web.search")
    r.set_enabled("web.search", True, confirmed=True)
    assert r.is_active("web.search")
    assert WEB_SEARCH.sends_data_out and WEB_SEARCH.spec.external_effect
    assert "keine Downloads" in WEB_SEARCH.description


# --- ToolGate ------------------------------------------------------------------------------------

def req(action, **kw):
    return ActionRequest(action, f"Vorschau {action}", user_initiated=True, speaker_verified=True, **kw)


def gate_for(*tools):
    return ActionGate([t.spec for t in tools], reviewer=lambda spec, r: set())


def test_disabled_tool_is_denied_even_if_the_gate_would_allow():
    g = gate_for(LOCAL, OUTER)
    assert g.check(req("demo.local")).decision is Decision.ALLOW          # der Gate allein würde erlauben
    tg = ToolGate(g, registry())
    v = tg.check(req("demo.local"))
    assert v.decision is Decision.DENY and "deaktiviert" in v.reason


def test_enabled_tool_still_goes_through_the_gate_rules():
    tg = ToolGate(gate_for(LOCAL, OUTER), registry(["demo.local", "demo.outer"]))
    assert tg.check(req("demo.local")).decision is Decision.ALLOW
    assert tg.check(req("demo.outer")).decision is Decision.ASK           # Außenwirkung: weiter Vorschau und Freigabe
    not_user = ActionRequest("demo.outer", "x", user_initiated=False, speaker_verified=True)
    assert tg.check(not_user).decision is Decision.DENY                   # nicht vom Nutzer ausgelöst
    tg.kill()
    assert tg.check(req("demo.local")).decision is Decision.DENY          # Notaus des Gates wirkt durch die Hülle


def test_enabled_but_unavailable_tool_is_denied():
    tg = ToolGate(gate_for(BLOCKED), registry(["demo.blocked"]))
    assert tg.check(req("demo.blocked")).decision is Decision.DENY


def test_actions_outside_the_registry_are_untouched_and_unknown_ones_denied():
    other = ActionSpec("wake_word_change", Risk.REVERSIBLE)
    tg = ToolGate(ActionGate([other], reviewer=lambda s, r: set()), registry())
    assert tg.check(req("wake_word_change")).decision is Decision.ASK
    assert tg.check(req("irgendwas")).decision is Decision.DENY           # Default-Deny des Gates


# --- Config --------------------------------------------------------------------------------------

def test_config_roundtrip_keeps_other_sections_and_is_atomic(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('[memory]\nlocation = "local:x"\n\n[llm]\nmodel = "qwen2.5:7b"\n', encoding="utf-8")
    c = Config.load(f)
    assert c.tools_enabled == ()
    c.set_tools_enabled(["web.search", "demo.local", "web.search"])
    again = Config.load(f)
    assert again.tools_enabled == ("demo.local", "web.search") and again.memory_location == "local:x" and again.llm_model == "qwen2.5:7b"
    c.set_tools_enabled([])
    assert Config.load(f).tools_enabled == () and not list(tmp_path.glob("*.tmp"))
    assert f.read_text(encoding="utf-8").count("[tools]") == 1


def test_config_rejects_bad_names_and_ignores_junk_in_the_file(tmp_path):
    f = tmp_path / "config.toml"
    c = Config(path=f)
    for bad in (["../x"], ["UPPER"], ["a b"], ['x"; evil'], [""]):
        with pytest.raises(ValueError):
            c.set_tools_enabled(bad)
    assert not f.exists()
    for junk in ('[tools]\nenabled = "web.search"\n', '[tools]\nenabled = [1, 2, "OK"]\n', "[tools]\nenabled = [[1]]\n"):
        f.write_text(junk, encoding="utf-8")
        assert Config.load(f).tools_enabled == ()


# --- API -----------------------------------------------------------------------------------------

@pytest.fixture()
def api():
    token, reg, saved = new_token(), registry(), []
    core = ApiCore(token)
    register_tools(core, reg, saved.append)

    def call(type_, **kw):
        return json.loads(core.handle(json.dumps({"token": token, "type": type_, **kw})))
    call.core, call.reg, call.saved, call.token = core, reg, saved, token
    return call


def test_api_needs_token_and_lists_everything_off(api):
    assert json.loads(api.core.handle(json.dumps({"type": "tools.list"}))) == {"ok": False, "error": "unauthorized"}
    assert json.loads(api.core.handle(json.dumps({"type": "tools.set", "name": "demo.local", "enabled": True,
                                                  "confirm": True}))) == {"ok": False, "error": "unauthorized"}
    assert api.reg.enabled_names() == []
    r = api("tools.list")
    assert r["ok"] and [t["name"] for t in r["tools"]] == ["demo.local", "demo.outer", "demo.blocked"]
    assert not any(t["enabled"] or t["active"] for t in r["tools"])
    blocked = next(t for t in r["tools"] if t["name"] == "demo.blocked")
    assert blocked["available"] is False and blocked["reason"] == "Voraussetzung fehlt"
    assert next(t for t in r["tools"] if t["name"] == "demo.outer")["sends_data_out"] is True


def test_api_enable_needs_explicit_confirm_true_disable_does_not(api):
    for unsure in ({}, {"confirm": "true"}, {"confirm": 1}, {"confirm": False}):
        assert api("tools.set", name="demo.local", enabled=True, **unsure) == {"ok": False, "error": "confirm_required"}
    assert api.saved == [] and not api.reg.is_enabled("demo.local")
    r = api("tools.set", name="demo.local", enabled=True, confirm=True)
    assert next(t for t in r["tools"] if t["name"] == "demo.local")["active"] is True and api.saved == [["demo.local"]]
    r = api("tools.set", name="demo.local", enabled=False)
    assert next(t for t in r["tools"] if t["name"] == "demo.local")["enabled"] is False and api.saved[-1] == []


def test_api_validates_input_and_unavailable_tools(api):
    assert api("tools.set", name="demo.blocked", enabled=True, confirm=True) == {"ok": False, "error": "not_available"}
    assert api("tools.set", name="gibt.es.nicht", enabled=True, confirm=True) == {"ok": False, "error": "bad_tool"}
    for bad in ({"name": 3, "enabled": True}, {"name": "demo.local", "enabled": "ja"}, {"enabled": True}, {"name": "demo.local"}):
        assert api("tools.set", confirm=True, **bad) == {"ok": False, "error": "bad_request"}


def test_api_save_failure_is_neutral_and_changes_nothing(tmp_path):
    token, reg = new_token(), registry()
    core = ApiCore(token)

    def boom(names):
        raise OSError(str(tmp_path))
    register_tools(core, reg, boom)
    out = core.handle(json.dumps({"token": token, "type": "tools.set", "name": "demo.local", "enabled": True, "confirm": True}))
    assert json.loads(out) == {"ok": False, "error": "not_saved"} and str(tmp_path) not in out and not reg.is_enabled("demo.local")


def test_api_responses_have_no_paths_or_secrets(api):
    blob = json.dumps([api("tools.list"), api("tools.set", name="demo.local", enabled=True, confirm=True)])
    assert api.token not in blob and "C:\\" not in blob and "/home" not in blob


# --- CLI -----------------------------------------------------------------------------------------

def test_cli_lists_tools_and_refuses_unavailable_enable(tmp_path, monkeypatch, capsys):
    f = tmp_path / "config.toml"
    monkeypatch.setenv("KUSHIM_CONFIG", str(f))
    assert cli.main(["tools"]) == 0
    out = capsys.readouterr().out
    assert "web.search" in out and "[aus]" in out and "sendet Daten nach außen" in out and "keine Downloads" in out
    import kushim.tools.registry as reg
    monkeypatch.setattr(reg, "default_tools", lambda: [BLOCKED])
    assert cli.main(["tools", "enable", "demo.blocked"]) == 1                  # nicht verfügbar: gar nicht erst gefragt
    assert "Voraussetzung fehlt" in capsys.readouterr().out and not f.exists()
    assert cli.main(["tools", "enable", "gibt.es.nicht"]) == 2


def test_cli_enable_asks_and_defaults_to_no(tmp_path, monkeypatch, capsys):
    f = tmp_path / "config.toml"
    monkeypatch.setenv("KUSHIM_CONFIG", str(f))
    monkeypatch.setattr(cli, "default_tools", lambda: [LOCAL], raising=False)
    import kushim.tools.registry as reg
    monkeypatch.setattr(reg, "default_tools", lambda: [LOCAL])
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    assert cli.main(["tools", "enable", "demo.local"]) == 1 and not f.exists()          # Enter = Nein
    monkeypatch.setattr("builtins.input", lambda prompt="": "j")
    assert cli.main(["tools", "enable", "demo.local"]) == 0
    assert Config.load(f).tools_enabled == ("demo.local",)
    assert cli.main(["tools", "disable", "demo.local"]) == 0 and Config.load(f).tools_enabled == ()
