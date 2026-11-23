"""Lokale Sprachausgabe: Satzweises Streaming über eine austauschbare Engine.

Die Engine (Kokoro „Martin“ im eigenen Prozess, `voice/ttsworker.py`) wird von außen geliefert; hier liegt nur die Logik:
- Sätze teilen (mit Schutz für Abkürzungen, Datumsangaben und Ordinalzahlen), den ersten langen Satz am Komma teilen;
- Text normalisieren (`speechnorm`, nach `imitation.guard`, entfernt Steuerzeichen);
- einen Satz vorausrechnen: Satz n+1 wird synthetisiert, während Satz n läuft;
- feste Sätze aus kushims Code („Ja?“, „Moment.“, Bestätigungen) einmal rechnen und wiederverwenden (`SentenceCache`);
- fällt die Stimme aus, nie still bleiben: Hinweiston und Text (`on_unspoken`).
Satzweise Ausgabe senkt die Latenz bis zum ersten Ton und erlaubt Barge-in zwischen Sätzen.
"""
from __future__ import annotations

import queue
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, Protocol

from .earcon import MARK
from .speechnorm import MONTH_NAMES, SPLIT_PROTECT, normalize

FIRST_SPLIT_CHARS = 60          # erster Satz länger als das: am Komma teilen (früherer erster Ton)
FIRST_SPLIT_MIN = 15            # jedes Teilstück mindestens so lang (kein „Ja,“ allein)


class TTSUnavailable(RuntimeError):
    """Die Stimme kann diesen Satz gerade nicht liefern (Worker lädt, abgestürzt, aus, Fehler). Speaker: Text plus Hinweiston."""


class TTSCancelled(RuntimeError):
    """Der Satz wurde abgebrochen (Unterbrechen, Notaus). Kein Fehler, nichts nachholen."""


def prefetch(source: Iterable[str], stop: Callable[[], bool] = lambda: False, size: int = 2) -> Iterator[str]:
    """Erzeugt Sätze in einem Hintergrund-Thread vor, damit das LLM während der Wiedergabe weiterschreibt.

    Bei `stop()` (Notaus, Unterbrechen) endet der Strom sofort, auch wenn das LLM gerade noch an einem Satz schreibt."""
    q: queue.Queue = queue.Queue(maxsize=size)
    END, ERR = object(), object()

    def work():
        try:
            for item in source:
                while True:
                    if stop():
                        return
                    try:
                        q.put(item, timeout=0.1)
                        break
                    except queue.Full:
                        continue
            q.put(END)
        except Exception as e:           # noqa: BLE001 (Fehler an den Verbraucher weiterreichen)
            q.put((ERR, e))

    threading.Thread(target=work, daemon=True).start()
    while True:
        try:
            item = q.get(timeout=0.1)
        except queue.Empty:
            if stop():                   # Erzeuger hängt noch im LLM: nicht auf ihn warten
                return
            continue
        if item is END:
            return
        if isinstance(item, tuple) and item and item[0] is ERR:
            raise item[1]
        yield item


class Engine(Protocol):
    def synthesize(self, text: str) -> Any: ...


# --- Satzteilung ---------------------------------------------------------------------------------------------------------

_BOUNDARY = re.compile(r"[.!?…]+[\"'“”»)\]]*(\s+)")
_WORD_BEFORE = re.compile(r"([\wäöüÄÖÜß]+)$")
_NUMBER_PREFIX = re.compile(r"(?:^|\s)(am|im|zum|vom|dem|den|der|die|das|eine|einen|einem|jede|jeden|jedem|jeder|beim|seit|ab|bis)"
                            r"\s+\d{1,4}$", re.I)
_MONTH_AHEAD = re.compile("(?:" + "|".join(MONTH_NAMES) + r")\b")


def _keeps_together(text: str, dot: int, nxt: int) -> bool:
    """Punkt an `dot` beendet KEINEN Satz: Abkürzung („z. B.“, „ca.“, „Prof.“), Initiale („A. Müller“), Ordinalzahl nach
    Artikel („die 2. Schiene“) oder Datum („am 3. Mai“)."""
    if text[dot] != "." or text[dot:dot + 2] == "..":
        return False
    before = text[:dot]
    word = _WORD_BEFORE.search(before)
    if not word:
        return False
    w = word.group(1)
    if w.lower() in SPLIT_PROTECT or (len(w) == 1 and w.isupper()):
        return True
    if w.isdigit() and len(w) <= 4:
        return bool(_NUMBER_PREFIX.search(before) or _MONTH_AHEAD.match(text, nxt))
    return False


def _cuts(text: str) -> list[tuple[int, int]]:
    """(Ende des Satzes, Anfang des nächsten). Nur wo nach dem Leerraum schon ein Zeichen steht, das nicht klein ist."""
    out = []
    for m in _BOUNDARY.finditer(text):
        nxt = m.end()
        if nxt >= len(text) or text[nxt].islower() or _keeps_together(text, m.start(), nxt):
            continue
        out.append((m.start(1), nxt))
    return out


def split_sentences(text: str) -> list[str]:
    text = text.strip()
    parts, start = [], 0
    for end, nxt in _cuts(text):
        parts.append(text[start:end])
        start = nxt
    parts.append(text[start:])
    return [s.strip() for s in parts if s.strip()]


def chunk_stream(tokens: Iterable[str]) -> Iterator[str]:
    """Fasst einen LLM-Tokenstrom zu vollständigen Sätzen zusammen."""
    buf = ""
    for tok in tokens:
        buf += tok
        cuts = _cuts(buf)
        if not cuts:
            continue
        start = 0
        for end, nxt in cuts:
            if buf[start:end].strip():
                yield buf[start:end].strip()
            start = nxt
        buf = buf[start:]
    if buf.strip():
        yield buf.strip()


def split_first(sentence: str, limit: int = FIRST_SPLIT_CHARS, min_part: int = FIRST_SPLIT_MIN) -> list[str]:
    """Langer erster Satz: am ersten passenden Komma teilen, damit der erste Ton früher kommt („1,5“ bleibt ganz)."""
    if len(sentence) <= limit:
        return [sentence]
    for m in re.finditer(r",\s+", sentence):
        if m.start() >= min_part and len(sentence) - m.end() >= min_part:
            return [sentence[:m.start() + 1].strip(), sentence[m.end():].strip()]
    return [sentence]


# --- Speaker -------------------------------------------------------------------------------------------------------------

@dataclass
class _Part:
    index: int          # Nummer des Satzes aus der Quelle (Zählung „gesprochen“ je Satz, nicht je Teilstück)
    first: bool         # erstes Teilstück dieses Satzes (Signalton nur davor)
    chime: bool
    text: str           # normalisiert, das bekommt die Stimme
    shown: str          # Original ohne Steuerzeichen, für die Textanzeige, wenn die Stimme ausfällt
    audio: Any = None
    error: BaseException | None = None


class Speaker:
    def __init__(self, engine: Engine, play: Callable[[Any], None],
                 should_stop: Callable[[], bool] = lambda: False, lookahead: bool = True):
        self.engine, self.play, self.should_stop = engine, play, should_stop
        self.lookahead = lookahead          # Satz n+1 rechnen, während Satz n läuft
        self.split_first = True             # ersten langen Satz am Komma teilen
        # Nur Anzeige und Barge-in: direkt vor und nach jeder echten Wiedergabe (nicht während auf den Satz gewartet wird)
        self.on_play_start: Callable[[], Any] = lambda: None
        self.on_play_end: Callable[[Any], None] = lambda token: None
        self.on_played: Callable[[], None] = lambda: None     # nach jedem wirklich abgespielten Satz (nur Zählung, talk.log)
        self.chime: Any = None              # Signalton (WAV) vor Sätzen mit earcon.MARK; nur kushims feste Systemansagen
        self.hint: Any = None               # Hinweiston (WAV), wenn die Stimme ausfällt; einmal je `say`
        self.on_unspoken: Callable[[str], None] = lambda text: None    # Satz als Text, wenn die Stimme ausfällt

    def _parts(self, sentences: Iterable[str]) -> Iterator[_Part]:
        first = True
        for index, raw in enumerate(sentences):
            chime = raw.startswith(MARK)
            text = normalize(raw)                     # entfernt auch MARK und alle anderen Steuerzeichen
            if not text:
                continue
            pieces = split_first(text) if first and self.split_first else [text]
            first = False
            shown = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", raw).split())
            for i, piece in enumerate(pieces):
                yield _Part(index, i == 0, chime and i == 0, piece, shown)

    def say(self, sentences: Iterable[str]) -> int:
        """Spielt Sätze nacheinander; bricht vor jedem Satz ab, wenn `should_stop` (Barge-in/Notaus). Beginnt ein Satz mit
        `earcon.MARK`, kommt vorher der Signalton (das Zeichen selbst wird nie gesprochen). Gibt die Zahl der wirklich
        gesprochenen Sätze zurück (ein am Komma geteilter Satz zählt einmal)."""
        parts = self._parts(sentences)
        if not self.lookahead:
            return self._say_serial(parts)
        return self._say_ahead(parts)

    def _synth(self, part: _Part) -> _Part:
        try:
            part.audio = self.engine.synthesize(part.text)
            if part.audio is None:
                part.error = TTSUnavailable("keine Audiodaten")
        except TTSCancelled as e:
            part.error = e
        except Exception as e:              # noqa: BLE001 (jede Störung der Stimme: Text plus Hinweiston)
            part.error = e
        return part

    def _say_serial(self, parts: Iterator[_Part]) -> int:
        state = {"n": 0, "hinted": False, "counted": set(), "shown": set()}
        for part in parts:
            if self.should_stop():
                break
            self._synth(part)
            if not self._deliver(part, state):
                break
        return state["n"]

    def _say_ahead(self, parts: Iterator[_Part]) -> int:
        q: queue.Queue = queue.Queue(maxsize=1)            # höchstens ein Satz fertig im Voraus
        done, failed = object(), object()
        leave = threading.Event()

        def stopped() -> bool:
            return leave.is_set() or self.should_stop()

        def hand_over(item: Any) -> bool:
            while not leave.is_set():
                try:
                    q.put(item, timeout=0.02)
                    return True
                except queue.Full:
                    continue
            return False

        def produce() -> None:
            end: Any = done
            try:
                for part in parts:
                    if stopped():
                        return
                    self._synth(part)
                    if isinstance(part.error, TTSCancelled) or not hand_over(part):
                        return
            except Exception as e:                       # noqa: BLE001 (Quelle, z. B. das LLM, ist gescheitert)
                end = (failed, e)
            finally:
                hand_over(end)                           # der Verbraucher wartet nie ins Leere

        worker = threading.Thread(target=produce, daemon=True, name="kushim-tts-ahead")
        worker.start()
        state: dict[str, Any] = {"n": 0, "hinted": False, "counted": set(), "shown": set()}
        early = False
        try:
            while True:
                try:
                    item = q.get(timeout=0.05)
                except queue.Empty:
                    if self.should_stop():                 # nicht auf Quelle oder Synthese warten
                        early = True
                        break
                    continue
                if item is done:
                    break
                if isinstance(item, tuple) and item[0] is failed:
                    raise item[1]
                if self.should_stop() or not self._deliver(item, state):
                    early = True
                    break
        finally:
            leave.set()                                     # Erzeuger rechnet danach keinen neuen Satz mehr an
            if early:
                cancel = getattr(self.engine, "cancel", None)
                if cancel is not None:
                    try:
                        cancel()                            # laufende Vorausrechnung im Worker verwerfen
                    except Exception:                       # noqa: BLE001
                        pass
            else:
                worker.join(timeout=1.0)                    # regulär zu Ende: der Erzeuger ist schon fertig
        return state["n"]

    def _deliver(self, part: _Part, state: dict[str, Any]) -> bool:
        """Spielt ein fertiges Teilstück (oder Hinweiston plus Text). False: abbrechen."""
        if isinstance(part.error, TTSCancelled):
            return False
        if part.error is not None:
            if not state["hinted"] and self.hint is not None:
                state["hinted"] = True
                token = self.on_play_start()
                try:
                    if self.should_stop():
                        return False
                    self.play(self.hint)
                finally:
                    self.on_play_end(token)
            state["hinted"] = True
            if part.index not in state["shown"]:
                state["shown"].add(part.index)
                try:
                    self.on_unspoken(part.shown)
                except Exception:                           # noqa: BLE001 (Anzeige darf die Ausgabe nie stören)
                    pass
            return not self.should_stop()
        token = self.on_play_start()
        try:
            if self.should_stop():      # zwischen Synthese und Zustandswechsel unterbrochen: nichts mehr abspielen
                return False
            if part.chime and self.chime is not None:
                self.play(self.chime)
                if self.should_stop():
                    return False
            self.play(part.audio)
        finally:
            self.on_play_end(token)
        if part.index not in state["counted"]:
            state["counted"].add(part.index)
            state["n"] += 1
            try:
                self.on_played()
            except Exception:               # noqa: BLE001 (Zählung darf die Ausgabe nie stören)
                pass
        return True


# --- Satz-Cache ----------------------------------------------------------------------------------------------------------

class SentenceCache:
    """Fertige Audios für feste Sätze aus kushims eigenem Code („Ja?“, „Moment.“, Bestätigungen).

    Gespeichert wird NUR, was in `texts` steht (Konstanten im Code, beim Start übergeben); jeder andere Text geht ohne
    Zwischenspeicher an die Engine. Nichts davon landet auf der Platte."""

    def __init__(self, engine: Engine, texts: Iterable[str]):
        self.engine = engine
        self._order = tuple(dict.fromkeys(k for k in (normalize(t) for t in texts) if k))     # Reihenfolge beim Vorwärmen
        self._fixed = frozenset(self._order)
        self._audio: dict[str, Any] = {}
        self._lock = threading.Lock()

    @property
    def fixed(self) -> frozenset[str]:
        return self._fixed

    def synthesize(self, text: str) -> Any:
        key = normalize(text)
        if key not in self._fixed:
            return self.engine.synthesize(text)
        with self._lock:
            hit = self._audio.get(key)
        if hit is not None:
            return hit
        audio = self.engine.synthesize(key)
        if audio is not None:
            with self._lock:
                self._audio[key] = audio
        return audio

    def cached(self, text: str) -> Any:
        """Nur aus dem Speicher (None, wenn noch nicht gerechnet). Rechnet nie."""
        with self._lock:
            return self._audio.get(normalize(text))

    def warm(self, stop: Callable[[], bool] = lambda: False) -> int:
        """Alle festen Sätze einmal rechnen (im Hintergrund nach dem Start, in der übergebenen Reihenfolge). Bricht beim
        ersten Fehler ab."""
        n = 0
        for key in self._order:
            if stop():
                break
            try:
                if self.synthesize(key) is not None:
                    n += 1
            except Exception:               # noqa: BLE001 (Stimme noch nicht bereit: später bei Bedarf)
                break
        return n

    def cancel(self) -> None:
        cancel = getattr(self.engine, "cancel", None)
        if cancel is not None:
            cancel()
