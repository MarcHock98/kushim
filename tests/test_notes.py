"""Notizen per Sprache: lokal im Vault, Gate, Rückfrage beim Löschen, nie nach außen."""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from kushim.memory.store import Fact
from kushim.safety.gate import ActionGate
from kushim.tools.registry import NOTES, ToolGate, ToolRegistry, default_tools
from kushim.voice.commands import CommandChain
from kushim.voice.note_commands import DELETE_SPEC, NoteCommands, clean_note, notes_reviewer


class FakeStore:
    def __init__(self):
        self.facts, self.audits, self._id = [], [], 0

    def add_fact(self, text, kind="other", source="user", confidence=1.0):
        self._id += 1
        self.facts.insert(0, Fact(self._id, text, kind, source, confidence, 0.0))
        return self._id

    def search_facts(self, query, limit=10):
        return [f for f in self.facts if query.lower() in f.text.lower()][:limit]

    def delete_fact(self, fact_id):
        self.facts = [f for f in self.facts if f.id != fact_id]

    def audit(self, event, detail=""):
        self.audits.append((event, detail))


def make(enabled=("notes.local",)):
    store = FakeStore()
    reg = ToolRegistry(default_tools(), enabled)
    cfg = SimpleNamespace(tools_enabled=list(enabled))
    gate = ToolGate(ActionGate([NOTES.spec, DELETE_SPEC], reviewer=notes_reviewer), reg)

    @contextmanager
    def opener():
        yield store

    return NoteCommands(cfg, reg, gate, opener), store, cfg, reg


@pytest.mark.parametrize("text,saved", [
    ("Notiere: Milch kaufen", "Milch kaufen"), ("Merk dir, dass der Schlüssel im Flur liegt", "dass der Schlüssel im Flur liegt"),
    ("Schreib auf Zahnarzt am Dienstag", "Zahnarzt am Dienstag"), ("Neue Notiz: Geschenk für Oma", "Geschenk für Oma"),
    ("Kushim, notiere bitte Brot holen", "Brot holen"), ("Halte fest: Passwort ist nicht hier", "Passwort ist nicht hier"),
])
def test_add_note(text, saved):
    nc, store, *_ = make()
    assert nc.handle(text, True) == "Notiert."
    assert store.facts[0].text == saved and store.facts[0].kind == "note" and store.facts[0].source == "voice"
    assert store.audits[-1] == ("note_added", f"{len(saved)} Zeichen") and saved not in store.audits[-1][1]     # Audit ohne Text


def test_read_search_and_empty():
    nc, store, *_ = make()
    assert nc.handle("Lies meine Notizen vor", True) == "Du hast keine Notizen."
    nc.handle("Notiere: Milch kaufen", True)
    nc.handle("Notiere: Zahnarzt am Dienstag", True)
    msg = nc.handle("Lies meine Notizen vor", True)
    assert "2 Notizen" in msg and "Nummer 1: Zahnarzt" in msg and "Nummer 2: Milch" in msg
    assert "Milch kaufen" in nc.handle("Was habe ich über Milch notiert?", True)
    assert "keine Notiz" in nc.handle("Was habe ich über Auto notiert?", True)


def test_other_facts_are_never_read_as_notes():
    nc, store, *_ = make()
    store.add_fact("Lieblingsfarbe blau", kind="preference")
    assert nc.handle("Lies meine Notizen vor", True) == "Du hast keine Notizen."


def test_delete_asks_first_and_only_yes_deletes():
    nc, store, *_ = make()
    nc.handle("Notiere: Milch kaufen", True)
    nc.handle("Notiere: Brot holen", True)
    assert "löschen? Sage ja oder nein" in nc.handle("Lösche die letzte Notiz", True) and nc.awaiting and len(store.facts) == 2
    assert "Okay" in nc.handle("ja", True) and [f.text for f in store.facts] == ["Milch kaufen"]
    nc.handle("Lösche die letzte Notiz", True)
    assert "Abgebrochen" in nc.handle("nein", True) and len(store.facts) == 1
    nc.handle("Lösche die letzte Notiz", True)
    assert "Abgebrochen" in nc.handle("vielleicht", True) and len(store.facts) == 1


def test_delete_by_number_and_unclear_asks_back():
    nc, store, *_ = make()
    for t in ("a eins", "b zwei", "c drei"):
        nc.handle(f"Notiere: {t}", True)
    assert "Welche Notiz" in nc.handle("Lösche eine Notiz", True)
    assert "b zwei" in nc.handle("Lösche Notiz Nummer zwei", True)
    nc.handle("ja", True)
    assert [f.text for f in store.facts] == ["c drei", "a eins"]
    assert "So viele" in nc.handle("Lösche Notiz Nummer fünf", True)


def test_unverified_yes_does_not_delete():
    nc, store, *_ = make()
    nc.handle("Notiere: Milch kaufen", True)
    nc.handle("Lösche die letzte Notiz", True)
    assert "Abgebrochen" in nc.handle("ja", False) and len(store.facts) == 1


def test_off_by_default_unverified_refused_and_never_enabled_by_voice(tmp_path):
    nc, store, cfg, reg = make(enabled=())
    assert "kushim tools enable notes.local" in nc.handle("Notiere: Milch", True) and "nie per Sprache" in nc.handle("Notiere: Milch", True)
    assert store.facts == [] and not reg.enabled_names()
    nc, store, *_ = make()
    assert "deine Stimme" in nc.handle("Notiere: Milch", False) and store.facts == []


def test_ordinary_talk_is_not_a_note_command():
    nc, store, *_ = make()
    for text in ("Wie spät ist es", "Erzähl mir etwas über Notizbücher aus Leder und Papier", "Ich mag Milch", "Merkwürdig"):
        assert nc.handle(text, True) is None or "Notizen" in (nc.handle(text, True) or "")
    assert store.facts == []


def test_note_text_is_cleaned_and_limited():
    assert len(clean_note("x" * 900)) == 500 and "\x1b" not in clean_note("a\x1b[31mb\x00c")


def test_vault_unreachable_is_reported_not_raised():
    nc, store, *_ = make()

    @contextmanager
    def broken():
        raise FileNotFoundError("vault")
        yield

    nc.open_store = broken
    assert "nicht erreichbar" in nc.handle("Notiere: Milch", True)


def test_reviewer_flags_unknown_actions_and_gate_denies_when_killed():
    from kushim.safety.gate import ActionRequest
    nc, *_ = make()
    nc.gate.kill()
    assert "nicht" in nc.handle("Notiere: Milch", True)
    assert notes_reviewer(NOTES.spec, ActionRequest("notes.local", "Mail senden")) and not notes_reviewer(NOTES.spec, ActionRequest("notes.local", "Notiz anlegen"))


def test_registry_entry_is_local_default_off_and_chain_routes_confirmation():
    assert not NOTES.sends_data_out and not NOTES.spec.external_effect
    assert not ToolRegistry(default_tools()).is_active("notes.local")
    nc, store, *_ = make()
    chain = CommandChain([SimpleNamespace(awaiting=False, handle=lambda t, v, s=True: None), nc])
    chain.handle("Notiere: Milch", True)
    chain.handle("Lösche die letzte Notiz", True)
    assert chain.awaiting and "Okay" in chain.handle("ja", True)
