"""Stimmprofil v2: mehrere Prototypen statt eines Mittelwerts, Schwelle aus Messdaten.

Aus den langen Einschreibe-Aufnahmen entstehen viele Embeddings (Fenster von ca. 3 s). Sie werden zu
wenigen Prototypen gebündelt (k-means). Eine Probe wird mit dem ÄHNLICHSTEN Prototyp verglichen. So deckt
das Profil verschiedene Tonlagen, Lautstärken und Sprechweisen ab, was ein einzelner Mittelwert verwischt.

Die Schwelle kommt aus zwei Messungen (Leave-one-recording-out):
  Ziel:   Werte deiner eigenen, zurückgehaltenen Aufnahmen gegen ein Profil aus den übrigen
  Fremde: Werte fremder/künstlicher Stimmen (Kohorte) gegen dasselbe Profil
und liegt dazwischen, begrenzt auf [MIN_THRESHOLD, MAX_THRESHOLD]. Überlappen beide Verteilungen, wird das
gemeldet (`separation`) statt so zu tun, als sei alles sicher.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

import numpy as np

MIN_THRESHOLD, MAX_THRESHOLD = 0.5, 0.9     # unter 0,5 liegt Rauschen (gemessen bis 0,77 gegen mehrere Prototypen, siehe STT-Gate)
STRONG_MARGIN = 0.10                        # "stark" verifiziert: Schwelle plus Abstand
MAX_PROTOTYPES = 6


def unit(v: Any) -> np.ndarray | None:
    a = np.asarray(v, dtype=np.float64).ravel()
    n = np.linalg.norm(a)
    if a.size == 0 or not np.all(np.isfinite(a)) or n == 0:
        return None
    return a / n


def kmeans(x: np.ndarray, k: int, iters: int = 25, seed: int = 0) -> np.ndarray:
    """Einfaches k-means auf Einheitsvektoren (Kosinus); gibt Einheitsvektoren als Zentren zurück."""
    rng = np.random.default_rng(seed)
    k = max(1, min(k, len(x)))
    centers = x[rng.choice(len(x), size=k, replace=False)]
    for _ in range(iters):
        assign = np.argmax(x @ centers.T, axis=1)
        new = np.array([x[assign == i].mean(axis=0) if np.any(assign == i) else centers[i] for i in range(k)])
        new /= np.linalg.norm(new, axis=1, keepdims=True)
        if np.allclose(new, centers, atol=1e-6):
            break
        centers = new
    return centers


@dataclass
class SpeakerProfile:
    prototypes: np.ndarray                  # [k, dim], Einheitsvektoren
    threshold: float = 0.6
    margin: float = STRONG_MARGIN
    model: str = ""
    stats: dict = field(default_factory=dict)
    enrolled = True

    def score(self, embedding: Any) -> float:
        u = unit(embedding)
        if u is None or u.size != self.prototypes.shape[1]:
            return 0.0
        return float(np.max(self.prototypes @ u))

    def verify(self, embedding: Any):
        from .speaker import Verdict
        s = self.score(embedding)
        ok = s >= self.threshold
        return Verdict(ok, s, "ok" if ok else "Stimme passt nicht")

    def to_json(self) -> dict:
        return {"version": 2, "model": self.model, "dim": int(self.prototypes.shape[1]),
                "threshold": float(self.threshold), "margin": float(self.margin), "stats": self.stats,
                "prototypes": [base64.b64encode(p.astype(np.float32).tobytes()).decode() for p in self.prototypes]}

    @classmethod
    def from_json(cls, data: dict) -> "SpeakerProfile":
        dim = int(data["dim"])
        protos = np.array([np.frombuffer(base64.b64decode(p), dtype=np.float32) for p in data["prototypes"]],
                          dtype=np.float64)
        if protos.ndim != 2 or protos.shape[1] != dim or not len(protos):
            raise ValueError("Profil beschädigt")
        protos = np.array([unit(p) for p in protos])
        return cls(protos, float(data.get("threshold", 0.6)), float(data.get("margin", STRONG_MARGIN)),
                   str(data.get("model", "")), dict(data.get("stats", {})))


def _prototypes(groups: list[np.ndarray], k: int) -> np.ndarray:
    allv = np.vstack(groups)
    return kmeans(allv, k)


def build_profile(recordings: list[list[Any]], cohort: list[Any], model: str = "") -> SpeakerProfile:
    """recordings: je Aufnahme eine Liste von Fenster-Embeddings; cohort: Embeddings fremder Stimmen/Rauschen."""
    groups = []
    for rec in recordings:
        u = [x for x in (unit(e) for e in rec) if x is not None]
        if u:
            groups.append(np.array(u))
    if len(groups) < 3 or sum(len(g) for g in groups) < 12:
        raise ValueError("Zu wenig Material: mindestens 3 Aufnahmen und 12 Fenster nötig")
    k = min(MAX_PROTOTYPES, max(2, sum(len(g) for g in groups) // 15))
    final = SpeakerProfile(_prototypes(groups, k), model=model)

    # Leave-one-recording-out: Zielwerte deiner eigenen Stimme
    target = []
    others_cohort: list[np.ndarray] = []
    cohort_u = np.array([x for x in (unit(e) for e in cohort) if x is not None]) if cohort else np.zeros((0, 1))
    impostor = []
    for i, held in enumerate(groups):
        rest = [g for j, g in enumerate(groups) if j != i]
        prof = SpeakerProfile(_prototypes(rest, k))
        target += [prof.score(e) for e in held]
        if len(cohort_u) and cohort_u.shape[1] == held.shape[1]:
            impostor += [prof.score(e) for e in cohort_u]
    target_arr, imp_arr = np.array(target), np.array(impostor) if impostor else np.array([])
    p10 = float(np.percentile(target_arr, 10))
    p95 = float(np.percentile(imp_arr, 95)) if imp_arr.size else MIN_THRESHOLD
    mid = 0.5 * (p10 + p95)
    final.threshold = float(min(MAX_THRESHOLD, max(MIN_THRESHOLD, mid)))
    separation = p10 - p95
    final.stats = {"recordings": len(groups), "windows": int(sum(len(g) for g in groups)),
                   "prototypes": int(len(final.prototypes)), "target_p10": round(p10, 3),
                   "target_median": round(float(np.median(target_arr)), 3), "cohort_p95": round(p95, 3),
                   "separation": round(separation, 3), "cohort_size": int(len(cohort_u))}
    return final
