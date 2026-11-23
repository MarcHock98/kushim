"""Konfiguration. `memory.location` ist der einzige Ort, der den Speicherort kennt."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path



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
    path: Path | None = field(default=None, repr=False)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or config_path()
        if not path.exists():
            return cls(path=path)
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        mem, bak = data.get("memory", {}), data.get("backup", {})
        gpu = data.get("gpu", {})
        raw_folders = data.get("claude", {}).get("folders", [])
        folders = tuple(f for f in raw_folders if isinstance(f, str) and "|" in f) if isinstance(raw_folders, list) else ()
        audio = data.get("audio", {})
        audio = audio if isinstance(audio, dict) else {}
        return cls(
            memory_location=mem.get("location", cls.memory_location),
            backup_target=bak.get("target", ""),
            backup_keep=int(bak.get("keep", 10)),
            gpu_whisper=str(gpu.get("whisper", "auto")),
            claude_folders=folders,
            audio_mic=device_name(audio.get("mic", "")),
            audio_out=device_name(audio.get("out", "")),
            path=path,
        )

    def set_audio(self, mic: str, out: str) -> None:
        """Schreibt nur `mic` und `out` im Abschnitt [audio] ("" = Systemstandard); übrige Datei bleibt erhalten. Atomar."""
        import json
        for name in (mic, out):
            if not isinstance(name, str) or device_name(name) != name:
                raise ValueError("Ungültiger Gerätename")
        self._set_keys("audio", {"mic": "mic = " + json.dumps(mic, ensure_ascii=False),
                                 "out": "out = " + json.dumps(out, ensure_ascii=False)})
        self.audio_mic, self.audio_out = mic, out

    def _set_keys(self, section: str, entries: dict[str, str]) -> None:
        """Ersetzt bzw. ergänzt Zeilen `schlüssel = ...` in genau einem Abschnitt; atomar (Temp-Datei, dann ersetzen)."""
        path = self.path or config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        head = f"[{section}]"
        in_sec, done = False, set()
        for i, l in enumerate(lines):
            s = l.strip()
            if s.startswith("["):
                in_sec = s == head
                continue
            key = s.split("=", 1)[0].strip() if "=" in s else ""
            if in_sec and key in entries and key not in done:
                lines[i] = entries[key]
                done.add(key)
        missing = [entries[k] for k in entries if k not in done]
        if missing:
            heads = [l.strip() for l in lines]
            if head in heads:
                at = heads.index(head) + 1
                lines[at:at] = missing
            else:
                lines += ([""] if lines else []) + [head] + missing
        tmp = path.with_suffix(".toml.tmp")
        tmp.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
        os.replace(tmp, path)

    def set_claude_folders(self, entries: list[str]) -> None:
        """Schreibt nur `folders` im Abschnitt [claude] (Einträge "name|pfad"); übrige Datei bleibt erhalten. Atomar."""
        import json
        clean = []
        for e in entries:
            if not isinstance(e, str) or "|" not in e or any(c in e for c in (chr(10), chr(13))):
                raise ValueError(f"Ungültiger Ordner-Eintrag: {e!r}")
            clean.append(e)
        path = self.path or config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = "folders = [" + ", ".join(json.dumps(e, ensure_ascii=False) for e in clean) + "]"
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        in_sec, done = False, False
        for i, l in enumerate(lines):
            s = l.strip()
            if s.startswith("["):
                in_sec = s == "[claude]"
            elif in_sec and s.startswith("folders"):
                lines[i] = line
                done = True
        if not done:
            heads = [l.strip() for l in lines]
            if "[claude]" in heads:
                lines.insert(heads.index("[claude]") + 1, line)
            else:
                lines += ([""] if lines else []) + ["[claude]", line]
        tmp = path.with_suffix(".toml.tmp")
        tmp.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
        os.replace(tmp, path)
        self.claude_folders = tuple(clean)

    def set_memory_location(self, location: str) -> None:
        """Schreibt nur die Zeile `location` um; übrige Datei bleibt erhalten."""
        path = self.path or config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = f'location = "{location}"'
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()
            in_mem, done = False, False
            for i, l in enumerate(lines):
                s = l.strip()
                if s.startswith("["):
                    in_mem = s == "[memory]"
                elif in_mem and s.startswith("location"):
                    lines[i] = line
                    done = True
            if not done:
                lines = ["[memory]", line, ""] + lines
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            path.write_text(f"[memory]\n{line}\n", encoding="utf-8")
        self.memory_location = location
