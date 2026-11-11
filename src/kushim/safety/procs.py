"""Prozess-Hilfen ohne Netz: Läuft ein Prozess noch? (für den Channel-Server, der nur Standardmodule und `safety` nutzt)."""
from __future__ import annotations

import os
from typing import Any


def pid_alive(pid: Any) -> bool:
    """Läuft dieser Prozess noch? Unter Windows über OpenProcess (os.kill(pid, 0) würde dort den Prozess BEENDEN)."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(k32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
