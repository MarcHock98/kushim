"""Prüfung 2026-11-24, Sprachausgabe-Worker: Kill-Rückfall, keine Neustarts bei aktivem Notaus, Schreib-Lock für stdin, eigener
Temp-Ordner, keine unwirksamen PYTHON*-Variablen, Telemetrie aus, lange Texte mit dem echten Worker."""
import ast
import os
import threading
import time
from pathlib import Path

import pytest

from kushim.voice import ttsworker as tw
from kushim.voice.speechnorm import normalize
from kushim.voice.tts import TTSUnavailable, Speaker, split_sentences
from test_tts_worker import ASSETS, REAL, ROOT, WORKER, fake_worker, load_worker_module, wait_for

LIST_630 = "Die Liste - " + " - ".join(f"Punkt {w} mit einer kurzen Beschreibung ohne Komma"
                                           for w in ("eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun",
                                                     "zehn", "elf"))
REPEAT = " ".join(["Die Tests laufen jetzt und ich melde mich gleich wieder bei dir"] * 6) + "."


def test_kill_falls_back_to_proc_kill_when_kill_tree_does_not_work():
    w, spawns = fake_worker("ok", kill=lambda pid: None)             # kill_tree wirkungslos
    w.start()
    assert w.wait_ready(15)
    proc = w._proc
    w.kill()
    assert proc.wait(timeout=5) is not None and w.state == "off"


def test_no_start_and_no_restart_while_the_kill_marker_is_set():
    marker = {"on": True}
    w, spawns = fake_worker("ok", blocked=lambda: marker["on"])
    w.start()
    assert spawns.providers == [] and w.state == "off"
    marker["on"] = False
    w2, spawns2 = fake_worker("crash", blocked=lambda: marker["on"])
    try:
        w2.start()
        assert w2.wait_ready(15)
        marker["on"] = True                                           # Notaus über die Oberfläche (nur Marker-Datei)
        with pytest.raises(TTSUnavailable):
            w2.synthesize("Absturz.")
        assert wait_for(lambda: w2.state == "off")
        time.sleep(0.3)
        assert len(spawns2.providers) == 1                            # kein Neustart
    finally:
        w2.close()


def test_for_root_blocks_on_the_real_kill_marker(tmp_path):
    from kushim.safety import killswitch
    killswitch.trigger(tmp_path)
    w = tw.KokoroWorker.for_root(tmp_path, "cpu")
    w.start()
    assert w.state == "off" and w._proc is None


def test_concurrent_cancel_and_synth_never_garble_the_stream():
    w, spawns = fake_worker("slow", delay=0.02)
    try:
        w.start()
        assert w.wait_ready(15)
        stop = threading.Event()

        def hammer():
            while not stop.is_set():
                w.cancel()
        threads = [threading.Thread(target=hammer) for _ in range(4)]
        for t in threads:
            t.start()
        ok = 0
        for _ in range(30):
            try:
                w.synthesize("Ein Satz mit etwas Text, damit der Rahmen nicht winzig ist.")
                ok += 1
            except Exception:                                         # noqa: BLE001 (abgebrochen ist hier erlaubt)
                pass
        stop.set()
        for t in threads:
            t.join()
        assert len(spawns.providers) == 1 and w.state == "ready"      # kein Protokollfehler, kein Absturz
        tw.check_wav(w.synthesize("Danach geht es normal weiter."))
    finally:
        w.close()


def test_worker_env_has_no_ineffective_python_variables_and_its_own_temp(tmp_path):
    assert not any(k.startswith("PYTHON") for k in tw.OFFLINE_ENV)
    w = tw.KokoroWorker.for_root(tmp_path, "cpu")
    assert Path(w._env["TEMP"]) == tmp_path / tw.TEMP_DIR == Path(w._env["TMP"]) and (tmp_path / tw.TEMP_DIR).is_dir()
    kw = load_worker_module()
    assert "ORT_DISABLE_TELEMETRY" not in kw.OFFLINE_ENV and kw.TEMP_NAME == tw.TEMP_DIR.name


def test_worker_cleans_only_its_own_espeak_copies(tmp_path, monkeypatch):
    kw = load_worker_module()
    own = tmp_path / "tts-tmp"
    (own / "tmpabc").mkdir(parents=True)
    (own / "tmpabc" / "espeak-ng.dll").write_bytes(b"x")
    (own / "tmpkeep").mkdir()                                         # ohne DLL: bleibt
    (own / "andere").mkdir()
    (own / "andere" / "espeak-ng.dll").write_bytes(b"x")              # anderer Name: bleibt
    monkeypatch.setenv("TEMP", str(own))
    assert kw.clean_own_temp() == 1
    assert not (own / "tmpabc").exists() and (own / "tmpkeep").exists() and (own / "andere").exists()
    foreign = tmp_path / "Temp"                                       # fremder Temp-Ordner: nichts anfassen
    (foreign / "tmpx").mkdir(parents=True)
    (foreign / "tmpx" / "espeak-ng.dll").write_bytes(b"x")
    monkeypatch.setenv("TEMP", str(foreign))
    assert kw.clean_own_temp() == 0 and (foreign / "tmpx").exists()


def test_worker_disables_onnxruntime_telemetry_before_the_session_and_sets_utf8_stderr():
    tree = ast.parse(WORKER.read_text(encoding="utf-8"))
    klass = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "KokoroEngine")
    init = next(n for n in klass.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    lines = {getattr(n.func, "attr", ""): n.lineno for n in ast.walk(init) if isinstance(n, ast.Call)}
    assert lines["disable_telemetry_events"] < lines["InferenceSession"]
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    calls = [getattr(n.func, "attr", getattr(n.func, "id", "")) for n in ast.walk(main) if isinstance(n, ast.Call)]
    assert "reconfigure" in calls and "clean_own_temp" in calls


def test_halves_splits_near_the_middle_without_losing_text():
    kw = load_worker_module()
    for text in ("eins zwei drei vier fünf sechs", "a" * 50, "Erster Teil, zweiter Teil und noch mehr Text danach."):
        a, b = kw.halves(text)
        assert a and b and (a + b).replace(" ", "") == text.replace(" ", "")


# --- echter Worker: lange Abschnitte --------------------------------------------------------------------------------------

@pytest.mark.skipif(not REAL, reason="tools/kokoro/venv oder models/kokoro fehlt (KUSHIM_MODELS_ROOT setzen)")
def test_real_worker_speaks_long_lists_and_repetitions_completely(tmp_path):
    w = tw.KokoroWorker.for_root(ROOT, "cpu", assets=ASSETS)
    w._log_path = tmp_path / "tts-worker.log"
    try:
        w.start()
        assert w.wait_ready(120), w.state
        for text in (LIST_630, REPEAT):
            audio, missing = [], []
            spk = Speaker(w, audio.append)
            spk.on_unspoken = missing.append
            assert spk.say(split_sentences(text)) >= 1 and missing == []
            seconds = sum(tw.check_wav(a)[1] / 24000 for a in audio)
            # Martin spricht etwa 20–22 Zeichen je Sekunde; abgeschnitten (510 Phoneme) wären es höchstens etwa 10 s
            assert seconds > len(normalize(text)) / 30, (len(text), seconds)
        # ohne Speaker direkt an den Worker: 450 Zeichen ohne Satzzeichen, der Worker teilt nach Phonemen selbst
        long_plain = " ".join(["Wort"] * 90)
        rate, frames = tw.check_wav(w.synthesize(long_plain))
        assert frames / rate > len(long_plain) / 35
    finally:
        w.close()
    assert "Error" not in (tmp_path / "tts-worker.log").read_text(encoding="utf-8", errors="replace")
