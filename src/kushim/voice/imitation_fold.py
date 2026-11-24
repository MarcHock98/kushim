"""Zweite, strengere Prüfung auf nachgeahmte Systemansagen für Sätze von Claude, bevor die Stimme sie spricht.

`safety/imitation.py` prüft feste Muster („Notaus“, „Freigabe … erteilt“, „Terminal … bestätigen“, „Erlauben?“). Durch
Schreibweisen lassen sie sich umgehen: „Frei-gabe-erteilt“, „Frei. Gabe. Erteilt.“, „Not!aus“, „Not(aus)“, „Not͏aus“,
„Notаus“ (kyrillisches а), „Nohtaus“, „Notausschalter“. Die Stimme spricht trotzdem „Freigabe erteilt“ bzw. „Notaus“.
Dieses Modul faltet den Text (Unicode NFKD, ohne kombinierende Zeichen, Doppelgänger-Buchstaben auf lateinische), zerlegt ihn
in Wortteile und setzt benachbarte Teile (2 bis 4) wieder zusammen, wenn die Lücke dazwischen so ist, wie sie beim Sprechen
verschwindet. Gefundene Kernwörter (eigene kleine Liste, nur Verschärfung; `safety/` bleibt unverändert):
- „Notaus“ samt lautgleicher Formen und Zusammensetzungen wie „Notausschalter“ (nicht: „Notausgang“, „Notaufnahme“);
- „Freigabe“ und kurz danach (oder kurz davor) „erteilt“, „gegeben“, „bestätigt“ usw.;
- „Terminal“ und kurz danach bzw. davor „bestätig…“;
- „erlauben“ direkt vor „?“.

Lücken, die zusammengezogen werden dürfen:
- ohne Leerzeichen (Satzzeichen, Symbole, Bindestriche mitten im Wort: „Not!aus“, „Frei.gabe“, „Not(aus)“);
- nur Leerzeichen („Frei gabe“);
- Satzgrenze, wenn der folgende Satz höchstens zwei Wörter hat („Frei. Gabe. Erteilt.“, „Not! Aus! Ist aktiv.“), nicht aber
  vor einem normalen Satz („Ich war in Not. Aus Angst rief ich an.“);
- für „Notaus“ zusätzlich jede Lücke im selben Satz („Not, aus“), weil schon „Not aus“ eine Systemansage ist.
Nur Standardbibliothek, reine Funktionen.
"""
from __future__ import annotations

import re
import unicodedata

# kyrillische und griechische Doppelgänger lateinischer Buchstaben; Ziffern, die in Wörtern wie Buchstaben aussehen
_CONFUSABLE = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ӏ": "l",
    "к": "k", "м": "m", "н": "h", "т": "t", "в": "b", "г": "r", "ɑ": "a", "α": "a", "ο": "o", "ε": "e", "ι": "i", "κ": "k",
    "ν": "v", "τ": "t", "υ": "u", "ρ": "p", "β": "b", "η": "n", "ı": "i", "ſ": "s",
})
_DIGIT_LETTER = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t"})
_FILLERS = dict.fromkeys(map(ord, "ㅤᅟᅠﾠ⠀"), " ")       # unsichtbare „Buchstaben“: Lücke

_TOKEN = re.compile(r"[a-z0-9ß]+")
_BOUNDARY = re.compile(r"[.!?…]+(?=\s|$)")

_NOTAUS = re.compile(r"no+h?t+a+u+s+(?:schalter|funktion|knopf|taste|signal|stopp?|befehl|modus|zustand|ausgelost|aktiv|"
                     r"fall|meldung)?")
_NOT = re.compile(r"no+h?t+")
_FREIGABE = re.compile(r"f+r+e+i+g+a+b+e+n?")
_GRANTED = re.compile(r"e+r+t+[ae]+i+l+t+|e+r+t+e+i+l+e+n?|gegeben|erhalten|bestatigt|genehmigt|abgelehnt|erfolgt|notig|"
                      r"erforderlich|noetig")
_TERMINAL = re.compile(r"t+e+r+m+i+n+a+l+s?")
_CONFIRM = re.compile(r"b+e+s+t+a+e?t+i+g\w*")
_ALLOW = re.compile(r"e+r+l+a+u+b+e+n+")
MAX_PARTS = 4                    # so viele Wortteile werden höchstens zusammengezogen
NEAR_AFTER, NEAR_BEFORE = 10, 4  # Abstand in Wortteilen zwischen „Freigabe“/„Terminal“ und dem Verb


def fold(text: str) -> str:
    """Prüffassung: NFKD, ohne kombinierende Zeichen (Kategorie M), Doppelgänger auf lateinisch, klein."""
    t = unicodedata.normalize("NFKD", text.translate(_FILLERS))
    t = "".join(ch for ch in t if not unicodedata.category(ch).startswith("M"))
    return t.translate(_CONFUSABLE).lower()


def _tokens(folded: str) -> tuple[list[str], list[str], list[int], list[int]]:
    """(Wortteile, Lücke danach, Satznummer, Wörter je Satz)."""
    words, gaps, sents = [], [], []
    bounds = [m.end() for m in _BOUNDARY.finditer(folded)]
    matches = list(_TOKEN.finditer(folded))
    for i, m in enumerate(matches):
        word = m.group(0)
        if any(c.isalpha() for c in word):
            word = word.translate(_DIGIT_LETTER)
        words.append(word)
        gaps.append(folded[m.end():matches[i + 1].start()] if i + 1 < len(matches) else folded[m.end():])
        sents.append(sum(1 for b in bounds if b <= m.start()))
    counts = [sents.count(k) for k in range(max(sents) + 1)] if sents else []
    return words, gaps, sents, counts


def _joinable(gap: str, next_sentence_words: int, crosses: bool) -> str | None:
    """"tight" (verschwindet beim Sprechen), "loose" (Komma o. Ä. im selben Satz) oder None (nicht zusammenziehen)."""
    if crosses:
        return "tight" if next_sentence_words <= 2 else None
    if not gap or not any(c.isspace() for c in gap) or not gap.strip():
        return "tight"                                    # „Frei-gabe“, „Not!aus“, „Frei gabe“
    return "loose"


def _groups(words, gaps, sents, counts, loose: bool):
    """(Anfang, Ende, zusammengesetztes Wort, lockere Lücke benutzt) für 1 bis MAX_PARTS benachbarte Wortteile."""
    for i in range(len(words)):
        joined, used_loose = words[i], False
        yield i, i, joined, used_loose
        for j in range(i + 1, min(len(words), i + MAX_PARTS)):
            kind = _joinable(gaps[j - 1], counts[sents[j]], sents[j] != sents[j - 1])
            if kind is None or (kind == "loose" and not loose):
                break
            joined, used_loose = joined + words[j], used_loose or kind == "loose"
            yield i, j, joined, used_loose


def folded_suspect(text: str) -> bool:
    """Klingt der Text nach dem Falten und Zusammenziehen wie eine Systemansage von kushim?"""
    words, gaps, sents, counts = _tokens(fold(text))
    if not words:
        return False
    for i, _, g, used_loose in _groups(words, gaps, sents, counts, loose=True):
        # über ein Komma o. Ä. nur „Not, aus“ (nicht „Nota, us-amerikanisch“)
        if _NOTAUS.fullmatch(g) and (not used_loose or _NOT.fullmatch(words[i])):
            return True
    found: dict[str, list[tuple[int, int]]] = {"freigabe": [], "granted": [], "terminal": [], "confirm": []}
    for i, j, g, _ in _groups(words, gaps, sents, counts, loose=False):
        if _ALLOW.fullmatch(g) and "?" in gaps[j]:
            return True
        for key, pattern in (("freigabe", _FREIGABE), ("granted", _GRANTED), ("terminal", _TERMINAL), ("confirm", _CONFIRM)):
            if pattern.fullmatch(g):
                found[key].append((i, j))
    for a, b in (("freigabe", "granted"), ("terminal", "confirm")):
        for start_a, end_a in found[a]:
            for start_b, end_b in found[b]:
                if 0 < start_b - end_a <= NEAR_AFTER or 0 < start_a - end_b <= NEAR_BEFORE:
                    return True
    return False
