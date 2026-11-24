"""`build_live` mit der Sprachausgabe: Whisper zuerst, dann der Worker; Notaus beendet den Worker; „Ja?“ aus dem Satz-Cache
oder - wenn die Stimme fehlt - der Hinweiston; Text ohne Stimme geht an `on_note`. Alles mit Fakes (keine Modelle, kein Audio)."""
import time
from types import SimpleNamespace

import pytest

from kushim.voice import audio, earcon, stt, talk, ttsworker
from kushim.voice.tts import TTSUnavailable


class FakeWorker:
    def __init__(self, order, ready=True, fail=False):
        self.order, self.ready, self.fail = order, ready, fail
        self.state, self.killed, self.said = "off", 0, []
        self.on_note = lambda s: None

    def start(self):
        self.order.append("tts")
        self.state = "loading"

    def wait_ready(self, timeout):
        self.state = "ready" if self.ready else "loading"
        return self.ready

    def synthesize(self, text):
        self.said.append(text)
        if self.fail:
            raise TTSUnavailable("weg")
        return b"WAV:" + text.encode()

    def cancel(self):
        pass

    def kill(self):
        self.killed += 1
        self.state = "off"


@pytest.fixture
def live(monkeypatch, tmp_path):
    def make(ready=True, fail=False):
        order, played, notes, made = [], [], [], {}

        def from_local(path, **kw):
            order.append("whisper")
            return SimpleNamespace(transcribe=lambda pcm: SimpleNamespace(text=""))

        def for_root(root, provider, device_id=0, **kw):
            made.update(provider=provider, device_id=device_id)
            made["worker"] = FakeWorker(order, ready, fail)
            return made["worker"]
        monkeypatch.setattr(stt.SpeechToText, "from_local", staticmethod(from_local))
        monkeypatch.setattr(ttsworker.KokoroWorker, "for_root", staticmethod(for_root))
        monkeypatch.setattr(audio, "Mic", lambda dev: SimpleNamespace(flush=lambda: None))
        monkeypatch.setattr(audio, "play_wav", lambda wav, dev=None: played.append(wav))
        monkeypatch.setattr(audio, "stop_playback", lambda: None)
        pipeline, kill, mic, ack = talk.build_live(tmp_path, None, None, whisper_device="cuda", whisper_index=1,
                                                   on_note=notes.append)
        return SimpleNamespace(pipeline=pipeline, kill=kill, ack=ack, order=order, played=played, notes=notes, **made)
    return make


def test_whisper_loads_first_then_the_worker_on_the_same_card(live):
    r = live()
    assert r.order == ["whisper", "tts"] and r.provider == "cuda" and r.device_id == 1
    assert r.pipeline.tts is r.worker


def test_kill_switch_kills_the_worker(live):
    r = live()
    r.kill.fire()
    assert r.worker.killed == 1 and r.worker.state == "off"


def test_ack_comes_from_the_cache_and_is_computed_once(live):
    r = live()
    deadline = time.monotonic() + 3
    while "Ja?" not in r.worker.said and time.monotonic() < deadline:       # Vorwärmen im Hintergrund
        time.sleep(0.01)
    r.ack()
    r.ack()
    assert r.played == [b"WAV:Ja?", b"WAV:Ja?"] and r.worker.said.count("Ja?") == 1


def test_without_voice_ack_is_the_hint_tone_and_answers_come_as_text(live):
    r = live(ready=False, fail=True)
    assert any("noch nicht bereit" in n for n in r.notes)
    r.ack()
    assert r.played == [earcon.hint_wav()]
    r.played.clear()
    assert r.pipeline.say_text("Es ist 14:35 Uhr. Alles gut.") == 2                 # beide als Text geliefert
    assert r.played == [earcon.hint_wav()]                                   # einmal der Hinweiston, nie Stille
    assert [n for n in r.notes if n.startswith("Ohne Stimme:")] == ["Ohne Stimme: Es ist 14:35 Uhr.", "Ohne Stimme: Alles gut."]


def test_without_gpu_the_worker_runs_on_the_cpu(monkeypatch, tmp_path):
    order, made = [], {}
    monkeypatch.setattr(stt.SpeechToText, "from_local", staticmethod(lambda path, **kw: order.append("whisper")))

    def for_root(root, provider, device_id=0, **kw):
        made["provider"] = provider
        return FakeWorker(order)
    monkeypatch.setattr(ttsworker.KokoroWorker, "for_root", staticmethod(for_root))
    monkeypatch.setattr(audio, "Mic", lambda dev: None)
    talk.build_live(tmp_path, None, None, whisper_device="cpu")
    assert made["provider"] == "cpu" and order == ["whisper", "tts"]
