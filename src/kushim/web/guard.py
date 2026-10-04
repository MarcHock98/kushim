"""Prüfer für Suchanfragen: Es darf nichts Privates hinausgehen.

Läuft VOR der Vorschau und ein zweites Mal als Prüfer im `ActionGate`. Treffer bedeuten: Anfrage wird verweigert
(Schaden "Privatsphäre" bzw. "Dritte"). Heuristiken, keine Garantie: Die Vorschau mit Freigabe durch den Nutzer bleibt
die eigentliche Sicherung.
"""
from __future__ import annotations

import re

from ..safety.rules import Harm

MAX_QUERY = 200

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
_DIGIT_RUN = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_PHONE = re.compile(r"(?:\+|00)?\d[\d\s/().-]{6,}\d")
_LONG_TOKEN = re.compile(r"[A-Za-z0-9_\-+/=]{24,}")
_PATH = re.compile(r"[A-Za-z]:[\\/]|\\\\|~[\\/]|(?:^|\s)/(?:home|users|etc|var|mnt)/|%[A-Za-z_]+%", re.IGNORECASE)
_SECRET_WORDS = re.compile(r"\b(passwort|password|kennwort|schlüssel|schluessel|api[- ]?key|token|vault|secret)\b", re.IGNORECASE)
# Suche nach Privatpersonen (Daten über Dritte): Adresse/Telefon/Wohnort von jemandem
_PERSON_DATA = re.compile(
    r"\b(adresse|anschrift|telefonnummer|handynummer|privatadresse|wohnort|geburtsdatum|kontonummer)\s+(von|des|der|vom)\b|"
    r"\bwo\s+wohnt\b|\bwer\s+wohnt\b", re.IGNORECASE)


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def normalize(query: str) -> str:
    """Steuerzeichen raus, Leerraum zusammenfassen, Anführungszeichen der Vorschau neutralisieren."""
    q = "".join(ch if ch.isprintable() else " " for ch in str(query))
    q = q.replace("«", '"').replace("»", '"')
    return " ".join(q.split())


def reasons(query: str) -> list[str]:
    """Gründe, warum die Anfrage nicht hinausgehen darf (leer = in Ordnung)."""
    q = normalize(query)
    found: list[str] = []
    if _EMAIL.search(q):
        found.append("enthält eine E-Mail-Adresse")
    compact = q.replace(" ", "").upper()
    if _IBAN.search(compact):
        found.append("enthält eine IBAN")
    for m in _DIGIT_RUN.finditer(q):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            found.append("enthält eine Kartennummer")
            break
    for m in _PHONE.finditer(q):
        if len(re.sub(r"\D", "", m.group())) >= 9:
            found.append("enthält eine Telefonnummer")
            break
    for m in _LONG_TOKEN.finditer(q):
        t = m.group()
        if re.search(r"\d", t) and re.search(r"[A-Za-z]", t):
            found.append("enthält eine schlüsselähnliche Zeichenfolge")
            break
    if _PATH.search(q):
        found.append("enthält einen lokalen Pfad")
    if _SECRET_WORDS.search(q):
        found.append("erwähnt Passwörter oder Schlüssel")
    if _PERSON_DATA.search(q):
        found.append("fragt nach persönlichen Daten einer Person")
    return found


def query_harms(query: str) -> set[Harm]:
    out: set[Harm] = set()
    for r in reasons(query):
        out.add(Harm.THIRD_PARTY if "Person" in r else Harm.PRIVACY)
    return out


def validate(query: str) -> str:
    """Bereinigte Anfrage oder ValueError (leer, zu lang). Prüft NICHT auf Privates (siehe `reasons`)."""
    q = normalize(query)
    if not q:
        raise ValueError("Die Suchanfrage ist leer.")
    if len(q) > MAX_QUERY:
        raise ValueError(f"Die Suchanfrage ist zu lang (höchstens {MAX_QUERY} Zeichen).")
    return q
