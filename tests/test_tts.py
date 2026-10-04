from kushim.voice.tts import Speaker, chunk_stream, split_sentences


def test_split_sentences():
    assert split_sentences("Hallo Welt. Wie geht's? Gut!") == ["Hallo Welt.", "Wie geht's?", "Gut!"]
    assert split_sentences("  ") == []


def test_chunk_stream_yields_complete_sentences():
    toks = ["Hal", "lo. Wie ", "geht", "'s? Gut"]
    assert list(chunk_stream(toks)) == ["Hallo.", "Wie geht's?", "Gut"]


class Eng:
    def synthesize(self, text):
        return text.upper()


def test_speaker_plays_all():
    out = []
    assert Speaker(Eng(), out.append).say(["a.", "b."]) == 2
    assert out == ["A.", "B."]


def test_speaker_stops_on_barge_in():
    out, flag = [], {"stop": False}

    def play(x):
        out.append(x)
        flag["stop"] = True

    assert Speaker(Eng(), play, lambda: flag["stop"]).say(["a.", "b.", "c."]) == 1
    assert out == ["A."]


def test_piper_engine_wraps_voice_output():
    import io
    import wave

    from kushim.voice.tts import PiperEngine

    class FakeVoice:
        def synthesize_wav(self, text, w):
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
            w.writeframes(b"\x00\x00" * 100)

    data = PiperEngine(FakeVoice()).synthesize("Hallo.")
    with wave.open(io.BytesIO(data)) as w:
        assert w.getnframes() == 100 and w.getframerate() == 22050


def test_piper_real_voice_if_present():
    import wave
    from pathlib import Path

    import pytest

    from kushim.voice.tts import PiperEngine
    model = Path(__file__).resolve().parents[1] / "models" / "piper" / "de_DE-thorsten-high.onnx"
    if not model.exists():
        pytest.skip("Piper-Modell nicht vorhanden")
    import io
    data = PiperEngine.from_local(str(model)).synthesize("Hallo Welt.")
    with wave.open(io.BytesIO(data)) as w:
        assert w.getnframes() > 1000


def test_prefetch_keeps_order_and_propagates_errors():
    import pytest

    from kushim.voice.tts import prefetch
    assert list(prefetch(iter(["a", "b", "c"]))) == ["a", "b", "c"]

    def bad():
        yield "x"
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        list(prefetch(bad()))


def test_prefetch_stops_when_requested():
    from kushim.voice.tts import prefetch

    def endless():
        i = 0
        while True:
            yield str(i)
            i += 1

    flag = {"stop": False}
    it = prefetch(endless(), stop=lambda: flag["stop"])
    assert next(it) == "0"
    flag["stop"] = True      # Erzeuger-Thread beendet sich, kein Hängen


def test_prefetch_ends_when_stopped_even_if_the_llm_is_still_writing():
    import threading
    import time
    from kushim.voice.tts import prefetch
    release, stop = threading.Event(), threading.Event()

    def slow_source():
        yield "Satz eins."
        release.wait(timeout=10)              # LLM schreibt noch am nächsten Satz
        yield "Satz zwei."
    got, t0 = [], time.time()
    gen = prefetch(slow_source(), stop=stop.is_set)
    got.append(next(gen))
    threading.Timer(0.3, stop.set).start()    # Nutzer unterbricht
    got.extend(gen)                           # darf nicht hängen bleiben
    release.set()
    assert got == ["Satz eins."] and time.time() - t0 < 3
