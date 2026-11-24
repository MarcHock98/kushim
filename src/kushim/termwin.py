"""macOS: ein Programm in einem eigenen, sichtbaren Terminal-Fenster starten (Gegenstück zu `cmd.exe /k` + CREATE_NEW_CONSOLE).

Windows gibt kushim ein Fenster-Prozess-Objekt zurück, auf das es warten kann. macOS öffnet Terminal-Fenster nur über
`open -a Terminal <datei>.command`; `open` endet sofort. Darum:

1. kushim schreibt `run/<name>.command` (nur für den Nutzer lesbar, 0700). Inhalt: Fenstertitel setzen und
   `exec <kushim-python> -m kushim.termwin --run <name> --env <art> --cwd <ordner> -- <befehl ...>`. Alle Teile mit
   `shlex.quote`; die Datei enthält nur Pfade, Sitzungs-ID und feste Schalter, nie Schlüssel oder Token.
2. Im Fenster legt dieser Helfer seine PID in `run/<name>.pid`, löscht die `.command`-Datei und startet den Befehl als Kind
   (gleiches Terminal). Die Umgebung baut er SELBST aus der Login-Umgebung des Fensters (`--env claude`: `claude_env()`,
   gefiltert wie unter Windows; `--env restart`: `restart_env()`). So steht nie eine Umgebungsvariable in einer Datei.
3. Endet der Befehl, bleibt das Fenster wie bei `cmd /k` offen, bis Enter gedrückt oder das Fenster geschlossen wird
   (Claude Code kann sich in seinen Hintergrund-Dienst abkoppeln). Fenster schließen = SIGHUP = Helfer und Kind enden.
4. kushim beobachtet das Fenster über `TerminalWindow` (`poll`/`wait`/`pid`): lebt die PID aus `run/<name>.pid`, ist das
   Fenster offen. Beenden: `procflags.kill_tree(pid)`.
Nur lokal: `open` und das Terminal des Nutzers, kein Netz, keine AppleScript-Steuerung (keine Automations-Freigabe nötig).
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Sequence

RUN = Path("run")
START_TIMEOUT = 60.0            # so lange darf Terminal brauchen, bis der Helfer im Fenster läuft
POLL = 0.5
ENV_KINDS = ("claude", "restart", "plain")
_NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


def is_mac() -> bool:
    return sys.platform == "darwin"


def _paths(root: Path, name: str) -> tuple[Path, Path]:
    if not _NAME.fullmatch(name):
        raise ValueError(f"ungültiger Fenstername {name!r}")
    return root / RUN / f"{name}.command", root / RUN / f"{name}.pid"


def script_text(name: str, title: str, cwd: Path, argv: Sequence[str], env_kind: str, root: Path,
                python: str = sys.executable) -> str:
    """Inhalt der `.command`-Datei. Nur feste Teile und `shlex.quote`-te Werte; kein Befehls-String aus Eingaben."""
    if env_kind not in ENV_KINDS:
        raise ValueError(f"unbekannte Umgebung {env_kind!r}")
    safe_title = re.sub(r"[^A-Za-z0-9 ._-]", "", title)[:60]
    helper = [python, "-P", "-m", "kushim.termwin", "--run", name, "--root", str(root), "--env", env_kind, "--cwd", str(cwd), "--",
              *map(str, argv)]
    return ("#!/bin/sh\n"
            f"printf '\\033]0;%s\\007' {shlex.quote(safe_title)}\n"
            f"cd {shlex.quote(str(root))} || exit 1\n"
            f"exec {' '.join(shlex.quote(a) for a in helper)}\n")


class TerminalWindow:
    """Ein von kushim geöffnetes Terminal-Fenster, beobachtet über die PID des Helfers (siehe Moduldoku).
    Verhält sich für kushim wie `subprocess.Popen`: `pid`, `poll()` (None = offen), `wait()`."""

    def __init__(self, pid_file: Path, since: float, start_timeout: float = START_TIMEOUT,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep,
                 alive: Callable[[int], bool] | None = None):
        from .safety.procs import pid_alive
        self._pid_file, self._since, self._timeout = pid_file, since, start_timeout
        self._clock, self._sleep, self._alive = clock, sleep, alive or pid_alive
        self._pid: int | None = None
        self.returncode: int | None = None

    @property
    def pid(self) -> int | None:
        if self._pid is None:
            self._pid = self._read_pid()
        return self._pid

    def _read_pid(self) -> int | None:
        try:
            if self._pid_file.stat().st_mtime < self._since - 1.0:      # Rest eines früheren Fensters
                return None
            text = self._pid_file.read_text(encoding="ascii").strip()
        except (OSError, UnicodeDecodeError):
            return None
        return int(text) if text.isdigit() and int(text) > 0 else None

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        pid = self.pid
        if pid is None:
            if self._clock() - self._since > self._timeout:
                self.returncode = 1                   # Fenster ist nie gestartet
            return self.returncode
        if not self._alive(pid):
            self.returncode = 0
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        end = None if timeout is None else self._clock() + timeout
        while self.poll() is None:
            if end is not None and self._clock() >= end:
                raise subprocess.TimeoutExpired("terminal", timeout)
            self._sleep(POLL)
        return self.returncode  # type: ignore[return-value]

    def terminate(self) -> None:
        pid = self.pid
        if pid is not None:
            from .procflags import kill_tree
            kill_tree(pid)

    kill = terminate


def open_window(root: Path, name: str, title: str, argv: Sequence[str], cwd: Path, env_kind: str,
                run: Callable[..., Any] = subprocess.run, python: str = sys.executable,
                clock: Callable[[], float] = time.time) -> TerminalWindow:
    """Öffnet `argv` in einem neuen Terminal-Fenster (macOS). OSError, wenn `open` scheitert."""
    command, pid_file = _paths(root, name)
    command.parent.mkdir(parents=True, exist_ok=True)
    pid_file.unlink(missing_ok=True)
    since = clock()
    tmp = command.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o700)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(script_text(name, title, cwd, argv, env_kind, root, python))
    os.chmod(tmp, 0o700)
    os.replace(tmp, command)
    r = run(["open", "-a", "Terminal", str(command)], capture_output=True, text=True, timeout=30, check=False)
    if getattr(r, "returncode", 1) != 0:
        command.unlink(missing_ok=True)
        raise OSError("Terminal-Fenster konnte nicht geöffnet werden (open -a Terminal)")
    return TerminalWindow(pid_file, since, clock=clock)


# --- Helfer im Fenster ---------------------------------------------------------------------------------------------------

def child_env(kind: str, base: dict[str, str] | None = None) -> dict[str, str]:
    if kind == "claude":
        from .channel.launch import claude_env
        return claude_env(base)
    if kind == "restart":
        from .channel.launch import restart_env
        return restart_env(base)
    return dict(os.environ if base is None else base)


def helper_main(argv: list[str] | None = None, popen: Callable[..., Any] = subprocess.Popen,
                wait_close: Callable[[], None] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="kushim.termwin")
    ap.add_argument("--run", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--env", choices=ENV_KINDS, required=True)
    ap.add_argument("--cwd", required=True)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        print("kushim: kein Befehl.", file=sys.stderr)
        return 2
    command, pid_file = _paths(Path(args.root), args.run)
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = pid_file.with_suffix(".tmp")
    tmp.write_text(str(os.getpid()), encoding="ascii")
    os.replace(tmp, pid_file)
    command.unlink(missing_ok=True)              # einmalig: die Startdatei wird nicht wiederverwendet
    import signal
    # Strg+C im Fenster gilt dem Kind (Claude Code), nicht dem Helfer. Ein eigener (leerer) Handler statt SIG_IGN: Handler
    # gehen beim exec verloren, das Kind bekommt also wieder das normale Verhalten; ein ignoriertes Signal würde es erben.
    signal.signal(signal.SIGINT, lambda *_a: None)
    try:
        proc = popen(cmd, cwd=args.cwd, env=child_env(args.env))
        rc = proc.wait()
    except OSError as e:
        print(f"kushim: Start nicht möglich ({type(e).__name__}).", file=sys.stderr)
        rc = 127
    print(f"\n[{cmd[0].rsplit('/', 1)[-1]} beendet] Enter drücken oder das Fenster schließen; das beendet auch kushim.",
          flush=True)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    try:
        (wait_close or (lambda: input()))()
    except (EOFError, KeyboardInterrupt, OSError):
        pass
    pid_file.unlink(missing_ok=True)
    return rc


if __name__ == "__main__":
    sys.exit(helper_main())
