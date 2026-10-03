import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from kushim.net.loopback import NotLoopback, check_url, request_json


@pytest.mark.parametrize("url", [
    "https://127.0.0.1/x", "http://example.com/", "http://192.168.1.5/", "http://0.0.0.0/",
    "http://127.0.0.1.evil.com/", "http://user:pw@127.0.0.1/", "ftp://127.0.0.1/", "http://[::2]/",
    "http://10.0.0.1:11434/api",
])
def test_non_loopback_rejected(url):
    with pytest.raises(NotLoopback):
        check_url(url)


def test_loopback_accepted_and_localhost_pinned():
    assert check_url("http://localhost:11434/api/tags?x=1") == ("127.0.0.1", 11434, "/api/tags?x=1")
    assert check_url("http://127.0.0.1/")[1] == 80
    assert check_url("http://[::1]:8000/a")[0] == "::1"


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(n))
        out = json.dumps({"echo": body}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers()

    def log_message(self, *a):
        pass


def test_roundtrip_and_http_error():
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        assert request_json("POST", base + "/x", {"a": 1}) == {"echo": {"a": 1}}
        with pytest.raises(ConnectionError):
            request_json("GET", base + "/x")
    finally:
        srv.shutdown()
