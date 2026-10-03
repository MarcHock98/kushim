import pytest

from kushima.config import Config
from kushima.memory import open_store
from kushima.memory.local import LocalStore
from kushima.memory.migrate import backup, migrate
from kushima.privacy import EgressDenied, EgressGate

KEY = "ab" * 32


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("KUSHIMA_VAULT_KEY", KEY)


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
    monkeypatch.setenv("KUSHIMA_VAULT_KEY", "cd" * 32)
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


def test_backup_rotation(tmp_path):
    cfg = make_cfg(tmp_path, backup_target=str(tmp_path / "nas"), backup_keep=2)
    import time
    for _ in range(3):
        backup(cfg)
        time.sleep(1.1)
    assert len(list((tmp_path / "nas").glob("vault-*"))) == 2


def test_egress_gate(tmp_path):
    send = lambda p: "ok"
    assert_denied = lambda g, **kw: pytest.raises(EgressDenied)
    with pytest.raises(EgressDenied):
        EgressGate(False, lambda d, p: True).send("claude", "x", True, send)  # Modus A
    with pytest.raises(EgressDenied):
        EgressGate(True, lambda d, p: True).send("claude", "x", False, send)  # nicht vom Nutzer
    with pytest.raises(EgressDenied):
        EgressGate(True, lambda d, p: False).send("claude", "x", True, send)  # abgelehnt
    assert EgressGate(True, lambda d, p: True).send("claude", "x", True, send) == "ok"


def test_wake_words_from_config(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('[voice]' + chr(10) + 'wake_words = ["hey_jarvis", "alexa"]' + chr(10), encoding="utf-8")
    assert Config.load(f).wake_words == ["hey_jarvis", "alexa"]
    assert Config.load(tmp_path / "fehlt.toml").wake_words == ["hey_jarvis"]


def test_legacy_env_and_keyring_service_still_work(monkeypatch):
    from kushima.memory import keys
    monkeypatch.delenv("KUSHIMA_VAULT_KEY", raising=False)
    monkeypatch.setenv("KUSHIM_VAULT_KEY", "aa" * 32)
    assert keys.get_or_create_key("v1") == "aa" * 32


def test_legacy_keyring_key_is_found_and_copied(monkeypatch):
    from kushima.memory import keys
    monkeypatch.delenv("KUSHIMA_VAULT_KEY", raising=False)
    monkeypatch.delenv("KUSHIM_VAULT_KEY", raising=False)
    store = {(keys.LEGACY_SERVICE, "v1"): "bb" * 32}
    monkeypatch.setattr(keys.keyring, "get_password", lambda s, u: store.get((s, u)))
    monkeypatch.setattr(keys.keyring, "set_password", lambda s, u, k: store.__setitem__((s, u), k))
    assert keys.get_or_create_key("v1") == "bb" * 32
    assert store[(keys.SERVICE, "v1")] == "bb" * 32           # unter dem neuen Namen abgelegt
    assert store[(keys.LEGACY_SERVICE, "v1")] == "bb" * 32    # alter Eintrag bleibt


def test_default_location_keeps_existing_legacy_vault(tmp_path, monkeypatch):
    from kushima import config
    monkeypatch.setattr(config.Path, "home", classmethod(lambda cls: tmp_path))
    assert config.default_memory_location() == "local:~/kushima-vault"
    (tmp_path / "kushim-vault").mkdir()
    assert config.default_memory_location() == "local:~/kushim-vault"
    (tmp_path / "kushima-vault").mkdir()
    assert config.default_memory_location() == "local:~/kushima-vault"
