"""Lokales Backend: verschlüsselte SQLCipher-DB im Vault-Ordner."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import sqlcipher3

from .keys import get_or_create_key
from .store import Fact, MemoryStore
from .vault import DB_FILE, MANIFEST, SCHEMA_VERSION, SUBDIRS, Manifest, create_vault, is_vault

SCHEMA = """
create table if not exists facts(
  id integer primary key, text text not null, kind text not null, source text not null,
  confidence real not null, created real not null);
create table if not exists episodes(
  id integer primary key, ts real not null, session text, role text not null, text text not null);
create table if not exists feedback(
  id integer primary key, ts real not null, episode_id integer, rating integer not null, note text);
create table if not exists profile(key text primary key, value text not null);
create table if not exists audit(
  id integer primary key, ts real not null, event text not null, detail text);
"""


def _connect(db: Path, key: str):
    con = sqlcipher3.connect(str(db))
    con.execute('pragma key="x\'%s\'"' % key)
    con.execute("select count(*) from sqlite_master")  # schlägt bei falschem Schlüssel fehl
    return con


class LocalStore(MemoryStore):
    def __init__(self, root: Path, create: bool = False, key: str | None = None):
        self.root = root
        if create and not is_vault(root):
            self.manifest = create_vault(root)
        elif is_vault(root):
            self.manifest = Manifest.read(root)
        else:
            raise FileNotFoundError(f"Kein Vault in {root}")
        if self.manifest.schema_version > SCHEMA_VERSION:
            raise RuntimeError("Vault stammt von einer neueren kushim-Version")
        self.key = key or get_or_create_key(self.manifest.vault_id, create=create)
        self.con = _connect(root / DB_FILE, self.key)
        self.con.executescript(SCHEMA)
        self.con.commit()

    def add_fact(self, text, kind="other", source="user", confidence=1.0):
        cur = self.con.execute(
            "insert into facts(text,kind,source,confidence,created) values(?,?,?,?,?)",
            (text, kind, source, confidence, time.time()))
        self.con.commit()
        return cur.lastrowid

    def search_facts(self, query, limit=10):
        rows = self.con.execute(
            "select id,text,kind,source,confidence,created from facts where text like ? "
            "order by created desc limit ?", (f"%{query}%", limit)).fetchall()
        return [Fact(*r) for r in rows]

    def delete_fact(self, fact_id):
        self.con.execute("delete from facts where id=?", (fact_id,))
        self.con.commit()

    def log_episode(self, role, text, session=""):
        cur = self.con.execute("insert into episodes(ts,session,role,text) values(?,?,?,?)",
                               (time.time(), session, role, text))
        self.con.commit()
        return cur.lastrowid

    def add_feedback(self, episode_id, rating, note=""):
        cur = self.con.execute("insert into feedback(ts,episode_id,rating,note) values(?,?,?,?)",
                               (time.time(), episode_id, rating, note))
        self.con.commit()
        return cur.lastrowid

    def set_profile(self, key, value):
        self.con.execute("insert into profile(key,value) values(?,?) "
                         "on conflict(key) do update set value=excluded.value", (key, value))
        self.con.commit()

    def get_profile(self):
        return dict(self.con.execute("select key,value from profile").fetchall())

    def audit(self, event, detail=""):
        self.con.execute("insert into audit(ts,event,detail) values(?,?,?)",
                         (time.time(), event, detail))
        self.con.commit()

    def counts(self) -> dict[str, int]:
        return {t: self.con.execute(f"select count(*) from {t}").fetchone()[0]
                for t in ("facts", "episodes", "feedback", "profile", "audit")}

    def snapshot(self, dest: Path) -> None:
        if dest.exists() and any(dest.iterdir()):
            raise FileExistsError(f"Ziel nicht leer: {dest}")
        dest.mkdir(parents=True, exist_ok=True)
        self.con.commit()
        out = _connect(dest / DB_FILE, self.key)  # gleicher Schlüssel -> verschlüsselte Kopie
        self.con.backup(out)
        out.close()
        shutil.copy2(self.root / MANIFEST, dest / MANIFEST)
        for d in SUBDIRS:
            src = self.root / d
            if src.exists():
                shutil.copytree(src, dest / d)
            else:
                (dest / d).mkdir()

    def close(self):
        self.con.close()
