import hashlib
import importlib.util
import io
import sys
import tarfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "fetch_models", Path(__file__).resolve().parents[1] / "scripts" / "fetch_models.py")
fm = importlib.util.module_from_spec(SPEC)
sys.modules["fetch_models"] = fm          # Dataclasses im Skript brauchen den Modul-Eintrag
SPEC.loader.exec_module(fm)


def make_archive(files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def patch(monkeypatch, tmp_path, archive, size=None, sha=None):
    monkeypatch.setattr(fm, "ROOT", tmp_path)
    monkeypatch.setattr(fm, "KWS_SIZE", size if size is not None else len(archive))
    monkeypatch.setattr(fm, "KWS_SHA256", sha or hashlib.sha256(archive).hexdigest())
    monkeypatch.setattr(fm.urllib.request, "urlopen", lambda *a, **k: FakeResponse(archive))


def test_kws_download_verified_and_extracted(monkeypatch, tmp_path):
    arc = make_archive({"model/bpe.model": b"x", "model/tokens.txt": b"y"})
    patch(monkeypatch, tmp_path, arc)
    fm.fetch_kws()
    assert (tmp_path / "models" / "kws" / "model" / "bpe.model").read_bytes() == b"x"
    assert not list((tmp_path / "models" / "kws").glob("tmp*"))         # temporäre Dateien weg


def test_kws_wrong_checksum_is_rejected_and_nothing_extracted(monkeypatch, tmp_path):
    arc = make_archive({"model/bpe.model": b"x"})
    patch(monkeypatch, tmp_path, arc, sha="0" * 64)
    with pytest.raises(RuntimeError):
        fm.fetch_kws()
    assert not (tmp_path / "models" / "kws" / "model").exists()


def test_kws_archive_cannot_write_outside_target(monkeypatch, tmp_path):
    arc = make_archive({"../evil.txt": b"boese"})
    patch(monkeypatch, tmp_path, arc)
    with pytest.raises(Exception):
        fm.fetch_kws()
    assert not (tmp_path / "models" / "evil.txt").exists() and not (tmp_path / "evil.txt").exists()


def test_is_ok_checks_size_and_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(fm, "ROOT", tmp_path)
    f = tmp_path / "a.bin"
    f.write_bytes(b"abc")
    good = fm.Item("a.bin", 3, hashlib.sha256(b"abc").hexdigest())
    assert fm.is_ok(good)
    assert not fm.is_ok(fm.Item("a.bin", 4, None))
    assert not fm.is_ok(fm.Item("a.bin", 3, "0" * 64))
    assert not fm.is_ok(fm.Item("fehlt.bin", 3, None))
