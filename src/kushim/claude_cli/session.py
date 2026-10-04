"""Ein Claude-Lauf im Entwicklungs-Modus: starten, Status, Antwort (nächster Zug), Stopp, Notaus, Ergebnis.

Ein Lauf ist ein Zug (`claude -p`). Er endet "wartend": Claude hat geantwortet, entweder mit Rückfrage oder fertig, und die Antwort des
Nutzers setzt die Sitzung mit `--resume` fort. Es läuft höchstens EIN Claude-Prozess zugleich. Zustand liegt in `run/claude-session.json`
(atomar, nicht im Git, ohne Geheimnisse). Stopp, `abbrechen` (tasks.py) und Notaus beenden den Prozess samt Kindern; der Branch bleibt.
Der Ordner wird bei JEDEM Start neu geprüft (folders.validate_path). Claudes Text ist `Untrusted` und löst in kushim nie etwas aus.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from ..launcher import kill_tree
from ..tasks import TaskRegistry
from . import dev, folders, report, review
from .base import clean_env

STATE = Path("run") / "claude-session.json"
STOP_MARKER = Path("run") / "claude-stop"
MAX_TEXT = 20_000
POLL_S = 0.25
_EXTRA = re.compile(r"Bash\([a-z0-9_./ -]+\*\)")


def pid_alive(pid: int) -> bool:
    """Lebt der Prozess? Windows: nur abfragen (OpenProcess), NIE os.kill (das würde dort beenden)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, pid)           # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(k32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259     # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class SessionError(Exception):
    """Klartext-Grund, warum etwas nicht geht (für den Nutzer, nie mit Pfaden zu Geheimnissen)."""


@dataclass
class State:
    id: str = ""
    folder: str = ""
    folder_path: str = ""
    worktree: str = ""
    worktree_path: str = ""
    branch: str = ""
    base_sha: str = ""
    base_branch: str = ""
    claude_session: str = ""
    turn: int = 0
    status: str = ""                       # "running" | "waiting" | "failed" | "stopped"
    started: str = ""
    updated: str = ""
    last_text: str = ""
    cost_usd: float = 0.0
    seconds: float = 0.0
    offers: list[str] = field(default_factory=list)          # was kushim für diese Sitzung zusätzlich anbieten würde
    extra_allowed: list[str] = field(default_factory=list)   # vom Nutzer für diese Sitzung zusätzlich Erlaubtes
    error: str = ""
    denied: list[str] = field(default_factory=list)          # was die CLI in diesem Zug verweigert hat (kurz, für die Übersicht)
    denial_count: int = 0                  # so viele Verweigerungen meldete die CLI bisher (sie nennt die der ganzen Sitzung, nicht nur des Zuges)
    owner_pid: int = 0                     # kushim-Prozess, der den Lauf überwacht (für Status/Stopp aus einem zweiten Terminal)
    proc_pid: int = 0                      # der Claude-Prozess


_STATE_LOCK = threading.RLock()            # Lesen und Schreiben im selben Prozess nie gleichzeitig (Windows verweigert sonst os.replace)


def load_state(root: Path) -> State | None:
    with _STATE_LOCK:
        try:
            data = json.loads((root / STATE).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            known = {k: v for k, v in data.items() if k in State.__dataclass_fields__}
            return State(**known)
        except (OSError, ValueError, TypeError):
            return None


def save_state(root: Path, st: State) -> None:
    p = root / STATE
    with _STATE_LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(st), ensure_ascii=False), encoding="utf-8")
        for attempt in range(25):                                    # ein zweites Terminal liest evtl. gerade: kurz wiederholen
            try:
                os.replace(tmp, p)                                   # atomar
                return
            except PermissionError:
                if attempt == 24:
                    raise
                time.sleep(0.02)


class ClaudeSessions:
    def __init__(self, root: Path, exe: Path | None, vault: Path | None = None, home: Path | None = None,
                 popen: Callable[..., subprocess.Popen] = subprocess.Popen, kill: Callable[[int], None] = kill_tree,
                 git: review.Git = review.run_git, tasks: TaskRegistry | None = None,
                 now: Callable[[], datetime] = datetime.now, clock: Callable[[], float] = time.monotonic,
                 timeout_min: float = dev.TIMEOUT_MIN, budget: float = dev.BUDGET_USD, poll: float = POLL_S):
        self.root, self.exe, self.vault, self.home = root, exe, vault, home          # home=None: der echte Benutzerordner
        self._popen, self._kill, self._git, self._now, self._clock = popen, kill, git, now, clock
        self.tasks = tasks if tasks is not None else TaskRegistry()
        self.timeout_min, self.budget, self.poll = timeout_min, budget, poll
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()

    # --- Zustand
    def _alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def state(self) -> State | None:
        st = load_state(self.root)
        if st is not None and st.status == "running" and not self._owned_and_alive(st):      # Besitzer beendet: Lauf ist weg
            st.status, st.error = "failed", "Unterbrochen (kushim wurde beendet, der Lauf ist nicht mehr da)."
            save_state(self.root, st)
        return st

    def _owned_and_alive(self, st: State) -> bool:
        if st.owner_pid == os.getpid():
            return self._alive()                                              # eigener Lauf: lebt der Thread?
        return pid_alive(st.owner_pid)                                        # Lauf eines anderen kushim-Prozesses

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    # --- Starten und Antworten
    def start(self, folder: folders.Folder, task: str, extra_allowed: Iterable[str] = ()) -> State:
        with self._lock:
            st = self.state()
            if st is not None and st.status == "running":
                raise SessionError("Es läuft schon ein Claude-Lauf. Erst stoppen oder abwarten.")
            if self.exe is None:
                raise SessionError("Die Claude CLI wurde nicht gefunden.")
            try:
                path = folders.validate_path(folder.path, self.vault, self.home)
            except ValueError as e:
                raise SessionError(f"Der Ordner «{folder.name}» ist nicht mehr zulässig: {e}")
            try:
                base_sha = self._git(["rev-parse", "HEAD"], path).strip()
                base_branch = self._git(["rev-parse", "--abbrev-ref", "HEAD"], path).strip()
            except review.GitError:
                raise SessionError("Der Ordner ist kein nutzbares Git-Repository (kein Commit?).")
            name = dev.worktree_name(self._now())
            try:
                argv = dev.build_start_argv(self.exe, task, name, self.budget, tuple(extra_allowed))
            except ValueError as e:
                raise SessionError(str(e))
            now = self._now().isoformat(timespec="seconds")
            st = State(id=uuid.uuid4().hex[:8], folder=folder.name, folder_path=str(path), worktree=name, base_sha=base_sha,
                       base_branch=base_branch, turn=1, status="running", started=now, updated=now,
                       extra_allowed=list(extra_allowed), owner_pid=os.getpid())
            save_state(self.root, st)
            self._launch(argv, path, st, first=True)
            return st

    def answer(self, text: str, allow: Iterable[str] = ()) -> State:
        """Nächster Zug: die Antwort des Nutzers. `allow`: Muster, die kushim vorher angeboten hat (sonst Fehler)."""
        with self._lock:
            st = self.state()
            if st is None or st.status != "waiting" or not st.claude_session or not st.worktree_path:
                raise SessionError("Es wartet keine Claude-Sitzung auf eine Antwort.")
            allow = list(allow)
            for p in allow:
                if p not in st.offers or not _EXTRA.fullmatch(p):
                    raise SessionError(f"«{p}» wurde nicht angeboten und darf nicht erlaubt werden.")
            extras = list(dict.fromkeys(st.extra_allowed + allow))
            try:
                argv = dev.build_resume_argv(self.exe, text, st.claude_session, self.budget, tuple(extras))
            except ValueError as e:
                raise SessionError(str(e))
            st.extra_allowed, st.offers, st.denied, st.status, st.error, st.turn = extras, [], [], "running", "", st.turn + 1
            st.owner_pid, st.proc_pid = os.getpid(), 0
            st.updated = self._now().isoformat(timespec="seconds")
            save_state(self.root, st)
            self._launch(argv, Path(st.worktree_path), st, first=False)
            return st

    def _launch(self, argv: list[str], cwd: Path, st: State, first: bool) -> None:
        self._cancel.clear()
        (self.root / STOP_MARKER).unlink(missing_ok=True)
        self._thread = threading.Thread(target=self._run, args=(argv, cwd, st, first), daemon=True, name="kushim-claude")
        self._thread.start()

    # --- Stoppen
    def stop(self) -> bool:
        """Beendet den laufenden Zug (auch für Notaus und "abbrechen"). True, wenn etwas lief."""
        st = load_state(self.root)
        mine = self._alive()
        self._cancel.set()
        if st is None or st.status != "running":
            return mine
        marker = self.root / STOP_MARKER
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("stop", encoding="utf-8")                  # der besitzende Prozess sieht das beim nächsten Abfragen
        if not mine and not pid_alive(st.owner_pid) and pid_alive(st.proc_pid):
            self._kill(st.proc_pid)                                  # Besitzer ist weg, Claude läuft noch: direkt beenden
        return True

    # --- Der eigentliche Lauf (Hintergrund-Thread)
    def _run(self, argv: list[str], cwd: Path, st: State, first: bool) -> None:
        t0 = self._clock()
        proc = None
        with self.tasks.running("Claude (Entwicklung)", cancel=self._cancel.set) as tok:
            try:
                proc = self._popen(argv, cwd=str(cwd), env=clean_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
                st.proc_pid = proc.pid
                save_state(self.root, st)
                deadline = t0 + self.timeout_min * 60
                out = None
                marker = self.root / STOP_MARKER
                while True:
                    try:
                        out, _err = proc.communicate(timeout=self.poll)
                        break
                    except subprocess.TimeoutExpired:
                        if self._cancel.is_set() or tok.cancelled() or marker.exists():
                            self._kill(proc.pid)
                            proc.kill()
                            proc.communicate()
                            return self._finish(st, t0, status="stopped", error="Gestoppt.")
                        if self._clock() >= deadline:
                            self._kill(proc.pid)
                            proc.kill()
                            proc.communicate()
                            return self._finish(st, t0, status="failed", error=f"Zeitgrenze von {self.timeout_min:g} Minuten erreicht.")
                if self._cancel.is_set() or tok.cancelled() or marker.exists():
                    return self._finish(st, t0, status="stopped", error="Gestoppt.")
                self._finish_with_output(st, t0, first, out, proc.returncode, cwd)
            except Exception as e:                           # noqa: BLE001 (nie eine Ausnahme aus dem Thread, nur ein kurzer Grund)
                self._finish(st, t0, status="failed", error=f"Fehler: {type(e).__name__}")
            finally:
                if proc is not None and proc.poll() is None:
                    self._kill(proc.pid)

    def _finish(self, st: State, t0: float, status: str, error: str = "") -> None:
        st.status, st.error = status, error
        st.seconds += self._clock() - t0
        st.updated = self._now().isoformat(timespec="seconds")
        st.proc_pid = 0
        save_state(self.root, st)
        (self.root / STOP_MARKER).unlink(missing_ok=True)

    def _finish_with_output(self, st: State, t0: float, first: bool, out: str | None, rc: int | None, cwd: Path) -> None:
        try:
            data = json.loads(out or "")
        except ValueError:
            return self._finish(st, t0, status="failed", error="Antwort der Claude CLI nicht lesbar.")
        if not isinstance(data, dict):
            return self._finish(st, t0, status="failed", error="Antwort der Claude CLI nicht lesbar.")
        sid = data.get("session_id")
        if isinstance(sid, str) and re.fullmatch(r"[A-Za-z0-9-]{8,64}", sid):
            st.claude_session = sid
        result = data.get("result")
        st.last_text = str(result)[:MAX_TEXT] if isinstance(result, str) else ""
        cost = data.get("total_cost_usd")
        st.cost_usd += float(cost) if isinstance(cost, (int, float)) else 0.0
        denials = report.extract_denials(data)
        fresh = denials[st.denial_count:] if len(denials) >= st.denial_count else denials       # nur NEUE Verweigerungen dieses Zuges
        st.denial_count = len(denials)
        st.offers = report.offers(fresh)
        st.denied = [f"{d.tool}: {d.command}"[:120] for d in fresh][:5]
        if first:
            wt = review.find_worktree(Path(st.folder_path), st.worktree, self._git)
            if wt is not None:
                st.worktree_path, st.branch = str(wt.path), wt.branch
        failed = rc != 0 or data.get("is_error") is True
        if failed:
            return self._finish(st, t0, status="failed", error="Claude meldet einen Fehler (Limit, Anmeldung oder Budget).")
        if not st.worktree_path or not st.claude_session:
            return self._finish(st, t0, status="failed", error="Worktree oder Sitzung nicht gefunden; Antworten ist nicht möglich.")
        self._finish(st, t0, status="waiting")

    # --- Ergebnis
    def result(self) -> tuple[State, review.Review, report.Overview] | None:
        st = self.state()
        if st is None:
            return None
        folder = Path(st.folder_path)
        wt = Path(st.worktree_path) if st.worktree_path else None
        if wt is None:
            found = review.find_worktree(folder, st.worktree, self._git)
            wt = found.path if found else None
        rv = review.review(folder, wt, st.base_sha, st.base_branch, self._git)
        ov = report.build_overview(report.parse(st.last_text), rv, st.cost_usd, st.seconds, st.turn, st.offers, st.denied)
        return st, rv, ov
