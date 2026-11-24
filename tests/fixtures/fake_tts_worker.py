"""Fake-Worker für die Tests von voice/ttsworker.py: echte Rahmen- und Auftragslogik aus scripts/kokoro_worker.py, aber eine
Fake-Engine statt Kokoro (kein Modell, keine GPU). Verhalten über --mode:

  ok              synthetisiert einen kurzen Sinuston
  slow            wie ok, aber jede Synthese dauert --delay Sekunden
  crash           beendet sich bei jeder Synthese hart (Absturz)
  hang_cuda       hängt bei jeder Synthese, solange --provider cuda ist; auf der CPU normal
  load_fail_cuda  Laden scheitert mit --provider cuda (wie „GPU voll“); auf der CPU normal
  cuda_error      Synthese meldet einen CUDA-Fehler, solange --provider cuda ist; auf der CPU normal
  cpu_ready       --provider cuda angefragt, meldet aber „cpu“ (CUDA nicht verfügbar)
  garbage         schickt bei der ersten Synthese kaputte Bytes
  big_frame       schickt bei der ersten Synthese einen Kopf mit zu großer Nutzdatenlänge
  bad_wav         antwortet mit Nutzdaten, die keine WAV sind
  no_ready        meldet sich nie bereit
Aufruf: python -I fake_tts_worker.py <pfad zu kokoro_worker.py> --mode ok --provider cuda [--delay 1.0]
"""
import argparse
import importlib.util
import math
import os
import struct
import sys
import time

spec = importlib.util.spec_from_file_location("kokoro_worker", sys.argv[1])
kw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kw)


def tone(seconds=0.1, rate=24000):
    import io
    import wave
    n = int(seconds * rate)
    pcm = struct.pack(f"<{n}h", *(int(8000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(n)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


class FakeEngine:
    def __init__(self, mode, provider, delay, out):
        self.mode, self.provider, self.delay, self.out, self.calls = mode, provider, delay, out, 0
        self.rate = 24000

    def synth(self, text):
        self.calls += 1
        if self.mode == "crash":
            os._exit(9)
        if self.mode == "hang_cuda" and self.provider == "cuda":
            time.sleep(3600)
        if self.mode == "cuda_error" and self.provider == "cuda":
            raise RuntimeError("CUDA failure 2: out of memory")
        if self.mode == "garbage" and self.calls == 1:
            self.out.write(b"\xff\xff\xff\xffnot a frame")
            self.out.flush()
            time.sleep(3600)
        if self.mode == "big_frame" and self.calls == 1:
            head = b'{"type":"audio","id":1,"epoch":0,"bytes":99999999}'       # 95 MB angekündigt, Grenze 16 MiB
            self.out.write(struct.pack(">I", len(head)) + head)
            self.out.flush()
            time.sleep(3600)
        if self.mode == "bad_wav":
            return b"RIFF....WAVEjunkjunkjunkjunkjunkjunkjunkjunkjunk"
        if self.mode == "slow":
            time.sleep(self.delay)
        return tone(0.05 + 0.01 * len(text) / 10)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("worker")
    ap.add_argument("--mode", default="ok")
    ap.add_argument("--provider", default="cuda")
    ap.add_argument("--delay", type=float, default=0.5)
    a = ap.parse_args()
    out, inp = sys.stdout.buffer, sys.stdin.buffer
    sys.stdout = sys.stderr
    kw.block_network()
    if a.mode == "load_fail_cuda" and a.provider == "cuda":
        out.write(kw.encode_frame({"type": "error", "code": "load", "cuda": True, "error": "RuntimeError"}))
        out.flush()
        return 3
    if a.mode == "no_ready":
        time.sleep(3600)
    provider = "cpu" if a.mode == "cpu_ready" else a.provider
    engine = FakeEngine(a.mode, provider, a.delay, out)
    server = kw.Server(engine, out, provider)
    server.send({"type": "ready", "provider": provider, "sr": 24000, "load_s": 0.0})
    return server.run(inp)


if __name__ == "__main__":
    sys.exit(main())
