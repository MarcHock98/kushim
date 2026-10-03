"""Baut aus der zentralen Konfiguration (wakeconfig) den passenden Wake-Word-Detektor."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .trigger import CombinedDetector, KwsDetector, WakeWordDetector, resolve_wake_words
from .wakeconfig import WakeConfig

KWS_DIR = Path("models") / "kws" / "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"


def build_detector(cfg: WakeConfig, root: Path) -> Any:
    """Ein Detektor je Engine; mehrere Engines laufen parallel auf denselben Frames."""
    cd = cfg.settings.cooldown_seconds
    oww = [w for w in cfg.enabled() if w.engine == "openwakeword"]
    kws = [w for w in cfg.enabled() if w.engine == "kws"]
    detectors: list[Any] = []
    if oww:
        models = resolve_wake_words([w.name for w in oww], root)
        threshold = min(w.effective_threshold for w in oww)        # ein gemeinsames Modell-Set: empfindlichste Schwelle
        detectors.append(WakeWordDetector.from_openwakeword(models, threshold=threshold, cooldown=cd))
    if kws:
        model_dir = root / KWS_DIR
        if not (model_dir / "bpe.model").is_file():
            raise FileNotFoundError("KWS-Modell fehlt: install.ps1 erneut ausführen (oder scripts/fetch_models.py)")
        detectors.append(KwsDetector.from_model(
            model_dir, [(w.name, w.effective_threshold, w.boost) for w in kws],
            root / "run" / "kws_keywords.txt", cooldown=cd))
    return detectors[0] if len(detectors) == 1 else CombinedDetector(detectors)
