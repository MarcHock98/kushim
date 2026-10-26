"""`kushim app`: startet die Oberfläche samt Backend mit einem Klick (Desktop-Verknüpfung "kushim App").

Ablauf: (1) Läuft schon ein Sprachdienst (Lebenszeichen in `run/voice-state.json`), wird er benutzt und nur das Fenster geöffnet.
Sonst startet `appstart` einen eigenen Hintergrundprozess: `kushim talk --ui` (Sprache plus API), bei aktivem Notaus nur `kushim serve`
(damit das Fenster "NOTAUS aktiv" zeigen und aufheben kann). (2) Wartet, bis das Backend `run/api.json` frisch geschrieben hat.
(3) Öffnet das Fenster (`ui/src-tauri/target/release/kushim-ui.exe`) und wartet, bis es geschlossen wird. (4) Beendet den selbst gestarteten
Hintergrundprozess samt Kindern. Nichts Fremdes wird angefasst. Nur lokal, kein Netz.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from .procflags import kill_tree
from .safety import killswitch
from .voice import statefile

UI_EXE = Path("ui") / "src-tauri" / "target" / "release" / "kushim-ui.exe"
API_FILE = Path("run") / "api.json"
LOG = Path("run") / "app.log"
WAIT_API = 120.0                      # Sprachmodell und Whisper laden dauern
NO_WINDOW = 0x08000000                # CREATE_NO_WINDOW (Windows)


class AppError(Exception):
    pass


def backend_args(root: Path, voice: bool = True) -> list[str]:
    """Befehl des Hintergrundprozesses: Sprache + API, oder nur die API (ohne Sprache oder bei aktivem Notaus)."""
    mode = ["talk", "--ui"] if voice and not killswitch.is_triggered(root) else ["serve"]
    return [sys.executable, "-m", "kushim.cli", *mode]


def ui_path(root: Path) -> Path:
    return root / UI_EXE


def wait_for_api(root: Path, since: float, timeout: float = WAIT_API, alive: Callable[[], bool] = lambda: True,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> bool:
    """Wartet, bis `run/api.json` NEU ist (jünger als `since`); ein Rest einer früheren Sitzung zählt nicht."""
    end = clock() + timeout
    path = root / API_FILE
    while clock() < end:
        try:
            if path.stat().st_mtime >= since:
                return True
        except OSError:
            pass
        if not alive():
            return False
        sleep(0.5)
    return False


def run(root: Path, voice: bool = True, popen: Callable[..., Any] = subprocess.Popen,
        say: Callable[[str], None] = print, wait: Callable[..., bool] = wait_for_api) -> int:
    exe = ui_path(root)
    if not exe.is_file():
        say("Die App ist noch nicht gebaut. Einmalig: cd ui && npx tauri build --no-bundle (braucht Node und Rust, siehe README).")
        return 2
    backend: Any = None
    if statefile.read(root)["active"]:
        say("Der Sprachdienst läuft schon, ich öffne nur das Fenster.")
    else:
        (root / LOG).parent.mkdir(exist_ok=True)
        flags = NO_WINDOW if os.name == "nt" else 0

        def start(args: list[str]) -> Any:
            with open(root / LOG, "ab") as log:
                return popen(args, cwd=str(root), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags)

        say("Starte den Dienst (Sprache und Oberfläche), das dauert beim ersten Mal etwas ...")
        try:
            backend = start(backend_args(root, voice))
            ready = wait(root, time.time(), alive=lambda: backend.poll() is None)
            if not ready and voice and backend.poll() is not None:
                # Der Sprachdienst ist früh beendet (z. B. kein Stimmprofil, Mikrofon fehlt): Fenster trotzdem öffnen, nur mit der API.
                say(f"Der Sprachdienst startet nicht (siehe {LOG}). Ich öffne das Fenster ohne Sprache.")
                backend = start(backend_args(root, False))
                ready = wait(root, time.time(), alive=lambda: backend.poll() is None)
        except OSError as e:
            say(f"Der Dienst konnte nicht starten ({type(e).__name__}).")
            _stop(backend, root)
            return 1
        if not ready:
            say(f"Der Dienst ist nicht bereit geworden. Siehe {LOG}.")
            _stop(backend, root)
            return 1
    try:
        ui = popen([str(exe)], cwd=str(root))
        ui.wait()                                              # das Fenster bestimmt, wie lange alles läuft
    finally:
        _stop(backend, root)
    return 0


def _stop(proc: Any, root: Path | None = None) -> None:
    """Beendet nur den selbst gestarteten Dienst (samt Kindern) und räumt dessen `run/api.json` weg
    (ein hart beendeter Dienst kann das nicht mehr selbst)."""
    if proc is None:
        return
    if root is not None:
        try:
            (root / API_FILE).unlink(missing_ok=True)
        except OSError:
            pass
    pid = getattr(proc, "pid", None)
    if isinstance(pid, int):
        kill_tree(pid)
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:                                           # noqa: BLE001
        try:
            proc.kill()
        except Exception:                                       # noqa: BLE001
            pass
