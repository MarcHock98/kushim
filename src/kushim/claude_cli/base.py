"""Gemeinsame Bausteine für die Claude CLI: finden, Anmeldung prüfen, saubere Umgebung.

Nur lokale Aufrufe der CLI selbst (`claude auth status`). Es werden nie Kontodaten (E-Mail, Organisation, Pfade) gelesen
oder weitergegeben, nur ob der Nutzer angemeldet ist und wie (`claude.ai` = Abo, sonst API-Konto).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from ..procflags import hidden

SUBSCRIPTION = "claude.ai"                    # Anmeldung mit dem Abo; alles andere kann nach API-Verbrauch abrechnen


@dataclass(frozen=True)
class Auth:
    logged_in: bool
    method: str = ""                          # "claude.ai" = Abo
    error: str = ""                           # kurzer fester Grund ("not_runnable", "unreadable"), nie Systemtext

    @property
    def subscription(self) -> bool:
        return self.logged_in and self.method == SUBSCRIPTION


def find_claude(which: Callable[[str], str | None] = shutil.which) -> Path | None:
    """Pfad der Claude CLI (nur eine Datei, die wirklich `claude` heißt), sonst None. Wird nie aus Eingaben abgeleitet."""
    found = which("claude")
    if not found:
        return None
    p = Path(found)
    return p if p.stem.lower() == "claude" and p.is_file() else None


MIN_VERSION = (2, 1, 234)                     # ab hier: Freigaben nur an registrierte Channels (Roadmap v2 Phase B/C)
_VERSION = re.compile(r"^\s*(\d+)\.(\d+)\.(\d+)")


def version(exe: Path, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> tuple[int, int, int] | None:
    """`claude --version` (z. B. "2.1.310 (Claude Code)") als Zahlentripel, sonst None."""
    try:
        r = run([str(exe), "--version"], capture_output=True, text=True, timeout=20, check=False, env=clean_env(), **hidden())
    except (OSError, subprocess.SubprocessError):
        return None
    m = _VERSION.match(r.stdout or "")
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def auth_status(exe: Path, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> Auth:
    """`claude auth status --json`: nur `loggedIn` und `authMethod` werden gelesen."""
    try:
        r = run([str(exe), "auth", "status", "--json"], capture_output=True, text=True, timeout=20, check=False,
                env=clean_env(), **hidden())
    except (OSError, subprocess.SubprocessError):
        return Auth(False, error="not_runnable")
    try:
        data = json.loads(r.stdout)
        return Auth(data.get("loggedIn") is True, str(data.get("authMethod", ""))[:20])
    except (ValueError, AttributeError, TypeError):
        return Auth(False, error="unreadable")


class AuthCache:
    """Merkt sich die Anmeldung kurz, damit Listen in der UI die CLI nicht bei jedem Aufruf starten."""

    def __init__(self, exe: Path | None, ttl: float = 30.0, run=subprocess.run, clock: Callable[[], float] = time.monotonic):
        self.exe, self.ttl, self._run, self._clock = exe, ttl, run, clock
        self._value: Auth | None = None
        self._at = 0.0

    def get(self) -> Auth:
        if self.exe is None:
            return Auth(False, error="not_installed")
        now = self._clock()
        if self._value is None or now - self._at > self.ttl:
            self._value, self._at = auth_status(self.exe, self._run), now
        return self._value


@dataclass(frozen=True)
class ClaudeState:
    installed: bool
    version: tuple[int, int, int] | None = None
    logged_in: bool = False
    checking: bool = False                    # noch kein Ergebnis: die erste Prüfung läuft im Hintergrund

    @property
    def ready(self) -> bool:
        return (not self.checking and self.installed and self.version is not None and self.version >= MIN_VERSION
                and self.logged_in)


CHECKING = ClaudeState(False, checking=True)


def _in_background(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, name="kushim-claude-probe", daemon=True).start()


class ClaudeProbe:
    """Zustand der Claude CLI für die Oberfläche (Setup-Assistent): installiert, Version, angemeldet.

    `get()` blockiert nie (Safety-Audit E3, N5): Es liefert den zuletzt bekannten Stand (anfangs `CHECKING`) und stößt bei Bedarf
    EINE Prüfung im Hintergrund an (höchstens eine gleichzeitig). Fällig ist sie, wenn noch nichts bekannt ist, `ttl` Sekunden
    vergangen sind oder sich die Programmdatei geändert hat (Pfad, Größe, Änderungszeit; Suchen und `stat` starten keinen Prozess).
    Die Anmeldung kommt aus einem `AuthCache` (höchstens ein `claude auth status` je `ttl`), die Version nur einmal je
    Programmdatei. Jeder CLI-Aufruf ist versteckt und hat ein Zeitlimit (`version`, `auth_status`).
    `spawn` startet die Prüfung (Standard: Hintergrund-Thread); das CLI übergibt `lambda fn: fn()` und wartet so auf das Ergebnis."""

    def __init__(self, find: Callable[[], Path | None] | None = None,
                 run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
                 ttl: float = 30.0, clock: Callable[[], float] = time.monotonic,
                 spawn: Callable[[Callable[[], None]], None] = _in_background):
        self._find = find if find is not None else (lambda: find_claude())
        self._run, self._ttl, self._clock, self._spawn = run, ttl, clock, spawn
        self._lock = threading.Lock()
        self._state = CHECKING
        self._key: tuple | None = None            # Programmdatei der letzten Prüfung
        self._checked_at: float | None = None
        self._running = False
        self._version_key: tuple | None = None    # nur vom (einzigen) laufenden Prüf-Thread benutzt
        self._version: tuple[int, int, int] | None = None
        self._auth: AuthCache | None = None

    def _locate(self) -> tuple[Path | None, tuple | None]:
        try:
            exe = self._find()
            if exe is None:
                return None, None
            st = Path(exe).stat()
            return Path(exe), (str(exe), st.st_size, st.st_mtime_ns)
        except OSError:
            return None, None

    def get(self) -> ClaudeState:
        exe, key = self._locate()
        with self._lock:
            due = self._checked_at is None or key != self._key or self._clock() - self._checked_at > self._ttl
            start = due and not self._running
            if start:
                self._running = True
        if start:
            try:
                self._spawn(lambda: self._refresh(exe, key))
            except Exception:                     # noqa: BLE001 (kein Thread: beim nächsten Aufruf erneut versuchen)
                with self._lock:
                    self._running = False
        with self._lock:
            return self._state

    def _refresh(self, exe: Path | None, key: tuple | None) -> None:
        state = ClaudeState(False)
        try:
            if exe is not None:
                if key != self._version_key or self._auth is None:
                    self._version, self._version_key = version(exe, self._run), key
                    self._auth = AuthCache(exe, self._ttl, self._run, self._clock)
                state = ClaudeState(True, self._version, self._auth.get().logged_in)
        except Exception:                         # noqa: BLE001 (nie abstürzen; gilt als "nicht bereit")
            state = ClaudeState(exe is not None)
        finally:
            with self._lock:
                self._state, self._key, self._checked_at, self._running = state, key, self._clock(), False


# Variablen, die Claude nie bekommen darf: fremde Schlüssel/Umleiter (es zählt nur die Anmeldung des Nutzers) und alles von kushim.
_DROP = re.compile(r"^(ANTHROPIC_.*|KUSHIM_.*|.*API_?KEY.*|.*SECRET.*|.*PASSW(OR)?D.*|.*TOKEN.*)$", re.IGNORECASE)
_KEEP = {"CLAUDE_CODE_OAUTH_TOKEN"}           # falls der Nutzer die CLI so angemeldet hat


def clean_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    import os
    src = os.environ if base is None else base
    return {k: v for k, v in src.items() if k in _KEEP or not _DROP.match(k)}
