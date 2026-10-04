"""Sprachbefehle für Werkzeuge: Parser, Ablauf mit Bestätigung, Ehrlichkeit der Liste, Meldungen von sich aus."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from kushim.claude_cli.folders import Folder
from kushim.claude_cli.report import Overview
from kushim.claude_cli.session import State
from kushim.config import LiveConfig
from kushim.safety.gate import ActionSpec, Risk
from kushim.tools.registry import ToolInfo, ToolRegistry
from kushim.voice.commands import CommandChain
from kushim.voice.talk import TalkLoop
from kushim.voice.tool_commands import ToolCommands, parse
from kushim.web.sanitize import Untrusted


def _tool(name, title, out=True, why=""):
    return ToolInfo(name, title, "x", ActionSpec(name, Risk.READ, external_effect=out), out, lambda: why)


class FakeApproval:
    id = "a1"


class FakeOwner:
    def __init__(self, ok=True):
        self.calls, self.ok, self.proposed = [], ok, []

    def approve(self, p):
        self.calls.append("approve")
        return self.ok

    def deny(self, p):
        self.calls.append("deny")


class FakeResearch(FakeOwner):
    def propose(self, query, speaker_verified, user_initiated=True):
        self.proposed.append(query)
        return SimpleNamespace(approval=FakeApproval(), route="claude", preview="x Wikipedia", reason="")

    def execute(self, p):
        self.calls.append("execute")
        return SimpleNamespace(kind="claude", answer=Untrusted("324 Meter"), wiki=None, note="")


class FakeControl(FakeOwner):
    def propose_start(self, task, folder_name, speaker_verified, user_initiated=True):
        self.proposed.append((task, folder_name))
        return SimpleNamespace(approval=FakeApproval(), reason="", task=task or "Standardauftrag")

    def propose_answer(self, text, allow, speaker_verified, user_initiated=True):
        self.proposed.append(("answer", text, tuple(allow)))
        return SimpleNamespace(approval=FakeApproval(), reason="", task=text)

    def execute(self, p):
        self.calls.append("execute")


class FakeSessions:
    on_finish = None

    def __init__(self):
        self.st, self.stopped = None, 0

    def state(self):
        return self.st

    def stop(self):
        self.stopped += 1
        return True

    def result(self):
        ov = Overview(Untrusted("Tests geschrieben"), facts=["3 Dateien geändert"], question=Untrusted("Variante A oder B?"))
        return self.st, None, ov


def make(enabled=(), folders=(Folder("kushim", "C:/p"),), tools=None, direct=False):
    reg = ToolRegistry(tools or [_tool("web.search", "Websuche"), _tool("claude.research", "Claude-Recherche"),
                                  _tool("claude.code", "Claude-Entwicklung")], enabled)
    cfg = SimpleNamespace(tools_enabled=list(enabled), voice_direct=direct)
    research, control, sessions = FakeResearch(), FakeControl(), FakeSessions()
    tc = ToolCommands(cfg, reg, research, control, sessions, lambda w: "Zusammenfassung", lambda: list(folders))
    return tc, reg, research, control, sessions


# --- Parser
@pytest.mark.parametrize("text,kind", [
    ("Hast du Tools?", "list"), ("Werkzeugeliste", "list"), ("Werkzeug Lüste", "list"), ("Werkzeugliste", "list"), ("Werkzeug Liste", "list"), ("Deine Tools", "list"), ("Gib mir die Werkzeugliste.", "list"), ("Zeig mir deine Toolliste", "list"), ("Liste deine Werkzeuge auf", "list"), ("Welche Werkzeuge hast du", "list"), ("Zeig mir die Tools", "list"), ("Was kannst du?", "list"),
    ("Wie schalte ich die Tools ein?", "enable_how"), ("Aktiviere die Werkzeuge", "enable_how"),
    ("Recherchiere die Höhe des Eiffelturms", "research"), ("Schau mir bitte die Höhe vom Eiffelturm nach", "research"),
    ("Suche im Internet nach Wetter Hamburg", "research"),
    ("Nutze Claude um das Projekt kushim weiterzuentwickeln", "start"), ("Claude soll die Tests schreiben", "start"),
    ("Lass Claude den Timer bauen", "start"), ("Was macht Claude?", "status"), ("Stopp Claude", "stop"),
    ("Was hat Claude gemacht?", "result"), ("Antwort an Claude: nimm Variante zwei", "answer"), ("Erlaube das", "allow"),
])
def test_parse_kinds(text, kind):
    assert parse(text).kind == kind


@pytest.mark.parametrize("text", ["Wie spät ist es", "Wie hoch ist der Eiffelturm", "Schalte das Licht ein",
                                  "Was kannst du über Paris erzählen und sagen", ""])
def test_ordinary_sentences_are_not_commands(text):
    assert parse(text) is None


def test_research_query_keeps_umlauts_and_drops_filler():
    assert parse("Recherchiere die Höhe des Eiffelturms").text == "die Höhe des Eiffelturms"
    assert parse("Suche im Internet nach Wetter Hamburg").text == "Wetter Hamburg"


def test_start_task_after_und():
    assert parse("Nutze Claude um kushim weiterzuentwickeln und baue den Timer für Erinnerungen").text == "baue den Timer für Erinnerungen"


# --- Liste (ehrlich, aus dem echten Stand)
def test_list_is_truthful_about_state_and_never_enables():
    tc, reg, *_ = make(enabled=["web.search"], tools=[_tool("web.search", "Websuche"),
                       _tool("claude.code", "Claude-Entwicklung", why="Modus C ist aus (kushim claude enable)")])
    text = tc.handle("Welche Werkzeuge hast du?", verified=False)        # Anzeigen braucht keine Stimme und ändert nichts
    assert "Websuche: an" in text and "Claude-Entwicklung: aus, weil Modus C ist aus" in text
    assert "nie per Sprache" in text
    assert not reg.is_active("claude.code")


def test_list_works_without_any_tool_enabled():
    tc, *_ = make()
    assert "keines" in tc.handle("Hast du Tools?", verified=True)


def test_voice_cannot_enable_tools():
    tc, reg, *_ = make()
    for phrase in ("Schalte die Tools ein", "Aktiviere die Werkzeuge", "Schalte Claude Recherche ein"):
        reply = tc.handle(phrase, verified=True)
        assert reply is None or "nie per Sprache" in reply
    assert not reg.enabled_names()


def test_registry_sync_follows_config():
    tc, reg, *_ = make()
    tc.cfg.tools_enabled = ["web.search"]
    tc.handle("Hast du Tools?", verified=True)
    assert reg.is_enabled("web.search")
    tc.cfg.tools_enabled = []
    tc.handle("Hast du Tools?", verified=True)
    assert not reg.is_enabled("web.search")


# --- Recherche mit Bestätigung
def test_research_needs_yes_and_runs_once():
    tc, _, research, *_ = make(enabled=["claude.research"])
    ask = tc.handle("Recherchiere die Höhe des Eiffelturms", True)
    assert "Anthropic" in ask and "ja oder nein" in ask and tc.awaiting
    assert research.calls == []                                           # vor dem "ja" passiert nichts
    assert tc.handle("ja", True) == "Laut Claude: 324 Meter"
    assert research.calls == ["approve", "execute"] and not tc.awaiting
    assert tc.handle("ja", True) is None                                  # kein zweites Mal


@pytest.mark.parametrize("answer", ["nein", "vielleicht", "ja nein", "hm"])
def test_anything_but_clear_yes_denies(answer):
    tc, _, research, *_ = make()
    tc.handle("Recherchiere Wetter Hamburg", True)
    assert "Abgebrochen" in tc.handle(answer, True)
    assert research.calls == ["deny"]


def test_unverified_speaker_gets_nothing_executed():
    tc, _, research, control, _s = make()
    assert "deine Stimme" in tc.handle("Recherchiere Wetter", False)
    assert "deine Stimme" in tc.handle("Claude soll die Tests schreiben", False)
    assert not research.proposed and not control.proposed and not tc.awaiting


def test_unverified_yes_denies_pending():
    tc, _, research, *_ = make()
    tc.handle("Recherchiere Wetter Hamburg", True)
    assert "Stimme" in tc.handle("ja", False)
    assert research.calls == ["deny"]


def test_expired_approval_is_reported():
    tc, _, research, *_ = make()
    research.ok = False
    tc.handle("Recherchiere Wetter Hamburg", True)
    assert "abgelaufen" in tc.handle("ja", True) and "execute" not in research.calls


def test_empty_research_query_asks_back():
    tc, _, research, *_ = make()
    assert "Wonach" in tc.handle("Recherchiere", True) and not research.proposed


# --- Claude
def test_claude_start_requires_tool_active():
    tc, *_ = make()                                                        # nichts eingeschaltet
    reply = tc.handle("Nutze Claude um das Projekt kushim weiterzuentwickeln", True, True)
    assert "nicht eingeschaltet" in reply and not tc.awaiting


def test_claude_start_needs_strong_voice_and_yes():
    tc, _, _, control, _s = make(enabled=["claude.code"])
    assert "deutliche" in tc.handle("Nutze Claude um das Projekt kushim weiterzuentwickeln", True, False)
    assert not control.proposed
    msg = tc.handle("Nutze Claude um das Projekt kushim weiterzuentwickeln", True, True)
    assert "Ordner kushim" in msg and "Anthropic" in msg and control.calls == []
    assert "Claude arbeitet" in tc.handle("ja", True, True) and control.calls == ["approve", "execute"]


def test_single_folder_is_used_when_not_named():
    tc, _, _, control, _s = make(enabled=["claude.code"])
    tc.handle("Claude soll die Tests schreiben", True, True)
    assert control.proposed == [("die Tests schreiben", "kushim")]


def test_unknown_folder_among_several_asks():
    tc, _, _, control, _s = make(enabled=["claude.code"], folders=(Folder("alpha", "C:/a"), Folder("beta", "C:/b")))
    assert "Welchen Ordner" in tc.handle("Claude soll die Tests schreiben", True, True) and not control.proposed


def test_stop_status_result_and_answer():
    tc, _, _, control, sessions = make(enabled=["claude.code"])
    assert "gestoppt" in tc.handle("Stopp Claude", True) and sessions.stopped == 1
    assert "kein Claude-Lauf" in tc.handle("Was macht Claude?", True)
    sessions.st = State(folder="kushim", status="waiting", turn=2, seconds=120, offers=["Bash(pytest *)"])
    assert "wartet" in tc.handle("Was macht Claude?", True)
    assert "Tests geschrieben" in tc.handle("Was hat Claude gemacht?", True)
    assert "Variante zwei" in tc.handle("Antwort an Claude: Variante zwei", True, True)
    tc.handle("ja", True, True)
    assert control.proposed[-1] == ("answer", "Variante zwei", ())


def test_allow_offers_only_what_was_offered():
    tc, _, _, control, sessions = make(enabled=["claude.code"])
    assert "nichts" in tc.handle("Erlaube das", True, True)
    sessions.st = State(folder="kushim", status="waiting", offers=["Bash(pytest *)"])
    tc.handle("Erlaube das", True, True)
    assert control.proposed[-1][2] == ("Bash(pytest *)",)


# --- Meldungen von sich aus
def test_announcement_when_claude_finishes_with_question():
    tc, _, _, _c, sessions = make(enabled=["claude.code"])
    sessions.st = State(folder="kushim", status="waiting", turn=1)
    sessions.on_finish(sessions.st)
    msg = tc.announcement()
    assert "Variante A oder B" in msg and "Antwort an Claude" in msg
    assert tc.announcement() is None                                     # einmalig


def test_announcement_on_failure():
    tc, _, _, _c, sessions = make()
    sessions.on_finish(State(status="failed", error="Zeitüberschreitung"))
    assert "gescheitert" in tc.announcement()


def test_talkloop_speaks_announcement_when_idle():
    spoken, flushed, msgs = [], [], ["Claude ist fertig."]
    pipe = SimpleNamespace(interrupt=lambda: None)
    kill = SimpleNamespace(poll=lambda: False)
    loop = TalkLoop(iter([0, 1]), pipe, kill, wake=lambda f: False, flush=lambda: flushed.append(1),
                    announce=lambda: msgs.pop() if msgs else None, say=spoken.append)
    assert loop.run() == "ended"
    assert spoken == ["Claude ist fertig."] and flushed


# --- Kette
def test_chain_routes_yes_to_the_waiting_group():
    first = SimpleNamespace(awaiting=False, handle=lambda t, v, s=True: None)
    calls = []

    class Waiting:
        awaiting = True

        def handle(self, t, v, s=True):
            calls.append(t)
            return "ok"

    chain = CommandChain([first, Waiting()])
    assert chain.awaiting and chain.handle("ja", True) == "ok" and calls == ["ja"]


def test_chain_first_answer_wins_and_none_passes():
    one = SimpleNamespace(awaiting=False, handle=lambda t, v, s=True: None)
    two = SimpleNamespace(awaiting=False, handle=lambda t, v, s=True: "zwei")
    assert CommandChain([one, two]).handle("x", True) == "zwei"
    assert CommandChain([one]).handle("x", True) is None


# --- LiveConfig
def test_liveconfig_reloads_after_ttl_and_keeps_last_good():
    now = [0.0]
    states = [SimpleNamespace(v=1), SimpleNamespace(v=2), "boom"]

    def loader():
        s = states.pop(0)
        if s == "boom":
            raise ValueError("kaputt")
        return s

    live = LiveConfig(ttl=2.0, loader=loader, clock=lambda: now[0])
    assert live.v == 1
    now[0] = 1.0
    assert live.v == 1                                                   # noch frisch
    now[0] = 3.0
    assert live.v == 2
    now[0] = 6.0
    assert live.v == 2                                                   # Lesefehler: letzter guter Stand


@pytest.mark.parametrize("yes", ["Yep.", "Ja bitte", "Genau, starte", "Okay", "Jawohl", "In Ordnung"])
def test_natural_yes_words_confirm(yes):
    tc, _, research, *_ = make()
    tc.handle("Recherchiere Wetter Hamburg", True)
    tc.handle(yes, True)
    assert research.calls == ["approve", "execute"]


# --- Direkt handeln (Nutzerwunsch: kein zweites "ja" für Recherche und Claude-Start)
def test_direct_research_runs_without_yes():
    tc, _, research, *_ = make(enabled=["claude.research"], direct=True)
    reply = tc.handle("Recherchiere die Höhe des Eiffelturms", True)
    assert "Laut Claude: 324 Meter" in reply and research.calls == ["approve", "execute"] and not tc.awaiting


def test_direct_claude_start_runs_without_yes_but_needs_strong_voice():
    tc, _, _, control, _s = make(enabled=["claude.code"], direct=True)
    assert "deutliche" in tc.handle("Claude soll die Tests schreiben", True, False) and not control.proposed
    reply = tc.handle("Claude soll die Tests schreiben", True, True)
    assert "Claude arbeitet" in reply and control.calls == ["approve", "execute"]


def test_direct_never_skips_verification_or_answers():
    tc, _, research, control, sessions = make(enabled=["claude.research", "claude.code"], direct=True)
    assert "deine Stimme" in tc.handle("Recherchiere Wetter", False) and not research.proposed
    sessions.st = State(folder="kushim", status="waiting", offers=["Bash(pytest *)"])
    assert "ja oder nein" in tc.handle("Antwort an Claude: Variante zwei", True, True) and control.calls == []   # Antworten fragen nach
    tc.handle("nein", True, True)
    assert "ja oder nein" in tc.handle("Erlaube das", True, True)                                                   # Erlaubnisse auch


def test_direct_announces_before_running():
    tc, _, research, *_ = make(enabled=["claude.research"], direct=True)
    order = []
    tc.say = lambda text: order.append(("say", text, list(research.calls)))
    reply = tc.handle("Recherchiere die Höhe des Eiffelturms", True)
    assert order[0][0] == "say" and "Ich starte." in order[0][1] and order[0][2] == ["approve"][:0] or order[0][2] == ["approve"][:0]
    assert reply == "Laut Claude: 324 Meter"                          # Ansage kam schon vorher, nicht doppelt in der Antwort
