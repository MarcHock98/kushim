import pytest

from kushim.config import Config
from kushim.doctor import run_checks
from kushim.llm.ollama import DEFAULT_MODEL, manifest_rel


def test_default_model(tmp_path):
    assert Config.load(tmp_path / "none.toml").llm_model == DEFAULT_MODEL


def test_set_model_roundtrip_keeps_rest(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[memory]\nlocation = "local:x"\n\n[privacy]\nclaude_enabled = false\n', encoding="utf-8")
    cfg = Config.load(p)
    cfg.set_llm_model("qwen3.5:9b")
    cfg.set_llm_model("gemma4:e4b")
    again = Config.load(p)
    assert again.llm_model == "gemma4:e4b" and again.memory_location == "local:x"
    assert p.read_text(encoding="utf-8").count("[llm]") == 1


def test_invalid_model_rejected(tmp_path):
    p = tmp_path / "config.toml"
    cfg = Config.load(p)
    with pytest.raises(ValueError):
        cfg.set_llm_model("x; rm -rf")
    p.write_text('[llm]\nmodel = "../evil"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        Config.load(p)


def test_doctor_checks_configured_model(tmp_path):
    by = {c.name: c for c in run_checks(tmp_path, llm_model="qwen3.5:9b")}
    assert not by["LLM qwen3.5:9b"].ok
    f = tmp_path / manifest_rel("qwen3.5:9b")
    f.parent.mkdir(parents=True)
    f.write_text("x")
    assert {c.name: c for c in run_checks(tmp_path, llm_model="qwen3.5:9b")}["LLM qwen3.5:9b"].ok
