"""`kushim talk`: Auslöser (Wake Word oder Taste) -> Aufnahme -> Pipeline, mit Notaus in jeder Runde.

Die Schleife selbst ist reine Logik (testbar). `build_live` setzt die echten Komponenten zusammen:
Whisper, Ollama (nur Loopback), Piper, Mikrofon/Lautsprecher. Nichts davon wird gespeichert.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

from ..safety.killswitch import KillSwitch
from .audio import UtteranceCollector
from .pipeline import Pipeline, Result


class TalkLoop:
    def __init__(self, frames: Iterable[Any], pipeline: Pipeline, kill: KillSwitch,
                 wake: Callable[[Any], bool] | None = None,
                 ptt_down: Callable[[], bool] | None = None,
                 new_collector: Callable[[], UtteranceCollector] = UtteranceCollector,
                 on_result: Callable[[Result], None] = lambda r: None):
        if (wake is None) == (ptt_down is None):
            raise ValueError("Genau ein Auslöser nötig: wake oder ptt_down")
        self.frames, self.pipeline, self.kill = frames, pipeline, kill
        self.wake, self.ptt_down = wake, ptt_down
        self.new_collector, self.on_result = new_collector, on_result

    def run(self) -> str:
        """Läuft, bis Notaus greift oder die Frames enden. Gibt den Grund zurück."""
        it = iter(self.frames)
        collecting: UtteranceCollector | None = None
        for frame in it:
            if self.kill.poll():
                return "killed"
            if collecting is None:
                fired = self.wake(frame) if self.wake else self.ptt_down()
                if fired:
                    collecting = self.new_collector()
                    collecting.feed(frame) if self.ptt_down else None
                continue
            done = collecting.feed(frame)
            if self.ptt_down is not None:
                done = not self.ptt_down()
            if done:
                audio, heard = collecting.audio(), collecting.heard_speech or self.ptt_down is not None
                collecting = None
                if heard:
                    res = self.pipeline.handle(audio)
                    self.on_result(res)
                    if res.outcome == "killed":
                        return "killed"
        return "ended"


def build_live(root: Path, out_device: int | None):
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
    return Pipeline(stt, llm.chat_stream, speaker, dialog, kill), kill
