"""Stimmklon-Engine: Kindprozess-Protokoll, Fehlerfälle, Ersatzstimme, Netz- und Umgebungs-Schutz (alles mit Fake-Prozess, ohne Torch)."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kushim.voice.tts import CloneEngine, FallbackEngine


class FakeProc:
    def __init__(self, lines, wav=b"RIFFfake", write_wav=True, dead=False):
        self.lines, self.wav, self.write_wav, self.dead, self.killed = list(lines), wav, write_wav, dead, False
        self.stdin = self
        self.stdout = self
        self.sent = []

    def readline(self):
        return self.lines.pop(0) if self.lines else ""

    def write(self, s):
        self.sent.append(json.loads(s))
        if self.write_wav:
            Path(self.sent[-1]["out"]).write_bytes(self.wav)

    def flush(self):
        pass

    def poll(self):
        return 1 if self.dead or self.killed else None

    def kill(self):
        self.killed = True


def engine(tmp_path, proc, **kw):
    spawned = []

    def popen(argv, **k):
        spawned.append((argv, k))
        return proc

    e = CloneEngine("py", "worker.py", "ref.wav", str(tmp_path / "out"), popen=popen, ready_timeout=1, job_timeout=1, **kw)
    return e, spawned


def ready():
    return json.dumps({"ok": True, "ready": True}) + "\n"


def ok():
    return json.dumps({"ok": True}) + "\n"


def test_synthesize_roundtrip_and_cleanup(tmp_path):
    proc = FakeProc([ready(), ok(), ok()])
    e, spawned = engine(tmp_path, proc)
    assert e.synthesize("Hallo Welt.") == b"RIFFfake" and e.synthesize("Noch ein Satz.") == b"RIFFfake"
    assert len(spawned) == 1                                                       # Worker bleibt geladen
    assert proc.sent[0]["text"] == "Hallo Welt." and Path(proc.sent[0]["out"]).parent == tmp_path / "out"
    assert not list((tmp_path / "out").glob("*.wav"))                              # Zwischendateien gelöscht


def test_child_gets_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "geheim")
    monkeypatch.setenv("KUSHIM_TOKEN", "geheim")
    monkeypatch.setenv("MY_PASSWORD", "geheim")
    proc = FakeProc([ready(), ok()])
    e, spawned = engine(tmp_path, proc)
    e.synthesize("Hallo.")
    env = spawned[0][1]["env"]
    assert "PATH" in env or "Path" in env or os.name == "nt"
    assert not any("KEY" in k or "TOKEN" in k or "PASSWORD" in k or k.startswith("KUSHIM") for k in env)


def test_worker_not_ready_or_silent_raises(tmp_path):
    for lines in ([""], ["kaputt\n"], [json.dumps({"ok": True}) + "\n"]):
        e, _ = engine(tmp_path, FakeProc(lines))
        with pytest.raises(RuntimeError):
            e.synthesize("Hallo.")


def test_job_error_and_missing_wav_raise_and_close(tmp_path):
    proc = FakeProc([ready(), json.dumps({"ok": False, "error": "CUDA out of memory"}) + "\n"])
    e, _ = engine(tmp_path, proc)
    with pytest.raises(RuntimeError, match="CUDA"):
        e.synthesize("Hallo.")
    proc2 = FakeProc([ready(), ok()], write_wav=False)
    e2, _ = engine(tmp_path, proc2)
    with pytest.raises(RuntimeError):
        e2.synthesize("Hallo.")
    assert proc2.killed


def test_dead_worker_is_restarted_once_per_call(tmp_path):
    procs = [FakeProc([ready(), ok()]), FakeProc([ready(), ok()])]
    spawned = []

    def popen(argv, **k):
        spawned.append(1)
        return procs[len(spawned) - 1]

    e = CloneEngine("py", "w.py", "r.wav", str(tmp_path / "o"), popen=popen, ready_timeout=1, job_timeout=1)
    e.synthesize("Eins.")
    procs[0].dead = True
    e.synthesize("Zwei.")
    assert len(spawned) == 2


def test_fallback_engine_uses_piper_after_failure_and_stays_there():
    class Bad:
        calls = 0

        def synthesize(self, text):
            self.calls += 1
            raise RuntimeError("Der Stimmklon startet nicht")

    class Good:
        def synthesize(self, text):
            return b"piper"

    notes = []
    bad = Bad()
    f = FallbackEngine(bad, Good(), notes.append)
    assert f.synthesize("a") == b"piper" and f.synthesize("b") == b"piper"
    assert bad.calls == 1 and len(notes) == 1                                      # nicht bei jedem Satz neu versuchen


def test_fallback_engine_prefers_primary():
    class P:
        def synthesize(self, t):
            return b"klon"
    assert FallbackEngine(P(), P()).synthesize("x") == b"klon"


# --- Worker-Skript (ohne Torch): Netzsperre wirkt wirklich
def test_worker_blocks_network_in_process():
    worker = Path(__file__).resolve().parents[1] / "scripts" / "clone_worker.py"
    r = subprocess.run([sys.executable, str(worker), "--ref", "x", "--out-dir", "y", "--selftest-network"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "GESPERRT" in r.stdout, r.stdout + r.stderr


def test_worker_source_has_no_upload_or_download_code():
    src = (Path(__file__).resolve().parents[1] / "scripts" / "clone_worker.py").read_text(encoding="utf-8")
    for bad in ("requests", "urllib", "httpx", "snapshot_download", "hf_hub_download", "upload", "push_to_hub"):
        assert bad not in src, bad
    assert "HF_HUB_OFFLINE" in src and "block_network()" in src


# --- Voraussetzungen und Auswahl (voice/clone.py)
def _wav(path: Path, seconds: float, sr=24000):
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"\x00\x00" * int(sr * seconds))


def test_pick_reference_closest_to_ten_seconds(tmp_path):
    from kushim.voice.clone import pick_reference
    for name, sec in (("a", 2.0), ("b", 8.5), ("c", 14.0), ("d", 11.0)):
        _wav(tmp_path / f"{name}.wav", sec)
    assert pick_reference(tmp_path).name == "d.wav"
    assert pick_reference(tmp_path / "leer") is None
    assert pick_reference(tmp_path, str(tmp_path / "c.wav")).name == "c.wav" and pick_reference(tmp_path, str(tmp_path / "x.wav")) is None


def test_missing_reports_each_prerequisite_and_build_falls_back(tmp_path):
    from kushim.voice import clone
    assert "Klon-Umgebung" in clone.missing(tmp_path)
    p = clone.paths(tmp_path)
    p["python"].parent.mkdir(parents=True)
    p["python"].write_text("")
    assert "nicht geladen" in clone.missing(tmp_path)
    p["hf"].mkdir(parents=True)
    (p["hf"] / "m.safetensors").write_text("")
    assert "Aufnahme" in clone.missing(tmp_path)
    p["recordings"].mkdir(parents=True)
    _wav(p["recordings"] / "01.wav", 9.0)
    assert clone.missing(tmp_path) == ""
    notes, piper = [], object()
    assert clone.build(tmp_path / "nichts", piper, on_note=notes.append) is piper and "Piper bleibt" in notes[0]
    built = clone.build(tmp_path, piper)
    assert isinstance(built, FallbackEngine) and built.fallback is piper and isinstance(built.primary, CloneEngine)


def test_clone_is_off_by_default_and_read_from_config(tmp_path):
    from kushim.config import Config
    assert Config().voice_clone is False
    f = tmp_path / "c.toml"
    f.write_text('[voice]\nclone = true\nclone_ref = "x.wav"\n', encoding="utf-8")
    c = Config.load(f)
    assert c.voice_clone is True and c.voice_clone_ref == "x.wav"
