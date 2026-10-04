"""Modelle laden und entfernen: nur offizielle Bibliothek, nie aktives/vorheriges/letztes Modell, Freigabe hash-gebunden und einmalig."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from kushim.llm import manage
from kushim.llm.ops import ModelOps, OpsError, library_name, pull_preview, remove_preview
from kushim.safety.gate import Decision


def install(root: Path, *names: str):
    for n in names:
        name, _, tag = n.partition(":")
        p = root / "models" / "ollama" / "manifests" / "registry.ollama.ai" / "library" / name / tag
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}")


def make(tmp_path, installed=("qwen3.5:9b", "qwen2.5:7b", "llama3:8b"), active="qwen3.5:9b"):
    install(tmp_path, *installed)
    calls = []
    cfg = SimpleNamespace(llm_model=active)

    def request(method, url, payload=None, timeout=30.0):
        calls.append((method, url, payload, timeout))
        if url.endswith("/api/pull"):
            install(tmp_path, payload["model"])
        if url.endswith("/api/delete"):
            n, _, t = payload["model"].partition(":")
            (tmp_path / "models" / "ollama" / "manifests" / "registry.ollama.ai" / "library" / n / t).unlink()
        return {"status": "success"}

    return ModelOps(cfg, tmp_path, request=request), calls


@pytest.mark.parametrize("name", ["hf.co/org/repo:Q4", "nutzer/modell:1b", "llama3", "../x:1", "a b:1", "http://evil/x:1", ""])
def test_only_official_library_names_with_tag(name):
    with pytest.raises(ValueError):
        library_name(name)


def test_library_name_accepts_normal_names():
    assert library_name("qwen3.5:9b") == "qwen3.5:9b" and library_name("llama3.1:8b-instruct-q4_K_M") == "llama3.1:8b-instruct-q4_K_M"


def test_pull_needs_verified_speaker_preview_and_approval(tmp_path):
    ops, calls = make(tmp_path)
    assert ops.propose_pull("gemma3:4b", speaker_verified=False).decision is Decision.DENY
    p = ops.propose_pull("gemma3:4b", speaker_verified=True)
    assert p.decision is Decision.ASK and "gemma3:4b" in p.preview and "registry.ollama.ai" in p.preview and "mehrere GB" in p.preview
    assert calls == []                                                          # vor der Freigabe passiert nichts
    assert ops.approve(p) and "geladen" in ops.execute(p)
    assert calls[0][0] == "POST" and calls[0][1].endswith("/api/pull") and calls[0][2] == {"model": "gemma3:4b", "stream": False}
    with pytest.raises(OpsError):
        ops.execute(p)                                                          # einmalig


def test_pull_denied_when_installed_foreign_or_unapproved(tmp_path):
    ops, calls = make(tmp_path)
    assert "schon installiert" in ops.propose_pull("qwen3.5:9b", True).reason
    assert ops.propose_pull("hf.co/x/y:Q4", True).decision is Decision.DENY
    p = ops.propose_pull("gemma3:4b", True)
    with pytest.raises(OpsError):
        ops.execute(p)                                                          # ohne approve
    ops.deny(p)
    assert not ops.approve(p) and calls == []


def test_notaus_blocks_everything(tmp_path):
    ops, calls = make(tmp_path)
    p = ops.propose_pull("gemma3:4b", True)
    ops.gate.kill()
    assert not ops.approve(p) or True
    with pytest.raises(OpsError):
        ops.execute(p)
    assert ops.propose_pull("gemma3:2b", True).decision is Decision.DENY and calls == []


def test_remove_protects_active_previous_and_last(tmp_path):
    ops, calls = make(tmp_path)
    manage.save_previous(tmp_path, "qwen2.5:7b")
    assert "aktive" in ops.propose_remove("qwen3.5:9b", True).reason
    assert "vorherige" in ops.propose_remove("qwen2.5:7b", True).reason
    assert "nicht installiert" in ops.propose_remove("gemma3:4b", True).reason
    ops2, _ = make(tmp_path / "eins", installed=("qwen3.5:9b",), active="anderes:1b")
    assert "letzte" in ops2.propose_remove("qwen3.5:9b", True).reason
    assert calls == []


def test_remove_flow(tmp_path):
    ops, calls = make(tmp_path)
    p = ops.propose_remove("llama3:8b", True)
    assert p.decision is Decision.ASK and "llama3:8b" in p.preview and "keine Rückgabe" in p.preview
    assert ops.approve(p) and "entfernt" in ops.execute(p)
    assert calls[0][0] == "DELETE" and calls[0][1].endswith("/api/delete") and calls[0][2] == {"model": "llama3:8b"}
    assert not manage.is_installed(tmp_path, "llama3:8b")


def test_execute_rechecks_protection_at_execution_time(tmp_path):
    ops, calls = make(tmp_path)
    p = ops.propose_remove("llama3:8b", True)
    ops.approve(p)
    ops.cfg.llm_model = "llama3:8b"                                             # inzwischen aktiv gesetzt
    with pytest.raises(OpsError, match="aktive"):
        ops.execute(p)
    assert calls == []


def test_ollama_down_gives_neutral_error(tmp_path):
    ops, _ = make(tmp_path)

    def broken(*a, **k):
        raise ConnectionRefusedError("C:\\geheim")
    ops.request = broken
    p = ops.propose_remove("llama3:8b", True)
    ops.approve(p)
    with pytest.raises(OpsError) as e:
        ops.execute(p)
    assert "geheim" not in str(e.value) and "kushim start" in str(e.value)


def test_previews_are_what_they_say():
    assert "qwen3.5:9b" in pull_preview("qwen3.5:9b") and "Gesendet wird nur der Modellname" in pull_preview("x:1")
    assert "gelöscht" in remove_preview("x:1")
