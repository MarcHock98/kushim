"""Abbrechen: laufende Aufgaben (Recherche, Claude-Lauf, offene Freigaben) lassen sich auf Zuruf beenden, ohne etwas zu sperren.

"Abbrechen" ist NICHT der Notaus: Es beendet nur das, was gerade läuft oder auf Freigabe wartet, danach geht alles normal weiter.
Der Notaus (safety/killswitch.py) hält dagegen alles an und sperrt bis zum bewussten Aufheben. Abbrechen ist immer sicher und braucht
deshalb keine Sprecher-Prüfung (wie Anhalten): ein Fremder kann höchstens eine Aufgabe des Nutzers beenden, nie etwas auslösen.

Jede Aufgabe, die lange laufen kann, meldet sich mit `running(name, cancel)` an und fragt `token.cancelled()` regelmäßig ab.
Offene Freigaben (`ApprovalQueue`) werden beim Abbrechen abgelehnt.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from .safety.killswitch import _tokens

# Kurze Sätze, die als Abbruch gelten (nach Normalisierung: klein, ohne Umlaute/Satzzeichen). Längere Sätze mit dem Wort
# "Abbruch" mitten in einer Frage ("Recherche zum Abbruch der Verhandlungen") sind kein Befehl.
MAX_TOKENS = 6
_WORDS = {"abbrechen", "abbruch", "cancel"}
_PHRASES = [("brich", "ab"), ("brich", "das", "ab"), ("brich", "es", "ab"), ("brich", "den", "befehl", "ab"),
            ("breche", "ab"), ("vergiss", "es"), ("vergiss", "das"), ("lass", "es"), ("lass", "das"), ("lass", "es", "sein"),
            ("stopp", "den", "befehl"), ("stop", "den", "befehl"), ("doch", "nicht"), ("nicht", "ausfuhren")]


def is_cancel_phrase(text: str) -> bool:
    toks = _tokens(text)
    if not toks or len(toks) > MAX_TOKENS:
        return False
    if any(t in _WORDS for t in toks):
        return True
    if "brich" in toks and "ab" in toks:
        return True
    return any(tuple(toks[i:i + len(ph)]) == ph for ph in _PHRASES for i in range(len(toks) - len(ph) + 1))


class Token:
    """Handle einer laufenden Aufgabe: die Aufgabe fragt `cancelled()` ab; `cancel()` setzt das Zeichen und ruft die Abbruchfunktion."""

    def __init__(self, name: str, cancel: Callable[[], None]):
        self.name, self._cancel, self._event = name, cancel, threading.Event()

    def cancel(self) -> None:
        self._event.set()
        try:
            self._cancel()
        except Exception:                              # noqa: BLE001 (ein kaputter Abbruch darf die anderen nicht aufhalten)
            pass

    def cancelled(self) -> bool:
        return self._event.is_set()


class TaskRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[int, Token] = {}
        self._queues: list[Any] = []
        self._next = 0

    @contextmanager
    def running(self, name: str, cancel: Callable[[], None] = lambda: None) -> Iterator[Token]:
        token = Token(name, cancel)
        with self._lock:
            key, self._next = self._next, self._next + 1
            self._tasks[key] = token
        try:
            yield token
        finally:
            with self._lock:
                self._tasks.pop(key, None)

    def add_queue(self, queue: Any) -> None:
        """Eine `ApprovalQueue`, deren offene Freigaben beim Abbrechen abgelehnt werden."""
        self._queues.append(queue)

    def active(self) -> list[str]:
        with self._lock:
            return [t.name for t in self._tasks.values()]

    def pending_approvals(self) -> int:
        return sum(len(q.pending()) for q in self._queues)

    def cancel_all(self) -> list[str]:
        """Beendet alle laufenden Aufgaben und lehnt offene Freigaben ab. Gibt Namen dessen zurück, was abgebrochen wurde."""
        with self._lock:
            tokens = list(self._tasks.values())
        names = []
        for t in tokens:
            t.cancel()
            names.append(t.name)
        for q in self._queues:
            for item in list(q.pending()):
                if q.deny(item.id):
                    names.append(f"Freigabe für {item.request.action}")
        return names
