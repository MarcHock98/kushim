"""Konfiguration. `memory.location` ist der einzige Ort, der den Speicherort kennt."""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .llm.ollama import DEFAULT_MODEL, validate_model

TOOL_NAME = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)?")      # z. B. "web.search"


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
        return cls(
            memory_location=mem.get("location", cls.memory_location),
            backup_target=bak.get("target", ""),
            backup_keep=int(bak.get("keep", 10)),
            claude_enabled=bool(priv.get("claude_enabled", False)),
            llm_model=validate_model(str(llm.get("model", DEFAULT_MODEL))),
            gpu_whisper=str(gpu.get("whisper", "auto")),
            gpu_llm=str(gpu.get("llm", "auto")),
            tools_enabled=tools,
            path=path,
        )

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
