"""Bandit über Antwortstile (z. B. kurz/ausführlich/direkt) mit Sicherheits-Reward.

Lernt nur Stil-Parameter, nie Berechtigungen: Arme sind reine Bezeichner, der ActionGate bleibt
unberührt. Der Reward ist die Nutzerbewertung, begrenzt auf [-1, 1], und wird durch Strafen
überstimmt: Ein Sicherheits-Verstoß setzt ihn auf -1 (hartes Minimum); Schmeichelei und
Abhängigkeitsförderung ziehen ab. Positives Feedback kann Verstöße nie ausgleichen.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


def reward(rating: float, safety_violation: bool = False, sycophancy: float = 0.0,
           dependence: float = 0.0) -> float:
    """rating, sycophancy, dependence in [0, 1] bzw. [-1, 1] (rating); Ergebnis in [-1, 1]."""
    if safety_violation:
        return -1.0
    r = max(-1.0, min(1.0, rating))
    r -= 0.5 * max(0.0, min(1.0, sycophancy)) + 0.5 * max(0.0, min(1.0, dependence))
    return max(-1.0, min(1.0, r))


@dataclass
class Arm:
    n: int = 0
    mean: float = 0.0


@dataclass
class StyleBandit:
    arms: dict[str, Arm]
    epsilon: float = 0.1
    rng: random.Random = field(default_factory=random.Random)

    @classmethod
    def create(cls, names: list[str], **kw) -> "StyleBandit":
        if not names:
            raise ValueError("Mindestens ein Arm nötig")
        return cls({n: Arm() for n in names}, **kw)

    def choose(self) -> str:
        untried = [n for n, a in self.arms.items() if a.n == 0]
        if untried:
            return untried[0]
        if self.rng.random() < self.epsilon:
            return self.rng.choice(list(self.arms))
        return max(self.arms, key=lambda n: self.arms[n].mean)

    def update(self, name: str, r: float) -> None:
        if name not in self.arms:
            raise KeyError(name)
        r = max(-1.0, min(1.0, r))
        a = self.arms[name]
        a.n += 1
        a.mean += (r - a.mean) / a.n
