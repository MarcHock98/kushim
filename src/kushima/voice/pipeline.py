"""Sprachpipeline: Äußerung -> STT -> Notaus-Prüfung -> Sprecher-Prüfung -> LLM -> Sprachausgabe.

Reihenfolge ist sicherheitsrelevant:
  1. Notaus-Wortlaut wird VOR allem anderen geprüft (ohne Sprecherprüfung, ohne LLM).
  2. Ist ein Sprecherprofil eingeschrieben, wird bei Nichtübereinstimmung nichts beantwortet.
  3. Das LLM liefert nur Text. Aktionen gibt es hier nicht, sie liefen über den ActionGate.
Alle Komponenten werden injiziert (testbar ohne Audio/Modelle).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from ..safety.killswitch import KillSwitch, is_kill_phrase
from .dialog import Dialog, State
from .speaker import SpeakerVerifier
from .stt import SpeechToText
from .tts import Speaker, chunk_stream, prefetch

SYSTEM_PROMPT = (
    "Du bist kushima, ein persönlicher, lokaler Assistent. Antworte auf Deutsch, kurz und sachlich, "
    "in höchstens drei Sätzen. Du hast keine Werkzeuge und führst nichts aus. Erfinde keine Fakten; "
    "sag, wenn du etwas nicht weißt.")

ChatStream = Callable[[list[dict[str, str]]], Iterable[str]]


@dataclass
class Result:
    heard: str
    reply: str
    outcome: str      # "spoken" | "killed" | "empty" | "rejected_speaker" | "halted"


class Pipeline:
    def __init__(self, stt: SpeechToText, chat: ChatStream, speaker: Speaker, dialog: Dialog,
                 kill: KillSwitch, verifier: SpeakerVerifier | None = None,
                 embed: Callable[[Any], Any] | None = None, history_limit: int = 6):
        self.stt, self.chat, self.speaker, self.dialog, self.kill = stt, chat, speaker, dialog, kill
        self.verifier, self.embed = verifier, embed
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
        if self.verifier is not None and self.verifier.enrolled:
            if self.embed is None or not self.verifier.verify(self.embed(pcm)).accepted:
                return Result(text, "", "rejected_speaker")
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
