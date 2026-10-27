"""kushim-Seite der Brücke (src/kushim/channel/bridge.py, Roadmap v2 B3)."""
import io
import json
import threading

import pytest

from kushim.channel import bridge as br
from kushim.channel import server as ch
from kushim.net import loopback
from kushim.safety import killswitch

TOKEN = "t" * 32


def write(root, data):
    (root / "run").mkdir(exist_ok=True)
    (root / "run" / "channel.json").write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")


@pytest.mark.parametrize("data", [
    "{kaputt", "[]", {"port": "1", "token": TOKEN}, {"port": True, "token": TOKEN}, {"port": 0, "token": TOKEN},
    {"port": 70000, "token": TOKEN}, {"port": 5000, "token": "kurz"}, {"port": 5000, "token": 5},
    {"port": 5000, "token": "x" * 300}, {"port": 5000, "token": "a\nb" * 10}, {"port": 5000},
])
def test_read_info_rejects_junk(tmp_path, data):
    write(tmp_path, data)
    assert br.read_info(tmp_path) is None


def test_read_info_missing_or_huge(tmp_path):
    assert br.read_info(tmp_path) is None
    write(tmp_path, " " * (br.MAX_INFO_BYTES + 1))
    assert br.read_info(tmp_path) is None
    write(tmp_path, {"port": 5000, "token": TOKEN, "pid": 1})
    assert br.read_info(tmp_path) == br.ChannelInfo(5000, TOKEN)


@pytest.fixture
def channel(tmp_path):
    out = io.StringIO()
    c = ch.Channel(out, log=lambda s: None)
    c.ready.set()
    httpd = ch.make_http(c, tmp_path, TOKEN)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    ch.write_info(tmp_path, httpd.server_address[1], TOKEN)
    yield c, out, tmp_path
    httpd.shutdown()


def test_send_and_fetch_through_the_real_channel(channel):
    c, out, root = channel
    b = br.Bridge(root)
    assert b.available() and b.send("Mach die Tests\ngrün") == "ok"
    note = json.loads(out.getvalue().splitlines()[-1])
    assert note["params"]["content"] == "Mach die Tests grün"
    c.say("Alles grün.")
    assert b.fetch() == ("ok", ["Alles grün."]) and b.fetch(0.1) == ("ok", [])
    threading.Timer(0.2, lambda: c.say("Später.")).start()
    assert b.fetch(5) == ("ok", ["Später."])


def test_states_without_channel_wrong_token_and_kill(channel, tmp_path_factory):
    c, out, root = channel
    empty = tmp_path_factory.mktemp("leer")
    assert br.Bridge(empty).send("x") == "not_running" and br.Bridge(empty).fetch() == ("not_running", [])
    port = br.read_info(root).port
    write(root, {"port": port, "token": "f" * 32})                              # alter oder fremder Token
    assert br.Bridge(root).send("x") == "not_running"
    write(root, {"port": port, "token": TOKEN})
    killswitch.trigger(root)
    assert br.Bridge(root).send("x") == "kill" and br.Bridge(root).fetch() == ("kill", [])
    assert br.Bridge(root).send("   ") == "error"
    assert "notifications/claude/channel" not in out.getvalue()


def test_closed_port_counts_as_not_running(tmp_path):
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                                                                   # Port frei, nichts lauscht
    write(tmp_path, {"port": port, "token": TOKEN})
    assert br.Bridge(tmp_path).send("x") == "not_running"


def test_fetch_treats_replies_as_data_and_limits_them(tmp_path):
    write(tmp_path, {"port": 5000, "token": TOKEN})
    seen = {}

    def fake(method, url, payload=None, timeout=None, headers=None):
        seen.update(url=url, headers=headers, timeout=timeout)
        return {"texts": ["a\x1b[2Jb", 5, "y" * 5000, ""] + ["z"] * 50}
    status, texts = br.Bridge(tmp_path, request=fake).fetch(wait=999)
    assert status == "ok" and texts[0] == "a [2Jb" and len(texts[1]) == ch.MAX_SPOKEN and len(texts) <= ch.MAX_QUEUE
    assert seen["url"] == "http://127.0.0.1:5000/reply?wait=25" and seen["timeout"] == 30.0
    assert seen["headers"] == {"Authorization": f"Bearer {TOKEN}"}
    for junk in (None, [], {"texts": "x"}):
        assert br.Bridge(tmp_path, request=lambda *a, **k: junk).fetch() == ("error", [])


def test_loopback_http_error_carries_the_status():
    e = loopback.HttpError(423)
    assert isinstance(e, ConnectionError) and e.status == 423 and br.Bridge._status(e) == "kill"
    assert br.Bridge._status(loopback.HttpError(500)) == "error"
