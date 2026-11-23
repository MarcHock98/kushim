"""Netzsperre des Sprachausgabe-Workers (scripts/kokoro_worker.py): greift auch für Loopback, kommt vor jedem Import außerhalb
der Standardbibliothek, und der Worker enthält keine Download-Aufrufe. test_no_egress.py gilt für src/ und bleibt unverändert;
dieser Test deckt das Skript ab, das außerhalb von src/ im eigenen venv läuft."""
import ast
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kushim.voice import ttsworker as tw

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "scripts" / "kokoro_worker.py"
ASSETS = Path(os.environ.get("KUSHIM_MODELS_ROOT") or ROOT)
TREE = ast.parse(WORKER.read_text(encoding="utf-8"))
STDLIB_TOP = {"__future__", "json", "os", "struct", "sys", "threading", "time"}
THIRD_PARTY = {"numpy", "onnxruntime", "kokoro_onnx", "espeakng_loader", "phonemizer", "soundfile"}
NETWORK = {"socket", "_socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx", "aiohttp", "huggingface_hub", "websockets",
           "ftplib", "smtplib", "asyncio"}


def _imports(nodes):
    for node in nodes:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Import):
                yield sub, [a.name.split(".")[0] for a in sub.names]
            elif isinstance(sub, ast.ImportFrom):
                yield sub, [(sub.module or "").split(".")[0]]


def _func(name):
    return next(n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and n.name == name)


def _first_line(func, pred):
    lines = [n.lineno for n in ast.walk(func) if pred(n)]
    return min(lines) if lines else None


def _calls(name):
    return lambda n: isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", None)) == name


def test_module_level_imports_are_only_stdlib():
    top = [n for n in TREE.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    mods = {m for _, ms in _imports(top) for m in ms}
    assert mods <= STDLIB_TOP, mods


def test_third_party_and_network_modules_are_imported_only_inside_functions():
    allowed_net = {"block_network", "selftest_network"}       # die Sperre selbst und ihr Selbsttest
    for func in (n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef)):
        for _, mods in _imports(func.body):
            net = set(mods) & NETWORK
            assert not net or func.name in allowed_net, (func.name, net)


def test_main_blocks_the_network_before_loading_anything():
    main = _func("main")
    block = _first_line(main, _calls("block_network"))
    load = _first_line(main, _calls("KokoroEngine"))
    redirect = _first_line(main, lambda n: isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Attribute) and t.attr == "stdout" for t in n.targets))
    assert block and load and redirect and redirect < block < load
    # KokoroEngine importiert die Bibliotheken erst im Konstruktor, also nach der Sperre
    engine_init = next(n for n in ast.walk(_func_in_class("KokoroEngine", "__init__")) if isinstance(n, ast.ImportFrom))
    assert engine_init.module == "kokoro_onnx"


def _func_in_class(cls, name):
    klass = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == cls)
    return next(n for n in klass.body if isinstance(n, ast.FunctionDef) and n.name == name)


def test_selftest_blocks_before_trying():
    st = _func("selftest_network")
    assert _first_line(st, _calls("block_network")) < _first_line(st, _calls("create_connection"))


def test_worker_has_no_download_or_remote_calls():
    names = {n.id for n in ast.walk(TREE) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(TREE) if isinstance(n, ast.Attribute)}
    banned = {"urlopen", "urlretrieve", "hf_hub_download", "snapshot_download", "from_pretrained", "download_models", "download",
              "Request", "HTTPConnection", "HTTPSConnection", "requests", "httpx", "urllib", "load_dataset"}
    assert not names & banned, names & banned
    src = WORKER.read_text(encoding="utf-8")
    assert "http://" not in src and "https://" not in src and "huggingface" not in src.lower()


def test_worker_only_loads_the_fixed_voice_and_model_files():
    src = WORKER.read_text(encoding="utf-8")
    assert 'VOICE = "martin"' in src and 'MODEL_FILE = "kokoro-martin.onnx"' in src and 'VOICES_FILE = "voices-martin.npz"' in src
    assert "audio_prompt" not in src and "clone" not in src.lower()          # nur die eingebaute Stimme, kein Klonen


def _selftest(python):
    r = subprocess.run([str(python), "-I", str(WORKER), "--selftest-net"], capture_output=True, timeout=60, env=tw.worker_env())
    header, _ = tw.read_frame(io.BytesIO(r.stdout))
    return r.returncode, header


def test_network_block_works_at_runtime_including_loopback():
    code, header = _selftest(sys.executable)
    assert code == 0 and header["type"] == "selftest" and header["open"] == []
    assert set(header["blocked"]) == {"socket", "raw_socket", "create_connection", "getaddrinfo", "socketpair", "gethostbyname"}
    assert header["offline"] is True


@pytest.mark.skipif(not (ASSETS / tw.VENV_PYTHON).is_file(), reason="tools/kokoro/venv fehlt (KUSHIM_MODELS_ROOT setzen)")
def test_network_block_in_the_kokoro_venv_and_libraries_import_under_it(tmp_path):
    python = ASSETS / tw.VENV_PYTHON
    code, header = _selftest(python)
    assert code == 0 and header["open"] == []
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import importlib.util, socket, sys\n"
        f"spec = importlib.util.spec_from_file_location('kw', {str(WORKER)!r})\n"
        "kw = importlib.util.module_from_spec(spec); spec.loader.exec_module(kw)\n"
        "kw.block_network()\n"
        "import numpy, onnxruntime, kokoro_onnx, espeakng_loader, phonemizer\n"
        "try:\n    socket.create_connection(('127.0.0.1', 9), timeout=1)\nexcept OSError:\n    print('GESPERRT')\n"
        "else:\n    print('OFFEN')\n", encoding="utf-8")
    r = subprocess.run([str(python), "-I", str(probe)], capture_output=True, text=True, timeout=120, env=tw.worker_env())
    assert r.returncode == 0, r.stderr[-500:]
    assert r.stdout.strip() == "GESPERRT"                  # die Bibliotheken heben die Sperre nicht auf


def test_client_starts_the_worker_isolated_and_only_from_the_project():
    w = tw.KokoroWorker.for_root(Path("C:/kushim"), "cuda", device_id=1)
    argv = w._command("cuda")
    assert argv[1] == "-I" and argv[0].endswith(str(tw.VENV_PYTHON)) and argv[2].endswith(str(tw.WORKER_SCRIPT))
    assert argv[argv.index("--model-dir") + 1].endswith(str(tw.MODEL_DIR)) and argv[-1] == "1"
