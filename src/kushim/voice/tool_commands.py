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


def _near(token: str, targets: tuple[str, ...]) -> bool:
    """Spracherkennung verhört sich oft leicht ("Werkzeugliste" -> "Werkzeugeliste"): ähnliche Wörter zählen mit."""
    return len(token) >= 6 and any(difflib.SequenceMatcher(None, token, t).ratio() >= 0.85 for t in targets)


def is_claude(token: str) -> bool:
    return token in {"claude", "claud", "klaud", "klaude", "clode", "clod"} or difflib.SequenceMatcher(None, "claude", token).ratio() >= 0.8


_TOOL_WORDS = {"tools", "tool", "werkzeuge", "werkzeug", "fahigkeiten", "fahigkeit", "funktionen", "hilfsmittel", "hilfsmitteln", "skills"}
_LIST_FILLER = {"alles", "so", "noch", "fur", "mich", "mir", "tun", "helfen", "denn", "eigentlich", "sonst", "uberhaupt"}
_SHOW = {"hast", "hat", "welche", "zeig", "zeige", "zeigen", "nenne", "liste", "anzeigen", "gibt", "gibts", "habe", "verfugbar", "aktiv",
         "sind", "stehen", "kannst", "gib", "geb", "liste", "auflisten", "aufzahlen", "uber", "habt", "verfugst", "nutzt", "benutzt", "zeigst", "nennst",
         "was", "alles", "drauf", "sag", "erzahl", "verfugung"}
_ENABLE = {"einschalten", "aktivieren", "anschalten", "freischalten", "aktiviere", "anmachen", "schalte", "schalt", "ein"}
_ENGINES = {"web", "search", "recherche", "websuche", "claude", "modus"}
_DEV_STRICT = {"weiterzuentwickeln", "weiterentwickeln", "weiterentwickle", "weiterentwickelt", "entwickeln", "entwickle", "programmieren",
               "programmiere", "coden", "bauen", "baue", "verbessern", "verbessere", "erweitern", "erweitere", "implementieren", "implementiere",
               "fortentwickeln", "codieren", "umsetzen", "reparieren", "repariere", "testen", "teste", "entwicklung", "entwickelst"}
_DEV = _DEV_STRICT | {"arbeiten", "arbeite", "arbeit"}                       # "arbeite weiter" ist Fortsetzen, nicht neu starten
_USE = {"nutze", "nutz", "benutze", "starte", "lass", "lasse", "soll", "bitte", "los", "kannst", "nimm", "verwende", "setz", "setze", "mach", "mache", "kann", "sollst", "sollte", "dann", "jetzt",
        "schick", "schicke", "beauftrage", "beginne", "fang", "fange", "aktiviere", "geh", "gehe", "hey"}
_STATUS = {"status", "stand", "weit", "macht", "fertig", "lauft", "laeuft", "arbeitet", "dran", "fortschritt", "treibt", "tut", "passiert", "noch"}
_STOP = {"stopp", "stop", "stoppe", "stoppen", "beende", "beenden", "halt", "anhalten", "aufhoren", "hor", "pause", "pausiere", "schluss", "abschalten"}
_RESULT = {"ergebnis", "gemacht", "getan", "zusammenfassung", "ubersicht", "uebersicht", "bericht", "fakten", "gebaut", "erreicht", "erzahl", "erzahle", "berichte", "neues", "resultat", "geschafft", "erledigt",
           "zusammenfassen", "uberblick", "ueberblick"}
_ALLOW_VERBS = {"erlaube", "erlauben", "erlaubt", "freigeben", "genehmige", "genehmigen", "freigabe", "erlaubnis"}
_CONTINUE_WORDS = {"weiter", "weitermachen", "weiterarbeiten", "fortsetzen", "fortfahren", "fort", "weiterfuhren", "weiterbauen", "dranbleiben",
                   "weitergehen", "wiederaufnehmen", "fortsetze", "weitermache", "weiterarbeite"}
_RESEARCH_DROP = {"recherchiere", "recherchier", "recherche", "recherchieren", "schau", "schaue", "schauen", "nach", "suche", "such", "suchen",
                  "internet", "online", "netz", "kushim", "hey", "bitte", "mal", "doch", "mir", "mich", "claude", "frag", "frage", "fragen", "finde", "finden",
                  "heraus", "google", "googel", "googele", "nachschlagen", "schlag", "sieh", "sehe", "nachsehen", "nachschauen", "guck", "gucke",
                  "gucken", "nachgucken", "check", "checke", "prufe", "prufen", "informiere", "dich", "kannst", "du", "konntest", "web", "uber",
                  "dann", "jetzt", "einmal"}


_BRANCH_WORDS = {"branch", "branches", "zweig", "zweige", "worktree", "worktrees", "branchs"}
_CONTINUE = {"weiter", "weitermachen", "weiterarbeiten", "fortsetzen", "fortfahren", "arbeite", "mach", "mache", "nutze"}
_NUMBERS = {"eins": 1, "ein": 1, "erste": 1, "ersten": 1, "neueste": 1, "neuesten": 1, "letzte": 1, "letzten": 1, "zwei": 2, "zweite": 2, "zweiten": 2,
            "drei": 3, "dritte": 3, "dritten": 3, "vier": 4, "vierte": 4, "vierten": 4, "funf": 5, "funfte": 5, "funften": 5}
CONTINUE_TASK = ("Mach dort weiter, wo du aufgehört hast: sieh dir den Stand im Branch an (git status, git log), schließe die offene Arbeit ab, "
                 "teste, committe lokal und pushe nicht.")
_MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]


def _when(name: str) -> str:
    """"kushim-20261004-051157" -> "vom 4. Oktober um 5 Uhr 11" (Name des Worktrees trägt den Startzeitpunkt)."""
    m = re.search(r"(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})", name)
    if not m or not 1 <= int(m.group(2)) <= 12:
        return name
    return f"vom {int(m.group(3))}. {_MONTHS[int(m.group(2)) - 1]} um {int(m.group(4))} Uhr {int(m.group(5))}"


def _number(tokens: list[str]) -> int | None:
    for t in tokens:
        if t.isdigit() and 1 <= int(t) <= 9:
            return int(t)
        if t in _NUMBERS:
            return _NUMBERS[t]
    return None


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
    s |= {"tools" for t in toks if t.startswith(("werkzeug", "tool", "fahigkeit", "funktion", "hilfsmittel")) or _near(t, ("werkzeuge", "werkzeugliste", "toolliste"))}      # auch Zusammensetzungen ("Werkzeugliste")
    claude = any(is_claude(t) for t in toks)
    has_continue = bool(s & _CONTINUE_WORDS) or any(t.startswith("weiter") and not t.startswith(("weiterentw", "weiterzu")) for t in toks)
    # --- Werkzeuge anzeigen / wie einschalten
    if s & _ENABLE and (s & _TOOL_WORDS or s & _ENGINES) and ("ein" in s or s & (_ENABLE - {"schalte", "schalt", "ein"})):
        return Intent("enable_how")
    if s & _TOOL_WORDS and ((s & _SHOW) and len(toks) <= 12 or len(toks) <= 3):          # auch kurz: "Werkzeugliste", "Deine Tools"
        return Intent("list")
    if toks[:3] == ["was", "kannst", "du"] and len(toks) <= 6 and set(toks[3:]) <= _LIST_FILLER:
        return Intent("list")
    if (toks[:3] in (["was", "hast", "du"], ["womit", "kannst", "du"], ["wobei", "kannst", "du"]) or toks[:2] == ["was", "kann"]) and len(toks) <= 7 \
            and set(toks[3:]) <= _LIST_FILLER | {"drauf", "helfen", "mir", "mich"}:
        return Intent("list")
    # --- vorhandene Claude-Branches anzeigen / dort weitermachen
    if s & _BRANCH_WORDS or (s & {"nummer", "nr"} and s & _CONTINUE and (claude or has_continue)):
        if has_continue or (s & {"nummer", "nr"} and s & _CONTINUE):
            tail = _after_marker(text, r"\bund\s+(.{8,})$")
            return Intent("resume", tail, text)
        if s & {"welche", "gibt", "zeig", "zeige", "liste", "offen", "vorhanden", "habe", "hast", "hat", "gibts", "nenne", "zeigen"}:
            return Intent("branches")
    # --- Recherche ("recherchiere", "schau nach", "frag Claude", "finde heraus", "google", "such im Internet")
    nach = bool(s & {"nach", "heraus", "nachschauen", "nachsehen", "nachgucken", "nachschlagen"})
    if (s & {"recherchiere", "recherchier", "recherche", "recherchieren", "recherchiert", "google", "googel", "googele", "nachschlagen"}
            or (s & {"schau", "schaue", "schauen", "guck", "gucke", "gucken", "sieh", "sehe", "nachschauen", "nachsehen", "nachgucken", "check",
                     "checke", "prufe", "prufen", "such", "suche", "suchen", "schlag", "informiere"} and (nach or "dich" in s))
            or (s & {"suche", "such", "suchen"} and s & {"internet", "online", "netz", "web"})
            or (s & {"finde", "finden"} and "heraus" in s)
            or (s & {"frag", "frage", "fragen"} and claude and len(toks) >= 4 and not s & _DEV)):
        kept = []
        for i, (orig, f) in enumerate(ws):
            if f in _RESEARCH_DROP or is_claude(f):
                continue
            if f == "im" and i + 1 < len(ws) and ws[i + 1][1] in {"internet", "web", "netz"}:
                continue
            kept.append(orig)
        return Intent("research", " ".join(kept))
    # --- "Mach dort weiter" / "Mach damit weiter" (ohne Namen): gilt nur, wenn eine Claude-Sitzung da ist (prüft der Aufrufer)
    if not claude and has_continue and len(toks) <= 5 and toks[0] in {"mach", "mache", "arbeite", "fahr", "fahre", "geh", "gehe", "setz", "setze", "los"} \
            and not s & _DEV_STRICT:
        return Intent("continue_soft", "", text)
    # --- Claude
    if claude:
        if s & _STOP:
            return Intent("stop")
        if "status" in s or (len(toks) <= 8 and s & _STATUS and not has_continue and not s & _RESULT):
            return Intent("status")
        if s & _RESULT and not s & _DEV_STRICT:
            return Intent("result")
        if has_continue and not s & _DEV_STRICT:                                                   # "Mach weiter mit Claude"
            return Intent("continue", _after_marker(text, r"\bund\s+(.{8,})$"), text)
        verb = r"(?:antwort\w*|sag\w*|schreib\w*|schick\w*|sende\w*|teil\w*(?:\s+mit)?|richte\w*\s+(?:\w+\s+)?aus|gib)"
        m = re.search(verb + r"\s+(?:an\s+|auf\s+|dem\s+|ihm\s+)?(\w+)\W+(.+)$", text, re.IGNORECASE | re.UNICODE)
        if m and is_claude(fold(m.group(1))):
            ans = re.sub(r"^mit\s+", "", m.group(2).strip(" ,.:;-!?"), flags=re.IGNORECASE)
            mm = re.match(r"(?:er\s+)?soll\s+(.+)", ans, re.IGNORECASE)
            return Intent("start", mm.group(1).strip(" ,.:;-!?"), text) if mm else Intent("answer", ans, text)
        task = (_after_marker(text, r"\bclaude\W+(?:soll|sollst|muss|möge)\s+(.+)$")
                or _after_marker(text, r"\b(?:lass\w*|bitte|beauftrage|beauftrag)\s+claude\s+(.+?)(?:\s+(?:machen|tun))?\W*$"))
        if task:
            return Intent("start", task, text)
        if s & _DEV and s & _USE:
            tail = _after_marker(text, r"(?:weiterzuentwickeln|weiterentwickeln|entwickeln|programmieren)\W+und\s+(.{12,})$")
            return Intent("start", tail, text)
        if s & _DEV_STRICT and len(toks) <= 12:                                                    # "Claude, entwickle das Projekt weiter"
            return Intent("start", "", text)
        first = toks[0]
        if is_claude(first) and len(toks) >= 3 and first not in {"was", "wie"}:                    # "Claude, schreib die Tests für den Timer"
            return Intent("start", " ".join(o for o, _ in ws[1:]), text)
    if (s & _ALLOW_VERBS and (claude or s & {"das", "pytest", "test", "tests", "ihm", "es", "befehl", "befehle"})) \
            or ("gib" in s and s & {"frei", "erlaubnis"}) or ("darf" in s and claude):
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
        self.say: Callable[[str], None] | None = None       # sofortige Ansage vor langen Aktionen (Pipeline.say_text)
        self.before: Callable[[], None] = lambda: None      # vor jedem Satz: frischen Stand übernehmen (z. B. Modus C im EgressGate)
        self._pending: _Pending | None = None
        self._branch_list: list = []
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
        if k == "branches":
            return self._branches()
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
        if k == "resume":
            return self._resume(intent)
        if k == "continue":
            return self._continue(intent)
        if k == "continue_soft":                                      # "Mach dort weiter" ohne "Claude": nur, wenn es eine Claude-Sitzung gibt
            st = self.sessions.state()
            if st is None or not st.worktree_path or not getattr(self.sessions, "worktree_ok", lambda s: True)(st):
                return None
            return self._continue(intent)
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
        if self._direct():
            return self._run_direct(f"Ich frage Claude im Internet nach: {intent.text}. " if p.route == "claude" else f"Ich frage Wikipedia nach: {intent.text}. ")
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
        if self._direct():
            return self._run_direct(f"Claude arbeitet im Ordner {folder.name}, in einem eigenen Branch. Auftrag: {p.task}. ")
        return (f"Claude soll im Ordner {folder.name} arbeiten, in einem eigenen Branch. Auftrag: {p.task}. "
                "Der Auftrag und Ausschnitte aus den Dateien gehen an Anthropic. Soll ich starten? Sage ja oder nein.")

    def _answer(self, text: str, allow: tuple[str, ...]) -> str:
        p = self.control.propose_answer(text, allow, speaker_verified=True)
        if p.approval is None:
            return p.reason or "Das darf ich gerade nicht."
        self._pending = _Pending("answer", p, control=True)
        if self._direct():
            extra = (" Dabei erlaube ich Claude: " + ", ".join(allow) + ".") if allow else ""
            return self._run_direct(f"Ich antworte Claude: {p.task}.{extra} ")
        extra = " Dabei erlaube ich Claude für diese Sitzung: " + ", ".join(allow) + "." if allow else ""
        return f"Ich antworte Claude: {p.task}.{extra} Soll ich das senden? Sage ja oder nein."

    def _branches(self) -> str:
        """Vorhandene Claude-Branches aller freigegebenen Ordner, nummeriert (neueste zuerst); nur lesend."""
        self._branch_list = []
        for f in self.folders():
            self._branch_list += [(f, w, dirty, ahead) for w, dirty, ahead in self.sessions.branches(f)]
        if not self._branch_list:
            return "Es gibt keine Claude-Branches in den freigegebenen Ordnern."
        parts = []
        for i, (f, w, dirty, ahead) in enumerate(self._branch_list[:5], 1):
            parts.append(f"Nummer {i}: Ordner {f.name}, {_when(w.path.name)}, {dirty} ungesicherte Dateien, {ahead} Commits.")
        return (f"Es gibt {len(self._branch_list)} Claude-Branches. " + " ".join(parts)
                + " Sag zum Beispiel: Mach bei Nummer eins weiter.")

    def _continue(self, intent: Intent) -> str:
        """"Mach weiter mit Claude": die aktuelle Sitzung fortsetzen; ohne Sitzung (oder nach Stopp/Fehler) den letzten Branch bzw. die Auswahl."""
        st = self.sessions.state()
        if st is not None and st.status == "running":
            return "Claude arbeitet gerade noch. Ich melde mich, wenn er fertig ist."
        tool = self.registry.tools.get("claude.code")
        if tool is None or not self.registry.is_active("claude.code"):
            why = _short_reason(tool.available()) if tool is not None else "es gibt es nicht"
            return f"Claude zum Entwickeln ist nicht eingeschaltet: {why or 'das Werkzeug ist aus'}. {ENABLE_HOW}"
        if st is not None and not getattr(self.sessions, "worktree_ok", lambda s: True)(st):
            st = None                                                  # Worktree wurde entfernt: wie "keine Sitzung" behandeln
        if st is not None and st.status == "waiting" and st.worktree_path:
            return self._answer(intent.text or CONTINUE_TASK, ())
        if st is not None and st.worktree and st.status in ("stopped", "failed"):                 # gleichen Branch wieder aufnehmen
            folder = next((f for f in self.folders() if f.name == st.folder), None)
            if folder is not None:
                try:
                    self.sessions.adopt(folder, st.worktree)
                except SessionError:
                    pass
                else:
                    return self._answer(intent.text or CONTINUE_TASK, ())
        if not self._branches_exist():
            return self._start(Intent("start", intent.text, intent.folder_hint))      # nichts zum Fortsetzen: neuen Lauf starten
        return self._resume(intent)

    def _branches_exist(self) -> bool:
        self._branches()
        return bool(self._branch_list)

    def _resume(self, intent: Intent) -> str:
        tool = self.registry.tools.get("claude.code")
        if tool is None or not self.registry.is_active("claude.code"):
            why = _short_reason(tool.available()) if tool is not None else "es gibt es nicht"
            return f"Claude zum Entwickeln ist nicht eingeschaltet: {why or 'das Werkzeug ist aus'}. {ENABLE_HOW}"
        if not self._branch_list:
            self._branches()
        if not self._branch_list:
            return "Es gibt keine Claude-Branches in den freigegebenen Ordnern."
        n = _number([f for _, f in words(intent.folder_hint)])
        if n is None and len(self._branch_list) > 1:
            return "Welchen Branch meinst du? Frag: Welche Claude-Branches gibt es? Dann sag die Nummer."
        n = n or 1
        if n > len(self._branch_list):
            return f"So viele Branches gibt es nicht, es sind {len(self._branch_list)}."
        folder, wt, _dirty, _ahead = self._branch_list[n - 1]
        try:
            self.sessions.adopt(folder, wt.path.name)
        except SessionError as e:
            return f"Das geht nicht: {e}"
        return self._answer(intent.text or CONTINUE_TASK, ())

    def _direct(self) -> bool:
        """Direkt handeln: der gesprochene Befehl der verifizierten Stimme ist die Freigabe (Einstellung [tools] direct, Standard an).
        Alles andere bleibt: Prüfer, Hash-Bindung, Gate, Notaus, "abbrechen". Auch Antworten an Claude und Erlaubnisse laufen so (erlaubt werden nur von Claude angebotene, harmlose Befehle)."""
        return bool(getattr(self.cfg, "voice_direct", False))

    def _run_direct(self, intro: str) -> str:
        """Erst sofort ansagen ("... Ich starte."), dann ausführen; die Ausführung kann bis zu zwei Minuten dauern."""
        intro += "Ich starte."
        if self.say is None:
            return intro + " " + self._confirm("ja", True)
        try:
            self.say(intro)
        except Exception:                                              # noqa: BLE001 (Ansage ist nur Komfort, nie Grund abzubrechen)
            pass
        return self._confirm("ja", True)

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
