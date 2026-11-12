"""API-Typ `system.stats`: Auslastung des eigenen Rechners für das Panel „Systemzustand“ (nur lesen).

Antwort: {"cpu", "memory", "gpu", "disk", "battery", "net", "system", "warn_at"}. Jeder Wert ist einzeln abgesichert:
ist er nicht lesbar, steht dort `null` und die Oberfläche zeigt „unbekannt“. Quellen nur lokal und ohne Netz:
Windows-Funktionen über ctypes (GetSystemTimes, GlobalMemoryStatusEx, GetSystemPowerStatus, GetTickCount64, GetIfTable),
`shutil.disk_usage` und `nvidia-smi` (verstecktes Fenster, Zeitlimit, höchstens alle 5 s). Keine Namen, Adressen oder Pfade
in der Antwort, kein ActionGate (nichts wird ausgeführt). Auf anderen Systemen als Windows ist fast alles `null`.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from ..gpu import _nvidia_smi
from ..procflags import hidden
from .protocol import ApiCore

WARN_AT = 80                 # ab hier warnt die Oberfläche (Prozent und °C)
GPU_EVERY = 5.0              # nvidia-smi höchstens alle 5 s
GPU_TIMEOUT = 2.0
GB = 1024 ** 3


class WinProbes:
    """Rohwerte vom Betriebssystem. Jede Methode darf werfen; der Aufrufer macht daraus `null`."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("nur Windows")
        import ctypes
        from ctypes import wintypes
        self._c, self._w = ctypes, wintypes
        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._iphlp = ctypes.WinDLL("iphlpapi")

    def cpu_times(self) -> tuple[int, int]:
        """(beschäftigt, gesamt) in 100-ns-Einheiten seit dem Start; Kernel-Zeit enthält die Leerlaufzeit."""
        ft = self._w.FILETIME
        idle, kernel, user = ft(), ft(), ft()
        if not self._k32.GetSystemTimes(self._c.byref(idle), self._c.byref(kernel), self._c.byref(user)):
            raise OSError("GetSystemTimes")
        v = lambda f: (f.dwHighDateTime << 32) | f.dwLowDateTime          # noqa: E731
        total = v(kernel) + v(user)
        return total - v(idle), total

    def memory(self) -> tuple[int, int]:
        """(gesamt, frei) in Byte."""
        c = self._c

        class MemStatus(c.Structure):
            _fields_ = [("dwLength", c.c_ulong), ("dwMemoryLoad", c.c_ulong), ("ullTotalPhys", c.c_ulonglong),
                        ("ullAvailPhys", c.c_ulonglong), ("ullTotalPageFile", c.c_ulonglong), ("ullAvailPageFile", c.c_ulonglong),
                        ("ullTotalVirtual", c.c_ulonglong), ("ullAvailVirtual", c.c_ulonglong), ("ullAvailExtendedVirtual", c.c_ulonglong)]
        s = MemStatus()
        s.dwLength = c.sizeof(MemStatus)
        if not self._k32.GlobalMemoryStatusEx(c.byref(s)):
            raise OSError("GlobalMemoryStatusEx")
        return s.ullTotalPhys, s.ullAvailPhys

    def battery(self) -> tuple[bool, int | None, bool | None]:
        """(Akku vorhanden, Prozent oder None, am Netz oder None)."""
        c = self._c

        class Power(c.Structure):
            _fields_ = [("ACLineStatus", c.c_ubyte), ("BatteryFlag", c.c_ubyte), ("BatteryLifePercent", c.c_ubyte),
                        ("SystemStatusFlag", c.c_ubyte), ("BatteryLifeTime", c.c_ulong), ("BatteryFullLifeTime", c.c_ulong)]
        p = Power()
        if not self._k32.GetSystemPowerStatus(c.byref(p)):
            raise OSError("GetSystemPowerStatus")
        if p.BatteryFlag == 128:                         # kein Akku eingebaut
            return False, None, None
        pct = None if p.BatteryLifePercent == 255 else int(p.BatteryLifePercent)
        ac = None if p.ACLineStatus == 255 else p.ACLineStatus == 1
        return True, pct, ac

    def uptime_s(self) -> int:
        self._k32.GetTickCount64.restype = self._c.c_ulonglong
        return int(self._k32.GetTickCount64() // 1000)

    def net_octets(self) -> tuple[int, int]:
        """(empfangen, gesendet) in Byte über alle laufenden Ethernet- und WLAN-Adapter.
        Windows listet Filtertreiber als eigene Zeilen mit denselben Zählern: je Hardware-Adresse zählt nur die größte Zeile."""
        c = self._c

        class IfRow(c.Structure):
            _fields_ = [("wszName", c.c_wchar * 256), ("dwIndex", c.c_ulong), ("dwType", c.c_ulong), ("dwMtu", c.c_ulong),
                        ("dwSpeed", c.c_ulong), ("dwPhysAddrLen", c.c_ulong), ("bPhysAddr", c.c_ubyte * 8),
                        ("dwAdminStatus", c.c_ulong), ("dwOperStatus", c.c_ulong), ("dwLastChange", c.c_ulong),
                        ("dwInOctets", c.c_ulong), ("dwInUcastPkts", c.c_ulong), ("dwInNUcastPkts", c.c_ulong),
                        ("dwInDiscards", c.c_ulong), ("dwInErrors", c.c_ulong), ("dwInUnknownProtos", c.c_ulong),
                        ("dwOutOctets", c.c_ulong), ("dwOutUcastPkts", c.c_ulong), ("dwOutNUcastPkts", c.c_ulong),
                        ("dwOutDiscards", c.c_ulong), ("dwOutErrors", c.c_ulong), ("dwOutQLen", c.c_ulong),
                        ("dwDescrLen", c.c_ulong), ("bDescr", c.c_ubyte * 256)]
        size = c.c_ulong(0)
        self._iphlp.GetIfTable(None, c.byref(size), False)
        buf = c.create_string_buffer(size.value)
        if self._iphlp.GetIfTable(buf, c.byref(size), False) != 0:
            raise OSError("GetIfTable")
        count = c.c_ulong.from_buffer(buf).value
        rows = (IfRow * count).from_buffer(buf, c.sizeof(c.c_ulong))
        best: dict[bytes, tuple[int, int]] = {}
        for r in rows:
            if r.dwType not in (6, 71) or r.dwOperStatus != 5 or not r.dwPhysAddrLen:   # Ethernet/WLAN, verbunden
                continue
            mac = bytes(r.bPhysAddr[:r.dwPhysAddrLen])
            if mac not in best or r.dwInOctets + r.dwOutOctets > sum(best[mac]):
                best[mac] = (r.dwInOctets, r.dwOutOctets)
        return sum(v[0] for v in best.values()), sum(v[1] for v in best.values())

    def gpu(self) -> tuple[float, int, int, float | None]:
        """(Auslastung %, VRAM belegt MB, VRAM gesamt MB, Temperatur °C) der größten NVIDIA-Karte."""
        exe = _nvidia_smi()
        if not exe:
            raise OSError("kein nvidia-smi")
        out = subprocess.run([exe, "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=GPU_TIMEOUT,
                             check=False, **hidden())
        return parse_gpu(out.stdout if out.returncode == 0 else "")


def parse_gpu(csv: str) -> tuple[float, int, int, float | None]:
    cards = []
    for line in csv.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 4:
            continue
        try:
            temp = float(parts[3]) if parts[3] not in ("", "[N/A]") else None
            cards.append((float(parts[0]), int(float(parts[1])), int(float(parts[2])), temp))
        except ValueError:
            continue
    if not cards:
        raise ValueError("keine Karte")
    return max(cards, key=lambda g: g[2])


def os_label() -> str | None:
    if os.name != "nt":
        return None
    try:
        build = int(platform.version().split(".")[-1])
    except (ValueError, IndexError):
        build = 0
    return "Windows 11" if build >= 22000 else f"Windows {platform.release()}"


def _pct(part: float, whole: float) -> float:
    return round(100.0 * part / whole, 1) if whole > 0 else 0.0


class SystemStats:
    """Hält die letzten Zählerstände, um CPU-Last und Netzdurchsatz als Unterschied zwischen zwei Abfragen zu rechnen."""

    def __init__(self, probes: Any, disk_path: Path, clock: Callable[[], float] = time.monotonic,
                 os_name: Callable[[], str | None] = os_label):
        self._p, self._disk, self._clock, self._os = probes, disk_path, clock, os_name
        self._cpu: tuple[int, int] | None = None
        self._net: tuple[float, int, int] | None = None
        self._gpu: tuple[float, dict[str, Any] | None] | None = None
        self._lock = threading.Lock()                    # die API kann mehrere Abfragen gleichzeitig bedienen

    @staticmethod
    def _safe(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except Exception:                                # noqa: BLE001 (ein fehlender Wert darf die Antwort nie stören)
            return None

    def _cpu_val(self) -> dict[str, Any] | None:
        busy, total = self._p.cpu_times()
        prev, self._cpu = self._cpu, (busy, total)
        if prev is None or total <= prev[1]:
            return None                                  # erster Abruf: noch kein Unterschied
        return {"percent": max(0.0, min(100.0, _pct(busy - prev[0], total - prev[1])))}

    def _mem_val(self) -> dict[str, Any]:
        total, free = self._p.memory()
        used = total - free
        return {"percent": _pct(used, total), "used_gb": round(used / GB, 1), "total_gb": round(total / GB, 1)}

    def _disk_val(self) -> dict[str, Any]:
        u = shutil.disk_usage(self._disk)
        return {"percent": _pct(u.used, u.total), "used_gb": round(u.used / GB), "total_gb": round(u.total / GB)}

    def _battery_val(self) -> dict[str, Any]:
        present, pct, ac = self._p.battery()
        return {"present": present, "percent": pct, "on_ac": ac}

    def _net_val(self) -> dict[str, Any] | None:
        now = self._clock()
        rx, tx = self._p.net_octets()
        prev, self._net = self._net, (now, rx, tx)
        if prev is None or now <= prev[0]:
            return None
        dt = now - prev[0]
        wrap = lambda d: d + 2 ** 32 if d < 0 else d          # noqa: E731 (32-bit-Zähler laufen über)
        return {"down_mbit": round(wrap(rx - prev[1]) * 8 / dt / 1e6, 1), "up_mbit": round(wrap(tx - prev[2]) * 8 / dt / 1e6, 1)}

    def _gpu_val(self) -> dict[str, Any] | None:
        now = self._clock()
        if self._gpu is not None and now - self._gpu[0] < GPU_EVERY:
            return self._gpu[1]
        val = None
        try:
            util, used, total, temp = self._p.gpu()
            val = {"percent": util, "vram_used_mb": used, "vram_total_mb": total, "temp_c": None if temp is None else round(temp)}
        except Exception:                                # noqa: BLE001
            val = None
        self._gpu = (now, val)                           # auch Fehlschläge merken: nicht jede Abfrage nvidia-smi starten
        return val

    def read(self) -> dict[str, Any]:
        with self._lock:
            return self._read()

    def _read(self) -> dict[str, Any]:
        s = self._safe
        return {
            "cpu": s(self._cpu_val),
            "memory": s(self._mem_val),
            "gpu": s(self._gpu_val),
            "disk": s(self._disk_val),
            "battery": s(self._battery_val),
            "net": s(self._net_val),
            "system": {"os": s(self._os), "uptime_s": s(self._p.uptime_s)},
            "warn_at": WARN_AT,
        }


class _NoProbes:
    def __getattr__(self, _name: str) -> Callable[[], Any]:
        def missing() -> Any:
            raise OSError("nicht verfügbar")
        return missing


def register_system(core: ApiCore, root: Path, probes: Any = None) -> None:
    if probes is None:
        try:
            probes = WinProbes()
        except Exception:                                # noqa: BLE001 (kein Windows: alles unbekannt)
            probes = _NoProbes()
    stats = SystemStats(probes, Path(root).resolve().anchor or Path(root))
    core.register("system.stats", lambda _msg: stats.read())
