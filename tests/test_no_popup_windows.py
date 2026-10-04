"""Hintergrundprozesse dürfen kein Konsolenfenster öffnen (unter `pythonw` poppt sonst für jedes `git`, `nvidia-smi`, `taskkill` ... ein Fenster auf)."""
import ast
import subprocess
from pathlib import Path

from kushim import procflags

SRC = Path(__file__).resolve().parents[1] / "src" / "kushim"
# Bewusst sichtbar: das Live-Fenster `kushim claude watch` (CREATE_NEW_CONSOLE).
VISIBLE_ON_PURPOSE = {"cli.py"}


def test_hidden_flags_on_windows_and_empty_elsewhere(monkeypatch):
    monkeypatch.setattr(procflags.os, "name", "nt")
    assert procflags.hidden() == {"creationflags": 0x08000000}
    monkeypatch.setattr(procflags.os, "name", "posix")
    assert procflags.hidden() == {}


def test_every_direct_subprocess_call_in_src_hides_its_window():
    bad = []
    for f in SRC.rglob("*.py"):
        if f.name in VISIBLE_ON_PURPOSE:
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("run", "Popen", "check_output", "call")
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == "subprocess"):
                has = any(k.arg == "creationflags" for k in n.keywords) or any(
                    k.arg is None and isinstance(k.value, ast.Call) and getattr(k.value.func, "id", "") == "hidden" for k in n.keywords)
                if not has:
                    bad.append(f"{f.relative_to(SRC).as_posix()}:{n.lineno}")
    assert not bad, "subprocess-Aufruf ohne verstecktes Fenster: " + ", ".join(bad)


def test_the_callers_that_take_subprocess_as_a_default_also_pass_the_flags(monkeypatch, tmp_path):
    """git (Review), nvidia-smi (gpu), taskkill (Launcher), claude auth (base): echte Aufrufe mit abgefangenem subprocess.run."""
    monkeypatch.setattr(procflags.os, "name", "nt")
    seen = []

    def spy(*a, **kw):
        seen.append(kw.get("creationflags"))
        return subprocess.CompletedProcess(a, 0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", spy)

    from kushim.claude_cli import review
    review.run_git(["status"], tmp_path)
    from kushim import launcher
    import kushim.launcher as lm
    monkeypatch.setattr(lm.os, "name", "nt")
    launcher.kill_tree(1234)
    assert seen and all(f == 0x08000000 for f in seen), seen


def test_gpu_and_claude_auth_defaults_are_called_with_the_flags(monkeypatch):
    calls = []

    def spy(argv, **kw):
        calls.append(kw.get("creationflags"))
        return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")
    monkeypatch.setattr(procflags.os, "name", "nt")
    from kushim import gpu
    from kushim.claude_cli import base
    monkeypatch.setattr(gpu, "_nvidia_smi", lambda: "nvidia-smi")
    gpu.list_gpus(run=lambda argv, **kw: spy(argv, **kw))
    base.auth_status(Path("claude"), run=lambda argv, **kw: spy(argv, **kw))
    assert calls == [0x08000000, 0x08000000]
