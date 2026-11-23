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
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from ..safety.killswitch import KillSwitch, is_kill_phrase
from ..tasks import TaskRegistry, is_cancel_phrase
from .dialog import Dialog, State
from .stt import SpeechToText
from .tts import Speaker, chunk_stream, prefetch, split_sentences

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
    detail: str = ""  # nur Anzeige, z. B. Score und Dauer bei abgelehntem Sprecher (kein Audio)


class Pipeline:
    def __init__(self, stt: SpeechToText, chat: ChatStream, speaker: Speaker, dialog: Dialog,
                 kill: KillSwitch,
                 history_limit: int = 6,
                 commands: Any = None, wake_names: Sequence[str] = (), tasks: TaskRegistry | None = None):
        self.wake_names = tuple(wake_names)       # werden am Anfang des erkannten Textes entfernt
        self.tasks = tasks if tasks is not None else TaskRegistry()      # laufende Aufgaben, die "abbrechen" beenden kann
        self._interrupted = threading.Event()     # gesetzt, wenn der Nutzer dazwischenspricht
        previous_stop = speaker.should_stop
        speaker.should_stop = lambda: previous_stop() or self._interrupted.is_set()
        # "Ich spreche" nur, solange wirklich Ton läuft; während auf Claude gewartet wird, bleibt es "Ich denke"
        # (Live-Test 2026-11-23: Anzeige "spricht" ohne Ton, weil SPEAKING schon vor dem Warten gesetzt wurde).
        speaker.on_play_start = dialog.playing
        speaker.on_play_end = dialog.played
        self.stt, self.chat, self.speaker, self.dialog, self.kill = stt, chat, speaker, dialog, kill
        self.commands = commands          # Sprachbefehle ohne LLM (`handle(text, verified, strong)`), optional
        self.history: list[dict[str, str]] = []
        self.history_limit = history_limit

    def interrupt(self) -> None:
        """Der Nutzer spricht dazwischen (aus einem anderen Thread): Ausgabe stoppt sofort, nichts wird weitergesprochen."""
        self._interrupted.set()
        self.dialog.triggered()                   # stoppt laufende Wiedergabe (Barge-in), setzt auf Zuhören

    def try_cancel(self, pcm: Any) -> bool:
        """Für die Schleife, WÄHREND eine Antwort läuft: war die Äußerung "abbrechen"? Dann alles Laufende beenden (aus einem
        anderen Thread). Nein: nichts tun (die Äußerung wird danach normal behandelt)."""
        text = self.stt.transcribe(pcm).text
        if not text or not is_cancel_phrase(text):
            return False
        self.tasks.cancel_all()
        self._interrupted.set()                   # stoppt auch Denken/Sprechen
        self.dialog.triggered()
        return True

    def say_text(self, text: str) -> None:
        """Spricht einen fertigen Text (z. B. eine Meldung von sich aus, wenn Claude fertig ist). Satzweise, unterbrechbar."""
        self._interrupted.clear()
        self.speaker.say(split_sentences(text) or [text])

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

    def handle(self, pcm: Any) -> Result:
        self._interrupted.clear()
        if self.kill.poll() or self.dialog.state is State.HALTED:
            return Result("", "", "halted")
        text = self.stt.transcribe(pcm).text
        if not text:
            return Result("", "", "empty")
        if is_kill_phrase(text):
            self.kill.on_transcript(text)
            self.dialog.halt()
            return Result(text, "", "killed")
        if is_cancel_phrase(strip_wake_words(text, self.wake_names) or text):   # Abbrechen ist immer sicher
            return self._cancel(text)
        text = strip_wake_words(text, self.wake_names)
        if not text:
            return Result("", "", "wake_only")      # nur das Wake Word: kein Befehl, nichts prüfen, nichts antworten
        verified = strong = False                        # keine Sprecher-Prüfung mehr: jede Stimme zählt gleich
        score: float | None = None
        if " ".join(_TOKEN.findall(re.sub(r"['’`]", "", text.lower()))) in END_PHRASES:     # Gespräch beenden
            self.speaker.say([END_REPLY])
            return Result(text, END_REPLY, "end_conversation")
        if is_shutdown_phrase(text):                     # kushim beenden
            self.speaker.say([SHUTDOWN_REPLY])
            return Result(text, SHUTDOWN_REPLY, "shutdown")
        if self.commands is not None:
            answer = self.commands.handle(text, verified, strong, score=score)
            if answer is not None:                       # Befehl oder Bestätigung: kein LLM
                self.speaker.say(split_sentences(answer) or [answer])      # satzweise: der erste Satz kommt früher
                return Result(text, answer, "command")
        if not self.dialog.triggered():
            return Result(text, "", "halted")
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

        def sentence_source():
            for s in chunker(self.chat(messages)):
                sentences.append(s)
                yield s

        # Kein reply_ready() hier: Der Zustand bleibt THINKING, bis der erste Satz wirklich abgespielt wird (Speaker-Haken).
        self.speaker.say(prefetch(sentence_source(), stop=lambda: self.kill.fired or self._interrupted.is_set()))
        reply = " ".join(sentences)
        self.history.append({"role": "assistant", "content": reply})
        self.dialog.reply_done()
        return Result(text, reply, "interrupted" if self._interrupted.is_set() else "spoken")
