"""Sprecherverifikation: vergleicht ein Stimm-Embedding mit dem eingeschriebenen Profil.

Fail-closed: ohne Profil, bei ungültigem Embedding oder Unsicherheit wird abgelehnt.
Die Verifikation ist nur eine Hürde vor der Befehlsverarbeitung, keine Autorisierung;
der ActionGate gilt danach unverändert. Das Embedding-Modell wird von außen geliefert.
Persistenz des Profils gehört in den verschlüsselten Vault (noch nicht angebunden).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


def _unit(v: Any) -> np.ndarray | None:
    a = np.asarray(v, dtype=np.float64).ravel()
    n = np.linalg.norm(a)
    if a.size == 0 or not np.all(np.isfinite(a)) or n == 0:
        return None
    return a / n


@dataclass(frozen=True)
class Verdict:
    accepted: bool
    score: float
    reason: str


MIN_THRESHOLD, MAX_THRESHOLD = 0.5, 0.75    # unter 0,5 liegt Rauschen (gemessen ca. 0,43)


def calibrate_threshold(embeddings: list[Any]) -> float:
    """Schwelle aus den Einschreibe-Proben: 80 % der mittleren Ähnlichkeit, begrenzt auf [0,5; 0,75].

    Die Untergrenze verhindert, dass uneinheitliche Proben die Prüfung zu weit öffnen.
    """
    units = [u for u in (_unit(e) for e in embeddings) if u is not None]
    sims = [float(np.dot(units[i], units[j])) for i in range(len(units)) for j in range(i + 1, len(units))
            if units[i].size == units[j].size]
    if not sims:
        return MAX_THRESHOLD
    return min(MAX_THRESHOLD, max(MIN_THRESHOLD, 0.8 * float(np.mean(sims))))


class SpeakerVerifier:
    def __init__(self, threshold: float = 0.75, min_enroll: int = 3):
        self.threshold, self.min_enroll = threshold, min_enroll
        self._profile: np.ndarray | None = None

    @property
    def enrolled(self) -> bool:
        return self._profile is not None

    def profile_vector(self) -> np.ndarray | None:
        return None if self._profile is None else self._profile.copy()

    def set_profile_vector(self, vec: Any) -> None:
        u = _unit(vec)
        if u is None:
            raise ValueError("Ungültiges Profil")
        self._profile = u

    def enroll(self, embeddings: list[Any]) -> None:
        units = [u for u in (_unit(e) for e in embeddings) if u is not None]
        if len(units) < self.min_enroll or len({u.size for u in units}) != 1:
            raise ValueError(f"Mindestens {self.min_enroll} gültige Embeddings gleicher Größe nötig")
        self._profile = _unit(np.mean(units, axis=0))

    def verify(self, embedding: Any) -> Verdict:
        if self._profile is None:
            return Verdict(False, 0.0, "kein Profil")
        u = _unit(embedding)
        if u is None or u.size != self._profile.size:
            return Verdict(False, 0.0, "ungültiges Embedding")
        score = float(np.dot(u, self._profile))
        ok = score >= self.threshold
        return Verdict(ok, score, "ok" if ok else "Stimme passt nicht")
