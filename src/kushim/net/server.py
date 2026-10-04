"""WebSocket-Server der Backend-API: ausschließlich 127.0.0.1, nur Standardbibliothek (keine neue Abhängigkeit).

Vom Nutzer am 2026-10-04 freigegeben (ALLOWLIST in tests/test_no_egress.py). Grenzen, die Tests sperren:
- Bindung fest an 127.0.0.1, der Host ist kein Parameter.
- Handshake nur mit passendem `Host` (gegen DNS-Rebinding) und `Origin` entweder fehlend (eigener Client) oder
  in der Liste der eigenen Oberfläche; fremde Webseiten im Browser werden abgewiesen.
- Jede Nachricht geht durch `ApiCore.handle` (Token, Default-Deny). Nach 3 abgelehnten Nachrichten wird getrennt.
- Nur Text-Frames, maskiert, nicht fragmentiert, höchstens `MAX_MESSAGE_BYTES`; höchstens 4 Verbindungen.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import struct
import threading
from typing import Iterable

from ..api.protocol import MAX_MESSAGE_BYTES, ApiCore

BIND_HOST = "127.0.0.1"
MAX_CONNECTIONS = 4
MAX_FAILURES = 3
HANDSHAKE_TIMEOUT = 5.0
IDLE_TIMEOUT = 600.0
MAX_HEADER_BYTES = 8192
_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
DEFAULT_ORIGINS = frozenset({"tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"})


def _accept(key: str) -> str:
    return base64.b64encode(hashlib.sha1(key.encode() + _GUID).digest()).decode()


def encode_frame(opcode: int, payload: bytes) -> bytes:
    n = len(payload)
    head = bytes([0x80 | opcode])
    if n < 126:
        head += bytes([n])
    elif n < 65536:
        head += bytes([126]) + struct.pack(">H", n)
    else:
        head += bytes([127]) + struct.pack(">Q", n)
    return head + payload                                   # Server-Frames sind nie maskiert


class LocalServer:
    def __init__(self, core: ApiCore, port: int = 0, origins: Iterable[str] = DEFAULT_ORIGINS):
        self._core = core
        self._want_port = port
        self._origins = frozenset(origins)
        self._active = 0
        self.port = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: asyncio.base_events.Server | None = None
        self._thread: threading.Thread | None = None

    # --- Lebenszyklus ---------------------------------------------------------------------------------------
    def start(self) -> int:
        ready = threading.Event()

        def run() -> None:
            self._loop = asyncio.new_event_loop()
            self._server = self._loop.run_until_complete(
                asyncio.start_server(self._client, BIND_HOST, self._want_port))
            self.port = self._server.sockets[0].getsockname()[1]
            ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=run, name="kushim-api", daemon=True)
        self._thread.start()
        if not ready.wait(5):
            raise RuntimeError("API-Server startet nicht")
        return self.port

    def stop(self) -> None:
        loop = self._loop
        if loop is None:
            return

        async def close() -> None:
            if self._server:
                self._server.close()
                await self._server.wait_closed()
            loop.stop()

        asyncio.run_coroutine_threadsafe(close(), loop)
        if self._thread:
            self._thread.join(5)
        self._loop = None

    # --- Verbindung -----------------------------------------------------------------------------------------
    async def _client(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        try:
            if self._active >= MAX_CONNECTIONS:
                await self._refuse(w, "503 Service Unavailable")
                return
            self._active += 1
            try:
                if await self._handshake(r, w):
                    await self._session(r, w)
            finally:
                self._active -= 1
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError,
                ValueError, OSError):
            pass
        finally:
            try:
                w.close()
            except Exception:
                pass

    async def _refuse(self, w: asyncio.StreamWriter, status: str) -> None:
        w.write(f"HTTP/1.1 {status}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n".encode())
        await w.drain()

    async def _handshake(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> bool:
        raw = await asyncio.wait_for(r.readuntil(b"\r\n\r\n"), HANDSHAKE_TIMEOUT)
        if len(raw) > MAX_HEADER_BYTES:
            await self._refuse(w, "431 Request Header Fields Too Large")
            return False
        lines = raw.decode("latin-1").split("\r\n")
        h = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                h[k.strip().lower()] = v.strip()
        ok = (lines[0].startswith("GET ") and h.get("upgrade", "").lower() == "websocket"
              and "upgrade" in h.get("connection", "").lower() and h.get("sec-websocket-version") == "13"
              and bool(h.get("sec-websocket-key")))
        host_ok = h.get("host", "") in {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        origin = h.get("origin")
        origin_ok = origin is None or origin in self._origins
        if not (ok and host_ok and origin_ok):
            await self._refuse(w, "403 Forbidden")
            return False
        w.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                 f"Sec-WebSocket-Accept: {_accept(h['sec-websocket-key'])}\r\n\r\n").encode())
        await w.drain()
        return True

    async def _read_frame(self, r: asyncio.StreamReader) -> tuple[int, bytes] | None:
        b1, b2 = await asyncio.wait_for(r.readexactly(2), IDLE_TIMEOUT)
        fin, opcode, masked, n = b1 & 0x80, b1 & 0x0F, b2 & 0x80, b2 & 0x7F
        if not fin or not masked or opcode not in (1, 8, 9, 10):
            return None                                     # fragmentiert, unmaskiert, binär: Protokollfehler
        if n == 126:
            n = struct.unpack(">H", await r.readexactly(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", await r.readexactly(8))[0]
        if n > MAX_MESSAGE_BYTES:
            return None                                     # vor dem Lesen abgelehnt
        mask = await r.readexactly(4)
        data = bytearray(await r.readexactly(n))
        for i in range(n):
            data[i] ^= mask[i % 4]
        return opcode, bytes(data)

    async def _session(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        loop = asyncio.get_running_loop()
        failures = 0
        while True:
            frame = await self._read_frame(r)
            if frame is None:
                w.write(encode_frame(8, struct.pack(">H", 1002)))
                await w.drain()
                return
            opcode, data = frame
            if opcode == 8:
                w.write(encode_frame(8, data[:2]))
                await w.drain()
                return
            if opcode == 9:
                w.write(encode_frame(10, data))
            elif opcode == 1:
                reply = await loop.run_in_executor(None, self._core.handle, data.decode("utf-8", "replace"))
                if not json.loads(reply).get("ok"):
                    failures += 1
                w.write(encode_frame(1, reply.encode()))
                if failures >= MAX_FAILURES:
                    await w.drain()
                    return
            await w.drain()
