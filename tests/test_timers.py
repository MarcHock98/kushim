"""Lokale Timer und Erinnerungen: Dauer aus gesprochenem Deutsch, Speicher mit Grenzen."""
from __future__ import annotations

import json

import pytest

from kushim.timers import MAX_TIMERS, TimerError, TimerStore, clean_label, parse_duration
from kushim.tools.registry import TIMER, ToolRegistry, default_tools


@pytest.mark.parametrize("text,seconds", [
    ("Timer auf 10 Minuten", 600), ("zehn Minuten", 600), ("eine halbe Stunde", 1800), ("anderthalb Stunden", 5400),
    ("1 Stunde 30 Minuten", 5400), ("zwei Stunden", 7200), ("90 Sekunden", 90), ("fünfundzwanzig Minuten", 1500),
    ("in einer Minute", 60), ("zwei Tage", 172800), ("2,5 Minuten", 150), ("eine Stunde und zwanzig Minuten", 4800),
])
def test_parse_duration(text, seconds):
    assert parse_duration(text)[0] == seconds


def test_parse_duration_none_and_rest():
    assert parse_duration("Timer bitte")[0] is None
    sec, rest = parse_duration("Erinnere mich in zwanzig Minuten an die Wäsche")
    assert sec == 1200 and "Wäsche" in rest and "Minuten" not in rest


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_store_add_due_once_and_persist(tmp_path):
    clock = Clock()
    s = TimerStore(tmp_path, clock)
    s.add(60, "Tee")
    assert TimerStore(tmp_path, clock).list()[0].label == "Tee"                  # überlebt Neustart
    assert s.take_due() == []
    clock.t += 61
    due = s.take_due()
    assert [t.label for t in due] == ["Tee"] and s.take_due() == [] and s.list() == []


def test_store_limits_and_cleaning(tmp_path):
    s = TimerStore(tmp_path, Clock())
    for bad in (0, -5, 8 * 24 * 3600):
        with pytest.raises(TimerError):
            s.add(bad)
    for _ in range(MAX_TIMERS):
        s.add(60)
    with pytest.raises(TimerError):
        s.add(60)
    assert clean_label("a\x1b[31m\x00b" + "x" * 200).isprintable() and len(clean_label("x" * 200)) == 80


def test_store_ignores_garbage_file(tmp_path):
    p = tmp_path / "run" / "timers.json"
    p.parent.mkdir()
    p.write_text(json.dumps([{"id": "a", "due": "kaputt"}, 5, {"id": "b", "due": 5, "label": "ok"}]), encoding="utf-8")
    assert [t.id for t in TimerStore(tmp_path).list()] == ["b"]
    p.write_text("{nicht json", encoding="utf-8")
    assert TimerStore(tmp_path).list() == []


def test_registry_entry_is_local_and_default_off():
    assert not TIMER.sends_data_out and not TIMER.spec.external_effect and not TIMER.spec.costs_money
    assert not ToolRegistry(default_tools()).is_active("timer.local")
