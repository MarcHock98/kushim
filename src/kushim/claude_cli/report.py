"""Zug-Ergebnis lesen und eine kurze Übersicht bauen: Getan, Fakten, Rückfrage, nächste Schritte.

Drei getrennte Quellen: (1) Claudes eigene Zusammenfassung (laut Claude, `Untrusted`), (2) Fakten aus Git (review.py, unabhängig von
Claudes Aussagen), (3) feste Optionen von kushim. Verweigerte Berechtigungen werden als Rückfrage angeboten, aber NUR für eine kleine
Positivliste harmloser Befehle; alles Gefährliche wird nie angeboten. Claudes Text löst in kushim nie eine Aktion aus.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..web.sanitize import Untrusted, clean_text
from .review import Review

_HEAD = re.compile(r"^#{1,3}\s*(Zusammenfassung|R(?:ü|ue)ckfrage|N(?:ä|ae)chste Schritte)\s*:?\s*$", re.IGNORECASE | re.MULTILINE)
_EMPTY = {"", "-", "–", "—", "keine", "keine rückfrage", "keine rueckfrage", "none", "n/a", "nein", "entfällt"}
MAX_SUMMARY = 700
MAX_STEP = 160

# Befehle, die der Nutzer für eine Sitzung nachträglich erlauben kann (Vorsatz-Muster). Nur lesend/prüfend.
# klein geschrieben -> Schreibweise des Musters (so wie die CLI es erwartet: Leerzeichen vor dem Stern)
SAFE_PREFIXES = {"python -m pytest": "python -m pytest", ".venv/scripts/python -m pytest": ".venv/Scripts/python -m pytest", "pytest": "pytest",
                 "git diff": "git diff", "git show": "git show", "git log": "git log", "git status": "git status"}
_DANGEROUS = re.compile(r"[;|&<>$`\n\r]|\b(push|merge|rebase|reset|checkout|switch|branch|worktree|remote|config|rm|del|rmdir|rd|curl|wget|"
                        r"pip|powershell|pwsh|cmd|ssh|scp|format|shutdown|reg|takeown|icacls|net|sc|start|invoke|iex)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Parsed:
    summary: Untrusted
    question: Untrusted
    next_steps: tuple[Untrusted, ...]
    structured: bool                       # hielt sich Claude an das feste Format?


def parse(text: str) -> Parsed:
    """Zerlegt die Antwort in die drei Abschnitte. Fehlt das Format, wird der ganze Text gekürzt als Zusammenfassung gezeigt."""
    marks = list(_HEAD.finditer(text or ""))
    if not marks:
        return Parsed(clean_text(text or "", MAX_SUMMARY), Untrusted(""), (), False)
    sections: dict[str, str] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        key = m.group(1).lower()
        key = "frage" if key.startswith("r") else "schritte" if key.startswith("n") else "summary"
        sections[key] = text[m.end():end].strip()
    question = sections.get("frage", "")
    if re.sub(r"[\s.!]+", " ", question).strip().lower() in _EMPTY:
        question = ""
    steps = [clean_text(re.sub(r"^[\s*•\-–\d.)]+", "", ln), MAX_STEP) for ln in sections.get("schritte", "").splitlines() if ln.strip()]
    return Parsed(clean_text(sections.get("summary", ""), MAX_SUMMARY), clean_text(question, 400), tuple(s for s in steps if s)[:3], True)


@dataclass(frozen=True)
class Denial:
    tool: str
    command: str


def extract_denials(result: dict[str, Any]) -> list[Denial]:
    """Verweigerte Werkzeug-Aufrufe aus dem Ergebnis der CLI (`permission_denials`)."""
    out = []
    for d in result.get("permission_denials") or []:
        if isinstance(d, dict) and isinstance(d.get("tool_name"), str):
            inp = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
            cmd = inp.get("command") if isinstance(inp.get("command"), str) else ""
            out.append(Denial(d["tool_name"][:40], cmd[:300]))
    return out


def offer(d: Denial) -> str | None:
    """Muster, das der Nutzer für diese Sitzung zusätzlich erlauben könnte, sonst None. Nur harmlose Bash-Befehle."""
    if d.tool != "Bash":
        return None                                    # Dateizugriff außerhalb des Worktrees u. ä. wird nie angeboten
    cmd = " ".join(d.command.split())
    if not cmd or _DANGEROUS.search(cmd):
        return None
    low = cmd.lower().replace("\\", "/")
    for prefix, canonical in SAFE_PREFIXES.items():
        if low == prefix or low.startswith(prefix + " "):
            return f"Bash({canonical} *)"
    return None


def offers(denials: list[Denial]) -> list[str]:
    seen: list[str] = []
    for d in denials:
        o = offer(d)
        if o and o not in seen:
            seen.append(o)
    return seen


@dataclass
class Overview:
    done: Untrusted
    facts: list[str] = field(default_factory=list)
    question: Untrusted = Untrusted("")
    permission_questions: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    protected: list[str] = field(default_factory=list)
    structured: bool = True
    denied: list[str] = field(default_factory=list)          # was die CLI verweigert hat (auch wenn es nicht angeboten werden darf)


def build_overview(parsed: Parsed, rv: Review, cost_usd: float, seconds: float, turn: int, offered: list[str],
                   denied: list[str] | None = None) -> Overview:
    facts = []
    if rv.error:
        facts.append(f"Prüfung unvollständig: {rv.error}.")
    if rv.branch:
        facts.append(f"Branch {rv.branch}")
    n = len(rv.files)
    facts.append(f"{n} Datei{'en' if n != 1 else ''} geändert ({rv.new_files} neu)" + (f", {rv.shortstat}" if rv.shortstat else ""))
    if rv.uncommitted:
        facts.append(f"{rv.uncommitted} uncommittete Änderung{'en' if rv.uncommitted != 1 else ''} im Worktree")
    facts.append("dein aktueller Stand ist unverändert" if rv.base_unchanged else "ACHTUNG: dein aktueller Stand hat sich verändert")
    facts.append(f"Zug {turn}, {seconds / 60:.1f} min, {cost_usd:.2f} USD")
    if rv.branch:
        facts.append("Der Arbeitsordner liegt unter .claude/worktrees/ im Projekt (Tipp: dort in der .gitignore eintragen, sonst erscheint er als ungetrackt)")
    steps = list(parsed.next_steps)
    ov = Overview(parsed.summary, facts, parsed.question, [f"Claude wollte etwas ausführen, das nicht erlaubt war. Für diese Sitzung erlauben: {o}?" for o in offered],
                  [str(s) for s in steps], list(rv.protected), parsed.structured, list(denied or []))
    return ov


def written(ov: Overview) -> str:
    lines = [f"Getan (laut Claude): {ov.done or '(keine Zusammenfassung)'}" + ("" if ov.structured else "  [Format fehlte, gekürzt]"),
             "Fakten von kushim (aus Git): " + "; ".join(ov.facts)]
    if ov.protected:
        lines.append("!! SICHERHEITSRELEVANT geändert, bitte genau prüfen: " + ", ".join(ov.protected))
    if ov.denied:
        lines.append("Verweigert (war nicht erlaubt): " + "; ".join(ov.denied))
    if ov.question:
        lines.append(f"Rückfrage von Claude: {ov.question}")
    lines += [f"Rückfrage von kushim: {q}" for q in ov.permission_questions]
    lines.append("Nächste Schritte: " + (" | ".join(ov.next_steps) if ov.next_steps else "(keine genannt)"))
    return "\n".join(lines)


def spoken(ov: Overview) -> str:
    """Höchstens fünf kurze Zeilen zum Vorlesen; Ausführliches steht in der UI."""
    lines = [f"Claude meldet: {ov.done}" if ov.done else "Claude hat einen Zug beendet."]
    lines.append(ov.facts[0] if ov.facts and not ov.facts[0].startswith("Prüfung") else (ov.facts[1] if len(ov.facts) > 1 else ""))
    if ov.protected:
        lines.append("Achtung: sicherheitsrelevante Dateien wurden geändert, bitte prüfen.")
    if ov.question:
        lines.append(f"Claude fragt: {ov.question}")
    elif ov.permission_questions:
        lines.append(ov.permission_questions[0])
    elif ov.next_steps:
        lines.append("Als Nächstes: " + str(ov.next_steps[0]))
    return "\n".join(l for l in lines if l)[:900]
