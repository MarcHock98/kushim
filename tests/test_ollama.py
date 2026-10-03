import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from kushima.llm.ollama import OllamaClient
from kushima.net.loopback import NotLoopback

SEEN = []


class H(BaseHTTPRequestHandler):
    def _send(self, obj):
        out = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        self._send({"models": [{"name": "llama3.1:8b"}, {"name": "qwen2.5:7b"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append(body)
        if body.get("stream"):
            self.send_response(200); self.send_header("Connection", "close"); self.end_headers()
            nl = chr(10)
            for t in ["Hal", "lo", "!"]:
                self.wfile.write((json.dumps({"message": {"content": t}, "done": False}) + nl).encode())
            self.wfile.write((json.dumps({"message": {"content": ""}, "done": True}) + nl).encode())
            return
        self._send({"message": {"role": "assistant", "content": " Hallo! "}} if body["messages"]
                   else {"oops": 1})

    def log_message(self, *a):
        pass


@pytest.fixture()
def url():
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_models_and_chat(url):
    c = OllamaClient("llama3.1:8b", base_url=url)
    assert c.available_models() == ["llama3.1:8b", "qwen2.5:7b"]
    assert c.chat([{"role": "user", "content": "Hi"}]) == "Hallo!"
    assert SEEN[-1]["stream"] is False and SEEN[-1]["model"] == "llama3.1:8b"


def test_bad_response_raises(url):
    with pytest.raises(ValueError):
        OllamaClient("m", base_url=url).chat([])


def test_remote_url_refused():
    with pytest.raises(NotLoopback):
        OllamaClient("m", base_url="http://example.com:11434").chat([{"role": "user", "content": "x"}])


def test_chat_stream_yields_pieces(url):
    pieces = list(OllamaClient("m", base_url=url).chat_stream([{"role": "user", "content": "x"}]))
    assert pieces == ["Hal", "lo", "!"] and SEEN[-1]["stream"] is True
