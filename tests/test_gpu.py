import subprocess
from pathlib import Path

import pytest

from kushim import gpu
from kushim.config import Config
from kushim.gpu import Gpu, make_plan, parse_gpus


def g(i, mb, name="Karte"):
    return Gpu(i, f"{name} {i}", mb, mb - 500, f"GPU-uuid-{i}")


CSV = ("0, NVIDIA GeForce RTX 3070, 8192, 185, GPU-aaa\n"
       "1, NVIDIA Tesla, Model X, 24576, 24000, GPU-bbb\n"
       "kaputte Zeile\n")


def test_parse_nvidia_smi_output_including_commas_in_names():
    gpus = parse_gpus(CSV)
    assert [x.index for x in gpus] == [0, 1]
    assert gpus[0].name == "NVIDIA GeForce RTX 3070" and gpus[0].total_mb == 8192 and gpus[0].free_mb == 185
    assert gpus[1].name == "NVIDIA Tesla, Model X" and gpus[1].uuid == "GPU-bbb"


def test_list_gpus_without_nvidia_smi_or_on_failure(monkeypatch):
    monkeypatch.setattr(gpu, "_nvidia_smi", lambda: None)
    assert gpu.list_gpus() == []
    monkeypatch.setattr(gpu, "_nvidia_smi", lambda: "nvidia-smi")
    bad = lambda *a, **k: subprocess.CompletedProcess(a, 9, stdout="", stderr="x")
    assert gpu.list_gpus(run=bad) == []
    boom = lambda *a, **k: (_ for _ in ()).throw(OSError("weg"))
    assert gpu.list_gpus(run=boom) == []
    ok = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=CSV, stderr="")
    assert len(gpu.list_gpus(run=ok)) == 2


def test_no_gpu_means_whisper_on_cpu():
    p = make_plan([])
    assert p.whisper_device == "cpu" and p.notes


def test_single_gpu_is_used_for_whisper():
    p = make_plan([g(0, 8192)])
    assert (p.whisper_device, p.whisper_index) == ("cuda", 0)


def test_several_gpus_whisper_takes_the_biggest_card():
    p = make_plan([g(0, 8192), g(1, 24576), g(2, 12288)])
    assert p.whisper_device == "cuda" and p.whisper_index == 1
    assert make_plan([g(0, 8192), g(1, 8192)]).whisper_index == 0          # gleich groß: die erste


def test_manual_settings():
    gpus = [g(0, 8192), g(1, 8192), g(2, 8192)]
    assert make_plan(gpus, whisper="cpu").whisper_device == "cpu"
    assert make_plan(gpus, whisper="2").whisper_index == 2


def test_wrong_numbers_are_reported_not_ignored():
    gpus = [g(0, 8192)]
    for bad, cards in (("3", gpus), ("x", gpus), (",", gpus), ("0,1", gpus + [g(1, 8192)])):
        with pytest.raises(ValueError):
            make_plan(cards, whisper=bad)


def test_describe_shows_assignment_without_a_language_model():
    gpus = [g(0, 8192), g(1, 8192)]
    text = gpu.describe(gpus, make_plan(gpus))
    assert "0:" in text and "Whisper" in text and "Sprachmodell" not in text and "unbenutzt" in text


def test_config_reads_gpu_section_and_ignores_the_old_llm_keys(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('[llm]\nmodel = "qwen2.5:7b"\n\n[gpu]\nwhisper = "1"\nllm = "0,2"\n', encoding="utf-8")
    assert Config.load(f).gpu_whisper == "1"
    assert Config.load(tmp_path / "none.toml").gpu_whisper == "auto"
