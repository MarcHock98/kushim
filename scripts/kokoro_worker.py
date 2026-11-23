"""Sprachausgabe-Worker: Kokoro-82M deutsch, Stimme „Martin“ (ONNX), als Kindprozess von `kushim talk`.

Läuft im eigenen venv (tools/kokoro/venv, mit onnxruntime-gpu) und wird von `src/kushim/voice/ttsworker.py` gestartet:
    tools/kokoro/venv/Scripts/python.exe -I scripts/kokoro_worker.py --model-dir models/kokoro --provider cuda|cpu

Sicherheit:
- KEIN NETZ: Als Allererstes (vor jedem Import außerhalb der Standardbibliothek) sperrt `block_network()` im Prozess jede
  Socket-Erzeugung, Verbindung, Namensauflösung und `socketpair` - auch Loopback. Dazu Offline-Variablen. Native Bibliotheken
  (onnxruntime, espeak-ng) sind davon nicht erfasst; sie haben in diesem Einsatz keinen Netzcode im Pfad.
- Kein Socket als Schnittstelle: Aufträge kommen über stdin, Antworten gehen über stdout, sonst nichts. Alles andere
  (auch `print` von Bibliotheken) geht nach stderr (Protokolldatei). Der Worker schreibt nie den vorgelesenen Text in ein Log.
- Nur die eingebaute Stimme „martin“, kein Klonen, keine Referenzaufnahme. Modell und Stimmen nur aus --model-dir, keine
  Downloads (keine HF-/URL-Aufrufe in dieser Datei; ein Test prüft das).

Protokoll (Rahmen): 4 Byte Länge (big endian) + JSON-Kopf (UTF-8, höchstens 64 KiB); hat der Kopf "bytes": n, folgen n Byte
Nutzdaten (WAV, höchstens 16 MiB).
  Worker -> kushim: {"type": "ready", "provider": "cuda"|"cpu", "sr": 24000, "load_s": 1.2}
                    {"type": "audio", "id": 7, "epoch": 2, "bytes": n} + WAV (16 bit, mono)
                    {"type": "error", "id": 7, "epoch": 2, "code": "synth"|"cuda"|"cancelled"|"bad_request"|"load"}
  kushim -> Worker: {"type": "synth", "id": 7, "epoch": 2, "text": "..."}
                    {"type": "cancel", "epoch": 3}   (verwirft wartende Aufträge mit kleinerer Epoche)
                    {"type": "quit"}
"""
from __future__ import annotations

import json
import os
import struct
import sys
import threading
import time

MAX_HEADER = 64 * 1024
MAX_PAYLOAD = 16 * 1024 * 1024
MAX_TEXT = 2000
VOICE = "martin"
SPEED = 1.125                    # wie im Repo-Skript (onnx-docker/main.py) und in der Messung
MODEL_FILE = "kokoro-martin.onnx"
VOICES_FILE = "voices-martin.npz"
OFFLINE_ENV = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
               "DO_NOT_TRACK": "1", "ORT_DISABLE_TELEMETRY": "1"}
CUDA_HINTS = ("cuda", "cudnn", "cublas", "out of memory", "failed to allocate", "bfcarena", "cufft", "curand")


class ProtocolError(ValueError):
    pass


class NetworkBlocked(OSError):
    pass


# --- Netzsperre (vor allem anderen) --------------------------------------------------------------------------------------

def block_network() -> None:
    """Sperrt im eigenen Prozess jeden Netzzugang, auch Loopback: keine Sockets, keine Verbindungen, keine Namensauflösung."""
    os.environ.update(OFFLINE_ENV)
    import socket
    import _socket

    def refuse(*_a, **_k):
        raise NetworkBlocked("Netz gesperrt (Sprachausgabe läuft offline)")

    class BlockedSocket(socket.socket):
        def __init__(self, *_a, **_k):          # noqa: D401 - jede Erzeugung scheitert
            raise NetworkBlocked("Netz gesperrt (Sprachausgabe läuft offline)")

    for name in ("connect", "connect_ex", "bind", "listen", "sendto", "sendmsg"):
        if hasattr(socket.socket, name):          # nur vorhandene ersetzen (asyncio prüft z. B. hasattr(socket, "sendmsg"))
            setattr(socket.socket, name, refuse)
    socket.socket = BlockedSocket                 # type: ignore[misc]
    socket.SocketType = BlockedSocket             # type: ignore[misc]
    for name in ("create_connection", "create_server", "getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr",
                 "getnameinfo", "socketpair", "fromfd"):
        if hasattr(socket, name):
            setattr(socket, name, refuse)
    for name in ("socket", "SocketType", "getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo",
                 "socketpair", "fromfd"):
        if hasattr(_socket, name):
            setattr(_socket, name, refuse)


# --- Rahmen --------------------------------------------------------------------------------------------------------------

def encode_frame(header: dict, payload: bytes = b"") -> bytes:
    if payload:
        header = {**header, "bytes": len(payload)}
    raw = json.dumps(header, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    if len(raw) > MAX_HEADER or len(payload) > MAX_PAYLOAD:
        raise ProtocolError("Rahmen zu groß")
    return struct.pack(">I", len(raw)) + raw + payload


def _read_exact(stream, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            raise EOFError("Strom zu Ende")
        buf += chunk
    return bytes(buf)


def read_frame(stream) -> tuple[dict, bytes]:
    """(Kopf, Nutzdaten). EOFError am Ende, ProtocolError bei kaputten oder zu großen Daten."""
    size = struct.unpack(">I", _read_exact(stream, 4))[0]
    if size == 0 or size > MAX_HEADER:
        raise ProtocolError(f"Kopf mit {size} Byte")
    try:
        header = json.loads(_read_exact(stream, size).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ProtocolError("Kopf ist kein JSON") from e
    if not isinstance(header, dict) or not isinstance(header.get("type"), str):
        raise ProtocolError("Kopf ohne Typ")
    n = header.get("bytes", 0)
    if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= MAX_PAYLOAD:
        raise ProtocolError("ungültige Nutzdatenlänge")
    return header, _read_exact(stream, n) if n else b""


# --- Engine --------------------------------------------------------------------------------------------------------------

def wav_bytes(samples, rate: int) -> bytes:
    import io
    import wave

    import numpy as np
    pcm = (np.clip(np.asarray(samples, dtype=np.float32).reshape(-1), -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


class KokoroEngine:
    """Kokoro Martin über onnxruntime (CUDA oder CPU) und kokoro-onnx mit espeak-ng aus `espeakng-loader` (keine Systeminstallation)."""

    def __init__(self, model_dir: str, provider: str, device_id: int = 0, threads: int = 0, gpu_mem_mb: int = 2048):
        import logging

        import onnxruntime as ort
        from kokoro_onnx import Kokoro
        logging.getLogger("kokoro_onnx").setLevel(logging.ERROR)      # sonst stehen Phoneme (also der Text) im Log
        ort.set_default_logger_severity(3)
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if threads:
            so.intra_op_num_threads = threads
            so.inter_op_num_threads = 1
        if provider == "cuda":
            ort.preload_dlls()        # CUDA-/cuDNN-DLLs aus den nvidia-*-Wheels im venv (keine Systeminstallation)
            providers = [("CUDAExecutionProvider", {"device_id": int(device_id), "arena_extend_strategy": "kSameAsRequested",
                                                    "gpu_mem_limit": int(gpu_mem_mb) * 1024 * 1024,
                                                    "cudnn_conv_algo_search": "DEFAULT"}), "CPUExecutionProvider"]
        else:
            providers = ["CPUExecutionProvider"]
        model = os.path.join(model_dir, MODEL_FILE)
        sess = ort.InferenceSession(model, sess_options=so, providers=providers)
        active = sess.get_providers()
        self.provider = "cuda" if active and active[0] == "CUDAExecutionProvider" else "cpu"
        self.kokoro = Kokoro.from_session(sess, os.path.join(model_dir, VOICES_FILE))
        self.rate = 24000

    def synth(self, text: str) -> bytes:
        samples, rate = self.kokoro.create(text=text, voice=VOICE, speed=SPEED, lang="de")
        self.rate = int(rate)
        return wav_bytes(samples, rate)


# --- Ablauf --------------------------------------------------------------------------------------------------------------

class Server:
    """Liest Aufträge in einem eigenen Thread (damit `cancel` auch während einer Synthese ankommt) und arbeitet sie der Reihe
    nach ab. Aufträge mit einer Epoche unter der zuletzt abgebrochenen werden verworfen."""

    def __init__(self, engine, out, provider: str):
        self.engine, self.out, self.provider = engine, out, provider
        self.min_epoch = 0
        self.jobs: list[dict] = []
        self.cond = threading.Condition()
        self.quit = False
        self.write_lock = threading.Lock()

    def send(self, header: dict, payload: bytes = b"") -> None:
        frame = encode_frame(header, payload)
        with self.write_lock:
            self.out.write(frame)
            self.out.flush()

    def read_loop(self, inp) -> None:
        try:
            while True:
                header, _ = read_frame(inp)
                kind = header["type"]
                with self.cond:
                    if kind == "synth":
                        self.jobs.append(header)
                    elif kind == "cancel":
                        epoch = header.get("epoch")
                        if isinstance(epoch, int) and not isinstance(epoch, bool):
                            self.min_epoch = max(self.min_epoch, epoch)
                    elif kind == "quit":
                        self.quit = True
                    else:
                        raise ProtocolError(f"unbekannter Typ {kind!r}")
                    self.cond.notify_all()
        except (EOFError, ProtocolError, OSError, ValueError):
            with self.cond:                       # kushim ist weg oder schickt Unsinn: sauber beenden
                self.quit = True
                self.cond.notify_all()

    def next_job(self) -> dict | None:
        with self.cond:
            while not self.jobs and not self.quit:
                self.cond.wait()
            if self.quit:
                return None
            return self.jobs.pop(0)

    def run(self, inp) -> int:
        threading.Thread(target=self.read_loop, args=(inp,), daemon=True).start()
        while True:
            job = self.next_job()
            if job is None:
                return 0
            self.handle(job)

    def handle(self, job: dict) -> None:
        jid, epoch, text = job.get("id"), job.get("epoch"), job.get("text")
        ref = {"id": jid, "epoch": epoch}
        if (not isinstance(jid, int) or isinstance(jid, bool) or not isinstance(epoch, int) or isinstance(epoch, bool)
                or not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT):
            self.send({"type": "error", **ref, "code": "bad_request"})
            return
        if epoch < self.min_epoch:
            self.send({"type": "error", **ref, "code": "cancelled"})
            return
        try:
            audio = self.engine.synth(text)
        except Exception as e:                    # noqa: BLE001 (Fehler melden, nie den Text)
            msg = f"{type(e).__name__}: {e}".lower()
            code = "cuda" if self.provider == "cuda" and any(h in msg for h in CUDA_HINTS) else "synth"
            print(f"Synthese-Fehler ({code}): {type(e).__name__}", file=sys.stderr, flush=True)
            self.send({"type": "error", **ref, "code": code})
            return
        if epoch < self.min_epoch:                # während der Rechnung abgebrochen
            self.send({"type": "error", **ref, "code": "cancelled"})
            return
        self.send({"type": "audio", **ref}, audio)


def selftest_network(out) -> int:
    """Nur für Tests: Netzsperre setzen und prüfen, dass jeder Weg ins Netz (auch Loopback) scheitert."""
    block_network()
    import socket
    import _socket
    attempts = {
        "socket": lambda: socket.socket(),
        "raw_socket": lambda: _socket.socket(),
        "create_connection": lambda: socket.create_connection(("127.0.0.1", 9), timeout=1),
        "getaddrinfo": lambda: socket.getaddrinfo("localhost", 80),
        "socketpair": lambda: socket.socketpair(),
        "gethostbyname": lambda: socket.gethostbyname("example.com"),
    }
    blocked, open_ = [], []
    for name, attempt in attempts.items():
        try:
            attempt()
        except OSError:
            blocked.append(name)
        else:
            open_.append(name)
    out.write(encode_frame({"type": "selftest", "blocked": blocked, "open": open_,
                            "offline": all(os.environ.get(k) == v for k, v in OFFLINE_ENV.items())}))
    out.flush()
    return 0 if not open_ else 1


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir")
    ap.add_argument("--provider", choices=("cuda", "cpu"), default="cuda")
    ap.add_argument("--device-id", type=int, default=0)
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--gpu-mem-mb", type=int, default=2048)
    ap.add_argument("--selftest-net", action="store_true")
    args = ap.parse_args(argv)
    out, inp = sys.stdout.buffer, sys.stdin.buffer
    sys.stdout = sys.stderr                       # Bibliotheken schreiben gern nach stdout: das gehört nicht ins Protokoll
    if args.selftest_net:
        return selftest_network(out)
    block_network()                               # vor onnxruntime, numpy, kokoro_onnx, espeak
    model_dir = os.path.abspath(args.model_dir or "")
    if not all(os.path.isfile(os.path.join(model_dir, f)) for f in (MODEL_FILE, VOICES_FILE)):
        out.write(encode_frame({"type": "error", "code": "load", "cuda": False, "error": "Modelldateien fehlen"}))
        out.flush()
        return 2
    t0 = time.perf_counter()
    try:
        engine = KokoroEngine(model_dir, args.provider, args.device_id, args.threads, args.gpu_mem_mb)
        engine.synth("Hallo.")                    # Aufwärmen: der erste Aufruf ist sonst deutlich langsamer
    except Exception as e:                        # noqa: BLE001
        print(f"Laden gescheitert: {type(e).__name__}: {str(e)[:300]}", file=sys.stderr, flush=True)
        out.write(encode_frame({"type": "error", "code": "load", "cuda": args.provider == "cuda",
                                "error": type(e).__name__}))
        out.flush()
        return 3
    server = Server(engine, out, engine.provider)
    server.send({"type": "ready", "provider": engine.provider, "sr": engine.rate, "load_s": round(time.perf_counter() - t0, 2)})
    print(f"bereit: {engine.provider}, {time.perf_counter() - t0:.1f} s", file=sys.stderr, flush=True)
    return server.run(inp)


if __name__ == "__main__":
    sys.exit(main())
