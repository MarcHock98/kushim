"""`kushim talk`: Wake Word -> Quittung -> Aufnahme -> Pipeline, mit Notaus in jeder Runde.

Vor dem Wake Word sieht nur der lokale Wake-Word-Detektor das Mikrofonsignal: keine Spracherkennung,
kein LLM, keine Speicherung. Wird nur das Wake Word gesagt, antwortet kushim mit einer kurzen Quittung
und wartet auf den Befehl. Die Schleife ist reine Logik (testbar); `build_live` setzt die echten
Komponenten zusammen.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

from ..safety.killswitch import KillSwitch
from .audio import UtteranceCollector
from .pipeline import Pipeline, Result

ACK_TEXT = "Ja?"


class TalkLoop:
    def __init__(self, frames: Iterable[Any], pipeline: Pipeline, kill: KillSwitch,
                 wake: Callable[[Any], bool],
                 ack: Callable[[], None] = lambda: None,
                 flush: Callable[[], None] = lambda: None,
                 new_collector: Callable[[], UtteranceCollector] = UtteranceCollector,
                 on_result: Callable[[Result], None] = lambda r: None):
        self.frames, self.pipeline, self.kill, self.wake = frames, pipeline, kill, wake
        self.ack, self.flush = ack, flush
        self.new_collector, self.on_result = new_collector, on_result

    def run(self) -> str:
        """Läuft, bis Notaus greift oder die Frames enden. Gibt den Grund zurück."""
        collecting: UtteranceCollector | None = None
        for frame in self.frames:
            if self.kill.poll():
                return "killed"
            if collecting is None:
                if self.wake(frame):                 # nur der Detektor sieht Audio vor dem Wake Word
                    self.ack()
                    self.flush()                     # eigene Quittung nicht als Befehl hören
                    collecting = self.new_collector()
                continue
            if collecting.feed(frame):
                audio, heard = collecting.audio(), collecting.heard_speech
                collecting = None
                if heard:                            # nur Wake Word gesagt: Quittung genügt
                    res = self.pipeline.handle(audio)
                    self.on_result(res)
                    if res.outcome == "killed":
                        return "killed"
        return "ended"


def build_live(root: Path, out_device: int | None, in_device: int | None = None):
    """Echte Komponenten. Ollama muss laufen (kushim start oder Launcher)."""
    from ..llm.ollama import OllamaClient
    from . import audio
    from .dialog import Dialog
    from .stt import SpeechToText
    from .tts import PiperEngine, Speaker

    stt = SpeechToText.from_local(str(root / "models" / "whisper-large-v3-turbo"),
                                  device="cuda", compute_type="float16")
    engine = PiperEngine.from_local(str(root / "models" / "piper" / "de_DE-thorsten-high.onnx"))
    llm = OllamaClient("qwen2.5:7b")
    dialog = Dialog(audio.stop_playback)
    kill = KillSwitch(root, [audio.stop_playback])
    speaker = Speaker(engine, lambda wav: audio.play_wav(wav, out_device), lambda: kill.fired)
    ack_wav = engine.synthesize(ACK_TEXT)
    mic = audio.Mic(in_device)
    pipeline = Pipeline(stt, llm.chat_stream, speaker, dialog, kill)
    return pipeline, kill, mic, lambda: audio.play_wav(ack_wav, out_device)
