from kushim.voice.dialog import Dialog, State


def test_normal_turn():
    d = Dialog()
    assert d.triggered() and d.state is State.LISTENING
    assert d.utterance_done() and d.reply_ready() and d.speech_done()
    assert d.state is State.IDLE


def test_barge_in_stops_speech():
    stops = []
    d = Dialog(lambda: stops.append(1))
    d.triggered(); d.utterance_done(); d.reply_ready()
    assert d.triggered()
    assert stops == [1] and d.state is State.LISTENING


def test_out_of_order_transitions_rejected():
    d = Dialog()
    assert not d.reply_ready() and not d.speech_done() and not d.utterance_done()
    assert d.state is State.IDLE


def test_halt_blocks_everything_until_reset():
    stops = []
    d = Dialog(lambda: stops.append(1))
    d.triggered(); d.utterance_done(); d.reply_ready()
    d.halt()
    assert stops == [1] and d.state is State.HALTED
    assert not d.triggered() and not d.utterance_done()
    d.reset()
    assert d.triggered()
