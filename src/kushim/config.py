"""Konfiguration. `memory.location` ist der einzige Ort, der den Speicherort kennt."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


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
    path: Path | None = field(default=None, repr=False)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or config_path()
        if not path.exists():
            return cls(path=path)
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        mem, bak, priv = data.get("memory", {}), data.get("backup", {}), data.get("privacy", {})
        return cls(
            memory_location=mem.get("location", cls.memory_location),
            backup_target=bak.get("target", ""),
            backup_keep=int(bak.get("keep", 10)),
            claude_enabled=bool(priv.get("claude_enabled", False)),
            path=path,
        )

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
