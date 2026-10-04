"""Stimmklon-Worker: läuft im eigenen venv (tools/chatterbox) als Kindprozess von kushim und spricht Sätze mit der eigenen Stimme.

Sicherheit:
- KEIN NETZ: Beim Start wird im Prozess jede Verbindung außer Loopback gesperrt (socket.connect/create_connection/getaddrinfo auf Nicht-Loopback
  wirft), Hugging Face und Transformers laufen im Offline-Modus. Modelle liegen unter tools/chatterbox/hf.
- Die Referenzaufnahme (voice-data/clone/*.wav) wird nur gelesen und verlässt den PC nie.
- Protokoll über stdin/stdout, eine JSON-Zeile pro Auftrag: {"text": "...", "out": "<wav>"} -> {"ok": true} oder {"ok": false, "error": "..."}.
  Der Ausgabepfad muss unter dem erlaubten Ordner liegen (--out-dir); sonst wird abgelehnt.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["HF_HOME"] = str(ROOT / "tools" / "chatterbox" / "hf")
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["DO_NOT_TRACK"] = "1"
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"

_LOCAL = {"127.0.0.1", "::1", "localhost"}


def block_network() -> None:
    """Sperrt alles außer Loopback im eigenen Prozess (zweite Sperre neben dem Offline-Modus)."""
    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex

    def _host(address):
        return address[0] if isinstance(address, tuple) and address else address

    def connect(self, address):
        if _host(address) not in _LOCAL:
            raise OSError("Netzwerk gesperrt (Stimmklon läuft offline)")
        return real_connect(self, address)

    def connect_ex(self, address):
        if _host(address) not in _LOCAL:
            raise OSError("Netzwerk gesperrt (Stimmklon läuft offline)")
        return real_connect_ex(self, address)

    def getaddrinfo(host, *a, **k):
        if host not in _LOCAL and host is not None:
            raise OSError("Namensauflösung gesperrt (Stimmklon läuft offline)")
        return real_getaddrinfo(host, *a, **k)

    real_getaddrinfo = socket.getaddrinfo
    socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = connect, connect_ex, getaddrinfo


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True, help="Referenzaufnahme (WAV, eigene Stimme)")
    ap.add_argument("--out-dir", required=True, help="Nur hier dürfen Ausgaben liegen")
    ap.add_argument("--language", default="de")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--selftest-network", action="store_true", help="Prüft nur, dass das Netz gesperrt ist, und endet")
    args = ap.parse_args()
    proto = sys.stdout
    sys.stdout = sys.stderr                         # Bibliotheken schreiben gern nach stdout: das gehört nicht ins Protokoll
    block_network()
    if args.selftest_network:
        try:
            socket.create_connection(("example.com", 443), timeout=3)
        except OSError as e:
            print("GESPERRT:", e, file=proto)
            return 0
        print("OFFEN", file=proto)                      # darf nie passieren
        return 1
    out_dir = Path(args.out_dir).resolve()
    ref = Path(args.ref).resolve()
    if not ref.is_file():
        print(json.dumps({"ok": False, "error": "Referenz fehlt"}), file=proto, flush=True)
        return 2
    # spacy_pkuseg (nur für Chinesisch) lädt bei jeder Initialisierung ein Modell von GitHub. Wir brauchen es nicht (Deutsch): Import
    # verhindern; chatterbox fängt den ImportError ab und überspringt nur die chinesische Segmentierung. Nichts wird nachgeladen.
    sys.modules["spacy_pkuseg"] = None
    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    model = ChatterboxMultilingualTTS.from_pretrained(device=args.device)
    print(json.dumps({"ok": True, "ready": True, "sr": int(model.sr)}), file=proto, flush=True)
    for line in sys.stdin:
        try:
            job = json.loads(line)
            text, out = str(job["text"]), Path(job["out"]).resolve()
            if out_dir not in out.parents or out.suffix.lower() != ".wav":
                raise ValueError("Ausgabepfad nicht erlaubt")
            if not text.strip() or len(text) > 600:
                raise ValueError("Text leer oder zu lang")
            with torch.inference_mode():
                wav = model.generate(text, language_id=args.language, audio_prompt_path=str(ref))
            pcm = (wav.detach().cpu().float().clamp(-1, 1).reshape(-1) * 32767).short().numpy().tobytes()      # 16-Bit-PCM, von kushim lesbar
            with wave.open(str(out), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(int(model.sr))
                w.writeframes(pcm)
            print(json.dumps({"ok": True}), file=proto, flush=True)
        except Exception as e:                                             # noqa: BLE001
            print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}), file=proto, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
