"""E3b: Pegeltest im Sprachprozess (voice.level_*), Wake-Word-Zähler in voice-state.json, Namen vom Detektor."""
import json
import threading
import time

import numpy as np
import pytest

from kushim.api.protocol import ApiCore, new_token
from kushim.api.voice_api import register_voice
from kushim.safety import killswitch
from kushim.voice import levels, statefile, wakeconfig
from kushim.voice.audio import FRAME
from kushim.voice.levels import QUIET_FRAMES, SPEECH_FRAMES, LevelTest

RNG = np.random.default_rng(7)
QUIET = [RNG.normal(0, 20, FRAME).astype(np.int16) for _ in range(QUIET_FRAMES)]
SPEECH = [RNG.normal(0, a, FRAME).astype(np.int16) for a in np.linspace(500, 2500, SPEECH_FRAMES)]
SILENT = np.zeros(FRAME, dtype=np.int16)


class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


# --- LevelTest (läuft im Sprachprozess) --------------------------------------------------------------------------

def test_level_test_measures_quiet_then_speech_and_suggests():
    lt = LevelTest(clock=Clock())
    assert lt.result() == {"state": "idle", "seconds_left": 0.0, "suggestion": None}
    lt.feed(SPEECH[0])                                                       # ohne Start zählt nichts
    lt.start()
    assert lt.result() == {"state": "quiet", "seconds_left": 3.0, "suggestion": None}
    for f in QUIET[:10]:
        lt.feed(f, "idle")
    assert lt.result()["state"] == "quiet" and lt.result()["seconds_left"] == pytest.approx(2.2)
    for f in QUIET[10:]:
        lt.feed(f, "listening")
    assert lt.result() == {"state": "speak", "seconds_left": 6.0, "suggestion": None}
    for f in SPEECH:
        lt.feed(f, "idle")
    r = lt.result()
    assert r["state"] == "done" and r["seconds_left"] == 0.0
    expected = levels.suggest(levels.frame_rms(QUIET), levels.frame_rms(SPEECH))
    assert r["suggestion"] == {"speech_level": float(expected.speech_level), "barge_in_level": float(expected.barge_in_level)}
    s = wakeconfig.Settings(speech_level=r["suggestion"]["speech_level"], barge_in_level=r["suggestion"]["barge_in_level"])
    wakeconfig.validate(wakeconfig.WakeConfig(s), None)                      # Vorschlag liegt in den erlaubten Grenzen
    assert set(r) == {"state", "seconds_left", "suggestion"}


def test_level_test_keeps_only_numbers_never_audio():
    lt = LevelTest(clock=Clock())
    lt.start()
    for f in QUIET:
        lt.feed(f)
    for f in SPEECH[:5]:
        lt.feed(f)
    assert all(isinstance(x, float) for x in lt._noise + lt._speech)
    for f in SPEECH[5:]:
        lt.feed(f)
    assert lt._noise == [] and lt._speech == []                              # nach dem Ergebnis auch keine Pegel mehr


def test_frames_while_kushim_speaks_or_thinks_do_not_count():
    lt = LevelTest(clock=Clock())
    lt.start()
    for phase in ("speaking", "thinking", "halted", "asking"):
        lt.feed(QUIET[0], phase)
    assert lt.result()["seconds_left"] == 3.0


def test_too_little_speech_ends_without_suggestion():
    lt = LevelTest(clock=Clock())
    lt.start()
    for f in QUIET + [SILENT] * SPEECH_FRAMES:
        lt.feed(f)
    assert lt.result() == {"state": "done", "seconds_left": 0.0, "suggestion": None}


def test_level_test_times_out_and_can_restart():
    clock = Clock()
    lt = LevelTest(clock=clock)
    lt.start()
    lt.feed(QUIET[0])
    clock.t += levels.TEST_TIMEOUT + 1
    assert lt.result() == {"state": "done", "seconds_left": 0.0, "suggestion": None}
    lt.start()
    assert lt.result()["state"] == "quiet" and lt.result()["seconds_left"] == 3.0


def test_level_test_feed_and_result_from_different_threads():
    lt = LevelTest(clock=Clock())
    lt.start()
    seen = []

    def loop():
        for f in QUIET + SPEECH:
            lt.feed(f)
    th = threading.Thread(target=loop)
    th.start()
    while th.is_alive():
        seen.append(lt.result()["state"])
    th.join()
    assert lt.result()["state"] == "done" and set(seen) <= {"quiet", "speak", "done"}


# --- voice.level_test / level_result / level_apply ------------------------------------------------------------------

def make_api(tmp_path, level_test=None, alive=True):
    if alive:
        statefile.StatePublisher(tmp_path).phase("idle", 0.1)               # Lebenszeichen des Sprachprozesses
    token = new_token()
    core = ApiCore(token)
    register_voice(core, tmp_path, level_test=level_test)

    def call(t, **kw):
        return json.loads(core.handle(json.dumps({"token": token, "type": t, **kw})))
    call.core, call.token = core, token
    return call


def test_level_api_happy_path(tmp_path):
    lt = LevelTest(clock=Clock())
    api = make_api(tmp_path, lt)
    assert api("voice.level_result") == {"ok": True, "state": "idle", "seconds_left": 0.0, "suggestion": None}
    assert api("voice.level_test", confirm=True) == {"ok": True}
    assert api("voice.level_result")["state"] == "quiet"
    for f in QUIET + SPEECH:
        lt.feed(f)
    r = api("voice.level_result")
    assert r["ok"] and r["state"] == "done" and set(r["suggestion"]) == {"speech_level", "barge_in_level"}
    applied = api("voice.level_apply", confirm=True, **r["suggestion"])
    assert applied == {"ok": True, **r["suggestion"], "restart_needed": True}
    s = wakeconfig.load(tmp_path).settings
    assert (s.speech_level, s.barge_in_level) == (r["suggestion"]["speech_level"], r["suggestion"]["barge_in_level"])


def test_level_test_without_voice_process_is_unavailable(tmp_path):
    api = make_api(tmp_path, None)                                           # z. B. `kushim serve`
    assert api("voice.level_result") == {"ok": True, "state": "unavailable", "seconds_left": 0.0, "suggestion": None}
    assert api("voice.level_test", confirm=True) == {"ok": False, "error": "unavailable"}
    lt = LevelTest()
    dead = make_api(tmp_path / "x", lt, alive=False)                         # Sprachdienst ohne Lebenszeichen
    assert dead("voice.level_result")["state"] == "unavailable"
    assert dead("voice.level_test", confirm=True) == {"ok": False, "error": "unavailable"}
    assert lt.result()["state"] == "idle"


def test_level_test_needs_confirm_and_is_blocked_by_the_kill_switch(tmp_path):
    lt = LevelTest()
    api = make_api(tmp_path, lt)
    for unsure in ({}, {"confirm": "true"}, {"confirm": 1}):
        assert api("voice.level_test", **unsure) == {"ok": False, "error": "confirm_required"}
    killswitch.trigger(tmp_path)
    assert api("voice.level_test", confirm=True) == {"ok": False, "error": "kill"}
    assert lt.result()["state"] == "idle"
    assert api("voice.level_apply", speech_level=300, barge_in_level=400, confirm=True) == {"ok": False, "error": "kill"}
    assert not (tmp_path / "wakewords.toml").exists()


def test_level_apply_limits_and_confirm(tmp_path):
    api = make_api(tmp_path, None)                                           # Übernehmen geht auch ohne Sprachprozess
    for kw in ({"speech_level": 10, "barge_in_level": 400}, {"speech_level": 300, "barge_in_level": 50},
               {"speech_level": 6000, "barge_in_level": 400}, {"speech_level": 300, "barge_in_level": 30000}):
        assert api("voice.level_apply", confirm=True, **kw) == {"ok": False, "error": "invalid"}, kw
    for kw in ({"speech_level": "300", "barge_in_level": 400}, {"speech_level": True, "barge_in_level": 400},
               {"barge_in_level": 400}, {"speech_level": None, "barge_in_level": 400}, {"speech_level": [1], "barge_in_level": 2}):
        assert api("voice.level_apply", confirm=True, **kw) == {"ok": False, "error": "bad_request"}, kw
    nan = '{"token": "%s", "type": "voice.level_apply", "speech_level": NaN, "barge_in_level": Infinity, "confirm": true}'
    assert json.loads(api.core.handle(nan % api.token)) == {"ok": False, "error": "bad_request"}
    assert api("voice.level_apply", speech_level=300, barge_in_level=400) == {"ok": False, "error": "confirm_required"}
    assert not (tmp_path / "wakewords.toml").exists()
    assert api("voice.level_apply", speech_level=300, barge_in_level=400.5, confirm=True)["restart_needed"] is True
    (tmp_path / "wakewords.toml").write_text("[settings\n", encoding="utf-8")
    assert api("voice.level_apply", speech_level=300, barge_in_level=400, confirm=True) == {"ok": False, "error": "broken_file"}


def test_voice_types_need_the_token(tmp_path):
    api = make_api(tmp_path, LevelTest())
    for t in ("voice.level_test", "voice.level_result", "voice.level_apply"):
        assert json.loads(api.core.handle(json.dumps({"type": t, "confirm": True}))) == {"ok": False, "error": "unauthorized"}


# --- Wake-Word-Zähler in voice-state.json --------------------------------------------------------------------------

def test_publisher_counts_wake_words_and_keeps_only_the_name(tmp_path):
    clock = Clock(1000.0)
    pub = statefile.StatePublisher(tmp_path, clock=clock)
    pub.phase("idle", 0.3)
    pub.wake("hey kushim")
    r = statefile.read(tmp_path, now=clock())
    assert r == {"active": True, "state": "idle", "level": 0.3, "wake_count": 1, "wake_last": "hey kushim"}
    pub.wake("Hey_Jarvis")
    pub.wake("<script>alert(1)</script>")
    r = statefile.read(tmp_path, now=clock())
    assert r["wake_count"] == 3 and r["wake_last"] == ""
    pub.wake("x" * 100)
    assert statefile.read(tmp_path, now=clock())["wake_last"] == "x" * 40
    pub.phase("listening", 0.1)
    clock.t += 1
    pub.phase("listening", 0.1)
    assert statefile.read(tmp_path, now=clock())["wake_count"] == 4                 # bleibt über weitere Schreibvorgänge


def test_api_voice_state_shows_wake_count_and_name(tmp_path):
    api = make_api(tmp_path)
    statefile.StatePublisher(tmp_path).wake("kushim")
    r = api("voice.state")
    assert r["ok"] and r["wake_count"] == 1 and r["wake_last"] == "kushim"


def write_state(tmp_path, **fields):
    p = tmp_path / statefile.FILE
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps({"state": "idle", "level": 0.2, "ts": time.time(), **fields}), encoding="utf-8")


def test_reader_validates_wake_fields(tmp_path):
    for bad in ("5", True, -1, 10 ** 12, 1.5, None, [1]):
        write_state(tmp_path, wake_count=bad)
        r = statefile.read(tmp_path)
        assert r["active"] is True and r["wake_count"] == 0, bad
    for bad in (123, "x" * 41, "Hey Kushim", "kushim\n", "<b>", "", None, ["kushim"], " kushim"):
        write_state(tmp_path, wake_last=bad)
        r = statefile.read(tmp_path)
        assert r["active"] is True and r["wake_last"] == "", bad
    write_state(tmp_path, wake_count=7, wake_last="hey_jarvis_v0.1", text="geheim", audio=[1, 2, 3])
    r = statefile.read(tmp_path)
    assert r == {"active": True, "state": "idle", "level": 0.2, "wake_count": 7, "wake_last": "hey_jarvis_v0.1"}


def test_reader_rejects_huge_nan_and_odd_files(tmp_path):
    p = tmp_path / statefile.FILE
    p.parent.mkdir()
    now = time.time()
    p.write_text(json.dumps({"state": "idle", "level": 0.2, "ts": now, "pad": "x" * 5000}), encoding="utf-8")
    assert statefile.read(tmp_path)["active"] is False
    for raw in ('{"state": "idle", "level": NaN, "ts": %f}' % now, '{"state": "idle", "level": 0.1, "ts": Infinity}',
                '{"state": ["idle"], "level": 0.1, "ts": %f}' % now, '"idle"', "null", "\xff\xfe"):
        p.write_text(raw, encoding="utf-8")
        assert statefile.read(tmp_path) == {"active": False, "state": "idle", "level": 0.0, "wake_count": 0, "wake_last": ""}, raw
    p.write_bytes(b"\xff\xfe\x00")
    assert statefile.read(tmp_path)["active"] is False


# --- Namen vom Detektor --------------------------------------------------------------------------------------------

def test_openwakeword_detector_reports_the_best_model_name():
    from kushim.voice.trigger import WakeWordDetector

    class Model:
        def predict(self, frame):
            return {"alexa": 0.2, "hey_jarvis": 0.9}
    d = WakeWordDetector(Model(), threshold=0.5, hits=1, clock=lambda: 0.0)
    ev = d.process(None)
    assert ev.source == "wake" and ev.name == "hey_jarvis" and ev.score == 0.9


def test_kws_detector_reports_the_keyword_name():
    from kushim.voice.trigger import KwsDetector

    class Stream:
        def accept_waveform(self, rate, x):
            pass

    class Spotter:
        ready = 1

        def create_stream(self):
            return Stream()

        def is_ready(self, s):
            return self.ready > 0

        def decode_stream(self, s):
            self.ready -= 1

        def get_result(self, s):
            return "hey_kushim"

        def reset_stream(self, s):
            pass
    ev = KwsDetector(Spotter(), clock=lambda: 0.0).process(SILENT)
    assert ev.name == "hey kushim" and statefile.wake_name(ev.name) == "hey kushim"
