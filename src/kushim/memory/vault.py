"""Vault = in sich geschlossener Ordner. Keine absoluten Pfade im Inhalt, daher kopierbar."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path

SCHEMA_VERSION = 1
MANIFEST = "manifest.json"
DB_FILE = "memory.db"
SUBDIRS = ("vectors", "episodes", "blobs")


@dataclass
class Manifest:
    vault_id: str
    schema_version: int = SCHEMA_VERSION
    embedding_model: str | None = None  # Vektoren sind neu berechenbar, wenn sich das ändert

    @classmethod
    def read(cls, root: Path) -> "Manifest":
        return cls(**json.loads((root / MANIFEST).read_text(encoding="utf-8")))

    def write(self, root: Path) -> None:
        (root / MANIFEST).write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


def is_vault(root: Path) -> bool:
    return (root / MANIFEST).exists()


def create_vault(root: Path) -> Manifest:
    root.mkdir(parents=True, exist_ok=True)
    if is_vault(root):
        raise FileExistsError(f"Vault existiert bereits: {root}")
    for d in SUBDIRS:
        (root / d).mkdir(exist_ok=True)
    m = Manifest(vault_id=uuid.uuid4().hex)
    m.write(root)
    return m


def parse_location(location: str) -> tuple[str, str]:
    """'local:C:/pfad' -> ('local', 'C:/pfad'); ohne Präfix gilt local."""
    scheme, sep, rest = location.partition(":")
    if sep and scheme in ("local", "remote") and not (len(scheme) == 1):
        return scheme, rest
    return "local", location


def resolve_local(path: str) -> Path:
    return Path(path).expanduser().resolve()
