"""Vorhandene Claude-Branches erkennen und dort weitermachen (Sprache)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from kushim.claude_cli.session import State
from kushim.voice.tool_commands import parse

from test_voice_tools import make


def _wt(name):
    return SimpleNamespace(path=SimpleNamespace(name=name), branch="worktree-" + name)


def make_branches(direct=False, n=2):
    tc, reg, research, control, sessions = make(enabled=["claude.code"], direct=direct)
    items = [(_wt("kushim-20261004-051157"), 2, 0), (_wt("kushim-20261004-044808"), 0, 1)][:n]
    sessions.branches = lambda folder: items
    sessions.adopted = []

    def adopt(folder, name):
        sessions.adopted.append(name)
        sessions.st = State(folder=folder.name, status="waiting", worktree=name)
    sessions.adopt = adopt
    return tc, control, sessions


@pytest.mark.parametrize("text,kind", [
    ("Welche Claude Branches gibt es?", "branches"), ("Zeig mir die Branches", "branches"),
    ("Mach bei Nummer eins weiter", "resume"), ("Claude soll im Branch weiterarbeiten", "resume"), ("Mach im neuesten Branch weiter", "resume"),
])
def test_branch_intents(text, kind):
    assert parse(text).kind == kind


def test_branches_are_listed_numbered_newest_first():
    tc, *_ = make_branches()
    msg = tc.handle("Welche Claude Branches gibt es?", True)
    assert "Nummer 1" in msg and "4. Oktober um 5 Uhr 11" in msg and "2 ungesicherte" in msg and "Nummer 2" in msg


def test_resume_adopts_chosen_branch_and_continues_after_yes():
    tc, control, sessions = make_branches()
    tc.handle("Welche Claude Branches gibt es?", True)
    msg = tc.handle("Mach bei Nummer zwei weiter", True, True)
    assert sessions.adopted == ["kushim-20261004-044808"] and "ja oder nein" in msg
    tc.handle("ja", True, True)
    assert control.proposed[-1][0] == "answer" and "Mach dort weiter" in control.proposed[-1][1] and control.calls == ["approve", "execute"]


def test_resume_direct_and_asks_which_when_ambiguous():
    tc, control, sessions = make_branches(direct=True)
    assert "Welchen Branch" in tc.handle("Claude soll im Branch weiterarbeiten", True, True) and not sessions.adopted
    tc.handle("Mach bei Nummer eins weiter und schreibe die Tests", True, True)
    assert sessions.adopted == ["kushim-20261004-051157"] and control.proposed[-1][1] == "schreibe die Tests"


def test_resume_single_branch_needs_no_number_and_needs_strong_voice():
    tc, control, sessions = make_branches(n=1, direct=True)
    assert "deutliche" in tc.handle("Claude soll im Branch weiterarbeiten", True, False)
    tc.handle("Claude soll im Branch weiterarbeiten", True, True)
    assert sessions.adopted == ["kushim-20261004-051157"]


def test_resume_needs_tool_and_voice():
    tc, *_ = make()
    assert "nicht eingeschaltet" in tc.handle("Mach bei Nummer eins weiter", True, True)
    tc, control, sessions = make_branches()
    assert "deine Stimme" in tc.handle("Mach bei Nummer eins weiter", False) and not sessions.adopted


def test_continue_argv_keeps_all_safety_flags():
    from pathlib import Path
    from kushim.claude_cli import dev
    argv = dev.build_continue_argv(Path("claude"), "Mach weiter")
    assert "--continue" in argv and "--setting-sources" in argv and argv[argv.index("--setting-sources") + 1] == "user"
    assert "-w" not in argv and not set(argv) & set(dev.FORBIDDEN_FLAGS)
    assert "--disallowedTools" in argv and "--strict-mcp-config" in argv
