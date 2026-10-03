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
