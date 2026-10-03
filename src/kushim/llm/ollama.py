"""Lokaler LLM-Client für Ollama, ausschließlich über net/loopback.py (nur 127.0.0.1).

Der Client hat keine Werkzeuge: er liefert nur Text. Aktionen laufen nie hierüber, sondern über
den ActionGate.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..net.loopback import request_json, stream_json_lines

DEFAULT_URL = "http://127.0.0.1:11434"


@dataclass
class OllamaClient:
    model: str
    base_url: str = DEFAULT_URL
    timeout: float = 120.0

    def available_models(self) -> list[str]:
        data = request_json("GET", f"{self.base_url}/api/tags", timeout=5.0) or {}
        return [m["name"] for m in data.get("models", []) if "name" in m]

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.3) -> str:
        data = request_json("POST", f"{self.base_url}/api/chat", {
            "model": self.model, "messages": messages, "stream": False,
            "options": {"temperature": temperature}}, timeout=self.timeout)
        try:
            return str(data["message"]["content"]).strip()
        except (TypeError, KeyError) as e:
            raise ValueError("Unerwartete Antwort des lokalen LLM") from e

    def chat_stream(self, messages: list[dict[str, str]], temperature: float = 0.3):
        """Liefert die Antwort Stück für Stück (Tokens) über Loopback-Streaming."""
        for obj in stream_json_lines("POST", f"{self.base_url}/api/chat", {
                "model": self.model, "messages": messages, "stream": True,
                "options": {"temperature": temperature}}, timeout=self.timeout):
            if not isinstance(obj, dict):
                raise ValueError("Unerwartete Antwort des lokalen LLM")
            piece = (obj.get("message") or {}).get("content", "")
            if piece:
                yield str(piece)
            if obj.get("done"):
                return
