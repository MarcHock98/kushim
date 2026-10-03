import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from kushim.llm.ollama import OllamaClient
from kushim.net.loopback import NotLoopback

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


def test_stream_keeps_model_warm_and_warm_up_only_loads(url):
    c = OllamaClient("m", base_url=url)
    list(c.chat_stream([{"role": "user", "content": "x"}]))
    assert SEEN[-1]["keep_alive"] == "2h"
    c.warm_up()
    assert SEEN[-1]["messages"] == [] and SEEN[-1]["keep_alive"] == "2h" and "stream" not in SEEN[-1]


def test_validate_model_and_manifest_path():
    from kushim.llm.ollama import manifest_rel, validate_model
    assert validate_model(" qwen3.5:9b ") == "qwen3.5:9b"
    assert manifest_rel("qwen2.5:7b") == "models/ollama/manifests/registry.ollama.ai/library/qwen2.5/7b"
    assert manifest_rel("gemma4") == "models/ollama/manifests/registry.ollama.ai/library/gemma4/latest"
    assert manifest_rel("hf.co/org/repo:Q4_K_M") == "models/ollama/manifests/hf.co/org/repo/Q4_K_M"
    for bad in ("", "../x", "a b", "x;rm", "a:b:c", "/abs", "a\\b"):
        with pytest.raises(ValueError):
            validate_model(bad)


def test_thinking_is_off_by_default_and_can_be_left_to_the_model(url):
    c = OllamaClient("m", base_url=url)
    c.chat([{"role": "user", "content": "x"}])
    assert SEEN[-1]["think"] is False
    list(c.chat_stream([{"role": "user", "content": "x"}]))
    assert SEEN[-1]["think"] is False
    list(OllamaClient("m", base_url=url, think=None).chat_stream([{"role": "user", "content": "x"}]))
    assert "think" not in SEEN[-1]
