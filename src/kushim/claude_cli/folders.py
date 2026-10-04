"""Freigegebene Ordner für Claude (Entwicklungs-Modus): prüfen, speichern, per Name auflösen.

Claude arbeitet NUR in Ordnern, die der Nutzer ausdrücklich freigegeben hat (UI/CLI, nie per Sprache, nie durch Claude oder das LLM).
Ein Ordner muss absolut, vorhanden, ein Git-Repository und ohne Verknüpfung nach außen sein. Verboten sind Laufwerkswurzeln,
der Benutzerordner selbst, Systemordner, AppData, `.ssh`/`.gnupg`/`.claude` des Benutzers und der Vault (er selbst, alles in ihm
und alles, was ihn enthält). Eintragsformat in `config.toml`: `name|pfad` (`|` ist in Windows-Pfaden nicht erlaubt).
"""
from __future__ import annotations

import difflib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,30}")        # sprechbarer Kleinbuchstaben-Name ("kushim", "mein-projekt")
SEP = "|"


@dataclass(frozen=True)
class Folder:
    name: str
    path: Path

    def entry(self) -> str:
        return f"{self.name}{SEP}{self.path.as_posix()}"


def vault_path(location: str) -> Path | None:
    """Vault-Ordner aus `memory.location` ("local:~/kushim-vault"); andere Orte (z. B. NAS) kennen wir hier nicht."""
    if location.startswith("local:"):
        return Path(location[len("local:"):]).expanduser()
    return None


def parse_entry(entry: str) -> Folder | None:
    name, sep, raw = entry.partition(SEP)
    name = name.strip()
    if not sep or not NAME_RE.fullmatch(name) or not raw.strip():
        return None
    return Folder(name, Path(raw.strip()))


def parse(entries: Iterable[str]) -> list[Folder]:
    """Kaputte oder doppelte Einträge werden ignoriert (nie raten, nie etwas Fremdes freigeben)."""
    seen: set[str] = set()
    out: list[Folder] = []
    for e in entries:
        f = parse_entry(e)
        if f is not None and f.name not in seen:
            seen.add(f.name)
            out.append(f)
    return out


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _norm(p: Path) -> Path:
    return Path(os.path.normcase(str(p)))


def forbidden_roots(home: Path) -> list[Path]:
    roots = [home / ".ssh", home / ".gnupg", home / ".claude", home / "AppData"]
    for var in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "APPDATA", "LOCALAPPDATA"):
        if os.environ.get(var):
            roots.append(Path(os.environ[var]))
    return roots


def validate_path(raw: str | Path, vault: Path | None = None, home: Path | None = None) -> Path:
    """Gibt den aufgelösten Pfad zurück oder wirft ValueError mit dem Grund (in Klartext für den Nutzer)."""
    home = (home or Path.home())
    p = Path(raw).expanduser()
    if not p.is_absolute():
        raise ValueError("Der Pfad muss absolut sein.")
    try:
        resolved = p.resolve(strict=True)
    except (OSError, RuntimeError):
        raise ValueError("Der Ordner existiert nicht.")
    if not resolved.is_dir():
        raise ValueError("Das ist kein Ordner.")
    if _norm(resolved) != _norm(Path(os.path.abspath(p))):          # Verknüpfung/Junction führt woanders hin
        raise ValueError("Verknüpfungen (Junction/Symlink) sind nicht erlaubt, bitte den echten Pfad angeben.")
    if resolved == Path(resolved.anchor):
        raise ValueError("Ein ganzes Laufwerk ist nicht erlaubt.")
    rn, hn = _norm(resolved), _norm(home.resolve())
    if rn == hn:
        raise ValueError("Der Benutzerordner selbst ist nicht erlaubt, nur ein Projektordner darin.")
    for bad in forbidden_roots(home):
        bn = _norm(bad.resolve() if bad.exists() else bad)
        if rn == bn or _inside(rn, bn):
            raise ValueError("Dieser Ordner liegt in einem geschützten Bereich (System, AppData, .ssh, .claude).")
    if vault is not None:
        vn = _norm(vault.resolve() if vault.exists() else vault)
        if rn == vn or _inside(rn, vn) or _inside(vn, rn):
            raise ValueError("Der Ordner enthält den Vault oder liegt darin (Schlüssel und Gedächtnis müssen draußen bleiben).")
    if not (resolved / ".git").exists():
        raise ValueError("Kein Git-Repository (Claude arbeitet immer in einem eigenen Branch und Worktree).")
    return resolved


def resolve(folders: list[Folder], spoken: str | None) -> Folder | None:
    """Ordner nach gesprochenem Namen ("das Projekt kushim"); ohne Namen nur, wenn es genau einen gibt. Sonst None (nie raten)."""
    if not folders:
        return None
    words = re.findall(r"[a-z0-9äöüß_-]+", (spoken or "").lower())
    candidates = [w for w in words if w not in {"das", "dem", "den", "projekt", "ordner", "im", "in", "von", "mit", "claude", "nutze"}]
    for w in candidates:
        for f in folders:
            if f.name == w:
                return f
    for w in candidates:
        close = difflib.get_close_matches(w, [f.name for f in folders], n=1, cutoff=0.8)
        if close:
            return next(f for f in folders if f.name == close[0])
    return folders[0] if len(folders) == 1 and not candidates else None
