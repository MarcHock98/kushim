"""Startet die lokalen Dienste (Ollama nur auf 127.0.0.1) und beendet sie wieder sauber.

Startet nichts doppelt: läuft Ollama schon, wird es nicht übernommen und beim Beenden nicht
angefasst. Die Umgebung wird hart gesetzt (Loopback, Modelle im Projekt), fremde OLLAMA_*-Werte
des Benutzers werden nicht übernommen.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from .net.loopback import request_json

OLLAMA_URL = "http://127.0.0.1:11434"


def ollama_env(root: Path, base: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in (base if base is not None else os.environ).items()
           if not k.startswith("OLLAMA_")}
    env["OLLAMA_HOST"] = "127.0.0.1:11434"
    env["OLLAMA_MODELS"] = str(root / "models" / "ollama")
    return env


def ollama_alive(url: str = OLLAMA_URL) -> bool:
    try:
        request_json("GET", f"{url}/api/tags", timeout=2.0)
        return True
    except Exception:
        return False


def kill_tree(pid: int) -> None:
    """Beendet einen Prozess samt Kindern. Ollama startet llama-server.exe als Kind; `terminate()` allein
    lässt es unter Windows laufen (hält das Modell im VRAM). Nur für ein selbst gestartetes PID aufrufen."""
    if os.name != "nt":
        return
    try:
        subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True, timeout=15, check=False)
    except Exception:
        pass


class Launcher:
    def __init__(self, root: Path, popen: Callable[..., Any] = subprocess.Popen,
                 alive: Callable[[], bool] = ollama_alive,
                 sleep: Callable[[float], None] = time.sleep,
                 tree_kill: Callable[[int], None] = kill_tree):
        self.root, self._popen, self._alive, self._sleep = root, popen, alive, sleep
        self._tree_kill = tree_kill
        self._proc: Any = None

    @property
    def exe(self) -> Path:
        return self.root / "tools" / "ollama" / "ollama.exe"

    def start_ollama(self, timeout: float = 60.0) -> str:
        """Gibt "already" (lief schon), "started" oder wirft bei Fehler/Timeout zurück."""
        if self._alive():
            return "already"
        if not self.exe.exists():
            raise FileNotFoundError(f"Ollama fehlt: {self.exe}")
        self._proc = self._popen([str(self.exe), "serve"], env=ollama_env(self.root),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        waited = 0.0
        while waited < timeout:
            if self._alive():
                return "started"
            if self._proc.poll() is not None:
                self._proc = None
                raise RuntimeError("Ollama ist beim Start beendet worden")
            self._sleep(0.5)
            waited += 0.5
        self.stop()
        raise TimeoutError("Ollama wurde nicht rechtzeitig bereit")

    def stop(self) -> None:
        """Beendet nur, was dieser Launcher selbst gestartet hat."""
        p, self._proc = self._proc, None
        if p is None:
            return
        pid = getattr(p, "pid", None)
        if isinstance(pid, int):
            self._tree_kill(pid)                  # zuerst, solange der Elternprozess die Kinder noch verknüpft
        p.terminate()
        try:
            p.wait(timeout=10)
        except Exception:
            p.kill()
