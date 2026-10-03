"""MemoryStore: einzige Schnittstelle zum Gedächtnis. Der Rest des Programms kennt keinen Ort."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Fact:
    id: int
    text: str
    kind: str          # preference | decision | person | routine | other
    source: str
    confidence: float
    created: float


class MemoryStore(ABC):
    @abstractmethod
    def add_fact(self, text: str, kind: str = "other", source: str = "user",
                 confidence: float = 1.0) -> int: ...

    @abstractmethod
    def search_facts(self, query: str, limit: int = 10) -> list[Fact]: ...

    @abstractmethod
    def delete_fact(self, fact_id: int) -> None: ...

    @abstractmethod
    def log_episode(self, role: str, text: str, session: str = "") -> int: ...

    @abstractmethod
    def add_feedback(self, episode_id: int | None, rating: int, note: str = "") -> int:
        """Trainingsdaten für späteres Preference-Learning / Bandit."""

    @abstractmethod
    def set_profile(self, key: str, value: str) -> None: ...

    @abstractmethod
    def get_profile(self) -> dict[str, str]: ...

    @abstractmethod
    def audit(self, event: str, detail: str = "") -> None: ...

    @abstractmethod
    def snapshot(self, dest: Path) -> None:
        """Konsistente Kopie des gesamten Vaults nach dest (auch bei laufendem Betrieb)."""

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
