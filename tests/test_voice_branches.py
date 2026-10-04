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


# --- "Mach weiter mit Claude"
@pytest.mark.parametrize("text", ["Mach weiter mit Claude.", "Claude soll weitermachen", "Setz Claude fort und prüfe die Tests", "Claude weiterarbeiten"])
def test_continue_intent(text):
    assert parse(text).kind == "continue"


def test_continue_resumes_waiting_session_directly():
    tc, control, sessions = make_branches(direct=True)
    sessions.st = State(folder="kushim", status="waiting", worktree="w", worktree_path="C:/w")
    tc.handle("Mach weiter mit Claude.", True, True)
    assert control.proposed[-1][0] == "answer" and "Mach dort weiter" in control.proposed[-1][1] and not sessions.adopted


def test_continue_while_running_does_nothing():
    tc, control, sessions = make_branches(direct=True)
    sessions.st = State(folder="kushim", status="running")
    assert "arbeitet gerade" in tc.handle("Mach weiter mit Claude.", True, True) and not control.proposed


def test_continue_after_stop_adopts_same_branch_again():
    tc, control, sessions = make_branches(direct=True)
    sessions.st = State(folder="kushim", status="stopped", worktree="kushim-20261004-051157", worktree_path="C:/w")
    tc.handle("Mach weiter mit Claude.", True, True)
    assert sessions.adopted == ["kushim-20261004-051157"] and control.proposed[-1][0] == "answer"


def test_continue_without_session_falls_back_to_branch_choice():
    tc, control, sessions = make_branches(direct=True, n=1)
    tc.handle("Mach weiter mit Claude.", True, True)
    assert sessions.adopted == ["kushim-20261004-051157"]


def test_continue_needs_strong_voice():
    tc, control, sessions = make_branches(direct=True)
    sessions.st = State(folder="kushim", status="waiting", worktree_path="C:/w")
    assert "deutliche" in tc.handle("Mach weiter mit Claude.", True, False) and not control.proposed


# --- viele Auslöse-Wörter (Nutzerwunsch)
@pytest.mark.parametrize("text,kind", [
    ("Setz Claude fort", "continue"), ("Claude weiter", "continue"), ("Claude arbeite weiter", "continue"), ("Claude soll dranbleiben", "continue"),
    ("Dann nutze Claude und entwickle das Projekt weiter.", "start"), ("Claude, entwickle das Projekt weiter", "start"),
    ("Lass Claude das Projekt weiterentwickeln", "start"), ("Claude, schreib die Tests für den Timer", "start"), ("Bitte Claude die README zu verbessern", "start"),
    ("Frag Claude wie hoch der Eiffelturm ist", "research"), ("Finde heraus wann Paris gegründet wurde", "research"),
    ("Google mal das Wetter in Hamburg", "research"), ("Kannst du nachschauen wie spät es in Tokio ist", "research"),
    ("Schlag nach was ein Quantencomputer ist", "research"), ("Informiere dich über den Mond", "research"),
    ("Guck mal nach der Höhe vom Mount Everest", "research"),
    ("Ist Claude fertig?", "status"), ("Läuft Claude noch?", "status"), ("Wie weit ist Claude?", "status"), ("Was treibt Claude gerade", "status"),
    ("Hör auf Claude", "stop"), ("Pausiere Claude", "stop"), ("Halt Claude an", "stop"),
    ("Erzähl mir was Claude gemacht hat", "result"), ("Berichte was Claude geschafft hat", "result"), ("Gib mir den Überblick von Claude", "result"),
    ("Gib ihm die Erlaubnis", "allow"), ("Erlaube Claude das", "allow"), ("Genehmige das", "allow"), ("Gib das frei", "allow"),
    ("Schreib Claude ja bitte", "answer"), ("Sag Claude nimm Variante zwei", "answer"), ("Antworte Claude mit nein", "answer"),
    ("Was kannst du alles?", "list"), ("Was hast du drauf", "list"), ("Womit kannst du mir helfen", "list"), ("Welche Hilfsmittel hast du", "list"),
])
def test_many_trigger_words(text, kind):
    assert parse(text).kind == kind


@pytest.mark.parametrize("text", ["Wie spät ist es", "Gib mir die Zeit", "Das Wetter ist schön", "Ich suche meinen Schlüssel", "Kannst du mir Mut machen",
                                  "Ich möchte weiter schlafen", "Mach das Licht an", "Frag mich was", "Wie hoch ist der Eiffelturm"])
def test_everyday_sentences_still_go_to_the_llm(text):
    assert parse(text) is None


def test_answer_text_loses_leading_mit():
    assert parse("Antworte Claude mit nein").text == "nein"


# --- "Mach dort weiter" ohne Namen und entfernter Worktree (Fehler aus dem Live-Test)
def test_soft_continue_only_with_a_claude_session():
    tc, control, sessions = make_branches(direct=True)
    assert tc.handle("Mach dort weiter.", True, True) is None and not control.proposed          # keine Sitzung: geht an das Sprachmodell
    sessions.st = State(folder="kushim", status="waiting", worktree="w", worktree_path="C:/w")
    tc.handle("Mach dort weiter.", True, True)
    assert control.proposed[-1][0] == "answer"


@pytest.mark.parametrize("text", ["Ich möchte weiter schlafen", "Mach das Licht an", "Mach weiter so wie gestern beim Kochen für alle"])
def test_soft_continue_is_not_triggered_by_everyday_talk(text):
    assert parse(text) is None or parse(text).kind != "continue_soft"


def test_continue_with_removed_worktree_does_not_crash_and_starts_new_run():
    tc, control, sessions = make_branches(direct=True)
    sessions.branches = lambda folder: []
    sessions.worktree_ok = lambda st: False
    sessions.st = State(folder="kushim", status="waiting", worktree="gone", worktree_path="C:/gone")
    reply = tc.handle("Sag Claude er soll weitermachen mit der Roadmap", True, True)
    assert "Claude arbeitet" in reply and control.proposed[-1][0] == "mit der Roadmap" or control.proposed[-1][1] == "kushim"


def test_answer_refuses_missing_worktree(tmp_path):
    from kushim.claude_cli.session import ClaudeSessions, SessionError, save_state
    s = ClaudeSessions(tmp_path, None)
    save_state(tmp_path, State(id="x", folder="k", status="waiting", worktree_path=str(tmp_path / "weg")))
    with pytest.raises(SessionError, match="existiert nicht mehr"):
        s.answer("weiter")
