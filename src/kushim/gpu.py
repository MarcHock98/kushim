"""Grafikkarten erkennen und sinnvoll verteilen (NVIDIA/CUDA).

Zwei Verbraucher teilen sich den Grafikspeicher: die Spracherkennung (Whisper) und das Sprachmodell (Ollama).
Ist nur eine Karte da, bleibt alles wie bisher. Bei mehreren Karten bekommt Whisper EINE Karte für sich, und das
Sprachmodell nutzt alle übrigen. So konkurrieren beide nicht um denselben Speicher, und größere Modelle passen eher.

Einstellung in config.toml:
  [gpu]
  whisper = "auto"    # "auto", "cpu" oder die Nummer der Karte (siehe `kushim gpu`)
  llm     = "auto"    # "auto", "all" (alle Karten, Ollama entscheidet) oder Nummern wie "0,1"

Karten werden über die UUID an Ollama übergeben (CUDA_VISIBLE_DEVICES), das ist eindeutig. Nummern in dieser Datei
und in `kushim gpu` sind die Nummern von `nvidia-smi` (PCI-Reihenfolge).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable

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
    llm_visible: str | None = None           # CUDA_VISIBLE_DEVICES für Ollama (UUIDs); None = Ollama entscheidet
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
                  capture_output=True, text=True, timeout=10, check=False)
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


def make_plan(gpus: list[Gpu], whisper: str = "auto", llm: str = "auto") -> Plan:
    """Verteilt Whisper und das Sprachmodell auf die vorhandenen Karten. Wirft ValueError bei falschen Nummern."""
    whisper, llm = whisper.strip().lower(), llm.strip().lower()
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
            # kleinste Karte, die Whisper noch trägt; die größeren bleiben dem Sprachmodell
            fits = [g for g in gpus if g.total_mb >= MIN_WHISPER_MB]
            pick = min(fits, key=lambda g: (g.total_mb, g.index)) if fits else max(gpus, key=lambda g: g.total_mb)
            w_dev, w_idx = "cuda", pick.index
            notes.append(f"Whisper auf Karte {pick.index} ({pick.name}), das Sprachmodell auf den übrigen.")
    else:
        chosen = _by_index(gpus, whisper, "whisper")
        if len(chosen) > 1:
            raise ValueError("whisper: nur eine Karte angeben")
        w_dev, w_idx = "cuda", chosen[0].index

    # --- Sprachmodell
    llm_visible: str | None = None
    if llm == "auto":
        if len(gpus) >= 2 and w_dev == "cuda":          # alle Karten außer der von Whisper
            llm_visible = ",".join(g.uuid for g in gpus if g.index != w_idx)
    elif llm == "all":
        llm_visible = None
    else:
        chosen = _by_index(gpus, llm, "llm")
        llm_visible = ",".join(g.uuid for g in chosen)
        if w_dev == "cuda" and any(g.index == w_idx for g in chosen):
            notes.append("Whisper und das Sprachmodell teilen sich eine Karte (Einstellung); der Speicher kann knapp werden.")
    return Plan(w_dev, w_idx, llm_visible, tuple(notes))


def describe(gpus: list[Gpu], plan: Plan) -> str:
    if not gpus:
        lines = ["Keine NVIDIA-Grafikkarte gefunden (nvidia-smi fehlt oder meldet nichts)."]
    else:
        lines = ["Grafikkarten:"]
        for g in gpus:
            use = []
            if plan.whisper_device == "cuda" and g.index == plan.whisper_index:
                use.append("Whisper")
            if plan.llm_visible is None or g.uuid in plan.llm_visible.split(","):
                use.append("Sprachmodell")
            lines.append(f"  {g.index}: {g.name}, {g.total_mb} MB gesamt, {g.free_mb} MB frei"
                         + (f"  -> {', '.join(use)}" if use else "  -> unbenutzt"))
    lines.append(f"Whisper: {'Karte ' + str(plan.whisper_index) if plan.whisper_device == 'cuda' else 'Prozessor'}")
    lines.append("Sprachmodell: " + ("Ollama entscheidet (alle sichtbaren Karten)" if plan.llm_visible is None
                                      else "nur die oben markierten Karten"))
    lines += [f"Hinweis: {n}" for n in plan.notes]
    return "\n".join(lines)
