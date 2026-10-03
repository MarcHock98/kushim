"""Lokaler LLM-Client für Ollama, ausschließlich über net/loopback.py (nur 127.0.0.1).

Der Client hat keine Werkzeuge: er liefert nur Text. Aktionen laufen nie hierüber, sondern über
den ActionGate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..net.loopback import request_json, stream_json_lines

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:7b"    # Standard; austauschbar über config.toml ([llm] model) oder `kushim llm set`

_MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*){0,3}(:[A-Za-z0-9._-]+)?")


def validate_model(name: str) -> str:
    """Nur einfache Ollama-Modellnamen (z. B. `qwen3.5:9b`, `hf.co/org/repo:Q4_K_M`), keine Pfade oder Sonderzeichen."""
    name = name.strip()
    if not _MODEL_RE.fullmatch(name) or ".." in name:
        raise ValueError(f"Ungültiger Modellname: {name!r}")
    return name


def manifest_rel(model: str) -> str:
    """Relativer Pfad des Ollama-Manifests (für die Installationsprüfung)."""
    name, _, tag = validate_model(model).partition(":")
    parts = name.split("/")
    if len(parts) == 1:
        parts = ["registry.ollama.ai", "library", parts[0]]
    elif len(parts) == 2:
        parts = ["registry.ollama.ai", *parts]
    return "/".join(["models/ollama/manifests", *parts, tag or "latest"])


@dataclass
class OllamaClient:
    model: str
    base_url: str = DEFAULT_URL
    timeout: float = 120.0
    keep_alive: str = "2h"       # Modell im VRAM halten (Standard von Ollama: 5 Minuten, danach Kaltstart von ca. 2 s)

    def warm_up(self) -> None:
        """Lädt das Modell vorab (leere Nachrichtenliste lädt nur, erzeugt keinen Text)."""
        request_json("POST", f"{self.base_url}/api/chat", {
            "model": self.model, "messages": [], "keep_alive": self.keep_alive}, timeout=self.timeout)

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
                "model": self.model, "messages": messages, "stream": True, "keep_alive": self.keep_alive,
                "options": {"temperature": temperature}}, timeout=self.timeout):
            if not isinstance(obj, dict):
                raise ValueError("Unerwartete Antwort des lokalen LLM")
            piece = (obj.get("message") or {}).get("content", "")
            if piece:
                yield str(piece)
            if obj.get("done"):
                return
