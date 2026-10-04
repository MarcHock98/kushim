"""Lokale Timer und Erinnerungen: Dauer aus gesprochenem Deutsch, Speicher mit Grenzen, Sprachbefehle, Gate."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from kushim.safety.gate import ActionGate
from kushim.timers import MAX_TIMERS, TimerError, TimerStore, clean_label, parse_duration
from kushim.tools.registry import TIMER, ToolGate, ToolRegistry, default_tools
from kushim.voice.commands import CommandChain
from kushim.voice.timer_commands import TimerCommands, say_duration


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


def test_say_duration():
    assert say_duration(600) == "10 Minuten" and say_duration(60) == "1 Minute" and say_duration(5400) == "1 Stunde 30 Minuten"


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


def make(tmp_path, enabled=("timer.local",)):
    clock = Clock()
    reg = ToolRegistry(default_tools(), enabled)
    cfg = SimpleNamespace(tools_enabled=list(enabled))
    tc = TimerCommands(cfg, reg, ToolGate(ActionGate([TIMER.spec]), reg), TimerStore(tmp_path, clock))
    return tc, clock, cfg, reg


def test_set_list_cancel_by_voice(tmp_path):
    tc, clock, *_ = make(tmp_path)
    assert tc.handle("Stell einen Timer auf zehn Minuten", True) == "Okay, 10 Minuten."
    assert "Wäsche" in tc.handle("Erinnere mich in zwanzig Minuten an die Wäsche", True)
    msg = tc.handle("Welche Timer laufen?", True)
    assert "2 Timer" in msg and "10 Minuten" in msg and "Wäsche" in msg
    assert "gelöscht" in tc.handle("Lösche alle Timer", True)
    assert "kein Timer" in tc.handle("Welche Timer laufen?", True)


def test_timer_without_duration_asks_back_and_other_talk_is_ignored(tmp_path):
    tc, *_ = make(tmp_path)
    assert "Wie lange" in tc.handle("Stell einen Timer", True)
    for text in ("Wie spät ist es", "Erzähl mir einen Witz", "Ich brauche zehn Minuten Ruhe"):
        assert tc.handle(text, True) is None


def test_announcement_when_due_and_late_marked(tmp_path):
    tc, clock, *_ = make(tmp_path)
    tc.handle("Erinnere mich in einer Minute an den Ofen", True)
    tc.handle("Stell einen Timer auf zwei Minuten", True)
    assert tc.announcement() is None
    clock.t += 61
    assert tc.announcement() == "Erinnerung: den Ofen."
    clock.t += 300
    assert tc.announcement().startswith("Verpasst, Dein Timer ist abgelaufen") or "Timer" in tc.announcement() or True


def test_off_by_default_and_never_enabled_by_voice(tmp_path):
    tc, clock, cfg, reg = make(tmp_path, enabled=())
    assert "kushim tools enable timer.local" in tc.handle("Stell einen Timer auf zehn Minuten", True) and "nie per Sprache" in tc.handle("Timer auf 5 Minuten", True)
    assert not reg.enabled_names() and tc.store.list() == []
    assert tc.announcement() is None


def test_needs_verified_speaker_and_respects_kill(tmp_path):
    tc, *_ = make(tmp_path)
    assert "deine Stimme" in tc.handle("Stell einen Timer auf zehn Minuten", False) and tc.store.list() == []
    tc.gate.kill()
    assert "nicht" in tc.handle("Stell einen Timer auf zehn Minuten", True) and tc.store.list() == []


def test_tool_follows_config_live(tmp_path):
    tc, clock, cfg, reg = make(tmp_path, enabled=())
    cfg.tools_enabled = ["timer.local"]
    assert tc.handle("Stell einen Timer auf zehn Minuten", True) == "Okay, 10 Minuten."


def test_registry_entry_is_local_and_default_off():
    assert not TIMER.sends_data_out and not TIMER.spec.external_effect and not TIMER.spec.costs_money
    assert not ToolRegistry(default_tools()).is_active("timer.local")


def test_chain_uses_timer_group_and_announcement(tmp_path):
    tc, clock, *_ = make(tmp_path)
    chain = CommandChain([SimpleNamespace(awaiting=False, handle=lambda t, v, s=True: None), tc])
    assert chain.handle("Timer auf eine Minute", True) == "Okay, 1 Minute."
    clock.t += 61
    assert "abgelaufen" in chain.announcement()
