"""Zustand der Sprach-Pipeline für die Oberfläche: `kushim talk` schreibt, `kushim serve` liest (`voice.state`).

Eine kleine Datei `run/voice-state.json` (atomar, nur lokal): Zustand, Pegel 0..1 und Zeitstempel. Kein Audio, kein Text.
Für den Wake-Word-Test der Oberfläche (E3b) zusätzlich ein Zähler der erkannten Wake Words und der NAME des zuletzt
erkannten Worts (nie Audio, nie Gesprochenes).
Der Zeitstempel dient als Lebenszeichen: ist er älter als `MAX_AGE`, läuft kein Sprachdienst (`active: false`).
Der Leser vertraut der Datei nicht: unbekannte Zustände, falsche Typen oder alte Stempel ergeben "inaktiv"; ein ungültiger
Zähler oder Name ergibt 0 bzw. "" (alte Dateien ohne diese Felder bleiben gültig).
Feld `tts`: Zustand der Sprachausgabe (loading | ready | cpu | failed | off), für einen Chip der Oberfläche. Fehlt es oder ist es
ungültig, gilt "off".
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable

STATES = ("idle", "listening", "thinking", "speaking", "asking", "alarm", "halted")
TTS_STATES = ("loading", "ready", "cpu", "failed", "off")      # Sprachausgabe: lädt, GPU, Prozessor, ausgefallen, aus
FILE = Path("run") / "voice-state.json"
MAX_AGE = 5.0                      # Sekunden ohne Lebenszeichen = kein Sprachdienst
MIN_GAP = 0.2                      # höchstens 5 Schreibvorgänge pro Sekunde (Pegel und Lebenszeichen)
ALARM_SECONDS = 6.0                # so lange bleibt "alarm" nach einer abgelehnten Stimme sichtbar
MAX_FILE_BYTES = 4096              # die Datei ist winzig; Größeres liest der Leser gar nicht erst
MAX_WAKE_COUNT = 10 ** 9
WAKE_NAME = re.compile(r"^[a-z0-9äöüß][a-z0-9äöüß ._-]{0,39}$")     # Name eines Wake Words (kws oder openWakeWord)


def wake_name(raw: object) -> str:
    """Name eines erkannten Wake Words für Datei und Anzeige: klein, nur Buchstaben/Ziffern/Leerzeichen/._-, höchstens 40 Zeichen."""
    if not isinstance(raw, str):
        return ""
    name = " ".join(raw.strip().lower().split())[:40].strip()
    return name if WAKE_NAME.fullmatch(name) else ""


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
        self._last_level = 0.0
        self._wake_count = 0
        self._wake_last = ""
        self._tts = "off"
        self._lock = threading.Lock()                # Sprach-Schleife und Antwort-Thread schreiben dieselbe Datei

    def tts(self, state: str) -> None:
        """Zustand der Sprachausgabe (`KokoroWorker.on_state`); sofort schreiben, Unbekanntes wird "off"."""
        with self._lock:
            self._tts = state if state in TTS_STATES else "off"
        self._write(self._state(), self._last_level)

    def alarm(self) -> None:
        """Unbekannte Stimme: kurz "alarm" zeigen (keine Antwort, kein Ton)."""
        self._alarm_until = self._clock() + ALARM_SECONDS
        self._write(self._state(), 0.0)

    def wake(self, name: str = "") -> None:
        """Ein Wake Word wurde erkannt: Zähler erhöhen, Namen merken und sofort schreiben (Wake-Word-Test der Oberfläche)."""
        with self._lock:
            self._wake_count = min(MAX_WAKE_COUNT, self._wake_count + 1)
            self._wake_last = wake_name(name)
        self._write(self._state(), self._last_level)

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
        with self._lock:
            now = self._clock()
            level = round(min(1.0, max(0.0, float(level))), 3)
            data = {"state": state, "level": level, "ts": now,
                    "wake_count": self._wake_count, "wake_last": self._wake_last, "tts": self._tts}
            tmp = self._path.with_suffix(".tmp")
            try:
                self._path.parent.mkdir(exist_ok=True)
                tmp.write_text(json.dumps(data), encoding="utf-8")
                os.replace(tmp, self._path)
            except OSError:
                return                               # Anzeige ist nie wichtiger als der Betrieb
            self._last_state, self._last_write, self._last_level = state, now, level

    def clear(self) -> None:
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            pass


def _wake_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_WAKE_COUNT:
        return 0
    return value


def _wake_last(value: object) -> str:
    """Leser: nur ein Name, der genau der Form des Schreibers entspricht (nichts wird umgedeutet oder gekürzt)."""
    return value if isinstance(value, str) and WAKE_NAME.fullmatch(value) else ""


def _tts(value: object) -> str:
    return value if isinstance(value, str) and value in TTS_STATES else "off"


def read(root: Path, now: float | None = None) -> dict:
    """{"active", "state", "level", "wake_count", "wake_last", "tts"}; bei Fehlern oder alter Datei inaktiv."""
    off = {"active": False, "state": "idle", "level": 0.0, "wake_count": 0, "wake_last": "", "tts": "off"}
    try:
        with open(root / FILE, "rb") as f:
            raw = f.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            return off
        data = json.loads(raw.decode("utf-8"))
        state, level, ts = data["state"], data["level"], data["ts"]
        if (not isinstance(state, str) or state not in STATES or isinstance(level, bool) or not isinstance(level, (int, float))
                or isinstance(ts, bool) or not isinstance(ts, (int, float))
                or not math.isfinite(level) or not math.isfinite(ts)):
            return off
        if (time.time() if now is None else now) - ts > MAX_AGE:
            return off
        return {"active": True, "state": state, "level": min(1.0, max(0.0, float(level))),
                "wake_count": _wake_count(data.get("wake_count", 0)), "wake_last": _wake_last(data.get("wake_last", "")),
                "tts": _tts(data.get("tts", "off"))}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return off


def frame_level(frame, full_scale: float = 4000.0) -> float:
    """Pegel eines 16-bit-Frames 0..1 (RMS, auf einen typischen Sprechpegel bezogen). Nur die Zahl, kein Audio."""
    import numpy as np
    x = np.asarray(frame, dtype=np.int16).astype(np.float64)
    return float(min(1.0, np.sqrt(np.mean(x * x)) / full_scale)) if x.size else 0.0
