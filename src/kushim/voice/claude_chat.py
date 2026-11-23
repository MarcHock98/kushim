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

Unterbrechen und Notaus (`stop`, von der Pipeline je Runde): Danach holt die Runde kein `/reply` mehr ab, sonst landete eine
spätere Antwort im Nichts oder als falsche Antwort auf die nächste Frage. Was nach dem Stopp schon abgeholt war, wird nicht
verworfen, sondern später als Meldung nachgereicht (`announcement`). Abgeholt wird nie gleichzeitig aus zwei Runden.
Idee für später (nicht umgesetzt): eine Anfrage-ID im Bridge-Protokoll, damit jede Antwort eindeutig ihrer Frage zugeordnet ist.
"""
from __future__ import annotations

import threading
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
    accepts_stop = True             # `chat(messages, stop=...)`: Stopp der Runde (Unterbrechen, Notaus)

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
        self._fetch_lock = threading.Lock()     # nie zwei Abrufe von `/reply` gleichzeitig (alte und neue Runde)
        self._request_lock = threading.RLock()  # schützt `_request` (alte Runde im Hintergrund, neue Runde, Leerlauf)
        self._late_lock = threading.Lock()
        self._late: list[str] = []              # nach einem Stopp abgeholte Texte, kommen als Meldung

    def defer(self, texts: list[str]) -> None:
        """Abgeholte, aber nicht mehr gesprochene Texte für die nächste Meldung merken (nie still verwerfen)."""
        texts = [t for t in texts if t]
        if texts:
            with self._late_lock:
                self._late.extend(texts)

    def _take_late(self) -> str | None:
        with self._late_lock:
            late, self._late = self._late, []
        return " ".join(late) if late else None

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
        """Neue Anfrage an Claude ist unterwegs: als abbrechbare Aufgabe anmelden (ersetzt eine ältere, noch offene).
        Gibt den Eintrag (key, Token) zurück; eine Runde schließt später nur ihren eigenen Eintrag."""
        holder: dict[str, Any] = {}

        def cancel() -> None:                          # "abbrechen": Claude bekommt kind="cancel", danach ist nichts mehr offen
            self.bridge.cancel()
            self._close(holder.get("entry"))
        with self._request_lock:
            self._close()
            key, token = self.tasks.begin(TASK_NAME, cancel=cancel)
            holder["entry"] = self._request = (key, token)
            return holder["entry"]

    def _close(self, entry: Any = None) -> None:
        """Ergebnis da, Notaus oder Verbindung weg: nichts mehr offen, "abbrechen" sagt dann ehrlich, dass nichts läuft.
        Mit `entry`: nur schließen, wenn das noch die offene Anfrage ist (eine alte, unterbrochene Runde schließt nie die
        Anfrage der neuen)."""
        with self._request_lock:
            if self._request is None or (entry is not None and self._request is not entry):
                return
            key, self._request = self._request[0], None
            self.tasks.end(key)

    def request_open(self) -> bool:
        with self._request_lock:
            return self._request is not None

    def __call__(self, messages: list[dict[str, str]], stop: Callable[[], bool] | None = None, **_: Any) -> Iterator[str]:
        stopped = stop if stop is not None else (lambda: False)
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
        mine = self._open()
        token = mine[1]
        while not token.cancelled():
            if stopped():                             # Unterbrechen/Notaus: kein weiteres `/reply`, Anfrage bleibt offen
                return
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
            with self._fetch_lock:
                if stopped():
                    return
                status, texts = self.bridge.fetch(wait=wait)
                final = getattr(self.bridge, "last_final", True)
            if token.cancelled():
                return
            notes = self.permission_notes()
            if stopped():                             # während des Abrufs unterbrochen: nachreichen statt verwerfen
                self.defer(notes + (texts if status == "ok" else []))
                if (status == "ok" and texts and final) or status in ("kill", "not_running"):
                    self._close(mine)                 # nur die eigene Anfrage; eine neuere bleibt offen
                return
            if notes:
                yield " ".join(notes + texts)
                return                                # bei einer Freigabe wartet Claude: Runde beenden, Anfrage bleibt offen
            if texts:
                yield " ".join(texts)
                said = heard = True
                if final:
                    self._close(mine)
                    return                            # Ergebnis da; nach einem Zwischenstand („Ich schaue …“) weiter warten
                continue
            if status == "kill":
                self._close(mine)
                yield earcon.mark(KILLED)
                return
            if status == "not_running":
                self._close(mine)
                yield LOST
                return
            if not heard and self.clock() - start >= SILENT_AFTER:
                yield SILENT                          # Anfrage bleibt offen; eine spätere Antwort kommt als Meldung
                return

    def announcement(self) -> str | None:
        """Für die Sprachschleife im Leerlauf: eine verspätete oder von Claude selbst gesendete Antwort, sonst None."""
        late = self._take_late()
        if late:                                      # nach einem Unterbrechen abgeholt: zuerst nachreichen
            return late
        now = self.clock()
        if now < self._next_announce:
            return None
        self._next_announce = now + ANNOUNCE_EVERY
        if not self.bridge.available():
            return None
        if not self._fetch_lock.acquire(blocking=False):      # eine unterbrochene Runde ruft gerade noch ab: später
            return None
        try:
            status, texts = self.bridge.fetch(wait=0)
            final = getattr(self.bridge, "last_final", True)
        finally:
            self._fetch_lock.release()
        if status == "ok" and texts and final:
            self._close()                             # das verspätete Ergebnis ist da
        elif status == "kill":
            self._close()
        parts = self.permission_notes() + (texts if status == "ok" else [])
        return " ".join(parts) if parts else None
