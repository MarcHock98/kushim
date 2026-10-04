"""Gemeinsame Bausteine für die Claude CLI: finden, Anmeldung prüfen, saubere Umgebung.

Nur lokale Aufrufe der CLI selbst (`claude auth status`). Es werden nie Kontodaten (E-Mail, Organisation, Pfade) gelesen
oder weitergegeben, nur ob der Nutzer angemeldet ist und wie (`claude.ai` = Abo, sonst API-Konto).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

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


def auth_status(exe: Path, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> Auth:
    """`claude auth status --json`: nur `loggedIn` und `authMethod` werden gelesen."""
    try:
        r = run([str(exe), "auth", "status", "--json"], capture_output=True, text=True, timeout=20, check=False,
                env=clean_env())
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


# Variablen, die Claude nie bekommen darf: fremde Schlüssel/Umleiter (es zählt nur die Anmeldung des Nutzers) und alles von kushim.
_DROP = re.compile(r"^(ANTHROPIC_.*|KUSHIM_.*|.*API_?KEY.*|.*SECRET.*|.*PASSW(OR)?D.*|.*TOKEN.*)$", re.IGNORECASE)
_KEEP = {"CLAUDE_CODE_OAUTH_TOKEN"}           # falls der Nutzer die CLI so angemeldet hat


def clean_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    import os
    src = os.environ if base is None else base
    return {k: v for k, v in src.items() if k in _KEEP or not _DROP.match(k)}
