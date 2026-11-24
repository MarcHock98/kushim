"""Konfiguration. `memory.location` ist der einzige Ort, der den Speicherort kennt."""
from __future__ import annotations

import os
import sys
import re
import threading
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_LOCK = threading.RLock()        # jeder Schreiber von config.toml (UI-Threads, CLI) hält sie für Lesen-Ändern-Schreiben
_TABLE_HEAD = re.compile(r"^\s*\[\s*([A-Za-z0-9_-]+)\s*\]\s*(#.*)?$")      # [abschnitt], auch [ abschnitt ] # Kommentar


class NotSaved(Exception):
    """config.toml wurde NICHT geändert (Gegenprobe gescheitert oder Datei fehlerhaft)."""



class LiveConfig:
    """Liest `config.toml` höchstens alle `ttl` Sekunden neu. Für lange laufende Gespräche: Schaltet der Nutzer in einem anderen Fenster
    einen Ordner oder die Grafikkarte um, gilt das ohne Neustart (zu einem Zeitpunkt, den der Nutzer sieht, nie durch Sprache oder das LLM)."""

    def __init__(self, ttl: float = 2.0, loader=None, clock=None):
        import time
        self._ttl, self._clock = ttl, clock or time.monotonic
        self._loader = loader or Config.load
        self._cfg: "Config | None" = None
        self._at = 0.0

    def get(self) -> "Config":
        now = self._clock()
        if self._cfg is None or now - self._at >= self._ttl:
            try:
                self._cfg, self._at = self._loader(), now
            except Exception:                              # kaputte Datei: den letzten guten Stand behalten (nie "alles an")
                if self._cfg is None:
                    self._cfg = Config()
                self._at = now
        return self._cfg

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self.get(), name)


MAX_DEVICE_NAME = 200


def device_name(value: object) -> str:
    """Gerätename aus der Konfiguration: nur Text ohne Steuerzeichen, höchstens 200 Zeichen, sonst "" (Systemstandard)."""
    if not isinstance(value, str) or len(value) > MAX_DEVICE_NAME or not all(c.isprintable() for c in value):
        return ""
    return value


def config_path() -> Path:
    env = os.environ.get("KUSHIM_CONFIG")
    if env:
        return Path(env)
    local = Path("config.toml")
    if local.exists():
        return local
    if sys.platform == "darwin" and not os.environ.get("APPDATA"):
        return Path.home() / "Library" / "Application Support" / "kushim" / "config.toml"
    return Path(os.environ.get("APPDATA", Path.home())) / "kushim" / "config.toml"


@dataclass
class Config:
    memory_location: str = "local:~/kushim-vault"
    backup_target: str = ""
    backup_keep: int = 10
    gpu_whisper: str = "auto"      # "auto", "cpu" oder Kartennummer (kushim gpu)
    claude_folders: tuple[str, ...] = ()  # freigegebene Ordner für Claude als "name|pfad"; ändert nur der Nutzer (UI/CLI)
                                          # (Entscheidung des Nutzers 2026-11-11); ohne Prüfung keine Freigaben per Stimme.
    audio_mic: str = ""            # gemerktes Mikrofon ([audio] mic), "" = Systemstandard; `--mic` hat Vorrang (E3b)
    audio_out: str = ""            # gemerktes Ausgabegerät ([audio] out), "" = Systemstandard; `--out` hat Vorrang
    claude_model: str = "sonnet"   # Modell der kushim-Sitzung (--model); "" = Standard von Claude Code. Geprüft in channel/launch.py
    claude_effort: str = "high"    # Aufwand (--effort); "" = Standard von Claude Code
    path: Path | None = field(default=None, repr=False)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or config_path()
        if not path.exists():
            return cls(path=path)
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        mem, bak = data.get("memory", {}), data.get("backup", {})
        gpu = data.get("gpu", {})
        claude = data.get("claude", {}) if isinstance(data.get("claude", {}), dict) else {}
        raw_folders = claude.get("folders", [])
        folders = tuple(f for f in raw_folders if isinstance(f, str) and "|" in f) if isinstance(raw_folders, list) else ()
        audio = data.get("audio", {})
        audio = audio if isinstance(audio, dict) else {}
        model, effort = claude.get("model", cls.claude_model), claude.get("effort", cls.claude_effort)
        return cls(
            memory_location=mem.get("location", cls.memory_location),
            backup_target=bak.get("target", ""),
            backup_keep=int(bak.get("keep", 10)),
            gpu_whisper=str(gpu.get("whisper", "auto")),
            claude_folders=folders,
            audio_mic=device_name(audio.get("mic", "")),
            audio_out=device_name(audio.get("out", "")),
            claude_model=model.strip().lower() if isinstance(model, str) else repr(model),      # kein Text: fällt bei der Prüfung durch
            claude_effort=effort.strip().lower() if isinstance(effort, str) else repr(effort),
            path=path,
        )

    def set_audio(self, mic: str, out: str) -> None:
        """Schreibt nur `mic` und `out` im Abschnitt [audio] ("" = Systemstandard); übrige Datei bleibt erhalten. Atomar."""
        for name in (mic, out):
            if not isinstance(name, str) or device_name(name) != name:
                raise ValueError("Ungültiger Gerätename")
        self._set_keys("audio", {"mic": mic, "out": out})
        self.audio_mic, self.audio_out = mic, out

    def set_claude_folders(self, entries: list[str]) -> None:
        """Schreibt nur `folders` im Abschnitt [claude] (Einträge "name|pfad"); übrige Datei bleibt erhalten. Atomar."""
        clean = []
        for e in entries:
            if not isinstance(e, str) or "|" not in e or any(c in e for c in (chr(10), chr(13))):
                raise ValueError(f"Ungültiger Ordner-Eintrag: {e!r}")
            clean.append(e)
        self._set_keys("claude", {"folders": clean})
        self.claude_folders = tuple(clean)

    def set_memory_location(self, location: str) -> None:
        """Schreibt nur `location` im Abschnitt [memory]; übrige Datei bleibt erhalten. Atomar."""
        if not isinstance(location, str) or any(c in location for c in (chr(10), chr(13))):
            raise ValueError("Ungültiger Speicherort")
        self._set_keys("memory", {"location": location})
        self.memory_location = location

    def _set_keys(self, section: str, values: dict[str, object]) -> None:
        """Setzt Schlüssel in genau einem Abschnitt `[section]`; alles andere bleibt Zeichen für Zeichen erhalten.

        Gegenprobe vor dem Ersetzen (Safety-Audit E3, M1): Der neue Text wird mit `tomllib` gelesen und muss genau der alte
        Inhalt plus die gewünschten Werte sein. Sonst (Abschnitt als Inline-Tabelle oder gepunktete Schlüssel, Schlüssel in
        einem mehrzeiligen Text, kaputte Datei) wird NICHTS geschrieben (`NotSaved`). Alle Schreiber von config.toml halten
        `CONFIG_LOCK` (lesen, ändern, schreiben als Einheit) und schreiben über eine eigene Temp-Datei, dann `os.replace`."""
        import copy
        import json
        path = self.path or config_path()
        entries = {k: f"{k} = {json.dumps(v, ensure_ascii=False)}" for k, v in values.items()}
        with CONFIG_LOCK:
            old_text = path.read_text(encoding="utf-8") if path.exists() else ""
            try:
                old = tomllib.loads(old_text)
            except tomllib.TOMLDecodeError as e:
                raise NotSaved("config.toml ist fehlerhaft") from e
            lines = old_text.splitlines()
            current, head_at, done = None, None, set()
            for i, line in enumerate(lines):
                m = _TABLE_HEAD.match(line)
                if m:
                    current = m.group(1)
                    if current == section and head_at is None:
                        head_at = i
                    continue
                if line.lstrip().startswith("["):              # Array-Tabelle, Untertabelle o. ä.: kein bekannter Abschnitt
                    current = None
                    continue
                key = line.split("=", 1)[0].strip() if "=" in line else ""
                if current == section and key in entries and key not in done:
                    lines[i] = entries[key]
                    done.add(key)
            missing = [entries[k] for k in entries if k not in done]
            if missing:
                if head_at is not None:
                    lines[head_at + 1:head_at + 1] = missing
                else:
                    lines += ([""] if lines else []) + [f"[{section}]"] + missing
            new_text = chr(10).join(lines) + chr(10)
            expected = copy.deepcopy(old)
            table = expected.setdefault(section, {})
            if not isinstance(table, dict):
                raise NotSaved("Abschnitt ist keine Tabelle")
            table.update(values)
            try:
                if tomllib.loads(new_text) != expected:
                    raise NotSaved("Gegenprobe passt nicht")
            except tomllib.TOMLDecodeError as e:
                raise NotSaved("Gegenprobe nicht lesbar") from e
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            try:
                tmp.write_text(new_text, encoding="utf-8")
                os.replace(tmp, path)
            finally:
                tmp.unlink(missing_ok=True)
