"""Grafikkarten erkennen und für die Spracherkennung (Whisper) wählen (NVIDIA/CUDA).

Ein lokales Sprachmodell gibt es nicht mehr (Roadmap v2 A6): Whisper ist der einzige Verbraucher. Bei mehreren Karten
nimmt "auto" die mit dem meisten Speicher.

Einstellung in config.toml:
  [gpu]
  whisper = "auto"    # "auto", "cpu" oder die Nummer der Karte (siehe `kushim gpu`)

Nummern in dieser Datei und in `kushim gpu` sind die Nummern von `nvidia-smi` (PCI-Reihenfolge).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable

from .procflags import hidden

MIN_WHISPER_MB = 4096        # Whisper large-v3-turbo (float16) braucht etwa 3 GB plus Reserve


@dataclass(frozen=True)
class Gpu:
    index: int
    name: str
    total_mb: int
    free_mb: int
    uuid: str


@dataclass(frozen=True)
class Plan:
    whisper_device: str                      # "cuda" oder "cpu"
    whisper_index: int = 0                   # Nummer der Karte (nvidia-smi), nur bei "cuda"
    notes: tuple[str, ...] = field(default_factory=tuple)


def _nvidia_smi() -> str | None:
    found = shutil.which("nvidia-smi")
    if found:
        return found
    fallback = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe")
    return fallback if os.path.isfile(fallback) else None


def parse_gpus(csv: str) -> list[Gpu]:
    gpus = []
    for line in csv.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        try:
            gpus.append(Gpu(int(parts[0]), ", ".join(parts[1:-3]), int(float(parts[-3])), int(float(parts[-2])), parts[-1]))
        except ValueError:
            continue
    return sorted(gpus, key=lambda g: g.index)


def list_gpus(run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> list[Gpu]:
    """Liest die Karten über nvidia-smi (lokales Programm). Fehlt es oder scheitert es: keine Karten."""
    exe = _nvidia_smi()
    if not exe:
        return []
    try:
        out = run([exe, "--query-gpu=index,name,memory.total,memory.free,uuid", "--format=csv,noheader,nounits"],
                  capture_output=True, text=True, timeout=10, check=False, **hidden())
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_gpus(out.stdout) if out.returncode == 0 else []


def _by_index(gpus: list[Gpu], text: str, what: str) -> list[Gpu]:
    chosen = []
    for tok in (t.strip() for t in text.split(",") if t.strip()):
        if not tok.isdigit() or not any(g.index == int(tok) for g in gpus):
            raise ValueError(f"{what}: Grafikkarte {tok!r} gibt es nicht (vorhanden: "
                             f"{', '.join(str(g.index) for g in gpus) or 'keine'})")
        chosen.append(next(g for g in gpus if g.index == int(tok)))
    if not chosen:
        raise ValueError(f"{what}: keine Grafikkarte angegeben")
    return chosen


def make_plan(gpus: list[Gpu], whisper: str = "auto") -> Plan:
    """Wählt die Karte für Whisper. Wirft ValueError bei falschen Nummern."""
    whisper = whisper.strip().lower()
    notes: list[str] = []

    # --- Whisper
    if whisper == "cpu":
        w_dev, w_idx = "cpu", 0
        notes.append("Whisper läuft auf dem Prozessor (Einstellung).")
    elif whisper == "auto":
        if not gpus:
            w_dev, w_idx = "cpu", 0
            notes.append("Keine NVIDIA-Karte gefunden: Whisper läuft auf dem Prozessor (langsamer).")
        elif len(gpus) == 1:
            w_dev, w_idx = "cuda", gpus[0].index
        else:
            pick = max(gpus, key=lambda g: (g.total_mb, -g.index))          # die größte Karte
            w_dev, w_idx = "cuda", pick.index
            notes.append(f"Whisper auf Karte {pick.index} ({pick.name}).")
    else:
        chosen = _by_index(gpus, whisper, "whisper")
        if len(chosen) > 1:
            raise ValueError("whisper: nur eine Karte angeben")
        w_dev, w_idx = "cuda", chosen[0].index

    return Plan(w_dev, w_idx, tuple(notes))


def describe(gpus: list[Gpu], plan: Plan) -> str:
    if not gpus:
        lines = ["Keine NVIDIA-Grafikkarte gefunden (nvidia-smi fehlt oder meldet nichts)."]
    else:
        lines = ["Grafikkarten:"]
        for g in gpus:
            use = []
            if plan.whisper_device == "cuda" and g.index == plan.whisper_index:
                use.append("Whisper")
            lines.append(f"  {g.index}: {g.name}, {g.total_mb} MB gesamt, {g.free_mb} MB frei"
                         + (f"  -> {', '.join(use)}" if use else "  -> unbenutzt"))
    lines.append(f"Whisper: {'Karte ' + str(plan.whisper_index) if plan.whisper_device == 'cuda' else 'Prozessor'}")
    lines += [f"Hinweis: {n}" for n in plan.notes]
    return "\n".join(lines)
