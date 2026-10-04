"""Einmaliger Modell-Download für den Stimmklon (Chatterbox Multilingual, MIT, Resemble AI, Hugging Face `ResembleAI/chatterbox`).

Läuft NUR mit dem venv unter tools/chatterbox und NUR auf ausdrücklichen Aufruf von Hand:
    tools\\chatterbox\\venv\\Scripts\\python scripts\\clone_fetch.py
Das ist der einzige Schritt, der ins Netz geht (Hugging Face, nur Download, es wird nichts hochgeladen, keine Aufnahmen, keine Telemetrie).
Danach läuft alles offline (scripts/clone_worker.py sperrt das Netz im Prozess selbst). Modelldateien landen in tools/chatterbox/hf (git-ignoriert).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["HF_HOME"] = str(ROOT / "tools" / "chatterbox" / "hf")
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["DO_NOT_TRACK"] = "1"


def main() -> int:
    from huggingface_hub import snapshot_download
    # genau die Dateien, die chatterbox.mtl_tts selbst lädt (Version 0.1.7), nichts darüber hinaus
    files = ["ve.pt", "t3_mtl23ls_v2.safetensors", "s3gen.pt", "grapheme_mtl_merged_expanded_v1.json", "conds.pt", "Cangjie5_TC.json"]
    path = snapshot_download(repo_id="ResembleAI/chatterbox", repo_type="model", revision="main", allow_patterns=files)
    print("Geladen nach:", path)
    for p in sorted(Path(path).rglob("*")):
        if p.is_file():
            print(f"  {p.relative_to(path)}  {p.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
