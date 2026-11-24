"""Sprachausgabe-Worker (Kokoro „Martin“): Protokollrahmen, WAV-Prüfung, Umgebung, Client gegen einen Fake-Worker
(Absturz, Hänger, Notaus, CPU-Rückfall, Abbruch) und - falls vorhanden - der echte Worker."""
import io
import json
import os
import struct
import sys
import threading
import time
import wave
from pathlib import Path

import pytest

from kushim.safety.killswitch import KillSwitch
from kushim.voice import ttsworker as tw
from kushim.voice.tts import TTSCancelled, TTSUnavailable

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "scripts" / "kokoro_worker.py"
FAKE = Path(__file__).resolve().parent / "fixtures" / "fake_tts_worker.py"
ASSETS = Path(os.environ.get("KUSHIM_MODELS_ROOT") or ROOT)      # venv und Modell liegen nicht im Git (auch nicht im Worktree)


def load_worker_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("kokoro_worker_for_tests", WORKER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                 # ohne Nebenwirkung: die Netzsperre greift erst in main()
    return mod


def wav(seconds=0.1, rate=24000, channels=1, width=2, frames=None):
    buf = io.BytesIO()
    n = int(seconds * rate) if frames is None else frames
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x01" * (n * channels * width))
    return buf.getvalue()


# --- Rahmen --------------------------------------------------------------------------------------------------------------

def test_frame_roundtrip_with_and_without_payload():
    data = tw.encode_frame({"type": "synth", "id": 1, "epoch": 0, "text": "Grüße"}) + tw.encode_frame({"type": "audio", "id": 1}, b"xyz")
    s = io.BytesIO(data)
    assert tw.read_frame(s) == ({"type": "synth", "id": 1, "epoch": 0, "text": "Grüße"}, b"")
    assert tw.read_frame(s) == ({"type": "audio", "id": 1, "bytes": 3}, b"xyz")
    with pytest.raises(EOFError):
        tw.read_frame(s)


@pytest.mark.parametrize("raw", [
    struct.pack(">I", 0),                                                # leerer Kopf
    struct.pack(">I", tw.MAX_HEADER + 1) + b"{",                         # zu großer Kopf: wird gar nicht erst gelesen
    struct.pack(">I", 0xFFFFFFFF),
    struct.pack(">I", 5) + b"nojsn",
    struct.pack(">I", 2) + b"\xff\xfe",
    struct.pack(">I", 3) + b"[1]",
    struct.pack(">I", 2) + b"{}",                                        # kein Typ
    struct.pack(">I", 11) + b'{"type":1}x'[:11],
])
def test_broken_frames_are_protocol_errors(raw):
    with pytest.raises((tw.ProtocolError, EOFError)):
        tw.read_frame(io.BytesIO(raw))


@pytest.mark.parametrize("n", [-1, True, "5", 1.5, tw.MAX_PAYLOAD + 1])
def test_bad_or_too_large_payload_length_is_rejected_before_reading(n):
    head = json.dumps({"type": "audio", "bytes": n}).encode()

    class Guard(io.BytesIO):
        def read(self, size=-1):
            assert size is None or size < 1_000_000, "darf keine riesige Menge anfordern"
            return super().read(size)
    with pytest.raises(tw.ProtocolError):
        tw.read_frame(Guard(struct.pack(">I", len(head)) + head))


def test_truncated_frames_end_with_eof():
    full = tw.encode_frame({"type": "audio", "id": 2}, b"0123456789")
    for cut in (2, 6, len(full) - 3):
        with pytest.raises(EOFError):
            tw.read_frame(io.BytesIO(full[:cut]))


def test_encoder_refuses_oversized_frames():
    with pytest.raises(tw.ProtocolError):
        tw.encode_frame({"type": "synth", "text": "x" * (tw.MAX_HEADER + 10)})
    with pytest.raises(tw.ProtocolError):
        tw.encode_frame({"type": "audio"}, b"\0" * (tw.MAX_PAYLOAD + 1))


def test_client_and_worker_framing_are_identical_both_ways():
    kw = load_worker_module()
    assert kw.MAX_HEADER == tw.MAX_HEADER and kw.MAX_PAYLOAD == tw.MAX_PAYLOAD and kw.MAX_TEXT == tw.MAX_TEXT
    for header, payload in (({"type": "synth", "id": 3, "epoch": 1, "text": "Größe 1,5 m"}, b""),
                            ({"type": "audio", "id": 3, "epoch": 1}, wav())):
        assert kw.encode_frame(header, payload) == tw.encode_frame(header, payload)
        assert kw.read_frame(io.BytesIO(tw.encode_frame(header, payload)))[1] == payload
        assert tw.read_frame(io.BytesIO(kw.encode_frame(header, payload)))[1] == payload
    for raw in (struct.pack(">I", tw.MAX_HEADER + 1), struct.pack(">I", 3) + b"[1]"):
        with pytest.raises(kw.ProtocolError):
            kw.read_frame(io.BytesIO(raw))


# --- Worker-Ablauf (Server) ohne Prozess ---------------------------------------------------------------------------------

class Pipe(io.BytesIO):
    def flush(self):
        pass


def frames_in(data):
    s, out = io.BytesIO(data), []
    while True:
        try:
            out.append(tw.read_frame(s))
        except EOFError:
            return out


def test_server_answers_validates_and_honours_cancel():
    kw = load_worker_module()

    class Eng:
        def __init__(self):
            self.texts = []

        def synth(self, text):
            self.texts.append(text)
            return wav()
    eng, out = Eng(), Pipe()
    srv = kw.Server(eng, out, "cpu")
    srv.handle({"type": "synth", "id": 1, "epoch": 0, "text": "Hallo."})
    srv.handle({"type": "synth", "id": 2, "epoch": 0, "text": ""})                     # leer
    srv.handle({"type": "synth", "id": True, "epoch": 0, "text": "x"})                 # bool statt Zahl
    srv.handle({"type": "synth", "id": 3, "epoch": 0, "text": "x" * (kw.MAX_TEXT + 1)})
    srv.min_epoch = 2                                                                    # cancel mit Epoche 2 kam an
    srv.handle({"type": "synth", "id": 4, "epoch": 1, "text": "verworfen"})
    srv.handle({"type": "synth", "id": 5, "epoch": 2, "text": "Neu."})
    got = [(h["type"], h.get("id"), h.get("code")) for h, _ in frames_in(out.getvalue())]
    assert got == [("audio", 1, None), ("error", 2, "bad_request"), ("error", True, "bad_request"),
                   ("error", 3, "bad_request"), ("error", 4, "cancelled"), ("audio", 5, None)]
    assert eng.texts == ["Hallo.", "Neu."]


def test_server_reports_cuda_errors_only_on_the_gpu_and_never_the_text():
    kw = load_worker_module()

    class Eng:
        def synth(self, text):
            raise RuntimeError("CUDA failure 2: out of memory")
    for provider, code in (("cuda", "cuda"), ("cpu", "synth")):
        out = Pipe()
        kw.Server(Eng(), out, provider).handle({"type": "synth", "id": 1, "epoch": 0, "text": "Geheimer Satz"})
        (h, _), = frames_in(out.getvalue())
        assert h["code"] == code and "Geheimer" not in json.dumps(h)


def test_server_read_loop_stops_cleanly_on_garbage_or_end():
    kw = load_worker_module()
    for data in (b"", b"\x00\x00\x00\x05nojsn", tw.encode_frame({"type": "unbekannt"})):
        srv = kw.Server(None, Pipe(), "cpu")
        srv.read_loop(io.BytesIO(data))
        assert srv.quit and srv.next_job() is None


# --- WAV-Prüfung ---------------------------------------------------------------------------------------------------------

def test_check_wav_accepts_16bit_mono():
    assert tw.check_wav(wav(0.5)) == (24000, 12000)


@pytest.mark.parametrize("data", [
    b"", b"RIFF", b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 40, b"not a wav file at all" * 3,
    wav(channels=2), wav(width=1), wav(rate=4000), wav(rate=96000), wav(frames=0),
    wav(seconds=121, rate=8000), wav(0.5)[:-100],
], ids=["leer", "kurz", "nur-kopf", "text", "stereo", "8bit", "4kHz", "96kHz", "ohne-frames", "zu-lang", "abgeschnitten"])
def test_check_wav_rejects_everything_else(data):
    with pytest.raises(ValueError):
        tw.check_wav(data)


# --- Umgebung ------------------------------------------------------------------------------------------------------------

def test_worker_env_is_an_allowlist_without_tokens():
    base = {"SystemRoot": r"C:\Windows", "PATH": r"C:\x", "TEMP": r"C:\t", "ANTHROPIC_API_KEY": "sk-1", "KUSHIM_TOKEN": "t",
            "HF_TOKEN": "hf", "GITHUB_TOKEN": "gh", "HTTPS_PROXY": "http://proxy", "PYTHONPATH": r"C:\evil", "USERPROFILE": "u",
            "CUDA_DEVICE_ORDER": "PCI_BUS_ID"}
    env = tw.worker_env(base)
    assert env["SYSTEMROOT"] == r"C:\Windows" and env["PATH"] == r"C:\x" and env["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"
    assert env["HF_HUB_OFFLINE"] == "1" and env["TRANSFORMERS_OFFLINE"] == "1"
    assert set(env) <= set(tw.ALLOWED_ENV) | set(tw.OFFLINE_ENV)
    assert not any(v in env.values() for v in ("sk-1", "t", "hf", "gh", "http://proxy", r"C:\evil", "u"))


def test_spawn_hides_the_window_and_passes_only_the_allowlist(monkeypatch, tmp_path):
    from kushim import procflags
    monkeypatch.setattr(procflags.os, "name", "nt")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "geheim")
    seen = {}

    def popen(argv, **kw):
        seen.update(kw, argv=argv)
        raise OSError("nur geprüft")
    w = tw.KokoroWorker(lambda p: ["python", "-I", "w.py", "--provider", p], popen=popen, restart_pauses=(60,),
                        kill=lambda pid: None)
    w.start()
    assert seen["creationflags"] == 0x08000000 and seen["stdin"] is tw.subprocess.PIPE and seen["stdout"] is tw.subprocess.PIPE
    assert "ANTHROPIC_API_KEY" not in seen["env"] and "geheim" not in seen["env"].values()
    assert seen["argv"][-1] == "cuda" and w.state == "loading" and w.provider == "cpu"     # Startfehler: nächster Versuch CPU
    w.kill()


# --- Client gegen Fake-Worker --------------------------------------------------------------------------------------------

class Spawns:
    """Merkt sich jeden Start (Provider) und jedes kill_tree."""

    def __init__(self):
        self.providers, self.killed = [], []


def fake_worker(mode, spawns=None, provider="cuda", delay=0.5, **kw):
    spawns = spawns if spawns is not None else Spawns()

    def command(p):
        spawns.providers.append(p)
        return [sys.executable, "-I", str(FAKE), str(WORKER), "--mode", mode, "--provider", p, "--delay", str(delay)]

    def kill(pid):
        spawns.killed.append(pid)
        tw.kill_tree(pid)
    opts = dict(restart_pauses=(0.05,), load_timeout=10.0, watchdog=lambda text: 1.5, kill=kill)
    opts.update(kw)
    w = tw.KokoroWorker(command, provider, **opts)
    w.states = []
    w.on_state = w.states.append
    w.notes = []
    w.on_note = w.notes.append
    return w, spawns


def wait_for(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_fake_worker_roundtrip_and_clean_close():
    w, spawns = fake_worker("ok")
    try:
        w.start()
        assert w.wait_ready(15) and w.state == "ready" and w.active == "cuda"
        rate, frames = tw.check_wav(w.synthesize("Hallo Welt."))
        assert rate == 24000 and frames > 0
        proc = w._proc
    finally:
        w.close()
    assert w.state == "off" and proc.wait(timeout=5) is not None
    assert spawns.killed == [proc.pid]                     # nach quit sicherheitshalber kill_tree
    with pytest.raises(TTSUnavailable):
        w.synthesize("Nach dem Ende.")


def test_crash_restarts_with_pause_and_gives_up_after_three():
    w, spawns = fake_worker("crash")
    try:
        w.start()
        assert w.wait_ready(15)
        for _ in range(3):
            with pytest.raises(TTSUnavailable):
                w.synthesize("Absturz.")
            assert wait_for(lambda: w.state != "loading")
            if w.state == "failed":
                break
        assert wait_for(lambda: w.state in ("failed", "cpu", "ready"))
        while w.state != "failed":                         # weitere Abstürze bis zur Grenze
            with pytest.raises(TTSUnavailable):
                w.synthesize("Absturz.")
            assert wait_for(lambda: w.state != "loading")
        assert w.state == "failed" and len(spawns.providers) == 1 + tw.MAX_RESTARTS
        assert spawns.providers[0] == "cuda" and set(spawns.providers[1:]) == {"cpu"}        # nach GPU-Absturz: CPU
        assert any("Text mit Hinweiston" in n for n in w.notes)
        time.sleep(0.3)
        assert len(spawns.providers) == 1 + tw.MAX_RESTARTS                                     # kein weiterer Versuch
    finally:
        w.close()


def test_hang_is_caught_by_the_watchdog_and_the_worker_comes_back_on_the_cpu():
    w, spawns = fake_worker("hang_cuda")
    try:
        w.start()
        assert w.wait_ready(15) and w.active == "cuda"
        t0 = time.monotonic()
        with pytest.raises(TTSUnavailable):
            w.synthesize("Hängt.")
        assert time.monotonic() - t0 < 4                     # Watchdog 1,5 s
        assert len(spawns.killed) == 1
        assert w.wait_ready(15) and w.state == "cpu" and spawns.providers == ["cuda", "cpu"]
        tw.check_wav(w.synthesize("Jetzt auf dem Prozessor."))
    finally:
        w.close()


def test_gpu_load_failure_restarts_on_the_cpu():
    w, spawns = fake_worker("load_fail_cuda")
    try:
        w.start()
        assert w.wait_ready(15)
        assert w.state == "cpu" and spawns.providers == ["cuda", "cpu"] and w.states[:1] == ["loading"]
        assert any("Laden gescheitert (GPU)" in n for n in w.notes)
        tw.check_wav(w.synthesize("Läuft."))
    finally:
        w.close()


def test_cuda_error_while_speaking_restarts_on_the_cpu():
    w, spawns = fake_worker("cuda_error")
    try:
        w.start()
        assert w.wait_ready(15) and w.state == "ready"
        with pytest.raises(TTSUnavailable):
            w.synthesize("GPU voll.")
        assert w.wait_ready(15) and w.state == "cpu" and spawns.providers == ["cuda", "cpu"]
        tw.check_wav(w.synthesize("Weiter auf der CPU."))
    finally:
        w.close()


def test_worker_without_cuda_reports_cpu_and_stays_there():
    w, spawns = fake_worker("cpu_ready")
    try:
        w.start()
        assert w.wait_ready(15) and w.state == "cpu" and w.provider == "cpu" and w.active == "cpu"
    finally:
        w.close()


@pytest.mark.parametrize("mode", ["garbage", "big_frame", "bad_wav"])
def test_broken_answers_never_reach_the_speaker(mode):
    w, spawns = fake_worker(mode)
    try:
        w.start()
        assert w.wait_ready(15)
        with pytest.raises(TTSUnavailable):
            w.synthesize("Kaputt.")
        if mode != "bad_wav":                              # kaputter Rahmen: Worker gilt als abgestürzt
            assert wait_for(lambda: len(spawns.providers) == 2)
    finally:
        w.close()


def test_load_timeout_kills_and_retries():
    w, spawns = fake_worker("no_ready", load_timeout=0.5)
    try:
        w.start()
        assert wait_for(lambda: len(spawns.providers) >= 2, timeout=10) and spawns.killed
        assert not w.wait_ready(0.2)
    finally:
        w.close()


def test_kill_switch_kills_the_worker_and_it_stays_off(tmp_path):
    w, spawns = fake_worker("slow", delay=5.0)
    w.start()
    assert w.wait_ready(15)
    proc = w._proc
    errors = []

    def speak():
        try:
            w.synthesize("Langer Satz.")
        except Exception as e:                             # noqa: BLE001
            errors.append(e)
    t = threading.Thread(target=speak)
    t.start()
    time.sleep(0.2)
    kill = KillSwitch(tmp_path, [w.kill])
    t0 = time.monotonic()
    kill.fire()
    t.join(timeout=3)
    assert not t.is_alive() and time.monotonic() - t0 < 2
    assert isinstance(errors[0], (TTSUnavailable, TTSCancelled))
    assert w.state == "off" and spawns.killed == [proc.pid]
    assert proc.wait(timeout=5) is not None
    time.sleep(0.3)
    assert len(spawns.providers) == 1 and w.state == "off"            # nach dem Notaus kein Neustart
    w.start()
    assert len(spawns.providers) == 1                                  # auch nicht auf Nachfrage


def test_cancel_ends_the_wait_at_once_and_stale_audio_is_dropped():
    w, spawns = fake_worker("slow", delay=0.6)
    try:
        w.start()
        assert w.wait_ready(15)
        result = {}

        def speak():
            try:
                w.synthesize("Wird abgebrochen.")
            except TTSCancelled as e:
                result["cancelled"] = e
        t = threading.Thread(target=speak)
        t.start()
        time.sleep(0.15)
        t0 = time.monotonic()
        w.cancel()
        t.join(timeout=2)
        assert "cancelled" in result and time.monotonic() - t0 < 0.5
        data = w.synthesize("Neuer Satz, etwas länger als der alte.")      # die alte Antwort kommt noch, wird verworfen
        assert tw.check_wav(data)[1] == int(24000 * (0.05 + 0.01 * len("Neuer Satz, etwas länger als der alte.") / 10))
    finally:
        w.close()


def test_states_follow_the_documented_set():
    w, _ = fake_worker("ok")
    try:
        w.start()
        assert w.wait_ready(15)
    finally:
        w.close()
    assert w.states == ["loading", "ready", "off"] and set(w.states) <= set(tw.STATES)


def test_restart_window_forgets_old_crashes():
    clock = {"t": 0.0}
    w, spawns = fake_worker("crash", clock=lambda: clock["t"])
    try:
        w.start()
        for _ in range(6):                                  # weit auseinander: nie mehr als 3 in 10 Minuten
            assert w.wait_ready(15)
            with pytest.raises(TTSUnavailable):
                w.synthesize("Absturz.")
            clock["t"] += tw.RESTART_WINDOW + 1
        assert w.wait_ready(15) and w.state == "cpu"
    finally:
        w.close()


# --- echter Worker (nur mit venv und Modell) -----------------------------------------------------------------------------

REAL = (ASSETS / tw.VENV_PYTHON).is_file() and (ASSETS / tw.MODEL_DIR / "kokoro-martin.onnx").is_file()


@pytest.mark.skipif(not REAL, reason="tools/kokoro/venv oder models/kokoro fehlt (KUSHIM_MODELS_ROOT setzen)")
@pytest.mark.parametrize("provider", ["cpu", "cuda"])
def test_real_worker_speaks_martin(provider, tmp_path):
    w = tw.KokoroWorker.for_root(ROOT, provider, assets=ASSETS)
    w._log_path = tmp_path / "tts-worker.log"
    try:
        w.start()
        assert w.wait_ready(120), w.state
        assert w.state in ("ready", "cpu") and (provider == "cuda" or w.state == "cpu")
        rate, frames = tw.check_wav(w.synthesize("Es ist vierzehn Uhr fünfunddreißig."))
        assert rate == 24000 and 1.0 < frames / rate < 6.0
    finally:
        w.close()
    log = (tmp_path / "tts-worker.log").read_text(encoding="utf-8", errors="replace")
    assert "fünfunddreißig" not in log and "Uhr" not in log             # nie der Text im Protokoll
