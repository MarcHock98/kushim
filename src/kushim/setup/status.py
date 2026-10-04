"""Status der vier Setup-Schritte aus echten Fakten plus der gemerkten Entscheidung (übersprungen/erledigt).

Reine Logik: Vault-Zustand und Prüfungen werden hineingereicht (testbar ohne Vault/Modelle/Audio).
Siehe docs/ui-setup-plan.md. "Überspringen" ändert nie eine Sicherheitsregel, nur den Funktionsumfang.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..doctor import Check, run_checks
from ..llm.ollama import DEFAULT_MODEL
from ..safety import killswitch
from . import state as state_file

TITLES = {
    "system": "Systemcheck und Vault",
    "audio_voice": "Mikrofon, Lautsprecher und Stimme",
    "wake_words": "Wake Words",
    "safety": "Sicherheit und Notaus",
}

# Folge des Überspringens (aus dem Plan, "Eingeschränkter Modus"); Sicherheitsregeln bleiben immer gleich.
IF_SKIPPED = {
    "system": "Kein Gedächtnis, kein Stimmprofil, kein Sprechen. Notaus und Sicherheitsregeln gelten weiter.",
    "audio_voice": "Sprechen bleibt gesperrt (ohne Stimmprofil antwortet kushim nicht per Sprache); Texteingabe ist möglich.",
    "wake_words": "Es gelten die Standard-Wörter aus der Vorlage.",
    "safety": "Der Notaus wirkt trotzdem.",
}

# Schritte ohne eigene Tatsache: erledigt heißt "der Nutzer hat es bestätigt".
MANUAL_DONE = ("wake_words", "safety")


@dataclass(frozen=True)
class StepStatus:
    step: str
    title: str
    status: str            # "done" | "skipped" | "open"
    detail: str = ""


def _facts(root: Path, vault_state: Callable[[], str], checks: list[Check]) -> dict[str, tuple[bool, str]]:
    vault = vault_state()
    failing = [c.name for c in checks if not c.ok]
    own_wake_file = (root / "wakewords.toml").is_file()
    if failing:
        system_detail = "Fehlt: " + ", ".join(failing[:3]) + (" ..." if len(failing) > 3 else "")
    else:
        system_detail = "Kein Vault angelegt" if vault == "kein-vault" else "Alles vorhanden"
    return {
        "system": (not failing and vault != "kein-vault", system_detail),
        "audio_voice": (vault == "ok", "Stimmprofil eingeschrieben" if vault == "ok" else "Noch keine Stimme eingeschrieben"),
        "wake_words": (own_wake_file, "Eigene Wake-Word-Datei vorhanden" if own_wake_file else "Es gelten die Standard-Wörter"),
        "safety": (False, "Notaus noch nicht ausprobiert"),
    }


def compute(root: Path, vault_state: Callable[[], str], llm_model: str = DEFAULT_MODEL,
            checks: list[Check] | None = None) -> list[StepStatus]:
    """Status je Schritt. Tatsache "erledigt" gewinnt; sonst zählt die gemerkte Entscheidung; sonst offen."""
    checks = checks if checks is not None else run_checks(root, None, llm_model)
    remembered = state_file.load(root)
    facts = _facts(root, vault_state, checks)
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
