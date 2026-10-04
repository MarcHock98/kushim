"""Claude-Sitzungen (Entwicklungs-Modus): Lauf, Stopp, Antwort, Zustand, Steuerung mit Freigabe. Kein echter Claude-Aufruf."""
import json
import os
import subprocess
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from kushim.claude_cli import dev, session
from kushim.claude_cli.base import Auth
from kushim.claude_cli.control import Control, dev_reviewer, normalize_task, secret_reasons
from kushim.claude_cli.folders import Folder
from kushim.claude_cli.review import GitError
from kushim.claude_cli.session import ClaudeSessions, SessionError, State, load_state, pid_alive, save_state
from kushim.config import Config
from kushim.privacy import EgressGate
from kushim.safety.gate import ActionRequest, Decision
from kushim.tasks import TaskRegistry
from kushim.tools.registry import CLAUDE_CODE, ToolRegistry, claude_code_tool, default_tools
from kushim.web.sanitize import Untrusted

EXE = Path("C:/fake/claude.exe")
ABO = Auth(True, "claude.ai")
NOW = datetime(2026, 10, 4, 12, 0, 0)
WORKTREE = "kushim-20261004-120000"
SID = "0123abcd-ef01-2345-6789-abcdef012345"
FULL = "## Zusammenfassung\nTimer gebaut, 5 Tests.\n\n## Rückfrage\nAuch per Sprache?\n\n## Nächste Schritte\n- Sprache\n- UI"


@pytest.fixture(autouse=True)
def neutral_environment(monkeypatch):
    for var in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.delenv(var, raising=False)


def result_json(text=FULL, denials=None, cost=0.35, error=False, sid=SID):
    return json.dumps({"type": "result", "is_error": error, "result": text, "session_id": sid, "total_cost_usd": cost,
                       "permission_denials": denials if denials is not None else
                       [{"tool_name": "Bash", "tool_input": {"command": "pytest -k timer"}}]})


class FakeProc:
    def __init__(self, out="", rc=0, hang=False, pid=4000):
        self.out, self.returncode, self.hang, self.pid, self.killed = out, rc, hang, pid, False

    def communicate(self, timeout=None):
        if self.hang and not self.killed:
            time.sleep(min(timeout or 0.01, 0.01))
            raise subprocess.TimeoutExpired("claude", timeout)
        return self.out, ""

    def kill(self):
        self.killed = True

    def poll(self):
        return None if (self.hang and not self.killed) else self.returncode


class Popper:
    def __init__(self, *procs, error=None):
        self.procs, self.calls, self.error = list(procs), [], error

    def __call__(self, argv, **kw):
        self.calls.append({"argv": argv, "kw": kw})
        if self.error:
            raise self.error
        return self.procs.pop(0)


def fake_git(worktree_path):
    def git(args, cwd):
        a = tuple(args)
        if a[:2] == ("rev-parse", "HEAD"):
            return "aaaa\n"
        if a[:2] == ("rev-parse", "--abbrev-ref"):
            return "master\n" if str(cwd) != str(worktree_path) else "worktree-" + WORKTREE + "\n"
        if a[:2] == ("worktree", "list"):
            return f"worktree {cwd}\nHEAD aaaa\nbranch refs/heads/master\n\nworktree {worktree_path}\nHEAD bbbb\nbranch refs/heads/worktree-{WORKTREE}\n"
        if a[:2] == ("diff", "--name-status"):
            return "M\tREADME.md\nA\ttools/timer.py\n"
        if a[:2] == ("diff", "--shortstat"):
            return " 2 files changed, 40 insertions(+)\n"
        if a[:2] == ("status", "--porcelain"):
            return ""
        raise GitError("unbekannt")
    return git


@pytest.fixture()
def env(tmp_path):
    project = tmp_path / "proj"
    (project / ".git").mkdir(parents=True)
    worktree = project / ".claude" / "worktrees" / WORKTREE
    worktree.mkdir(parents=True)                       # der Worktree existiert (Claude hat ihn angelegt)
    root = tmp_path / "root"
    root.mkdir()
    return SimpleNamespace(root=root, project=project, worktree=worktree, folder=Folder("kushim", project), tmp=tmp_path)


def make(env, *procs, **kw):
    popper = Popper(*procs)
    s = ClaudeSessions(env.root, EXE, vault=env.tmp / "vault", home=env.tmp / "home", popen=popper, kill=kw.pop("kill", lambda pid: None),
                       git=fake_git(env.worktree), now=lambda: NOW, poll=0.01, **kw)
    return s, popper


def finish(s):
    s.join(10)
    return s.state()


# --- Lauf ----------------------------------------------------------------------------------------

def test_first_turn_runs_in_the_project_with_a_new_worktree_and_ends_waiting(env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-geheim")
    s, popper = make(env, FakeProc(result_json()))
    started = s.start(env.folder, "Baue den Timer")
    assert started.status == "running" and started.worktree == WORKTREE and started.base_sha == "aaaa" and started.owner_pid == os.getpid()
    st = finish(s)
    assert st.status == "waiting" and st.claude_session == SID and st.turn == 1 and st.cost_usd == 0.35 and st.error == ""
    assert st.worktree_path == str(env.worktree) and st.branch == f"worktree-{WORKTREE}"
    assert st.offers == ["Bash(pytest *)"] and "Timer gebaut" in st.last_text
    (call,) = popper.calls
    assert call["argv"][:5] == [str(EXE), "-p", "Baue den Timer", "-w", WORKTREE] and call["kw"]["cwd"] == str(env.project.resolve())
    assert "ANTHROPIC_API_KEY" not in call["kw"]["env"] and call["kw"]["stdin"] == subprocess.DEVNULL
    for bad in dev.FORBIDDEN_FLAGS:
        assert bad not in call["argv"]
    assert not (env.root / session.STOP_MARKER).exists()


def test_result_combines_claudes_text_with_facts_from_git(env):
    s, _ = make(env, FakeProc(result_json()))
    s.start(env.folder, "Baue den Timer")
    finish(s)
    st, rv, ov = s.result()
    assert rv.files == [("M", "README.md"), ("A", "tools/timer.py")] and rv.base_unchanged and rv.branch == "worktree-" + WORKTREE
    assert ov.done == "Timer gebaut, 5 Tests." and ov.question == "Auch per Sprache?" and ov.next_steps == ["Sprache", "UI"]
    assert ov.permission_questions and "Bash(pytest *)" in ov.permission_questions[0] and not ov.protected
    assert ClaudeSessions(env.root, EXE, git=fake_git(env.worktree)).result() is not None
    assert ClaudeSessions(env.root.parent / "leer", EXE).result() is None


def test_only_one_run_at_a_time_and_stop_ends_it(env):
    kills = []
    proc = FakeProc(hang=True, pid=777)
    s, _ = make(env, proc, kill=kills.append)
    s.start(env.folder, "lange Arbeit")
    with pytest.raises(SessionError, match="schon ein Claude-Lauf"):
        s.start(env.folder, "noch eine")
    assert s.stop() is True
    st = finish(s)
    assert st.status == "stopped" and st.error == "Gestoppt." and 777 in kills and proc.killed
    assert not (env.root / session.STOP_MARKER).exists() and s.tasks.active() == []


def test_the_run_registers_as_a_cancellable_task_so_spoken_cancel_works(env):
    kills, proc = [], FakeProc(hang=True, pid=555)
    tasks = TaskRegistry()
    s, _ = make(env, proc, kill=kills.append, tasks=tasks)
    s.start(env.folder, "lange Arbeit")
    deadline = time.time() + 5
    while not tasks.active() and time.time() < deadline:
        time.sleep(0.01)
    assert tasks.active() == ["Claude (Entwicklung)"]
    assert tasks.cancel_all() == ["Claude (Entwicklung)"]
    assert finish(s).status == "stopped" and 555 in kills


def test_time_limit_ends_the_run(env):
    kills = []
    s, _ = make(env, FakeProc(hang=True, pid=9), kill=kills.append, timeout_min=0.0001)
    s.start(env.folder, "x")
    st = finish(s)
    assert st.status == "failed" and "Zeitgrenze" in st.error and 9 in kills


@pytest.mark.parametrize("proc,reason", [
    (FakeProc(result_json(error=True), rc=1), "Claude meldet einen Fehler"),
    (FakeProc("kein json"), "nicht lesbar"), (FakeProc("[]"), "nicht lesbar"),
    (FakeProc(result_json(sid="kurz")), "Worktree oder Sitzung nicht gefunden")])
def test_failures_end_failed_with_a_short_reason(env, proc, reason):
    s, _ = make(env, proc)
    s.start(env.folder, "x")
    st = finish(s)
    assert st.status == "failed" and reason in st.error


def test_a_failing_process_start_is_reported_without_details(env):
    s = ClaudeSessions(env.root, EXE, home=env.tmp / "home", popen=Popper(error=OSError("C:\\geheim")), kill=lambda p: None, git=fake_git(env.worktree), now=lambda: NOW, poll=0.01)
    s.start(env.folder, "x")
    st = finish(s)
    assert st.status == "failed" and st.error == "Fehler: OSError" and "geheim" not in st.error


def test_start_is_refused_for_unusable_folders_cli_or_git(env):
    s, popper = make(env, FakeProc(result_json()))
    no_git = env.tmp / "ohne"
    no_git.mkdir()
    with pytest.raises(SessionError, match="nicht mehr zulässig"):
        s.start(Folder("x", no_git), "x")
    with pytest.raises(SessionError, match="nicht mehr zulässig"):
        s.start(Folder("x", env.tmp / "gibt-es-nicht"), "x")
    vault = env.tmp / "vault"
    (vault / ".git").mkdir(parents=True)
    with pytest.raises(SessionError, match="nicht mehr zulässig"):
        s.start(Folder("v", vault), "x")                                         # der Vault ist nie freigebbar
    with pytest.raises(SessionError, match="nicht gefunden"):
        ClaudeSessions(env.root, None).start(env.folder, "x")
    broken = ClaudeSessions(env.root, EXE, home=env.tmp / "home", popen=popper, git=lambda a, c: (_ for _ in ()).throw(GitError("x")))
    with pytest.raises(SessionError, match="Git-Repository"):
        broken.start(env.folder, "x")
    with pytest.raises(SessionError):
        s.start(env.folder, "---")
    assert popper.calls == []


# --- Antworten (nächster Zug) --------------------------------------------------------------------

def test_answer_continues_the_same_session_in_the_worktree_and_only_allows_what_was_offered(env):
    s, popper = make(env, FakeProc(result_json()), FakeProc(result_json(denials=[], cost=0.10)))
    s.start(env.folder, "Baue den Timer")
    finish(s)
    for bad in ("Bash(git push*)", "Bash(rm *)", "Bash(pytest -k*)", "Bash(curl*)"):
        with pytest.raises(SessionError, match="nicht angeboten"):
            s.answer("Ja, mach", allow=[bad])
    assert len(popper.calls) == 1                                                  # nichts wurde gestartet
    st = s.answer("Ja, auch per Sprache", allow=["Bash(pytest *)"])
    assert st.status == "running" and st.turn == 2 and st.extra_allowed == ["Bash(pytest *)"] and st.offers == []
    done = finish(s)
    assert done.status == "waiting" and done.turn == 2 and done.cost_usd == pytest.approx(0.45)
    argv, kw = popper.calls[1]["argv"], popper.calls[1]["kw"]
    assert argv[:5] == [str(EXE), "-p", "Ja, auch per Sprache", "--resume", SID] and "-w" not in argv
    assert kw["cwd"] == str(env.worktree) and "Bash(pytest *)" in argv[argv.index("--allowedTools") + 1].split(",")


def test_only_new_denials_count_per_turn_because_the_cli_reports_the_whole_session(env):
    push = {"tool_name": "Bash", "tool_input": {"command": "git push origin master"}}
    pytest_k = {"tool_name": "Bash", "tool_input": {"command": "pytest -k timer"}}
    other = {"tool_name": "Bash", "tool_input": {"command": "git diff HEAD~1"}}
    s, popper = make(env, FakeProc(result_json(denials=[pytest_k, push])), FakeProc(result_json(denials=[pytest_k, push])),
                     FakeProc(result_json(denials=[pytest_k, push, other])))
    s.start(env.folder, "x")
    st = finish(s)
    assert st.offers == ["Bash(pytest *)"] and len(st.denied) == 2 and st.denial_count == 2          # Zug 1: beides neu
    s.answer("weiter", allow=["Bash(pytest *)"])
    st = finish(s)
    assert st.offers == [] and st.denied == [] and st.denial_count == 2                               # Zug 2: nichts Neues, keine Altlast
    s.answer("noch einmal")
    st = finish(s)
    assert st.denied == ["Bash: git diff HEAD~1"] and st.offers == ["Bash(git diff *)"] and st.denial_count == 3


def test_answer_needs_a_waiting_session(env):
    s, _ = make(env, FakeProc(hang=True))
    with pytest.raises(SessionError, match="wartet keine"):
        s.answer("x")                                                              # noch nichts gestartet
    s.start(env.folder, "x")
    with pytest.raises(SessionError, match="wartet keine"):
        s.answer("x")                                                              # läuft noch
    s.stop()
    finish(s)
    with pytest.raises(SessionError, match="wartet keine"):
        s.answer("x")                                                              # gestoppt


# --- Zustand über Prozesse hinweg ----------------------------------------------------------------

def test_a_run_whose_owner_process_is_gone_is_marked_failed_but_a_live_owner_is_left_alone(env):
    save_state(env.root, State(id="a", folder="k", status="running", owner_pid=2 ** 22 + 12345, started="x"))
    s = ClaudeSessions(env.root, EXE)
    st = s.state()
    assert st.status == "failed" and "Unterbrochen" in st.error and load_state(env.root).status == "failed"
    save_state(env.root, State(id="b", folder="k", status="running", owner_pid=os.getppid(), started="x"))
    assert s.state().status == "running" and load_state(env.root).status == "running"          # Besitzer lebt: nicht anfassen


def test_stop_from_a_second_terminal_leaves_a_marker_for_the_live_owner(env):
    save_state(env.root, State(id="b", folder="k", status="running", owner_pid=os.getppid(), proc_pid=4242, started="x"))
    kills = []
    other = ClaudeSessions(env.root, EXE, kill=kills.append)
    assert other.stop() is True
    assert (env.root / session.STOP_MARKER).read_text(encoding="utf-8") == "stop" and kills == []       # der Besitzer beendet es selbst


def test_stop_kills_a_claude_process_whose_owner_is_gone(env):
    save_state(env.root, State(id="b", folder="k", status="running", owner_pid=2 ** 22 + 99, proc_pid=os.getpid(), started="x"))
    kills = []
    assert ClaudeSessions(env.root, EXE, kill=kills.append).stop() is True and kills == [os.getpid()]


def test_stop_without_anything_running_does_nothing(env):
    s = ClaudeSessions(env.root, EXE)
    assert s.stop() is False and not (env.root / session.STOP_MARKER).exists()


def test_the_owner_sees_the_marker_of_a_second_terminal_and_stops(env):
    kills, proc = [], FakeProc(hang=True, pid=31)
    s, _ = make(env, proc, kill=kills.append)
    s.start(env.folder, "lange Arbeit")
    time.sleep(0.05)
    (env.root / session.STOP_MARKER).write_text("stop", encoding="utf-8")        # wie `kushim claude stop` im zweiten Fenster
    assert finish(s).status == "stopped" and 31 in kills


def test_state_file_is_atomic_and_tolerates_junk(env):
    save_state(env.root, State(id="z", folder="k", status="waiting"))
    assert load_state(env.root).id == "z" and not list((env.root / "run").glob("*.tmp"))
    p = env.root / session.STATE
    for junk in ("{kaputt", "[]", "", "5"):
        p.write_text(junk, encoding="utf-8")
        assert load_state(env.root) is None
    p.write_text(json.dumps({"id": "q", "unbekannt": 1, "status": "waiting"}), encoding="utf-8")
    assert load_state(env.root).id == "q"                                          # unbekannte Felder werden ignoriert


def test_pid_alive_is_safe_and_correct():
    assert pid_alive(os.getpid()) and not pid_alive(0) and not pid_alive(-5) and not pid_alive(2 ** 22 + 777)


# --- Steuerung mit Freigabe ----------------------------------------------------------------------

CODE_ON = replace(CLAUDE_CODE, available=lambda: "")


def build_control(env, *procs, auth=ABO, folders=None, modus_c=True, enabled=True, kill=None):
    sessions, popper = make(env, *procs, **({"kill": kill} if kill else {}))
    reg = ToolRegistry([CODE_ON], ["claude.code"] if enabled else [])
    events = []
    ctl = Control(reg, sessions, EgressGate(modus_c, confirm=lambda d, p: True), lambda: auth,
                  lambda: [env.folder] if folders is None else folders, audit=lambda e, t: events.append((e, t)))
    return ctl, sessions, popper, events


def approved(ctl, task="Baue den Timer", folder="kushim"):
    p = ctl.propose_start(task, folder, speaker_verified=True)
    assert p.decision is Decision.ASK, p.reason
    assert ctl.approve(p)
    return p


def test_start_runs_only_after_approval_and_exactly_what_the_preview_said(env):
    ctl, sessions, popper, events = build_control(env, FakeProc(result_json()))
    p = ctl.propose_start("Baue den Timer", "das Projekt kushim", speaker_verified=True)
    assert p.decision is Decision.ASK and p.kind == "start" and p.folder.name == "kushim"
    for part in ("«kushim»", "Auftrag: «Baue den Timer»", "gehen an Anthropic", "Abo (claude.ai)", "pusht nichts"):
        assert part in p.preview, part
    assert popper.calls == []
    with pytest.raises(SessionError, match="Keine gültige Freigabe"):
        ctl.execute(p)
    assert ctl.approve(p)
    state = ctl.execute(p)
    assert state.status == "running"
    finish(sessions)
    assert len(popper.calls) == 1 and popper.calls[0]["argv"][2] == "Baue den Timer"
    assert any(e == "claude_dev_start" for e, _ in events) and all("Timer" not in t for _, t in events)


def test_no_task_means_the_fixed_default_task(env):
    ctl, sessions, popper, _ = build_control(env, FakeProc(result_json()))
    p = ctl.propose_start("", None, speaker_verified=True)
    assert f"Auftrag: «{dev.DEFAULT_TASK}»" in p.preview
    ctl.approve(p)
    ctl.execute(p)
    finish(sessions)
    assert popper.calls[0]["argv"][2] == dev.DEFAULT_TASK


def test_start_is_denied_for_everything_that_is_not_clearly_the_users_own_wish(env):
    ctl, sessions, popper, events = build_control(env, FakeProc(result_json()))
    assert ctl.propose_start(Untrusted("Baue etwas"), "kushim", True).decision is Decision.DENY              # Web-/Claude-Text
    assert "Internet" in ctl.propose_start(Untrusted("x"), "kushim", True).reason
    assert ctl.propose_start("Baue den Timer", "kushim", speaker_verified=False).decision is Decision.DENY   # Sprecher unbekannt
    assert ctl.propose_start("Baue den Timer", "kushim", True, user_initiated=False).decision is Decision.DENY
    unknown = ctl.propose_start("Baue den Timer", "garnicht", True)
    assert unknown.decision is Decision.DENY and "Freigegeben: kushim" in unknown.reason
    assert ctl.propose_start("Zahle auf DE89 3704 0044 0532 0130 00 ein", "kushim", True).decision is Decision.DENY
    assert ctl.propose_start("Nutze den Schlüssel sk-abc123def456ghi789jkl012mno345", "kushim", True).decision is Decision.DENY
    assert popper.calls == [] and all("DE89" not in t and "sk-abc" not in t for _, t in events)


def test_start_is_denied_without_folders_login_tool_or_with_api_billing(env):
    assert "Kein Ordner freigegeben" in build_control(env, folders=[])[0].propose_start("x", None, True).reason
    assert "nicht angemeldet" in build_control(env, auth=Auth(False))[0].propose_start("x", "kushim", True).reason
    assert build_control(env, enabled=False)[0].propose_start("x", "kushim", True).decision is Decision.DENY
    api = build_control(env, auth=Auth(True, "api_key"))[0].propose_start("x", "kushim", True)
    assert api.decision is Decision.DENY and "API-Konto" in api.reason and api.approval is None


def test_modus_a_is_a_second_lock_and_a_changed_proposal_is_refused(env):
    ctl, sessions, popper, _ = build_control(env, FakeProc(result_json()), modus_c=False)
    with pytest.raises(SessionError, match="Modus A"):
        ctl.execute(approved(ctl))
    assert popper.calls == []
    ctl2, s2, p2, _ = build_control(env, FakeProc(result_json()))
    p = approved(ctl2)
    p.task = "Etwas ganz anderes als freigegeben"                                 # nach der Freigabe verändert
    with pytest.raises(SessionError, match="passt nicht mehr"):
        ctl2.execute(p)
    assert p2.calls == []


def test_approval_is_single_use_and_void_when_denied_tampered_or_killed(env):
    ctl, sessions, popper, _ = build_control(env, FakeProc(result_json()), FakeProc(result_json()), FakeProc(result_json()))
    p = approved(ctl)
    ctl.execute(p)
    finish(sessions)
    with pytest.raises(SessionError):
        ctl.execute(p)                                                             # einmalig
    p2 = ctl.propose_start("Baue den Timer", "kushim", True)
    assert ctl.deny(p2)
    with pytest.raises(SessionError):
        ctl.execute(p2)
    p3 = approved(ctl)
    p3.approval.request.description = "etwas anderes"
    with pytest.raises(SessionError):
        ctl.execute(p3)
    p4 = approved(ctl)
    ctl.queue.gate.kill()
    with pytest.raises(SessionError):
        ctl.execute(p4)
    assert len(popper.calls) == 1


def test_spoken_cancel_rejects_a_proposal_that_still_waits_for_approval(env):
    ctl, sessions, popper, _ = build_control(env, FakeProc(result_json()))
    p = ctl.propose_start("Baue den Timer", "kushim", True)
    assert sessions.tasks.pending_approvals() == 1
    assert sessions.tasks.cancel_all() == ["Freigabe für claude.code"]
    assert not ctl.approve(p) and popper.calls == []


def test_answer_needs_a_waiting_session_and_only_offered_permissions(env):
    ctl, sessions, popper, _ = build_control(env, FakeProc(result_json()), FakeProc(result_json(denials=[])))
    assert "wartet keine" in ctl.propose_answer("Ja", [], True).reason
    ctl.execute(approved(ctl))
    finish(sessions)
    assert ctl.propose_answer("Ja", ["Bash(git push*)"], True).decision is Decision.DENY
    assert ctl.propose_answer("", [], True).decision is Decision.DENY
    assert ctl.propose_answer(Untrusted("Ja"), [], True).decision is Decision.DENY               # Claudes eigener Text beantwortet nie
    assert ctl.propose_answer("Ja", [], speaker_verified=False).decision is Decision.DENY
    assert ctl.propose_answer("Mein Konto DE89 3704 0044 0532 0130 00", [], True).decision is Decision.DENY
    p = ctl.propose_answer("Ja, auch per Sprache", ["Bash(pytest *)"], speaker_verified=True)
    assert p.decision is Decision.ASK and p.kind == "answer"
    assert "Claude antwortet" in p.preview and "Zusätzlich für diese Sitzung erlaubt: Bash(pytest *)" in p.preview
    assert len(popper.calls) == 1
    assert ctl.approve(p)
    ctl.execute(p)
    finish(sessions)
    argv = popper.calls[1]["argv"]
    assert argv[:5] == [str(EXE), "-p", "Ja, auch per Sprache", "--resume", SID] and "Bash(pytest *)" in argv[argv.index("--allowedTools") + 1]


def test_reviewer_is_an_independent_second_check_for_secrets_and_odd_previews():
    bad = ActionRequest("claude.code", dev.preview_text("k", "Zahle DE89 3704 0044 0532 0130 00", "w", "claude.ai", 2, 45), user_initiated=True, speaker_verified=True)
    assert dev_reviewer(None, bad)
    ok = ActionRequest("claude.code", dev.preview_text("k", "Baue den Timer", "w", "claude.ai", 2, 45), user_initiated=True, speaker_verified=True)
    assert dev_reviewer(None, ok) == set()
    assert dev_reviewer(None, ActionRequest("claude.code", "irgendein anderer Text"))
    assert normalize_task("  a \n\t b  ") == "a b" and len(normalize_task("x" * 5000)) == 1000
    assert secret_reasons("Baue den Timer in C:/Users/x/projekt") == []                # Pfade und E-Mails sind im Entwickeln normal
    assert secret_reasons("a@b.de und +49 170 1234567") == []


# --- Registry und Konfiguration ------------------------------------------------------------------

def test_claude_code_tool_availability_matrix():
    assert "Modus C" in claude_code_tool(None).available() and CLAUDE_CODE.sends_data_out and CLAUDE_CODE.spec.external_effect
    cfg = SimpleNamespace(claude_enabled=False, claude_folders=())
    cache = SimpleNamespace(get=lambda: ABO)
    assert "Modus C" in claude_code_tool(cfg, cache).available()
    cfg.claude_enabled = True
    assert "Kein Ordner" in claude_code_tool(cfg, cache).available()
    cfg.claude_folders = ("kaputt", "Gross|C:/x")
    assert "Kein Ordner" in claude_code_tool(cfg, cache).available()                 # nur gültige Einträge zählen
    cfg.claude_folders = ("kushim|C:/x",)
    assert claude_code_tool(cfg, cache).available() == ""
    assert "nicht gefunden" in claude_code_tool(cfg, SimpleNamespace(get=lambda: Auth(False, error="not_installed"))).available()
    assert "angemeldet" in claude_code_tool(cfg, SimpleNamespace(get=lambda: Auth(False))).available()
    assert [t.name for t in default_tools(cfg, cache)] == ["web.search", "claude.research", "claude.code"]
    assert not ToolRegistry(default_tools()).is_active("claude.code")                # Standard: aus


def test_claude_folders_roundtrip_keeps_the_rest_and_ignores_junk(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('[llm]\nmodel = "qwen2.5:7b"\n\n[claude]\nfolders = []\n', encoding="utf-8")
    c = Config.load(f)
    assert c.claude_folders == ()
    c.set_claude_folders(["kushim|C:/Users/x/kushim", "web|C:/Users/x/Mein Projekt"])
    again = Config.load(f)
    assert again.claude_folders == ("kushim|C:/Users/x/kushim", "web|C:/Users/x/Mein Projekt") and again.llm_model == "qwen2.5:7b"
    assert not list(tmp_path.glob("*.tmp")) and f.read_text(encoding="utf-8").count("[claude]") == 1
    for bad in (["ohne-trenner"], ["a|b\nc|d"], [5]):
        with pytest.raises(ValueError):
            c.set_claude_folders(bad)
    assert Config.load(f).claude_folders == again.claude_folders                     # Fehler ändern nichts
    for junk in ('[claude]\nfolders = "kushim|C:/x"\n', '[claude]\nfolders = [1, "ohne"]\n', "[claude]\nfolders = [[1]]\n"):
        f.write_text(junk, encoding="utf-8")
        assert Config.load(f).claude_folders == ()
    g = tmp_path / "neu.toml"
    Config(path=g).set_claude_folders(["a|C:/a"])
    assert Config.load(g).claude_folders == ("a|C:/a",)


# --- Live-Ansicht
def test_live_view_formats_events_and_strips_escape_codes():
    from kushim.claude_cli.watch import format_event, last_result
    ev = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Ich lese \x1b]0;evil\x07 die README"},
        {"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q"}}]}})
    lines = format_event(ev)
    assert "\x1b" not in "".join(lines) and any("Bash: pytest -q" in l for l in lines)
    assert last_result("x\n" + result_json() + "\nnoise") is not None
    assert last_result("nur\nText") is None
