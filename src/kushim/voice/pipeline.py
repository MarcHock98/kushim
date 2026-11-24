"""Sprachpipeline: Äußerung -> STT -> Notaus-Prüfung -> Claude -> Sprachausgabe.

Reihenfolge ist sicherheitsrelevant:
  1. Notaus-Wortlaut wird VOR allem anderen geprüft (ohne Claude).
  2. Es gibt keine Sprecher-Prüfung: jede Stimme kann Befehle geben, Freigaben per Stimme sind deshalb gesperrt.
  3. Die Antwort ist nur Text. Aktionen gibt es in kushim nicht; Freigaben macht Claude Code (Roadmap v2 Phase C).
Alle Komponenten werden injiziert (testbar ohne Audio/Modelle).
"""
from __future__ import annotations

import difflib
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from ..safety.killswitch import KillSwitch, is_kill_phrase
from ..tasks import TaskRegistry, is_cancel_phrase
from .dialog import Dialog, State
from .earcon import plain
from .stt import SpeechToText
from .tts import Speaker, chunk_stream, prefetch, sentences_of, split_sentences

SYSTEM_PROMPT = (
    "Du bist kushim, ein persönlicher, lokaler Assistent. Antworte auf Deutsch, kurz und sachlich, "
    "in höchstens drei Sätzen. Antworte nur auf die Frage; erwähne Werkzeuge nur, wenn der Nutzer ausdrücklich danach fragt. "
    "Du selbst führst nichts aus; Werkzeuge verwaltet kushim außerhalb von dir. Behaupte nie, kushim habe keine Werkzeuge oder könne etwas "
    "nicht; sag bei Fragen dazu nur: Frag mich: Welche Werkzeuge hast du? Erfinde keine Fakten und behaupte nie, etwas nachgeschlagen zu haben; "
    "sag, wenn du etwas nicht weißt. "
    "Äußert der Nutzer Sorgen, Einsamkeit oder Not, geh zuerst darauf ein, nimm es ernst und ermutige ihn zu Gesprächen mit Freunden, Familie oder Fachleuten; "
    "ersetze nie Beziehungen zu anderen Menschen und stimm riskanten Plänen nicht einfach zu.")

ChatStream = Callable[[list[dict[str, str]]], Iterable[str]]

_TOKEN = re.compile(r"[\wäöüßÄÖÜ]+")
END_PHRASES = {"das wars", "das war es", "das war es dann", "das reicht", "das reicht danke", "danke das wars",
               "danke das reicht", "tschüss", "tschüs", "bis später", "bis dann", "bis gleich", "ende", "gespräch beenden"}
END_REPLY = "Bis gleich."
SHUTDOWN_REPLY = "Okay, ich beende mich."
_SHUTDOWN_WORDS = {"beende", "beenden", "exit", "quit", "herunter", "runter", "ausschalten", "abschalten", "herunterfahren", "runterfahren"}
_SHUTDOWN_SELF = {"dich", "kushim", "programm", "alles", "exit", "quit", "herunter", "runter", "herunterfahren", "runterfahren", "ausschalten",
                  "abschalten", "komplett", "ganz"}


def is_shutdown_phrase(text: str) -> bool:
    """"Beende dich", "exit", "kushim beenden", "fahr herunter", "schalte dich aus": kushim samt Diensten beenden. Kurze Sätze; nie wenn es um
    Claude geht ("Beende Claude" stoppt nur Claude) und nicht das bloße "Gespräch beenden" (das beendet nur das Gespräch)."""
    toks = [t.lower() for t in _TOKEN.findall(re.sub(r"['’`]", "", text))]
    if not toks or len(toks) > 6 or any(t.startswith(("claud", "klaud")) for t in toks):
        return False
    if "gespräch" in toks or "gespraech" in toks:
        return False
    if "aus" in toks and "schalte" in toks or "schalt" in toks and "aus" in toks:
        return bool(set(toks) & {"dich", "kushim"})
    return bool(set(toks) & _SHUTDOWN_WORDS) and bool(set(toks) & _SHUTDOWN_SELF)

# --- Mikrofon-Schwellen per Stimme (ohne Claude, wird nie gespeichert; voice/tuning.py) ---------------------------------
_TUNING_TOPIC = ("mikro", "pegel", "empfindlich", "unempfindlich")       # Wortanfänge: Mikrofon, Pegel, Empfindlichkeit, ...
_TUNING_NOUN = ("mikro", "pegel", "empfindlichkeit")                    # ohne eines davon nur die kurzen Formen unten
_TUNING_MORE = {"empfindlicher", "sensibler"}
_TUNING_LESS = {"unempfindlicher", "unempfindlich", "unsensibler"}
_TUNING_SENS = ("empfindlich", "sensib", "unempfindlich", "unsensib")
_TUNING_RESET = {"normal", "zurück", "zurücksetzen", "zurückstellen", "standard", "reset"}
_TUNING_VOLUME = {"laut", "lauter", "leise", "leiser", "lautstärke"}    # Lautstärke der Stimme ist etwas anderes
# Feststellungen und Fragen ("Das Mikrofon ist normal", "Ist das Mikrofon empfindlicher") sind kein Befehl. Einzige Ausnahme:
# "(Das Mikrofon ist) zu empfindlich" ist ein klarer Wunsch.
_TUNING_STATE = {"ist", "war", "sind", "waren", "wird", "werden", "wurde", "wurden", "geworden", "funktioniert",
                 "funktionieren", "bin", "bist", "seid"}
_TUNING_COPULA = {"ist", "sind"}
_TUNING_FILLER = {"bitte", "etwas", "noch", "ein", "bisschen", "wenig", "mach", "stell", "weniger", "nicht", "so", "mehr", "zu"}
_STEP_WORDS = {-2: "minus zwei", -1: "minus eins", 0: "null", 1: "plus eins", 2: "plus zwei"}


def is_tuning_phrase(text: str) -> int | None:
    """"Mikrofon empfindlicher" (+1), "Mikrofon weniger empfindlich" (-1), "Mikrofon normal" (0), sonst None. Wie
    `is_shutdown_phrase`: höchstens 6 Wörter, nie wenn es um Claude geht. Nötig ist "Mikrofon", "Pegel" oder "empfindlich"
    zusammen mit genau EINER Richtung; "lauter"/"leiser" zählen nicht (das wäre die Lautstärke der Stimme).
    Keine Fragen und keine Feststellungen ("Das Mikrofon ist normal", "Ist das Mikrofon jetzt empfindlicher", "Mikrofon ist
    empfindlicher geworden"); nur "(Das Mikrofon ist) zu empfindlich" (-1) bzw. "zu unempfindlich" (+1) gilt als Wunsch.
    Ohne "Mikrofon"/"Pegel"/"Empfindlichkeit" nur kurze Zurufe ("empfindlicher bitte"), damit ein Satz im Gespräch
    ("du bist empfindlicher als ich") nicht auslöst. Im Zweifel None."""
    if text.strip().endswith("?"):
        return None
    toks = [t.lower() for t in _TOKEN.findall(re.sub(r"['’`]", "", text))]
    if not toks or len(toks) > 6 or any(t.startswith(("claud", "klaud")) for t in toks):
        return None
    if set(toks) & _TUNING_VOLUME or not any(t.startswith(_TUNING_TOPIC) for t in toks):
        return None
    if toks[0] in _TUNING_STATE:                                # Frage-Inversion: "Ist das Mikrofon ...", "Wird der Pegel ..."
        return None

    def before(i: int, *words: str) -> bool:
        return i >= len(words) and toks[i - len(words):i] == list(words)

    less_at: set[int] = set()
    more_at: set[int] = set()
    zu = nicht_ok = False
    for i, t in enumerate(toks):
        if not t.startswith(_TUNING_SENS):
            continue
        un = t.startswith("un")
        nicht_so = before(i, "nicht", "so") or before(i, "nicht", "mehr", "so")
        if before(i, "zu"):                                     # "zu empfindlich" -> weniger, "zu unempfindlich" -> mehr
            (more_at if un else less_at).add(i)
            zu = True
        elif nicht_so or before(i, "weniger") or (i + 1 < len(toks) and toks[i + 1] == "weniger"):
            if un:                                              # "weniger unempfindlich": unklar
                return None
            less_at.add(i)
            nicht_ok = nicht_ok or nicht_so
        elif t in _TUNING_LESS:
            less_at.add(i)
        elif t in _TUNING_MORE:
            more_at.add(i)
    if "nicht" in toks and not nicht_ok:                        # "Mikrofon nicht zurücksetzen", "nicht empfindlicher": unklar
        return None
    state = set(toks) & _TUNING_STATE
    if state and (not zu or state - _TUNING_COPULA):            # Feststellung: nur "ist/sind zu empfindlich" zählt
        return None
    reset = bool(set(toks) & _TUNING_RESET)
    found = [d for d, on in ((1, bool(more_at)), (-1, bool(less_at)), (0, reset)) if on]
    if len(found) != 1:
        return None
    if any(t.startswith(_TUNING_NOUN) for t in toks):
        return found[0]
    if found[0] == 0:                                           # "zurücksetzen" allein ist kein Mikrofon-Befehl
        return None
    allowed = _TUNING_FILLER | _TUNING_MORE | _TUNING_LESS
    return found[0] if all(t in allowed or t.startswith(_TUNING_SENS) for t in toks) else None


def tuning_reply(direction: int, step: int, moved: bool) -> str:
    """Feste Ansage nach einem Sprachbefehl zu den Mikrofon-Schwellen (kein Text von Claude, keine Werte)."""
    if direction == 0:
        return "Mikrofon normal, Stufe null."
    words = _STEP_WORDS.get(step, str(step))
    if not moved:
        edge = "am empfindlichsten" if direction > 0 else "am unempfindlichsten"
        return f"Mikrofon ist schon {edge}, Stufe {words}. „Mikrofon normal“ setzt zurück."
    what = "empfindlicher" if direction > 0 else "weniger empfindlich"
    return f"Mikrofon {what}, Stufe {words}. „Mikrofon normal“ setzt zurück."


CANCEL_REPLY = "Okay, abgebrochen."
NOTHING_REPLY = "Es läuft nichts, das ich abbrechen könnte."
MATCH = 0.8      # Ähnlichkeit, ab der ein erkanntes Wort als Wake Word zählt ("Kuschim" statt "kushim")
# Kurze Wörter, die Whisper anders schreibt; bei drei Buchstaben reicht die Ähnlichkeit nicht ("Hej" statt "hey", Live-Test 2026-11-11)
_SPELLINGS = {"hej": "hey", "hei": "hey", "hay": "hey", "he": "hey", "hai": "hi", "hy": "hi", "halo": "hallo"}


def _same_word(heard: str, wake: str) -> bool:
    heard = _SPELLINGS.get(heard, heard)
    return heard == wake or difflib.SequenceMatcher(None, heard, wake).ratio() >= MATCH


def strip_wake_words(text: str, names: Sequence[str]) -> str:
    """Entfernt Wake Words am Anfang des erkannten Textes ("Hey Kushim, schau mir das nach" -> "schau mir das nach").

    Whisper schreibt das Wake Word oft leicht anders ("Kuschim"), deshalb zählt Ähnlichkeit statt Gleichheit.
    Nur am Anfang, höchstens zweimal. Bleibt nichts übrig, ist es nur das Wake Word gewesen."""
    if not names:
        return text.strip()
    phrases = sorted({tuple(n.lower().split()) for n in names if n.strip()}, key=len, reverse=True)
    for _ in range(2):
        toks = list(_TOKEN.finditer(text))
        cut = None
        for ph in phrases:
            if len(toks) >= len(ph) and all(_same_word(toks[i].group().lower(), w) for i, w in enumerate(ph)):
                cut = toks[len(ph) - 1].end()
                break
        if cut is None:
            break
        text = text[cut:].lstrip(" \t,.;:!?-–—")
    return text.strip()


@dataclass
class Result:
    heard: str
    reply: str
    outcome: str      # "spoken" | "killed" | "empty" | "wake_only" | "halted" | "interrupted" | "end_conversation" | "cancelled"
    #                   | "announced" | "announce_interrupted" (Meldung von sich aus, ohne Nutzereingabe)
    detail: str = ""  # nur Anzeige, z. B. Score und Dauer bei abgelehntem Sprecher (kein Audio)
    entry: int | None = None    # id des Transkript-Eintrags dieser Runde (`notes.heard`), sonst None
    spoken: int | None = None   # wirklich gesprochene Sätze (nur bei Meldungen gesetzt, für talk.log)
    parts: tuple[str, ...] | None = None    # Meldung: Sätze mit ihren eigenen Kennzeichen (zum Nachreichen), sonst None


class Pipeline:
    def __init__(self, stt: SpeechToText, chat: ChatStream, speaker: Speaker, dialog: Dialog,
                 kill: KillSwitch,
                 history_limit: int = 6,
                 commands: Any = None, wake_names: Sequence[str] = (), tasks: TaskRegistry | None = None,
                 notes: Any = None, tuning: Any = None):
        # `tuning`: Mikrofon-Schwellen zur Laufzeit (`LiveTuning`), optional. Dann wirkt der Sprachbefehl „Mikrofon
        # empfindlicher/weniger empfindlich/normal“ lokal (nie an Claude, nie gespeichert).
        self.tuning = tuning
        # `notes`: Live-Transkript (`Transcript`), optional. Die Zeile „Du“ entsteht direkt nach der Spracherkennung
        # (`heard`), danach `sent` oder `drop` mit Grund. Nur Anzeige im Arbeitsspeicher; Fehler darin stören `handle` nie.
        self.notes = notes
        self.wake_names = tuple(wake_names)       # werden am Anfang des erkannten Textes entfernt
        self.tasks = tasks if tasks is not None else TaskRegistry()      # laufende Aufgaben, die "abbrechen" beenden kann
        self._interrupted = threading.Event()     # gesetzt, wenn der Nutzer dazwischenspricht
        previous_stop = speaker.should_stop
        # Notaus über `kill.poll()`, nicht nur `kill.fired`: Verknüpfung und Oberfläche schreiben nur die Marker-Datei, die Ausgabe
        # stoppt damit vor dem nächsten Satz statt erst am Ende (poll löst die Notaus-Aktionen höchstens einmal aus).
        speaker.should_stop = lambda: previous_stop() or self._interrupted.is_set() or bool(kill.poll())
        # "Ich spreche" nur, solange wirklich Ton läuft; während auf Claude gewartet wird, bleibt es "Ich denke"
        # (Live-Test 2026-11-23: Anzeige "spricht" ohne Ton, weil SPEAKING schon vor dem Warten gesetzt wurde).
        speaker.on_play_start = self._play_start
        speaker.on_play_end = dialog.played
        speaker.on_played = self._played
        # Nur Zahlen für talk.log (C5), je Runde neu: stt_s, first_text_s, first_audio_s (Sekunden ab Rundenbeginn), spoken
        # (wirklich gesprochene Sätze). Nie Text, nie Audio.
        self.metrics: dict[str, float | int | None] = {}
        self._t0 = time.monotonic()
        self.stt, self.chat, self.speaker, self.dialog, self.kill = stt, chat, speaker, dialog, kill
        self.commands = commands          # Sprachbefehle ohne LLM (`handle(text, verified, strong)`), optional
        self.history: list[dict[str, str]] = []
        self.history_limit = history_limit

    def _since(self) -> float:
        return time.monotonic() - self._t0

    def _reset_metrics(self) -> None:
        self._t0 = time.monotonic()
        self.metrics = {"stt_s": None, "first_text_s": None, "first_audio_s": None, "spoken": 0}

    def _play_start(self) -> Any:
        if self.metrics.get("first_audio_s") is None:
            self.metrics["first_audio_s"] = self._since()
        return self.dialog.playing()

    def _played(self) -> None:
        self.metrics["spoken"] = int(self.metrics.get("spoken") or 0) + 1

    def interrupt(self) -> None:
        """Der Nutzer spricht dazwischen (aus einem anderen Thread): Ausgabe stoppt sofort, nichts wird weitergesprochen."""
        self._interrupted.set()
        self.dialog.triggered()                   # stoppt laufende Wiedergabe (Barge-in), setzt auf Zuhören

    def try_cancel(self, pcm: Any) -> bool:
        """Für die Schleife, WÄHREND eine Antwort läuft: war die Äußerung "abbrechen"? Dann alles Laufende beenden (aus einem
        anderen Thread). Nein: nichts tun (die Äußerung wird danach normal behandelt)."""
        text = self.stt.transcribe(pcm).text
        if not text:
            return False
        if is_kill_phrase(text):                  # "Notaus" als Zwischenruf: zuerst, wie im normalen Notaus-Pfad
            self.kill.on_transcript(text)
            self._interrupted.set()
            self.dialog.halt()
            self.tasks.cancel_all()
            self._note("heard", "", "", "killed")             # Zeile „Du“ ohne Text, nur „Notaus erkannt“
            return True
        if not is_cancel_phrase(text):
            return False
        self.tasks.cancel_all()
        self._interrupted.set()                   # stoppt auch Denken/Sprechen
        self.dialog.triggered()
        self._note("heard", text, strip_wake_words(text, self.wake_names) or text, "cancelled")   # eigene Zeile „Du“
        return True

    # --- Live-Transkript (nur Anzeige): jeder Aufruf gekapselt, ein Fehler darf die Runde nie stören
    def _note(self, method: str, *args: Any) -> Any:
        notes = self.notes
        if notes is None:
            return None
        try:
            return getattr(notes, method)(*args)
        except Exception:                         # noqa: BLE001 (Anzeige darf den Betrieb nie stören)
            return None

    def _drop(self, entry: int | None, reason: str) -> None:
        if entry is not None:
            self._note("drop", entry, reason)

    def _send_status(self, entry: int | None, status: str) -> None:
        """Haken `on_send` des Chats: was `bridge.send` gemeldet hat."""
        if entry is None:
            return
        if status == "ok":
            self._note("sent", entry)
        else:
            self._drop(entry, {"not_running": "not_running", "kill": "killed"}.get(status, "send_failed"))

    def say_text(self, text: str | Sequence[str]) -> int:
        """Spricht einen fertigen Text (z. B. eine Meldung von sich aus, wenn Claude fertig ist). Satzweise, unterbrechbar.
        Eine Meldung aus mehreren Stücken (eigene Ansagen, Texte von Claude) bleibt getrennt: jedes Stück wird für sich
        zerlegt. Gibt die Zahl der gelieferten Sätze zurück."""
        self._interrupted.clear()
        return self.speaker.say(sentences_of(text))

    def say_cancelled(self) -> None:
        """Kurze Bestätigung nach dem Abbruch (nachdem die laufende Antwort beendet ist)."""
        self._interrupted.clear()
        self.speaker.say([CANCEL_REPLY])

    def _cancel(self, text: str) -> Result:
        cancelled = self.tasks.cancel_all()
        self._interrupted.clear()                 # die Bestätigung soll gesprochen werden
        reply = CANCEL_REPLY if cancelled else NOTHING_REPLY
        self.speaker.say([reply])
        return Result(text, reply, "cancelled")

    def _tune(self, direction: int) -> str:
        """Stufe ändern (+1 empfindlicher = niedrigere Schwellen, -1 weniger empfindlich) oder zurücksetzen (0)."""
        if direction == 0:
            self.tuning.reset(source="voice")
            return tuning_reply(0, 0, True)
        before = self.tuning.snapshot()["step"]
        after = self.tuning.step_by(direction, source="voice")
        return tuning_reply(direction, after, after != before)

    def handle(self, pcm: Any) -> Result:
        self._interrupted.clear()
        self._reset_metrics()
        if self.kill.poll() or self.dialog.state is State.HALTED:
            return Result("", "", "halted")
        text = self.stt.transcribe(pcm).text
        self.metrics["stt_s"] = self._since()
        if not text:
            return Result("", "", "empty")
        if is_kill_phrase(text):
            self.kill.on_transcript(text)
            self.dialog.halt()
            return Result(text, "", "killed", entry=self._note("heard", "", "", "killed"))    # ohne Text, nur „Notaus erkannt“
        raw, text = text, strip_wake_words(text, self.wake_names)
        entry = self._note("heard", raw, text)           # Zeile „Du“ sofort, bevor irgendetwas an Claude geht
        if is_cancel_phrase(text or raw):                # Abbrechen ist immer sicher
            self._drop(entry, "cancelled")
            r = self._cancel(raw)
            r.entry = entry
            return r
        if not text:
            self._drop(entry, "wake_only")
            return Result("", "", "wake_only", entry=entry)   # nur das Wake Word: kein Befehl, nichts prüfen, nichts antworten
        verified = strong = False                        # keine Sprecher-Prüfung mehr: jede Stimme zählt gleich
        score: float | None = None
        if " ".join(_TOKEN.findall(re.sub(r"['’`]", "", text.lower()))) in END_PHRASES:     # Gespräch beenden
            self._drop(entry, "end_conversation")
            self.speaker.say([END_REPLY])
            return Result(text, END_REPLY, "end_conversation", entry=entry)
        if is_shutdown_phrase(text):                     # kushim beenden
            self._drop(entry, "shutdown")
            self.speaker.say([SHUTDOWN_REPLY])
            return Result(text, SHUTDOWN_REPLY, "shutdown", entry=entry)
        direction = is_tuning_phrase(text) if self.tuning is not None else None
        if direction is not None:                        # Mikrofon-Schwellen: lokal, nichts an Claude, nie gespeichert
            self._drop(entry, "command")
            reply = self._tune(direction)
            self.speaker.say(split_sentences(reply) or [reply])
            return Result(text, reply, "command", entry=entry)
        if self.commands is not None:
            answer = self.commands.handle(text, verified, strong, score=score)
            if answer is not None:                       # Befehl oder Bestätigung: kein LLM
                self._drop(entry, "command")
                self.speaker.say(split_sentences(answer) or [answer])      # satzweise: der erste Satz kommt früher
                return Result(text, answer, "command", entry=entry)
        if not self.dialog.triggered():
            self._drop(entry, "halted")
            return Result(text, "", "halted", entry=entry)
        self.dialog.utterance_done()
        self.history.append({"role": "user", "content": text})
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *self.history[-self.history_limit:]]
        sentences: list[str] = []

        def split_whole(stream):
            for item in stream:
                yield from split_sentences(item)

        # Ein Token-Strom (LLM) wird zu Sätzen gesammelt; ganze Meldungen (Claude über den Channel) sofort zerlegen, sonst
        # wartet der letzte Satz auf das nächste Stück und die Quittung kommt erst mit Claudes Antwort (Live-Test 2026-11-11).
        chunker = split_whole if getattr(self.chat, "yields_messages", False) else chunk_stream

        # Wann der Befehl wirklich an Claude ging: ein Chat mit Haken `on_send` meldet das Ergebnis von `bridge.send`,
        # bei jedem anderen Chat gilt der Aufruf selbst als gesendet.
        reports = hasattr(self.chat, "on_send")
        if reports:
            self.chat.on_send = lambda status: self._send_status(entry, status)
        called = threading.Event()
        # Stopp nur für DIESE Runde, einmal gesetzt bleibt er gesetzt: Unterbrechen oder Notaus (auch per Marker-Datei) oder das
        # Ende der Runde. Der Erzeuger-Thread (z. B. ClaudeChat, der noch auf `/reply` wartet) hört damit auf, auch wenn die
        # nächste Runde `_interrupted` schon wieder zurückgesetzt hat; sonst holte er die Antwort der nächsten Frage ab.
        ended = threading.Event()
        # Entweder der Erzeuger-Thread ruft den Chat auf (und `called` steht) oder die Runde endet vorher und der Eintrag wird
        # verworfen: nie beides. Ohne diese Sperre konnte der Thread nach dem Verwerfen noch `bridge.send` aufrufen
        # (Zeile „verworfen: Abbruch“, obwohl Claude den Text bekam).
        start_lock = threading.Lock()

        def turn_stop() -> bool:
            if not ended.is_set() and (self._interrupted.is_set() or self.kill.poll()):
                ended.set()
            return ended.is_set()

        def open_stream():
            if getattr(self.chat, "accepts_stop", False):
                return self.chat(messages, stop=turn_stop)
            return self.chat(messages)

        def sentence_source():
            with start_lock:
                if turn_stop():                                  # schon unterbrochen/Notaus/vorbei: gar nicht erst senden
                    return
                called.set()
            try:
                stream = open_stream()
                marked = reports or entry is None
                for s in chunker(stream):
                    if not marked:                               # "gesendet" erst, wenn der Chat wirklich etwas liefert
                        self._note("sent", entry)
                        marked = True
                    if self.metrics.get("first_text_s") is None:
                        self.metrics["first_text_s"] = self._since()
                    sentences.append(plain(s))                  # Kennzeichen nur für die Stimme, nie im Verlauf
                    yield s
                if not marked:                                   # Chat lief ohne Fehler, aber ohne Text
                    self._note("sent", entry)
            except Exception:
                self._drop(entry, "send_failed")                 # nur, falls noch nicht gesendet
                raise

        try:
            # Kein reply_ready() hier: Der Zustand bleibt THINKING, bis der erste Satz wirklich abgespielt wird (Speaker-Haken).
            self.speaker.say(prefetch(sentence_source(), stop=turn_stop))
        finally:
            with start_lock:
                ended.set()                                      # Runde vorbei: ein noch wartender Erzeuger hört auf
                if not called.is_set():                          # Chat nie aufgerufen (Notaus, Unterbrechen, Fehler)
                    self._drop(entry, "killed" if self.kill.fired else "cancelled" if self._interrupted.is_set()
                               else "send_failed")
                elif not reports and entry is not None:          # Chat ohne `on_send` lief: nie auf `pending` stehen lassen
                    self._note("sent", entry)
        reply = " ".join(sentences)
        self.history.append({"role": "assistant", "content": reply})
        self.dialog.reply_done()
        return Result(text, reply, "interrupted" if self._interrupted.is_set() else "spoken", entry=entry)
