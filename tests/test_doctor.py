from kushima.doctor import FILES, run_checks


def test_missing_files_are_reported(tmp_path):
    checks = run_checks(tmp_path)
    by = {c.name: c for c in checks}
    assert not by["Whisper-Modell"].ok and not by["Ollama"].ok
    assert by["Notaus nicht aktiv"].ok


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
    assert not by["Vault vorhanden"].ok and not by["Stimmprofil eingeschrieben"].ok
    by = {c.name: c for c in run_checks(tmp_path, lambda: "kein-profil")}
    assert by["Vault vorhanden"].ok and not by["Stimmprofil eingeschrieben"].ok
    by = {c.name: c for c in run_checks(tmp_path, lambda: "ok")}
    assert by["Vault vorhanden"].ok and by["Stimmprofil eingeschrieben"].ok
