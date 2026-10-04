"""Sprachbefehle für Werkzeuge: anzeigen, recherchieren, Claude steuern. Alles läuft über die geprüften Wege, nie daran vorbei.

Was gesagt werden kann (Beispiele):
  "Welche Werkzeuge hast du?"                              -> ehrliche Liste aus dem echten Stand (nicht vom Sprachmodell erfunden)
  "Wie schalte ich die Werkzeuge ein?"                     -> Erklärung; Einschalten geht NIE per Sprache, nur UI/CLI
  "Recherchiere die Höhe des Eiffelturms" / "Schau ... nach" -> Claude zuerst, Wikipedia als Ersatz (research.py)
  "Nutze Claude um das Projekt kushim weiterzuentwickeln"  -> Claude entwickelt im freigegebenen Ordner (claude_cli/control.py)
  "Was macht Claude?" / "Stopp Claude" / "Was hat Claude gemacht?" / "Antwort an Claude: ..." / "Erlaube das"

Sicherheit: Jede Außenwirkung (Recherche, Claude starten, Claude antworten) ist ein Vorschlag mit vorgelesener Vorschau, den der Nutzer mit "ja"
bestätigt (hash-gebunden über die ApprovalQueue). Claude starten und beantworten brauchen eine STARK verifizierte Stimme. Antworten aus dem Netz
oder von Claude werden nur gesprochen, nie als Befehl gelesen. Die Pipeline ruft `handle` erst nach der Sprecher-Prüfung auf; Notaus und
"abbrechen" stehen davor.
"""
from __future__ import annotations

import difflib
import queue
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable

from ..claude_cli import report
from ..claude_cli.folders import Folder, resolve
from ..claude_cli.session import SessionError
from ..tools.registry import ToolRegistry
from .wake_commands import _NO, _YES, _words

_WORD = re.compile(r"[\wäöüÄÖÜß]+", re.UNICODE)


def fold(word: str) -> str:
    """Klein, ohne Umlaute und Satzzeichen ("Fähigkeiten" -> "fahigkeiten")."""
    return unicodedata.normalize("NFKD", word.lower()).encode("ascii", "ignore").decode()


def words(text: str) -> list[tuple[str, str]]:
    """(Originalwort, gefaltetes Wort); Originale bleiben für die Anfrage erhalten (Umlaute)."""
    return [(w, fold(w)) for w in _WORD.findall(text) if fold(w)]


def is_claude(token: str) -> bool:
    return token in {"claude", "claud", "klaud", "klaude", "clode", "clod"} or difflib.SequenceMatcher(None, "claude", token).ratio() >= 0.8


_TOOL_WORDS = {"tools", "tool", "werkzeuge", "werkzeug", "fahigkeiten", "fahigkeit", "funktionen"}
_SHOW = {"hast", "hat", "welche", "zeig", "zeige", "zeigen", "nenne", "liste", "anzeigen", "gibt", "gibts", "habe", "verfugbar", "aktiv",
         "sind", "stehen", "kannst", "gib", "geb", "liste", "auflisten", "aufzahlen", "uber"}
_ENABLE = {"einschalten", "aktivieren", "anschalten", "freischalten", "aktiviere", "anmachen", "schalte", "schalt", "ein"}
_ENGINES = {"web", "search", "recherche", "websuche", "claude", "modus"}
_DEV = {"weiterzuentwickeln", "weiterentwickeln", "weiterentwickle", "weiterentwickelt", "entwickeln", "entwickle", "programmieren",
        "programmiere", "arbeiten", "arbeite", "coden", "bauen", "baue"}
_USE = {"nutze", "nutz", "benutze", "starte", "lass", "lasse", "soll", "bitte", "los", "kannst", "nimm", "verwende", "setz", "setze"}
_STATUS = {"status", "stand", "weit", "macht", "fertig", "lauft", "laeuft", "arbeitet", "dran"}
_STOP = {"stopp", "stop", "stoppe", "stoppen", "beende", "beenden", "halt", "anhalten"}
_RESULT = {"ergebnis", "gemacht", "getan", "zusammenfassung", "ubersicht", "uebersicht", "bericht", "fakten", "gebaut", "erreicht"}
_ALLOW = {"erlaube", "erlauben", "erlaubt", "freigeben", "gib"}
_RESEARCH_DROP = {"recherchiere", "recherchier", "recherche", "recherchieren", "schau", "schaue", "schauen", "nach", "suche", "such", "suchen",
                  "internet", "online", "netz", "kushim", "hey", "bitte", "mal", "doch", "mir", "mich", "claude"}


@dataclass
class Intent:
    kind: str                   # list | enable_how | research | start | status | stop | result | answer | allow
    text: str = ""              # Anfrage, Auftrag oder Antwort (im Original, mit Umlauten)
    folder_hint: str = ""       # ganzer Satz, daraus wird der Ordnername aufgelöst


def _after_marker(text: str, pattern: str) -> str:
    m = re.search(pattern, text, re.IGNORECASE | re.UNICODE)
    return m.group(1).strip(" ,.:;-!?") if m else ""


def parse(text: str) -> Intent | None:
    ws = words(text)
    toks = [f for _, f in ws]
    if not toks:
        return None
    s = set(toks)
    s |= {"tools" for t in toks if t.startswith(("werkzeug", "tool", "fahigkeit", "funktion"))}      # auch Zusammensetzungen ("Werkzeugliste")
    claude = any(is_claude(t) for t in toks)
    # --- Werkzeuge anzeigen / wie einschalten
    if s & _ENABLE and (s & _TOOL_WORDS or s & _ENGINES) and ("ein" in s or s & (_ENABLE - {"schalte", "schalt", "ein"})):
        return Intent("enable_how")
    if s & _TOOL_WORDS and (s & _SHOW) and len(toks) <= 12:
        return Intent("list")
    if toks[:3] == ["was", "kannst", "du"] and len(toks) <= 4:
        return Intent("list")
    # --- Recherche
    if s & {"recherchiere", "recherchier", "recherche", "recherchieren"} or ("schau" in s or "schaue" in s or "schauen" in s) and "nach" in s \
            or (s & {"suche", "such", "suchen"} and s & {"internet", "online", "netz", "web"}):
        kept, skip_im = [], False
        for i, (orig, f) in enumerate(ws):
            if f in _RESEARCH_DROP:
                continue
            if f == "im" and i + 1 < len(ws) and ws[i + 1][1] in {"internet", "web", "netz"}:
                continue
            kept.append(orig)
        return Intent("research", " ".join(kept))
    # --- Claude
    if claude:
        if s & _STOP:
            return Intent("stop")
        if "status" in s or (s & {"was", "wie"} and s & (_STATUS - {"status"})):
            return Intent("status")
        if s & _RESULT and not s & _DEV:
            return Intent("result")
        ans = _after_marker(text, r"(?:antwort(?:e)?\s+(?:an|auf)\s+\w+|antworte\s+\w+|sag(?:e)?\s+(?:dem\s+)?\w+)\W+(.+)$")
        if ans and re.search(r"(?:antwort\w*\s+(?:an|auf)\s+|antworte\s+|sag\w*\s+(?:dem\s+)?)(\w+)", text, re.IGNORECASE):
            who = re.search(r"(?:antwort\w*\s+(?:an|auf)\s+|antworte\s+|sag\w*\s+(?:dem\s+)?)(\w+)", text, re.IGNORECASE).group(1)
            if is_claude(fold(who)):
                m = re.match(r"(?:er\s+)?soll\s+(.+)", ans, re.IGNORECASE)
                return Intent("answer", ans, text) if not m else Intent("start", m.group(1).strip(" ,.:;-!?"), text)
        task = _after_marker(text, r"\bclaude\W+soll\s+(.+)$") or _after_marker(text, r"\blass\w*\s+claude\s+(.+?)(?:\s+(?:machen|tun))?\W*$")
        if task:
            return Intent("start", task, text)
        if s & _DEV and s & _USE:
            tail = _after_marker(text, r"(?:weiterzuentwickeln|weiterentwickeln|entwickeln|programmieren)\W+und\s+(.{12,})$")
            return Intent("start", tail, text)
    if s & _ALLOW and s & {"das", "pytest", "test", "tests", "ihm", "claude"}:
        return Intent("allow")
    return None


# --- Antworttexte ---------------------------------------------------------------------------------

def _speakable(text: str) -> str:
    """Zum Vorlesen: Quellenliste und Links raus (stehen in der UI), Markdown-Zeichen weg, höchstens ~600 Zeichen."""
    text = re.split(r"Quellen?:", text, maxsplit=1)[0]
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"", text)
    text = re.sub(r"https?://\S+|[*_`#>]", "", text)
    text = " ".join(text.split())
    return text if len(text) <= 600 else text[:600].rsplit(" ", 1)[0] + " ..."


def _short_reason(why: str) -> str:
    return why.split(" (")[0].strip()


def describe(reg: ToolRegistry) -> str:
    """Ehrliche Liste: jedes Werkzeug mit Zustand und Grund. Quelle ist der echte Stand, nie das Sprachmodell."""
    parts, active = [], []
    for t in reg.tools.values():
        why = t.available()
        if reg.is_active(t.name):
            active.append(t.title)
            state = "an" + (", sendet Daten nach außen" if t.sends_data_out else "")
        elif reg.is_enabled(t.name):
            state = f"eingeschaltet, aber nicht verfügbar: {_short_reason(why)}"
        else:
            state = "aus" + (f", weil {_short_reason(why)}" if why else "")
        parts.append(f"{t.title}: {state}.")
    head = f"Ich habe {len(parts)} Werkzeuge. "
    tail = ("Eingeschaltet ist: " + ", ".join(active) + ". ") if active else "Eingeschaltet ist im Moment keines. "
    return head + " ".join(parts) + " " + tail + ENABLE_HOW


ENABLE_HOW = ("Einschalten kannst du sie nur in den Einstellungen oder mit kushim tools enable, nie per Sprache, "
              "damit nichts ohne dein bewusstes Zutun Daten verschickt.")


@dataclass
class _Pending:
    kind: str                    # "research" | "start" | "answer"
    proposal: Any
    control: bool = False


class ToolCommands:
    def __init__(self, cfg: Any, registry: ToolRegistry, research: Any, control: Any, sessions: Any,
                 summarize: Callable[[Any], str], folders: Callable[[], list[Folder]]):
        """`cfg`: LiveConfig (frischer Stand der Werkzeug-Schalter). `research`/`control`/`sessions`: die geprüften Bausteine.
        `summarize`: fasst Wikipedia-Treffer mit dem werkzeuglosen lokalen Modell zusammen (kommt von cli.py; dieses Modul fasst das Web-Paket nicht an)."""
        self.cfg, self.registry, self.research, self.control, self.sessions = cfg, registry, research, control, sessions
        self.summarize, self.folders = summarize, folders
        self.before: Callable[[], None] = lambda: None      # vor jedem Satz: frischen Stand übernehmen (z. B. Modus C im EgressGate)
        self._pending: _Pending | None = None
        self._announcements: "queue.SimpleQueue[str]" = queue.SimpleQueue()
        self.sessions.on_finish = self._on_turn_finished

    @property
    def awaiting(self) -> bool:
        return self._pending is not None

    # --- Meldungen von sich aus (Claude ist fertig oder fragt)
    def _on_turn_finished(self, st: Any) -> None:
        if st.status == "waiting":
            got = self.sessions.result()
            if got is None:
                return
            _, _rv, ov = got
            text = report.spoken(ov)
            if ov.question:
                text += " Antworte mit: Antwort an Claude, und dann deine Antwort."
            elif ov.permission_questions:
                text += " Sag: erlaube das, wenn Claude es ausführen darf."
            else:
                text += " Sag: Was hat Claude gemacht, für die ganze Übersicht."
            self._announcements.put(text)
        elif st.status == "failed":
            self._announcements.put(f"Claude ist gescheitert: {st.error or 'unbekannter Grund'}")

    def announcement(self) -> str | None:
        """Nächste Meldung von sich aus, einmalig (die Schleife spricht sie, wenn gerade nichts anderes läuft)."""
        try:
            return self._announcements.get_nowait()
        except queue.Empty:
            return None

    # --- Befehle
    def handle(self, text: str, verified: bool, strong: bool = True) -> str | None:
        self.registry.sync(self.cfg.tools_enabled)                      # frischer Stand der Schalter
        self.before()
        if self._pending is not None:
            return self._confirm(text, verified)
        intent = parse(text)
        if intent is None:
            return None
        k = intent.kind
        if k == "list":
            return describe(self.registry)
        if k == "enable_how":
            return ENABLE_HOW + " Frag mich: Welche Werkzeuge hast du? Dann sage ich dir den Stand."
        if not verified:
            return "Das mache ich nur auf deine Stimme."
        if k == "research":
            return self._research(intent)
        if k == "stop":
            return "Okay, Claude wird gestoppt. Der Branch bleibt erhalten." if self.sessions.stop() else "Es läuft kein Claude-Lauf."
        if k == "status":
            return self._status()
        if k == "result":
            return self._result()
        if not strong:
            return ("Für Claude brauche ich eine etwas längere, deutliche Äußerung. Sag den Befehl bitte noch einmal in einem ganzen Satz.")
        if k == "start":
            return self._start(intent)
        if k == "answer":
            return self._answer(intent.text, ())
        if k == "allow":
            st = self.sessions.state()
            if st is None or st.status != "waiting" or not st.offers:
                return "Es gibt nichts, das ich für Claude erlauben könnte."
            return self._answer("Du darfst das jetzt ausführen. Mach weiter.", tuple(st.offers))
        return None

    def _research(self, intent: Intent) -> str:
        if not intent.text.strip():
            return "Wonach soll ich suchen? Sag zum Beispiel: Recherchiere die Höhe des Eiffelturms."
        p = self.research.propose(intent.text, speaker_verified=True)
        if p.approval is None:
            return p.reason or "Das darf ich gerade nicht."
        self._pending = _Pending("research", p)
        if p.route == "claude":
            fallback = " Falls Claude nicht antwortet, frage ich stattdessen Wikipedia." if "Wikipedia" in p.preview else ""
            return (f"Ich frage Claude im Internet nach: {intent.text}. Der Suchtext geht an Anthropic.{fallback} "
                    "Soll ich das tun? Sage ja oder nein.")
        return f"Ich frage Wikipedia nach: {intent.text}. Es geht nur dieser Suchtext raus. Soll ich das tun? Sage ja oder nein."

    def _start(self, intent: Intent) -> str:
        tool = self.registry.tools.get("claude.code")
        if tool is None or not self.registry.is_active("claude.code"):
            why = _short_reason(tool.available()) if tool is not None else "es gibt es nicht"
            return f"Claude zum Entwickeln ist nicht eingeschaltet: {why or 'das Werkzeug ist aus'}. {ENABLE_HOW}"
        known = self.folders()
        folder = resolve(known, intent.folder_hint) or (known[0] if len(known) == 1 else None)      # genau ein freigegebener Ordner: eindeutig
        if folder is None:
            return "Welchen Ordner meinst du? Freigegeben sind: " + ", ".join(f.name for f in known) + "."
        p = self.control.propose_start(intent.text, folder.name, speaker_verified=True)
        if p.approval is None:
            return p.reason or "Das darf ich gerade nicht."
        self._pending = _Pending("start", p, control=True)
        return (f"Claude soll im Ordner {folder.name} arbeiten, in einem eigenen Branch. Auftrag: {p.task}. "
                "Der Auftrag und Ausschnitte aus den Dateien gehen an Anthropic. Soll ich starten? Sage ja oder nein.")

    def _answer(self, text: str, allow: tuple[str, ...]) -> str:
        p = self.control.propose_answer(text, allow, speaker_verified=True)
        if p.approval is None:
            return p.reason or "Das darf ich gerade nicht."
        self._pending = _Pending("answer", p, control=True)
        extra = " Dabei erlaube ich Claude für diese Sitzung: " + ", ".join(allow) + "." if allow else ""
        return f"Ich antworte Claude: {p.task}.{extra} Soll ich das senden? Sage ja oder nein."

    def _status(self) -> str:
        st = self.sessions.state()
        if st is None:
            return "Es läuft kein Claude-Lauf."
        minutes = st.seconds / 60
        if st.status == "running":
            return f"Claude arbeitet im Ordner {st.folder}, Zug {st.turn}."
        if st.status == "waiting":
            return f"Claude wartet auf dich oder ist fertig (Zug {st.turn}, {minutes:.0f} Minuten). Sag: Was hat Claude gemacht?"
        if st.status == "failed":
            return f"Der Claude-Lauf ist gescheitert: {st.error or 'unbekannter Grund'}"
        return "Der Claude-Lauf wurde gestoppt. Der Branch bleibt erhalten."

    def _result(self) -> str:
        got = self.sessions.result()
        if got is None:
            return "Es gibt noch kein Ergebnis."
        st, _rv, ov = got
        text = report.spoken(ov)
        if st.status == "running":
            text = "Claude arbeitet noch. Zwischenstand: " + text
        return text

    # --- Bestätigung ("ja"/"nein")
    def _confirm(self, text: str, verified: bool) -> str:
        pending, self._pending = self._pending, None
        owner = self.control if pending.control else self.research
        w = _words(text)
        if not verified:
            owner.deny(pending.proposal)
            return "Abgebrochen, das mache ich nur auf deine Stimme."
        if w & _NO or not (w & _YES):
            owner.deny(pending.proposal)
            return "Abgebrochen. Es wurde nichts gesendet."
        if not owner.approve(pending.proposal):
            return "Die Bestätigung ist abgelaufen. Sag den Befehl bitte noch einmal."
        try:
            if pending.kind == "research":
                return self._speak_research(self.research.execute(pending.proposal))
            self.control.execute(pending.proposal)
        except SessionError as e:
            return f"Das hat nicht geklappt: {e}"
        except Exception:                                              # noqa: BLE001 (nie Details, nie Pfade sprechen)
            return "Das hat nicht geklappt."
        return "Okay, Claude arbeitet. Ich melde mich, wenn er fertig ist oder etwas fragt."

    def _speak_research(self, out: Any) -> str:
        note = f"{out.note}. " if out.note and out.kind != "none" else ""
        if out.kind == "claude":
            return f"{note}Laut Claude: {_speakable(str(out.answer))}"
        if out.kind == "wikipedia" and out.wiki is not None:
            if not out.wiki.sources:
                return f"{note}Ich habe keine brauchbaren Treffer gefunden."
            return f"{note}Laut Wikipedia: {self.summarize(out.wiki)}"
        return out.note or "Ich konnte nichts herausfinden."
