"""Notaus, Unterbrechen und verlorene Antworten bei der Sprachausgabe (Befunde C1 bis C5, 2026-11-23).

Alles mit Attrappen (kein echtes Audio, keine Modelle, kein Netz): echte Pipeline, echter Speaker, echter Dialog, echter
KillSwitch mit Marker-Datei im tmp-Ordner; nur Stimme, Spracherkennung, Brücke und Mikrofon-Frames sind nachgebaut.
"""
import json
import threading
import time
from types import SimpleNamespace

import numpy as np

from kushim.safety import killswitch
from kushim.safety.killswitch import KillSwitch
from kushim.tasks import TaskRegistry
from kushim.voice import claude_chat as cc
from kushim.voice import wakeconfig
from kushim.voice.audio import FRAME, UtteranceCollector
from kushim.voice.bargein import BargeIn
from kushim.voice.dialog import Dialog, State
from kushim.voice.pipeline import Pipeline
from kushim.voice.talk import TalkLoop
from kushim.voice.talklog import TalkLog, numbers
from kushim.voice.transcript import Transcript
from kushim.voice.tts import Speaker

PCM = np.zeros(16000, dtype=np.int16)
LOUD = (np.ones(FRAME) * 3000).astype(np.int16)
QUIET = np.zeros(FRAME, dtype=np.int16)


class Eng:
    def synthesize(self, text):
        return text


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def collector():
    return UtteranceCollector(silence_ms=160, min_ms=80)          # 2 stille Frames beenden die Äußerung


def stt_says(*texts):
    """Spracherkennung: liefert die Texte der Reihe nach (der letzte bleibt)."""
    queue = list(texts)

    def transcribe(pcm):
        return SimpleNamespace(text=queue.pop(0) if len(queue) > 1 else queue[0])
    return SimpleNamespace(transcribe=transcribe)


class Paced:
    """Mikrofon-Frames mit kleiner Pause; vor Frame `gate_at` wird gewartet, bis `gate` gesetzt ist (z. B. Wiedergabe läuft)."""

    def __init__(self, frames, gate=None, gate_at=0):
        self.frames, self.gate, self.gate_at = frames, gate, gate_at

    def __iter__(self):
        for i, f in enumerate(self.frames):
            if self.gate is not None and i == self.gate_at:
                assert self.gate.wait(timeout=5)
            time.sleep(0.01)
            yield f


def once(*msgs):
    """`announce` der Schleife: liefert die Meldungen je einmal, danach None."""
    queue = list(msgs)
    return lambda: queue.pop(0) if queue else None


class BlockingPlayer:
    """Wiedergabe, die so lange „spielt“, bis sie gestoppt wird (Barge-in oder Notaus rufen `stop`)."""

    def __init__(self):
        self.played, self.started, self._stop = [], threading.Event(), threading.Event()

    def stop(self):
        self._stop.set()

    def __call__(self, wav):
        self.played.append(wav)
        self.started.set()
        self._stop.wait(timeout=0.6)          # ohne Stopp endet der Satz nach kurzer Zeit von selbst


def live_parts(tmp_path, stt, chat=None, play=None, actions=None, notes=None):
    player = play if play is not None else BlockingPlayer()
    stop = getattr(player, "stop", lambda: None)
    dialog = Dialog(stop)
    kill = KillSwitch(tmp_path, [stop] + list(actions or []))
    speaker = Speaker(Eng(), player, kill.poll)           # wie build_live: Marker-Datei zählt sofort
    p = Pipeline(stt, chat or (lambda m: iter(["Erster Satz. Zweiter Satz. Dritter Satz."])), speaker, dialog, kill,
                 notes=notes)
    return p, kill, player


# --- C1: Notaus per Marker-Datei stoppt die laufende Ausgabe vor dem nächsten Satz ---------------------------------------

def test_marker_kill_during_an_answer_stops_before_the_next_sentence_and_actions_run_once(tmp_path):
    ran, played = [], []

    def play(wav):
        played.append(wav)
        if len(played) == 1:
            killswitch.trigger(tmp_path)            # Verknüpfung/Oberfläche: schreibt nur die Marker-Datei

    p, kill, _ = live_parts(tmp_path, stt_says("Erzähl mir was"), play=play, actions=[lambda: ran.append(1)])
    r = p.handle(PCM)
    assert played == ["Erster Satz."]                # nicht erst am Ende der Antwort
    assert kill.fired and ran == [1]
    assert kill.poll() and kill.poll() and ran == [1]                 # weiteres Abfragen: Notaus-Aktionen nur einmal
    assert r.outcome in ("spoken", "interrupted")


def test_speaker_without_pipeline_also_stops_on_the_marker(tmp_path):
    kill, played = KillSwitch(tmp_path, []), []

    def play(wav):
        played.append(wav)
        killswitch.trigger(tmp_path)
    assert Speaker(Eng(), play, kill.poll).say(["Eins.", "Zwei.", "Drei."]) == 1 and played == ["Eins."]


def test_marker_kill_during_an_announcement_stops_before_the_next_sentence(tmp_path):
    played, flushed = [], []

    def play(wav):
        played.append(wav)
        if len(played) == 1:
            killswitch.trigger(tmp_path)

    p, kill, _ = live_parts(tmp_path, stt_says("x"), play=play)
    done = threading.Event()
    say = lambda text: (p.say_text(text), done.set())[0]
    loop = TalkLoop(Paced([QUIET] * 40), p, kill, wake=lambda f: False, barge=BargeIn(), flush=lambda: flushed.append(1),
                    announce=once("Fertig. Alles gebaut. Tests grün."), say=say)
    assert loop.run() == "killed"
    assert done.wait(timeout=5)
    assert played == ["Fertig."] and kill.fired and flushed == []


def test_marker_kill_during_an_announcement_without_barge_also_stops_early(tmp_path):
    played = []

    def play(wav):
        played.append(wav)
        killswitch.trigger(tmp_path)

    p, kill, _ = live_parts(tmp_path, stt_says("x"), play=play)
    loop = TalkLoop([QUIET] * 5, p, kill, wake=lambda f: False, announce=once("Eins. Zwei. Drei."), say=p.say_text)
    assert loop.run() == "killed" and played == ["Eins."]


# --- C2: Meldungen laufen über den Worker: Mikrofon wird weiter gelesen ---------------------------------------------------

def test_spoken_kill_during_an_announcement_is_heard_and_not_flushed(tmp_path):
    notes, flushed, shown = Transcript(), [], []
    p, kill, player = live_parts(tmp_path, stt_says("Notaus"), notes=notes)
    frames = [QUIET, QUIET] + [LOUD] * 4 + [QUIET] * 3 + [QUIET] * 20
    loop = TalkLoop(Paced(frames, player.started, gate_at=2), p, kill, wake=lambda f: False, barge=BargeIn(),
                    new_collector=collector, flush=lambda: flushed.append(1), on_result=lambda r: shown.append(r),
                    announce=once("Ich bin fertig. Hier kommt ein langer Bericht. Und noch mehr."), say=p.say_text)
    assert loop.run() == "killed"
    assert kill.fired and killswitch.is_triggered(tmp_path) and p.dialog.state is State.HALTED
    assert flushed == []                                         # nichts weggeworfen
    assert len(player.played) < 3                                # die Meldung lief nicht zu Ende
    entries = notes.since(0)
    assert [(e["heard"], e["raw"], e["reason"]) for e in entries] == [("", "", "killed")]      # „Notaus erkannt“, ohne Text


def test_barge_in_during_an_announcement_becomes_the_next_question_without_a_du_line_for_the_announcement(tmp_path):
    notes, barges, shown = Transcript(), [], []
    p, kill, player = live_parts(tmp_path, stt_says("Wie spät ist es?"), notes=notes,
                                 chat=lambda m: iter(["Zehn Uhr."]))
    frames = [QUIET, QUIET] + [LOUD] * 4 + [QUIET] * 3 + [QUIET] * 40

    def on_result(r):
        shown.append(r.outcome)
        notes.add(r)                                             # auch wenn eine Meldung im Transkript landet: keine Zeile

    loop = TalkLoop(Paced(frames, player.started, gate_at=2), p, kill, wake=lambda f: False, barge=BargeIn(),
                    new_collector=collector, on_result=on_result, on_barge=lambda *a: barges.append(a),
                    announce=once("Ich bin fertig. Hier kommt ein langer Bericht. Und noch mehr."), say=p.say_text)
    assert loop.run() == "ended"
    assert shown == ["announce_interrupted", "spoken"]
    assert len(barges) == 1 and barges[0][0] is True and barges[0][1] >= 2999 and barges[0][2] is True
    assert "Zehn Uhr." in player.played and "Und noch mehr." not in player.played
    entries = notes.since(0)
    assert [e["heard"] for e in entries] == ["Wie spät ist es?"]                # nur die echte Frage hat eine Zeile „Du“
    assert not kill.fired


def test_wake_word_during_an_announcement_interrupts_it(tmp_path):
    p, kill, player = live_parts(tmp_path, stt_says("Wie spät ist es?"), chat=lambda m: iter(["Zehn Uhr."]))
    n = {"i": 0}

    def wake(frame):
        n["i"] += 1
        return n["i"] == 3                                        # leise genug für Barge-in, aber das Wake Word fällt
    shown = []
    frames = [QUIET] * 2 + [(np.ones(FRAME) * 120).astype(np.int16)] * 3 + [LOUD, LOUD, QUIET, QUIET] + [QUIET] * 30
    loop = TalkLoop(Paced(frames, player.started, gate_at=1), p, kill, wake=wake, barge=BargeIn(),
                    new_collector=collector, on_result=lambda r: shown.append(r.outcome),
                    announce=once("Eins. Zwei. Drei."), say=p.say_text)
    assert loop.run() == "ended"
    assert shown[0] == "announce_interrupted" and "Drei." not in player.played


def test_announcement_that_runs_to_the_end_is_reported_with_its_sentence_count(tmp_path):
    shown = []
    p, kill, _ = live_parts(tmp_path, stt_says("x"), play=lambda wav: None)
    loop = TalkLoop(Paced([QUIET] * 20), p, kill, wake=lambda f: False, barge=BargeIn(),
                    on_result=shown.append, announce=once("Eins. Zwei."), say=p.say_text)
    assert loop.run() == "ended"
    assert [(r.heard, r.outcome, r.spoken, r.entry) for r in shown] == [("", "announced", 2, None)]


# --- C3: "Notaus" als Zwischenruf in try_cancel ----------------------------------------------------------------------------

def test_kill_phrase_as_interjection_fires_halts_and_leaves_no_text(tmp_path):
    for i, text in enumerate(("Notaus", "Notaus, abbrechen", "abbrechen, Notaus")):
        root = tmp_path / str(i)
        notes, tasks = Transcript(), TaskRegistry()
        p, kill, _ = live_parts(root, stt_says(text), notes=notes)
        p.tasks = tasks
        with tasks.running("Claude arbeitet") as tok:
            assert p.try_cancel(PCM) is True
            assert tok.cancelled()
        assert kill.fired and killswitch.is_triggered(root) and p.dialog.state is State.HALTED, text
        assert [(e["heard"], e["raw"], e["reason"]) for e in notes.since(0)] == [("", "", "killed")], text


def test_kill_interjection_while_an_answer_runs_ends_the_loop_as_killed(tmp_path):
    for i, text in enumerate(("Notaus, abbrechen", "abbrechen, Notaus")):
        root = tmp_path / str(i)
        root.mkdir()
        release, notes = threading.Event(), Transcript()

        def slow_chat(messages):
            release.wait(timeout=5)                               # Claude arbeitet noch
            yield "Viel zu spät."

        p, kill, player = live_parts(root, stt_says("Erzähl mir was", text), chat=slow_chat, notes=notes)
        n = {"i": -1}

        def wake(frame):
            n["i"] += 1
            return n["i"] == 0
        frames = [LOUD, LOUD, QUIET, QUIET] + [QUIET] * 3 + [LOUD] * 4 + [QUIET] * 3 + [QUIET] * 10
        loop = TalkLoop(Paced(frames), p, kill, wake=wake, barge=BargeIn(), new_collector=collector,
                        first_collector=collector)
        try:
            assert loop.run() == "killed", text
        finally:
            release.set()
        assert kill.fired and p.dialog.state is State.HALTED
        heard = [(e["heard"], e["reason"]) for e in notes.since(0)]
        assert heard[0][0] == "Erzähl mir was" and heard[-1] == ("", "killed")    # Zwischenruf ohne Text
        assert all(text not in e["heard"] and text not in e["raw"] for e in notes.since(0))


# --- C4: nach dem Unterbrechen kein weiteres /reply, späte Texte als Meldung -----------------------------------------------

class Bridge:
    last_final = True

    def __init__(self, fetch):
        self._fetch, self.fetches, self.sent = fetch, 0, []

    def send(self, text):
        self.sent.append(text)
        return "ok"

    def cancel(self):
        return "ok"

    def pending(self):
        return []

    def available(self):
        return True

    def fetch(self, wait=0.0):
        self.fetches += 1
        return self._fetch(self.fetches)


def test_chat_stops_polling_when_stopped_and_defers_a_text_fetched_after_the_stop():
    stop = threading.Event()

    def fetch(n):
        stop.set()                                                # Unterbrechen, während Claude gerade antwortet
        return "ok", ["Späte Antwort."] if n == 1 else []
    b = Bridge(fetch)
    chat = cc.ClaudeChat(b, TaskRegistry(), clock=Clock())
    assert list(chat([{"role": "user", "content": "Frage"}], stop=stop.is_set)) == []
    assert b.fetches == 1
    assert chat.announcement() == ["Späte Antwort."] and chat.announcement() is None


def test_chat_does_not_fetch_at_all_once_stopped():
    b = Bridge(lambda n: ("ok", []))
    chat = cc.ClaudeChat(b, TaskRegistry(), clock=Clock())
    assert list(chat([{"role": "user", "content": "Frage"}], stop=lambda: True)) == []
    assert b.fetches == 0 and b.sent == ["Frage"] and chat.request_open()     # Anfrage bleibt offen ("abbrechen" erreicht Claude)


def test_after_an_interruption_the_old_turn_never_takes_the_next_answer(tmp_path):
    entered, release = threading.Event(), threading.Event()

    def fetch(n):
        if n == 1:
            entered.set()
            assert release.wait(timeout=5)
            return "ok", ["Alt."]                                 # Antwort auf die unterbrochene Frage
        return "ok", ["Neu."]
    b = Bridge(fetch)
    chat = cc.ClaudeChat(b, TaskRegistry(), clock=Clock())
    p, kill, player = live_parts(tmp_path, stt_says("Frage eins", "Frage zwei"), chat=chat, play=lambda wav: None)
    first = {}
    t = threading.Thread(target=lambda: first.setdefault("r", p.handle(PCM)))
    t.start()
    assert entered.wait(timeout=5)
    p.interrupt()                                                 # Nutzer spricht dazwischen
    t.join(timeout=5)
    assert first["r"].outcome == "interrupted"
    threading.Timer(0.3, release.set).start()
    second = p.handle(PCM)                                        # nächste Frage, während der alte Abruf noch hängt
    assert second.outcome == "spoken" and second.reply == "Neu."
    deadline = time.monotonic() + 5
    late = None
    while late is None and time.monotonic() < deadline:
        late = chat.announcement()
        time.sleep(0.02)
    assert late == ["Alt."]                                       # nachgereicht, nicht verloren
    time.sleep(0.3)
    assert b.fetches == 2                                         # danach holt niemand mehr ab


# --- C5: talk.log nur mit Zahlen und Flags ---------------------------------------------------------------------------------

OLD_TEXT_FIELDS = {"ts", "event", "heard", "reply", "outcome", "detail"}


def test_talklog_result_has_timings_and_spoken_count_but_no_new_text(tmp_path):
    log = TalkLog(tmp_path / "talk.log")
    p, kill, _ = live_parts(tmp_path, stt_says("Erzähl mir was"), play=lambda wav: None,
                            chat=lambda m: iter(["Eins. Zwei."]))
    handle = log.timed(p.handle, metrics=lambda: p.metrics)
    assert handle(PCM).outcome == "spoken"
    entry = json.loads((tmp_path / "talk.log").read_text(encoding="utf-8").splitlines()[-1])
    for k in ("stt_s", "first_text_s", "first_audio_s", "seconds"):
        assert isinstance(entry[k], (int, float)) and not isinstance(entry[k], bool) and entry[k] >= 0
    assert entry["spoken"] == 2
    assert {k for k, v in entry.items() if isinstance(v, str)} == OLD_TEXT_FIELDS


def test_talklog_barge_and_announcement_lines_are_numbers_and_flags_only(tmp_path):
    log = TalkLog(tmp_path / "talk.log")
    log.barge(True, 3000.0, False)
    log.announced("announce_interrupted", 1)
    log.announced("irgendein Text", "drei")
    lines = [json.loads(x) for x in (tmp_path / "talk.log").read_text(encoding="utf-8").splitlines()]
    assert lines[0] == {"ts": lines[0]["ts"], "event": "barge", "speaking": True, "rms": 3000.0, "announcement": False}
    assert lines[1]["outcome"] == "announce_interrupted" and lines[1]["spoken"] == 1
    assert lines[2]["outcome"] == "other" and lines[2]["spoken"] is None          # fremder Text kommt nie ins Protokoll
    assert numbers({"stt_s": 0.5, "spoken": 2, "first_text_s": "Hallo", "heard": "x", "first_audio_s": True}) == \
        {"stt_s": 0.5, "spoken": 2}


def test_metrics_count_only_sentences_that_really_played(tmp_path):
    played = []

    def play(wav):
        played.append(wav)
        killswitch.trigger(tmp_path)
    p, kill, _ = live_parts(tmp_path, stt_says("Erzähl"), play=play, chat=lambda m: iter(["Eins. Zwei. Drei."]))
    p.handle(PCM)
    assert p.metrics["spoken"] == 1 and isinstance(p.metrics["stt_s"], float)


# --- Nebenbefund und optionaler Punkt --------------------------------------------------------------------------------------

def test_bargein_class_defaults_match_the_effective_config_defaults():
    b, s = BargeIn(), wakeconfig.WakeSettings() if hasattr(wakeconfig, "WakeSettings") else None
    assert b.level == 250.0 and b.need == 3                       # 240 ms bei 80-ms-Frames
    if s is not None:
        assert b.level == s.barge_in_level and b.need == round(s.barge_in_ms / 80)


def test_a_chat_without_on_send_counts_as_sent_only_once_it_really_starts(tmp_path):
    notes = Transcript()

    def broken(messages):
        raise RuntimeError("kaputt")
        yield "nie"                                               # noqa: unreachable (Generator)
    p, kill, _ = live_parts(tmp_path, stt_says("Frage"), chat=broken, notes=notes, play=lambda wav: None)
    try:
        p.handle(PCM)
    except RuntimeError:
        pass
    e = notes.since(0)[-1]
    assert e["status"] == "dropped" and e["reason"] == "send_failed" and e["sent_ts"] is None


def test_interruption_before_the_worker_starts_sends_nothing_and_the_line_says_cancelled(tmp_path, monkeypatch):
    sent, notes = [], Transcript()
    original = threading.Thread

    class Delayed(original):                                      # der Erzeuger-Thread kommt erst spät dran
        def run(self):
            time.sleep(0.3)
            super().run()

    def chat(messages):
        sent.append(messages[-1]["content"])                      # stünde hier für bridge.send
        yield "Antwort."
    p, kill, _ = live_parts(tmp_path, stt_says("Frage"), chat=chat, notes=notes, play=lambda wav: None)
    threading.Timer(0.05, p.interrupt).start()                    # Barge-in, bevor der Thread den Chat erreicht
    monkeypatch.setattr(threading, "Thread", Delayed)
    r = p.handle(PCM)
    monkeypatch.setattr(threading, "Thread", original)
    assert r.outcome == "interrupted"
    time.sleep(0.6)                                               # der verspätete Thread ist jetzt gelaufen
    assert sent == []                                             # nichts ging an Claude
    e = notes.since(0)[-1]
    assert e["status"] == "dropped" and e["reason"] == "cancelled"


# --- Nachprüfung (M1, M2, N1, N4) -----------------------------------------------------------------------------------------

def test_the_old_interrupted_turn_never_closes_the_request_of_the_new_turn(tmp_path):
    entered1, release1, entered2, release2 = (threading.Event() for _ in range(4))

    def fetch(n):
        if n == 1:
            entered1.set()
            assert release1.wait(timeout=5)
            return "ok", ["Alt."]                                 # Ergebnis der alten Frage, kommt nach dem Unterbrechen
        entered2.set()
        assert release2.wait(timeout=5)
        return "ok", ["Neu."]
    b, tasks = Bridge(fetch), TaskRegistry()
    chat = cc.ClaudeChat(b, tasks, clock=Clock())
    p, kill, _ = live_parts(tmp_path, stt_says("Frage eins", "Frage zwei"), chat=chat, play=lambda wav: None)
    results = {}
    t1 = threading.Thread(target=lambda: results.setdefault(1, p.handle(PCM)))
    t1.start()
    assert entered1.wait(timeout=5)
    p.interrupt()
    t1.join(timeout=5)
    t2 = threading.Thread(target=lambda: results.setdefault(2, p.handle(PCM)))
    t2.start()                                                    # Runde 2 öffnet ihre Anfrage, wartet auf die Sperre
    deadline = time.monotonic() + 5
    while len(b.sent) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    release1.set()                                                # Abruf 1 liefert jetzt "Alt."
    assert entered2.wait(timeout=5)                               # alte Runde ist fertig, Runde 2 ruft ab
    assert chat.request_open() and tasks.active() == [cc.TASK_NAME]          # "abbrechen" erreicht Claude weiter
    release2.set()
    t2.join(timeout=5)
    assert results[2].reply == "Neu." and not chat.request_open() and tasks.active() == []
    assert chat.announcement() == ["Alt."]


def test_without_barge_the_mic_buffer_is_flushed_after_an_announcement(tmp_path):
    flushed = []
    p, kill, _ = live_parts(tmp_path, stt_says("x"), play=lambda wav: None)
    loop = TalkLoop([QUIET] * 3, p, kill, wake=lambda f: False, flush=lambda: flushed.append(1),
                    announce=once("Eins. Zwei."), say=p.say_text)
    assert loop.run() == "ended" and flushed == [1]


class StepPlayer:
    """Jeder Satz „spielt“, bis er gestoppt wird oder 0,6 s vergehen; zählt die begonnenen Sätze."""

    def __init__(self):
        self.played, self._lock, self._current = [], threading.Lock(), threading.Event()

    def stop(self):
        self._current.set()

    def __call__(self, wav):
        ev = threading.Event()
        with self._lock:
            self._current = ev
            self.played.append(wav)
        ev.wait(timeout=0.6)

    def reached(self, n):
        deadline = time.monotonic() + 5
        while len(self.played) < n and time.monotonic() < deadline:
            time.sleep(0.005)
        return len(self.played) >= n


class Gated:
    def __init__(self, frames, gates):
        self.frames, self.gates = frames, gates

    def __iter__(self):
        for i, f in enumerate(self.frames):
            if i in self.gates:
                assert self.gates[i]()
            time.sleep(0.01)
            yield f


def test_an_announcement_interrupted_only_by_noise_is_replayed_once_and_not_in_a_loop(tmp_path):
    player, shown = StepPlayer(), []
    p, kill, _ = live_parts(tmp_path, stt_says(""), play=player)              # Geräusch: Spracherkennung liefert nichts
    burst = [LOUD] * 4 + [QUIET] * 3
    frames = [QUIET] * 2 + burst + [QUIET] * 2 + burst + [QUIET] * 30
    loop = TalkLoop(Gated(frames, {2: lambda: player.reached(1), 11: lambda: player.reached(2)}), p, kill,
                    wake=lambda f: False, barge=BargeIn(), new_collector=collector,
                    on_result=lambda r: shown.append(r.outcome), announce=once("Eins. Zwei. Drei."), say=p.say_text)
    assert loop.run() == "ended"
    assert shown == ["announce_interrupted", "empty", "announce_interrupted", "empty"]   # einmal nachgereicht, dann Schluss
    assert player.played == ["Eins.", "Eins."]


def test_a_replayed_rest_plays_to_the_end(tmp_path):
    player, shown = StepPlayer(), []
    p, kill, _ = live_parts(tmp_path, stt_says(""), play=player)
    frames = [QUIET] * 2 + [LOUD] * 4 + [QUIET] * 3 + [QUIET] * 300
    loop = TalkLoop(Gated(frames, {2: lambda: player.reached(2)}), p, kill, wake=lambda f: False, barge=BargeIn(),
                    new_collector=collector, on_result=lambda r: shown.append(r.outcome),
                    announce=once("Eins. Zwei. Drei."), say=p.say_text)
    assert loop.run() == "ended"
    assert shown == ["announce_interrupted", "empty", "announced"]
    assert player.played == ["Eins.", "Zwei.", "Zwei.", "Drei."]               # nur der nicht gehörte Rest kommt nochmal


def test_cancel_drops_the_rest_of_an_interrupted_announcement(tmp_path):
    player, shown = StepPlayer(), []
    p, kill, _ = live_parts(tmp_path, stt_says("abbrechen", ""), play=player)
    burst = [LOUD] * 4 + [QUIET] * 3
    frames = [QUIET] * 2 + burst + [QUIET] * 40
    loop = TalkLoop(Gated(frames, {2: lambda: player.reached(1)}), p, kill, wake=lambda f: False, barge=BargeIn(),
                    new_collector=collector, on_result=lambda r: shown.append(r.outcome),
                    announce=once("Eins. Zwei. Drei."), say=p.say_text)
    loop.run()
    assert "Drei." not in player.played and "announced" not in shown


def test_a_chat_without_on_send_never_stays_pending_after_an_early_interruption(tmp_path):
    notes, started, release = Transcript(), threading.Event(), threading.Event()

    def chat(messages):
        started.set()
        release.wait(timeout=5)                                   # noch kein Text
        yield "Zu spät."
    p, kill, _ = live_parts(tmp_path, stt_says("Frage"), chat=chat, notes=notes, play=lambda wav: None)
    threading.Thread(target=lambda: (started.wait(5), p.interrupt())).start()
    try:
        assert p.handle(PCM).outcome == "interrupted"
    finally:
        release.set()
    e = notes.since(0)[-1]
    assert e["status"] == "sent"                                  # der Chat wurde aufgerufen: nicht mehr "pending"
