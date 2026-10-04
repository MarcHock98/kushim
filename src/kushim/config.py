"""Konfiguration. `memory.location` ist der einzige Ort, der den Speicherort kennt."""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .llm.ollama import DEFAULT_MODEL, validate_model

TOOL_NAME = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)?")      # z. B. "web.search"


class LiveConfig:
    """Liest `config.toml` höchstens alle `ttl` Sekunden neu. Für lange laufende Gespräche: Schaltet der Nutzer in einem anderen Fenster
    ein Werkzeug oder Modus C um, gilt das ohne Neustart (zu einem Zeitpunkt, den der Nutzer sieht, nie durch Sprache oder das LLM)."""

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
    claude_enabled: bool = False
    llm_model: str = DEFAULT_MODEL
    gpu_whisper: str = "auto"      # "auto", "cpu" oder Kartennummer (kushim gpu)
    gpu_llm: str = "auto"          # "auto", "all" oder Nummern wie "0,1"
    tools_enabled: tuple[str, ...] = ()   # nur diese Werkzeuge sind aktiv (Standard: keines); ändert nur der Nutzer
    voice_direct: bool = True             # [tools] direct: gesprochener Befehl gilt als Freigabe für Recherche/Claude-Start (kein zweites "ja"); false = immer Vorschau und "ja"
    claude_folders: tuple[str, ...] = ()  # freigegebene Ordner für Claude als "name|pfad"; ändert nur der Nutzer (UI/CLI)
    path: Path | None = field(default=None, repr=False)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or config_path()
        if not path.exists():
            return cls(path=path)
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        mem, bak, priv = data.get("memory", {}), data.get("backup", {}), data.get("privacy", {})
        llm = data.get("llm", {})
        gpu = data.get("gpu", {})
        raw_tools = data.get("tools", {}).get("enabled", [])
        tools = tuple(t for t in raw_tools if isinstance(t, str) and TOOL_NAME.fullmatch(t)) if isinstance(raw_tools, list) else ()
        raw_folders = data.get("claude", {}).get("folders", [])
        folders = tuple(f for f in raw_folders if isinstance(f, str) and "|" in f) if isinstance(raw_folders, list) else ()
        return cls(
            memory_location=mem.get("location", cls.memory_location),
            backup_target=bak.get("target", ""),
            backup_keep=int(bak.get("keep", 10)),
            claude_enabled=bool(priv.get("claude_enabled", False)),
            llm_model=validate_model(str(llm.get("model", DEFAULT_MODEL))),
            gpu_whisper=str(gpu.get("whisper", "auto")),
            gpu_llm=str(gpu.get("llm", "auto")),
            tools_enabled=tools,
            voice_direct=bool(data.get("tools", {}).get("direct", True)),
            claude_folders=folders,
            path=path,
        )

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

    def set_claude_enabled(self, on: bool) -> None:
        """Schreibt nur `claude_enabled` im Abschnitt [privacy] (Modus C); übrige Datei bleibt erhalten. Atomar."""
        path = self.path or config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = f"claude_enabled = {'true' if on else 'false'}"
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        in_priv, done = False, False
        for i, l in enumerate(lines):
            s = l.strip()
            if s.startswith("["):
                in_priv = s == "[privacy]"
            elif in_priv and s.startswith("claude_enabled"):
                lines[i] = line
                done = True
        if not done:
            heads = [l.strip() for l in lines]
            if "[privacy]" in heads:
                lines.insert(heads.index("[privacy]") + 1, line)
            else:
                lines += ([""] if lines else []) + ["[privacy]", line]
        tmp = path.with_suffix(".toml.tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        self.claude_enabled = on

    def set_tools_enabled(self, names: list[str]) -> None:
        """Schreibt nur `enabled` im Abschnitt [tools]; übrige Datei bleibt erhalten. Ungültige Namen: ValueError."""
        clean = sorted({n for n in names})
        for n in clean:
            if not isinstance(n, str) or not TOOL_NAME.fullmatch(n):
                raise ValueError(f"Ungültiger Werkzeugname: {n!r}")
        path = self.path or config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = "enabled = [" + ", ".join(f'"{n}"' for n in clean) + "]"
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        in_tools, done = False, False
        for i, l in enumerate(lines):
            s = l.strip()
            if s.startswith("["):
                in_tools = s == "[tools]"
            elif in_tools and s.startswith("enabled"):
                lines[i] = line
                done = True
        if not done:
            heads = [l.strip() for l in lines]
            if "[tools]" in heads:
                lines.insert(heads.index("[tools]") + 1, line)
            else:
                lines += ([""] if lines else []) + ["[tools]", line]
        tmp = path.with_suffix(".toml.tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, path)                     # atomar
        self.tools_enabled = tuple(clean)

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

    def set_llm_model(self, model: str) -> None:
        """Schreibt nur `model` im Abschnitt [llm]; übrige Datei bleibt erhalten."""
        model = validate_model(model)
        path = self.path or config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = f'model = "{model}"'
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        in_llm, done = False, False
        for i, l in enumerate(lines):
            s = l.strip()
            if s.startswith("["):
                in_llm = s == "[llm]"
            elif in_llm and s.startswith("model"):
                lines[i] = line
                done = True
        if not done:
            heads = [l.strip() for l in lines]
            if "[llm]" in heads:
                lines.insert(heads.index("[llm]") + 1, line)
            else:
                lines += ([""] if lines else []) + ["[llm]", line]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.llm_model = model
