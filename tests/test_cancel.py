import json
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from kushim import cli
from kushim.api.protocol import ApiCore, new_token
from kushim.api.tasks_api import register_tasks
from kushim.claude_cli import ask as claude_ask
from kushim.safety.approvals import ApprovalQueue
from kushim.safety.gate import ActionGate, ActionRequest, ActionSpec, Decision, Risk
from kushim.safety.killswitch import KillSwitch
from kushim.tasks import TaskRegistry, is_cancel_phrase
from kushim.voice.audio import FRAME, UtteranceCollector
from kushim.voice.bargein import BargeIn
from kushim.voice.dialog import Dialog
from kushim.voice.pipeline import CANCEL_REPLY, NOTHING_REPLY, Pipeline
from kushim.voice.talk import TalkLoop
from kushim.voice.tts import Speaker

# --- Abbruch-Sätze -------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Abbrechen", "abbrechen!", "Brich ab.", "Brich das ab", "Brich bitte ab", "Brich den Befehl ab",
                                  "Befehl abbrechen", "Kushim, abbrechen", "Vergiss es", "Lass es", "Lass das sein", "Doch nicht",
                                  "Stopp den Befehl", "Abbruch", "cancel", "Bitte abbrechen", "Nicht ausführen"])
def test_cancel_phrases_are_recognized(text):
    assert is_cancel_phrase(text), text


@pytest.mark.parametrize("text", ["", "Wie hoch ist der Eiffelturm?", "Das Projekt wurde abgebrochen und neu gestartet",
                                  "Recherchiere zum Abbruch der Verhandlungen zwischen den beiden Ländern im Jahr 1990",
                                  "Warum musste die Mission abgebrochen werden", "Ich vergiss es nicht gerne zu sagen und noch viel mehr",
                                  "Brich einen Rekord"])
def test_normal_sentences_are_not_cancel_commands(text):
    assert not is_cancel_phrase(text), text


# --- TaskRegistry --------------------------------------------------------------------------------

def test_running_tasks_are_listed_while_running_and_removed_afterwards():
    t = TaskRegistry()
    assert t.active() == []
    with t.running("A") as a, t.running("B"):
        assert sorted(t.active()) == ["A", "B"] and not a.cancelled()
    assert t.active() == []


def test_cancel_all_sets_the_flag_calls_the_cancel_functions_and_survives_a_broken_one():
    t, called = TaskRegistry(), []

    def broken():
        raise RuntimeError("kaputt")
    with t.running("kaputt", broken) as bad, t.running("gut", lambda: called.append("gut")) as good:
        names = t.cancel_all()
        assert sorted(names) == ["gut", "kaputt"] and bad.cancelled() and good.cancelled() and called == ["gut"]
    assert t.cancel_all() == []                                      # nichts mehr laufend


def test_cancel_all_denies_pending_approvals_but_leaves_decided_ones():
    gate = ActionGate([ActionSpec("web.search", Risk.READ, external_effect=True)], reviewer=lambda s, r: set())
    q = ApprovalQueue(gate)
    _, pending = q.submit(ActionRequest("web.search", "Vorschau A", speaker_verified=True, user_initiated=True))
    _, approved = q.submit(ActionRequest("web.search", "Vorschau B", speaker_verified=True, user_initiated=True))
    assert q.approve(approved.id, approved.digest)
    t = TaskRegistry()
    t.add_queue(q)
    assert t.pending_approvals() == 1
    names = t.cancel_all()
    assert names == ["Freigabe für web.search"] and t.pending_approvals() == 0
    assert q.take(pending.id) is None                                # abgelehnt: nicht mehr ausführbar
    assert q.take(approved.id) is not None                           # schon freigegeben und noch nicht gestartet: bleibt gültig


# --- ask(): laufenden Claude-Aufruf abbrechen ----------------------------------------------------

class HangingProc:
    pid = 555

    def __init__(self):
        self.killed, self.returncode = False, 0

    def communicate(self, timeout=None):
        if not self.killed:
            time.sleep(min(timeout or 0.01, 0.01))
            raise subprocess.TimeoutExpired("claude", timeout)
        return "", ""

    def kill(self):
        self.killed = True

    def poll(self):
        return self.returncode if self.killed else None


def test_a_running_claude_call_is_killed_on_cancel_and_the_scratch_dir_removed(tmp_path):
    proc, kills, scratch = HangingProc(), [], []
    state = {"calls": 0}

    def cancelled():
        state["calls"] += 1
        return state["calls"] >= 3                                    # nach ein paar Abfragen sagt der Nutzer "abbrechen"

    def popen(argv, **kw):
        scratch.append(Path(kw["cwd"]))
        return proc
    res = claude_ask.ask("Eiffelturm Höhe", Path("C:/fake/claude.exe"), tmp_path / "w", popen=popen, kill=kills.append,
                         timeout=60, cancelled=cancelled)
    assert not res.ok and res.reason == "cancelled" and kills == [555] and proc.killed and not scratch[0].exists()


def test_a_result_that_arrives_just_after_cancel_is_discarded(tmp_path):
    class Done:
        pid, returncode = 1, 0

        def communicate(self, timeout=None):
            return json.dumps({"type": "result", "is_error": False, "result": "Antwort"}), ""

        def poll(self):
            return 0
    res = claude_ask.ask("x", Path("C:/fake/claude.exe"), tmp_path / "w", popen=lambda a, **k: Done(), kill=lambda p: None,
                         cancelled=lambda: True)
    assert not res.ok and res.reason == "cancelled" and res.text == ""


# --- Research: nach Abbruch kein Ersatzweg -------------------------------------------------------

def make_research(ask):
    from dataclasses import replace
    from kushim.claude_cli.base import Auth
    from kushim.privacy import EgressGate
    from kushim.research import Research
    from kushim.tools.registry import CLAUDE_RESEARCH, WEB_SEARCH, ToolRegistry
    from kushim.web.search import make_search
    reg = ToolRegistry([replace(CLAUDE_RESEARCH, available=lambda: ""), WEB_SEARCH], ["claude.research", "web.search"])
    fetched = []
    body = json.dumps({"query": {"pages": {"1": {"pageid": 1, "title": "T", "index": 1, "extract": "Text."}}}})
    ws = make_search(reg, lambda url: fetched.append(url) or body)
    return Research(reg, ask, ws, lambda: Auth(True, "claude.ai"), EgressGate(True, confirm=lambda d, p: True)), fetched


def test_cancel_during_the_claude_call_ends_the_research_without_falling_back_to_wikipedia():
    holder = {}

    def ask(q, cancelled):
        assert holder["r"].tasks.active() == ["Recherche über Claude"]          # läuft als abbrechbare Aufgabe
        holder["r"].tasks.cancel_all()                                          # Nutzer sagt "abbrechen"
        assert cancelled()
        return claude_ask.Answer(False, reason="cancelled")
    r, fetched = make_research(ask)
    holder["r"] = r
    p = r.propose("Eiffelturm Höhe", speaker_verified=True)
    assert r.approve(p)
    out = r.execute(p)
    assert out.kind == "none" and out.note == "Abgebrochen." and fetched == [] and r.tasks.active() == []


def test_cancel_also_wins_when_claude_fails_at_the_same_moment():
    holder = {}

    def ask(q, cancelled):
        holder["r"].tasks.cancel_all()
        return claude_ask.Answer(False, reason="timeout")                     # scheitert zufällig gerade jetzt
    r, fetched = make_research(ask)
    holder["r"] = r
    p = r.propose("Eiffelturm Höhe", speaker_verified=True)
    r.approve(p)
    assert r.execute(p).kind == "none" and fetched == []


def test_cancel_denies_a_research_that_still_waits_for_approval():
    r, fetched = make_research(lambda q, c: claude_ask.Answer(True))
    p = r.propose("Eiffelturm Höhe", speaker_verified=True)
    assert r.tasks.pending_approvals() == 1
    assert r.tasks.cancel_all() == ["Freigabe für claude.research"]
    assert not r.approve(p)                                                   # abgelehnt: kann nicht mehr freigegeben werden


# --- Pipeline ------------------------------------------------------------------------------------

class Eng:
    def synthesize(self, t):
        return t


def make_pipeline(tmp_path, text, chat=None, tasks=None, verifier=None):
    played = []
    dialog = Dialog(lambda: None)
    kill = KillSwitch(tmp_path, [])
    spk = Speaker(Eng(), played.append, lambda: kill.fired)
    stt = SimpleNamespace(transcribe=lambda pcm: SimpleNamespace(text=text))
    p = Pipeline(stt, chat or (lambda m: iter(["Antwort."])), spk, dialog, kill, verifier, tasks=tasks)
    return p, played


PCM = np.zeros(16000, dtype=np.int16)


def test_spoken_cancel_stops_running_tasks_and_confirms_without_the_llm_or_speaker_check(tmp_path):
    tasks, called = TaskRegistry(), []
    p, played = make_pipeline(tmp_path, "Abbrechen", chat=lambda m: called.append(1) or iter([]), tasks=tasks,
                              verifier=SimpleNamespace(enrolled=True, check=lambda *a, **k: pytest.fail("keine Sprecher-Prüfung nötig")))
    with tasks.running("Recherche", lambda: called.append("cancel")) as tok:
        r = p.handle(PCM)
    assert r.outcome == "cancelled" and r.reply == CANCEL_REPLY and played == [CANCEL_REPLY] and tok.cancelled()
    assert called == ["cancel"]                                               # das LLM wurde nie gefragt


def test_cancel_with_nothing_running_says_so_honestly(tmp_path):
    p, played = make_pipeline(tmp_path, "Brich das ab")
    r = p.handle(PCM)
    assert r.outcome == "cancelled" and r.reply == NOTHING_REPLY and played == [NOTHING_REPLY]


def test_the_wake_word_before_cancel_does_not_matter_and_a_long_question_is_no_cancel(tmp_path):
    p, played = make_pipeline(tmp_path, "Hey Kushim, abbrechen")
    p.wake_names = ("hey kushim", "kushim")
    assert p.handle(PCM).outcome == "cancelled"
    p2, _ = make_pipeline(tmp_path, "Recherchiere zum Abbruch der Verhandlungen zwischen den beiden Ländern im Jahr 1990")
    assert p2.handle(PCM).outcome == "spoken"


def test_kill_phrase_still_wins_over_cancel_and_locks(tmp_path):
    p, played = make_pipeline(tmp_path, "Notaus")
    r = p.handle(PCM)
    assert r.outcome == "killed" and p.kill.fired


def test_try_cancel_for_the_loop_stops_things_without_speaking(tmp_path):
    tasks = TaskRegistry()
    p, played = make_pipeline(tmp_path, "abbrechen", tasks=tasks)
    with tasks.running("Recherche") as tok:
        assert p.try_cancel(PCM) is True and tok.cancelled()
    assert played == [] and p._interrupted.is_set()                           # still: die Bestätigung kommt nach dem Ende der Antwort
    p2, _ = make_pipeline(tmp_path, "Wie spät ist es")
    assert p2.try_cancel(PCM) is False and not p2._interrupted.is_set()
    p3, _ = make_pipeline(tmp_path, "")
    assert p3.try_cancel(PCM) is False


def test_say_cancelled_speaks_even_after_an_interrupt(tmp_path):
    p, played = make_pipeline(tmp_path, "x")
    p._interrupted.set()
    p.say_cancelled()
    assert played == [CANCEL_REPLY]


# --- Schleife: Abbrechen während die Antwort läuft -----------------------------------------------

LOUD = (np.ones(FRAME) * 3000).astype(np.int16)
QUIET = np.zeros(FRAME, dtype=np.int16)


def collector():
    return UtteranceCollector(silence_ms=160, min_ms=80)


def follow():
    return UtteranceCollector(wait_ms=240, silence_ms=160, min_ms=80)


def fires_at(*idx):
    n = {"i": -1}

    def wake(frame):
        n["i"] += 1
        return n["i"] in idx
    return wake


class CancellablePipeline:
    """Aufgabe läuft lange; `try_cancel` meldet "abbrechen" bei der Äußerung des Nutzers. `stop_on_interrupt=False` ist eine
    Aufgabe wie die Claude-Recherche, die das Dazwischensprechen NICHT beendet (nur "abbrechen" tut das)."""

    def __init__(self, cancel_utterance=2, stop_on_interrupt=False):
        self.handled, self.confirmed, self.cancel_calls = [], 0, 0
        self.started, self._stop = threading.Event(), threading.Event()
        self.cancel_utterance, self.stop_on_interrupt = cancel_utterance, stop_on_interrupt

    def try_cancel(self, pcm):
        self.cancel_calls += 1
        if self.cancel_calls == self.cancel_utterance - 1:
            self._stop.set()
            return True
        return False

    def interrupt(self):
        if self.stop_on_interrupt:
            self._stop.set()

    def say_cancelled(self):
        self.confirmed += 1

    def handle(self, pcm):
        self.handled.append(len(pcm))
        self.started.set()
        self._stop.wait(timeout=5)
        return SimpleNamespace(heard="x", reply="lange Antwort", outcome="interrupted")


class Paced:
    def __init__(self, frames, started):
        self.frames, self.started = frames, started

    def __iter__(self):
        for i, f in enumerate(self.frames):
            if i == 4:
                assert self.started.wait(timeout=5)
            time.sleep(0.002)
            yield f


def test_cancel_spoken_while_the_answer_runs_is_not_queued_as_a_new_question_and_gets_one_confirmation(tmp_path):
    p, notes, shown = CancellablePipeline(cancel_utterance=2), [], []
    frames = [LOUD, LOUD, QUIET, QUIET,                       # Frage 1
              QUIET, QUIET,                                    # Antwort läuft
              LOUD, LOUD, LOUD, LOUD, QUIET, QUIET,            # Nutzer: "abbrechen"
              QUIET, QUIET, QUIET, QUIET, QUIET, QUIET]
    loop = TalkLoop(Paced(frames, p.started), p, KillSwitch(tmp_path, []), wake=fires_at(0), new_collector=collector,
                    follow_collector=follow, barge=BargeIn(level=1200, min_ms=240, frame_ms=80),
                    on_result=lambda r: shown.append(r.outcome), on_note=notes.append)
    assert loop.run() == "ended"
    assert len(p.handled) == 1                                  # "abbrechen" wurde NICHT als zweite Frage gestellt
    assert p.confirmed == 1 and "Abgebrochen." in notes and shown == ["interrupted"]


def test_a_normal_interruption_is_still_queued_as_the_next_question(tmp_path):
    p, shown = CancellablePipeline(cancel_utterance=99, stop_on_interrupt=True), []   # nie "abbrechen"; Sprechen beendet die Antwort
    frames = [LOUD, LOUD, QUIET, QUIET, QUIET, QUIET, LOUD, LOUD, LOUD, LOUD, QUIET, QUIET, QUIET, QUIET, QUIET, QUIET]
    loop = TalkLoop(Paced(frames, p.started), p, KillSwitch(tmp_path, []), wake=fires_at(0), new_collector=collector,
                    follow_collector=follow, barge=BargeIn(level=1200, min_ms=240, frame_ms=80),
                    on_result=lambda r: shown.append(r.outcome))
    loop.run()
    assert len(p.handled) == 2 and p.confirmed == 0                               # zweite Äußerung wurde die nächste Frage


# --- STT-Sperre ----------------------------------------------------------------------------------

def test_speech_to_text_never_runs_two_transcriptions_at_once():
    from kushim.voice.stt import SpeechToText
    active, peak = {"n": 0}, {"n": 0}

    class Model:
        def transcribe(self, audio, **kw):
            active["n"] += 1
            peak["n"] = max(peak["n"], active["n"])
            time.sleep(0.05)

            def segs():
                time.sleep(0.02)                                                  # auch das Lesen der Segmente gehört in die Sperre
                yield SimpleNamespace(text="abbrechen")
                active["n"] -= 1
            return segs(), SimpleNamespace(language="de", language_probability=1.0)
    stt = SpeechToText(Model())
    threads = [threading.Thread(target=lambda: stt.transcribe(np.ones(1600, dtype=np.int16))) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert peak["n"] == 1


# --- API und CLI ---------------------------------------------------------------------------------

def test_tasks_api_lists_and_cancels_with_a_token_only():
    token, tasks = new_token(), TaskRegistry()
    core = ApiCore(token)
    register_tasks(core, tasks)

    def call(type_, **kw):
        return json.loads(core.handle(json.dumps({"token": token, "type": type_, **kw})))
    assert json.loads(core.handle(json.dumps({"type": "tasks.cancel"}))) == {"ok": False, "error": "unauthorized"}
    with tasks.running("Recherche über Claude") as tok:
        assert call("tasks.list") == {"ok": True, "tasks": ["Recherche über Claude"], "pending_approvals": 0}
        assert call("tasks.cancel") == {"ok": True, "cancelled": ["Recherche über Claude"]} and tok.cancelled()
    assert call("tasks.cancel") == {"ok": True, "cancelled": []}


def test_ctrl_c_cancels_a_cli_command_quietly(tmp_path, monkeypatch, capsys):
    from kushim.config import Config
    f = tmp_path / "config.toml"
    monkeypatch.setenv("KUSHIM_CONFIG", str(f))
    Config.load(f).set_tools_enabled(["web.search"])

    def interrupted(prompt=""):
        raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", interrupted)
    import kushim.net.web as netweb
    monkeypatch.setattr(netweb, "fetch_text", lambda url: pytest.fail("nach Abbruch nichts senden"))
    assert cli.main(["search", "Eiffelturm"]) == 130
    assert "Abgebrochen." in capsys.readouterr().out
