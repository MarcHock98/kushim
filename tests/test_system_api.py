"""`system.stats`: nur lesen, jeder Wert einzeln abgesichert, CPU/Netz als Unterschied, nvidia-smi selten und mit Zeitlimit."""
import json
import os

import pytest

from kushim.api import system_api
from kushim.api.protocol import ApiCore, new_token
from kushim.api.system_api import SystemStats, parse_gpu, register_system

GB = 1024 ** 3


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class Fake:
    def __init__(self):
        self.cpu = [(0, 0)]
        self.net = (0, 0)
        self.gpu_calls = 0
        self.gpu_fail = False

    def cpu_times(self):
        return self.cpu[-1]

    def memory(self):
        return 16 * GB, 4 * GB

    def battery(self):
        return True, 87, True

    def uptime_s(self):
        return 3600

    def net_octets(self):
        return self.net

    def gpu(self):
        self.gpu_calls += 1
        if self.gpu_fail:
            raise OSError("kein nvidia-smi")
        return 22.0, 3100, 8192, 58.0


def stats(fake, clock=None):
    return SystemStats(fake, os.getcwd(), clock=clock or Clock(), os_name=lambda: "Windows 11")


def test_first_call_has_no_cpu_or_net_then_differences_are_used():
    f, clock = Fake(), Clock()
    s = stats(f, clock)
    first = s.read()
    assert first["cpu"] is None and first["net"] is None                     # ehrlich: noch kein Unterschied
    f.cpu.append((340, 1000))                                                 # 34 % beschäftigt
    f.net = (5_000_000, 1_000_000)
    clock.t += 2.0
    r = s.read()
    assert r["cpu"] == {"percent": 34.0}
    assert r["net"] == {"down_mbit": 20.0, "up_mbit": 4.0}
    assert r["memory"] == {"percent": 75.0, "used_gb": 12.0, "total_gb": 16.0}
    assert r["battery"] == {"present": True, "percent": 87, "on_ac": True}
    assert r["system"] == {"os": "Windows 11", "uptime_s": 3600}
    assert r["warn_at"] == 80
    assert 0 <= r["disk"]["percent"] <= 100


def test_net_counters_that_wrap_around_stay_positive():
    f, clock = Fake(), Clock()
    s = stats(f, clock)
    f.net = (2 ** 32 - 1000, 0)
    s.read()
    f.net, clock.t = (1000, 0), clock.t + 1.0
    assert s.read()["net"]["down_mbit"] == pytest.approx(0.016, abs=0.1)


def test_each_failing_value_becomes_null_and_the_rest_still_arrives():
    class Broken(Fake):
        def memory(self):
            raise OSError("weg")

        def battery(self):
            raise OSError("weg")
    r = stats(Broken()).read()
    assert r["memory"] is None and r["battery"] is None
    assert r["gpu"]["percent"] == 22.0


def test_nvidia_smi_runs_at_most_every_five_seconds_also_after_failure():
    f, clock = Fake(), Clock()
    s = stats(f, clock)
    s.read(); s.read()
    assert f.gpu_calls == 1
    clock.t += system_api.GPU_EVERY
    f.gpu_fail = True
    assert s.read()["gpu"] is None and f.gpu_calls == 2
    s.read()
    assert f.gpu_calls == 2                                                  # Fehlschlag wird auch gemerkt


def test_parse_gpu_picks_the_largest_card_and_tolerates_missing_temperature():
    assert parse_gpu("10, 500, 4096, 40\n31, 1300, 8192, [N/A]\n") == (31.0, 1300, 8192, None)
    with pytest.raises(ValueError):
        parse_gpu("kaputt\n")


def test_api_type_answers_without_windows_too(tmp_path):
    core = ApiCore(token := new_token())

    class Nothing:
        def __getattr__(self, _):
            def missing():
                raise OSError("nicht verfügbar")
            return missing
    register_system(core, tmp_path, probes=Nothing())
    r = json.loads(core.handle(json.dumps({"token": token, "type": "system.stats"})))
    assert r["ok"] is True and r["cpu"] is None and r["memory"] is None and r["gpu"] is None
    assert set(r) >= {"cpu", "memory", "gpu", "disk", "battery", "net", "system", "warn_at"}


def test_answer_contains_no_names_addresses_or_paths(tmp_path):
    r = json.dumps(stats(Fake()).read())
    assert str(tmp_path) not in r and os.getcwd() not in r and "\\\\" not in r
    for key in ("host", "ip", "name", "mac", "path"):
        assert f'"{key}"' not in r
