"""`kushim talk`: Wake Word -> Quittung -> Aufnahme -> Pipeline, mit Notaus in jeder Runde.

Vor dem Wake Word sieht nur der lokale Wake-Word-Detektor das Mikrofonsignal: keine Spracherkennung,
kein LLM, keine Speicherung. Wird nur das Wake Word gesagt, antwortet kushim mit einer kurzen Quittung
und wartet auf den Befehl. Die Schleife ist reine Logik (testbar); `build_live` setzt die echten
Komponenten zusammen.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

from ..llm.ollama import DEFAULT_MODEL
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
                 on_result: Callable[[Result], None] = lambda r: None,
                 first_collector: Callable[[], UtteranceCollector] | None = None):
        """`first_collector`: Befehl direkt nach dem Wake Word ("hey kushim, wie spät ist es?") ohne "Ja?" davor.
        Kommt kein Befehl (nur Wake Word, nur Rauschen oder nur der Rest des Wake Words), folgt "Ja?" und
        `new_collector` wartet auf den Befehl. Ohne `first_collector` gibt es "Ja?" sofort."""
        self.frames, self.pipeline, self.kill, self.wake = frames, pipeline, kill, wake
        self.ack, self.flush = ack, flush
        self.new_collector, self.on_result = new_collector, on_result
        self.first_collector = first_collector

    def _ask_again(self) -> UtteranceCollector:
        self.ack()
        self.flush()                                 # eigene Quittung nicht als Befehl hören
        return self.new_collector()

    def run(self) -> str:
        """Läuft, bis Notaus greift oder die Frames enden. Gibt den Grund zurück."""
        collecting: UtteranceCollector | None = None
        direct = False                               # True: Befehl direkt nach dem Wake Word, noch ohne "Ja?"
        for frame in self.frames:
            if self.kill.poll():
                return "killed"
            if collecting is None:
                if self.wake(frame):                 # nur der Detektor sieht Audio vor dem Wake Word
                    if self.first_collector is not None:
                        collecting, direct = self.first_collector(), True
                    else:
                        collecting, direct = self._ask_again(), False
                continue
            if collecting.feed(frame):
                audio, heard = collecting.audio(), collecting.heard_speech
                collecting = None
                if not heard:                        # nur Wake Word gesagt: Quittung genügt
                    if direct:
                        collecting, direct = self._ask_again(), False
                    continue
                res = self.pipeline.handle(audio)
                if direct and res.outcome in ("wake_only", "empty"):
                    collecting, direct = self._ask_again(), False   # nur Rest des Wake Words oder nichts Verständliches
                    continue
                direct = False
                if res.outcome != "wake_only":
                    self.on_result(res)
                if res.outcome == "killed":
                    return "killed"
        return "ended"


def build_live(root: Path, out_device: int | None, in_device: int | None = None,
               verifier: Any = None, commands: Any = None, wake_names: Iterable[str] = (),
               llm_model: str = DEFAULT_MODEL):
    """Echte Komponenten. Ollama muss laufen (kushim start oder Launcher)."""
    from ..llm.ollama import OllamaClient
    from . import audio
    from .dialog import Dialog
    from .stt import SpeechToText
    from .tts import PiperEngine, Speaker

    stt = SpeechToText.from_local(str(root / "models" / "whisper-large-v3-turbo"),
                                  device="cuda", compute_type="float16")
    engine = PiperEngine.from_local(str(root / "models" / "piper" / "de_DE-thorsten-high.onnx"))
    llm = OllamaClient(llm_model)
    dialog = Dialog(audio.stop_playback)
    kill = KillSwitch(root, [audio.stop_playback])
    speaker = Speaker(engine, lambda wav: audio.play_wav(wav, out_device), lambda: kill.fired)
    ack_wav = engine.synthesize(ACK_TEXT)
    mic = audio.Mic(in_device)
    pipeline = Pipeline(stt, llm.chat_stream, speaker, dialog, kill, verifier, commands=commands,
                        wake_names=tuple(wake_names))
    try:
        llm.warm_up()                 # kein Kaltstart bei der ersten Frage
    except Exception:                 # noqa: BLE001 (nur Beschleunigung; Fehler zeigt sich bei der ersten Antwort)
        pass
    return pipeline, kill, mic, lambda: audio.play_wav(ack_wav, out_device)
