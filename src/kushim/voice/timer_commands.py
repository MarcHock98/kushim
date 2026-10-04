"""Sprachbefehle für Timer und Erinnerungen (Werkzeug `timer.local`, lokal, standardmäßig aus).

"Stell einen Timer auf zehn Minuten", "Erinnere mich in zwanzig Minuten an die Wäsche", "Welche Timer laufen?", "Lösche alle Timer".
Läuft ein Timer ab, wird er von sich aus angesagt (wie die Meldungen von Claude). Nur lokal; nichts verlässt den PC. Jede Aktion läuft durch
das Gate des Werkzeugs (Notaus, Werkzeug muss eingeschaltet sein); der Sprecher muss verifiziert sein.
"""
from __future__ import annotations

import queue
from typing import Any

from ..safety.gate import ActionRequest, Decision
from ..timers import Timer, TimerError, TimerStore, parse_duration
from .tool_commands import fold, words

TOOL = "timer.local"
_TIMER = {"timer", "wecker", "stoppuhr", "countdown", "erinnerung", "erinnerungen", "timers"}
_REMIND = {"erinner", "erinnere", "erinnerst", "wecke", "weck", "melde", "sag"}
_SET = {"stell", "stelle", "setz", "setze", "starte", "start", "mach", "mache", "ein", "erstelle", "neuen", "neuer", "einen", "auf", "von", "fur"}
_LIST = {"welche", "laufen", "lauft", "laeuft", "zeig", "zeige", "liste", "wie", "lange", "noch", "gibt", "habe", "offen", "aktiv", "gestellt", "hab"}
_CANCEL = {"losche", "loesche", "stoppe", "stopp", "stop", "beende", "entferne", "abbrechen", "bricht", "lass", "streiche", "aus", "ausschalten", "vergiss"}
_ALL = {"alle", "allen", "samtliche", "alles"}


def say_duration(seconds: float) -> str:
    s = int(round(seconds))
    if s >= 86400 and s % 86400 == 0:
        n = s // 86400
        return f"{n} Tag" + ("" if n == 1 else "e")
    if s >= 3600:
        h, m = divmod(s, 3600)
        m //= 60
        return f"{h} Stunde" + ("" if h == 1 else "n") + (f" {m} Minuten" if m else "")
    if s >= 60:
        m, sec = divmod(s, 60)
        return f"{m} Minute" + ("" if m == 1 else "n") + (f" {sec} Sekunden" if sec else "")
    return f"{s} Sekunde" + ("" if s == 1 else "n")


class TimerCommands:
    def __init__(self, cfg: Any, registry: Any, gate: Any, store: TimerStore):
        """`cfg`: LiveConfig (frische Werkzeug-Schalter), `registry`: ToolRegistry, `gate`: ToolGate mit Spec von `timer.local`."""
        self.cfg, self.registry, self.gate, self.store = cfg, registry, gate, store
        self.awaiting = False                                           # braucht nie eine Bestätigung (lokal, harmlos, umkehrbar)
        self._announce: "queue.SimpleQueue[str]" = queue.SimpleQueue()

    def _active(self) -> bool:
        self.registry.sync(self.cfg.tools_enabled)
        return self.registry.is_active(TOOL)

    def _allowed(self, what: str, verified: bool) -> str | None:
        """None = erlaubt, sonst der Satz für den Nutzer."""
        if not verified:
            return "Das mache ich nur auf deine Stimme."          # das Gate verlangt das für Nur-Lesen-Aktionen nicht, wir schon
        v = self.gate.check(ActionRequest(TOOL, what, speaker_verified=verified, user_initiated=True))
        return None if v.decision is Decision.ALLOW else "Das darf ich gerade nicht (" + v.reason + ")."

    # --- Meldungen von sich aus
    def announcement(self) -> str | None:
        if not self._active():
            return None
        due = self.store.take_due()
        for t in due:
            late = self.store.clock() - t.due > 120
            what = f": {t.label}" if t.label else ""
            self._announce.put(("Verpasst, " if late else "") + ("Erinnerung" if t.label else "Dein Timer ist abgelaufen") + what + ".")
        try:
            return self._announce.get_nowait()
        except queue.Empty:
            return None

    # --- Befehle
    def handle(self, text: str, verified: bool, strong: bool = True) -> str | None:
        ws = words(text)
        toks = [f for _, f in ws]
        s = set(toks)
        if not toks or not (s & _TIMER or s & _REMIND and ("an" in s or "daran" in s or any(t in s for t in ("minuten", "minute", "stunde", "stunden", "sekunden")))):
            return None
        seconds, rest = parse_duration(text)
        if s & _CANCEL and s & _TIMER and seconds is None:
            return self._cancel(s, verified)
        if s & _LIST and s & _TIMER and seconds is None:
            return self._list(verified)
        if seconds is None:
            if s & _TIMER and not s & (_CANCEL | _LIST):
                return "Wie lange soll der Timer laufen? Sag zum Beispiel: Stell einen Timer auf zehn Minuten."
            return None
        return self._set(seconds, rest, s, verified)

    def _off(self) -> str:
        return ("Das Werkzeug Timer ist aus. Einschalten kannst du es nur in den Einstellungen oder mit kushim tools enable timer.local, "
                "nie per Sprache.")

    def _set(self, seconds: float, rest: str, s: set[str], verified: bool) -> str:
        if not self._active():
            return self._off()
        no = self._allowed("Timer stellen", verified)
        if no:
            return no if verified else "Das mache ich nur auf deine Stimme."
        label = ""
        r = rest.split()
        low = [fold(w) for w in r]
        for i, w in enumerate(low):
            if w in ("an", "daran", "wegen", "fur") and i + 1 < len(low) and (s & _REMIND or "erinnerung" in s):
                label = " ".join(r[i + 1:])
                break
        if not label and s & _REMIND:
            label = " ".join(w for w, f in zip(r, low) if f not in ({"in", "mich", "an", "bitte", "mal", "kushim", "hey", "dich", "mir", "nach", "von", "jetzt"} | _REMIND | _SET))
        try:
            t = self.store.add(seconds, label)
        except TimerError as e:
            return str(e)
        return f"Okay, {say_duration(seconds)}" + (f", ich erinnere dich an {t.label}." if t.label else ".")

    def _list(self, verified: bool) -> str:
        if not self._active():
            return self._off()
        no = self._allowed("Timer anzeigen", verified)
        if no:
            return "Das mache ich nur auf deine Stimme." if not verified else no
        timers = self.store.list()
        if not timers:
            return "Es läuft kein Timer."
        now = self.store.clock()
        parts = [f"{say_duration(max(1, t.due - now))}" + (f" für {t.label}" if t.label else "") for t in timers[:5]]
        return f"Es laufen {len(timers)} Timer: " + ", ".join(parts) + "."

    def _cancel(self, s: set[str], verified: bool) -> str:
        if not self._active():
            return self._off()
        no = self._allowed("Timer löschen", verified)
        if no:
            return "Das mache ich nur auf deine Stimme." if not verified else no
        if s & _ALL:
            n = self.store.cancel_all()
            return f"Okay, {n} Timer gelöscht." if n else "Es lief kein Timer."
        t = self.store.cancel_next()
        return "Okay, der nächste Timer ist gelöscht." if t else "Es läuft kein Timer."
