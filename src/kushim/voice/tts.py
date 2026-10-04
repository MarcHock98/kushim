"""Lokale Sprachausgabe: Satzweises Streaming über eine austauschbare Engine.

Die Engine (Piper/Kokoro o. ä.) wird von außen geliefert; hier liegt nur die Logik.
Satzweise Ausgabe senkt die Latenz bis zum ersten Ton und erlaubt Barge-in zwischen Sätzen.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Iterator, Protocol

_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def prefetch(source: Iterable[str], stop: Callable[[], bool] = lambda: False, size: int = 2) -> Iterator[str]:
    """Erzeugt Sätze in einem Hintergrund-Thread vor, damit das LLM während der Wiedergabe weiterschreibt.

    Bei `stop()` (Notaus, Unterbrechen) endet der Strom sofort, auch wenn das LLM gerade noch an einem Satz schreibt."""
    import queue
    import threading
    q: queue.Queue = queue.Queue(maxsize=size)
    END, ERR = object(), object()

    def work():
        try:
            for item in source:
                while True:
                    if stop():
                        return
                    try:
                        q.put(item, timeout=0.1)
                        break
                    except queue.Full:
                        continue
            q.put(END)
        except Exception as e:           # noqa: BLE001 (Fehler an den Verbraucher weiterreichen)
            q.put((ERR, e))

    threading.Thread(target=work, daemon=True).start()
    while True:
        try:
            item = q.get(timeout=0.1)
        except queue.Empty:
            if stop():                   # Erzeuger hängt noch im LLM: nicht auf ihn warten
                return
            continue
        if item is END:
            return
        if isinstance(item, tuple) and item and item[0] is ERR:
            raise item[1]
        yield item


class Engine(Protocol):
    def synthesize(self, text: str) -> Any: ...


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SPLIT.split(text.strip()) if s.strip()]


def chunk_stream(tokens: Iterable[str]) -> Iterator[str]:
    """Fasst einen LLM-Tokenstrom zu vollständigen Sätzen zusammen."""
    buf = ""
    for tok in tokens:
        buf += tok
        parts = _SPLIT.split(buf)
        for s in parts[:-1]:
            if s.strip():
                yield s.strip()
        buf = parts[-1]
    if buf.strip():
        yield buf.strip()


class Speaker:
    def __init__(self, engine: Engine, play: Callable[[Any], None],
                 should_stop: Callable[[], bool] = lambda: False):
        self.engine, self.play, self.should_stop = engine, play, should_stop

    def say(self, sentences: Iterable[str]) -> int:
        """Spielt Sätze nacheinander; bricht vor jedem Satz ab, wenn `should_stop` (Barge-in/Notaus)."""
        n = 0
        for s in sentences:
            if self.should_stop():
                break
            wav = self.engine.synthesize(s)
            if self.should_stop():          # während der Synthese unterbrochen
                break
            self.play(wav)
            n += 1
        return n


class PiperEngine:
    """Piper (offline, GPL-3, nur lokale Modelldatei). Liefert WAV-Bytes pro Satz."""

    def __init__(self, voice: Any):
        self.voice = voice

    @classmethod
    def from_local(cls, model_path: str) -> "PiperEngine":
        from piper import PiperVoice
        return cls(PiperVoice.load(model_path))

    def synthesize(self, text: str) -> bytes:
        import io
        import wave
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            self.voice.synthesize_wav(text, w)
        return buf.getvalue()


class CloneEngine:
    """Eigene Stimme (Chatterbox Multilingual) über einen lokalen Kindprozess im eigenen venv (tools/chatterbox, scripts/clone_worker.py).

    Der Worker läuft ohne Netz (er sperrt es im Prozess selbst) und liest die Referenzaufnahme nur lokal. Hier wird nur ein Auftrag pro Satz
    ("text" -> WAV-Datei im eigenen Ordner) gesendet. Fällt der Worker aus oder braucht zu lange, wird er beendet und `synthesize` wirft
    RuntimeError; `FallbackEngine` nimmt dann die Piper-Stimme."""

    def __init__(self, python: str, worker: str, ref: str, out_dir: str, language: str = "de", device: str = "cuda",
                 popen: Any = None, ready_timeout: float = 240.0, job_timeout: float = 90.0):
        import subprocess
        import threading
        self._popen = popen or subprocess.Popen
        self.argv = [python, worker, "--ref", ref, "--out-dir", out_dir, "--language", language, "--device", device]
        self.out_dir, self.ready_timeout, self.job_timeout = out_dir, ready_timeout, job_timeout
        self._lock = threading.Lock()
        self._proc: Any = None
        self._seq = 0

    @staticmethod
    def _env() -> dict[str, str]:
        import os
        keep = ("PATH", "SystemRoot", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "COMSPEC", "PATHEXT", "CUDA_PATH",
                "CUDA_VISIBLE_DEVICES", "CUDA_DEVICE_ORDER")
        return {k: v for k, v in os.environ.items() if k in keep}                  # keine Schlüssel/Tokens an den Kindprozess

    def _readline(self, timeout: float) -> str:
        import queue
        import threading
        q: queue.Queue = queue.Queue()
        threading.Thread(target=lambda: q.put(self._proc.stdout.readline()), daemon=True).start()
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            self.close()
            raise RuntimeError("Der Stimmklon antwortet nicht")

    def _read_json(self, timeout: float) -> dict:
        """Nächste JSON-Zeile des Workers; Zeilen, die kein JSON sind (Meldungen von Bibliotheken), werden übersprungen."""
        import json
        for _ in range(50):
            line = self._readline(timeout)
            if not line:
                return {}                                       # Prozess beendet
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if isinstance(data, dict):
                return data
        return {}

    def start(self) -> None:
        import json
        import subprocess
        from pathlib import Path
        Path(self.out_dir).mkdir(parents=True, exist_ok=True)
        log = open(Path(self.out_dir) / "worker.log", "w", encoding="utf-8", errors="replace")      # nur Fehlermeldungen des Workers, lokal
        self._proc = self._popen(self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True,
                                 encoding="utf-8", errors="replace", env=self._env())
        ok = bool(self._read_json(self.ready_timeout).get("ready"))
        if not ok:
            self.close()
            raise RuntimeError("Der Stimmklon startet nicht")

    def synthesize(self, text: str) -> bytes:
        import json
        from pathlib import Path
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                self.start()
            self._seq += 1
            out = Path(self.out_dir) / f"clone-{self._seq}.wav"
            try:
                self._proc.stdin.write(json.dumps({"text": text, "out": str(out)}) + "\n")
                self._proc.stdin.flush()
                reply = self._read_json(self.job_timeout)
                if not reply.get("ok"):
                    raise RuntimeError("Stimmklon: " + str(reply.get("error", "Fehler"))[:100])
                return out.read_bytes()
            except (OSError, ValueError) as e:
                self.close()
                raise RuntimeError(f"Stimmklon fehlgeschlagen ({type(e).__name__})")
            finally:
                out.unlink(missing_ok=True)

    def close(self) -> None:
        p, self._proc = self._proc, None
        if p is not None:
            try:
                p.kill()
            except Exception:                                  # noqa: BLE001
                pass


class FallbackEngine:
    """Erst die Hauptstimme (Klon), bei Fehler die Ersatzstimme (Piper), damit kushim nie stumm bleibt."""

    def __init__(self, primary: Any, fallback: Any, on_fallback: Callable[[str], None] = lambda why: None):
        self.primary, self.fallback, self.on_fallback = primary, fallback, on_fallback
        self.disabled = False

    def synthesize(self, text: str) -> Any:
        if not self.disabled:
            try:
                return self.primary.synthesize(text)
            except RuntimeError as e:
                self.disabled = True                           # nicht bei jedem Satz neu versuchen (Startzeit); Neustart von kushim probiert es wieder
                self.on_fallback(str(e))
        return self.fallback.synthesize(text)
