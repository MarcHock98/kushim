"""Mikrofon-Schwellen, die sich zur Laufzeit ändern lassen (Oberfläche, Sprachbefehl), ohne `kushim talk` neu zu starten.

`LiveTuning` hält die vier Werte, die Collector (`voice/audio.py`) und Unterbrechen (`voice/bargein.py`) bei JEDEM Frame lesen:
- `speech_level`         Pegel, ab dem es als Sprechen zählt (Beginn und Ende einer Äußerung),
- `barge_in_level`       Pegel, ab dem es als Unterbrechen zählt,
- `barge_in_ms`          so lange muss dieser Pegel anhalten,
- `end_silence_seconds`  so lange Stille beendet eine Äußerung.
Eine Änderung wirkt deshalb ab dem nächsten Frame, auch mitten in einer Äußerung.

Grenzen: `set` und `step_by` halten die LIVE-GRENZEN (`BOUNDS`) ein, sonst ValueError bzw. Begrenzung. Die Startwerte aus
`wakewords.toml` gelten unverändert, auch wenn sie außerhalb liegen (die Datei prüft `wakeconfig.validate` mit eigenen Grenzen).
Sicherheit: Auch an der strengsten Grenze (speech 600, barge 1500 über 400 ms) lösen normal laut gesprochene Frames (RMS um
2000) Äußerung und Unterbrechen noch aus; ein gesprochenes „Notaus“ kommt also durch (tests/test_tuning.py). Das gilt auch
mit Echo-Schutz, während kushim spricht: dessen erhöhte Schwelle ist auf `bargein.ECHO_CAP` (= 1500, die Live-Obergrenze)
gedeckelt. Die Sperrzeit am Anfang der ersten Wiedergabe einer Runde (`echo_ignore_ms`) bleibt; dafür gibt es die
Notaus-Verknüpfung. `voice.level_apply` übernimmt Werte live nur begrenzt auf diese Grenzen (`adopt_file(clamp=True)`).

Stufen (`step_by`, Sprachbefehl „Mikrofon empfindlicher“): Faktor 1,4 je Stufe auf `speech_level` und `barge_in_level`,
ausgehend von den Dateiwerten, -2..+2. Plus heißt EMPFINDLICHER, also niedrigere Schwellen. Ein Wert wird an die Grenzen
gebunden, aber nie in die falsche Richtung (ein Dateiwert unter der Grenze wird bei „empfindlicher“ nicht angehoben).

`observe(rms)`: letzter Pegel (RMS) und Spitze der letzten Sekunde für die Anzeige. Nur Zahlen, nie Audio.
Alles unter einer Sperre; `version` zählt jede Änderung. `on_change(snapshot)` (optional, z. B. talk.log) wird nach einer
Änderung außerhalb der Sperre aufgerufen; Fehler darin stören nie.
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, replace
from typing import Any, Callable

KEYS = ("speech_level", "barge_in_level", "barge_in_ms", "end_silence_seconds")
BOUNDS: dict[str, tuple[float, float]] = {
    "speech_level": (80.0, 600.0),
    "barge_in_level": (150.0, 1500.0),
    "barge_in_ms": (160, 400),
    "end_silence_seconds": (0.6, 3.0),
}
STEP_MIN, STEP_MAX = -2, 2
STEP_FACTOR = 1.4
SOURCES = ("ui", "voice", "file")
PEAK_WINDOW = 1.0                  # Sekunden: Spitze der letzten Sekunde


@dataclass(frozen=True)
class TuningValues:
    speech_level: float = 200.0
    barge_in_level: float = 250.0
    barge_in_ms: int = 240
    end_silence_seconds: float = 0.9

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _number(key: str, value: Any) -> float | int:
    """Prüft Typ und Grenze eines Live-Werts; ValueError sonst. `barge_in_ms` muss ganzzahlig sein."""
    if key not in BOUNDS:
        raise ValueError(f"unbekannter Wert {key!r}")
    if not _finite(value):
        raise ValueError(f"{key} muss eine Zahl sein")
    lo, hi = BOUNDS[key]
    if not lo <= value <= hi:
        raise ValueError(f"{key} muss {lo:g} bis {hi:g} sein")
    if key == "barge_in_ms":
        if float(value) != int(value):
            raise ValueError("barge_in_ms muss ganzzahlig sein")
        return int(value)
    return float(value)


def _finite(value: Any) -> bool:
    """Endliche Zahl (int/float, kein bool). Riesige Ganzzahlen (OverflowError bei der Umwandlung) zählen nicht."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _clamp(key: str, value: float) -> float:
    lo, hi = BOUNDS[key]
    return float(min(hi, max(lo, value)))


class LiveTuning:
    def __init__(self, file_values: TuningValues | None = None, clock: Callable[[], float] = time.monotonic):
        self._lock = threading.Lock()
        self._clock = clock
        self._file = file_values or TuningValues()
        self._values = self._file            # unveränderlich: Leser im Frame-Pfad bekommen immer ein ganzes Paket
        self._step = 0
        self._source = "file"
        self._version = 0
        self._rms = 0.0
        self._recent: deque[tuple[float, float]] = deque(maxlen=64)
        self.on_change: Callable[[dict[str, Any]], None] | None = None

    @classmethod
    def from_settings(cls, settings: Any, clock: Callable[[], float] = time.monotonic) -> "LiveTuning":
        """Aus `wakeconfig.Settings`; die Dateiwerte gelten unverändert als Start (auch außerhalb der Live-Grenzen)."""
        return cls(TuningValues(float(settings.speech_level), float(settings.barge_in_level), int(settings.barge_in_ms),
                                float(settings.end_silence_seconds)), clock=clock)

    # --- Lesen (Frame-Pfad): ein Attributzugriff auf ein unveränderliches Objekt, keine Sperre nötig
    @property
    def values(self) -> TuningValues:
        return self._values

    @property
    def version(self) -> int:
        return self._version

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot()

    def _snapshot(self) -> dict[str, Any]:
        return {"version": self._version, "values": self._values.as_dict(), "file_values": self._file.as_dict(),
                "step": self._step, "source": self._source, "rms": round(self._rms, 1), "peak": round(self._peak(), 1)}

    # --- Ändern
    def set(self, source: str = "ui", **values: Any) -> dict[str, Any]:
        """Setzt einzelne Werte (geprüft gegen `BOUNDS`, alles oder nichts). ValueError bei Unbekanntem oder außerhalb.
        Die Stufe bleibt, wie sie ist (sie ändert sich nur über `step_by`/`reset`)."""
        self._check_source(source)
        if not values:
            raise ValueError("keine Werte")
        clean = {k: _number(k, v) for k, v in values.items()}
        with self._lock:
            self._values = replace(self._values, **clean)
            snap = self._changed(source)
        self._notify(snap)
        return snap

    def step_by(self, delta: int, source: str = "voice") -> int:
        """Eine Stufe empfindlicher (+1) oder weniger empfindlich (-1). Gibt die neue Stufe zurück; an der Grenze (-2/+2)
        bleibt alles, wie es ist (keine Änderung, keine neue Version)."""
        self._check_source(source)
        if delta not in (-1, 1):
            raise ValueError("step_by nimmt nur +1 oder -1")
        with self._lock:
            step = max(STEP_MIN, min(STEP_MAX, self._step + delta))
            if step == self._step:
                return step
            self._step = step
            self._values = replace(self._values, speech_level=self._stepped("speech_level", step),
                                   barge_in_level=self._stepped("barge_in_level", step))
            snap = self._changed(source)
        self._notify(snap)
        return step

    def _stepped(self, key: str, step: int) -> float:
        base = float(getattr(self._file, key))
        if step == 0:
            return base
        value = _clamp(key, base / STEP_FACTOR ** step)      # empfindlicher = niedrigere Schwelle
        return round(min(base, value) if step > 0 else max(base, value), 1)    # nie in die falsche Richtung

    def reset(self, source: str = "ui") -> dict[str, Any]:
        """Zurück auf die Dateiwerte, Stufe 0."""
        self._check_source(source)
        with self._lock:
            self._values, self._step = self._file, 0
            snap = self._changed(source)
        self._notify(snap)
        return snap

    def adopt_file(self, source: str = "ui", expect_version: int | None = None, clamp: bool = False,
                   **values: Any) -> dict[str, Any] | None:
        """Nach dem Speichern in `wakewords.toml` (schon von `wakeconfig.validate` geprüft): die gespeicherten Werte werden die
        neue Bezugsgröße für `reset`/Stufen (`file_values`) UND die aktuellen Werte, Stufe 0.
        `clamp`: live nur innerhalb der Live-Grenzen übernehmen (`voice.level_apply`; die Datei behält die Werte).
        `expect_version`: nur übernehmen, wenn sich seitdem nichts geändert hat; sonst bleibt der neuere Live-Stand und das
        Ergebnis ist None."""
        self._check_source(source)
        clean: dict[str, Any] = {}
        for k, v in values.items():
            if k not in KEYS or not _finite(v):
                raise ValueError(f"ungültiger Wert {k!r}")
            v = _clamp(k, float(v)) if clamp else v
            clean[k] = int(round(v)) if k == "barge_in_ms" else float(v)
        with self._lock:
            if expect_version is not None and expect_version != self._version:
                return None
            self._file = replace(self._file, **clean)
            self._values = replace(self._values, **clean)
            self._step = 0
            snap = self._changed(source)
        self._notify(snap)
        return snap

    def _changed(self, source: str) -> dict[str, Any]:
        self._source = source
        self._version += 1
        return self._snapshot()

    def _notify(self, snap: dict[str, Any]) -> None:
        cb = self.on_change
        if cb is None:
            return
        try:
            cb(snap)
        except Exception:                            # noqa: BLE001 (Protokoll/Anzeige darf den Betrieb nie stören)
            pass

    @staticmethod
    def _check_source(source: str) -> None:
        if source not in SOURCES:
            raise ValueError(f"unbekannte Quelle {source!r}")

    # --- Pegel für die Anzeige (nur Zahlen)
    def observe(self, rms: float) -> None:
        try:
            r = float(rms)
        except (TypeError, ValueError, OverflowError):
            return
        if not math.isfinite(r) or r < 0:
            return
        now = self._clock()
        with self._lock:
            self._rms = r
            self._recent.append((now, r))

    def _peak(self) -> float:
        limit = self._clock() - PEAK_WINDOW
        while self._recent and self._recent[0][0] < limit:
            self._recent.popleft()
        return max((r for _, r in self._recent), default=0.0)

    def levels(self) -> tuple[float, float]:
        """(letzter RMS, Spitze der letzten Sekunde)."""
        with self._lock:
            return round(self._rms, 1), round(self._peak(), 1)


def bounds() -> dict[str, dict[str, float]]:
    """Live-Grenzen für die API: {name: {min, max}} inklusive der Stufe."""
    out: dict[str, dict[str, float]] = {k: {"min": lo, "max": hi} for k, (lo, hi) in BOUNDS.items()}
    out["step"] = {"min": STEP_MIN, "max": STEP_MAX}
    return out
