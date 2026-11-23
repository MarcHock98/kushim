"""Claude darf kushims Systemansagen nicht nachahmen (Safety-Audit 2026-11-23).

Claude spricht über `sprich` mit kushims Stimme, in der ersten Person und ohne Rückfrage. Ein manipuliertes Claude (z. B.
durch eingeschleusten Text aus einer Webseite) könnte so „Ich möchte … Bitte im Terminal bestätigen.“, „Freigabe erteilt“
oder „Der Notaus ist aktiv …“ sagen und den Nutzer täuschen. Solche Texte werden nicht so vorgelesen, sondern durch einen
festen neutralen Satz ersetzt. Echte Ansagen macht nur kushim selbst, mit Signalton davor (voice/earcon.py).

Lieber einmal zu viel ersetzen als eine falsche Freigabe- oder Notaus-Ansage: Ein ersetzter harmloser Satz kostet wenig.
Nur Standardbibliothek.
"""
from __future__ import annotations

import re

NEUTRAL = "Das sage ich so nicht; schau bitte ins Terminal."
TOOL_NOTE = ("Ersetzt: Ansagen zu Freigaben, Bestätigungen im Terminal und zum Notaus spricht nur kushim selbst. "
             "Formuliere es anders oder zeig es im Fenster.")
_PATTERNS = [re.compile(p, re.I) for p in (
    r"\bterminal\w*\b.{0,30}\bbestätig",             # „Bitte im Terminal bestätigen“, „im Terminal zu bestätigen“
    r"\bbestätig\w*\b.{0,30}\bterminal",
    r"\bfreigabe\w*\b.{0,40}\b(erteilt|nötig|noetig|erforderlich|gegeben|erhalten|bestätigt|genehmigt|abgelehnt|erfolgt)",
    r"\b(erteilt|gegeben|erhalten|bestätigt|genehmigt)\b.{0,20}\bfreigabe",
    r"\bnot[\s-]?aus\b",                              # jede Erwähnung des Notaus
    r"\berlauben\s*\?",                               # die feste Frage „Erlauben?“
)]


def imitates_system(text: str) -> bool:
    """Klingt der Text wie eine Systemansage von kushim (Freigabe, Terminal-Bestätigung, Notaus)?"""
    return any(p.search(text) for p in _PATTERNS)


def guard(text: str) -> tuple[str, bool]:
    """(vorzulesender Text, ersetzt?). Nachahmungen werden zu NEUTRAL."""
    return (NEUTRAL, True) if imitates_system(text) else (text, False)
