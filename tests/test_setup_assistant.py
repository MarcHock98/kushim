"""E3 Setup-Assistent, Backend: setup.checks, Schritte claude/folder, audio.get/set, wake.get/set, Verdrahtung in _api_start."""
import json
import sys
import threading
import time
import tomllib
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from kushim.api.protocol import ApiCore, new_token
from kushim.api.setup_api import register_setup, safe_text
from kushim.claude_cli.base import ClaudeProbe, ClaudeState
from kushim.config import Config
from kushim.procflags import hidden
from kushim.safety import killswitch
from kushim.setup import state, status
from kushim.voice import wakeconfig

DEVICES = {"inputs": ["Mikro A", "Mikro B (USB)"], "outputs": ["Box", "Kopfhörer"]}
TOKENISH = "sk-ant-api03-FAKEtokenFAKEtokenFAKEtoken"
READY = ClaudeState(True, (2, 1, 400), True)
SYNC = lambda fn: fn()                                                       # Prüfung im selben Thread (Tests)


def make_api(tmp_path, claude=lambda: READY, folders_ok=lambda: True, list_devices=lambda: DEVICES, audit=None,
             config_file=None):
    token = new_token()
    core = ApiCore(token)
    cfgfile = config_file or tmp_path / "config.toml"
    register_setup(core, tmp_path, lambda: "ok", list_devices=list_devices, audit=audit, claude=claude,
                   folders_ok=folders_ok, load_config=lambda: Config.load(cfgfile))

    def call(type_, **kw):
        return json.loads(core.handle(json.dumps({"token": token, "type": type_, **kw})))
    call.core, call.token, call.cfg = core, token, cfgfile
    return call


@pytest.fixture()
def api(tmp_path):
    return make_api(tmp_path)


# --- setup.checks ---------------------------------------------------------------------------------------------------

def test_checks_lists_doctor_and_claude_checks_with_fixed_ids(api):
    r = api("setup.checks")
    assert r["ok"] is True and isinstance(r["checks"], list)
    ids = [c["id"] for c in r["checks"]]
    assert {"pkg_faster_whisper", "model_whisper", "model_piper", "model_kws", "gpu_libs", "kill_off", "vault",
            "claude_installed", "claude_version", "claude_login"} <= set(ids)
    assert len(ids) == len(set(ids))
    for c in r["checks"]:
        assert set(c) == {"id", "label", "ok", "hint"} and isinstance(c["ok"], bool)
        assert isinstance(c["label"], str) and c["label"] and isinstance(c["hint"], str)
        if c["ok"]:
            assert c["hint"] == ""
    by = {c["id"]: c for c in r["checks"]}
    assert not by["model_whisper"].get("ok") and by["model_whisper"]["hint"]           # tmp_path hat keine Modelle
    assert by["claude_login"]["ok"] and by["claude_version"]["ok"] and by["kill_off"]["ok"]


def test_checks_show_missing_claude_and_old_or_logged_out_claude(tmp_path):
    r = make_api(tmp_path, claude=lambda: ClaudeState(False))("setup.checks")
    claude = [c for c in r["checks"] if c["id"].startswith("claude")]
    assert claude == [{"id": "claude_installed", "label": "Claude Code installiert", "ok": False,
                       "hint": "Claude Code installieren und `claude auth login`"}]
    r = make_api(tmp_path, claude=lambda: ClaudeState(True, (2, 1, 1), False))("setup.checks")
    by = {c["id"]: c for c in r["checks"]}
    assert by["claude_installed"]["ok"] and not by["claude_version"]["ok"] and not by["claude_login"]["ok"]
    assert by["claude_login"]["hint"] == "claude auth login"


def test_checks_survive_a_failing_probe_without_system_text(tmp_path):
    def boom():
        raise OSError(f"C:\\Users\\x\\{TOKENISH}\\claude.exe")
    api = make_api(tmp_path, claude=boom)
    r = api("setup.checks")
    blob = json.dumps(r)
    assert r["ok"] and TOKENISH not in blob and "Users" not in blob
    assert any(c["id"] == "claude_installed" and not c["ok"] for c in r["checks"])


class FakeRun:
    """Gefälschte Claude CLI: zählt Aufrufe, liefert Version und eine Anmeldung samt Daten, die nie nach außen dürfen."""

    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw))
        if argv[-1] == "--version":
            out = "2.1.400 (Claude Code)"
        else:
            out = json.dumps({"loggedIn": True, "authMethod": "claude.ai", "email": "geheim@example.com",
                              "orgId": TOKENISH, "token": TOKENISH})
        return SimpleNamespace(stdout=out, returncode=0)


def fake_claude_exe(tmp_path):
    exe = tmp_path / TOKENISH / "claude.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"x")
    return exe


def test_checks_contain_no_paths_tokens_or_account_data(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", TOKENISH)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", TOKENISH)
    exe = fake_claude_exe(tmp_path)
    probe = ClaudeProbe(find=lambda: exe, run=FakeRun(), spawn=SYNC)
    api = make_api(tmp_path, claude=probe.get)
    blob = json.dumps([api("setup.checks"), api("setup.status")])
    for leak in (TOKENISH, "geheim", "example.com", str(tmp_path), "Users", "claude.exe", "AppData", "sk-ant", api.token):
        assert leak not in blob, leak
    assert ":\\" not in blob and ":/" not in blob


def test_claude_cli_runs_at_most_once_per_30_seconds_and_hidden(tmp_path):
    exe = fake_claude_exe(tmp_path)
    run, t = FakeRun(), [100.0]
    probe = ClaudeProbe(find=lambda: exe, run=run, clock=lambda: t[0], spawn=SYNC)
    api = make_api(tmp_path, claude=probe.get)
    for _ in range(5):
        assert api("setup.checks")["ok"] and api("setup.status")["ok"]
    kinds = [c[0][-1] for c in run.calls]
    assert kinds == ["--version", "--json"]                                  # Version einmal je Datei, Anmeldung einmal
    t[0] += 29
    api("setup.checks")
    assert len(run.calls) == 2
    t[0] += 2                                                                # 31 s später: genau ein neuer Aufruf
    api("setup.checks")
    api("setup.status")
    assert [c[0][-1] for c in run.calls] == ["--version", "--json", "--json"]
    for _argv, kw in run.calls:                                              # nie ein Konsolenfenster, nie fremde Schlüssel
        assert all(kw.get(k) == v for k, v in hidden().items())
        assert not any(k.startswith("ANTHROPIC_") or k.startswith("KUSHIM_") for k in kw["env"])


def test_claude_probe_is_safe_from_parallel_api_threads(tmp_path):
    exe = fake_claude_exe(tmp_path)
    run = FakeRun()
    probe = ClaudeProbe(find=lambda: exe, run=run, spawn=SYNC)
    threads = [threading.Thread(target=probe.get) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(run.calls) == 2


def test_claude_probe_reads_the_version_again_after_an_update(tmp_path):
    exe = fake_claude_exe(tmp_path)
    run = FakeRun()
    probe = ClaudeProbe(find=lambda: exe, run=run, spawn=SYNC)
    assert probe.get() == ClaudeState(True, (2, 1, 400), True) and probe.get().ready
    exe.write_bytes(b"neue Version")                                         # andere Größe: neues Programm
    probe.get()
    assert [c[0][-1] for c in run.calls].count("--version") == 2
    assert ClaudeProbe(find=lambda: None, run=run, spawn=SYNC).get() == ClaudeState(False)


def test_claude_probe_never_blocks_the_api_and_runs_one_check_at_a_time(tmp_path):
    exe = fake_claude_exe(tmp_path)
    gate, started = threading.Event(), threading.Event()
    inner = FakeRun()

    def slow_run(argv, **kw):                                                # die CLI hängt, bis der Test sie freigibt
        started.set()
        assert gate.wait(5)
        return inner(argv, **kw)
    probe = ClaudeProbe(find=lambda: exe, run=slow_run)                       # Standard: Prüfung im Hintergrund-Thread
    api = make_api(tmp_path, claude=probe.get)
    t0 = time.monotonic()
    r = api("setup.checks")
    s = api("setup.status")
    for _ in range(5):
        assert probe.get().checking
    assert time.monotonic() - t0 < 2 and started.wait(2)
    assert [c for c in r["checks"] if c["id"].startswith("claude")] == [
        {"id": "claude_checking", "label": "Claude Code wird geprüft", "ok": False, "hint": ""}]
    assert step(s, "claude") == {"step": "claude", "title": "Claude Code", "status": "open", "detail": "Wird geprüft"}
    gate.set()
    deadline = time.monotonic() + 5
    while probe.get().checking and time.monotonic() < deadline:
        time.sleep(0.01)
    assert probe.get() == ClaudeState(True, (2, 1, 400), True)
    assert [c[0][-1] for c in inner.calls] == ["--version", "--json"]       # genau eine Prüfung trotz vieler Anfragen
    assert {c["id"] for c in api("setup.checks")["checks"]} >= {"claude_installed", "claude_version", "claude_login"}


def test_claude_probe_survives_a_failing_cli_and_a_failing_thread_start(tmp_path):
    exe = fake_claude_exe(tmp_path)

    def broken(argv, **kw):
        raise RuntimeError("kaputt")
    assert ClaudeProbe(find=lambda: exe, run=broken, spawn=SYNC).get() == ClaudeState(True)     # installiert, nicht bereit

    def no_thread(fn):
        raise RuntimeError("keine Threads")
    probe = ClaudeProbe(find=lambda: exe, run=FakeRun(), spawn=no_thread)
    assert probe.get().checking and probe.get().checking                       # nächster Aufruf versucht es erneut


def test_safe_text_drops_paths_and_tokens():
    assert safe_text("Claude Code mindestens 2.1.234 (ist 2.1.310)") == "Claude Code mindestens 2.1.234 (ist 2.1.310)"
    for bad in ("C:\\Users\\x", "D:/kushim", "\\\\nas\\share", "~/geheim", "liegt in /home/x", TOKENISH):
        assert safe_text(bad, "fallback") == "fallback", bad
    assert safe_text("a\x1b[31mb " + "wort " * 60) == ("a[31mb " + "wort " * 60)[:120].strip()
    assert safe_text("x" * 30, "f") == "f"                                   # lange Zeichenkette ohne Leerzeichen: tokenartig
    assert safe_text(None, "f") == "f"


# --- setup.status: Schritte claude und folder ---------------------------------------------------------------------

def step(r, name):
    return next(s for s in r["steps"] if s["step"] == name)


def test_status_has_claude_and_folder_steps_from_facts(tmp_path):
    r = make_api(tmp_path)("setup.status")
    assert [s["step"] for s in r["steps"]] == ["system", "claude", "audio_voice", "wake_words", "folder", "safety"]
    assert step(r, "claude")["status"] == "done" and step(r, "folder")["status"] == "done"
    r = make_api(tmp_path, claude=lambda: ClaudeState(True, (2, 1, 400), False), folders_ok=lambda: False)("setup.status")
    assert step(r, "claude")["status"] == "open" and "angemeldet" in step(r, "claude")["detail"].lower()
    assert step(r, "folder")["status"] == "open" and "kein Ordner" in step(r, "folder")["detail"]
    assert step(make_api(tmp_path, claude=lambda: ClaudeState(False))("setup.status"), "claude")["detail"] == "Claude Code nicht gefunden"
    old = make_api(tmp_path, claude=lambda: ClaudeState(True, (2, 0, 9), True))("setup.status")
    assert step(old, "claude")["status"] == "open" and "zu alt" in step(old, "claude")["detail"]


def test_status_claude_and_folder_failures_stay_neutral(tmp_path):
    def boom():
        raise RuntimeError(f"C:\\geheim\\{TOKENISH}")
    r = make_api(tmp_path, claude=boom, folders_ok=boom)("setup.status")
    blob = json.dumps(r)
    assert r["ok"] and "geheim" not in blob and TOKENISH not in blob
    assert step(r, "claude")["status"] == "open" and step(r, "folder")["status"] == "open"


def test_claude_and_folder_steps_can_be_skipped_but_not_faked(api):
    r = api("setup.skip", step="folder", confirm=True)
    assert r["ok"]
    assert step(r, "folder")["status"] == "done"                           # die Tatsache gewinnt über das Überspringen
    for s in ("claude", "folder"):
        assert api("setup.done", step=s, confirm=True) == {"ok": False, "error": "not_allowed"}


def test_skipped_claude_and_folder_explain_the_consequence(tmp_path):
    api = make_api(tmp_path, claude=lambda: ClaudeState(False), folders_ok=lambda: False)
    api("setup.skip", step="claude", confirm=True)
    r = api("setup.skip", step="folder", confirm=True)
    assert step(r, "claude")["status"] == "skipped" and step(r, "folder")["status"] == "skipped"
    assert any(n.startswith("Claude Code:") for n in r["restricted"]) and any(n.startswith("Arbeitsordner:") for n in r["restricted"])


def test_old_state_file_with_four_steps_stays_valid(tmp_path):
    p = state.path(tmp_path)
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"system": {"status": "skipped", "date": "2026-10-04"},
                             "audio_voice": {"status": "done", "date": "2026-10-04"},
                             "wake_words": {"status": "skipped", "date": "2026-10-04"},
                             "safety": {"status": "done", "date": "2026-10-04"}}), encoding="utf-8")
    loaded = state.load(tmp_path)
    assert loaded["audio_voice"]["status"] == "done" and loaded["claude"]["status"] == "open"
    steps = {s.step: s.status for s in status.compute(tmp_path, lambda: "kein-vault", checks=[])}
    assert steps["audio_voice"] == "done" and steps["safety"] == "done" and steps["claude"] == "open"
    assert steps["folder"] == "open" and steps["wake_words"] == "skipped"


# --- audio.devices: echte Geräteliste, nie ein Stream -------------------------------------------------------------

class NoStream:
    def __init__(self, *a, **k):
        raise AssertionError("Gerät geöffnet")


def fake_sounddevice(monkeypatch):
    import importlib.machinery
    sd = types.ModuleType("sounddevice")
    sd.__spec__ = importlib.machinery.ModuleSpec("sounddevice", None)          # doctor.run_checks fragt find_spec
    sd.query_devices = lambda: [{"name": "Mikro A", "max_input_channels": 1, "max_output_channels": 0},
                                {"name": "Box", "max_input_channels": 0, "max_output_channels": 2},
                                {"name": "Headset", "max_input_channels": 1, "max_output_channels": 2},
                                {"name": "Mikro A", "max_input_channels": 2, "max_output_channels": 0}]
    sd.InputStream = sd.OutputStream = sd.Stream = sd.RawInputStream = NoStream

    def never(*a, **k):
        raise AssertionError("Audio benutzt")
    sd.play = sd.rec = sd.playrec = sd.wait = sd.stop = never
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    return sd


def test_audio_devices_lists_names_without_opening_a_device(tmp_path, monkeypatch):
    fake_sounddevice(monkeypatch)
    from kushim.voice import audio
    api = make_api(tmp_path, list_devices=audio.list_devices)
    assert api("audio.devices") == {"ok": True, "inputs": ["Mikro A", "Headset"], "outputs": ["Box", "Headset"]}


def test_find_device_prefers_the_exact_saved_name(monkeypatch):
    sd = fake_sounddevice(monkeypatch)
    sd.query_devices = lambda: [{"name": "Mikrofon (2- USB)", "max_input_channels": 1, "max_output_channels": 0},
                                {"name": "Mikrofon", "max_input_channels": 1, "max_output_channels": 0}]
    from kushim.voice import audio
    assert audio.find_device("Mikrofon", "input") == 1                         # genauer Name vor Namensteil
    assert audio.find_device("usb", "input") == 0
    with pytest.raises(LookupError):
        audio.find_device("Mikrofon", "output")


class FakeServer:
    cores = []

    def __init__(self, core, *a, **k):
        FakeServer.cores.append(core)

    def start(self):
        return 54321

    def stop(self):
        pass


def test_api_start_wires_devices_checks_audio_wake_level_and_usage(tmp_path, monkeypatch):
    """`kushim serve`: Geräteliste kommt wirklich an (Fehler vor E3a), ohne Sprachprozess kein Pegeltest."""
    from kushim import cli
    import kushim.net.server as net_server
    import kushim.claude_cli.base as base
    fake_sounddevice(monkeypatch)
    FakeServer.cores = []
    monkeypatch.setattr(net_server, "LocalServer", FakeServer)
    monkeypatch.setattr(base, "ClaudeProbe", lambda: SimpleNamespace(get=lambda: READY))
    monkeypatch.setattr(cli, "open_store", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    cfgfile = tmp_path / "config.toml"
    cfgfile.write_text('[audio]\nmic = "Headset"\nout = ""\n', encoding="utf-8")
    monkeypatch.setenv("KUSHIM_CONFIG", str(cfgfile))
    server, store, info = cli._api_start(Config.load(), tmp_path, extra=lambda core, store: None)
    try:
        core = FakeServer.cores[-1]
        token = json.loads(info.read_text(encoding="utf-8"))["token"]

        def call(t, **kw):
            return json.loads(core.handle(json.dumps({"token": token, "type": t, **kw})))
        assert call("audio.devices") == {"ok": True, "inputs": ["Mikro A", "Headset"], "outputs": ["Box", "Headset"]}
        assert call("audio.get") == {"ok": True, "mic": "Headset", "out": ""}
        assert call("setup.checks")["ok"] and call("wake.get")["ok"]
        assert call("voice.level_result") == {"ok": True, "state": "unavailable", "seconds_left": 0.0, "suggestion": None}
        assert call("voice.level_test", confirm=True) == {"ok": False, "error": "unavailable"}
        assert call("usage.get")["available"] is False
        assert step(call("setup.status"), "claude")["status"] == "done"
    finally:
        cli._api_stop(server, store, info)


# --- audio.get / audio.set ([audio] in config.toml) ---------------------------------------------------------------

def test_audio_get_defaults_to_system_devices(api):
    assert api("audio.get") == {"ok": True, "mic": "", "out": ""}


def test_audio_set_writes_audio_section_atomically_and_keeps_the_rest(tmp_path):
    cfgfile = tmp_path / "config.toml"
    cfgfile.write_text('[memory]\nlocation = "local:~/v"\n\n[claude]\nfolders = ["p|C:/p"]\n', encoding="utf-8")
    audits = []
    api = make_api(tmp_path, audit=lambda e, d: audits.append((e, d)))
    r = api("audio.set", mic="Mikro B (USB)", out="Kopfhörer", confirm=True)
    assert r == {"ok": True, "mic": "Mikro B (USB)", "out": "Kopfhörer", "restart_needed": True}
    cfg = Config.load(cfgfile)
    assert (cfg.audio_mic, cfg.audio_out) == ("Mikro B (USB)", "Kopfhörer")
    assert cfg.memory_location == "local:~/v" and cfg.claude_folders == ("p|C:/p",)
    assert api("audio.get") == {"ok": True, "mic": "Mikro B (USB)", "out": "Kopfhörer"}
    assert api("audio.set", mic="", out="Box", confirm=True)["ok"]               # zurück zum Systemstandard
    assert (Config.load(cfgfile).audio_mic, Config.load(cfgfile).audio_out) == ("", "Box")
    assert cfgfile.read_text(encoding="utf-8").count("[audio]") == 1
    assert not list(tmp_path.glob("*.tmp")) and audits == [("setup_audio", "api"), ("setup_audio", "api")]


def test_audio_set_validates_against_the_device_list(api):
    before = api.cfg.exists()
    for kw in ({"mic": "Fremdes Mikro", "out": ""}, {"mic": "", "out": "Mikro A"}, {"mic": "Box", "out": "Box"},
               {"mic": "mikro a", "out": ""}):
        assert api("audio.set", confirm=True, **kw) == {"ok": False, "error": "unknown_device"}, kw
    for kw in ({"mic": None, "out": ""}, {"mic": "", "out": 3}, {"out": ""}, {"mic": ""}, {"mic": "x" * 201, "out": ""},
               {"mic": ["Mikro A"], "out": ""}):
        assert api("audio.set", confirm=True, **kw) == {"ok": False, "error": "bad_request"}, kw
    assert api.cfg.exists() == before is False


def test_audio_set_needs_confirm_and_is_blocked_by_the_kill_switch(api, tmp_path):
    for unsure in ({}, {"confirm": "true"}, {"confirm": 1}, {"confirm": False}):
        assert api("audio.set", mic="Mikro A", out="", **unsure) == {"ok": False, "error": "confirm_required"}
    killswitch.trigger(tmp_path)
    assert api("audio.set", mic="Mikro A", out="", confirm=True) == {"ok": False, "error": "kill"}
    assert api("audio.get") == {"ok": True, "mic": "", "out": ""}               # lesen geht weiter
    assert not api.cfg.exists()


def test_audio_without_device_list_or_with_broken_config_is_neutral(tmp_path):
    api = make_api(tmp_path, list_devices=None)
    assert api("audio.set", mic="Mikro A", out="", confirm=True) == {"ok": False, "error": "unavailable"}
    api.cfg.write_text("[audio\nmic = ", encoding="utf-8")
    assert api("audio.get") == {"ok": False, "error": "broken_file"}
    api2 = make_api(tmp_path)
    assert api2("audio.set", mic="Mikro A", out="", confirm=True) == {"ok": False, "error": "broken_file"}
    assert api.cfg.read_text(encoding="utf-8") == "[audio\nmic = "            # kaputte Datei bleibt unangetastet


AUDIO_VARIANTS = {
    "comment_on_header": ('[memory]\nlocation = "local:~/v"\n\n[audio] # Geräte\nmic = "alt"\nout = ""\n\n[gpu]\nwhisper = "1"\n', True),
    "spaced_header": ('[ audio ]\nmic = "alt"\n[claude]\nfolders = ["p|C:/p"]\n', True),
    "inline_table": ('audio = {mic = "alt"}\n[gpu]\nwhisper = "auto"\n', False),
    "dotted_keys": ('audio.mic = "alt"\naudio.out = ""\n[gpu]\nwhisper = "auto"\n', False),
    "multiline_string": ('[audio]\nnote = """\nmic = "im Text"\n"""\nmic = "alt"\n', False),
}


@pytest.mark.parametrize("name", sorted(AUDIO_VARIANTS))
def test_set_audio_never_corrupts_unusual_but_valid_files(tmp_path, name):
    text, handled = AUDIO_VARIANTS[name]
    f = tmp_path / "config.toml"
    f.write_text(text, encoding="utf-8")
    before = tomllib.loads(text)
    api = make_api(tmp_path)
    r = api("audio.set", mic="Mikro A", out="Box", confirm=True)
    after_text = f.read_text(encoding="utf-8")
    after = tomllib.loads(after_text)                                         # die Datei bleibt immer lesbar
    Config.load(f)
    if handled:
        assert r == {"ok": True, "mic": "Mikro A", "out": "Box", "restart_needed": True}
        expected = {**before, "audio": {**before["audio"], "mic": "Mikro A", "out": "Box"}}
        assert after == expected                                              # alles andere unverändert
    else:
        assert r == {"ok": False, "error": "not_saved"}
        assert after_text == text                                             # nichts geschrieben, nichts umgedeutet
    assert not [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]


def test_config_writers_refuse_a_broken_file_and_keep_it(tmp_path):
    from kushim.config import NotSaved
    f = tmp_path / "config.toml"
    f.write_text("[audio]\nmic = \n", encoding="utf-8")
    with pytest.raises(NotSaved):
        Config(path=f).set_audio("Mikro A", "")
    with pytest.raises(NotSaved):
        Config(path=f).set_claude_folders(["a|C:/a"])
    assert f.read_text(encoding="utf-8") == "[audio]\nmic = \n"


def test_concurrent_config_writers_never_lose_or_break_anything(tmp_path):
    """audio.set (Setup) und claude.folder_* schreiben dieselbe config.toml: eine gemeinsame Sperre, eigene Temp-Dateien."""
    f = tmp_path / "config.toml"
    f.write_text('[memory]\nlocation = "local:~/v"\n', encoding="utf-8")
    errors = []

    def audio_writer(i):
        try:
            for n in range(25):
                Config.load(f).set_audio(f"Mikro {i}-{n}", "")
        except Exception as e:                                                # noqa: BLE001
            errors.append(e)

    def folder_writer():
        try:
            from kushim.config import CONFIG_LOCK
            for n in range(25):
                with CONFIG_LOCK:                                             # wie folders_api: lesen, ändern, schreiben als Einheit
                    cfg = Config.load(f)
                    cfg.set_claude_folders(list(cfg.claude_folders) + [f"f{n}|C:/f{n}"])
        except Exception as e:                                                # noqa: BLE001
            errors.append(e)
    threads = [threading.Thread(target=audio_writer, args=(i,)) for i in range(3)] + [threading.Thread(target=folder_writer)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert errors == []
    cfg = Config.load(f)
    assert len(cfg.claude_folders) == 25 and cfg.audio_mic.startswith("Mikro ") and cfg.memory_location == "local:~/v"
    assert not [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]


def test_folders_api_and_audio_set_share_one_lock(tmp_path):
    import inspect
    from kushim.api import folders_api
    from kushim import config
    src = inspect.getsource(folders_api)
    assert src.count("with CONFIG_LOCK:") == 2 and folders_api.CONFIG_LOCK is config.CONFIG_LOCK
    assert ".toml.tmp" not in inspect.getsource(config)                       # keine gemeinsame feste Temp-Datei mehr


def test_config_reads_audio_untrusted(tmp_path):
    f = tmp_path / "config.toml"
    for text, mic in (('[audio]\nmic = 5\n', ""), ('[audio]\nmic = "a\\u0007b"\n', ""), ('audio = 3\n', ""),
                      (f'[audio]\nmic = "{"x" * 201}"\n', ""), ('[audio]\nmic = "Mikro A"\n', "Mikro A")):
        f.write_text(text, encoding="utf-8")
        assert Config.load(f).audio_mic == mic, text
    with pytest.raises(ValueError):
        Config.load(f).set_audio("a\nb", "")


# --- [audio] wird von talk/start ohne --mic/--out benutzt ------------------------------------------------------------

def test_device_choice_flag_wins_then_saved_then_system_default(monkeypatch):
    from kushim import cli
    from kushim.voice import audio
    seen = []

    def find(name, kind):
        seen.append((name, kind))
        if name == "weg":
            raise LookupError(name)
        return 7
    monkeypatch.setattr(audio, "find_device", find)
    notes = []
    assert cli._device("Flag", "Gemerkt", "input", notes.append) == 7 and seen[-1] == ("Flag", "input")
    assert cli._device(None, "Gemerkt", "output", notes.append) == 7 and seen[-1] == ("Gemerkt", "output")
    assert cli._device(None, "", "input", notes.append) is None and len(seen) == 2
    assert cli._device(None, "weg", "input", notes.append) is None and "Systemstandard" in notes[-1]
    with pytest.raises(LookupError):                                          # ausdrücklich gewählt und weg: Fehler wie bisher
        cli._device("weg", "", "input", notes.append)


class Stop(Exception):
    pass


def test_talk_uses_saved_devices_without_flags(tmp_path, monkeypatch):
    from kushim import cli
    from kushim.voice import audio, talk, talklog
    cfgfile = tmp_path / "config.toml"
    cfgfile.write_text('[audio]\nmic = "Mikro B (USB)"\nout = "Kopfhörer"\n', encoding="utf-8")
    monkeypatch.setenv("KUSHIM_CONFIG", str(cfgfile))
    monkeypatch.setattr(cli, "_gpu_plan", lambda cfg: ([], SimpleNamespace(whisper_device="cpu", whisper_index=0)))
    monkeypatch.setattr(talklog, "TalkLog", lambda path: SimpleNamespace(write=lambda *a, **k: None))
    monkeypatch.setattr(audio, "find_device", lambda name, kind: f"{kind}:{name}")
    got = []

    def build_live(root, out_device, in_device, **kw):
        got.append((out_device, in_device))
        raise Stop()
    monkeypatch.setattr(talk, "build_live", build_live)
    import kushim.safety.killswitch as ks
    monkeypatch.setattr(ks, "is_triggered", lambda root: False)
    with pytest.raises(Stop):
        cli._main(["talk"])
    with pytest.raises(Stop):
        cli._main(["talk", "--mic", "Anders", "--out", "Box"])
    assert got == [("output:Kopfhörer", "input:Mikro B (USB)"), ("output:Box", "input:Anders")]


# --- wake.get / wake.set ----------------------------------------------------------------------------------------------

def test_wake_get_lists_words_with_switches(api):
    r = api("wake.get")
    assert r["ok"] and r["max"] == 12
    assert r["words"][0] == {"phrase": "hey kushim", "enabled": True} and all(set(w) == {"phrase", "enabled"} for w in r["words"])


def test_wake_set_writes_validated_and_keeps_engine_settings(tmp_path, monkeypatch):
    import kushim.voice.wakeconfig as wc
    monkeypatch.setattr(wc, "resolve_wake_words", lambda names, root: names)  # vortrainiertes Modell ohne Download
    cfg = wc.WakeConfig(wc.Settings(speech_level=333.0),
                        (wc.WakeWord("hey kushim", "kws", True, 0.2, 3.0), wc.WakeWord("hey_jarvis", "openwakeword", True, 0.7)))
    wc.save(tmp_path, cfg)
    audits = []
    api = make_api(tmp_path, audit=lambda e, d: audits.append(e))
    assert api("wake.get")["words"] == [{"phrase": "hey kushim", "enabled": True}, {"phrase": "hey_jarvis", "enabled": True}]
    r = api("wake.set", confirm=True, words=[{"phrase": "Hey  Kushim", "enabled": False}, {"phrase": "hey_jarvis", "enabled": True},
                                             {"phrase": "hallo computer", "enabled": True, "id": 3}])
    assert r == {"ok": True, "words": [{"phrase": "hey kushim", "enabled": False}, {"phrase": "hey_jarvis", "enabled": True},
                                       {"phrase": "hallo computer", "enabled": True}], "max": 12, "restart_needed": True}
    loaded = wc.load(tmp_path)
    assert loaded.settings.speech_level == 333.0
    assert loaded.words[0] == wc.WakeWord("hey kushim", "kws", False, 0.2, 3.0)
    assert loaded.words[1] == wc.WakeWord("hey_jarvis", "openwakeword", True, 0.7)
    assert loaded.words[2] == wc.WakeWord("hallo computer", "kws", True)
    assert audits == ["setup_wake"] and not list(tmp_path.glob("*.tmp"))


def test_wake_set_limits(api, tmp_path):
    many = [{"phrase": f"wort {chr(97 + i)}", "enabled": True} for i in range(13)]
    assert api("wake.set", confirm=True, words=many) == {"ok": False, "error": "too_many"}
    assert api("wake.set", confirm=True, words=many[:12])["ok"]
    assert len(api("wake.get")["words"]) == 12
    assert api("wake.set", confirm=True, words=[]) == {"ok": False, "error": "none_enabled"}
    assert api("wake.set", confirm=True, words=[{"phrase": "kushim", "enabled": False}]) == {"ok": False, "error": "none_enabled"}
    for bad_words in ([{"phrase": "hey!", "enabled": True}], [{"phrase": "ab", "enabled": True}],
                      [{"phrase": "kushim", "enabled": True}, {"phrase": " Kushim ", "enabled": True}],
                      [{"phrase": "", "enabled": True}], [{"phrase": "eins zwei drei vier fünf", "enabled": True}],
                      [{"phrase": "../evil.onnx", "enabled": True}]):
        assert api("wake.set", confirm=True, words=bad_words) == {"ok": False, "error": "invalid"}, bad_words
    for malformed in (None, "kushim", {"phrase": "kushim"}, [{"phrase": 3, "enabled": True}], [{"phrase": "kushim"}],
                      [{"phrase": "kushim", "enabled": "ja"}], ["kushim"], [{"phrase": "x" * 61, "enabled": True}]):
        assert api("wake.set", confirm=True, words=malformed) == {"ok": False, "error": "bad_request"}, malformed
    assert len(api("wake.get")["words"]) == 12                                   # nichts davon hat geschrieben


def test_wake_set_needs_confirm_and_is_blocked_by_the_kill_switch(api, tmp_path):
    words = [{"phrase": "kushim", "enabled": True}]
    for unsure in ({}, {"confirm": "yes"}, {"confirm": 1}):
        assert api("wake.set", words=words, **unsure) == {"ok": False, "error": "confirm_required"}
    killswitch.trigger(tmp_path)
    assert api("wake.set", words=words, confirm=True) == {"ok": False, "error": "kill"}
    assert api("wake.get")["ok"] and not (tmp_path / "wakewords.toml").exists()


def test_broken_wake_file_is_reported_and_never_overwritten(api, tmp_path):
    (tmp_path / "wakewords.toml").write_text("[[wakeword]]\nname = 5\nengine = \"nope\"\n", encoding="utf-8")
    assert api("wake.get") == {"ok": False, "error": "broken_file"}
    assert api("wake.set", confirm=True, words=[{"phrase": "kushim", "enabled": True}]) == {"ok": False, "error": "broken_file"}
    assert "nope" in (tmp_path / "wakewords.toml").read_text(encoding="utf-8")


# --- übergreifend ------------------------------------------------------------------------------------------------------

def test_new_types_need_the_token(api):
    for t in ("setup.checks", "audio.get", "audio.set", "wake.get", "wake.set"):
        assert json.loads(api.core.handle(json.dumps({"type": t, "confirm": True}))) == {"ok": False, "error": "unauthorized"}


def test_new_responses_never_contain_paths_or_secrets(api, tmp_path):
    blob = json.dumps([api("setup.checks"), api("audio.get"), api("wake.get"),
                       api("audio.set", mic="Mikro A", out="", confirm=True),
                       api("wake.set", confirm=True, words=[{"phrase": "kushim", "enabled": True}])])
    assert str(tmp_path) not in blob and api.token not in blob and "config.toml" not in blob and "wakewords" not in blob
