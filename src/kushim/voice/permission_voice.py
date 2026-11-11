"""Freigaben per Stimme (Roadmap v2 C3): Claude fragt im Terminal, kushim fragt laut nach, „ja“ erlaubt.

Regeln (sicherheitsrelevant):
- Erlaubt wird nur mit **stark** verifizierter Stimme (eingeschriebenes Profil, ganzer Satz). Ohne Profil nie.
- „nein“, Stille, Zeitablauf oder alles Unklare senden **nichts**: Der Dialog im Terminal bleibt offen, dort entscheidet
  der Nutzer. kushim sendet nie „deny“ von sich aus (das macht nur der Notaus).
- Gefragt wird nur, wenn die Ansage vollständig ist (`speakable.complete`) und die Sperrliste nichts einwendet (`blocked`,
  C4). Ohne Sperrliste ist alles gesperrt (fail-closed).
- Die Antwort gilt nur für die zuletzt gestellte Frage und nur `ASK_TTL` Sekunden lang.
"""
from __future__ import annotations

import re
import time
import unicodedata
from typing import Any, Callable

from ..channel import speakable
from ..channel.bridge import Bridge, Permission

ASK_TTL = 60.0
MAX_WORDS = 7                   # „Ja, das erlaube ich jetzt“: längere Sätze sind kein klares Ja

HOW = "Sag: Ja, das erlaube ich."
ALLOWED = "Erlaubt. Claude macht weiter."
NOT_SENT = "Okay, ich erlaube es nicht. Die Frage bleibt im Terminal offen."
NEED_VOICE = "Freigaben per Stimme gehen nur mit deiner eingeschriebenen Stimme. Bitte im Terminal bestätigen."
NEED_STRONG = "Ich habe dich nicht sicher genug erkannt. Sag es bitte in einem ganzen Satz: Ja, das erlaube ich."
GONE = "Die Anfrage ist schon erledigt."
KILLED = "Der Notaus ist aktiv, ich gebe nichts weiter."
FAILED = "Das konnte ich nicht an Claude geben. Bitte im Terminal bestätigen."

# Nur diese ganzen Sätze zählen als Ja (nach dem Audit 2026-11-11: „Ja, was macht der Befehl?“ darf nie erlauben).
YES_PHRASES = {"ja das erlaube ich", "ja ich erlaube das", "ja ich erlaube es", "das erlaube ich", "ich erlaube das",
               "ja erlauben", "ja erlaube es", "ja das ist erlaubt", "ja bitte erlauben", "ja das darfst du",
               "ja das darf claude", "ja"}
_NO = {"nein", "nicht", "nee", "ne", "nö", "no", "stopp", "stop", "warte", "warten", "lass", "verbiete", "ablehnen", "später",
       "kein", "keine", "keinen", "halt", "moment", "abbrechen"}
_TOKEN = re.compile(r"[a-zäöüß]+")


def _words(text: str) -> list[str]:
    t = unicodedata.normalize("NFC", text.lower())
    return _TOKEN.findall(t)


def is_yes(text: str) -> bool:
    """Nur eine feste Zusage, nichts dazu. Ein bloßes „ja“ zählt als Ja, ist aber zu kurz für „stark“ (dann Nachfrage)."""
    return " ".join(_words(text)) in YES_PHRASES


def is_no(text: str) -> bool:
    w = _words(text)
    return bool(w) and len(w) <= MAX_WORDS and bool(set(w) & _NO)


def _block_all(perm: Permission) -> str | None:
    return "keine Sperrliste"


class PermissionVoice:
    """Sprachbefehle der Pipeline (`handle(text, verified, strong)`, `awaiting`) für Claudes Freigabe-Anfragen."""

    def __init__(self, bridge: Bridge, blocked: Callable[[Permission], str | None] = _block_all,
                 clock: Callable[[], float] = time.monotonic, ttl: float = ASK_TTL,
                 on_decision: Callable[[dict[str, Any]], None] = lambda d: None):
        self.bridge, self.blocked, self.clock, self.ttl, self.on_decision = bridge, blocked, clock, ttl, on_decision
        self._asked: Permission | None = None
        self._asked_at = 0.0

    @property
    def awaiting(self) -> bool:
        if self._asked is not None and self.clock() - self._asked_at > self.ttl:
            self._asked = None                      # Zeitablauf: nichts senden, Terminal entscheidet
        return self._asked is not None

    def offer(self, perm: Permission) -> str:
        """Ansage für eine neue Anfrage. Fragt „Erlauben?“ nur, wenn eine Antwort per Stimme zulässig ist."""
        if speakable.complete(perm) and self.blocked(perm) is None:
            self._asked, self._asked_at = perm, self.clock()
            return f"{speakable.describe(perm)} {speakable.QUESTION} {HOW}"
        if self._asked is not None:
            self._asked = None                      # neue Anfrage: die alte Frage gilt nicht mehr
        return speakable.announce(perm)

    def handle(self, text: str, verified: bool, strong: bool = False) -> str | None:
        """None, wenn keine Frage offen ist oder der Satz weder Ja noch Nein ist (dann geht er normal an Claude)."""
        if not self.awaiting:
            return None
        perm = self._asked
        if is_no(text):
            self._asked = None
            self._log(perm, "not_sent", verified, strong)
            return NOT_SENT
        if not is_yes(text):
            return None
        if not verified:
            self._asked = None
            self._log(perm, "no_voice", verified, strong)
            return NEED_VOICE
        if not strong:
            self._log(perm, "weak", verified, strong)
            return NEED_STRONG                      # Frage bleibt offen, bis zum Zeitablauf
        self._asked = None
        if self.blocked(perm) is not None:          # nochmal prüfen, falls sich die Sperrliste geändert hat
            self._log(perm, "blocked", verified, strong)
            return speakable.TERMINAL
        status = self.bridge.answer(perm.request_id, "allow")
        self._log(perm, {"ok": "allowed", "unknown": "gone"}.get(status, status), verified, strong)
        return {"ok": ALLOWED, "unknown": GONE, "kill": KILLED}.get(status, FAILED)

    def _log(self, perm: Permission, result: str, verified: bool, strong: bool) -> None:
        try:
            self.on_decision({"request_id": perm.request_id, "tool": perm.tool_name, "result": result,
                              "verified": verified, "strong": strong})
        except Exception:                           # noqa: BLE001 (Protokoll darf nie die Antwort verhindern)
            pass
