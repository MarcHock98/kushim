"""Zustand der Sprach-Pipeline für die Oberfläche: `kushim talk` schreibt, `kushim serve` liest (`voice.state`).

Eine kleine Datei `run/voice-state.json` (atomar, nur lokal): Zustand, Pegel 0..1 und Zeitstempel. Kein Audio, kein Text.
Der Zeitstempel dient als Lebenszeichen: ist er älter als `MAX_AGE`, läuft kein Sprachdienst (`active: false`).
Der Leser vertraut der Datei nicht: unbekannte Zustände, falsche Typen oder alte Stempel ergeben "inaktiv".
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable

STATES = ("idle", "listening", "thinking", "speaking", "asking", "alarm", "halted")
FILE = Path("run") / "voice-state.json"
MAX_AGE = 5.0                      # Sekunden ohne Lebenszeichen = kein Sprachdienst
MIN_GAP = 0.2                      # höchstens 5 Schreibvorgänge pro Sekunde (Pegel und Lebenszeichen)
ALARM_SECONDS = 6.0                # so lange bleibt "alarm" nach einer abgelehnten Stimme sichtbar


class StatePublisher:
    def __init__(self, root: Path, pending: Callable[[], int] = lambda: 0,
                 clock: Callable[[], float] = time.time):
        self._path = root / FILE
        self._pending = pending
        self._clock = clock
        self._phase = "idle"
        self._alarm_until = 0.0
        self._last_state = ""
        self._last_write = 0.0

    def alarm(self) -> None:
        """Unbekannte Stimme: kurz "alarm" zeigen (keine Antwort, kein Ton)."""
        self._alarm_until = self._clock() + ALARM_SECONDS
        self._write(self._state(), 0.0)

    def phase(self, phase: str, level: float = 0.0) -> None:
        """Von der Sprach-Schleife je Frame (Zustand + Pegel) oder bei Zustandswechsel aufgerufen."""
        self._phase = phase if phase in STATES else "idle"
        state = self._state()
        now = self._clock()
        if state != self._last_state or now - self._last_write >= MIN_GAP:
            self._write(state, level)

    def _state(self) -> str:
        if self._phase == "halted":
            return "halted"
        if self._clock() < self._alarm_until:
            return "alarm"
        try:
            if self._pending() > 0:
                return "asking"
        except Exception:                            # noqa: BLE001 (Anzeige darf nie etwas stören)
            pass
        return self._phase

    def _write(self, state: str, level: float) -> None:
        now = self._clock()
        data = {"state": state, "level": round(min(1.0, max(0.0, float(level))), 3), "ts": now}
        tmp = self._path.with_suffix(".tmp")
        try:
            self._path.parent.mkdir(exist_ok=True)
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError:
            return                                   # Anzeige ist nie wichtiger als der Betrieb
        self._last_state, self._last_write = state, now

    def clear(self) -> None:
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            pass


def read(root: Path, now: float | None = None) -> dict:
    """{"active": bool, "state": str, "level": float}; bei Fehlern oder alter Datei inaktiv."""
    off = {"active": False, "state": "idle", "level": 0.0}
    try:
        data = json.loads((root / FILE).read_text(encoding="utf-8"))
        state, level, ts = data["state"], data["level"], data["ts"]
        if (state not in STATES or isinstance(level, bool) or not isinstance(level, (int, float))
                or isinstance(ts, bool) or not isinstance(ts, (int, float))):
            return off
        if (time.time() if now is None else now) - ts > MAX_AGE:
            return off
        return {"active": True, "state": state, "level": min(1.0, max(0.0, float(level)))}
    except (OSError, ValueError, KeyError, TypeError):
        return off


def frame_level(frame, full_scale: float = 4000.0) -> float:
    """Pegel eines 16-bit-Frames 0..1 (RMS, auf einen typischen Sprechpegel bezogen). Nur die Zahl, kein Audio."""
    import numpy as np
    x = np.asarray(frame, dtype=np.int16).astype(np.float64)
    return float(min(1.0, np.sqrt(np.mean(x * x)) / full_scale)) if x.size else 0.0
