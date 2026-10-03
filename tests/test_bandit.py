import random

import pytest

from kushima.learning.bandit import StyleBandit, reward


def test_safety_violation_is_minimum_regardless_of_rating():
    assert reward(1.0, safety_violation=True) == -1.0


def test_sycophancy_and_dependence_reduce_reward():
    assert reward(1.0, sycophancy=1.0) == 0.5
    assert reward(1.0, sycophancy=1.0, dependence=1.0) == 0.0
    assert reward(-1.0, sycophancy=1.0) == -1.0


def test_reward_is_clipped():
    assert reward(5.0) == 1.0 and reward(-5.0) == -1.0


def test_tries_every_arm_first():
    b = StyleBandit.create(["kurz", "lang"], epsilon=0.0)
    seen = {b.choose()}
    b.update("kurz", 0.0)
    seen.add(b.choose())
    assert seen == {"kurz", "lang"}


def test_converges_to_best_arm():
    b = StyleBandit.create(["a", "b", "c"], epsilon=0.1, rng=random.Random(1))
    truth = {"a": 0.1, "b": 0.8, "c": -0.3}
    for _ in range(300):
        arm = b.choose()
        b.update(arm, truth[arm])
    assert max(b.arms, key=lambda n: b.arms[n].n) == "b"


def test_style_that_violates_safety_is_abandoned():
    b = StyleBandit.create(["frech", "sachlich"], epsilon=0.0)
    b.update("frech", reward(1.0, safety_violation=True))
    b.update("sachlich", reward(0.2))
    assert b.choose() == "sachlich"


def test_unknown_arm_and_empty():
    with pytest.raises(KeyError):
        StyleBandit.create(["a"]).update("x", 1.0)
    with pytest.raises(ValueError):
        StyleBandit.create([])
