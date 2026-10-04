"""Prüfung nach einem Claude-Zug: Was hat sich geändert, ist der Stand des Nutzers unberührt, sind geschützte Dateien betroffen?

Alles kommt aus Git, UNABHÄNGIG von dem, was Claude behauptet. Es werden nur lesende `git`-Befehle ausgeführt (Whitelist);
nichts mit Netz, nichts, was etwas löscht, verschiebt oder zusammenführt. Übernehmen (mergen) macht nur der Nutzer.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

Git = Callable[[list[str], Path], str]

# Änderungen daran werden rot markiert und nie automatisch übernommen ("Regeln ändert nur der Nutzer").
PROTECTED_PREFIXES = ("src/kushim/safety/", "src/kushim/net/", ".claude/", ".github/")
PROTECTED_FILES = ("src/kushim/privacy.py", "tests/test_no_egress.py", "claude.md", ".gitignore", "install.ps1", "scripts/add-path.ps1",
                   "config.toml", "config.example.toml")
_ALLOWED_SUBCOMMANDS = {"rev-parse", "diff", "status", "log", "worktree"}


class GitError(Exception):
    pass


def run_git(args: list[str], cwd: Path) -> str:
    """Führt einen LESENDEN git-Befehl aus. Alles außerhalb der Whitelist wird abgelehnt (auch `worktree add/remove`)."""
    if not args or args[0] not in _ALLOWED_SUBCOMMANDS or (args[0] == "worktree" and args[1:2] != ["list"]):
        raise GitError("git-Befehl nicht erlaubt")
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=30, check=False,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as e:
        raise GitError(type(e).__name__)
    if r.returncode != 0:
        raise GitError("git meldet einen Fehler")
    return r.stdout


def is_protected(path: str) -> bool:
    p = re.sub(r"^(\./)+", "", path.replace("\\", "/").lstrip("/").lower())      # nur ein führendes "./" entfernen, NICHT den Punkt von ".claude"
    return p in PROTECTED_FILES or any(p.startswith(x) for x in PROTECTED_PREFIXES)


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str


def find_worktree(folder: Path, name: str, git: Git = run_git) -> Worktree | None:
    """Sucht den von Claude angelegten Worktree (Pfad oder Branch enthält den Namen)."""
    try:
        out = git(["worktree", "list", "--porcelain"], folder)
    except GitError:
        return None
    for block in out.split("\n\n"):
        path = branch = ""
        for line in block.splitlines():
            if line.startswith("worktree "):
                path = line[len("worktree "):].strip()
            elif line.startswith("branch "):
                branch = line[len("branch "):].strip().removeprefix("refs/heads/")
        if path and (name.lower() in path.lower().replace("\\", "/") or name.lower() in branch.lower()):
            return Worktree(Path(path), branch)
    return None


def list_worktrees(folder: Path, git: Git = run_git) -> list[Worktree]:
    """Alle von kushim/Claude angelegten Worktrees des Ordners (`<ordner>/.claude/worktrees/<name>`, Branch `worktree-<name>`), älteste zuerst."""
    try:
        out = git(["worktree", "list", "--porcelain"], folder)
    except GitError:
        return []
    base = (Path(folder).resolve() / ".claude" / "worktrees")
    found: list[Worktree] = []
    for block in re.split(r"\r?\n\r?\n", out):
        path = branch = ""
        for line in block.splitlines():
            if line.startswith("worktree "):
                path = line[len("worktree "):].strip()
            elif line.startswith("branch "):
                branch = line[len("branch "):].strip().removeprefix("refs/heads/")
        if not path or not branch.startswith("worktree-"):
            continue
        try:
            inside = Path(path).resolve().parent == base and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,60}", Path(path).name) is not None
        except OSError:
            inside = False
        if inside:
            found.append(Worktree(Path(path), branch))
    return sorted(found, key=lambda w: w.path.name)


def worktree_facts(wt: Worktree, folder: Path, git: Git = run_git) -> tuple[int, int]:
    """(ungesicherte Dateien, Commits seit dem aktuellen Stand des Hauptordners) eines Worktrees, nur lesend."""
    try:
        base = git(["rev-parse", "HEAD"], folder).strip()
        dirty = len([l for l in git(["status", "--porcelain"], wt.path).splitlines() if l.strip()])
        ahead = len([l for l in git(["log", "--oneline", f"{base}..HEAD"], wt.path).splitlines() if l.strip()])
        return dirty, ahead
    except GitError:
        return 0, 0


@dataclass
class Review:
    branch: str = ""
    files: list[tuple[str, str]] = field(default_factory=list)       # (Status, Pfad)
    protected: list[str] = field(default_factory=list)
    uncommitted: int = 0
    shortstat: str = ""
    base_unchanged: bool = True                                     # Stand des Nutzers (Ordner, Branch, Commit) unberührt
    error: str = ""

    @property
    def new_files(self) -> int:
        return sum(1 for s, _ in self.files if s.startswith("A"))


def review(folder: Path, worktree: Path | None, base_sha: str, base_branch: str, git: Git = run_git) -> Review:
    rv = Review()
    try:
        rv.base_unchanged = (git(["rev-parse", "HEAD"], folder).strip() == base_sha
                             and git(["rev-parse", "--abbrev-ref", "HEAD"], folder).strip() == base_branch)
        if worktree is None:
            rv.error = "Worktree nicht gefunden"
            return rv
        rv.branch = git(["rev-parse", "--abbrev-ref", "HEAD"], worktree).strip()
        for line in git(["diff", "--name-status", base_sha, "HEAD"], worktree).splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and re.fullmatch(r"[A-Z][0-9]*", parts[0]):
                rv.files.append((parts[0], parts[-1]))
        rv.uncommitted = len([l for l in git(["status", "--porcelain"], worktree).splitlines() if l.strip()])
        rv.shortstat = git(["diff", "--shortstat", base_sha, "HEAD"], worktree).strip()
    except GitError:
        rv.error = "git-Abfrage fehlgeschlagen"
    rv.protected = [p for _, p in rv.files if is_protected(p)]
    if worktree is not None and not rv.error:                        # auch uncommittete Änderungen an geschützten Dateien melden
        try:
            for line in git(["status", "--porcelain"], worktree).splitlines():
                path = line[3:].strip().split(" -> ")[-1]
                if path and is_protected(path) and path not in rv.protected:
                    rv.protected.append(path)
        except GitError:
            pass
    return rv
