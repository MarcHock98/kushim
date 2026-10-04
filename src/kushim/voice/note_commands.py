"""Sprachbefehle für Notizen (Werkzeug `notes.local`, lokal, standardmäßig aus): im verschlüsselten Vault, nie nach außen.

"Notiere: Milch kaufen", "Merk dir, dass der Schlüssel im Flur liegt", "Lies meine Notizen vor", "Was habe ich über Milch notiert?",
"Lösche die letzte Notiz" (mit Rückfrage "ja"). Notizen sind Nutzerdaten: Sie gehen nie an Claude, ins Netz oder ins Sprachmodell; vorgelesen
werden sie nur über die lokale Stimme. Anlegen, Vorlesen und Suchen sind lokal und umkehrbar; Löschen vernichtet Daten und braucht ein "ja".
"""
from __future__ import annotations

import re
from typing import Any, Callable

from ..safety.gate import ActionRequest, ActionSpec, Decision, Risk
from .tool_commands import fold, words
from .wake_commands import _NO, _YES, _words

TOOL = "notes.local"
MAX_NOTE = 500
MAX_NOTES = 500
DELETE_SPEC = ActionSpec("notes.delete", Risk.IRREVERSIBLE)       # vernichtet Nutzerdaten: immer mit Rückfrage

_ADD = re.compile(r"^(?:\W*(?:hey\s+)?(?:kushim\W+)?)?(?:(?:bitte\s+)?(?:notiere(?:\s+dir)?|notier(?:\s+dir)?|merk(?:e)?\s+dir|schreib(?:e)?\s+(?:das\s+)?auf|"
                  r"halte?\s+(?:das\s+)?fest|speichere(?:\s+das)?|(?:mach|mache)\s+(?:dir\s+)?eine\s+notiz|neue\s+notiz|notiz))(?=[\s:,\-])\s*(?:bitte|mal)?\s*[:,\-]?\s*(.+)$",
                  re.IGNORECASE | re.UNICODE)
_NOTE_WORDS = {"notiz", "notizen", "notiert", "notizbuch"}
_READ = {"lies", "lese", "vorlesen", "vor", "nenne", "zeig", "zeige", "liste", "welche", "was", "habe", "hab", "steht", "stehen", "gibt", "hast"}
_DELETE = {"losche", "loesche", "entferne", "streiche", "vergiss"}
_NUMBERS = {"eins": 1, "ein": 1, "erste": 1, "ersten": 1, "zwei": 2, "zweite": 2, "zweiten": 2, "drei": 3, "dritte": 3, "dritten": 3,
            "vier": 4, "vierte": 4, "vierten": 4, "funf": 5, "funfte": 5, "funften": 5}


def notes_reviewer(spec: ActionSpec, req: ActionRequest) -> set:
    """Unabhängige Prüfung für Notiz-Aktionen: nur bekannte Aktionen, Beschreibung muss von Notizen handeln (sonst Schaden gemeldet)."""
    from ..safety.rules import Harm
    return set() if spec.name in {"notes.local", "notes.delete"} and "Notiz" in req.description else {Harm.PRIVACY}


def clean_note(text: str) -> str:
    t = "".join(ch if ch.isprintable() else " " for ch in str(text))
    return " ".join(t.split())[:MAX_NOTE]


class NoteCommands:
    def __init__(self, cfg: Any, registry: Any, gate: Any, open_store: Callable[[], Any]):
        """`open_store`: öffnet den Vault bei Bedarf (Kontextmanager, wird sofort wieder geschlossen)."""
        self.cfg, self.registry, self.gate, self.open_store = cfg, registry, gate, open_store
        self._pending: tuple[int, str] | None = None             # (Notiz-Id, Text) wartet auf "ja"

    @property
    def awaiting(self) -> bool:
        return self._pending is not None

    def _active(self) -> bool:
        self.registry.sync(self.cfg.tools_enabled)
        return self.registry.is_active(TOOL)

    def _off(self) -> str:
        return ("Das Werkzeug Notizen ist aus. Einschalten kannst du es nur in den Einstellungen oder mit kushim tools enable notes.local, "
                "nie per Sprache.")

    def _notes(self, store: Any, query: str = "") -> list[Any]:
        return [f for f in store.search_facts(query, MAX_NOTES) if f.kind == "note"]

    def handle(self, text: str, verified: bool, strong: bool = True) -> str | None:
        if self._pending is not None:
            return self._confirm(text, verified)
        m = _ADD.match(text.strip())
        ws = words(text)
        toks = [f for _, f in ws]
        s = set(toks)
        if m is None and not (s & _NOTE_WORDS):
            return None
        kind = "add" if m else ("delete" if s & _DELETE else "read" if s & _READ else None)
        if kind is None:
            return None
        if not self._active():
            return self._off()
        if not verified:
            return "Das mache ich nur auf deine Stimme."
        try:
            with self.open_store() as store:
                if kind == "add":
                    return self._add(store, m.group(1))
                if kind == "delete":
                    return self._delete(store, toks)
                return self._read(store, ws, toks)
        except (OSError, FileNotFoundError, RuntimeError):
            return "Der Vault ist gerade nicht erreichbar."

    def _add(self, store: Any, raw: str) -> str:
        note = clean_note(raw.strip(" .,;:"))
        if len(note) < 2:
            return "Was soll ich notieren?"
        v = self.gate.check(ActionRequest(TOOL, "Notiz anlegen", speaker_verified=True, user_initiated=True))
        if v.decision is not Decision.ALLOW:
            return "Das darf ich gerade nicht (" + v.reason + ")."
        if len(self._notes(store)) >= MAX_NOTES:
            return "Es gibt schon zu viele Notizen. Lösch erst ein paar."
        store.add_fact(note, kind="note", source="voice")
        store.audit("note_added", f"{len(note)} Zeichen")                                      # nie der Text selbst
        return "Notiert."

    def _read(self, store: Any, ws: list[tuple[str, str]], toks: list[str]) -> str:
        query = ""
        if "uber" in toks:                                              # "Was habe ich über Milch notiert?"
            i = toks.index("uber")
            query = " ".join(o for o, f in ws[i + 1:] if f not in {"notiert", "notizen", "notiz", "aufgeschrieben", "gespeichert", "vor"})
        notes = self._notes(store, query.strip())
        if not notes:
            return "Dazu habe ich keine Notiz." if query else "Du hast keine Notizen."
        shown = notes[:5]
        parts = [f"Nummer {i}: {n.text}" for i, n in enumerate(shown, 1)]
        more = f" Insgesamt {len(notes)}." if len(notes) > len(shown) else ""
        return f"Du hast {len(notes)} Notizen." + " " + " ".join(parts) + more if not query else "Gefunden: " + " ".join(parts) + more

    def _delete(self, store: Any, toks: list[str]) -> str:
        notes = self._notes(store)
        if not notes:
            return "Du hast keine Notizen."
        n = next((_NUMBERS[t] for t in toks if t in _NUMBERS), None) or next((int(t) for t in toks if t.isdigit() and 1 <= int(t) <= 9), None)
        if n is None and not (set(toks) & {"letzte", "letzten", "neueste", "neuesten", "diese"}):
            return "Welche Notiz? Sag zum Beispiel: Lösche die letzte Notiz, oder: Lösche Notiz Nummer zwei."
        target = notes[(n or 1) - 1] if (n or 1) <= len(notes) else None
        if target is None:
            return f"So viele Notizen gibt es nicht, es sind {len(notes)}."
        v = self.gate.check(ActionRequest("notes.delete", f"Notiz löschen: {target.text[:40]}", speaker_verified=True, user_initiated=True))
        if v.decision is not Decision.ASK:
            return "Das darf ich gerade nicht (" + v.reason + ")."
        self._pending = (target.id, target.text)
        return f"Soll ich die Notiz {target.text[:80]} löschen? Sage ja oder nein."

    def _confirm(self, text: str, verified: bool) -> str:
        (nid, note), self._pending = self._pending, None
        w = _words(text)
        if not verified or w & _NO or not (w & _YES):
            return "Abgebrochen. Die Notiz bleibt."
        try:
            with self.open_store() as store:
                if not any(f.id == nid for f in self._notes(store)):
                    return "Die Notiz gibt es nicht mehr."
                store.delete_fact(nid)
                store.audit("note_deleted", "1 Notiz")
        except (OSError, FileNotFoundError, RuntimeError):
            return "Der Vault ist gerade nicht erreichbar."
        return "Okay, die Notiz ist gelöscht."
