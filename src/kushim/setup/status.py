"""Status der Setup-Schritte aus echten Fakten plus der gemerkten Entscheidung (übersprungen/erledigt).

Reine Logik: Vault-Zustand, Prüfungen, Claude-Zustand und freigegebene Ordner werden hineingereicht (testbar ohne
Vault/Modelle/Audio/CLI). Siehe docs/ui-setup-plan.md und docs/ui-e2e3-plan.md (Schritte `claude` und `folder`).
"Überspringen" ändert nie eine Sicherheitsregel, nur den Funktionsumfang.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..claude_cli.base import MIN_VERSION
from ..doctor import Check, run_checks
from ..safety import killswitch
from . import state as state_file

TITLES = {
    "system": "Systemcheck und Vault",
    "claude": "Claude Code",
    "audio_voice": "Mikrofon und Lautsprecher",
    "wake_words": "Wake Words",
    "folder": "Arbeitsordner",
    "safety": "Sicherheit und Notaus",
}

# Folge des Überspringens (aus dem Plan, "Eingeschränkter Modus"); Sicherheitsregeln bleiben immer gleich.
IF_SKIPPED = {
    "system": "Kein Gedächtnis. Notaus und Sicherheitsregeln gelten weiter.",
    "claude": "Ohne Claude Code startet kushim nicht (kushim start prüft es). Sicherheitsregeln gelten weiter.",
    "audio_voice": "Es gelten die Windows-Standardgeräte und die Standard-Pegel.",
    "wake_words": "Es gelten die Standard-Wörter aus der Vorlage.",
    "folder": "Ohne freigegebenen Ordner startet kushim nicht; Claude arbeitet nirgends.",
    "safety": "Der Notaus wirkt trotzdem.",
}

# Schritte ohne eigene Tatsache: erledigt heißt "der Nutzer hat es bestätigt".
MANUAL_DONE = ("audio_voice", "wake_words", "safety")


@dataclass(frozen=True)
class StepStatus:
    step: str
    title: str
    status: str            # "done" | "skipped" | "open"
    detail: str = ""


def _claude_fact(claude: Callable[[], Any] | None) -> tuple[bool, str]:
    """`claude()` liefert einen `ClaudeState` (installiert, Version, angemeldet); Fehler zählen als "nicht bereit"."""
    if claude is None:
        return False, "Nicht geprüft (kushim doctor)"
    try:
        st = claude()
    except Exception:                                    # noqa: BLE001 (Anzeige: nie abstürzen, nie Systemtext)
        return False, "Nicht prüfbar"
    if not st.installed:
        return False, "Claude Code nicht gefunden"
    if st.version is None or st.version < MIN_VERSION:
        return False, "Claude Code zu alt oder Version nicht lesbar (claude update)"
    if not st.logged_in:
        return False, "Nicht angemeldet (claude auth login)"
    return True, "Installiert, aktuell und angemeldet"


def _folder_fact(folders: Callable[[], bool] | None) -> tuple[bool, str]:
    if folders is None:
        return False, "Nicht geprüft"
    try:
        ok = bool(folders())
    except Exception:                                    # noqa: BLE001
        return False, "Nicht prüfbar"
    return ok, "Mindestens ein Ordner freigegeben" if ok else "Noch kein Ordner freigegeben"


def _facts(root: Path, vault_state: Callable[[], str], checks: list[Check],
           claude: Callable[[], Any] | None = None, folders: Callable[[], bool] | None = None) -> dict[str, tuple[bool, str]]:
    vault = vault_state()
    failing = [c.name for c in checks if not c.ok]
    own_wake_file = (root / "wakewords.toml").is_file()
    if failing:
        system_detail = "Fehlt: " + ", ".join(failing[:3]) + (" ..." if len(failing) > 3 else "")
    else:
        system_detail = "Kein Vault angelegt" if vault == "kein-vault" else "Alles vorhanden"
    return {
        "system": (not failing and vault != "kein-vault", system_detail),
        "claude": _claude_fact(claude),
        "audio_voice": (False, "Mikrofon und Lautsprecher noch nicht bestätigt (Pegel: kushim voice level)"),
        "wake_words": (own_wake_file, "Eigene Wake-Word-Datei vorhanden" if own_wake_file else "Es gelten die Standard-Wörter"),
        "folder": _folder_fact(folders),
        "safety": (False, "Notaus noch nicht ausprobiert"),
    }


def compute(root: Path, vault_state: Callable[[], str],
            checks: list[Check] | None = None, claude: Callable[[], Any] | None = None,
            folders: Callable[[], bool] | None = None) -> list[StepStatus]:
    """Status je Schritt. Tatsache "erledigt" gewinnt; sonst zählt die gemerkte Entscheidung; sonst offen.
    `claude()` liefert den Zustand der Claude CLI (`ClaudeProbe.get`), `folders()` ob ein Arbeitsordner freigegeben ist."""
    checks = checks if checks is not None else run_checks(root, None)
    remembered = state_file.load(root)
    facts = _facts(root, vault_state, checks, claude, folders)
    out = []
    for step in state_file.STEPS:
        fact_done, detail = facts[step]
        saved = remembered[step]["status"]
        if fact_done or (step in MANUAL_DONE and saved == "done"):
            status = "done"
            if step == "safety":
                detail = "Notaus ausprobiert"
        elif saved == "skipped":
            status = "skipped"
        else:
            status = "open"
        out.append(StepStatus(step, TITLES[step], status, detail))
    return out


def first_start(steps: list[StepStatus]) -> bool:
    """Die Oberfläche öffnet das Setup beim Start, solange ein Schritt offen (weder erledigt noch übersprungen) ist."""
    return any(s.status == "open" for s in steps)


def restricted_notes(steps: list[StepStatus]) -> list[str]:
    """Hinweise für den eingeschränkten Modus: was gerade nicht geht, weil Schritte übersprungen wurden."""
    return [f"{s.title}: {IF_SKIPPED[s.step]}" for s in steps if s.status == "skipped"]


def kill_active(root: Path) -> bool:
    return killswitch.is_triggered(root)
