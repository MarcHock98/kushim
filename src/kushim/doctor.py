"""`kushim doctor`: prueft, ob alles fuer den Betrieb vorhanden ist (nur Lesen, kein Netzwerk)."""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass
class Check:
    name: str
    ok: bool
    hint: str = ""
    id: str = ""           # feste kurze Kennung für die Oberfläche (`setup.checks`), z. B. "model_whisper"


MODULES = [("faster_whisper", "Spracherkennung"),
           ("sherpa_onnx", "Wake Word (freie Wörter)"), ("sounddevice", "Audio"),
           ("openwakeword", "Wake Word"), ("sentencepiece", "freie Wake Words"), ("sqlcipher3", "Vault"), ("keyring", "Schluesselbund")]

FILES = [
    ("Whisper-Modell", "models/whisper-large-v3-turbo/model.bin"),
    ("Stimme Kokoro Martin", "models/kokoro/kokoro-martin.onnx"),
    ("Wake-Word-Modell (freie Wörter)", "models/kws/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01/bpe.model"),
]
FILE_IDS = ("model_whisper", "model_tts", "model_kws")
# Sprachausgabe im eigenen venv (Kindprozess): Interpreter und die drei Pakete, die der Worker braucht. Nur nachsehen, nichts starten.
TTS_VENV = Path("tools") / "kokoro" / "venv"
TTS_PACKAGES = ("onnxruntime", "kokoro_onnx", "espeakng_loader")


def tts_venv_ok(root: Path) -> bool:
    venv = root / TTS_VENV
    site = venv / "Lib" / "site-packages"
    return (venv / "Scripts" / "python.exe").is_file() and all((site / p / "__init__.py").is_file() for p in TTS_PACKAGES)


def run_checks(root: Path, vault_state: Callable[[], str] | None = None) -> list[Check]:
    """`vault_state()` liefert "ok" oder "kein-vault" (wird vom CLI bereitgestellt)."""
    checks: list[Check] = []
    for mod, what in MODULES:
        checks.append(Check(f"Python-Paket {mod} ({what})", importlib.util.find_spec(mod) is not None,
                            "install.ps1 erneut ausfuehren", f"pkg_{mod}"))
    for (name, rel), cid in zip(FILES, FILE_IDS):
        checks.append(Check(name, (root / rel).exists(), "install.ps1 erneut ausfuehren", cid))
    checks.append(Check("Sprachausgabe-Umgebung (tools/kokoro/venv)", tts_venv_ok(root), "install.ps1 erneut ausfuehren", "tts_venv"))
    nv = importlib.util.find_spec("nvidia")
    gpu_libs = bool(nv and any((Path(p) / "cublas" / "bin").is_dir() for p in (nv.submodule_search_locations or [])))
    checks.append(Check("GPU-Bibliotheken (cuBLAS/cuDNN)", gpu_libs, "install.ps1 erneut ausfuehren", "gpu_libs"))
    checks.append(Check("Notaus nicht aktiv", not (root / "run" / "KILL").exists(), "kushim resume", "kill_off"))
    if vault_state is not None:
        state = vault_state()
        checks.append(Check("Vault vorhanden", state != "kein-vault", "kushim memory init (im eigenen Terminal)", "vault"))
    return checks


def claude_checks(find: Callable[[], Any], version: Callable[[Any], tuple[int, int, int] | None],
                  logged_in: Callable[[Any], bool], minimum: tuple[int, int, int]) -> list[Check]:
    """Claude Code für `kushim start`: vorhanden, neu genug (Channels mit Freigabe-Weiterleitung), angemeldet. Nur lokale Aufrufe."""
    exe = find()
    if exe is None:
        return [Check("Claude Code installiert", False, "Claude Code installieren und `claude auth login`", "claude_installed")]
    ver = version(exe)
    need = ".".join(map(str, minimum))
    checks = [Check("Claude Code installiert", True, "", "claude_installed"),
              Check(f"Claude Code mindestens {need}" + (f" (ist {'.'.join(map(str, ver))})" if ver else ""),
                    ver is not None and ver >= minimum, "Claude Code aktualisieren: claude update", "claude_version")]
    checks.append(Check("In Claude Code angemeldet", logged_in(exe), "claude auth login", "claude_login"))
    return checks
