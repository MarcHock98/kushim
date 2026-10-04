"""Sprachmodell verwalten: auflisten, ausprobieren, umschalten mit Rückweg (CLI und UI nutzen dieselben Funktionen).

Ein Wechsel verändert erst etwas, wenn die Probe gelingt; scheitert sie, bleibt das alte Modell. Das vorherige Modell
steht in `run/llm-state.json` für "Zurück". Alles läuft über Loopback (Ollama nur 127.0.0.1). Modelle werden hier nur
gelistet und umgeschaltet; Laden und Entfernen kommen mit eigener Freigabe (siehe docs/ui-llm-plan.md).
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Iterable

from ..config import Config
from ..net.loopback import request_json
from .ollama import DEFAULT_URL, OllamaClient, manifest_rel, validate_model

STATE = Path("run") / "llm-state.json"
PROBE_QUESTION = "Antworte mit genau einem Wort: ok"
MANIFESTS = Path("models") / "ollama" / "manifests"


@dataclass(frozen=True)
class ModelInfo:
    name: str
    size_mb: int = 0          # 0 = unbekannt (Offline-Liste)


@dataclass(frozen=True)
class Probe:
    ok: bool
    first_token_s: float = 0.0
    total_s: float = 0.0
    text: str = ""
    error: str = ""            # kurzer Grund, nie Pfade oder Stacktraces


@dataclass(frozen=True)
class Switch:
    switched: bool
    model: str                 # aktives Modell nach dem Aufruf
    previous: str = ""
    reason: str = ""           # "", "already_active", "not_installed", "probe_failed", "not_saved", "nothing_to_roll_back"
    probe: Probe | None = None

    def as_dict(self) -> dict:
        return {"switched": self.switched, "model": self.model, "previous": self.previous, "reason": self.reason,
                "probe": asdict(self.probe) if self.probe else None}


# --- Liste ---------------------------------------------------------------------------------------

def scan_manifests(root: Path) -> list[str]:
    """Installierte Modelle aus den Manifest-Dateien (offline, ohne laufendes Ollama)."""
    base = root / MANIFESTS
    names: list[str] = []
    if not base.is_dir():
        return names
    for f in sorted(base.rglob("*")):
        if not f.is_file():
            continue
        parts = f.relative_to(base).parts
        if len(parts) < 3:
            continue
        host, path, tag = parts[0], parts[1:-1], parts[-1]
        if host == "registry.ollama.ai":
            name = path[1] if len(path) == 2 and path[0] == "library" else "/".join(path)
        else:
            name = host + "/" + "/".join(path)
        try:
            names.append(validate_model(f"{name}:{tag}"))
        except ValueError:
            continue
    return names


def installed(root: Path, base_url: str = DEFAULT_URL) -> list[ModelInfo]:
    """Über Ollama (mit Größen), sonst offline über die Manifeste."""
    try:
        data = request_json("GET", f"{base_url}/api/tags", timeout=3.0) or {}
        found = [ModelInfo(str(m["name"]), int(m.get("size", 0)) // (1024 * 1024)) for m in data.get("models", []) if "name" in m]
        if found:
            return found
    except Exception:                                  # Ollama läuft nicht: Offline-Liste
        pass
    return [ModelInfo(n) for n in scan_manifests(root)]


def is_installed(root: Path, name: str) -> bool:
    return (root / manifest_rel(name)).is_file()


# --- Probe ---------------------------------------------------------------------------------------

def probe(model: str, chat_stream: Callable[[list[dict[str, str]]], Iterable[str]] | None = None,
          clock: Callable[[], float] = time.monotonic, limit_s: float = 60.0) -> Probe:
    """Eine feste, kurze Frage stellen und die Zeiten messen. Ohne Text oder bei Fehler: nicht ok."""
    stream = chat_stream or OllamaClient(model, timeout=limit_s).chat_stream
    t0 = clock()
    first, text = 0.0, ""
    try:
        for piece in stream([{"role": "user", "content": PROBE_QUESTION}]):
            if not first:
                first = clock() - t0
            text += piece
            if clock() - t0 > limit_s:
                return Probe(False, first, clock() - t0, text[:80], "timeout")
    except Exception as e:                             # noqa: BLE001 (nur ein kurzer Grund nach außen)
        return Probe(False, first, clock() - t0, text[:80], type(e).__name__)
    total = clock() - t0
    text = text.strip()
    if not text:
        return Probe(False, first, total, "", "empty_answer")
    return Probe(True, round(first, 2), round(total, 2), text[:80])


# --- Zustand "vorheriges Modell" -----------------------------------------------------------------

def load_previous(root: Path) -> str:
    try:
        data = json.loads((root / STATE).read_text(encoding="utf-8"))
        prev = data.get("previous", "")
        return validate_model(prev) if isinstance(prev, str) else ""     # nur Text, nie eine Zahl o. ä.
    except (OSError, ValueError, AttributeError):
        return ""


def save_previous(root: Path, name: str) -> None:
    p = root / STATE
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"previous": validate_model(name)}), encoding="utf-8")
    os.replace(tmp, p)                                 # atomar


# --- Umschalten ----------------------------------------------------------------------------------

def activate(cfg: Config, root: Path, name: str,
             probe_fn: Callable[[str], Probe] = probe, run_probe: bool = True) -> Switch:
    """Modell wählen: Name prüfen, Installation prüfen, Probe, dann erst speichern. Wirft ValueError bei ungültigem Namen."""
    name = validate_model(name)
    old = cfg.llm_model
    if name == old:
        return Switch(False, old, load_previous(root), "already_active")
    if not is_installed(root, name):
        return Switch(False, old, load_previous(root), "not_installed")
    result = probe_fn(name) if run_probe else None
    if result is not None and not result.ok:
        return Switch(False, old, load_previous(root), "probe_failed", result)
    try:
        save_previous(root, old)
        cfg.set_llm_model(name)
    except OSError:
        return Switch(False, old, load_previous(root), "not_saved", result)
    return Switch(True, name, old, "", result)


def rollback(cfg: Config, root: Path, probe_fn: Callable[[str], Probe] = probe, run_probe: bool = True) -> Switch:
    """Zurück zum vorherigen Modell (wiederholt dieselben Schritte inklusive Probe)."""
    prev = load_previous(root)
    if not prev:
        return Switch(False, cfg.llm_model, "", "nothing_to_roll_back")
    return activate(cfg, root, prev, probe_fn, run_probe)
