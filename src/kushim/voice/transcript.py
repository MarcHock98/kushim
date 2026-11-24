"""Live-Transkript für die Oberfläche: die letzten Äußerungen und Antworten, nur im Arbeitsspeicher.

- Nie auf der Platte, nie im Vault, nie in der Zustandsdatei: der Puffer lebt im Sprachprozess und stirbt mit ihm.
- Höchstens `MAX_ENTRIES` Einträge, je Text höchstens `MAX_CHARS` Zeichen.
- Eine abgelehnte Stimme hinterlässt KEINEN Text (nur "rejected_speaker"): Worte Unbekannter werden nicht angezeigt.
- Notaus-Sätze hinterlassen keinen Text (die Oberfläche zeigt nur "Notaus-Befehl erkannt"); leere Ergebnisse fehlen ganz.

Ablauf einer Runde (Zeile "Du" sofort nach der Spracherkennung, nicht erst nach Claudes Antwort):
  1. `heard(raw, text)` direkt nach der STT: neuer Eintrag mit `status="pending"`, gibt die stabile `id` zurück.
  2. `sent(id)`, sobald der Befehl an Claude ging, oder `drop(id, reason)`, wenn er nicht an Claude geht.
  3. `add(result)` am Rundenende: setzt `reply` und `outcome` an genau diesem Eintrag (`result.entry`).
Jede Änderung erhöht `rev`; `since(rev)` liefert jeden geänderten Eintrag genau einmal.

Felder je Eintrag: id, rev, heard (Befehl ohne Weckwort, so wie er an Claude geht), raw (Whisper-Text mit Weckwort, nie
geschwärzt), ts (Erkennungszeit), status (pending | sent | dropped), reason (Code aus REASONS oder ""), sent_ts (Zahl oder
None), reply, outcome, unspoken (Zahl der Sätze der Antwort, die die Stimme nicht sprechen konnte und die nur als Text kamen;
0 = alles gesprochen oder nichts zu sprechen).

`track_unspoken` zählt diese Sätze je Runde über den Haken `Speaker.on_unspoken` (nur eine Zahl, kein Text, nichts auf der
Platte) und hängt sie als `unspoken` an das Ergebnis; `add` übernimmt sie.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable

MAX_ENTRIES = 50
MAX_CHARS = 2000
MAX_UNSPOKEN = 10_000                           # Obergrenze der Zählung (nur Anzeige)
SKIP = {"empty", "wake_only", "halted", "announced", "announce_interrupted"}   # ohne Eintrag (`id`) nicht aufnehmen; Meldungen
#                                                                              ohne Nutzereingabe erzeugen keine Zeile „Du“
REASONS = {"killed", "cancelled", "wake_only", "command", "end_conversation", "shutdown", "halted", "not_running",
           "send_failed"}
_SENT = {"spoken", "interrupted"}               # nur für Ergebnisse ohne Eintrag: diese gingen an das Sprachmodell


def _cut(text: Any) -> str:
    return str(text or "")[:MAX_CHARS]


def _unspoken(result: Any) -> int:
    """Zahl der nicht gesprochenen Sätze aus dem Ergebnis; fehlt sie oder passt sie nicht, 0."""
    n = getattr(result, "unspoken", 0)
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        return 0
    return min(n, MAX_UNSPOKEN)


def track_unspoken(speaker: Any, handle: Callable[[Any], Any]) -> Callable[[Any], Any]:
    """Umhüllt `pipeline.handle`: zählt je Runde, wie oft `speaker.on_unspoken` kam (ein Satz nur als Text, weil die Stimme
    ausfiel), und setzt die Zahl als `unspoken` an das Ergebnis. Der bisherige Haken läuft unverändert weiter (Hinweis und
    talk.log bleiben, wie sie sind). Gezählt wird nur im Thread der Runde: `Speaker.say` ruft den Haken im Thread des
    Aufrufers auf; Meldungen von sich aus (`say_text` aus der Schleife) zählen nicht mit und erzeugen auch keine Zeile."""
    local = threading.local()
    previous = speaker.on_unspoken

    def on_unspoken(text: str) -> None:
        n = getattr(local, "n", None)
        if n is not None:
            local.n = min(n + 1, MAX_UNSPOKEN)
        previous(text)

    def run(pcm: Any) -> Any:
        local.n = 0
        try:
            result = handle(pcm)
        finally:
            n, local.n = local.n, None
        try:
            result.unspoken = n
        except Exception:                           # noqa: BLE001 (Anzeige darf den Betrieb nie stören)
            pass
        return result

    speaker.on_unspoken = on_unspoken
    return run


class Transcript:
    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self._items: deque[dict[str, Any]] = deque(maxlen=MAX_ENTRIES)
        self._next = 1
        self._rev = 0

    def _bump(self, item: dict[str, Any]) -> None:
        self._rev += 1
        item["rev"] = self._rev

    def _find(self, entry_id: Any) -> dict[str, Any] | None:
        if isinstance(entry_id, bool) or not isinstance(entry_id, int):
            return None
        return next((i for i in self._items if i["id"] == entry_id), None)

    def heard(self, raw: str, text: str, reason: str = "") -> int:
        """Erkannter Text direkt nach der STT: neuer Eintrag `pending` (mit `reason` gleich `dropped`). Gibt die id zurück."""
        with self._lock:
            item: dict[str, Any] = {"id": self._next, "rev": 0, "heard": _cut(text), "raw": _cut(raw), "ts": self._clock(),
                                    "status": "dropped" if reason else "pending", "reason": str(reason), "sent_ts": None,
                                    "reply": "", "outcome": "", "unspoken": 0}
            self._next += 1
            self._bump(item)
            self._items.append(item)
            return item["id"]

    def sent(self, entry_id: int) -> bool:
        """Der Befehl ging an Claude. Nur aus `pending`."""
        with self._lock:
            item = self._find(entry_id)
            if item is None or item["status"] != "pending":
                return False
            item["status"], item["sent_ts"] = "sent", self._clock()
            self._bump(item)
            return True

    def drop(self, entry_id: int, reason: str) -> bool:
        """Der Befehl geht nicht an Claude (Grund aus REASONS). Nur aus `pending`."""
        with self._lock:
            item = self._find(entry_id)
            if item is None or item["status"] != "pending":
                return False
            item["status"], item["reason"] = "dropped", str(reason)
            self._bump(item)
            return True

    def add(self, result: Any) -> None:
        """Nimmt ein `Result` (heard, reply, outcome, entry) auf. Mit `entry`: ergänzt genau diesen Eintrag, sonst neuer Eintrag.
        Fehler hier dürfen den Betrieb nie stören."""
        outcome = str(getattr(result, "outcome", ""))
        rejected = outcome == "rejected_speaker"
        reply = "" if rejected else _cut(getattr(result, "reply", ""))
        unspoken = _unspoken(result) if reply else 0     # ohne Antwort gibt es nichts, was ungesprochen bleiben konnte
        entry = getattr(result, "entry", None)
        if entry is not None:
            with self._lock:
                item = self._find(entry)
                if item is None:                        # schon aus dem Puffer gefallen: nichts doppelt anlegen
                    return
                item["reply"], item["outcome"], item["unspoken"] = reply, outcome, unspoken
                if rejected or outcome == "killed":
                    item["heard"] = item["raw"] = ""
                self._bump(item)
            return
        if outcome in SKIP:
            return
        heard = "" if rejected or outcome == "killed" else _cut(getattr(result, "heard", ""))
        with self._lock:
            item = {"id": self._next, "rev": 0, "heard": heard, "raw": "", "ts": self._clock(),
                    "status": "sent" if outcome in _SENT else "dropped", "reason": outcome if outcome in REASONS else "",
                    "sent_ts": None, "reply": reply, "outcome": outcome, "unspoken": unspoken}
            self._next += 1
            self._bump(item)
            self._items.append(item)

    def since(self, last_rev: int = 0) -> list[dict[str, Any]]:
        """Alle Einträge, die sich nach `last_rev` geändert haben (neu oder ergänzt), in der Reihenfolge ihrer id."""
        with self._lock:
            return [dict(i) for i in self._items if i["rev"] > last_rev]

    def get(self, entry_id: int) -> dict[str, Any] | None:
        with self._lock:
            item = self._find(entry_id)
            return dict(item) if item is not None else None

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
