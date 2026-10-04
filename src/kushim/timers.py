"""Lokale Timer und Erinnerungen: nur Zeit und ein kurzer Text, gespeichert in `run/timers.json`. Kein Netz, keine Außenwirkung.

Grenzen (gegen Missbrauch und Unfälle): höchstens 20 gleichzeitige Timer, höchstens 7 Tage Vorlauf, Text höchstens 80 Zeichen ohne Steuerzeichen.
Die Datei enthält nur Zahlen und diesen Kurztext; sie liegt neben dem Rest des Laufzeit-Zustands und wird atomar geschrieben.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

MAX_TIMERS = 20
MAX_SECONDS = 7 * 24 * 3600
MAX_LABEL = 80
FILE = "run/timers.json"


class TimerError(Exception):
    pass


@dataclass
class Timer:
    id: str
    due: float                  # Unix-Zeit
    label: str = ""
    created: float = 0.0


def clean_label(text: str) -> str:
    t = "".join(ch if ch.isprintable() else " " for ch in str(text))
    return " ".join(t.split())[:MAX_LABEL]


class TimerStore:
    def __init__(self, root: Path, clock: Callable[[], float] = time.time):
        self.path, self.clock = Path(root) / FILE, clock

    def _load(self) -> list[Timer]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        out = []
        for d in raw if isinstance(raw, list) else []:
            if isinstance(d, dict) and isinstance(d.get("due"), (int, float)) and isinstance(d.get("id"), str):
                out.append(Timer(d["id"][:16], float(d["due"]), clean_label(d.get("label", "")), float(d.get("created", 0) or 0)))
        return out[:MAX_TIMERS]

    def _save(self, timers: list[Timer]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(t) for t in timers]), encoding="utf-8")
        os.replace(tmp, self.path)

    def add(self, seconds: float, label: str = "") -> Timer:
        if not (0 < seconds <= MAX_SECONDS):
            raise TimerError("Die Dauer muss zwischen einer Sekunde und sieben Tagen liegen.")
        timers = self._load()
        if len(timers) >= MAX_TIMERS:
            raise TimerError(f"Es laufen schon {MAX_TIMERS} Timer.")
        now = self.clock()
        t = Timer(uuid.uuid4().hex[:8], now + seconds, clean_label(label), now)
        self._save(sorted(timers + [t], key=lambda x: x.due))
        return t

    def list(self) -> list[Timer]:
        return sorted(self._load(), key=lambda x: x.due)

    def cancel_all(self) -> int:
        n = len(self._load())
        self._save([])
        return n

    def cancel_next(self) -> Timer | None:
        timers = self.list()
        if not timers:
            return None
        self._save(timers[1:])
        return timers[0]

    def take_due(self) -> list[Timer]:
        """Abgelaufene Timer, einmalig (werden dabei entfernt)."""
        now = self.clock()
        timers = self._load()
        due = [t for t in timers if t.due <= now]
        if due:
            self._save([t for t in timers if t.due > now])
        return sorted(due, key=lambda x: x.due)


# --- Dauer aus gesprochenem Deutsch ----------------------------------------------------------------

_WORDS = {"null": 0, "ein": 1, "eine": 1, "einen": 1, "einer": 1, "eins": 1, "zwei": 2, "drei": 3, "vier": 4, "funf": 5, "fuenf": 5, "sechs": 6,
          "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "elf": 11, "zwolf": 12, "zwoelf": 12, "dreizehn": 13, "vierzehn": 14, "funfzehn": 15,
          "fuenfzehn": 15, "sechzehn": 16, "siebzehn": 17, "achtzehn": 18, "neunzehn": 19, "zwanzig": 20, "dreissig": 30, "dreibig": 30,
          "vierzig": 40, "funfzig": 50, "fuenfzig": 50, "sechzig": 60, "neunzig": 90, "hundert": 100}
_UNITS = {"sekunde": 1, "sekunden": 1, "sek": 1, "minute": 60, "minuten": 60, "min": 60, "stunde": 3600, "stunden": 3600, "std": 3600,
          "tag": 86400, "tage": 86400, "tagen": 86400}


def _fold(w: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", w.lower()).encode("ascii", "ignore").decode()


def parse_duration(text: str) -> tuple[float | None, str]:
    """Sekunden aus "10 Minuten", "eine halbe Stunde", "anderthalb Stunden", "1 Stunde 30 Minuten", "zwei Minuten dreißig".
    Gibt (Sekunden oder None, Rest des Textes ohne die Zeitangabe) zurück."""
    toks = re.findall(r"[\wäöüÄÖÜß]+(?:[.,]\d+)?", text)
    total, used, i = 0.0, [False] * len(toks), 0
    found = False
    while i < len(toks):
        w = _fold(toks[i])
        val: float | None = None
        j = i
        if w in ("halbe", "halben", "halbes") and i + 1 < len(toks) and _fold(toks[i + 1]) in _UNITS:
            val, j = 0.5, i
            unit = _UNITS[_fold(toks[i + 1])]
            total += 0.5 * unit
            used[i] = used[i + 1] = True
            found, i = True, i + 2
            continue
        if w in ("anderthalb", "eineinhalb"):
            if i + 1 < len(toks) and _fold(toks[i + 1]) in _UNITS:
                total += 1.5 * _UNITS[_fold(toks[i + 1])]
                used[i] = used[i + 1] = True
                found, i = True, i + 2
                continue
        num = None
        if re.fullmatch(r"\d+(?:[.,]\d+)?", w):
            num = float(w.replace(",", "."))
        elif w in _WORDS:
            num = float(_WORDS[w])
        elif "und" in w:                                           # "fünfundzwanzig"
            a, _, b = w.partition("und")
            if a in _WORDS and b in _WORDS and _WORDS[b] >= 20:
                num = float(_WORDS[a] + _WORDS[b])
        if num is not None and i + 1 < len(toks) and _fold(toks[i + 1]) in _UNITS:
            nxt = i + 2
            total += num * _UNITS[_fold(toks[i + 1])]
            used[i] = used[i + 1] = True
            found, i = True, nxt
            # "eine Stunde und eine halbe"/"zwei Minuten dreißig" bleibt bewusst einfach: weitere Einheiten werden addiert
            continue
        i += 1
    rest = " ".join(t for t, u in zip(toks, used) if not u)
    return (total if found and total > 0 else None), rest
