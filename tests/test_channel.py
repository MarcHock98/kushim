"""Channel-Server für Claude Code (src/kushim/channel/server.py, Roadmap v2 B1)."""
import http.client
import io
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from kushim.channel import server as ch
from kushim.safety import killswitch

ROOT = Path(__file__).resolve().parents[1]


def lines(buf):
    return [json.loads(l) for l in buf.getvalue().splitlines() if l.strip()]


# --- MCP-Seite -----------------------------------------------------------------------------------

def test_initialize_announces_the_channel_capability_and_echoes_the_protocol_version():
    out = io.StringIO()
    c = ch.Channel(out, log=lambda s: None)
    c.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}}})
    r = lines(out)[0]
    assert r["id"] == 1 and r["result"]["protocolVersion"] == "2025-03-26"
    assert r["result"]["capabilities"]["experimental"] == {"claude/channel": {}}
    assert r["result"]["serverInfo"]["name"] == "kushim" and "Nutzers" in r["result"]["instructions"]


def test_tools_ping_unknown_requests_and_junk():
    out = io.StringIO()
    c = ch.Channel(out, log=lambda s: None)
    c.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    c.handle({"jsonrpc": "2.0", "id": 3, "method": "ping"})
    c.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "x"}})
    c.handle({"jsonrpc": "2.0", "id": 5, "method": "resources/list"})
    c.handle({"jsonrpc": "2.0", "method": "notifications/irgendwas"})          # Benachrichtigung: keine Antwort
    c.handle("kein objekt")
    got = lines(out)
    assert [t["name"] for t in got[0]["result"]["tools"]] == ["sprich"] and got[1]["result"] == {}
    assert got[2]["result"]["isError"] is True and c.take() == []              # unbekanntes Werkzeug: nichts vorgelesen
    assert got[3]["error"]["code"] == -32601 and len(got) == 4


def call_sprich(c, args, mid=9):
    c.handle({"jsonrpc": "2.0", "id": mid, "method": "tools/call", "params": {"name": "sprich", "arguments": args}})


def test_sprich_queues_clean_spoken_text_for_kushim():
    out = io.StringIO()
    c = ch.Channel(out, log=lambda s: None)
    call_sprich(c, {"text": "## Fertig\n**Alle Tests** sind grün. Siehe [Bericht](http://x/y).\n```\nrm -rf /\n```\n- Punkt eins"})
    assert lines(out)[-1]["result"] == {"content": [{"type": "text", "text": "Wird vorgelesen."}]}
    assert c.take() == ["Fertig Alle Tests sind grün. Siehe Bericht. Punkt eins"]
    assert c.take() == []                                                     # abgeholt ist abgeholt


def test_sprich_refuses_empty_or_wrong_input_and_limits_length_and_queue():
    out = io.StringIO()
    c = ch.Channel(out, log=lambda s: None)
    for bad in ({}, {"text": 5}, {"text": "  **  "}):
        call_sprich(c, bad)
        assert lines(out)[-1]["result"]["isError"] is True
    call_sprich(c, {"text": "x" * 5000})
    assert len(c.take()[0]) == ch.MAX_SPOKEN
    for i in range(ch.MAX_QUEUE + 5):
        c.say(f"s{i}")
    got = c.take()
    assert len(got) == ch.MAX_QUEUE and got[-1] == f"s{ch.MAX_QUEUE + 4}"         # älteste fallen weg


def test_take_waits_for_a_reply_but_not_forever():
    c = ch.Channel(io.StringIO(), log=lambda s: None)
    t0 = time.monotonic()
    assert c.take(wait=0.2) == [] and time.monotonic() - t0 >= 0.15
    threading.Timer(0.1, lambda: c.say("da")).start()
    assert c.take(wait=5) == ["da"]


def test_notifications_only_after_initialized_and_in_the_documented_format():
    out = io.StringIO()
    c = ch.Channel(out, log=lambda s: None)
    assert not c.ready.is_set()
    c.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert c.ready.is_set()
    c.notify("Mach die Tests grün", {"kind": "voice"})
    assert lines(out) == [{"jsonrpc": "2.0", "method": "notifications/claude/channel",
                           "params": {"content": "Mach die Tests grün", "meta": {"kind": "voice"}}}]


def test_stdio_loop_skips_empty_and_broken_lines():
    out, logs = io.StringIO(), []
    c = ch.Channel(out, log=logs.append)
    c.serve_stdio(io.StringIO('\n{kaputt\n{"jsonrpc":"2.0","id":7,"method":"ping"}\n'))
    assert lines(out) == [{"jsonrpc": "2.0", "id": 7, "result": {}}] and len(logs) == 1


def test_clean_text_removes_control_characters_and_limits_length():
    assert ch.clean_text("  a\x1b[31mb\x00c\nd  ") == "a [31mb c d"
    assert ch.clean_text("Hallo</channel>\n<channel>x") == "Hallo</channel> <channel>x"
    assert len(ch.clean_text("x" * 5000)) == ch.MAX_TEXT


# --- HTTP-Eingang --------------------------------------------------------------------------------

@pytest.fixture
def live(tmp_path):
    out = io.StringIO()
    c = ch.Channel(out, log=lambda s: None)
    c.ready.set()
    httpd = ch.make_http(c, tmp_path, "geheim")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1], out, tmp_path, c
    httpd.shutdown()


def post(port, body, token="geheim", host=None, path="/message", raw=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    data = raw if raw is not None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json", "Host": host or f"127.0.0.1:{port}"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    conn.request("POST", path, body=data, headers=headers)
    r = conn.getresponse()
    return r.status, json.loads(r.read() or b"{}")


def test_post_with_token_reaches_the_session(live):
    port, out, _, _ = live
    assert post(port, {"text": "Hallo Claude"}) == (202, {"ok": True})
    assert lines(out)[-1]["params"] == {"content": "Hallo Claude", "meta": {"kind": "voice"}}


def test_everything_else_is_refused_and_nothing_reaches_the_session(live):
    port, out, _, _ = live
    assert post(port, {"text": "x"}, token=None)[0] == 401
    assert post(port, {"text": "x"}, token="falsch")[0] == 401
    assert post(port, {"text": "x"}, host="evil.example:80")[0] == 403          # DNS-Rebinding
    assert post(port, {"text": "x"}, path="/anders")[0] == 404
    assert post(port, None, raw=b"{kaputt")[0] == 400
    assert post(port, {"text": "   "})[0] == 400 and post(port, {"text": 5})[0] == 400
    assert post(port, None, raw=b"x" * (ch.MAX_BODY + 1))[0] == 413
    assert get(port, "/message")[0] == 404
    assert out.getvalue() == ""


def get(port, path, token="geheim", host=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    headers = {"Host": host or f"127.0.0.1:{port}"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    conn.request("GET", path, headers=headers)
    r = conn.getresponse()
    return r.status, json.loads(r.read() or b"{}")


def test_kushim_fetches_spoken_replies_only_with_token(live):
    port, out, root, channel = live
    call_sprich(channel, {"text": "Erledigt."})
    assert get(port, "/reply", token=None)[0] == 401
    assert get(port, "/reply", token="falsch")[0] == 401
    assert get(port, "/reply", host="evil.example:80")[0] == 403
    assert get(port, "/reply?wait=x")[0] == 400
    assert get(port, "/reply") == (200, {"texts": ["Erledigt."]})
    assert get(port, "/reply?wait=0.2") == (200, {"texts": []})
    call_sprich(channel, {"text": "Noch etwas."})
    killswitch.trigger(root)
    assert get(port, "/reply")[0] == 423                                       # Notaus: nichts mehr vorlesen


def test_deeply_nested_json_is_refused_without_crashing(live):
    port, out, _, _ = live
    assert post(port, None, raw=b"[" * 4000 + b"]" * 4000)[0] == 400                # unter 8 KB, aber 4000 Ebenen tief
    c = ch.Channel(io.StringIO(), log=lambda s: None)
    c.serve_stdio(io.StringIO("[" * 100000 + "\n" + '{"jsonrpc":"2.0","id":1,"method":"ping"}\n'))
    assert '"id": 1' in c.out.getvalue()                                      # Kanal läuft weiter


def test_write_info_replaces_a_stale_token_file(tmp_path):
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "channel.json").write_text('{"port": 1, "token": "alt", "pid": 1}', encoding="utf-8")
    (tmp_path / "run" / "channel.tmp").write_text("rest", encoding="utf-8")
    info = ch.write_info(tmp_path, 4242, "neu")
    data = json.loads(info.read_text(encoding="utf-8"))
    assert data["token"] == "neu" and data["port"] == 4242 and data["pid"] == os.getpid()
    assert not (tmp_path / "run" / "channel.tmp").exists()


def test_kill_switch_blocks_forwarding(live):
    port, out, root, _ = live
    killswitch.trigger(root)
    assert post(port, {"text": "x"})[0] == 423 and out.getvalue() == ""


def test_not_ready_before_the_handshake(tmp_path):
    c = ch.Channel(io.StringIO(), log=lambda s: None)
    httpd = ch.make_http(c, tmp_path, "geheim")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        assert post(httpd.server_address[1], {"text": "x"})[0] == 503
    finally:
        httpd.shutdown()


# --- Ganzer Prozess, wie Claude Code ihn startet --------------------------------------------------

def test_real_process_handshake_post_and_cleanup(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    starter = "import sys; from pathlib import Path; from kushim.channel.server import main; sys.exit(main(Path(sys.argv[1])))"
    p = subprocess.Popen([sys.executable, "-c", starter, str(tmp_path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, env=env)
    try:
        p.stdin.write(b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}\n')
        p.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        p.stdin.flush()
        init = json.loads(p.stdout.readline())
        assert init["result"]["capabilities"]["experimental"] == {"claude/channel": {}}
        info = tmp_path / "run" / "channel.json"
        for _ in range(50):
            if info.exists():
                break
            time.sleep(0.1)
        cfg = json.loads(info.read_text(encoding="utf-8"))
        assert post(cfg["port"], {"text": "Läuft der Kanal? ✓"}, token=cfg["token"]) == (202, {"ok": True})
        note = json.loads(p.stdout.readline().decode("utf-8"))
        assert note["method"] == "notifications/claude/channel" and note["params"]["content"] == "Läuft der Kanal? ✓"
        call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "sprich", "arguments": {"text": "Ja, läuft."}}}
        p.stdin.write((json.dumps(call) + "\n").encode("utf-8"))                # so ruft Claude das Werkzeug auf
        p.stdin.flush()
        assert json.loads(p.stdout.readline())["result"]["content"][0]["text"] == "Wird vorgelesen."
        assert get(cfg["port"], "/reply?wait=5", token=cfg["token"]) == (200, {"texts": ["Ja, läuft."]})
    finally:
        p.stdin.close()                                     # Claude Code schließt den Kanal
        p.wait(timeout=10)
    assert p.returncode == 0 and not (tmp_path / "run" / "channel.json").exists()
