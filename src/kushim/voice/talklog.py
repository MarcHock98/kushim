"""Gesprächsprotokoll für die Fehlersuche (Wunsch des Nutzers 2026-11-11): `run/talk.log`, eine JSON-Zeile je Ereignis.

Steht drin: Zeit, Ereignis (start, wake, result, note, end), was erkannt wurde, was kushim geantwortet hat, Ergebnis
(z. B. rejected_speaker mit Score) und wie lange die Runde gedauert hat. Nie Audio. Die Datei bleibt lokal (run/ ist nicht
im Git) und wird bei 1 MB einmal rotiert (talk.log.1). Fehler beim Schreiben stören den Betrieb nie.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

MAX_BYTES = 1_000_000
MAX_TEXT = 600


class TalkLog:
    def __init__(self, path: Path, clock=time.time):
        self.path, self.clock = path, clock
        self._lock = threading.Lock()

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

    def timed(self, handle):
        """Umhüllt `pipeline.handle`: schreibt jedes Ergebnis mit der Dauer der Runde (Erkennen bis fertig gesprochen)."""
        def run(pcm):
            t0 = time.monotonic()
            try:
                r = handle(pcm)
            except Exception as e:                    # noqa: BLE001 (protokollieren, dann wie bisher weiterwerfen)
                self.write("error", where="pipeline", error=f"{type(e).__name__}: {e}")
                raise
            self.write("result", heard=r.heard, reply=r.reply, outcome=r.outcome, detail=r.detail,
                       seconds=time.monotonic() - t0)
            return r
        return run
