"""Migration und Backup. Immer: Snapshot -> verifizieren -> erst dann umschalten. Alte Kopie bleibt."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from ..config import Config
from .local import LocalStore
from .vault import Manifest, parse_location, resolve_local


def _tree_hash(root: Path) -> dict[str, str]:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def verify_copy(src: Path, dst: Path) -> None:
    """Zeilenzahlen aus beiden Datenbanken vergleichen (Snapshot-DB-Bytes dürfen abweichen)."""
    with LocalStore(src) as a, LocalStore(dst) as b:
        if a.counts() != b.counts():
            raise RuntimeError(f"Verifikation fehlgeschlagen: {a.counts()} != {b.counts()}")
    ma, mb = Manifest.read(src), Manifest.read(dst)
    if ma != mb:
        raise RuntimeError("Manifest weicht ab")
    ha, hb = _tree_hash(src), _tree_hash(dst)
    for name in ha.keys() | hb.keys():
        if name != "memory.db" and ha.get(name) != hb.get(name):
            raise RuntimeError(f"Datei weicht ab: {name}")


def migrate(config: Config, target_location: str) -> Path:
    """Kopiert den aktuellen Vault an das Ziel, verifiziert und schaltet die Config um."""
    scheme, rest = parse_location(config.memory_location)
    tscheme, trest = parse_location(target_location)
    if scheme != "local" or tscheme != "local":
        raise NotImplementedError("Aktuell nur local -> local; Remote folgt mit dem NAS-Dienst.")
    src, dst = resolve_local(rest), resolve_local(trest)
    if src == dst:
        raise ValueError("Quelle und Ziel sind identisch")
    with LocalStore(src) as store:
        store.audit("migrate", f"{src} -> {dst}")
        store.snapshot(dst)
    verify_copy(src, dst)
    config.set_memory_location(target_location)
    return dst  # Quelle bleibt unangetastet (Rollback)


def backup(config: Config) -> Path:
    """Verschlüsselter Snapshot ins Backup-Ziel (z.B. NAS-Share). Live-DB bleibt lokal."""
    if not config.backup_target:
        raise ValueError("backup.target ist nicht konfiguriert")
    _, rest = parse_location(config.memory_location)
    base = resolve_local(config.backup_target)
    dest = base / time.strftime("vault-%Y%m%d-%H%M%S")
    with LocalStore(resolve_local(rest)) as store:
        store.snapshot(dest)
    verify_copy(resolve_local(rest), dest)
    snaps = sorted(p for p in base.glob("vault-*") if p.is_dir())
    import shutil
    for old in snaps[:-config.backup_keep]:
        shutil.rmtree(old)
    return dest
