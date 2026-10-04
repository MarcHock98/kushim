import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

from kushim import appstart
from kushim.safety import killswitch
from kushim.voice import statefile


class Proc:
    def __init__(self, args, alive=True, pid=4242):
        self.args, self._alive, self.pid = args, alive, pid
        self.terminated = self.killed = False
        self.waited = False

    def poll(self):
        return None if self._alive else 1

    def wait(self, timeout=None):
        self.waited = True
        return 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class Popper:
    def __init__(self, backend_alive=True):
        self.procs, self.backend_alive = [], backend_alive

    def __call__(self, args, **kw):
        is_ui = str(args[0]).endswith("kushim-ui.exe")
        p = Proc(args, alive=True if is_ui else self.backend_alive)
        self.procs.append(p)
        return p


def make_root(tmp_path, with_exe=True):
    if with_exe:
        exe = tmp_path / appstart.UI_EXE
        exe.parent.mkdir(parents=True)
        exe.write_text("x")
    return tmp_path


def ready(root, since, alive=lambda: True, **kw):
    return True


def run(root, popper, voice=True, wait=ready, monkeypatch=None):
    said = []
    code = appstart.run(root, voice=voice, popen=popper, say=said.append, wait=wait)
    return code, said


def test_backend_command_is_talk_with_ui_or_serve():
    root = Path("x")
    assert appstart.backend_args(root, True)[-3:] == ["kushim.cli", "talk", "--ui"] or appstart.backend_args(root, True)[-2:] == ["talk", "--ui"]
    assert appstart.backend_args(root, False)[-1] == "serve"


def test_active_killswitch_falls_back_to_serve_so_the_window_can_show_and_clear_it(tmp_path):
    killswitch.trigger(tmp_path)
    assert appstart.backend_args(tmp_path, True)[-1] == "serve"


def test_missing_app_gives_build_hint_and_starts_nothing(tmp_path):
    popper = Popper()
    code, said = run(make_root(tmp_path, with_exe=False), popper)
    assert code == 2 and "npx tauri build" in said[0] and popper.procs == []


def test_starts_backend_then_window_and_stops_only_its_own_backend_when_the_window_closes(tmp_path, monkeypatch):
    killed = []
    monkeypatch.setattr(appstart, "kill_tree", killed.append)
    popper = Popper()
    code, said = run(make_root(tmp_path), popper)
    assert code == 0 and len(popper.procs) == 2
    backend, ui = popper.procs
    assert backend.args[-2:] == ["talk", "--ui"] and str(ui.args[0]).endswith("kushim-ui.exe")
    assert ui.waited and backend.terminated and killed == [4242]


def test_reuses_a_running_voice_service_and_never_stops_it(tmp_path, monkeypatch):
    killed = []
    monkeypatch.setattr(appstart, "kill_tree", killed.append)
    statefile.StatePublisher(tmp_path).phase("idle")                   # frisches Lebenszeichen
    popper = Popper()
    code, said = run(make_root(tmp_path), popper)
    assert code == 0 and len(popper.procs) == 1 and str(popper.procs[0].args[0]).endswith("kushim-ui.exe")
    assert killed == [] and "läuft schon" in said[0]


def test_voice_service_that_dies_early_falls_back_to_the_api_only(tmp_path, monkeypatch):
    monkeypatch.setattr(appstart, "kill_tree", lambda pid: None)
    popper = Popper(backend_alive=False)
    calls = []

    def wait(root, since, alive=lambda: True, **kw):
        calls.append(alive())
        return len(calls) >= 2                                           # erster Versuch scheitert, zweiter (serve) klappt
    code, said = run(make_root(tmp_path), popper, wait=wait)
    assert code == 0
    assert popper.procs[0].args[-2:] == ["talk", "--ui"] and popper.procs[1].args[-1] == "serve"
    assert any("ohne Sprache" in s for s in said)


def test_backend_that_never_gets_ready_gives_an_error_and_cleans_up(tmp_path, monkeypatch):
    killed = []
    monkeypatch.setattr(appstart, "kill_tree", killed.append)
    popper = Popper()
    code, said = run(make_root(tmp_path), popper, wait=lambda *a, **k: False)
    assert code == 1 and any("nicht bereit" in s for s in said)
    assert len(popper.procs) == 1 and popper.procs[0].terminated and killed == [4242]      # kein Fenster, Dienst beendet


def test_backend_is_stopped_even_if_the_window_crashes(tmp_path, monkeypatch):
    monkeypatch.setattr(appstart, "kill_tree", lambda pid: None)

    class Crashy(Popper):
        def __call__(self, args, **kw):
            p = super().__call__(args, **kw)
            if str(args[0]).endswith("kushim-ui.exe"):
                p.wait = lambda timeout=None: (_ for _ in ()).throw(RuntimeError("Fenster abgestürzt"))
            return p
    popper = Crashy()
    try:
        run(make_root(tmp_path), popper)
    except RuntimeError:
        pass
    assert popper.procs[0].terminated


def test_wait_for_api_ignores_a_stale_file_and_accepts_a_fresh_one(tmp_path):
    api = tmp_path / appstart.API_FILE
    api.parent.mkdir()
    api.write_text(json.dumps({"port": 1, "token": "x" * 40}))
    old = time.time() - 3600
    os.utime(api, (old, old))
    t = {"now": 0.0}
    assert appstart.wait_for_api(tmp_path, time.time() - 5, timeout=1.0, clock=lambda: t["now"],
                                 sleep=lambda s: t.__setitem__("now", t["now"] + 0.5)) is False
    os.utime(api, None)
    assert appstart.wait_for_api(tmp_path, time.time() - 5, timeout=1.0, clock=lambda: t["now"], sleep=lambda s: None) is True


def test_wait_for_api_stops_waiting_when_the_backend_is_gone(tmp_path):
    assert appstart.wait_for_api(tmp_path, time.time(), timeout=60, alive=lambda: False, sleep=lambda s: None) is False


def test_module_has_no_network_imports():
    import ast
    tree = ast.parse(Path(appstart.__file__).read_text(encoding="utf-8"))
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | \
           {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not (mods & {"socket", "http.client", "urllib.request", "requests", "websockets", "asyncio"})


def test_own_backend_removes_a_leftover_api_file_when_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(appstart, "kill_tree", lambda pid: None)
    api = tmp_path / appstart.API_FILE
    api.parent.mkdir()
    api.write_text("{}")
    popper = Popper()
    run(make_root(tmp_path), popper)
    assert not api.exists()


def test_reused_service_keeps_its_api_file(tmp_path, monkeypatch):
    monkeypatch.setattr(appstart, "kill_tree", lambda pid: None)
    statefile.StatePublisher(tmp_path).phase("idle")
    api = tmp_path / appstart.API_FILE
    api.parent.mkdir(exist_ok=True)
    api.write_text("{}")
    run(make_root(tmp_path), Popper())
    assert api.exists()                                              # nicht unser Dienst: nichts anfassen
