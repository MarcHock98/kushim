from kushim.doctor import FILES, TTS_PACKAGES, TTS_VENV, run_checks


def test_missing_files_are_reported(tmp_path):
    checks = run_checks(tmp_path)
    by = {c.name: c for c in checks}
    assert not by["Whisper-Modell"].ok and not by["Stimme Kokoro Martin"].ok and "Ollama" not in by
    assert by["Notaus nicht aktiv"].ok
    ids = {c.id: c for c in checks}
    assert not ids["model_tts"].ok and not ids["tts_venv"].ok
    assert "model_piper" not in ids and "pkg_piper" not in ids              # Piper ist entfernt (2026-11-24)


def test_tts_venv_needs_interpreter_and_the_three_packages(tmp_path):
    venv = tmp_path / TTS_VENV
    (venv / "Scripts").mkdir(parents=True)
    (venv / "Scripts" / "python.exe").write_text("x")
    for pkg in TTS_PACKAGES[:-1]:
        (venv / "Lib" / "site-packages" / pkg).mkdir(parents=True)
        (venv / "Lib" / "site-packages" / pkg / "__init__.py").write_text("")
    assert not {c.id: c for c in run_checks(tmp_path)}["tts_venv"].ok            # espeakng_loader fehlt
    last = venv / "Lib" / "site-packages" / TTS_PACKAGES[-1]
    last.mkdir(parents=True)
    (last / "__init__.py").write_text("")
    assert {c.id: c for c in run_checks(tmp_path)}["tts_venv"].ok


def test_present_files_ok(tmp_path):
    for _, rel in FILES:
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    by = {c.name: c for c in run_checks(tmp_path)}
    assert all(by[n].ok for n, _ in FILES)


def test_kill_marker_is_flagged(tmp_path):
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "KILL").write_text("KILL")
    assert not {c.name: c for c in run_checks(tmp_path)}["Notaus nicht aktiv"].ok


def test_vault_states(tmp_path):
    by = {c.name: c for c in run_checks(tmp_path, lambda: "kein-vault")}
    assert not by["Vault vorhanden"].ok and "Stimmprofil eingeschrieben" not in by       # keine Sprecher-Prüfung mehr
    by = {c.name: c for c in run_checks(tmp_path, lambda: "ok")}
    assert by["Vault vorhanden"].ok
