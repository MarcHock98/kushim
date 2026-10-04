import base64
import json
import os
import socket
import struct

import pytest

from kushim.api.protocol import ApiCore, new_token
from kushim.net.server import LocalServer, _accept

TOKEN = new_token()


def make_core():
    c = ApiCore(TOKEN)
    c.register("ping", lambda m: {"pong": True})
    return c


@pytest.fixture()
def server():
    s = LocalServer(make_core())
    s.start()
    yield s
    s.stop()


def raw_conn(port):
    c = socket.create_connection(("127.0.0.1", port), timeout=5)
    return c


def handshake(port, host=None, origin=None, key=None):
    c = raw_conn(port)
    key = key or base64.b64encode(os.urandom(16)).decode()
    lines = ["GET / HTTP/1.1", f"Host: {host or f'127.0.0.1:{port}'}", "Upgrade: websocket",
             "Connection: Upgrade", f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
    if origin:
        lines.append(f"Origin: {origin}")
    c.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = c.recv(1024)
        if not chunk:
            break
        resp += chunk
    return c, resp.decode("latin-1"), key


def frame(payload: bytes, opcode=1, masked=True, fin=True):
    mask = os.urandom(4)
    n = len(payload)
    head = bytes([(0x80 if fin else 0) | opcode])
    mbit = 0x80 if masked else 0
    head += bytes([mbit | n]) if n < 126 else bytes([mbit | 126]) + struct.pack(">H", n)
    body = bytes(b ^ mask[i % 4] for i, b in enumerate(payload)) if masked else payload
    return head + (mask if masked else b"") + body


def read_frame(c):
    def exactly(n):
        buf = b""
        while len(buf) < n:
            chunk = c.recv(n - len(buf))
            if not chunk:
                raise EOFError
            buf += chunk
        return buf
    b1, b2 = exactly(2)
    n = b2 & 0x7F
    if n == 126:
        n = struct.unpack(">H", exactly(2))[0]
    return b1 & 0x0F, exactly(n)


def test_binds_only_loopback(server):
    assert server._server.sockets[0].getsockname()[0] == "127.0.0.1"


def test_handshake_and_authorized_call(server):
    c, resp, key = handshake(server.port)
    assert "101" in resp.split("\r\n")[0] and _accept(key) in resp
    c.sendall(frame(json.dumps({"token": TOKEN, "type": "ping"}).encode()))
    op, data = read_frame(c)
    assert op == 1 and json.loads(data) == {"ok": True, "pong": True}
    c.close()


def test_wrong_token_denied(server):
    c, _, _ = handshake(server.port)
    c.sendall(frame(json.dumps({"token": "x" * 43, "type": "ping"}).encode()))
    assert json.loads(read_frame(c)[1]) == {"ok": False, "error": "unauthorized"}
    c.close()


def test_disconnects_after_three_failures(server):
    c, _, _ = handshake(server.port)
    for _ in range(3):
        c.sendall(frame(b"{}"))
        read_frame(c)
    assert c.recv(10) == b""
    c.close()


@pytest.mark.parametrize("origin", ["https://evil.example", "http://localhost:3000", "null"])
def test_foreign_browser_origin_refused(server, origin):
    c, resp, _ = handshake(server.port, origin=origin)
    assert "403" in resp.split("\r\n")[0]
    c.close()


def test_own_ui_origin_accepted(server):
    c, resp, _ = handshake(server.port, origin="tauri://localhost")
    assert "101" in resp.split("\r\n")[0]
    c.close()


@pytest.mark.parametrize("host", ["evil.example", "evil.example:1", "192.168.1.5:80"])
def test_foreign_host_header_refused(server, host):
    c, resp, _ = handshake(server.port, host=host)
    assert "403" in resp.split("\r\n")[0]
    c.close()


def test_plain_http_refused(server):
    c = raw_conn(server.port)
    c.sendall(f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\n\r\n".encode())
    assert b"403" in c.recv(100)
    c.close()


def test_unmasked_binary_and_fragmented_frames_close_with_protocol_error(server):
    for kw in ({"masked": False}, {"opcode": 2}, {"fin": False}):
        c, _, _ = handshake(server.port)
        c.sendall(frame(b"{}", **kw))
        op, data = read_frame(c)
        assert op == 8 and struct.unpack(">H", data)[0] == 1002
        c.close()


def test_oversize_message_refused_before_reading(server):
    c, _, _ = handshake(server.port)
    c.sendall(bytes([0x81, 0x80 | 127]) + struct.pack(">Q", 10 ** 9) + os.urandom(4))
    op, data = read_frame(c)
    assert op == 8
    c.close()


def test_ping_gets_pong(server):
    c, _, _ = handshake(server.port)
    c.sendall(frame(b"hi", opcode=9))
    assert read_frame(c) == (10, b"hi")
    c.close()


def test_connection_limit(server):
    conns = [handshake(server.port)[0] for _ in range(4)]
    c, resp, _ = handshake(server.port)
    assert "503" in resp.split("\r\n")[0]
    for x in conns + [c]:
        x.close()


def test_handler_exception_is_neutral(server):
    core = server._core
    core.register("boom", lambda m: 1 / 0)
    c, _, _ = handshake(server.port)
    c.sendall(frame(json.dumps({"token": TOKEN, "type": "boom"}).encode()))
    assert json.loads(read_frame(c)[1]) == {"ok": False, "error": "internal"}
    c.close()
