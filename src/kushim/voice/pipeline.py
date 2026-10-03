"""Sprachpipeline: Äußerung -> STT -> Notaus-Prüfung -> Sprecher-Prüfung -> LLM -> Sprachausgabe.

Reihenfolge ist sicherheitsrelevant:
  1. Notaus-Wortlaut wird VOR allem anderen geprüft (ohne Sprecherprüfung, ohne LLM).
  2. Ist ein Sprecherprofil eingeschrieben, wird bei Nichtübereinstimmung nichts beantwortet.
  3. Das LLM liefert nur Text. Aktionen gibt es hier nicht, sie liefen über den ActionGate.
Alle Komponenten werden injiziert (testbar ohne Audio/Modelle).
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from ..safety.killswitch import KillSwitch, is_kill_phrase
from .dialog import Dialog, State
from .verify import AudioVerifier
from .stt import SpeechToText
from .tts import Speaker, chunk_stream, prefetch

SYSTEM_PROMPT = (
    "Du bist kushim, ein persönlicher, lokaler Assistent. Antworte auf Deutsch, kurz und sachlich, "
    "in höchstens drei Sätzen. Du hast keine Werkzeuge und führst nichts aus. Erfinde keine Fakten; "
    "sag, wenn du etwas nicht weißt.")

ChatStream = Callable[[list[dict[str, str]]], Iterable[str]]

_TOKEN = re.compile(r"[\wäöüßÄÖÜ]+")
MATCH = 0.8      # Ähnlichkeit, ab der ein erkanntes Wort als Wake Word zählt ("Kuschim" statt "kushim")


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
            if len(toks) >= len(ph) and all(
                    difflib.SequenceMatcher(None, toks[i].group().lower(), w).ratio() >= MATCH
                    for i, w in enumerate(ph)):
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
    outcome: str      # "spoken" | "killed" | "empty" | "wake_only" | "rejected_speaker" | "halted"
    detail: str = ""  # nur Anzeige, z. B. Score und Dauer bei abgelehntem Sprecher (kein Audio)


class Pipeline:
    def __init__(self, stt: SpeechToText, chat: ChatStream, speaker: Speaker, dialog: Dialog,
                 kill: KillSwitch, verifier: AudioVerifier | None = None,
                 history_limit: int = 6,
                 commands: Any = None, wake_names: Sequence[str] = ()):
        self.wake_names = tuple(wake_names)       # werden am Anfang des erkannten Textes entfernt
        self.stt, self.chat, self.speaker, self.dialog, self.kill = stt, chat, speaker, dialog, kill
        self.verifier = verifier
        self.commands = commands          # z. B. WakeWordCommands (Sprachbefehle ohne LLM)
        self.history: list[dict[str, str]] = []
        self.history_limit = history_limit

    def handle(self, pcm: Any) -> Result:
        if self.kill.poll() or self.dialog.state is State.HALTED:
            return Result("", "", "halted")
        text = self.stt.transcribe(pcm).text
        if not text:
            return Result("", "", "empty")
        if is_kill_phrase(text):
            self.kill.on_transcript(text)
            self.dialog.halt()
            return Result(text, "", "killed")
        text = strip_wake_words(text, self.wake_names)
        if not text:
            return Result("", "", "wake_only")      # nur das Wake Word: kein Befehl, nichts prüfen, nichts antworten
        verified = strong = False
        if self.verifier is not None and self.verifier.enrolled:
            # Eine kurze Bestätigung ("ja") nach einer stark verifizierten Anfrage darf kürzer sein.
            short_ok = getattr(self.commands, "awaiting", False)
            v = self.verifier.check(pcm, min_seconds=0.4) if short_ok else self.verifier.check(pcm)
            if not v.accepted:
                return Result(text, "", "rejected_speaker",
                              f"Ähnlichkeit {v.score:.2f} (Schwelle {float(self.verifier.profile.threshold):.2f}), "
                              f"{v.seconds:.1f} s, {v.windows} Fenster: {v.reason}")
            verified, strong = True, v.strong
        if self.commands is not None:
            answer = self.commands.handle(text, verified, strong)
            if answer is not None:                       # Befehl oder Bestätigung: kein LLM
                self.speaker.say([answer])
                return Result(text, answer, "command")
        if not self.dialog.triggered():
            return Result(text, "", "halted")
        self.dialog.utterance_done()
        self.history.append({"role": "user", "content": text})
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *self.history[-self.history_limit:]]
        sentences: list[str] = []

        def sentence_source():
            for s in chunk_stream(self.chat(messages)):
                sentences.append(s)
                yield s

        self.dialog.reply_ready()
        self.speaker.say(prefetch(sentence_source(), stop=lambda: self.kill.fired))
        reply = " ".join(sentences)
        self.history.append({"role": "assistant", "content": reply})
        self.dialog.speech_done()
        return Result(text, reply, "spoken")
