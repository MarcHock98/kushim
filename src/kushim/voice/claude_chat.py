"""Antwortweg über Claude Code (Roadmap v2 B4): Befehl über die Brücke senden, `sprich`-Antworten vorlesen.

Seit 2026-11-11 (Wunsch des Nutzers) keine feste Quittung mehr: Claude sagt zuerst selbst kurz, was es vorhat
(`sprich` mit zwischenstand=true), dann das Ergebnis. Seit 2026-11-23 ist Claude für den Nutzer kushim selbst: Was kushim
von sich aus sagt, nennt nie „Claude“ und nie eine Weitergabe. Schweigt Claude FILLER_AFTER Sekunden, sagt kushim einmal
ein kurzes Füllwort in der ersten Person („Moment.“), reihum aus FILLERS.

Ersetzt den Platzhalter `not_connected` in der Pipeline. Wartet in kurzen Abständen (POLL Sekunden) auf Claudes Antwort,
damit "abbrechen" und der Notaus schnell greifen. Braucht Claude länger als `patience`, sagt kushim das und liest die
Antwort später von sich aus vor (`announcement`, nur wenn gerade nichts läuft). Claudes Text ist nur zum Vorlesen da.
Freigabe-Anfragen von Claude werden je einmal angesagt; bestätigt wird nie per Stimme, nur im Claude-Fenster oder in der
Oberfläche (es gibt keine Sprecher-Prüfung).
"""
from __future__ import annotations

import time
from typing import Any, Callable, Iterator

from ..channel import speakable
from ..channel.bridge import Bridge
from ..tasks import TaskRegistry
from . import earcon

FILLERS = ("Moment.", "Ich schau mal.", "Einen Augenblick.")    # reihum, höchstens eins je Runde
FILLER_AFTER = 2.5              # Sekunden ohne `sprich`, bis kushim ein Füllwort sagt
NOT_RUNNING = "Ich bin gerade nicht startklar. Starte mich bitte mit kushim start neu."
KILLED = "Der Notaus ist aktiv. Ich mache nichts, bis du ihn aufhebst."
FAILED = "Das hat gerade nicht geklappt. Sag es bitte noch einmal."
LATE = "Das dauert etwas länger, ich melde mich gleich."
LOST = "Ich bin gerade nicht erreichbar. Starte mich bitte neu."
# Schutz gegen eine stumme Runde: Der Channel sieht kein Ende einer Claude-Runde (nur Werkzeugaufrufe an kushim). Laut
# Anweisung kommt aber immer zuerst ein `sprich` (Antwort oder Zwischenstand). Kam SILENT_AFTER Sekunden gar nichts, endet die
# Runde mit diesem Satz; die Anfrage bleibt offen ("abbrechen" erreicht Claude), eine spätere Antwort kommt als Meldung.
SILENT = "Ich bin noch dran. Sag abbrechen, wenn ich aufhören soll."
SILENT_AFTER = 25.0
POLL = 2.0                      # Sekunden je Abruf: so schnell greifen Abbrechen und Notaus
PATIENCE = 180.0                # so lange wartet eine Runde auf Claude, danach kommt die Antwort als Meldung
ANNOUNCE_EVERY = 2.0            # so oft fragt die Schleife im Leerlauf nach verspäteten Antworten
MAX_ANNOUNCED = 200             # gemerkte, schon angesagte Freigabe-Anfragen
TASK_NAME = "Claude arbeitet"   # nur Name in der Aufgabenliste (nie gesprochen)


class ClaudeChat:
    """Aufrufbar wie ein ChatStream: `chat(messages)` liefert die zu sprechenden Texte."""

    yields_messages = True          # jedes Stück ist eine ganze Meldung (nicht Token): die Pipeline spricht es sofort

    def __init__(self, bridge: Bridge, tasks: TaskRegistry, patience: float = PATIENCE,
                 clock: Callable[[], float] = time.monotonic):
        self.bridge, self.tasks, self.patience, self.clock = bridge, tasks, patience, clock
        self._next_announce = 0.0
        self._announced: list[str] = []         # request_ids, die schon vorgelesen wurden (neueste hinten)
        self._fillers = 0                       # wie viele Füllwörter schon gesagt wurden (bestimmt das nächste)
        self._request: Any = None               # (key, Token) der offenen Anfrage an Claude, sonst None
        # Haken für das Live-Transkript: bekommt direkt nach `bridge.send` dessen Status ("ok", "not_running", "kill", ...).
        # Nur Anzeige; ein Fehler darin stört die Runde nie.
        self.on_send: Callable[[str], None] | None = None

    def filler(self) -> str:
        """Nächstes Füllwort, reihum (deterministisch, damit Tests und Nutzer wissen, was kommt)."""
        text = FILLERS[self._fillers % len(FILLERS)]
        self._fillers += 1
        return text

    def permission_notes(self) -> list[str]:
        """Ansagen für neue, noch offene Freigabe-Anfragen; jede nur einmal, mit Signalton davor (nur kushim selbst, nie `sprich`)."""
        new = [p for p in self.bridge.pending() if p.request_id not in self._announced]
        self._announced.extend(p.request_id for p in new)
        del self._announced[:-MAX_ANNOUNCED]
        return [earcon.mark(speakable.announce(p)) for p in new]

    # --- offene Anfrage: "abbrechen" erreicht Claude, bis ein Ergebnis da ist (auch nach SILENT und LATE)
    def _open(self) -> Any:
        """Neue Anfrage an Claude ist unterwegs: als abbrechbare Aufgabe anmelden (ersetzt eine ältere, noch offene)."""
        self._close()
        holder: dict[str, Any] = {}

        def cancel() -> None:                          # "abbrechen": Claude bekommt kind="cancel", danach ist nichts mehr offen
            self.bridge.cancel()
            if self._request is holder.get("entry"):
                self._close()
        key, token = self.tasks.begin(TASK_NAME, cancel=cancel)
        holder["entry"] = self._request = (key, token)
        return token

    def _close(self) -> None:
        """Ergebnis da, Notaus oder Verbindung weg: nichts mehr offen, "abbrechen" sagt dann ehrlich, dass nichts läuft."""
        if self._request is not None:
            self.tasks.end(self._request[0])
            self._request = None

    def request_open(self) -> bool:
        return self._request is not None

    def __call__(self, messages: list[dict[str, str]], **_: Any) -> Iterator[str]:
        text = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
        status = self.bridge.send(text)
        if self.on_send is not None:
            try:
                self.on_send(status)
            except Exception:                         # noqa: BLE001 (Anzeige darf den Betrieb nie stören)
                pass
        if status != "ok":
            yield {"not_running": NOT_RUNNING, "kill": earcon.mark(KILLED)}.get(status, FAILED)
            return
        start = self.clock()
        deadline, said, heard = start + self.patience, False, False     # said: etwas gesagt (auch Füllwort); heard: von Claude
        token = self._open()
        while not token.cancelled():
            now = self.clock()
            left = deadline - now
            if left <= 0:
                yield LATE                            # Anfrage bleibt offen: "abbrechen" erreicht Claude weiter
                return
            wait = min(POLL, left)
            if not said:
                until_filler = start + FILLER_AFTER - now
                if until_filler <= 0:
                    yield self.filler()               # Claude hat sich noch nicht gemeldet: kurz, natürlich, einmal
                    said = True
                    continue
                wait = min(wait, until_filler)        # pünktlich nach FILLER_AFTER nachsehen, nicht erst beim nächsten POLL
            status, texts = self.bridge.fetch(wait=wait)
            if token.cancelled():
                return
            notes = self.permission_notes()
            if notes:
                yield " ".join(notes + texts)
                return                                # bei einer Freigabe wartet Claude: Runde beenden, Anfrage bleibt offen
            if texts:
                yield " ".join(texts)
                said = heard = True
                if getattr(self.bridge, "last_final", True):
                    self._close()
                    return                            # Ergebnis da; nach einem Zwischenstand („Ich schaue …“) weiter warten
                continue
            if status == "kill":
                self._close()
                yield earcon.mark(KILLED)
                return
            if status == "not_running":
                self._close()
                yield LOST
                return
            if not heard and self.clock() - start >= SILENT_AFTER:
                yield SILENT                          # Anfrage bleibt offen; eine spätere Antwort kommt als Meldung
                return

    def announcement(self) -> str | None:
        """Für die Sprachschleife im Leerlauf: eine verspätete oder von Claude selbst gesendete Antwort, sonst None."""
        now = self.clock()
        if now < self._next_announce:
            return None
        self._next_announce = now + ANNOUNCE_EVERY
        if not self.bridge.available():
            return None
        status, texts = self.bridge.fetch(wait=0)
        if status == "ok" and texts and getattr(self.bridge, "last_final", True):
            self._close()                             # das verspätete Ergebnis ist da
        elif status == "kill":
            self._close()
        parts = self.permission_notes() + (texts if status == "ok" else [])
        return " ".join(parts) if parts else None
