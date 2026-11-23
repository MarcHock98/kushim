"""Gesprächsprotokoll für die Fehlersuche (Wunsch des Nutzers 2026-11-11): `run/talk.log`, eine JSON-Zeile je Ereignis.

Steht drin: Zeit, Ereignis (start, wake, result, note, end; tuning nur mit Quelle, Stufe und Schwellen-Zahlen), was erkannt wurde, was kushim geantwortet hat, Ergebnis
(z. B. rejected_speaker mit Score) und wie lange die Runde gedauert hat. Nie Audio. Die Datei bleibt lokal (run/ ist nicht
im Git) und wird bei 1 MB einmal rotiert (talk.log.1). Fehler beim Schreiben stören den Betrieb nie.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

MAX_BYTES = 1_000_000
MAX_TEXT = 600
METRICS = ("stt_s", "first_text_s", "first_audio_s", "spoken")    # nur Zahlen aus `pipeline.metrics`, nie Text


def numbers(raw: Any) -> dict[str, Any]:
    """Nur bekannte Kennzahlen, nur Zahlen (int/float) oder None; alles andere fällt weg (kein neuer Text im Protokoll)."""
    out: dict[str, Any] = {}
    if not isinstance(raw, dict):
        return out
    for k in METRICS:
        v = raw.get(k)
        if v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)):
            out[k] = v
    return out


class TalkLog:
    def __init__(self, path: Path, clock=time.time):
        self.path, self.clock = path, clock
        self._lock = threading.Lock()

    def barge(self, speaking: bool, rms: float, announcement: bool) -> None:
        """Unterbrechen ausgelöst: nur Flags und der Pegel des auslösenden Frames."""
        self.write("barge", speaking=bool(speaking), rms=float(rms), announcement=bool(announcement))

    def tuning(self, snapshot: Any) -> None:
        """Mikrofon-Schwellen geändert (`LiveTuning.on_change`): Quelle (fester Wert), Stufe und die vier Zahlen, nie Text."""
        snap = snapshot if isinstance(snapshot, dict) else {}
        source = snap.get("source")
        values = snap.get("values") if isinstance(snap.get("values"), dict) else {}
        step = snap.get("step")
        fields: dict[str, Any] = {"source": source if source in ("ui", "voice", "file") else "other",
                                  "step": step if isinstance(step, int) and not isinstance(step, bool) else None}
        for k in ("speech_level", "barge_in_level", "barge_in_ms", "end_silence_seconds"):
            v = values.get(k)
            fields[k] = v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
        self.write("tuning", **fields)

    def announced(self, outcome: str, spoken: Any) -> None:
        """Meldung von sich aus zu Ende: Ergebnis-Code (fester Wert) und Zahl der gesprochenen Sätze, nie der Text."""
        code = outcome if outcome in ("announced", "announce_interrupted") else "other"
        n = spoken if isinstance(spoken, int) and not isinstance(spoken, bool) else None
        self.write("announce", outcome=code, spoken=n)

    def write(self, event: str, **fields: Any) -> None:
        entry: dict[str, Any] = {"ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.clock())), "event": event}
        for k, v in fields.items():
            if isinstance(v, str):
                v = " ".join(v.split())[:MAX_TEXT]
            elif isinstance(v, float):
                v = round(v, 2)
            elif not isinstance(v, (int, bool, type(None))):
                v = str(v)[:MAX_TEXT]
            entry[k] = v
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size > MAX_BYTES:
                    self.path.replace(self.path.with_name(self.path.name + ".1"))
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line)
        except OSError:
            pass

    def timed(self, handle, metrics: Callable[[], Any] | None = None):
        """Umhüllt `pipeline.handle`: schreibt jedes Ergebnis mit der Dauer der Runde (Erkennen bis fertig gesprochen).
        `metrics`: liefert die Kennzahlen der Runde (z. B. `lambda: pipeline.metrics`); nur Zahlen kommen ins Protokoll."""
        def run(pcm):
            t0 = time.monotonic()
            try:
                r = handle(pcm)
            except Exception as e:                    # noqa: BLE001 (protokollieren, dann wie bisher weiterwerfen)
                self.write("error", where="pipeline", error=f"{type(e).__name__}: {e}")
                raise
            extra: dict[str, Any] = {}
            if metrics is not None:
                try:
                    extra = numbers(metrics())
                except Exception:                     # noqa: BLE001 (Protokoll darf den Betrieb nie stören)
                    extra = {}
            self.write("result", heard=r.heard, reply=r.reply, outcome=r.outcome, detail=r.detail,
                       seconds=time.monotonic() - t0, **extra)
            return r
        return run
