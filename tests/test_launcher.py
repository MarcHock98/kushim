from pathlib import Path

import pytest

from kushim.launcher import Launcher, ollama_env


class FakeProc:
    def __init__(self, dead=False):
        self.dead, self.terminated, self.killed = dead, False, False

    def poll(self):
        return 1 if self.dead else None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        pass

    def kill(self):
        self.killed = True


def make(tmp_path, alive_seq, proc=None):
    exe = tmp_path / "tools" / "ollama" / "ollama.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("x")
    calls = []
    seq = iter(alive_seq)
    p = proc or FakeProc()
    launcher = Launcher(tmp_path, popen=lambda *a, **k: (calls.append((a, k)), p)[1],
                        alive=lambda: next(seq, True), sleep=lambda s: None)
    return launcher, calls, p


def test_env_is_hardened(tmp_path):
    env = ollama_env(tmp_path, {"OLLAMA_HOST": "0.0.0.0:11434", "OLLAMA_ORIGINS": "*", "PATH": "p"})
    assert env["OLLAMA_HOST"] == "127.0.0.1:11434"
    assert "OLLAMA_ORIGINS" not in env and env["PATH"] == "p"
    assert Path(env["OLLAMA_MODELS"]) == tmp_path / "models" / "ollama"


def test_already_running_is_not_touched(tmp_path):
    launcher, calls, _ = make(tmp_path, [True])
    assert launcher.start_ollama() == "already"
    assert calls == []
    launcher.stop()


def test_starts_and_stops_own_process(tmp_path):
    launcher, calls, proc = make(tmp_path, [False, False, True])
    assert launcher.start_ollama() == "started"
    assert calls[0][0][0][1] == "serve" and calls[0][1]["env"]["OLLAMA_HOST"] == "127.0.0.1:11434"
    launcher.stop()
    assert proc.terminated
    launcher.stop()   # zweites Stop ist harmlos


def test_died_at_start(tmp_path):
    launcher, _, _ = make(tmp_path, [False, False], FakeProc(dead=True))
    with pytest.raises(RuntimeError):
        launcher.start_ollama()


def test_timeout_stops_process(tmp_path):
    launcher, _, proc = make(tmp_path, [False] * 1000)
    with pytest.raises(TimeoutError):
        launcher.start_ollama(timeout=2)
    assert proc.terminated


def test_missing_exe(tmp_path):
    launcher = Launcher(tmp_path, alive=lambda: False)
    with pytest.raises(FileNotFoundError):
        launcher.start_ollama()
