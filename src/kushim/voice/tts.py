"""Lokale Sprachausgabe: Satzweises Streaming über eine austauschbare Engine.

Die Engine (Kokoro „Martin“ im eigenen Prozess, `voice/ttsworker.py`) wird von außen geliefert; hier liegt nur die Logik:
- Sätze teilen (mit Schutz für Abkürzungen, Datumsangaben und Ordinalzahlen), den ersten langen Satz am Komma teilen und jeden
  Abschnitt auf höchstens LONG_SPLIT Zeichen kürzen (sonst scheitert Kokoro an über 510 Phonemen);
- Text normalisieren (`speechnorm`, nach `imitation.guard`, entfernt Steuerzeichen) und danach Claudes Sätze noch einmal auf
  nachgeahmte Systemansagen prüfen (die Normalisierung entfernt Zeichen, die den ersten Filter umgehen konnten);
- das Prüffenster über `say`-Aufrufe hinweg halten (`ForeignWindow`): getrennt abgeholte oder nachgereichte Sätze von Claude
  („Die Freigabe.“ und kurz danach „Ist erteilt.“) werden zusammen geprüft;
- einen Satz vorausrechnen: Satz n+1 wird synthetisiert, während Satz n läuft;
- feste Sätze aus kushims Code („Ja?“, „Moment.“, Bestätigungen) einmal rechnen und wiederverwenden (`SentenceCache`);
- fällt die Stimme aus, nie still bleiben: Hinweiston und Text (`on_unspoken`).
Satzweise Ausgabe senkt die Latenz bis zum ersten Ton und erlaubt Barge-in zwischen Sätzen.
"""
from __future__ import annotations

import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, Protocol, Sequence

from ..safety import imitation
from .earcon import END, MARK, MARKS, OWN, plain
from .imitation_fold import fold, folded_suspect
from .speechnorm import MONTH_NAMES, SPLIT_PROTECT, normalize

FIRST_SPLIT_CHARS = 60          # erster Satz länger als das: am Komma teilen (früherer erster Ton)
FIRST_SPLIT_MIN = 15            # jedes Teilstück mindestens so lang (kein „Ja,“ allein)
LONG_SPLIT = 250                # kein Abschnitt länger (Kokoro: höchstens 510 Phoneme, sonst Abbruch oder abgeschnitten)


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
_ARTICLE_NUMBER = re.compile(r"(?:^|\s)(der|die|das|den|dem|eine|einen|einem|jede|jeden|jedem|jeder)\s+\d{1,4}$", re.I)
_PREP_NUMBER = re.compile(r"(?:^|\s)(am|im|zum|vom|beim|seit|ab|bis)\s+\d{1,4}$", re.I)
_MONTH_AHEAD = re.compile("(?:" + "|".join(MONTH_NAMES) + r")\b")
_NEXT_WORD = re.compile(r"([\wäöüÄÖÜß]+)")
# Nomen, vor denen eine Zahl mit Punkt nach einer Präposition eine Ordinalzahl ist („zum 2. Mal“, „am 3. Tag“)
_ORDINAL_NOUNS = frozenset({"Tag", "Mal", "Woche", "Monat", "Jahr", "Platz", "Stock", "Stockwerk", "Stelle", "Runde", "Klasse",
                            "Etage", "Advent", "Quartal", "Halbjahr", "Jahrhundert", "Jahrtausend", "Kapitel", "Schritt",
                            "Versuch", "Teil", "Geburtstag", "Spieltag", "Durchgang", "Halbzeit", "Bezirk", "Grad", "Grades"})
_INITIAL_BEFORE = re.compile(r"(?:^|[\s(])(?:Herr|Frau|Dr\.|Prof\.|von|van|de|[A-ZÄÖÜ]\.)\s*$")
_LETTER_PAIR = re.compile(r"(?:^|[\s(])[A-Za-zÄäÖöÜü]\.\s?[A-Za-zÄäÖöÜü]$")


def _keeps_together(text: str, dot: int, nxt: int) -> bool:
    """Punkt an `dot` beendet KEINEN Satz: Abkürzung („z. B.“, „ca.“, „Prof.“), Initiale („A. Müller“), Ordinalzahl nach
    Artikel („die 2. Schiene“), nach Präposition vor passendem Nomen („zum 2. Mal“) oder Datum („am 3. Mai“).
    Dagegen trennen „Plan B. Dann …“, „Vitamin C. Du …“, „seit 2020. Danach …“ und „am 3. Danach …“."""
    if text[dot] != "." or text[dot:dot + 2] == "..":
        return False
    before = text[:dot]
    word = _WORD_BEFORE.search(before)
    if not word:
        return False
    w = word.group(1)
    if len(w) > 1 and (w.lower() in SPLIT_PROTECT or w.endswith("str")):     # „Prof.“, „ca.“, „Hauptstr.“
        return True
    if len(w) == 1 and not w.isdigit():
        if w.islower():                                   # Teil einer Abkürzung: „z.“, „d.“, „u.“, „s.“
            return True
        head = before[:-1]
        return bool(_LETTER_PAIR.search(before) or not head.strip() or _INITIAL_BEFORE.search(head))
    if w.isdigit() and len(w) <= 4:
        if _MONTH_AHEAD.match(text, nxt):
            return True
        following = _NEXT_WORD.match(text, nxt)
        if _ARTICLE_NUMBER.search(before):
            return bool(following and following.group(1)[0].isupper())
        if _PREP_NUMBER.search(before):
            return bool(following and following.group(1) in _ORDINAL_NOUNS)
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


_UNITS = re.compile(f"(?=[{MARK}{OWN}])|(?<={END})")


def _plain_sentences(text: str) -> list[str]:
    text = text.strip()
    parts, start = [], 0
    for end, nxt in _cuts(text):
        parts.append(text[start:end])
        start = nxt
    parts.append(text[start:])
    return [s.strip() for s in parts if s.strip()]


def split_sentences(text: str) -> list[str]:
    """Teilt einen Text in Sätze. Eigene Sätze von kushim (`earcon.mark`: MARK bzw. OWN ... END) sind feste Einheiten: vor
    einem Anfangszeichen und nach END wird immer getrennt, und nur diese Einheiten behalten ihr Kennzeichen. Nichts wird
    abgeleitet: Text außerhalb einer Einheit (z. B. von Claude) gilt nie als eigener Satz, auch wenn er klein anfängt."""
    out: list[str] = []
    for unit in _UNITS.split(text):
        unit = unit.strip()
        if not unit:
            continue
        if unit[0] in (MARK, OWN) and unit.endswith(END):
            out.append(unit)                       # ein eigener Satz, unverändert (nie weiter zerlegt)
        elif unit[0] in (MARK, OWN):               # Anfangszeichen ohne END (ältere Form): nur der erste Satz ist eigen
            first, *rest = _plain_sentences(unit[1:]) or [""]
            out.append(unit[0] + first)
            out.extend(_plain_sentences(" ".join(rest)) if rest else [])
        else:
            out.extend(_plain_sentences(unit.replace(END, " ")))
    return [s for s in out if s.strip(MARKS + " ")]


def pieces_of(message: str | Sequence[str] | None) -> list[str]:
    """Eine Meldung als Liste getrennter Stücke (eigene Ansagen und Texte von Claude werden nie zu einem String verbunden)."""
    if message is None:
        return []
    return [message] if isinstance(message, str) else [p for p in message if isinstance(p, str) and p]


def sentences_of(message: str | Sequence[str] | None) -> list[str]:
    """Alle Sätze einer Meldung; jedes Stück wird für sich zerlegt und behält nur seine eigenen Kennzeichen."""
    return [s for piece in pieces_of(message) for s in split_sentences(piece)]


def display(message: str | Sequence[str] | None) -> str:
    """Meldung als Anzeigetext ohne Kennzeichen."""
    return " ".join(" ".join(plain(p).split()) for p in pieces_of(message))


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


# (Muster, Art): Art "keep" = Zeichen bleibt am Ende des ersten Stücks, "drop" = fällt weg, "next" = beginnt das zweite Stück
_LONG_BREAKS = ((re.compile(r"[,;:]\s+"), "keep"), (re.compile(r"\s[–—-]\s"), "drop"),
                (re.compile(r"\s(?=(?:und|oder|aber|sondern|denn|weil|dass|bis|sowie)\s)"), "next"),
                (re.compile(r"\s+"), "drop"))


def split_long(text: str, limit: int = LONG_SPLIT) -> list[str]:
    """Teilt einen (normalisierten) Abschnitt in Stücke von höchstens `limit` Zeichen: zuerst an Komma, Doppelpunkt, Semikolon,
    dann an Strichen, vor „und“/„oder“ …, zuletzt an einer Wortgrenze. Nichts wird abgeschnitten."""
    out: list[str] = []
    text = text.strip()
    while len(text) > limit:
        window, cut = text[:limit + 1], None
        for pattern, kind in _LONG_BREAKS:
            found = [m for m in pattern.finditer(window) if limit // 3 <= m.start() <= limit]
            if found:
                cut = (found[-1], kind)
                break
        if cut is None:                                   # ein einziges sehr langes Wort: hart teilen
            head, text = text[:limit], text[limit:]
        else:
            m, kind = cut
            head = text[:m.start() + 1] if kind == "keep" else text[:m.start()]
            text = text[m.start():] if kind == "next" else text[m.end():]
            if kind == "drop" and m.group(0).strip():     # Strich: als kurze Pause behalten
                head = head.rstrip() + ","
        out.append(head.strip())
        text = text.strip()
    if text:
        out.append(text)
    return out


def speech_pieces(text: str, first: bool) -> list[str]:
    """Stücke eines normalisierten Satzes, so wie die Stimme sie bekommt (Speaker und Satz-Cache benutzen dasselbe)."""
    pieces = split_first(text) if first else [text]
    return [q for p in pieces for q in split_long(p) if q]


# --- Speaker -------------------------------------------------------------------------------------------------------------

@dataclass
class _Part:
    index: int          # Nummer des Satzes aus der Quelle (Zählung „geliefert“ je Satz, nicht je Teilstück)
    first: bool         # erstes Teilstück dieses Satzes (Signalton nur davor)
    chime: bool
    text: str           # normalisiert, das bekommt die Stimme
    shown: str          # Original ohne Steuerzeichen, für die Textanzeige, wenn die Stimme ausfällt
    audio: Any = None
    error: BaseException | None = None


def _visible(raw: str) -> str:
    return " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", raw).split())


IMITATION_WINDOW = 160          # so viele Zeichen fremder Sätze davor prüft der Speaker mit
# Trennzeichen mitten in einem Wort ohne Leerraum („Not.aus“, „Not(aus)“, „Not‧aus“): für eine zusätzliche Prüfung Leerzeichen
_INNER_GAP = re.compile(r"(?<=[^\W\d_])[^\w\s]+(?=[^\W\d_])")


def imitation_suspect(text: str) -> bool:
    """`imitation.imitates_system` auf dem Text, auf der gefalteten Fassung und auf Fassungen ohne Trennzeichen in Wörtern;
    dazu die Kernwort-Prüfung über zusammengezogene Wortteile (`imitation_fold`). Verschärft nur (safety/ bleibt unverändert);
    harmlose Sätze wie „frei, gab er an“, „Notausgang“ oder „Ich war in Not. Aus Angst …“ bleiben."""
    if imitation.imitates_system(text):
        return True
    folded = fold(text)
    if imitation.imitates_system(folded):
        return True
    spaced = _INNER_GAP.sub(" ", folded)          # „Not.aus.ist.aktiv“ → „Not aus ist aktiv“ (keine Satzgrenzen betroffen)
    if spaced != folded and imitation.imitates_system(spaced):
        return True
    return folded_suspect(text)


FOREIGN_GAP = 8.0               # so viele Sekunden nach dem letzten fremden Satz gilt das Fenster noch im nächsten `say`


class ForeignWindow:
    """Die zuletzt gesprochenen fremden Sätze (nicht kushims eigene), normalisiert, über `say`-Aufrufe hinweg.

    Schließt zwei Lücken des Fensters im Speaker, das nur innerhalb eines `say` galt: zwei getrennt abgeholte `sprich`-Texte
    („Die Freigabe.“, kurz danach „Ist erteilt.“) und das Nachreichen einer unterbrochenen Meldung ab Satz 2. Gilt nur, wenn
    der vorige fremde Satz höchstens `gap` Sekunden her ist (`clock` austauschbar, für Tests). Geleert bei eigenem Text,
    Treffer, Abbruch, Unterbrechen, Notaus und neuer Nutzerrunde. Jedes Leeren beginnt eine neue Generation: Ein `say`, das
    davor begonnen hat, schreibt danach nichts mehr hinein. Thread-sicher, nur im Arbeitsspeicher (nie auf die Platte)."""

    def __init__(self, size: int = IMITATION_WINDOW, gap: float = FOREIGN_GAP, clock: Callable[[], float] = time.monotonic):
        self.size, self.gap, self.clock = size, gap, clock
        self._lock = threading.Lock()
        self._text = ""
        self._at = 0.0                      # Zeitpunkt des letzten fremden Satzes (bzw. des Endes seiner Wiedergabe)
        self._gen = 0

    def _fresh(self) -> bool:
        return bool(self._text) and self.clock() - self._at <= self.gap

    def generation(self) -> int:
        with self._lock:
            return self._gen

    def recent(self) -> str:
        """Der normalisierte Text davor, wenn er höchstens `gap` Sekunden alt ist, sonst ""."""
        with self._lock:
            return self._text if self._fresh() else ""

    def add(self, text: str, gen: int) -> bool:
        """Einen gesprochenen fremden Satz anhängen (nur in derselben Generation; Älteres als `gap` fällt vorher weg)."""
        with self._lock:
            if gen != self._gen:
                return False
            before = self._text if self._fresh() else ""
            self._text = f"{before} {text}".strip()[-self.size:]
            self._at = self.clock()
            return True

    def touch(self) -> None:
        """Ein `say` ist regulär zu Ende: die Frist zählt ab jetzt (der letzte Satz lief bis eben)."""
        with self._lock:
            if self._fresh():
                self._at = self.clock()

    def clear(self) -> int:
        """Leeren (Abbruch, Unterbrechen, Notaus, neue Runde). Gibt die neue Generation zurück."""
        with self._lock:
            self._text, self._gen = "", self._gen + 1
            return self._gen

    def restart(self, gen: int) -> int:
        """Leeren aus einem laufenden `say` (eigener Text, Treffer), nur wenn `gen` noch gilt; sonst bleibt `gen` (veraltet)."""
        with self._lock:
            if gen != self._gen:
                return gen
            self._text, self._gen = "", self._gen + 1
            return self._gen


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
        self.imitations = 0                 # nach der Normalisierung ersetzte Sätze (nur Zählung)
        self.recent = ForeignWindow()       # fremde Sätze der letzten `say`-Aufrufe (nur Arbeitsspeicher)

    def _parts(self, sentences: Iterable[str], count: bool = True) -> Iterator[_Part]:
        first = True
        window = ""                                       # normalisierter Text der fremden Sätze dieses `say` (gleitend)
        carried: str | None = None                        # fremder Text aus früheren `say` (beim ersten fremden Satz gelesen)
        recent = self.recent
        gen = recent.generation()
        for index, raw in enumerate(sentences):
            chime = raw.startswith(MARK)
            own = raw.startswith((MARK, OWN))             # kushims eigener fester Text (nur aus dem Code, nie von Claude)
            text = normalize(raw)                         # entfernt auch die Kennzeichen und alle anderen Steuerzeichen
            if not text:
                continue
            shown = _visible(raw)
            if own:
                gen = recent.restart(gen)                 # eigener Text trennt: das Davor zählt in späteren `say` nicht mehr
                carried = ""
            else:
                if carried is None:
                    carried = recent.recent()             # "" wenn leer oder der vorige fremde Satz älter als FOREIGN_GAP
                # Zweite Prüfung NACH der Normalisierung: Sie entfernt Anführungszeichen, Emoji und andere Zeichen, mit denen
                # Claude „Not«aus“ oder „Freig„abe erteilt“ am ersten Filter vorbeibringen könnte. Geprüft wird der Satz, das
                # gleitende Fenster über die fremden Sätze davor („Die Frei«gabe. Wurde vorhin. Erteilt.“), auch aus den
                # `say`-Aufrufen kurz davor, und der Rohtext.
                tail = f"{carried} {window}".strip()[-IMITATION_WINDOW:]
                if (imitation.imitates_system(shown) or imitation_suspect(text)
                        or (tail and imitation_suspect(f"{tail} {text}"))):
                    if count:
                        self.imitations += 1
                    shown = imitation.NEUTRAL
                    text = normalize(imitation.NEUTRAL)
                    window = carried = ""                 # Fund verbraucht: spätere Sätze nicht deswegen ersetzen
                    gen = recent.restart(gen)
                else:
                    window = f"{window} {text}".strip()[-IMITATION_WINDOW:]
                    recent.add(text, gen)
            for i, piece in enumerate(speech_pieces(text, first and self.split_first)):
                yield _Part(index, i == 0, chime and i == 0, piece, shown)
            first = False

    def forget_recent(self) -> None:
        """Fenster über `say` hinweg leeren (Abbruch, Unterbrechen, Notaus, neue Nutzerrunde)."""
        self.recent.clear()

    def prime_recent(self, sentences: Iterable[str]) -> None:
        """Nachreichen: das Fenster mit den schon gesprochenen Sätzen derselben Meldung vorbelegen, genau so, wie der Speaker sie
        beim ersten Mal gesehen hat (eigene Sätze trennen, ein Treffer leert). Spricht nichts, zählt nichts."""
        self.recent.clear()
        for _ in self._parts(sentences, count=False):
            pass

    def say(self, sentences: Iterable[str]) -> int:
        """Spielt Sätze nacheinander; bricht vor jedem Satz ab, wenn `should_stop` (Barge-in/Notaus). Beginnt ein Satz mit
        `earcon.MARK`, kommt vorher der Signalton (das Zeichen selbst wird nie gesprochen). Gibt die Zahl der gelieferten
        Sätze zurück: gesprochen oder (Stimme fehlt) als Text gezeigt; ein geteilter Satz zählt einmal. So setzt das
        Nachreichen einer unterbrochenen Meldung an der richtigen Stelle wieder an. Abgebrochen (Unterbrechen, Notaus,
        Fehler): das Fenster über `say` hinweg wird geleert; regulär zu Ende: seine Frist zählt ab jetzt."""
        parts = self._parts(sentences)
        try:
            n = self._say_serial(parts) if not self.lookahead else self._say_ahead(parts)
        except BaseException:
            self.recent.clear()
            raise
        if self.should_stop():
            self.recent.clear()
        else:
            self.recent.touch()
        return n

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

    def _cancel_engine(self) -> None:
        cancel = getattr(self.engine, "cancel", None)
        if cancel is not None:
            try:
                cancel()                    # laufende Vorausrechnung im Worker verwerfen
            except Exception:               # noqa: BLE001
                pass

    def _say_serial(self, parts: Iterator[_Part]) -> int:
        state: dict[str, Any] = {"n": 0, "hinted": False, "counted": set(), "shown": set()}
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
        early = True                                     # bis zum regulären Ende: auch bei Ausnahmen in `play` abbrechen
        try:
            while True:
                try:
                    item = q.get(timeout=0.05)
                except queue.Empty:
                    if self.should_stop():                 # nicht auf Quelle oder Synthese warten
                        break
                    continue
                if item is done:
                    early = False
                    break
                if isinstance(item, tuple) and item[0] is failed:
                    early = False                        # die Quelle ist zu Ende (mit Fehler), die Synthese ruht
                    raise item[1]
                if self.should_stop() or not self._deliver(item, state):
                    break
        finally:
            leave.set()                                     # Erzeuger rechnet danach keinen neuen Satz mehr an
            if early:
                self._cancel_engine()
            else:
                worker.join(timeout=1.0)                    # regulär zu Ende: der Erzeuger ist schon fertig
        return state["n"]

    def _count(self, part: _Part, state: dict[str, Any], played: bool) -> None:
        if part.index in state["counted"]:
            return
        state["counted"].add(part.index)
        state["n"] += 1
        if played:
            try:
                self.on_played()
            except Exception:               # noqa: BLE001 (Zählung darf die Ausgabe nie stören)
                pass

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
            if part.index not in state["shown"]:          # ganzer Satz als Text, auch wenn ein Teil schon zu hören war
                state["shown"].add(part.index)
                try:
                    self.on_unspoken(part.shown)
                except Exception:                           # noqa: BLE001 (Anzeige darf die Ausgabe nie stören)
                    pass
            self._count(part, state, played=False)
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
        self._count(part, state, played=True)
        return True


# --- Satz-Cache ----------------------------------------------------------------------------------------------------------

class SentenceCache:
    """Fertige Audios für feste Sätze aus kushims eigenem Code („Ja?“, „Moment.“, Bestätigungen).

    Gespeichert wird NUR, was aus `texts` stammt (Konstanten im Code, beim Start übergeben); jeder andere Text geht ohne
    Zwischenspeicher an die Engine. Mehrsatz-Texte werden wie beim Sprechen in Sätze und Stücke zerlegt, damit die Schlüssel
    genau denen des Speakers entsprechen. Nichts davon landet auf der Platte."""

    def __init__(self, engine: Engine, texts: Iterable[str]):
        self.engine = engine
        keys: list[str] = []
        for t in texts:
            for s in split_sentences(t):
                k = normalize(s)
                if not k:
                    continue
                for first in (True, False):           # jeder Satz kann der erste eines `say` sein (Komma-Teilung)
                    keys.extend(speech_pieces(k, first))
        self._order = tuple(dict.fromkeys(keys))      # Reihenfolge beim Vorwärmen
        self._fixed = frozenset(self._order)
        self._audio: dict[str, Any] = {}
        self._lock = threading.Lock()

    @property
    def fixed(self) -> frozenset[str]:
        return self._fixed

    def _key(self, text: str) -> str:
        return text if text in self._fixed else normalize(text)

    def synthesize(self, text: str) -> Any:
        key = self._key(text)
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
            return self._audio.get(self._key(text))

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
