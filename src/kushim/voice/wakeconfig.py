"""Zentrale Wake-Word-Konfiguration: EINE Datei für alle Wake Words (`wakewords.toml`).

- `wakewords.toml` (deine Datei, nicht im Git) hat Vorrang, sonst gilt `wakewords.example.toml`.
- Sprachbefehle ("Füge das Wake Word ... hinzu") ändern genau diese Datei, nach Bestätigung.
- Zwei Erkennungsarten:
    "kws"          beliebiges Wort/Wendung ohne Training (sherpa-onnx, offenes Vokabular)
    "openwakeword" vortrainierte Modelle (alexa, hey_jarvis, ...) oder eigene .onnx aus models/wakewords/
- Alles wird vor dem Laden und vor dem Speichern geprüft; Ungültiges wird nie verwendet.
"""
from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

from .trigger import PRETRAINED, resolve_wake_words

FILE = "wakewords.toml"
EXAMPLE = "wakewords.example.toml"
ENGINES = ("kws", "openwakeword")
MAX_WORDS = 12
_KWS_NAME = re.compile(r"^[a-zäöüß]+( [a-zäöüß]+){0,3}$")

DEFAULT_THRESHOLD = {"kws": 0.15, "openwakeword": 0.6}


@dataclass(frozen=True)
class WakeWord:
    name: str
    engine: str = "kws"
    enabled: bool = True
    threshold: float | None = None
    boost: float = 2.0

    @property
    def effective_threshold(self) -> float:
        return self.threshold if self.threshold is not None else DEFAULT_THRESHOLD[self.engine]


@dataclass(frozen=True)
class Settings:
    cooldown_seconds: float = 2.0
    listen_seconds: float = 4.0          # Wartezeit auf den Befehl, nachdem nur das Wake Word kam und "Ja?" gesagt wurde
    end_silence_seconds: float = 0.9     # so lange Stille beendet eine Äußerung (länger = Denkpausen erlaubt)
    max_seconds: float = 60.0            # längste einzelne Äußerung
    command_wait_seconds: float = 1.5    # direkt nach dem Wake Word: so lange auf den Befehl warten, bevor "Ja?" kommt
    follow_up_seconds: float = 8.0       # Gespräch: nach einer Antwort so lange ohne Wake Word zuhören (0 = aus)
    barge_in: bool = True                # Unterbrechen: Sprechen stoppt kushim sofort (Kopfhörer empfohlen)
    barge_in_level: float = 250.0        # Mikrofonpegel (0 bis 32767), ab dem es als Unterbrechen zählt; höher = unempfindlicher
    barge_in_ms: int = 240               # so lange muss der Pegel anhalten
    speech_level: float = 200.0          # Mikrofonpegel, ab dem es als Sprechen zählt (Beginn und Ende einer Äußerung)
    preroll_seconds: float = 1.0         # so viel Audio VOR dem Wake Word (nur im Speicher) kommt zum Befehl dazu


@dataclass(frozen=True)
class WakeConfig:
    settings: Settings = field(default_factory=Settings)
    words: tuple[WakeWord, ...] = tuple(WakeWord(n) for n in (
        "hey kushim", "kushim", "kush", "hallo kush", "hi kushim", "kushi"))

    def enabled(self) -> list[WakeWord]:
        return [w for w in self.words if w.enabled]


def normalize_name(name: str, engine: str) -> str:
    n = " ".join(name.strip().lower().split())
    return n if engine == "kws" else n.replace(" ", "_")


def validate(cfg: WakeConfig, root: Path) -> None:
    s = cfg.settings
    if not 0.5 <= s.cooldown_seconds <= 30 or not 2 <= s.listen_seconds <= 30:
        raise ValueError("cooldown_seconds muss 0,5 bis 30 und listen_seconds 2 bis 30 sein")
    if not 0.4 <= s.end_silence_seconds <= 5 or not 5 <= s.max_seconds <= 180:
        raise ValueError("end_silence_seconds muss 0,4 bis 5 und max_seconds 5 bis 180 sein")
    if not 0.5 <= s.command_wait_seconds <= 5:
        raise ValueError("command_wait_seconds muss 0,5 bis 5 sein")
    if s.follow_up_seconds != 0 and not 2 <= s.follow_up_seconds <= 120:
        raise ValueError("follow_up_seconds muss 0 (aus) oder 2 bis 120 sein")
    if not 50 <= s.speech_level <= 5000 or not 0 <= s.preroll_seconds <= 3:
        raise ValueError("speech_level muss 50 bis 5000 und preroll_seconds 0 bis 3 sein")
    if not 100 <= s.barge_in_level <= 20000 or not 100 <= s.barge_in_ms <= 2000:
        raise ValueError("barge_in_level muss 100 bis 20000 und barge_in_ms 100 bis 2000 sein")
    if not cfg.words or len(cfg.words) > MAX_WORDS:
        raise ValueError(f"1 bis {MAX_WORDS} Wake Words erlaubt")
    seen = set()
    for w in cfg.words:
        if w.engine not in ENGINES:
            raise ValueError(f"Unbekannte Engine {w.engine!r} (erlaubt: {', '.join(ENGINES)})")
        if w.name != normalize_name(w.name, w.engine):
            raise ValueError(f"Name nicht normalisiert: {w.name!r}")
        if w.engine == "kws":
            if not _KWS_NAME.match(w.name) or not 3 <= len(w.name) <= 40:
                raise ValueError(f"Ungültiges Wort {w.name!r}: nur Buchstaben und Leerzeichen, 3 bis 40 Zeichen")
        else:
            resolve_wake_words([w.name if w.name in PRETRAINED else w.name], root)
        if not 0.05 <= w.effective_threshold <= 0.95:
            raise ValueError(f"Schwelle für {w.name!r} außerhalb 0,05 bis 0,95")
        if not 0.5 <= w.boost <= 5.0:
            raise ValueError(f"boost für {w.name!r} außerhalb 0,5 bis 5")
        key = (w.engine, w.name)
        if key in seen:
            raise ValueError(f"Doppelt: {w.name!r}")
        seen.add(key)
    if not cfg.enabled():
        raise ValueError("Mindestens ein Wake Word muss aktiv sein")


def _parse(text: str) -> WakeConfig:
    data = tomllib.loads(text)
    st = data.get("settings", {})
    d = Settings()
    settings = Settings(float(st.get("cooldown_seconds", d.cooldown_seconds)),
                        float(st.get("listen_seconds", d.listen_seconds)),
                        float(st.get("end_silence_seconds", d.end_silence_seconds)),
                        float(st.get("max_seconds", d.max_seconds)),
                        float(st.get("command_wait_seconds", d.command_wait_seconds)),
                        float(st.get("follow_up_seconds", d.follow_up_seconds)),
                        bool(st.get("barge_in", d.barge_in)),
                        float(st.get("barge_in_level", d.barge_in_level)),
                        int(st.get("barge_in_ms", d.barge_in_ms)),
                        float(st.get("speech_level", d.speech_level)),
                        float(st.get("preroll_seconds", d.preroll_seconds)))
    words = []
    for e in data.get("wakeword", []):
        engine = str(e.get("engine", "kws"))
        words.append(WakeWord(
            name=normalize_name(str(e["name"]), engine), engine=engine, enabled=bool(e.get("enabled", True)),
            threshold=None if "threshold" not in e else float(e["threshold"]),
            boost=float(e.get("boost", 2.0))))
    return WakeConfig(settings, tuple(words))


def path(root: Path) -> Path:
    return root / FILE


def load(root: Path) -> WakeConfig:
    """Eigene Datei, sonst Beispiel, sonst eingebauter Standard. Ungültiges wirft ValueError."""
    for f in (root / FILE, root / EXAMPLE):
        if f.is_file():
            try:
                cfg = _parse(f.read_text(encoding="utf-8"))
            except (tomllib.TOMLDecodeError, KeyError, TypeError, ValueError) as e:
                raise ValueError(f"{f.name} ist fehlerhaft: {e}") from e
            validate(cfg, root)
            return cfg
    return WakeConfig()


HEADER = """# Zentrale Wake-Word-Konfiguration (wird auch von Sprachbefehlen geändert).
# engine = "kws":          beliebiges Wort ohne Training (Buchstaben/Leerzeichen). threshold: kleiner = empfindlicher.
# engine = "openwakeword": vortrainiert (alexa, hey_mycroft, hey_jarvis, hey_rhasspy, timer, weather)
#                          oder eigene .onnx-Datei aus models/wakewords/. threshold: Score 0..1, höher = strenger.
# Änderungen gelten ab dem nächsten Start von `kushim talk`.
"""


def dumps(cfg: WakeConfig) -> str:
    out = [HEADER, "[settings]",
           f"cooldown_seconds = {cfg.settings.cooldown_seconds}",
           f"listen_seconds = {cfg.settings.listen_seconds}",
           f"end_silence_seconds = {cfg.settings.end_silence_seconds}",
           f"max_seconds = {cfg.settings.max_seconds}",
           f"command_wait_seconds = {cfg.settings.command_wait_seconds}",
           f"follow_up_seconds = {cfg.settings.follow_up_seconds}",
           f"barge_in = {'true' if cfg.settings.barge_in else 'false'}",
           f"barge_in_level = {cfg.settings.barge_in_level}",
           f"barge_in_ms = {cfg.settings.barge_in_ms}",
           f"speech_level = {cfg.settings.speech_level}",
           f"preroll_seconds = {cfg.settings.preroll_seconds}", ""]
    for w in cfg.words:
        out += ["[[wakeword]]", f"name = {json.dumps(w.name, ensure_ascii=False)}",
                f"engine = {json.dumps(w.engine)}", f"enabled = {'true' if w.enabled else 'false'}"]
        if w.threshold is not None:
            out.append(f"threshold = {w.threshold}")
        if w.engine == "kws":
            out.append(f"boost = {w.boost}")
        out.append("")
    return "\n".join(out)


def save(root: Path, cfg: WakeConfig) -> None:
    """Prüft und schreibt `wakewords.toml` atomar (erst temporäre Datei, dann ersetzen)."""
    validate(cfg, root)
    text = dumps(cfg)
    _parse(text)                              # Gegenprobe: was wir schreiben, lässt sich wieder lesen
    target = path(root)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)


def from_names(names: list[str], root: Path) -> WakeConfig:
    """Für `--wake-words a,b`: bekannte Namen -> openwakeword, alles andere -> kws."""
    base = load(root)
    words = []
    for raw in names:
        n = raw.strip()
        if not n:
            continue
        eng = "openwakeword" if normalize_name(n, "openwakeword") in PRETRAINED or n.endswith(".onnx") else "kws"
        words.append(WakeWord(normalize_name(n, eng), eng))
    cfg = replace(base, words=tuple(words))
    validate(cfg, root)
    return cfg
