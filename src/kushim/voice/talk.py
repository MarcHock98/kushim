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
    """Wake Word -> (Befehl direkt | "Ja?" und warten) -> Antwort -> Gespräch ohne Wake Word -> Ende bei Stille.

    Ohne `barge` läuft alles nacheinander im selben Thread (wie früher). Mit `barge` läuft die Antwort in einem
    Hintergrund-Thread, während das Mikrofon weiter gelesen wird: Spricht der Nutzer dazwischen, wird die Ausgabe
    gestoppt und seine Äußerung ist die nächste Frage (Unterbrechen)."""

    CONTINUES = ("spoken", "command", "interrupted", "cancelled")      # Ergebnisse, nach denen das Gespräch weitergeht

    def __init__(self, frames: Iterable[Any], pipeline: Pipeline, kill: KillSwitch,
                 wake: Callable[[Any], bool],
                 ack: Callable[[], None] = lambda: None,
                 flush: Callable[[], None] = lambda: None,
                 new_collector: Callable[[], UtteranceCollector] = UtteranceCollector,
                 on_result: Callable[[Result], None] = lambda r: None,
                 first_collector: Callable[[], UtteranceCollector] | None = None,
                 follow_collector: Callable[[], UtteranceCollector] | None = None,
                 barge: Any = None, preroll_frames: int = 0, on_note: Callable[[str], None] = lambda s: None,
                 announce: Callable[[], str | None] | None = None, say: Callable[[str], None] | None = None):
        """`first_collector`: Befehl direkt nach dem Wake Word ("hey kushim, wie spät ist es?") ohne "Ja?" davor.
        Kommt kein Befehl (nur Wake Word, nur Rauschen oder nur der Rest des Wake Words), folgt "Ja?" und
        `new_collector` wartet auf den Befehl. Ohne `first_collector` gibt es "Ja?" sofort.
        `follow_collector`: nach einer Antwort ohne Wake Word weiter zuhören; Stille beendet das Gespräch.
        `barge`: Unterbrechungs-Detektor (`BargeIn`), schaltet Unterbrechen ein.
        `preroll_frames`: so viele Frames VOR dem Auslösen des Wake Words (nur im Arbeitsspeicher) kommen zum Befehl
        dazu, weil der Detektor erst kurz nach dem Wort auslöst und der Anfang des Befehls sonst fehlt.
        `on_note`: Hinweise zur Diagnose (warum "Ja?" kam).
        `announce`/`say`: Meldungen von sich aus (z. B. Claude ist fertig); gesprochen nur, wenn gerade nichts läuft und keiner spricht."""
        self.frames, self.pipeline, self.kill, self.wake = frames, pipeline, kill, wake
        self.ack, self.flush = ack, flush
        self.new_collector, self.on_result = new_collector, on_result
        self.first_collector, self.follow_collector, self.barge = first_collector, follow_collector, barge
        self.on_note = on_note
        self.announce, self.say = announce, say
        from collections import deque
        self._ring: Any = deque(maxlen=preroll_frames) if preroll_frames > 0 else None
        self._collecting: UtteranceCollector | None = None
        self._mode = "idle"          # idle | direct | ack | follow | barge
        self._turn_mode = "idle"     # Modus, in dem die laufende Antwort angefordert wurde
        self._busy: Any = None       # laufende Antwort (Future), nur mit barge
        self._queued: Any = None     # Äußerung, die nach dem Ende der unterbrochenen Antwort drankommt
        self._cancelled = False      # "abbrechen" wurde während der laufenden Antwort gesagt
        self._pool: Any = None

    def _ask_again(self) -> UtteranceCollector:
        self.ack()
        self.flush()                                 # eigene Quittung nicht als Befehl hören
        return self.new_collector()

    def run(self) -> str:
        """Läuft, bis Notaus greift oder die Frames enden. Gibt den Grund zurück."""
        if self.barge is not None:
            from concurrent.futures import ThreadPoolExecutor
            self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kushim-turn")
        try:
            for frame in self.frames:
                if self.kill.poll():
                    if self._busy is not None:
                        self.pipeline.interrupt()
                    return "killed"
                if self.announce is not None and self._busy is None and self._collecting is None:
                    self._speak_announcement()
                r = self._tick_busy(frame) if self._busy is not None else self._tick(frame)
                if r:
                    return r
            while self._busy is not None or self._queued is not None:   # Frames zu Ende: laufende Antwort abwarten
                r = self._finish_busy() if self._busy is not None else self._submit(self._take_queued(), "barge")
                if r:
                    return r
            return "ended"
        finally:
            if self._pool is not None:
                self._pool.shutdown(wait=False, cancel_futures=True)

    def _speak_announcement(self) -> None:
        msg = self.announce()
        if not msg or self.say is None:
            return
        self.on_note(f"Meldung: {msg}")
        try:
            self.say(msg)
        finally:
            self.flush()                             # eigene Ansage nicht als Befehl hören

    # --- Zustand: es läuft gerade eine Antwort (nur mit barge)
    def _tick_busy(self, frame: Any) -> str | None:
        if self._busy.done():
            return self._finish_busy()
        if self._collecting is not None:             # Nutzer hat schon dazwischengesprochen: Äußerung zu Ende sammeln
            if self._collecting.feed(frame):
                audio, self._collecting = self._collecting.audio(), None
                check = getattr(self.pipeline, "try_cancel", None)
                if check is not None and check(audio):          # "abbrechen": Laufendes beenden, nicht als neue Frage einreihen
                    self._cancelled = True
                else:
                    self._queued = audio
            return None
        if self.barge.feed(frame):
            self.pipeline.interrupt()                # Ausgabe sofort stoppen
            self._collecting, self._mode = self.new_collector(), "barge"
            for f in self.barge.recent():            # Anfang des Satzes nicht verlieren
                self._collecting.feed(f)
        return None

    def _finish_busy(self) -> str | None:
        res = self._busy.result()
        self._busy = None
        if self._cancelled:                                      # nach dem Ende der abgebrochenen Antwort kurz bestätigen
            self._cancelled = False
            confirm = getattr(self.pipeline, "say_cancelled", None)
            if confirm is not None:
                confirm()
            self.on_note("Abgebrochen.")
        r = self._process(res)
        if r is None and self._queued is not None:
            r = self._submit(self._take_queued(), "barge")
        return r

    def _take_queued(self) -> Any:
        audio, self._queued = self._queued, None
        return audio

    # --- Zustand: wartet auf das Wake Word oder sammelt eine Äußerung
    def _tick(self, frame: Any) -> str | None:
        if self._collecting is None:
            if self._ring is not None:
                self._ring.append(frame)             # nur im Arbeitsspeicher, verworfen ohne Wake Word
            if self.wake(frame):                     # nur der Detektor sieht Audio vor dem Wake Word
                if self.first_collector is not None:
                    self._collecting, self._mode = self.first_collector(), "direct"
                    if self._ring is not None:
                        self._collecting.preload(list(self._ring))
                        self._ring.clear()
                else:
                    self._collecting, self._mode = self._ask_again(), "ack"
            return None
        if self._collecting.feed(frame):
            audio, heard = self._collecting.audio(), self._collecting.heard_speech
            peak = getattr(self._collecting, "peak", 0.0)
            self._collecting = None
            if not heard:                            # nur Wake Word gesagt: Quittung genügt
                if self._mode == "direct":
                    self.on_note(f"Nach dem Wake Word kam kein Befehl (Stille, lautester Pegel {peak:.0f}, Schwelle siehe speech_level)")
                    self._collecting, self._mode = self._ask_again(), "ack"
                else:
                    self._mode = "idle"              # Stille nach "Ja?" oder im Gespräch: zurück zum Wake Word
                return None
            return self._submit(audio, self._mode)
        return None

    def _submit(self, audio: Any, mode: str) -> str | None:
        self._turn_mode = mode
        if self._pool is None:
            return self._process(self.pipeline.handle(audio))
        if self.barge is not None:
            self.barge.reset()
        self._busy = self._pool.submit(self.pipeline.handle, audio)
        return None

    def _process(self, res: Result) -> str | None:
        """Ergebnis einer Antwort: anzeigen, Gespräch fortsetzen oder beenden."""
        if self._turn_mode == "direct" and res.outcome in ("wake_only", "empty"):
            self._collecting, self._mode = self._ask_again(), "ack"      # nur Rest des Wake Words oder nichts Verständliches
            return None
        if res.outcome != "wake_only":
            self.on_result(res)
        if res.outcome == "killed":
            return "killed"
        if self._collecting is not None or self._queued is not None:     # Nutzer spricht schon weiter (Unterbrechen)
            return None
        if self.follow_collector is not None and res.outcome in self.CONTINUES:
            self.flush()                             # eigene Stimme aus dem Puffer verwerfen
            self._collecting, self._mode = self.follow_collector(), "follow"
        else:
            self._mode = "idle"
        return None


def build_live(root: Path, out_device: int | None, in_device: int | None = None,
               verifier: Any = None, commands: Any = None, wake_names: Iterable[str] = (),
               llm_model: str = DEFAULT_MODEL, whisper_device: str = "cuda", whisper_index: int = 0, tasks: Any = None):
    """Echte Komponenten. Ollama muss laufen (kushim start oder Launcher)."""
    from ..llm.ollama import OllamaClient
    from . import audio
    from .dialog import Dialog
    from .stt import SpeechToText
    from .tts import PiperEngine, Speaker

    import os
    os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")   # Kartennummern wie in nvidia-smi
    if whisper_device == "cuda":
        stt = SpeechToText.from_local(str(root / "models" / "whisper-large-v3-turbo"), device="cuda",
                                      compute_type="float16", device_index=whisper_index)
    else:                             # ohne NVIDIA-Karte oder per Einstellung: Prozessor
        stt = SpeechToText.from_local(str(root / "models" / "whisper-large-v3-turbo"), device="cpu",
                                      compute_type="int8")
    engine = PiperEngine.from_local(str(root / "models" / "piper" / "de_DE-thorsten-high.onnx"))
    llm = OllamaClient(llm_model)
    dialog = Dialog(audio.stop_playback)
    kill = KillSwitch(root, [audio.stop_playback])
    speaker = Speaker(engine, lambda wav: audio.play_wav(wav, out_device), lambda: kill.fired)
    ack_wav = engine.synthesize(ACK_TEXT)
    mic = audio.Mic(in_device)
    pipeline = Pipeline(stt, llm.chat_stream, speaker, dialog, kill, verifier, commands=commands,
                        wake_names=tuple(wake_names), tasks=tasks)
    try:
        llm.warm_up()                 # kein Kaltstart bei der ersten Frage
    except Exception:                 # noqa: BLE001 (nur Beschleunigung; Fehler zeigt sich bei der ersten Antwort)
        pass
    return pipeline, kill, mic, lambda: audio.play_wav(ack_wav, out_device)
