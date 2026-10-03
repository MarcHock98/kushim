import subprocess
from pathlib import Path

import pytest

from kushim import gpu
from kushim.config import Config
from kushim.gpu import Gpu, make_plan, parse_gpus
from kushim.launcher import Launcher, ollama_env


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


def test_no_gpu_means_whisper_on_cpu_and_ollama_untouched():
    p = make_plan([])
    assert p.whisper_device == "cpu" and p.llm_visible is None and p.notes


def test_single_gpu_keeps_everything_as_before():
    p = make_plan([g(0, 8192)])
    assert (p.whisper_device, p.whisper_index, p.llm_visible) == ("cuda", 0, None)


def test_two_equal_gpus_whisper_gets_one_llm_gets_the_other():
    p = make_plan([g(0, 8192), g(1, 8192)])
    assert p.whisper_device == "cuda" and p.whisper_index == 0 and p.llm_visible == "GPU-uuid-1"


def test_whisper_takes_the_smallest_card_that_fits_and_llm_the_rest():
    p = make_plan([g(0, 24576), g(1, 6144), g(2, 12288)])
    assert p.whisper_index == 1 and p.llm_visible == "GPU-uuid-0,GPU-uuid-2"


def test_tiny_cards_only_whisper_takes_the_biggest():
    p = make_plan([g(0, 2048), g(1, 3072)])
    assert p.whisper_index == 1 and p.llm_visible == "GPU-uuid-0"


def test_manual_settings():
    gpus = [g(0, 8192), g(1, 8192), g(2, 8192)]
    assert make_plan(gpus, whisper="cpu").whisper_device == "cpu"
    assert make_plan(gpus, whisper="cpu").llm_visible is None
    p = make_plan(gpus, whisper="2", llm="0,1")
    assert p.whisper_index == 2 and p.llm_visible == "GPU-uuid-0,GPU-uuid-1"
    assert make_plan(gpus, llm="all").llm_visible is None
    shared = make_plan(gpus, whisper="0", llm="0")
    assert shared.llm_visible == "GPU-uuid-0" and any("teilen sich" in n for n in shared.notes)


def test_wrong_numbers_are_reported_not_ignored():
    gpus = [g(0, 8192)]
    for kw in ({"whisper": "3"}, {"llm": "5"}, {"llm": "x"}, {"whisper": "0,1"}, {"llm": ","}):
        with pytest.raises(ValueError):
            make_plan(gpus + [g(1, 8192)] if kw == {"whisper": "0,1"} else gpus, **kw)


def test_describe_shows_assignment():
    gpus = [g(0, 8192), g(1, 8192)]
    text = gpu.describe(gpus, make_plan(gpus))
    assert "0:" in text and "Whisper" in text and "Sprachmodell" in text


def test_ollama_env_only_pins_cards_when_asked(tmp_path):
    assert "CUDA_VISIBLE_DEVICES" not in ollama_env(tmp_path, {"PATH": "p"})
    assert ollama_env(tmp_path, {"PATH": "p"}, cuda_devices="GPU-1,GPU-2")["CUDA_VISIBLE_DEVICES"] == "GPU-1,GPU-2"


def test_launcher_passes_cards_to_ollama(tmp_path):
    exe = tmp_path / "tools" / "ollama" / "ollama.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("x")
    seen = {}

    class P:
        pid = None
        def poll(self): return None
    launcher = Launcher(tmp_path, popen=lambda *a, **k: seen.update(k) or P(), alive=iter([False, True]).__next__,
                        sleep=lambda s: None, cuda_devices="GPU-9")
    assert launcher.start_ollama() == "started"
    assert seen["env"]["CUDA_VISIBLE_DEVICES"] == "GPU-9"


def test_config_reads_gpu_section(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('[gpu]\nwhisper = "1"\nllm = "0,2"\n', encoding="utf-8")
    c = Config.load(f)
    assert (c.gpu_whisper, c.gpu_llm) == ("1", "0,2")
    assert (Config.load(tmp_path / "none.toml").gpu_whisper, Config.load(tmp_path / "none.toml").gpu_llm) == ("auto", "auto")
