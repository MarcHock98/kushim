"""Wake Words per Sprachbefehl verwalten ("füge das Wake Word hey Kushim hinzu").

Geändert wird die zentrale Datei `wakewords.toml` (siehe wakeconfig.py). Sicherheitsnetz:
  1. Nur bei verifizierter Stimme (Pipeline reicht `verified` durch), sonst Ablehnung.
  2. Wörter werden streng geprüft (nur Buchstaben und Leerzeichen, oder bekannte Modellnamen).
  3. Die Änderung läuft über den ActionGate (umkehrbar, mit Rückfrage). Bestätigt wird per Sprache
     ("ja"), gebunden an genau den vorgelesenen Text (ApprovalQueue). Ohne Bestätigung passiert nichts.
  4. Mindestens ein Wake Word bleibt immer aktiv. Die Änderung gilt ab dem nächsten Start.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

from ..safety.approvals import ApprovalQueue
from ..safety.gate import ActionGate, ActionRequest, ActionSpec, Decision, Risk
from . import wakeconfig
from .trigger import PRETRAINED
from .wakeconfig import WakeWord, normalize_name

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
    def __init__(self, root: Path, clock=None):
        gate = ActionGate([SPEC], reviewer=lambda spec, req: set())
        kw = {} if clock is None else {"clock": clock}
        self.queue = ApprovalQueue(gate, ttl=60.0, **kw)
        self.root = root
        self._pending = None            # (Approval, neue WakeConfig)

    @staticmethod
    def _target(cmd: Parsed) -> tuple[str, str] | None:
        if cmd.word is not None:
            return "openwakeword", cmd.word
        if cmd.unknown:
            name = normalize_name(cmd.unknown, "kws")
            return ("kws", name) if wakeconfig._KWS_NAME.match(name) and len(name) >= 3 else None
        return None

    def handle(self, text: str, verified: bool) -> str | None:
        """Antwortet mit Text, wenn der Satz ein Wake-Word-Befehl (oder eine Bestätigung) ist, sonst None."""
        if self._pending is not None:
            return self._confirm(text, verified)
        cmd = parse(text)
        if cmd is None:
            return None
        if not verified:
            return "Das darf ich nur auf deine Stimme ändern."
        try:
            cfg = wakeconfig.load(self.root)
        except ValueError:
            return "Die Wake-Word-Datei ist fehlerhaft. Bitte korrigiere wakewords.toml."
        if cmd.action == "list":
            return "Aktive Wake Words: " + ", ".join(SPOKEN.get(w.name, w.name) for w in cfg.enabled()) + "."
        target = self._target(cmd)
        if target is None:
            return "Welches Wort meinst du? Sag zum Beispiel: Füge das Wake Word hey Kushim hinzu."
        engine, name = target
        spoken = SPOKEN.get(name, name)
        existing = next((w for w in cfg.words if (w.engine, w.name) == (engine, name)), None)
        if cmd.action == "add":
            if existing is not None and existing.enabled:
                return f"{spoken} ist schon aktiv."
            words = ([replace(w, enabled=True) if w is existing else w for w in cfg.words]
                     if existing else [*cfg.words, WakeWord(name, engine)])
            what = f"Wake Word {spoken} hinzufügen"
        else:
            if existing is None or not existing.enabled:
                return f"{spoken} ist gar nicht aktiv."
            words = [w for w in cfg.words if w is not existing]
            what = f"Wake Word {spoken} entfernen"
        new = replace(cfg, words=tuple(words))
        try:
            wakeconfig.validate(new, self.root)
        except ValueError as e:
            if cmd.action == "remove":
                return "Das ist das einzige aktive Wake Word, das lasse ich aktiv."
            return f"Das geht so nicht: {e}"
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
        try:
            wakeconfig.save(self.root, new)
        except (ValueError, OSError):
            return "Das konnte ich nicht speichern."
        return "Erledigt. Das gilt ab dem nächsten Start."
