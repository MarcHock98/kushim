import pytest

from kushim.config import Config
from kushim.memory import open_store
from kushim.memory.local import LocalStore
from kushim.memory.migrate import backup, migrate

KEY = "ab" * 32


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("KUSHIM_VAULT_KEY", KEY)


def make_cfg(tmp_path, **kw):
    cfg = Config(path=tmp_path / "config.toml", memory_location=f"local:{tmp_path / 'v1'}", **kw)
    with open_store(cfg, create=True) as s:
        s.add_fact("Marc trinkt Kaffee schwarz", kind="preference")
        s.log_episode("user", "Hallo")
        s.set_profile("stil", "direkt")
    return cfg


def test_roundtrip_and_encryption(tmp_path):
    cfg = make_cfg(tmp_path)
    with open_store(cfg) as s:
        assert s.search_facts("Kaffee")[0].kind == "preference"
        assert s.get_profile() == {"stil": "direkt"}
    raw = (tmp_path / "v1" / "memory.db").read_bytes()
    assert b"Kaffee" not in raw and not raw.startswith(b"SQLite format")


def test_wrong_key_fails(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    monkeypatch.setenv("KUSHIM_VAULT_KEY", "cd" * 32)
    with pytest.raises(Exception):
        open_store(cfg)


def test_migrate_switches_location_and_keeps_old(tmp_path):
    cfg = make_cfg(tmp_path)
    target = tmp_path / "v2"
    migrate(cfg, f"local:{target}")
    assert cfg.memory_location == f"local:{target}"
    assert "v2" in cfg.path.read_text()
    with open_store(cfg) as s:
        assert s.counts()["facts"] == 1
    assert (tmp_path / "v1" / "memory.db").exists()


def test_migrate_with_unusual_config_keeps_old_location_and_says_so(tmp_path):
    from kushim.memory.migrate import ConfigNotSwitched
    cfg = make_cfg(tmp_path)
    text = f'memory = {{location = "local:{(tmp_path / "v1").as_posix()}"}}\n'     # gültig, aber Inline-Tabelle
    cfg.path.write_text(text, encoding="utf-8")
    target = tmp_path / "v2"
    with pytest.raises(ConfigNotSwitched) as err:
        migrate(cfg, f"local:{target}")
    assert err.value.dst == target and (target / "memory.db").exists()              # die Kopie ist da
    assert cfg.path.read_text(encoding="utf-8") == text                             # Config zeigt weiter auf den alten Ort
    assert cfg.memory_location == f"local:{tmp_path / 'v1'}"
    with open_store(Config.load(cfg.path)) as s:                                    # alter Vault bleibt benutzbar
        assert s.counts()["facts"] == 1


def test_cli_migrate_with_unusual_config_prints_one_clear_message(tmp_path, monkeypatch, capsys):
    from kushim import cli
    cfg = make_cfg(tmp_path)
    text = f'memory = {{location = "local:{(tmp_path / "v1").as_posix()}"}}\n'
    cfg.path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("KUSHIM_CONFIG", str(cfg.path))
    assert cli._main(["memory", "migrate", "--to", f"local:{tmp_path / 'v2'}"]) == 3
    out = capsys.readouterr().out
    assert "Vault-Kopie liegt geprüft" in out and "alten Vault" in out and "Traceback" not in out
    assert "Migriert nach" not in out and cfg.path.read_text(encoding="utf-8") == text


def test_backup_rotation(tmp_path):
    cfg = make_cfg(tmp_path, backup_target=str(tmp_path / "nas"), backup_keep=2)
    import time
    for _ in range(3):
        backup(cfg)
        time.sleep(1.1)
    assert len(list((tmp_path / "nas").glob("vault-*"))) == 2
