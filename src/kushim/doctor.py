"""`kushim doctor`: prueft, ob alles fuer den Betrieb vorhanden ist (nur Lesen, kein Netzwerk)."""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .llm.ollama import DEFAULT_MODEL, manifest_rel


@dataclass
class Check:
    name: str
    ok: bool
    hint: str = ""


MODULES = [("faster_whisper", "Spracherkennung"), ("piper", "Sprachausgabe"),
           ("sherpa_onnx", "Sprecherverifikation"), ("sounddevice", "Audio"),
           ("openwakeword", "Wake Word"), ("sentencepiece", "freie Wake Words"), ("sqlcipher3", "Vault"), ("keyring", "Schluesselbund")]

FILES = [
    ("Whisper-Modell", "models/whisper-large-v3-turbo/model.bin"),
    ("Piper-Stimme", "models/piper/de_DE-thorsten-high.onnx"),
    ("Sprecher-Modell", "models/speaker/wespeaker_en_voxceleb_CAM++_LM.onnx"),
    ("Vergleichsstimmen für das Einschreiben", "models/piper-cohort/de_DE-mls-medium.onnx"),
    ("Wake-Word-Modell (freie Wörter)", "models/kws/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01/bpe.model"),
    ("Ollama", "tools/ollama/ollama.exe"),
]


def run_checks(root: Path, vault_state: Callable[[], str] | None = None,
               llm_model: str = DEFAULT_MODEL) -> list[Check]:
    """`vault_state()` liefert "ok", "kein-vault" oder "kein-profil" (wird vom CLI bereitgestellt)."""
    checks: list[Check] = []
    for mod, what in MODULES:
        checks.append(Check(f"Python-Paket {mod} ({what})", importlib.util.find_spec(mod) is not None,
                            "install.ps1 erneut ausfuehren"))
    for name, rel in FILES:
        checks.append(Check(name, (root / rel).exists(), "install.ps1 erneut ausfuehren"))
    checks.append(Check(f"LLM {llm_model}", (root / manifest_rel(llm_model)).exists(),
                        f"install.ps1 -Llm {llm_model}"))
    nv = importlib.util.find_spec("nvidia")
    gpu_libs = bool(nv and any((Path(p) / "cublas" / "bin").is_dir() for p in (nv.submodule_search_locations or [])))
    checks.append(Check("GPU-Bibliotheken (cuBLAS/cuDNN)", gpu_libs, "install.ps1 erneut ausfuehren"))
    checks.append(Check("Notaus nicht aktiv", not (root / "run" / "KILL").exists(), "kushim resume"))
    if vault_state is not None:
        state = vault_state()
        checks.append(Check("Vault vorhanden", state != "kein-vault", "kushim memory init"))
        checks.append(Check("Stimmprofil eingeschrieben", state == "ok", "kushim voice enroll"))
    return checks
