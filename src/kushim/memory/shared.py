"""Ein Vault-Zugriff, den mehrere Threads benutzen dürfen (z. B. die API des Sprachprozesses).

SQLite-Verbindungen gehören dem Thread, der sie angelegt hat. Die API läuft aber in Hintergrund-Threads. `SharedStore`
umhüllt einen `MemoryStore` und führt jeden Aufruf unter einer Sperre aus (nacheinander, nie gleichzeitig).
"""
from __future__ import annotations

import threading
from typing import Any

from .store import MemoryStore


class SharedStore:
    def __init__(self, store: MemoryStore):
        self._store = store
        self._lock = threading.RLock()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        attr = getattr(self._store, name)
        if not callable(attr):
            return attr

        def locked(*args: Any, **kwargs: Any) -> Any:
            with self._lock:
                return attr(*args, **kwargs)
        return locked

    def __enter__(self) -> "SharedStore":
        return self

    def __exit__(self, *a: Any) -> None:
        self.close()
