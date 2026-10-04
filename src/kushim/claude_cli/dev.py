"""Entwicklungs-Modus: Aufruf der Claude CLI für Arbeit an einem freigegebenen Projektordner.

Claude läuft in einem EIGENEN Git-Worktree (`-w`) auf einem eigenen Branch, nie auf dem Stand des Nutzers. `-p` ohne Rückfragen,
`acceptEdits` und `--permission-prompts none`: nur was in `ALLOWED_TOOLS` steht, läuft; alles andere wird abgelehnt (und dem Nutzer
als Rückfrage gemeldet, siehe report.py). Nie `bypassPermissions`. Ein Lauf ist ein Zug; die Antwort des Nutzers setzt die Sitzung
mit `--resume` fort. Plan: docs/claude-cli-plan.md.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .base import SUBSCRIPTION

BUDGET_USD = 2.0              # je Zug (Standard, einstellbar)
TIMEOUT_MIN = 45              # je Zug (Standard, einstellbar)

def _bash(*commands: str) -> tuple[str, ...]:
    """Regeln in der Schreibweise der CLI: `Bash(git add)` (ohne Argumente) UND `Bash(git add *)` (mit Argumenten, Leerzeichen vor dem Stern).
    Am echten Aufruf geprüft: `Bash(git add*)` greift NICHT, der Commit wurde verweigert."""
    return tuple(r for c in commands for r in (f"Bash({c})", f"Bash({c} *)"))


# Erlaubt: Lesen, Bearbeiten und eine feste Liste harmloser Befehle. `--permission-prompts none` lehnt alles andere automatisch ab.
ALLOWED_TOOLS = ("Read", "Glob", "Grep", "Edit", "Write") + _bash(
    "git status", "git diff", "git log", "git show", "git add", "git commit",
    "python -m pytest", ".venv/Scripts/python -m pytest", "pytest")
# Verboten (hat Vorrang vor Erlaubtem): alles, was Stand, Branches oder Rechner verlässt oder verändert.
DENIED_TOOLS = _bash("git push", "git checkout", "git switch", "git merge", "git reset", "git rebase", "git branch", "git worktree",
                     "git remote", "git config", "git clean", "git stash", "rm", "del", "rmdir", "rd", "curl", "wget", "pip", "powershell",
                     "pwsh", "cmd", "ssh", "scp") + ("WebFetch", "WebSearch")
FORBIDDEN_FLAGS = ("--dangerously-skip-permissions", "--allow-dangerously-skip-permissions", "bypassPermissions", "--add-dir",
                   "--mcp-config", "--chrome", "--bg", "--background")

PREAMBLE = ("Du wirst von kushim gestartet und arbeitest in einem eigenen Git-Worktree auf dem Branch dieser Sitzung. "
            "Arbeite nur dort. Nie pushen, nie nach master oder in einen anderen Branch mergen, keine Branches oder History löschen. "
            "Lies oder gib keine Geheimnisse aus (Schlüssel, Vault, Tokens, config.toml). Schwäche keine Sicherheitsregeln ab und lockere "
            "keine Egress-Sperre (src/kushim/safety, tests/test_no_egress.py). Arbeite in kleinen Schritten, führe die Tests aus, committe lokal. "
            "Wenn du eine Entscheidung des Nutzers brauchst, stelle genau EINE kurze Frage und höre dann auf. "
            "Beende JEDE Antwort mit genau diesen drei Abschnitten: "
            "'## Zusammenfassung' (höchstens 3 Sätze, was du getan hast und was ungetestet ist), "
            "'## Rückfrage' (leer oder genau eine kurze Frage), "
            "'## Nächste Schritte' (höchstens 3 Stichpunkte).")
DEFAULT_TASK = ("Nimm den nächsten offenen, nicht blockierten Punkt der ROADMAP.md (oder, falls es keine gibt, der README), arbeite ihn in kleinen "
                "Schritten ab, teste, committe lokal und pushe nicht.")


def worktree_name(now: datetime | None = None) -> str:
    return "kushim-" + (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


def _task(task: str) -> str:
    t = task.strip().lstrip("-").strip()
    if not t:
        raise ValueError("Leerer Auftrag")
    return t


def _common(extra_allowed: tuple[str, ...], budget: float) -> list[str]:
    allowed = ",".join(ALLOWED_TOOLS + tuple(extra_allowed))
    return ["--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits", "--permission-prompts", "none",
            "--allowedTools", allowed, "--disallowedTools", ",".join(DENIED_TOOLS),
            "--strict-mcp-config", "--disable-slash-commands",
            # NUR die Benutzer-Einstellungen des Nutzers laden, nie die des Projekts/lokale: Claude darf im Worktree Dateien bearbeiten, also auch
            # `.claude/settings*.json`; sonst könnte es sich in der nächsten Runde selbst Befehle erlauben oder Hooks eintragen (Selbst-Eskalation).
            "--setting-sources", "user",
            "--max-budget-usd", f"{budget:g}",
            "--append-system-prompt", PREAMBLE]


def build_start_argv(exe: Path, task: str, worktree: str, budget: float = BUDGET_USD,
                     extra_allowed: tuple[str, ...] = ()) -> list[str]:
    """Erster Zug: eigener Worktree `-w <name>`. Der Auftrag steht direkt hinter `-p` (vor den Listen-Optionen)."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,60}", worktree):
        raise ValueError("Ungültiger Worktree-Name")
    return [str(exe), "-p", _task(task), "-w", worktree] + _common(extra_allowed, budget)


def build_resume_argv(exe: Path, answer: str, session_id: str, budget: float = BUDGET_USD,
                      extra_allowed: tuple[str, ...] = ()) -> list[str]:
    """Folgezug: Antwort des Nutzers, gleiche Sitzung, Aufruf im Worktree (Arbeitsordner = Worktree, kein neues `-w`)."""
    if not re.fullmatch(r"[A-Za-z0-9-]{8,64}", session_id):
        raise ValueError("Ungültige Sitzungs-Kennung")
    return [str(exe), "-p", _task(answer), "--resume", session_id] + _common(extra_allowed, budget)


def preview_text(folder: str, task: str, worktree: str, method: str, budget: float, minutes: int,
                 resume: bool = False, extra_allowed: tuple[str, ...] = ()) -> str:
    login = "Abo (claude.ai)" if method == SUBSCRIPTION else "API-Konto (kann Geld kosten)"
    head = "Claude antwortet" if resume else "Claude startet"
    lines = [f"{head} im freigegebenen Ordner «{folder}» (eigener Worktree und Branch, nie dein aktueller Stand).",
             f"Auftrag: «{task.strip()}»",
             "Dieser Text und Ausschnitte aus den Dateien des Projekts gehen an Anthropic (Modus C).",
             "Erlaubt: Dateien lesen und bearbeiten, git status/diff/log/add/commit, pytest. Nicht erlaubt: push, merge, löschen, Netzwerk-Werkzeuge."]
    if extra_allowed:
        lines.append("Zusätzlich für diese Sitzung erlaubt: " + ", ".join(extra_allowed))
    lines.append(f"Grenzen: {budget:g} USD und {minutes} Minuten je Zug. Anmeldung: {login}. kushim übernimmt nichts und pusht nichts; das machst du.")
    return "\n".join(lines)
