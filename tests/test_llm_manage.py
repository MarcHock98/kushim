import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from kushim.api.llm_api import register_llm
from kushim.api.protocol import ApiCore, new_token
from kushim.config import Config
from kushim.llm import manage
from kushim.llm.manage import ModelInfo, Probe, activate, installed, load_previous, probe, rollback, save_previous, scan_manifests
from kushim.llm.ollama import manifest_rel


def install(root, *names):
    for n in names:
        f = root / manifest_rel(n)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")


def cfg_in(tmp_path, model="qwen2.5:7b"):
    f = tmp_path / "config.toml"
    f.write_text(f'[llm]\nmodel = "{model}"\n', encoding="utf-8")
    return Config.load(f)


GOOD = Probe(True, 0.2, 0.4, "ok")
BAD = Probe(False, 0.0, 5.0, "", "timeout")


# --- Liste ---------------------------------------------------------------------------------------

def test_scan_manifests_names_official_user_and_foreign_models(tmp_path):
    install(tmp_path, "qwen2.5:7b", "qwen3.5:9b", "someone/model:tagx", "hf.co/org/repo:Q4_K_M")
    base = tmp_path / "models" / "ollama" / "manifests" / "registry.ollama.ai" / "library" / "kaputt name"
    base.mkdir(parents=True)
    (base / "x").write_text("x")                                   # ungültiger Name wird übersprungen
    assert set(scan_manifests(tmp_path)) == {"qwen2.5:7b", "qwen3.5:9b", "someone/model:tagx", "hf.co/org/repo:Q4_K_M"}
    assert scan_manifests(tmp_path / "gibt-es-nicht") == []


class Tags(BaseHTTPRequestHandler):
    def do_GET(self):
        out = json.dumps({"models": [{"name": "qwen2.5:7b", "size": 4_700_000_000}, {"name": "qwen3.5:9b", "size": 6_600_000_000}]}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def test_installed_uses_ollama_with_sizes_and_falls_back_to_manifests(tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), Tags)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        got = installed(tmp_path, base_url=f"http://127.0.0.1:{srv.server_port}")
        assert got == [ModelInfo("qwen2.5:7b", 4482), ModelInfo("qwen3.5:9b", 6294)]
    finally:
        srv.shutdown()
    install(tmp_path, "qwen2.5:7b")
    assert installed(tmp_path, base_url="http://127.0.0.1:1") == [ModelInfo("qwen2.5:7b", 0)]     # Ollama aus: Offline-Liste


# --- Probe ---------------------------------------------------------------------------------------

def test_probe_measures_times_and_requires_text():
    ticks = iter([0.0, 0.3, 0.5, 0.9, 1.0, 1.1])
    p = probe("m", chat_stream=lambda msgs: iter(["O", "k."]), clock=lambda: next(ticks))
    assert p.ok and p.text == "Ok." and p.first_token_s == 0.3 and p.total_s > 0
    assert not probe("m", chat_stream=lambda msgs: iter([])).ok
    assert probe("m", chat_stream=lambda msgs: iter(["  "])).error == "empty_answer"


def test_probe_failure_gives_a_short_reason_not_details():
    def boom(msgs):
        raise ConnectionError("C:\\geheim\\pfad kaputt")
        yield
    p = probe("m", chat_stream=boom)
    assert not p.ok and p.error == "ConnectionError" and "geheim" not in json.dumps(p.__dict__)


def test_probe_timeout():
    t = iter([0.0, 0.1, 99.0, 99.0, 99.0])
    p = probe("m", chat_stream=lambda msgs: iter(["a", "b", "c"]), clock=lambda: next(t), limit_s=10)
    assert not p.ok and p.error == "timeout"


# --- Umschalten ----------------------------------------------------------------------------------

def test_switch_saves_only_after_a_good_probe_and_remembers_the_previous(tmp_path):
    install(tmp_path, "qwen2.5:7b", "qwen3.5:9b")
    cfg = cfg_in(tmp_path)
    r = activate(cfg, tmp_path, "qwen3.5:9b", probe_fn=lambda n: GOOD)
    assert r.switched and r.model == "qwen3.5:9b" and r.previous == "qwen2.5:7b" and r.probe == GOOD
    assert Config.load(cfg.path).llm_model == "qwen3.5:9b" and load_previous(tmp_path) == "qwen2.5:7b"


def test_failed_probe_or_missing_model_changes_nothing(tmp_path):
    install(tmp_path, "qwen2.5:7b", "qwen3.5:9b")
    cfg = cfg_in(tmp_path)
    r = activate(cfg, tmp_path, "qwen3.5:9b", probe_fn=lambda n: BAD)
    assert not r.switched and r.reason == "probe_failed" and r.probe == BAD and r.model == "qwen2.5:7b"
    assert Config.load(cfg.path).llm_model == "qwen2.5:7b" and load_previous(tmp_path) == ""
    r = activate(cfg, tmp_path, "gibt:es", probe_fn=lambda n: pytest.fail("Probe ohne Installation"))
    assert r.reason == "not_installed" and Config.load(cfg.path).llm_model == "qwen2.5:7b"
    assert activate(cfg, tmp_path, "qwen2.5:7b", probe_fn=lambda n: pytest.fail("schon aktiv")).reason == "already_active"
    with pytest.raises(ValueError):
        activate(cfg, tmp_path, "../evil", probe_fn=lambda n: GOOD)
    with pytest.raises(ValueError):
        activate(cfg, tmp_path, "x; rm -rf", probe_fn=lambda n: GOOD)


def test_save_failure_leaves_the_config_unchanged(tmp_path):
    install(tmp_path, "qwen2.5:7b", "qwen3.5:9b")
    cfg = cfg_in(tmp_path)
    (tmp_path / "run").write_text("ich bin eine Datei, kein Ordner")        # run/llm-state.json kann nicht angelegt werden
    r = activate(cfg, tmp_path, "qwen3.5:9b", probe_fn=lambda n: GOOD)
    assert not r.switched and r.reason == "not_saved" and Config.load(cfg.path).llm_model == "qwen2.5:7b"


def test_rollback_toggles_between_the_two_models(tmp_path):
    install(tmp_path, "qwen2.5:7b", "qwen3.5:9b")
    cfg = cfg_in(tmp_path)
    assert rollback(cfg, tmp_path, probe_fn=lambda n: GOOD).reason == "nothing_to_roll_back"
    activate(cfg, tmp_path, "qwen3.5:9b", probe_fn=lambda n: GOOD)
    r = rollback(cfg, tmp_path, probe_fn=lambda n: GOOD)
    assert r.switched and r.model == "qwen2.5:7b" and load_previous(tmp_path) == "qwen3.5:9b"
    assert rollback(cfg, tmp_path, probe_fn=lambda n: GOOD).model == "qwen3.5:9b"
    bad = rollback(cfg, tmp_path, probe_fn=lambda n: BAD)                      # Probe scheitert: bleibt
    assert not bad.switched and Config.load(cfg.path).llm_model == "qwen3.5:9b"


def test_junk_state_file_means_no_previous(tmp_path):
    p = tmp_path / manage.STATE
    p.parent.mkdir(parents=True)
    for junk in ("{kaputt", "[]", '{"previous": "../x"}', '{"previous": 5}', ""):
        p.write_text(junk, encoding="utf-8")
        assert load_previous(tmp_path) == "", junk
    save_previous(tmp_path, "qwen2.5:7b")
    assert load_previous(tmp_path) == "qwen2.5:7b" and not list(p.parent.glob("*.tmp"))
    with pytest.raises(ValueError):
        save_previous(tmp_path, "../evil")


# --- API -----------------------------------------------------------------------------------------

@pytest.fixture()
def api(tmp_path):
    install(tmp_path, "qwen2.5:7b", "qwen3.5:9b")
    cfg, token, changed = cfg_in(tmp_path), new_token(), []
    core = ApiCore(token)
    state = {"probe": GOOD}
    register_llm(core, cfg, tmp_path, probe_fn=lambda n: state["probe"],
                 installed_fn=lambda root: [ModelInfo("qwen2.5:7b", 4482), ModelInfo("qwen3.5:9b", 6293)], on_change=changed.append)

    def call(type_, **kw):
        return json.loads(core.handle(json.dumps({"token": token, "type": type_, **kw})))
    call.core, call.cfg, call.changed, call.state, call.token, call.root = core, cfg, changed, state, token, tmp_path
    return call


def test_api_needs_token_and_reports_state(api):
    assert json.loads(api.core.handle(json.dumps({"type": "llm.set", "model": "qwen3.5:9b"}))) == {"ok": False, "error": "unauthorized"}
    assert api.cfg.llm_model == "qwen2.5:7b"
    assert api("llm.get") == {"ok": True, "model": "qwen2.5:7b", "previous": "", "installed": True}
    models = api("llm.list")["models"]
    assert [m["name"] for m in models] == ["qwen2.5:7b", "qwen3.5:9b"] and models[0]["active"] and not models[1]["active"]


def test_api_switch_calls_on_change_only_on_success_and_rollback_works(api):
    api.state["probe"] = BAD
    r = api("llm.set", model="qwen3.5:9b")
    assert r["ok"] and r["switched"] is False and r["reason"] == "probe_failed" and r["probe"]["error"] == "timeout"
    assert api.changed == [] and api.cfg.llm_model == "qwen2.5:7b"
    api.state["probe"] = GOOD
    r = api("llm.set", model="qwen3.5:9b")
    assert r["switched"] and r["model"] == "qwen3.5:9b" and api.changed == ["qwen3.5:9b"] and api("llm.get")["previous"] == "qwen2.5:7b"
    r = api("llm.rollback")
    assert r["switched"] and r["model"] == "qwen2.5:7b" and api.changed == ["qwen3.5:9b", "qwen2.5:7b"]


def test_api_validates_input_and_installation(api):
    assert api("llm.set", model="../evil") == {"ok": False, "error": "bad_name"}
    assert api("llm.set", model=5) == {"ok": False, "error": "bad_request"}
    assert api("llm.set") == {"ok": False, "error": "bad_request"}
    assert api("llm.probe", model="gibt:es") == {"ok": False, "error": "not_installed"}
    r = api("llm.probe", model="qwen3.5:9b")
    assert r["ok"] and r["probe"]["ok"] and r["model"] == "qwen3.5:9b"
    assert api("llm.rollback")["reason"] == "nothing_to_roll_back"


def test_api_responses_have_no_paths_or_token(api):
    blob = json.dumps([api("llm.get"), api("llm.list"), api("llm.set", model="qwen3.5:9b"), api("llm.rollback")])
    assert api.token not in blob and str(api.root) not in blob and "C:\\" not in blob
