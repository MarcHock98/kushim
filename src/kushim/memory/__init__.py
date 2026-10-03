"""Einstieg: open_store() liest den Ort aus der Config und liefert das passende Backend."""
from __future__ import annotations

from ..config import Config
from .store import Fact, MemoryStore
from .vault import parse_location, resolve_local

__all__ = ["open_store", "Fact", "MemoryStore"]


def open_store(config: Config | None = None, create: bool = False) -> MemoryStore:
    config = config or Config.load()
    scheme, rest = parse_location(config.memory_location)
    if scheme == "local":
        from .local import LocalStore
        return LocalStore(resolve_local(rest), create=create)
    if scheme == "remote":
        raise NotImplementedError("Remote-Backend (NAS-Dienst) folgt; Ort ist bereits konfigurierbar.")
    raise ValueError(f"Unbekannter Speicherort: {config.memory_location}")
