"""`kushim talk`: Wake Word -> Quittung -> Aufnahme -> Pipeline, mit Notaus in jeder Runde.

Vor dem Wake Word sieht nur der lokale Wake-Word-Detektor das Mikrofonsignal: keine Spracherkennung,
keine Weitergabe, keine Speicherung. Wird nur das Wake Word gesagt, antwortet kushim mit einer kurzen Quittung
und wartet auf den Befehl. Die Schleife ist reine Logik (testbar); `build_live` setzt die echten
Komponenten zusammen.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Iterable

from ..safety.killswitch import KillSwitch
from .audio import UtteranceCollector
from .pipeline import Pipeline, Result
from .tts import split_sentences

ACK_TEXT = "Ja?"
TTS_READY_WAIT = 60.0          # so lange wartet `kushim talk` beim Start auf die Stimme (erster GPU-Start bis 20 s)


def cached_texts() -> tuple[str, ...]:
    """Feste Sätze aus kushims Code, die die Stimme einmal rechnet und dann wiederverwendet (Satz-Cache). Nur Konstanten."""
    from . import claude_chat as cc
    from . import pipeline as pl
    return (ACK_TEXT, *cc.FILLERS, pl.CANCEL_REPLY, pl.END_REPLY, pl.NOTHING_REPLY, pl.SHUTDOWN_REPLY, cc.LATE, cc.SILENT,
            cc.FAILED, cc.NOT_RUNNING, cc.LOST, cc.KILLED)


class TalkLoop:
    """Wake Word -> (Befehl direkt | "Ja?" und warten) -> Antwort -> Gespräch ohne Wake Word -> Ende bei Stille.

    Ohne `barge` läuft alles nacheinander im selben Thread (wie früher). Mit `barge` läuft die Antwort in einem
    Hintergrund-Thread, während das Mikrofon weiter gelesen wird: Spricht der Nutzer dazwischen, wird die Ausgabe
    gestoppt und seine Äußerung ist die nächste Frage (Unterbrechen)."""

    CONTINUES = ("spoken", "command", "interrupted", "cancelled", "announce_interrupted")   # danach geht das Gespräch weiter
    ANNOUNCED, ANNOUNCE_INTERRUPTED = "announced", "announce_interrupted"     # Meldung von sich aus: fertig bzw. unterbrochen

    def __init__(self, frames: Iterable[Any], pipeline: Pipeline, kill: KillSwitch,
                 wake: Callable[[Any], bool],
                 ack: Callable[[], None] = lambda: None,
                 flush: Callable[[], None] = lambda: None,
                 new_collector: Callable[[], UtteranceCollector] = UtteranceCollector,
                 on_result: Callable[[Result], None] = lambda r: None,
                 first_collector: Callable[[], UtteranceCollector] | None = None,
                 follow_collector: Callable[[], UtteranceCollector] | None = None,
                 barge: Any = None, preroll_frames: int = 0, on_note: Callable[[str], None] = lambda s: None,
                 announce: Callable[[], str | None] | None = None, say: Callable[[str], None] | None = None,
                 on_frame: Callable[[Any, str], None] = lambda frame, phase: None,
                 on_barge: Callable[[bool, float, bool], None] = lambda speaking, rms, announcement: None):
        """`first_collector`: Befehl direkt nach dem Wake Word ("hey kushim, wie spät ist es?") ohne "Ja?" davor.
        Kommt kein Befehl (nur Wake Word, nur Rauschen oder nur der Rest des Wake Words), folgt "Ja?" und
        `new_collector` wartet auf den Befehl. Ohne `first_collector` gibt es "Ja?" sofort.
        `follow_collector`: nach einer Antwort ohne Wake Word weiter zuhören; Stille beendet das Gespräch.
        `barge`: Unterbrechungs-Detektor (`BargeIn`), schaltet Unterbrechen ein.
        `preroll_frames`: so viele Frames VOR dem Auslösen des Wake Words (nur im Arbeitsspeicher) kommen zum Befehl
        dazu, weil der Detektor erst kurz nach dem Wort auslöst und der Anfang des Befehls sonst fehlt.
        `on_note`: Hinweise zur Diagnose (warum "Ja?" kam).
        `announce`/`say`: Meldungen von sich aus (z. B. Claude ist fertig); gesprochen nur, wenn gerade nichts läuft und keiner spricht.
        Mit `barge` laufen sie wie Antworten im Hintergrund: Das Mikrofon wird weiter gelesen (Unterbrechen, Wake Word, Notaus).
        `on_barge`: nur für talk.log, beim Auslösen des Unterbrechens (spielt kushim gerade Ton?, Pegel des Frames, Meldung?)."""
        self.frames, self.pipeline, self.kill, self.wake = frames, pipeline, kill, wake
        self.ack, self.flush = ack, flush
        self.new_collector, self.on_result = new_collector, on_result
        self.first_collector, self.follow_collector, self.barge = first_collector, follow_collector, barge
        self.on_note = on_note
        self.announce, self.say = announce, say
        self.on_frame = on_frame         # nur Anzeige: (Frame, Phase) je Frame, Fehler stören nie
        self.on_barge = on_barge
        self._barged = False             # in der laufenden Runde wurde unterbrochen
        self._replay: str | None = None  # Rest einer Meldung, die nur ein Geräusch ohne Text unterbrochen hat: kommt einmal
        self._rest: str | None = None    # noch nicht gesprochener Rest der zuletzt unterbrochenen Meldung (wartet aufs Ergebnis)
        self._replaying = False          # die laufende Meldung ist schon ein nachgereichter Rest (höchstens einmal je Meldung)
        from collections import deque
        self._ring: Any = deque(maxlen=preroll_frames) if preroll_frames > 0 else None
        self._collecting: UtteranceCollector | None = None
        self._mode = "idle"          # idle | direct | ack | follow | barge
        self._turn_mode = "idle"     # Modus, in dem die laufende Antwort angefordert wurde
        self._busy: Any = None       # laufende Antwort (Future), nur mit barge
        self._queued: Any = None     # Äußerung, die nach dem Ende der unterbrochenen Antwort drankommt
        self._cancelled = False      # "abbrechen" wurde während der laufenden Antwort gesagt
        self._pool: Any = None

    def phase(self) -> str:
        """Zustand für die Anzeige: halted > speaking > thinking > listening > idle."""
        from .dialog import State
        st = self.pipeline.dialog.state
        if st is State.HALTED:
            return "halted"
        if st is State.SPEAKING:
            return "speaking"
        if self._busy is not None or st is State.THINKING:
            return "thinking"
        if self._collecting is not None:
            return "listening"
        return "idle"

    def _speaking(self) -> bool:
        """Spielt kushim gerade selbst Ton ab? (Zustand SPEAKING gilt nur während echter Wiedergabe.)"""
        from .dialog import State
        dialog = getattr(self.pipeline, "dialog", None)
        return dialog is not None and dialog.state is State.SPEAKING

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
                try:
                    self.on_frame(frame, self.phase())
                except Exception:                # noqa: BLE001 (Anzeige darf den Betrieb nie stören)
                    pass
                if self.kill.poll():
                    if self._busy is not None:
                        self.pipeline.interrupt()
                    return "killed"
                if (self.announce is not None and self._busy is None and self._collecting is None
                        and self._queued is None):
                    r = self._start_announcement()
                    if r:
                        return r
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

    def _start_announcement(self) -> str | None:
        """Meldung von sich aus. Mit `barge` über den Worker wie eine Antwort: Die Frame-Schleife liest weiter das Mikrofon,
        damit Unterbrechen, Wake Word und Notaus auch während der Meldung greifen. Kein Leeren des Mikrofon-Puffers danach
        (sonst ginge ein gesprochener Notaus verloren); die Meldung erzeugt keine Zeile „Du“."""
        if self.say is None:
            return None
        replay, self._replay = self._replay, None
        msg = replay or self.announce()
        if not msg:
            return None
        self.on_note(f"Meldung: {msg}")
        self._turn_mode, self._barged, self._replaying = "announce", False, bool(replay)
        if self._pool is None:                   # ohne Unterbrechen: synchron; danach eigene Stimme aus dem Puffer verwerfen
            try:
                res = self._announce_job(msg)
            finally:
                self.flush()
            return self._process(res)
        if self.barge is not None:
            self.barge.reset()
        self._busy = self._pool.submit(self._announce_job, msg)
        return None

    def _announce_job(self, msg: str) -> Result:
        n = self.say(msg)
        return Result("", msg, self.ANNOUNCED, spoken=n if isinstance(n, int) and not isinstance(n, bool) else None)

    # --- Zustand: es läuft gerade eine Antwort (nur mit barge)
    def _tick_busy(self, frame: Any) -> str | None:
        if self._busy.done():
            return self._finish_busy()
        if self._collecting is not None:             # Nutzer hat schon dazwischengesprochen: Äußerung zu Ende sammeln
            if self._collecting.feed(frame):
                audio, self._collecting = self._collecting.audio(), None
                check = getattr(self.pipeline, "try_cancel", None)
                if check is not None and check(audio):          # "abbrechen" oder "Notaus": Laufendes beenden, nicht einreihen
                    if self.kill.poll():                         # gesprochener Notaus als Zwischenruf
                        return "killed"
                    self._cancelled = True
                else:
                    self._queued = audio
            return None
        speaking = self._speaking()
        announcing = self._turn_mode == "announce"
        barged = self.barge.feed(frame, speaking=speaking)       # eigene Wiedergabe: strengere Schwelle (Echo)
        if not barged and announcing:                            # während einer Meldung zählt auch das Wake Word
            barged = bool(self.wake(frame))
        if barged:
            self.pipeline.interrupt()                # Ausgabe sofort stoppen
            self._barged = True
            try:
                self.on_barge(speaking, float(getattr(self.barge, "last_rms", 0.0)), announcing)
            except Exception:                        # noqa: BLE001 (Protokoll darf den Betrieb nie stören)
                pass
            self._collecting, self._mode = self.new_collector(), "barge"
            for f in self.barge.recent():            # Anfang des Satzes nicht verlieren
                self._collecting.feed(f)
        return None

    def _finish_busy(self) -> str | None:
        res = self._busy.result()
        self._busy = None
        if res.outcome == self.ANNOUNCED and self._barged:
            res = replace(res, outcome=self.ANNOUNCE_INTERRUPTED)
            if not self._replaying:              # Rest merken; nachgereicht nur, wenn die Unterbrechung leer war
                sents = split_sentences(res.reply) or [res.reply]
                # der zuletzt gezählte Satz kann mittendrin abgebrochen sein (Speaker zählt ihn trotzdem): er kommt mit
                done = max(0, res.spoken - 1) if isinstance(res.spoken, int) else 0
                self._rest = " ".join(sents[done:]) or None
        if self._cancelled:                                      # nach dem Ende der abgebrochenen Antwort kurz bestätigen
            self._cancelled = False
            self._rest = None                    # "abbrechen": den Rest der Meldung nicht nachreichen
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
        self._turn_mode, self._barged = mode, False
        if self._pool is None:
            return self._process(self.pipeline.handle(audio))
        if self.barge is not None:
            self.barge.reset()
        self._busy = self._pool.submit(self.pipeline.handle, audio)
        return None

    def _process(self, res: Result) -> str | None:
        """Ergebnis einer Antwort: anzeigen, Gespräch fortsetzen oder beenden."""
        if res.outcome != self.ANNOUNCE_INTERRUPTED:
            rest, self._rest = self._rest, None
            if rest and res.outcome == "empty":   # nur Geräusch, kein Text: Rest einmal nachreichen
                self._replay = rest
        if self._turn_mode == "direct" and res.outcome in ("wake_only", "empty"):
            self._collecting, self._mode = self._ask_again(), "ack"      # nur Rest des Wake Words oder nichts Verständliches
            return None
        if res.outcome != "wake_only":
            self.on_result(res)
        if res.outcome == "killed":
            return "killed"
        if res.outcome == "shutdown":
            return "shutdown"
        if self._collecting is not None or self._queued is not None:     # Nutzer spricht schon weiter (Unterbrechen)
            return None
        if res.outcome == self.ANNOUNCED:            # Meldung zu Ende: zurück zum Wake Word, kein Gespräch ohne Wake Word
            self._mode = "idle"
            return None
        if self.follow_collector is not None and res.outcome in self.CONTINUES:
            self.flush()                             # eigene Stimme aus dem Puffer verwerfen
            self._collecting, self._mode = self.follow_collector(), "follow"
        else:
            self._mode = "idle"
        return None


def build_live(root: Path, out_device: int | None, in_device: int | None = None,
               commands: Any = None, wake_names: Iterable[str] = (),
               whisper_device: str = "cuda", whisper_index: int = 0, tasks: Any = None,
               on_note: Callable[[str], None] = lambda s: None):
    """Echte Komponenten. Antworten kommen von Claude Code über den kushim-Channel (Roadmap v2 B4); `pipeline.chat` ist ein
    `ClaudeChat` mit `announcement()` für verspätete Antworten. Freigaben gibt es nie per Stimme (keine Sprecher-Prüfung).

    Reihenfolge: zuerst Whisper (größter GPU-Verbraucher), danach der Sprachausgabe-Worker (Kokoro „Martin“, eigener Prozess,
    auf derselben Karte; ohne Karte auf dem Prozessor). `pipeline.tts` ist der Worker (Zustand, Beenden)."""
    import threading

    from ..channel.bridge import Bridge
    from ..tasks import TaskRegistry
    from . import audio
    from .claude_chat import ClaudeChat
    from .dialog import Dialog
    from .earcon import chime_wav, hint_wav
    from .stt import SpeechToText
    from .tts import SentenceCache, Speaker
    from .ttsworker import KokoroWorker

    import os
    os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")   # Kartennummern wie in nvidia-smi
    if whisper_device == "cuda":
        stt = SpeechToText.from_local(str(root / "models" / "whisper-large-v3-turbo"), device="cuda",
                                      compute_type="float16", device_index=whisper_index)
    else:                             # ohne NVIDIA-Karte oder per Einstellung: Prozessor
        stt = SpeechToText.from_local(str(root / "models" / "whisper-large-v3-turbo"), device="cpu",
                                      compute_type="int8")
    worker = KokoroWorker.for_root(root, "cuda" if whisper_device == "cuda" else "cpu", device_id=whisper_index)
    worker.on_note = on_note
    worker.start()
    if not worker.wait_ready(TTS_READY_WAIT):
        on_note(f"Sprachausgabe noch nicht bereit ({worker.state}): Antworten kommen bis dahin als Text mit Hinweiston.")
    cache = SentenceCache(worker, cached_texts())
    dialog = Dialog(audio.stop_playback)
    kill = KillSwitch(root, [audio.stop_playback, worker.kill])           # Notaus beendet auch den Worker (kill_tree)
    speaker = Speaker(cache, lambda wav: audio.play_wav(wav, out_device), kill.poll)   # Marker-Datei stoppt sofort
    speaker.chime = chime_wav()                 # Signalton vor kushims eigenen Ansagen (Freigabe, Notaus), nie vor `sprich`
    speaker.hint = hint = hint_wav()            # Stimme ausgefallen: Hinweiston, der Text steht im Fenster
    speaker.on_unspoken = lambda text: on_note(f"Ohne Stimme: {text}")
    threading.Thread(target=cache.warm, kwargs={"stop": lambda: kill.fired}, daemon=True, name="kushim-tts-warm").start()

    def ack() -> None:
        try:
            wav = cache.synthesize(ACK_TEXT)    # aus dem Satz-Cache, sonst einmal gerechnet
        except Exception:                       # noqa: BLE001 (Stimme fehlt: Hinweiston statt Stille)
            wav = hint
        audio.play_wav(wav, out_device)
    mic = audio.Mic(in_device)
    tasks = tasks if tasks is not None else TaskRegistry()
    bridge = Bridge(root)
    pipeline = Pipeline(stt, ClaudeChat(bridge, tasks), speaker, dialog, kill, commands=commands,
                        wake_names=tuple(wake_names), tasks=tasks)
    pipeline.tts = worker
    return pipeline, kill, mic, ack
