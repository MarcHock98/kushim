"""Mikrofon-Schwellen zur Laufzeit: LiveTuning (Grenzen, Stufen, reset, Threads), Collector und Unterbrechen lesen sie je Frame,
Sprachbefehl in der Pipeline, talk.log und die API `voice.tuning.*`. Audio-Fixtures sind erzeugte Frames (Sinus mit festem RMS)."""
import json
import threading

import numpy as np
import pytest

from kushim.api.protocol import ApiCore, new_token
from kushim.api.voice_api import register_voice
from kushim.safety import killswitch
from kushim.voice import statefile, wakeconfig
from kushim.voice.audio import FRAME, SAMPLE_RATE, UtteranceCollector
from kushim.voice.bargein import BargeIn
from kushim.voice.talklog import TalkLog
from kushim.voice.tuning import BOUNDS, STEP_FACTOR, LiveTuning, TuningValues, bounds


def tone(rms: float, n: int = 1) -> list[np.ndarray]:
    """n Frames (80 ms) Sinus mit dem gewünschten RMS (Amplitude = RMS * Wurzel 2)."""
    t = np.arange(FRAME) / SAMPLE_RATE
    f = (np.sin(2 * np.pi * 220 * t) * rms * np.sqrt(2)).astype(np.int16)
    return [f.copy() for _ in range(n)]


SILENCE = np.zeros(FRAME, dtype=np.int16)


def rms_of(f) -> float:
    return float(np.sqrt(np.mean(np.asarray(f, dtype=np.float64) ** 2)))


def test_tone_fixture_has_the_requested_level():
    assert rms_of(tone(2000)[0]) == pytest.approx(2000, rel=0.01)
    assert rms_of(tone(300)[0]) == pytest.approx(300, rel=0.01)


class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


FILE = TuningValues(speech_level=200.0, barge_in_level=250.0, barge_in_ms=240, end_silence_seconds=0.9)


# --- LiveTuning: Grenzen ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("key", list(BOUNDS))
def test_set_accepts_the_bounds_and_rejects_one_beyond(key):
    lo, hi = BOUNDS[key]
    t = LiveTuning(FILE)
    t.set(**{key: lo})
    assert getattr(t.values, key) == lo
    t.set(**{key: hi})
    assert getattr(t.values, key) == hi
    eps = 1 if key == "barge_in_ms" else (0.01 if key == "end_silence_seconds" else 1.0)
    for bad in (lo - eps, hi + eps):
        with pytest.raises(ValueError):
            t.set(**{key: bad})
        assert getattr(t.values, key) == hi                      # nichts geändert


def test_set_checks_types_names_and_is_all_or_nothing():
    t = LiveTuning(FILE)
    for bad in ({"speech_level": "300"}, {"speech_level": True}, {"speech_level": float("nan")},
                {"speech_level": float("inf")}, {"unknown": 1}, {"barge_in_ms": 200.5}, {}):
        with pytest.raises(ValueError):
            t.set(**bad)
    with pytest.raises(ValueError):
        t.set(speech_level=300, barge_in_level=5000)              # zweiter Wert falsch: auch der erste bleibt
    assert t.values == FILE and t.version == 0
    with pytest.raises(ValueError):
        t.set(source="cloud", speech_level=300)
    snap = t.set(speech_level=300, barge_in_ms=200.0, end_silence_seconds=2.5)
    assert t.values.barge_in_ms == 200 and isinstance(t.values.barge_in_ms, int)
    assert snap["values"] == {"speech_level": 300.0, "barge_in_level": 250.0, "barge_in_ms": 200, "end_silence_seconds": 2.5}
    assert snap["source"] == "ui" and snap["version"] == 1 and snap["step"] == 0


def test_end_silence_up_to_three_seconds():
    t = LiveTuning(FILE)
    t.set(end_silence_seconds=2.5)
    t.set(end_silence_seconds=3.0)
    with pytest.raises(ValueError):
        t.set(end_silence_seconds=3.01)


def test_file_values_outside_the_live_bounds_stay_as_start():
    settings = wakeconfig.Settings(speech_level=50.0, barge_in_level=5000.0, barge_in_ms=1000, end_silence_seconds=4.0)
    t = LiveTuning.from_settings(settings)
    assert t.values == TuningValues(50.0, 5000.0, 1000, 4.0)
    assert t.snapshot()["file_values"] == t.snapshot()["values"]
    t.reset()
    assert t.values == TuningValues(50.0, 5000.0, 1000, 4.0)      # reset bringt sie unverändert zurück


# --- LiveTuning: Stufen und reset ------------------------------------------------------------------------------------

def test_steps_scale_both_levels_by_1_4_from_the_file_values():
    t = LiveTuning(FILE)
    assert t.step_by(+1) == 1                                     # empfindlicher: Schwellen SINKEN
    assert t.values.speech_level == pytest.approx(200 / STEP_FACTOR, abs=0.1)
    assert t.values.barge_in_level == pytest.approx(250 / STEP_FACTOR, abs=0.1)
    assert t.step_by(+1) == 2
    assert t.values.speech_level == pytest.approx(200 / STEP_FACTOR ** 2, abs=0.1)
    assert t.values.barge_in_level == 150.0                        # 127,6 -> an die Grenze 150 gebunden
    v = t.version
    assert t.step_by(+1) == 2 and t.version == v                   # schon am Ende: keine Änderung
    assert t.step_by(-1) == 1 and t.step_by(-1) == 0
    assert (t.values.speech_level, t.values.barge_in_level) == (200.0, 250.0)
    assert t.step_by(-1) == -1
    assert t.values.speech_level == pytest.approx(280.0) and t.values.barge_in_level == pytest.approx(350.0)
    assert t.step_by(-1) == -2 and t.step_by(-1) == -2
    assert t.values.speech_level == pytest.approx(392.0) and t.values.barge_in_level == pytest.approx(490.0)
    assert (t.values.barge_in_ms, t.values.end_silence_seconds) == (240, 0.9)    # Stufen ändern nur die Pegel
    assert t.snapshot()["source"] == "voice"
    with pytest.raises(ValueError):
        t.step_by(2)


def test_steps_are_bound_to_the_limits_but_never_go_the_wrong_way():
    low = LiveTuning(TuningValues(speech_level=60.0, barge_in_level=120.0, barge_in_ms=240, end_silence_seconds=0.9))
    low.step_by(+1)                                               # unter der Grenze: "empfindlicher" hebt nicht an
    assert (low.values.speech_level, low.values.barge_in_level) == (60.0, 120.0)
    low.step_by(-1)
    low.step_by(-1)                                               # 60*1,4 = 84 liegt in den Grenzen
    assert low.values.speech_level == pytest.approx(84.0)
    high = LiveTuning(TuningValues(speech_level=500.0, barge_in_level=1400.0, barge_in_ms=240, end_silence_seconds=0.9))
    high.step_by(-1)
    assert (high.values.speech_level, high.values.barge_in_level) == (600.0, 1500.0)


def test_reset_returns_to_the_start_values_and_step_zero():
    t = LiveTuning(FILE)
    t.step_by(+1)
    t.set(barge_in_ms=400, end_silence_seconds=2.5)
    snap = t.reset(source="voice")
    assert t.values == FILE and snap["step"] == 0 and snap["source"] == "voice" and snap["values"] == FILE.as_dict()


def test_adopt_file_rebases_file_values():
    t = LiveTuning(FILE)
    t.step_by(+1)
    t.adopt_file(speech_level=142.9, barge_in_level=178.6)
    snap = t.snapshot()
    assert snap["step"] == 0 and snap["file_values"]["speech_level"] == 142.9 == snap["values"]["speech_level"]
    t.reset()
    assert t.values.speech_level == 142.9


def test_observe_keeps_last_rms_and_peak_of_the_last_second():
    clock = Clock()
    t = LiveTuning(FILE, clock=clock)
    assert t.levels() == (0.0, 0.0)
    for r in (100, 900, 300):
        t.observe(r)
        clock.t += 0.08
    assert t.levels() == (300.0, 900.0)
    clock.t += 1.0
    t.observe(50)
    assert t.levels() == (50.0, 50.0)                              # Spitze älter als 1 s fällt weg
    for junk in (float("nan"), -1, "x", None):
        t.observe(junk)
    assert t.levels() == (50.0, 50.0)
    snap = t.snapshot()
    assert snap["rms"] == 50.0 and snap["peak"] == 50.0 and t.version == 0     # Pegel ist keine Änderung


def test_on_change_gets_each_change_and_errors_do_not_matter():
    t = LiveTuning(FILE)
    seen = []
    t.on_change = seen.append
    t.set(speech_level=300)
    t.step_by(+1)
    t.step_by(+1)
    t.step_by(+1)                                                 # an der Grenze: keine Meldung
    t.reset()
    assert [s["version"] for s in seen] == [1, 2, 3, 4]

    def boom(_):
        raise RuntimeError("Protokoll kaputt")
    t.on_change = boom
    t.set(speech_level=250)
    assert t.values.speech_level == 250.0


def test_concurrent_access_keeps_values_consistent():
    t = LiveTuning(FILE)
    errors = []
    stop = threading.Event()
    lo_s, hi_s = BOUNDS["speech_level"]

    def writer(i):
        try:
            for n in range(300):
                if n % 3 == 0:
                    t.step_by(1 if (n + i) % 2 else -1, source="voice")
                elif n % 3 == 1:
                    t.set(speech_level=100 + (n % 400), barge_in_ms=160 + (n % 240))
                else:
                    t.reset()
        except Exception as e:                                    # noqa: BLE001
            errors.append(e)

    def reader():
        while not stop.is_set():
            v = t.values
            snap = t.snapshot()
            if not (lo_s <= v.speech_level <= hi_s or v.speech_level == FILE.speech_level):
                errors.append(("speech", v))
            if not -2 <= snap["step"] <= 2:
                errors.append(("step", snap))
            t.observe(123.0)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
    readers = [threading.Thread(target=reader) for _ in range(2)]
    for th in readers + threads:
        th.start()
    for th in threads:
        th.join()
    stop.set()
    for th in readers:
        th.join()
    assert errors == []
    # jede Änderung zählt genau einmal: 4 Threads je 200 set/reset plus die Stufen, die sich wirklich bewegt haben
    assert t.version >= 4 * 200


# --- Collector und Unterbrechen lesen die Werte je Frame ---------------------------------------------------------------

def test_collector_threshold_change_mid_stream_applies_from_the_next_frame():
    t = LiveTuning(FILE)                                          # speech_level 200
    c = UtteranceCollector(wait_ms=5000, silence_ms=800, energy_threshold=999.0, tuning=t)
    assert c.threshold == 200.0                                   # tuning hat Vorrang vor energy_threshold
    c.feed(tone(150)[0])
    assert not c.heard_speech
    t.step_by(+1)                                                 # 200 -> 142,9
    c.feed(tone(150)[0])
    assert c.heard_speech                                         # derselbe Pegel zählt ab dem nächsten Frame


def test_collector_end_silence_change_mid_utterance():
    t = LiveTuning(FILE)                                          # 0,9 s = 11 Frames Stille
    c = UtteranceCollector(wait_ms=5000, min_ms=80, tuning=t)
    for f in tone(1000, 5):
        assert not c.feed(f)
    for _ in range(5):
        assert not c.feed(SILENCE)
    t.set(end_silence_seconds=2.5)                                # Denkpause länger erlaubt: 31 Frames
    for _ in range(20):
        assert not c.feed(SILENCE)
    t.set(end_silence_seconds=0.6)                                # jetzt kürzer: schon genug Stille gesammelt
    assert c.feed(SILENCE)


def test_collector_without_tuning_is_unchanged():
    c = UtteranceCollector(energy_threshold=500.0, silence_ms=800)
    assert c.threshold == 500.0 and c.silence_frames == 10
    c.feed(tone(400)[0])
    assert not c.heard_speech


def test_bargein_threshold_and_duration_change_mid_stream():
    t = LiveTuning(FILE)                                          # 250 über 240 ms = 3 Frames
    b = BargeIn(level=9999, min_ms=2000, tuning=t)
    assert b.level == 250.0 and b.need == 3
    assert not b.feed(tone(300)[0])
    t.set(barge_in_level=400)                                     # strenger: 300 zählt ab dem nächsten Frame nicht mehr
    assert not b.feed(tone(300)[0])
    assert b._run == 0
    t.set(barge_in_level=150, barge_in_ms=160)                    # 2 Frames reichen
    assert not b.feed(tone(300)[0])
    assert b.feed(tone(300)[0])
    t.set(barge_in_ms=400)
    b.feed(SILENCE)
    assert b.need == 5 and len(b.recent()) <= 5 + b.preroll_frames


def test_bargein_keeps_the_echo_factor_with_tuning():
    t = LiveTuning(FILE)
    b = BargeIn(echo_guard=True, echo_factor=2.0, echo_ignore_ms=0, tuning=t)
    t.set(barge_in_level=300)
    b.feed(SILENCE, speaking=True)
    assert b.threshold(speaking=True) == 600.0 and b.threshold(speaking=False) == 300.0


def test_kill_fixture_at_the_strictest_bounds_still_triggers():
    """Notaus-Fixture: an den strengsten Live-Grenzen (speech 600, barge 1500 über 400 ms) lösen normal laut gesprochene
    Frames (RMS 2000, 560 ms) Collector und Unterbrechen noch aus; ein gesprochenes „Notaus“ kommt also an."""
    t = LiveTuning(FILE)
    t.set(speech_level=600, barge_in_level=1500, barge_in_ms=400, end_silence_seconds=3.0)
    speech = tone(2000, 7)                                        # 7 x 80 ms = 560 ms
    b = BargeIn(tuning=t)
    fired = [b.feed(f) for f in speech]
    assert any(fired) and fired.index(True) == 4                  # nach 400 ms (5 Frames)
    c = UtteranceCollector(wait_ms=5000, tuning=t)
    for f in speech:
        assert not c.feed(f)
    assert c.heard_speech
    done = [c.feed(SILENCE) for _ in range(40)]
    assert any(done) and done.index(True) == 37                   # 3,0 s Stille = 38 Frames
    assert len(c.audio()) >= 7 * FRAME


def test_kill_fixture_survives_the_strictest_voice_step():
    """Auch „weniger empfindlich“ bis Stufe -2 (aus den Standardwerten) lässt den gesprochenen Notaus durch."""
    t = LiveTuning(FILE)
    t.set(barge_in_ms=400)
    t.step_by(-1)
    t.step_by(-1)
    b = BargeIn(tuning=t)
    assert any(b.feed(f) for f in tone(2000, 7))
    c = UtteranceCollector(wait_ms=5000, tuning=t)
    for f in tone(2000, 7):
        c.feed(f)
    assert c.heard_speech


# --- Sprachbefehl in der Pipeline ----------------------------------------------------------------------------------------

from types import SimpleNamespace                                  # noqa: E402

from kushim.safety.killswitch import KillSwitch                    # noqa: E402
from kushim.voice.dialog import Dialog, State                      # noqa: E402
from kushim.voice.pipeline import Pipeline, is_tuning_phrase, tuning_reply   # noqa: E402
from kushim.voice.transcript import Transcript                     # noqa: E402
from kushim.voice.tts import Speaker                               # noqa: E402

PCM = np.zeros(16000, dtype=np.int16)

MORE = ["Mikrofon empfindlicher", "Mach das Mikrofon empfindlicher", "Mikrofon empfindlicher bitte", "Pegel empfindlicher",
        "Mikro etwas empfindlicher.", "Empfindlicher bitte", "empfindlicher", "Stell das Mikrofon empfindlicher",
        "Mikrofon sensibler"]
LESS = ["Mikrofon weniger empfindlich", "Mikrofon unempfindlicher", "Mikrofon nicht so empfindlich", "Pegel weniger empfindlich",
        "Weniger empfindlich bitte", "Mach das Mikrofon unempfindlicher", "Empfindlichkeit weniger"]
NORMAL = ["Mikrofon normal", "Mikrofon zurücksetzen", "Pegel zurücksetzen", "Empfindlichkeit normal", "Mikrofon zurück auf normal",
          "Mikrofon auf Standard"]
NEVER = ["mach lauter", "Mach leiser", "Mikrofon lauter", "Mikrofon leiser", "Pegel von Claude", "Claude, Mikrofon empfindlicher",
         "Sei nicht so empfindlich", "Du bist empfindlicher als ich", "Wie empfindlich ist das Mikrofon",
         "Das Mikrofon ist kaputt", "Mikrofon nicht zurücksetzen", "Mikrofon nicht empfindlicher", "zurücksetzen", "normal",
         "Kannst du bitte das Mikrofon etwas empfindlicher machen", "Mikrofon empfindlicher oder weniger empfindlich",
         "Mikrofon empfindlicher und normal", "Ist das Mikrofon normal?", "Pegel", "Erklär mir den Pegel des Rheins",
         "Wie funktioniert ein Mikrofon", ""]


@pytest.mark.parametrize("text", MORE)
def test_tuning_phrase_more_sensitive(text):
    assert is_tuning_phrase(text) == 1


@pytest.mark.parametrize("text", LESS)
def test_tuning_phrase_less_sensitive(text):
    assert is_tuning_phrase(text) == -1


@pytest.mark.parametrize("text", NORMAL)
def test_tuning_phrase_normal(text):
    assert is_tuning_phrase(text) == 0


@pytest.mark.parametrize("text", NEVER)
def test_tuning_phrase_does_not_trigger(text):
    assert is_tuning_phrase(text) is None


class FakeSTT:
    def __init__(self, text):
        self.text = text

    def transcribe(self, pcm):
        return SimpleNamespace(text=self.text)


class Eng:
    def synthesize(self, t):
        return t


def build(tmp_path, text, tuning):
    played, called = [], []
    dialog = Dialog(lambda: None)
    kill = KillSwitch(tmp_path, [lambda: None])
    spk = Speaker(Eng(), played.append, lambda: kill.fired)
    notes = Transcript()
    p = Pipeline(FakeSTT(text), lambda m: called.append(m) or iter(["Ok."]), spk, dialog, kill,
                 wake_names=("hey kushim", "kushim"), notes=notes, tuning=tuning)
    return p, played, called, kill, notes


def test_pipeline_voice_command_lowers_thresholds_locally(tmp_path):
    t = LiveTuning(FILE)
    p, played, called, _, notes = build(tmp_path, "Hey Kushim, Mikrofon empfindlicher", t)
    r = p.handle(PCM)
    assert r.outcome == "command" and not called                  # nichts an Claude
    assert t.values.speech_level < FILE.speech_level and t.values.barge_in_level < FILE.barge_in_level   # empfindlicher SENKT
    assert t.snapshot()["source"] == "voice" and t.snapshot()["step"] == 1
    assert played == ["Mikrofon empfindlicher, Stufe plus eins.", "„Mikrofon normal“ setzt zurück."]
    assert r.reply == tuning_reply(1, 1, True)
    item = notes.since(0)[0]
    assert item["status"] == "dropped" and item["reason"] == "command"
    assert not (tmp_path / "wakewords.toml").exists()             # per Stimme wird nie gespeichert


def test_pipeline_voice_command_less_normal_and_edges(tmp_path):
    t = LiveTuning(FILE)
    p, played, called, _, _ = build(tmp_path, "Mikrofon weniger empfindlich", t)
    p.handle(PCM)
    assert t.snapshot()["step"] == -1 and t.values.speech_level > FILE.speech_level
    assert played[-2:] == ["Mikrofon weniger empfindlich, Stufe minus eins.", "„Mikrofon normal“ setzt zurück."]
    p.handle(PCM)
    played.clear()
    p.handle(PCM)                                                 # schon -2: bleibt, ehrliche Ansage
    assert t.snapshot()["step"] == -2
    assert played == ["Mikrofon ist schon am unempfindlichsten, Stufe minus zwei.", "„Mikrofon normal“ setzt zurück."]
    p.stt = FakeSTT("Mikrofon normal")
    played.clear()
    r = p.handle(PCM)
    assert r.outcome == "command" and t.values == FILE and played == ["Mikrofon normal, Stufe null."]
    assert not called


def test_pipeline_kill_phrase_wins_over_tuning(tmp_path):
    t = LiveTuning(FILE)
    p, played, called, kill, _ = build(tmp_path, "Notaus Mikrofon empfindlicher", t)
    r = p.handle(PCM)
    assert r.outcome == "killed" and kill.fired and t.version == 0 and not called
    assert p.dialog.state is State.HALTED


def test_pipeline_non_tuning_sentences_go_on_normally(tmp_path):
    t = LiveTuning(FILE)
    for text in ("mach lauter", "Pegel von Claude"):
        p, played, called, _, _ = build(tmp_path, text, t)
        r = p.handle(PCM)
        assert r.outcome == "spoken" and called and t.version == 0, text


def test_pipeline_without_tuning_does_not_intercept(tmp_path):
    p, played, called, _, _ = build(tmp_path, "Mikrofon empfindlicher", None)
    assert p.handle(PCM).outcome == "spoken" and called


def test_pipeline_cancel_and_end_come_first(tmp_path):
    t = LiveTuning(FILE)
    p, _, _, _, _ = build(tmp_path, "das wars", t)
    assert p.handle(PCM).outcome == "end_conversation"
    p, _, _, _, _ = build(tmp_path, "Abbrechen Mikrofon empfindlicher", t)
    assert p.handle(PCM).outcome == "cancelled" and t.version == 0


# --- talk.log ----------------------------------------------------------------------------------------------------------

def test_talklog_tuning_line_has_only_source_step_and_numbers(tmp_path):
    log = TalkLog(tmp_path / "talk.log", clock=lambda: 0.0)
    t = LiveTuning(FILE)
    t.on_change = log.tuning
    t.step_by(+1, source="voice")
    log.tuning({"source": "<b>", "step": True, "values": {"speech_level": "hoch", "barge_in_level": 1}, "text": "geheim"})
    lines = [json.loads(x) for x in (tmp_path / "talk.log").read_text(encoding="utf-8").splitlines()]
    assert lines[0] == {"ts": lines[0]["ts"], "event": "tuning", "source": "voice", "step": 1, "speech_level": 142.9,
                        "barge_in_level": 178.6, "barge_in_ms": 240, "end_silence_seconds": 0.9}
    assert lines[1]["source"] == "other" and lines[1]["step"] is None and lines[1]["speech_level"] is None
    assert lines[1]["barge_in_level"] == 1 and "text" not in lines[1]


# --- API voice.tuning.* -------------------------------------------------------------------------------------------------

def make_api(tmp_path, tuning=None, alive=True, audit=None):
    if alive:
        statefile.StatePublisher(tmp_path).phase("idle", 0.1)    # Lebenszeichen des Sprachprozesses
    token = new_token()
    core = ApiCore(token)
    register_voice(core, tmp_path, tuning=tuning, audit=audit)

    def call(t, **kw):
        return json.loads(core.handle(json.dumps({"token": token, "type": t, **kw})))
    call.core, call.token = core, token
    return call


KEYS_GET = {"ok", "active", "values", "file_values", "bounds", "step", "rms", "peak", "last_source", "version"}


def test_tuning_get_live(tmp_path):
    t = LiveTuning(FILE)
    t.observe(321.0)
    api = make_api(tmp_path, t)
    r = api("voice.tuning.get")
    assert set(r) == KEYS_GET and r["ok"] and r["active"] is True
    assert r["values"] == r["file_values"] == FILE.as_dict()
    assert r["bounds"] == bounds() == {"speech_level": {"min": 80.0, "max": 600.0}, "barge_in_level": {"min": 150.0, "max": 1500.0},
                                       "barge_in_ms": {"min": 160, "max": 400}, "end_silence_seconds": {"min": 0.6, "max": 3.0},
                                       "step": {"min": -2, "max": 2}}
    assert (r["step"], r["rms"], r["peak"], r["last_source"], r["version"]) == (0, 321.0, 321.0, "file", 0)


def test_tuning_get_without_voice_process_is_inactive(tmp_path):
    api = make_api(tmp_path, None)                                # z. B. `kushim serve`
    r = api("voice.tuning.get")
    assert set(r) == KEYS_GET
    d = wakeconfig.Settings()
    assert r["active"] is False and r["values"] == {"speech_level": d.speech_level, "barge_in_level": d.barge_in_level,
                                                    "barge_in_ms": d.barge_in_ms, "end_silence_seconds": d.end_silence_seconds}
    assert (r["step"], r["rms"], r["peak"], r["last_source"]) == (0, 0.0, 0.0, "file")
    dead = make_api(tmp_path / "x", LiveTuning(FILE), alive=False)    # Objekt da, aber kein Lebenszeichen
    assert dead("voice.tuning.get")["active"] is False
    (tmp_path / "wakewords.toml").write_text("[settings\n", encoding="utf-8")
    broken = api("voice.tuning.get")
    assert broken["active"] is False and broken["values"] is None and broken["file_values"] is None


def test_tuning_set_partial_values(tmp_path):
    t = LiveTuning(FILE)
    api = make_api(tmp_path, t)
    r = api("voice.tuning.set", values={"end_silence_seconds": 2.5}, confirm=True)
    assert set(r) == KEYS_GET and r["values"]["end_silence_seconds"] == 2.5 and r["values"]["speech_level"] == 200.0
    assert r["last_source"] == "ui" and r["version"] == 1 and t.values.end_silence_seconds == 2.5
    r = api("voice.tuning.set", values={"speech_level": 120, "barge_in_level": 300, "barge_in_ms": 200}, confirm=True)
    assert r["values"] == {"speech_level": 120.0, "barge_in_level": 300.0, "barge_in_ms": 200, "end_silence_seconds": 2.5}
    assert r["file_values"] == FILE.as_dict()
    assert not (tmp_path / "wakewords.toml").exists()             # set speichert nie


def test_tuning_set_invalid_and_bad_request(tmp_path):
    t = LiveTuning(FILE)
    api = make_api(tmp_path, t)
    for vals in ({"speech_level": 79}, {"speech_level": 601}, {"barge_in_level": 149}, {"barge_in_level": 1501},
                 {"barge_in_ms": 159}, {"barge_in_ms": 401}, {"end_silence_seconds": 0.5}, {"end_silence_seconds": 3.1},
                 {"barge_in_ms": 200.5}, {"speech_level": 300, "barge_in_level": 2000}):
        assert api("voice.tuning.set", values=vals, confirm=True) == {"ok": False, "error": "invalid"}, vals
    for vals in ({}, None, [1], "x", {"speech_level": "300"}, {"speech_level": True}, {"speech_level": None},
                 {"step": 1}, {"echo_factor": 2}):
        assert api("voice.tuning.set", values=vals, confirm=True) == {"ok": False, "error": "bad_request"}, vals
    assert api("voice.tuning.set", confirm=True) == {"ok": False, "error": "bad_request"}
    nan = '{"token": "%s", "type": "voice.tuning.set", "values": {"speech_level": NaN}, "confirm": true}'
    assert json.loads(api.core.handle(nan % api.token)) == {"ok": False, "error": "bad_request"}
    assert t.values == FILE and t.version == 0


def test_tuning_writes_need_confirm(tmp_path):
    t = LiveTuning(FILE)
    api = make_api(tmp_path, t)
    for unsure in ({}, {"confirm": "true"}, {"confirm": 1}, {"confirm": False}):
        assert api("voice.tuning.set", values={"speech_level": 300}, **unsure) == {"ok": False, "error": "confirm_required"}
        assert api("voice.tuning.reset", **unsure) == {"ok": False, "error": "confirm_required"}
        assert api("voice.tuning.save", **unsure) == {"ok": False, "error": "confirm_required"}
    assert t.version == 0 and not (tmp_path / "wakewords.toml").exists()


def test_tuning_writes_are_blocked_by_the_kill_switch(tmp_path):
    t = LiveTuning(FILE)
    api = make_api(tmp_path, t)
    killswitch.trigger(tmp_path)
    assert api("voice.tuning.set", values={"speech_level": 300}, confirm=True) == {"ok": False, "error": "kill"}
    assert api("voice.tuning.reset", confirm=True) == {"ok": False, "error": "kill"}
    assert api("voice.tuning.save", confirm=True) == {"ok": False, "error": "kill"}
    assert api("voice.tuning.get")["ok"] is True                  # lesen geht weiter
    assert t.version == 0 and not (tmp_path / "wakewords.toml").exists()


def test_tuning_writes_without_voice_process_are_unavailable(tmp_path):
    api = make_api(tmp_path, None)
    assert api("voice.tuning.set", values={"speech_level": 300}, confirm=True) == {"ok": False, "error": "unavailable"}
    assert api("voice.tuning.reset", confirm=True) == {"ok": False, "error": "unavailable"}
    assert api("voice.tuning.save", confirm=True) == {"ok": False, "error": "unavailable"}
    t = LiveTuning(FILE)
    dead = make_api(tmp_path / "x", t, alive=False)
    assert dead("voice.tuning.set", values={"speech_level": 300}, confirm=True) == {"ok": False, "error": "unavailable"}
    assert t.version == 0 and not (tmp_path / "wakewords.toml").exists()


def test_tuning_reset_api(tmp_path):
    t = LiveTuning(FILE)
    api = make_api(tmp_path, t)
    t.step_by(+1)
    r = api("voice.tuning.reset", confirm=True)
    assert r["values"] == FILE.as_dict() and r["step"] == 0 and r["last_source"] == "ui"


def test_tuning_save_writes_with_backup_and_audit_without_values(tmp_path):
    seen = []
    original = wakeconfig.dumps(wakeconfig.WakeConfig(wakeconfig.Settings(speech_level=200.0, cooldown_seconds=3.0)))
    (tmp_path / "wakewords.toml").write_text(original, encoding="utf-8")
    t = LiveTuning.from_settings(wakeconfig.load(tmp_path).settings)
    api = make_api(tmp_path, t, audit=lambda event, detail: seen.append((event, detail)))
    t.step_by(+1)
    api("voice.tuning.set", values={"end_silence_seconds": 2.5, "barge_in_ms": 320}, confirm=True)
    r = api("voice.tuning.save", confirm=True)
    assert r["ok"] and r["backup"] is True and set(r) == KEYS_GET | {"backup"}
    assert (tmp_path / "wakewords.toml.bak").read_text(encoding="utf-8") == original      # Kopie VOR dem Schreiben
    s = wakeconfig.load(tmp_path).settings
    assert (s.speech_level, s.barge_in_level, s.barge_in_ms, s.end_silence_seconds) == (142.9, 178.6, 320, 2.5)
    assert s.cooldown_seconds == 3.0                              # alles andere bleibt
    assert r["file_values"] == r["values"] and r["step"] == 0     # gespeichert: neue Dateiwerte
    assert seen == [("voice_tuning_saved", "api")]                # nie Werte oder Pfade im Audit
    assert not list(tmp_path.glob("*.tmp"))
    t.step_by(-1)
    api("voice.tuning.reset", confirm=True)
    assert t.values.speech_level == 142.9                         # reset geht jetzt auf die gespeicherten Werte


def test_tuning_save_without_own_file_needs_no_backup_and_broken_file_is_refused(tmp_path):
    t = LiveTuning(FILE)
    api = make_api(tmp_path, t)
    r = api("voice.tuning.save", confirm=True)
    assert r["ok"] and r["backup"] is False and (tmp_path / "wakewords.toml").is_file()
    assert not (tmp_path / "wakewords.toml.bak").exists()
    (tmp_path / "wakewords.toml").write_text("[settings\n", encoding="utf-8")
    assert api("voice.tuning.save", confirm=True) == {"ok": False, "error": "broken_file"}
    assert (tmp_path / "wakewords.toml").read_text(encoding="utf-8") == "[settings\n"
    assert not (tmp_path / "wakewords.toml.bak").exists()


def test_tuning_save_audit_error_does_not_undo(tmp_path):
    def boom(event, detail):
        raise RuntimeError("Audit kaputt")
    t = LiveTuning(FILE)
    api = make_api(tmp_path, t, audit=boom)
    t.set(speech_level=333)
    assert api("voice.tuning.save", confirm=True)["ok"]
    assert wakeconfig.load(tmp_path).settings.speech_level == 333.0


def test_level_apply_sets_live_when_talk_runs(tmp_path):
    t = LiveTuning(FILE)
    api = make_api(tmp_path, t)
    t.step_by(+1)
    r = api("voice.level_apply", speech_level=320, barge_in_level=450, confirm=True)
    assert r == {"ok": True, "speech_level": 320.0, "barge_in_level": 450.0, "restart_needed": False}
    assert (t.values.speech_level, t.values.barge_in_level) == (320.0, 450.0)
    assert t.snapshot()["file_values"]["speech_level"] == 320.0 and t.snapshot()["step"] == 0
    wide = api("voice.level_apply", speech_level=2000, barge_in_level=5000, confirm=True)     # Dateigrenzen, nicht Live
    assert wide["restart_needed"] is False and t.values.barge_in_level == 5000.0
    (tmp_path / "x").mkdir()
    off = make_api(tmp_path / "x", None)
    assert off("voice.level_apply", speech_level=300, barge_in_level=400, confirm=True)["restart_needed"] is True


def test_tuning_types_need_the_token(tmp_path):
    api = make_api(tmp_path, LiveTuning(FILE))
    for t in ("voice.tuning.get", "voice.tuning.set", "voice.tuning.reset", "voice.tuning.save"):
        assert json.loads(api.core.handle(json.dumps({"type": t, "confirm": True}))) == {"ok": False, "error": "unauthorized"}
