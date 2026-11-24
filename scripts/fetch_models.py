"""Laedt die lokalen Modelle (einmalig) und prueft sie gegen feste Groessen und SHA-256.

Aufruf:  .venv\\Scripts\\python scripts/fetch_models.py [--check]

Das ist der EINZIGE Ort ausser pip in install.ps1, der beim Einrichten ins Netz geht,
und zwar nur zu: huggingface.co (Whisper, Stimme Kokoro "Martin"), github.com (Wake-Word-Modelle
ueber openWakeword). Nach der Installation arbeitet kushim offline. Mit --check wird nur geprueft,
nichts geladen. Vorhandene, passende Dateien werden uebersprungen.
Lokale Uebernahme: Liegt eine Datei mit passender Groesse und SHA-256 schon unter `local` (z. B. aus der TTS-Evaluation
in tools/tts-eval2), wird sie von dort kopiert statt geladen.
Dieses Skript liegt bewusst ausserhalb von src/ (der Egress-Test gilt fuer das Programm).
"""
from __future__ import annotations

import hashlib
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Item:
    dest: str                # relativ zu ROOT
    size: int
    sha256: str | None = None
    hf_repo: str | None = None
    hf_revision: str | None = None
    hf_path: str | None = None
    url: str | None = None
    local: tuple[str, ...] = ()     # relativ zu ROOT: hier zuerst nachsehen (nur bei gleicher Groesse und gleichem SHA-256)


WHISPER = ("mobiuslabsgmbh/faster-whisper-large-v3-turbo", "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf")
# Kokoro-82M deutsch, Stimme "Martin" (ONNX), Apache-2.0. Die alte URL huggingFresse/... leitet hierher weiter (HF-Umbenennung).
KOKORO = ("Godelaune/Kokoro-82M-ONNX-German-Martin", "a1cba7fbf0e72fbae38f0a3a48ce0dc8e6077804")
KOKORO_LOCAL = "tools/tts-eval2/dl/kokoro-martin-hf"
ITEMS = [
    Item("models/whisper-large-v3-turbo/model.bin", 1617884929,
         "e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da", *WHISPER, "model.bin"),
    Item("models/whisper-large-v3-turbo/config.json", 2263, None, *WHISPER, "config.json"),
    Item("models/whisper-large-v3-turbo/preprocessor_config.json", 340, None, *WHISPER,
         "preprocessor_config.json"),
    Item("models/whisper-large-v3-turbo/tokenizer.json", 2710337, None, *WHISPER, "tokenizer.json"),
    Item("models/whisper-large-v3-turbo/vocabulary.json", 1068114, None, *WHISPER, "vocabulary.json"),
    Item("models/kokoro/kokoro-martin.onnx", 325512630,
         "c302f1d8bc7adf40a842cb550e18c39a5026bdb1afdd29dbb700b501cb49276b", *KOKORO, "kokoro-martin.onnx",
         local=(f"{KOKORO_LOCAL}/kokoro-martin.onnx",)),
    Item("models/kokoro/voices-martin.npz", 522506,
         "5b9c8553398d7abf67498ce500c186cefaa7b68fed3e3d415da5380670105acd", *KOKORO, "voices-martin.npz",
         local=(f"{KOKORO_LOCAL}/voices-martin.npz",)),
    Item("models/kokoro/README.md", 12162,              # Model Card mit der Lizenzangabe (Apache-2.0)
         "4beed07717aaaef3625984f6fc952c207ac3fd7b3d57b69dffdccc80412a1f6d", *KOKORO, "README.md",
         local=(f"{KOKORO_LOCAL}/README.md",)),
]

KWS_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/"
           "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01.tar.bz2")
KWS_SIZE = 17626723
KWS_SHA256 = "f170013b4716e41b62b9bfd809687c207cef798ef9bc6534d524e17af9b6561a"   # laut checksum.txt des Releases
KWS_MARKER = "models/kws/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01/bpe.model"

WAKEWORD_FILES = ["alexa_v0.1.onnx", "hey_mycroft_v0.1.onnx", "hey_jarvis_v0.1.onnx",
                  "hey_rhasspy_v0.1.onnx", "timer_v0.1.onnx", "weather_v0.1.onnx",
                  "embedding_model.onnx", "melspectrogram.onnx"]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_ok(item: Item) -> bool:
    p = ROOT / item.dest
    if not p.is_file() or p.stat().st_size != item.size:
        return False
    return item.sha256 is None or sha256_of(p) == item.sha256


def adopt_local(item: Item) -> bool:
    """Kopiert eine schon vorhandene, gepruefte Datei (gleiche Groesse und SHA-256) statt sie zu laden. Das Original bleibt."""
    if not item.sha256:
        return False
    for rel in item.local:
        src = ROOT / rel
        if not src.is_file() or src.stat().st_size != item.size or sha256_of(src) != item.sha256:
            continue
        dest = ROOT / item.dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
            tmp_file = Path(tmp) / "copy"
            shutil.copyfile(src, tmp_file)
            if tmp_file.stat().st_size != item.size or sha256_of(tmp_file) != item.sha256:
                raise RuntimeError(f"Kopie stimmt nicht: {item.dest} (verworfen)")
            shutil.move(tmp_file, dest)
        return True
    return False


def fetch(item: Item) -> None:
    if adopt_local(item):
        return
    dest = ROOT / item.dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        tmp_file = Path(tmp) / "download"
        if item.hf_repo:
            from huggingface_hub import hf_hub_download
            got = hf_hub_download(item.hf_repo, item.hf_path, revision=item.hf_revision, local_dir=tmp)
            shutil.move(got, tmp_file)
        else:
            with urllib.request.urlopen(item.url, timeout=60) as r, tmp_file.open("wb") as out:
                shutil.copyfileobj(r, out)
        if tmp_file.stat().st_size != item.size or (item.sha256 and sha256_of(tmp_file) != item.sha256):
            raise RuntimeError(f"Pruefsumme/Groesse stimmt nicht: {item.dest} (Datei verworfen)")
        shutil.move(tmp_file, dest)


def kws_ok() -> bool:
    return (ROOT / KWS_MARKER).is_file()


def fetch_kws() -> None:
    dest = ROOT / "models" / "kws"
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest) as tmp:
        archive = Path(tmp) / "kws.tar.bz2"
        with urllib.request.urlopen(KWS_URL, timeout=60) as r, archive.open("wb") as out:
            shutil.copyfileobj(r, out)
        if archive.stat().st_size != KWS_SIZE or sha256_of(archive) != KWS_SHA256:
            raise RuntimeError("KWS-Modell: Pruefsumme/Groesse stimmt nicht (Datei verworfen)")
        with tarfile.open(archive, "r:bz2") as tf:
            tf.extractall(dest, filter="data")          # "data": keine fremden Pfade, keine Links nach aussen


def wakeword_dir() -> Path:
    import openwakeword
    return Path(openwakeword.__file__).parent / "resources" / "models"


def wakewords_ok() -> bool:
    try:
        d = wakeword_dir()
    except ImportError:
        return False
    return all((d / f).is_file() for f in WAKEWORD_FILES)


def main(argv: list[str]) -> int:
    check = "--check" in argv
    missing = [i for i in ITEMS if not is_ok(i)]
    for i in ITEMS:
        print(("ok      " if i not in missing else "FEHLT   ") + i.dest)
    ww = wakewords_ok()
    print(("ok      " if ww else "FEHLT   ") + "Wake-Word-Modelle (openWakeWord)")
    kws = kws_ok()
    print(("ok      " if kws else "FEHLT   ") + "Wake-Word-Modell fuer freie Woerter (KWS)")
    if check:
        return 0 if not missing and ww and kws else 1
    for i in missing:
        print(f"lade {i.dest} ...")
        fetch(i)
        print("  geprueft und abgelegt")
    if not kws:
        print("lade KWS-Modell ...")
        fetch_kws()
        print("  geprueft und entpackt")
    if not ww:
        import openwakeword.utils as u
        print("lade Wake-Word-Modelle ...")
        u.download_models()
        if not wakewords_ok():
            print("Wake-Word-Modelle unvollstaendig")
            return 1
    print("Alle Modelle vorhanden und geprueft.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
