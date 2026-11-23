"""Anbindung an den Sprachausgabe-Worker (Kokoro „Martin“, `scripts/kokoro_worker.py`) als Kindprozess.

Der Worker läuft in seinem eigenen venv (tools/kokoro/venv) und spricht nur über stdin/stdout mit kushim: Rahmen aus 4 Byte
Länge, JSON-Kopf und optional WAV-Bytes (siehe Worker). Kein Socket, kein Port.

Sicherheit und Betrieb:
- Umgebung des Kindprozesses nur nach Liste erlaubter Variablen (`ALLOWED_ENV`), ohne Tokens/Schlüssel; Offline-Variablen
  dazu; kein Konsolenfenster (`hidden()`). Im Worker sperrt `block_network()` jedes Netz, auch Loopback.
- Notaus: `kill()` (als `KillSwitch`-Aktion) beendet den Worker samt Kindern per `kill_tree`, danach kein Neustart.
- Beenden: `close()` schickt `quit`, wartet kurz, dann `kill_tree`.
- Absturz, kaputte Daten oder Hänger (Watchdog je Satz): Worker beenden und nach einer Pause neu starten, höchstens
  `MAX_RESTARTS` in `RESTART_WINDOW` Sekunden; danach „failed“ (Speaker: Text plus Hinweiston).
- CPU-Rückfall: Scheitert CUDA (Laden, GPU voll, CUDA-Fehler beim Rechnen, Absturz auf der GPU), startet der Worker mit dem
  CPU-Provider neu (Kokoro schafft dort etwa 0,5 s bis zum ersten Ton).
- Zustand für die Oberfläche (`voice-state.json`, Feld `tts`): loading | ready | cpu | failed | off.
"""
from __future__ import annotations

import io
import json
import os
import queue
import struct
import subprocess
import threading
import time
import wave
from pathlib import Path
from typing import Any, Callable, Sequence

from ..procflags import hidden, kill_tree
from .tts import TTSCancelled, TTSUnavailable

MAX_HEADER = 64 * 1024
MAX_PAYLOAD = 16 * 1024 * 1024
MAX_TEXT = 2000
MAX_AUDIO_SECONDS = 120.0
STATES = ("loading", "ready", "cpu", "failed", "off")
MAX_RESTARTS = 3
RESTART_WINDOW = 600.0
RESTART_PAUSES = (1.0, 3.0, 10.0)
LOAD_TIMEOUT = 120.0            # erster GPU-Start mit kaltem Cache dauerte 20 s; großzügig, danach CPU
QUIT_WAIT = 2.0

VENV_PYTHON = Path("tools") / "kokoro" / "venv" / "Scripts" / "python.exe"
WORKER_SCRIPT = Path("scripts") / "kokoro_worker.py"
MODEL_DIR = Path("models") / "kokoro"
LOG_FILE = Path("run") / "tts-worker.log"
LOG_MAX = 1_000_000

# Nur diese Variablen erbt der Worker (Windows braucht SYSTEMROOT u. a. zum Laden von DLLs). Keine Tokens, keine Proxys.
ALLOWED_ENV = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP", "NUMBER_OF_PROCESSORS",
               "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "OS", "COMSPEC", "CUDA_DEVICE_ORDER", "CUDA_VISIBLE_DEVICES")
OFFLINE_ENV = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
               "DO_NOT_TRACK": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}


class ProtocolError(ValueError):
    pass


# --- Rahmen und Prüfungen (reine Funktionen) -----------------------------------------------------------------------------

def encode_frame(header: dict, payload: bytes = b"") -> bytes:
    if payload:
        header = {**header, "bytes": len(payload)}
    raw = json.dumps(header, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    if len(raw) > MAX_HEADER or len(payload) > MAX_PAYLOAD:
        raise ProtocolError("Rahmen zu groß")
    return struct.pack(">I", len(raw)) + raw + payload


def _read_exact(stream: Any, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            raise EOFError("Strom zu Ende")
        buf += chunk
    return bytes(buf)


def read_frame(stream: Any) -> tuple[dict, bytes]:
    """(Kopf, Nutzdaten). EOFError am Ende, ProtocolError bei kaputten oder zu großen Daten (vor dem Lesen geprüft)."""
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


def check_wav(data: bytes) -> tuple[int, int]:
    """(Abtastrate, Frames) einer WAV vom Worker; ValueError, wenn es kein 16-bit-Mono-PCM in vernünftiger Länge ist."""
    if not isinstance(data, (bytes, bytearray)) or len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("keine WAV-Datei")
    try:
        with wave.open(io.BytesIO(data)) as w:
            channels, width, rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            if w.getcomptype() != "NONE":
                raise ValueError("komprimiert")
            body = w.readframes(frames)
    except (wave.Error, EOFError, RuntimeError, struct.error) as e:
        raise ValueError(f"WAV kaputt: {e}") from e
    if channels != 1 or width != 2 or not 8000 <= rate <= 48000:
        raise ValueError("nicht 16-bit-mono")
    if frames < 1 or len(body) != frames * 2 or frames / rate > MAX_AUDIO_SECONDS:
        raise ValueError("Länge passt nicht")
    return rate, frames


def worker_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Umgebung für den Kindprozess: nur erlaubte Variablen aus `base` (Groß-/Kleinschreibung egal) plus Offline-Variablen."""
    base = dict(os.environ if base is None else base)
    upper = {k.upper(): v for k, v in base.items()}
    env = {k: upper[k] for k in ALLOWED_ENV if k in upper}
    env.update(OFFLINE_ENV)
    return env


def watchdog_seconds(text: str) -> float:
    """Zeit für einen Satz, danach gilt der Worker als hängend (CPU: Echtzeitfaktor ~0,15, also reichlich Luft)."""
    return 8.0 + len(text) / 20.0


# --- Client --------------------------------------------------------------------------------------------------------------

class KokoroWorker:
    """Engine für den Speaker (`synthesize(text) -> WAV-Bytes`), die den Worker-Prozess verwaltet."""

    def __init__(self, command: Callable[[str], Sequence[str]], provider: str = "cuda", *,
                 env: dict[str, str] | None = None, log_path: Path | None = None, cwd: Path | None = None,
                 clock: Callable[[], float] = time.monotonic, load_timeout: float = LOAD_TIMEOUT,
                 restart_pauses: Sequence[float] = RESTART_PAUSES, watchdog: Callable[[str], float] = watchdog_seconds,
                 popen: Callable[..., Any] | None = None, kill: Callable[[int], None] = kill_tree):
        self._command, self._env, self._log_path, self._cwd = command, env, log_path, cwd
        self._clock, self._load_timeout, self._pauses, self._watchdog = clock, load_timeout, tuple(restart_pauses), watchdog
        self._popen, self._kill_tree = popen, kill
        self.provider = provider if provider in ("cuda", "cpu") else "cpu"   # gewünschter Provider des nächsten Starts
        self.active: str | None = None            # tatsächlicher Provider laut "ready"
        self.on_state: Callable[[str], None] = lambda state: None
        self.on_note: Callable[[str], None] = lambda text: None
        self._state = "off"
        self._lock = threading.RLock()
        self._req_lock = threading.Lock()
        self._proc: Any = None
        self._gen = 0
        self._epoch = 0
        self._next_id = 0
        self._ready = threading.Event()
        self._responses: queue.Queue = queue.Queue()
        self._restarts: list[float] = []
        self._stopped = False                     # close() oder kill(): nie wieder starten
        self._timers: list[threading.Timer] = []

    @classmethod
    def for_root(cls, root: Path, provider: str = "cuda", device_id: int = 0, assets: Path | None = None,
                 **kw: Any) -> "KokoroWorker":
        """Worker-Skript aus `root/scripts`; venv und Modell aus `assets` (Standard: dasselbe `root`; Tests im Worktree
        zeigen damit auf die nicht versionierten Ordner des Hauptprojekts)."""
        assets = root if assets is None else assets
        python, script, model = assets / VENV_PYTHON, root / WORKER_SCRIPT, assets / MODEL_DIR

        def command(p: str) -> list[str]:
            return [str(python), "-I", str(script), "--model-dir", str(model), "--provider", p, "--device-id", str(int(device_id))]
        return cls(command, provider, log_path=root / LOG_FILE, cwd=root, **kw)

    # --- Zustand
    @property
    def state(self) -> str:
        return self._state

    def _set_state(self, state: str) -> None:
        if state not in STATES or state == self._state:
            return
        self._state = state
        try:
            self.on_state(state)
        except Exception:                         # noqa: BLE001 (Anzeige darf nie stören)
            pass

    def _note(self, text: str) -> None:
        try:
            self.on_note(text)
        except Exception:                         # noqa: BLE001
            pass

    # --- Start, Ende, Notaus
    def start(self) -> None:
        with self._lock:
            if self._stopped or self._proc is not None:
                return
            self._spawn()

    def _spawn(self) -> None:
        """Startet einen neuen Worker (unter `_lock`)."""
        self._gen += 1
        gen, provider = self._gen, self.provider
        self._ready.clear()
        self.active = None
        self._set_state("loading")
        log = self._open_log()
        try:
            argv = list(self._command(provider))
            env = worker_env() if self._env is None else dict(self._env)
            if self._popen is not None:
                proc = self._popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log or subprocess.DEVNULL,
                                   env=env, cwd=str(self._cwd) if self._cwd else None, bufsize=0, **hidden())
            else:
                proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=log or subprocess.DEVNULL, env=env,
                                        cwd=str(self._cwd) if self._cwd else None, bufsize=0, **hidden())
        except OSError as e:
            if log is not None:
                log.close()
            self._proc = None
            self._note(f"Sprachausgabe startet nicht: {type(e).__name__}")
            self._crashed(gen, provider)
            return
        finally:
            if log is not None and not log.closed:
                log.close()                       # der Kindprozess hat seine eigene Kopie des Handles
        self._proc = proc
        threading.Thread(target=self._reader, args=(proc, gen, provider), daemon=True, name="kushim-tts-reader").start()
        timer = threading.Timer(self._load_timeout, self._load_timed_out, args=(gen,))
        timer.daemon = True
        self._timers.append(timer)
        timer.start()

    def _open_log(self) -> Any:
        if self._log_path is None:
            return None
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            mode = "wb" if not self._log_path.exists() or self._log_path.stat().st_size > LOG_MAX else "ab"
            return open(self._log_path, mode)     # noqa: SIM115 (Handle geht an den Kindprozess)
        except OSError:
            return None

    def wait_ready(self, timeout: float) -> bool:
        """Wartet, bis der Worker bereit ist (GPU oder CPU). False bei Zeitablauf, „failed“ oder „off“."""
        deadline = self._clock() + timeout
        while True:
            if self._ready.is_set():
                return True
            if self._state in ("failed", "off"):
                return False
            remaining = deadline - self._clock()
            if remaining <= 0:
                return False
            self._ready.wait(min(0.1, remaining))

    def kill(self) -> None:
        """Notaus: Worker samt Kindern sofort beenden, kein Neustart. Wartende Synthese endet sofort."""
        with self._lock:
            self._stopped = True
            proc, self._proc = self._proc, None
            self._gen += 1
            self._ready.clear()
            self._cancel_timers()
            self._set_state("off")
        if proc is not None:
            self._kill_tree(proc.pid)

    def close(self) -> None:
        """Regulär beenden: `quit` schicken, kurz warten, dann sicherheitshalber `kill_tree`."""
        with self._lock:
            self._stopped = True
            proc, self._proc = self._proc, None
            self._gen += 1
            self._ready.clear()
            self._cancel_timers()
            self._set_state("off")
        if proc is None:
            return
        try:
            proc.stdin.write(encode_frame({"type": "quit"}))
            proc.stdin.flush()
            proc.stdin.close()
        except (OSError, ValueError, AttributeError):
            pass
        try:
            proc.wait(timeout=QUIT_WAIT)
        except Exception:                         # noqa: BLE001
            pass
        self._kill_tree(proc.pid)

    def _cancel_timers(self) -> None:
        for t in self._timers:
            t.cancel()
        self._timers.clear()

    # --- Lesen, Absturz, Neustart
    def _reader(self, proc: Any, gen: int, provider: str) -> None:
        reason = "beendet"
        try:
            while True:
                header, payload = read_frame(proc.stdout)
                kind = header["type"]
                if kind == "ready":
                    active = header.get("provider")
                    if active not in ("cuda", "cpu"):
                        raise ProtocolError("ready ohne gültigen Provider")
                    with self._lock:
                        if gen != self._gen:
                            return
                        self.active = active
                        if active == "cpu":
                            self.provider = "cpu"         # CUDA nicht verfügbar: auch spätere Neustarts auf der CPU
                        self._ready.set()
                        self._set_state("ready" if active == "cuda" else "cpu")
                    if provider == "cuda" and active == "cpu":
                        self._note("Sprachausgabe: CUDA nicht verfügbar, sie läuft auf dem Prozessor.")
                elif kind in ("audio", "error"):
                    if kind == "error" and header.get("code") == "load":
                        reason = "Laden gescheitert" + (" (GPU)" if header.get("cuda") else "")
                        continue
                    self._responses.put((gen, header, payload))
                else:
                    raise ProtocolError(f"unbekannter Typ {kind!r}")
        except EOFError:
            pass
        except (ProtocolError, OSError, ValueError) as e:
            reason = f"Protokollfehler: {type(e).__name__}"
        self._crashed(gen, provider, proc, reason)

    def _crashed(self, gen: int, provider: str, proc: Any = None, reason: str = "abgestürzt") -> None:
        with self._lock:
            if gen != self._gen or self._stopped:
                return                                       # schon ersetzt, beendet oder Notaus
            self._gen += 1                                   # Antworten dieses Prozesses gelten nicht mehr
            self._proc = None
            self._ready.clear()
            now = self._clock()
            self._restarts = [t for t in self._restarts if now - t < RESTART_WINDOW]
            if provider == "cuda":
                self.provider = "cpu"                        # GPU voll oder CUDA ausgefallen: auf dem Prozessor weiter
            if len(self._restarts) >= MAX_RESTARTS:
                self._set_state("failed")
                self._note(f"Sprachausgabe aus ({reason}); Antworten kommen als Text mit Hinweiston.")
                kill_pid = proc.pid if proc is not None else None
            else:
                pause = self._pauses[min(len(self._restarts), len(self._pauses) - 1)] if self._pauses else 0.0
                self._restarts.append(now)
                self._set_state("loading")
                self._note(f"Sprachausgabe {reason}; Neustart auf {'GPU' if self.provider == 'cuda' else 'CPU'} "
                           f"in {pause:g} s.")
                timer = threading.Timer(pause, self._restart)
                timer.daemon = True
                self._timers.append(timer)
                timer.start()
                kill_pid = proc.pid if proc is not None else None
        if kill_pid is not None:
            self._kill_tree(kill_pid)

    def _restart(self) -> None:
        with self._lock:
            if self._stopped or self._proc is not None:
                return
            self._spawn()

    def _load_timed_out(self, gen: int) -> None:
        with self._lock:
            if gen != self._gen or self._ready.is_set() or self._proc is None:
                return
            proc = self._proc
        # beendet den Prozess (kill_tree) und plant den Neustart; GPU-Start, der nicht fertig wird: danach auf der CPU
        self._crashed(gen, self.provider if self.active is None else self.active, proc, "lädt nicht")

    # --- Engine
    def cancel(self) -> None:
        """Laufende und wartende Sätze verwerfen (Unterbrechen, Notaus). Wirkt sofort für den Wartenden in `synthesize`."""
        with self._lock:
            self._epoch += 1
            epoch, proc = self._epoch, self._proc
        if proc is not None:
            try:
                proc.stdin.write(encode_frame({"type": "cancel", "epoch": epoch}))
                proc.stdin.flush()
            except (OSError, ValueError, AttributeError):
                pass

    def synthesize(self, text: str) -> bytes:
        if not isinstance(text, str) or not text.strip():
            raise TTSUnavailable("leerer Text")
        text = text[:MAX_TEXT]
        with self._req_lock:
            if not self._ready.is_set():
                raise TTSUnavailable(f"Sprachausgabe {self._state}")
            with self._lock:
                proc, gen, epoch = self._proc, self._gen, self._epoch
                self._next_id += 1
                rid = self._next_id
            if proc is None:
                raise TTSUnavailable("kein Worker")
            try:
                proc.stdin.write(encode_frame({"type": "synth", "id": rid, "epoch": epoch, "text": text}))
                proc.stdin.flush()
            except (OSError, ValueError, AttributeError) as e:
                raise TTSUnavailable("Worker nimmt nichts an") from e
            deadline = self._clock() + self._watchdog(text)
            while True:
                if self._epoch != epoch:
                    raise TTSCancelled("abgebrochen")
                if self._gen != gen:
                    raise TTSUnavailable("Worker beendet")
                remaining = deadline - self._clock()
                if remaining <= 0:
                    self._note("Sprachausgabe hängt (Watchdog); Neustart.")
                    self._hung(gen, proc)
                    raise TTSUnavailable("Watchdog")
                try:
                    mgen, header, payload = self._responses.get(timeout=min(0.05, remaining))
                except queue.Empty:
                    continue
                if mgen != gen or header.get("id") != rid:
                    continue                                 # Antwort auf einen abgebrochenen Satz
                if header["type"] == "audio":
                    try:
                        check_wav(payload)
                    except ValueError as e:
                        raise TTSUnavailable(f"ungültiges Audio: {e}") from e
                    return payload
                code = header.get("code")
                if code == "cancelled":
                    raise TTSCancelled("abgebrochen")
                if code == "cuda" and self.active == "cuda":
                    self._note("Sprachausgabe: CUDA-Fehler beim Rechnen; Neustart auf dem Prozessor.")
                    self._hung(gen, proc, provider="cuda")
                raise TTSUnavailable(f"Synthese-Fehler ({code})")

    def _hung(self, gen: int, proc: Any, provider: str | None = None) -> None:
        """Hänger oder CUDA-Fehler: wie ein Absturz behandeln (`_crashed` beendet den Prozess per kill_tree)."""
        self._crashed(gen, provider or self.active or self.provider, proc, "hängt" if provider is None else "CUDA-Fehler")
