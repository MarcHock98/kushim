"""Wake Words per Sprachbefehl verwalten ("füge das Wake Word Alexa hinzu").

Ablauf mit Sicherheitsnetz:
  1. Nur bei verifizierter Stimme (Pipeline reicht `verified` durch), sonst Ablehnung.
  2. Nur vortrainierte, bekannte Wörter. Unbekannte Wörter brauchen ein Training (noch nicht eingebaut)
     und werden nie einfach "angenommen".
  3. Die Änderung läuft über den ActionGate (umkehrbar, mit Rückfrage). Bestätigt wird per Sprache
     ("ja"), gebunden an genau den vorgelesenen Text (ApprovalQueue). Ohne Bestätigung passiert nichts.
  4. Mindestens ein Wake Word bleibt immer aktiv. Die Änderung gilt ab dem nächsten Start.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Callable

from ..safety.approvals import ApprovalQueue
from ..safety.gate import ActionGate, ActionRequest, ActionSpec, Decision, Risk
from .trigger import PRETRAINED

ACTION = "wake_word_change"
SPEC = ActionSpec(ACTION, Risk.REVERSIBLE)

# gesprochene Namen -> Modellname
ALIASES = {
    "alexa": "alexa",
    "hey jarvis": "hey_jarvis", "jarvis": "hey_jarvis",
    "hey mycroft": "hey_mycroft", "mycroft": "hey_mycroft",
    "hey rhasspy": "hey_rhasspy", "rhasspy": "hey_rhasspy", "raspi": "hey_rhasspy",
    "timer": "timer",
    "weather": "weather", "wetter": "weather",
}
SPOKEN = {"alexa": "Alexa", "hey_jarvis": "hey Jarvis", "hey_mycroft": "hey Mycroft",
          "hey_rhasspy": "hey Rhasspy", "timer": "Timer", "weather": "Weather"}

_KEYWORD = re.compile(r"\b(wake ?word|weckwort|aktivierungswort|signalwort|aufwachwort)s?\b")
_ADD = {"fuge", "fuege", "hinzu", "hinzufugen", "hinzufuegen", "aktiviere", "speichere", "merke", "nimm",
        "ergaenze", "erganze", "setze", "stelle"}
_REMOVE = {"entferne", "losche", "loesche", "deaktiviere", "streiche", "vergiss", "entfernen"}
_LIST = {"welche", "liste", "zeige", "nenne", "aktuell"}
_YES = {"ja", "jawohl", "klar", "bestatigt", "bestaetigt", "okay", "ok", "mach", "mache"}
_NO = {"nein", "abbrechen", "stopp", "stop", "nicht", "lass"}


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z]+", t))


def _words(text: str) -> set[str]:
    return set(_norm(text).split())


def find_word(text: str) -> str | None:
    """Erstes bekanntes Wake Word im Text (längere Namen zuerst)."""
    n = _norm(text)
    for alias in sorted(ALIASES, key=len, reverse=True):
        if re.search(rf"\b{alias}\b", n):
            return ALIASES[alias]
    return None


@dataclass
class Parsed:
    action: str          # "add" | "remove" | "list"
    word: str | None     # Modellname oder None
    unknown: str | None  # unbekanntes gewünschtes Wort (Klartext), falls keines passt


def parse(text: str) -> Parsed | None:
    n = _norm(text)
    if not _KEYWORD.search(n):
        return None
    w = set(n.split())
    if w & _LIST and not (w & _ADD or w & _REMOVE):
        return Parsed("list", None, None)
    action = "remove" if w & _REMOVE else "add" if w & _ADD else None
    if action is None:
        return None
    word = find_word(n)
    if word:
        return Parsed(action, word, None)
    tail = _KEYWORD.split(n, maxsplit=1)[-1].split()
    stop = _ADD | _REMOVE | {"das", "dem", "die", "den", "neue", "neues", "bitte", "als", "zu", "meine", "meinen",
                              "liste", "ein", "eine", "mir", "ist", "wort", "und", "auch", "noch", "hinzu"}
    guess = " ".join(x for x in tail if x not in stop)
    return Parsed(action, None, guess or None)


class WakeWordCommands:
    def __init__(self, get_words: Callable[[], list[str]], set_words: Callable[[list[str]], None],
                 clock=None):
        gate = ActionGate([SPEC], reviewer=lambda spec, req: set())
        kw = {} if clock is None else {"clock": clock}
        self.queue = ApprovalQueue(gate, ttl=60.0, **kw)
        self.get_words, self.set_words = get_words, set_words
        self._pending = None            # (Approval, neue Liste)

    def handle(self, text: str, verified: bool) -> str | None:
        """Antwortet mit Text, wenn der Satz ein Wake-Word-Befehl (oder eine Bestätigung) ist, sonst None."""
        if self._pending is not None:
            return self._confirm(text, verified)
        cmd = parse(text)
        if cmd is None:
            return None
        if not verified:
            return "Das darf ich nur auf deine Stimme ändern."
        words = list(self.get_words())
        if cmd.action == "list":
            return "Aktive Wake Words: " + ", ".join(SPOKEN.get(w, w) for w in words) + "."
        if cmd.word is None:
            who = f"'{cmd.unknown}'" if cmd.unknown else "dieses Wort"
            return (f"Das Wort {who} kenne ich noch nicht. Es müsste erst trainiert werden, "
                    "das ist noch nicht eingebaut. Du kannst zwischen " +
                    ", ".join(SPOKEN[w] for w in sorted(PRETRAINED)) + " wählen.")
        if cmd.word not in PRETRAINED:
            return "Dieses Wake Word ist nicht erlaubt."
        name = SPOKEN.get(cmd.word, cmd.word)
        if cmd.action == "add":
            if cmd.word in words:
                return f"{name} ist schon aktiv."
            new = words + [cmd.word]
            what = f"Wake Word {name} hinzufügen"
        else:
            if cmd.word not in words:
                return f"{name} ist gar nicht aktiv."
            if len(words) == 1:
                return "Das ist das einzige Wake Word, das lasse ich aktiv."
            new = [w for w in words if w != cmd.word]
            what = f"Wake Word {name} entfernen"
        decision, approval = self.queue.submit(ActionRequest(
            ACTION, what, speaker_verified=verified, user_initiated=True))
        if decision is not Decision.ASK or approval is None:
            return "Das darf ich gerade nicht ändern."
        self._pending = (approval, new)
        return f"Soll ich das wirklich tun: {what}? Sage ja oder nein."

    def _confirm(self, text: str, verified: bool) -> str:
        approval, new = self._pending
        self._pending = None
        w = _words(text)
        if not verified:
            self.queue.deny(approval.id)
            return "Abgebrochen, das darf ich nur auf deine Stimme ändern."
        if w & _NO or not (w & _YES):
            self.queue.deny(approval.id)
            return "Abgebrochen. Es bleibt alles, wie es ist."
        if not self.queue.approve(approval.id, approval.digest) or self.queue.take(approval.id) is None:
            return "Die Bestätigung ist abgelaufen. Sag den Befehl bitte noch einmal."
        self.set_words(new)
        return "Erledigt. Das gilt ab dem nächsten Start."
