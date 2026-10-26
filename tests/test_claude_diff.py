"""Diff einer einzelnen Datei eines Claude-Laufs: nur lesend, nur geänderte Dateien, gekürzt, ohne Steuerzeichen."""
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from kushim.api.claude_api import register_claude
from kushim.api.protocol import ApiCore, new_token
from kushim.claude_cli import review
from kushim.claude_cli.review import MAX_DIFF_CHARS, GitError, diff_file

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git fehlt")


def sh(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path):
    sh(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("eins\nzwei\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("unberührt\n", encoding="utf-8")
    sh(tmp_path, "add", "-A")
    sh(tmp_path, "commit", "-q", "-m", "base")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True).stdout.strip()
    (tmp_path / "a.txt").write_text("eins\nzwei geändert\n\x1b[31mrot\x07\n", encoding="utf-8")
    (tmp_path / "neu.txt").write_text("neu\n", encoding="utf-8")
    sh(tmp_path, "add", "-A")
    sh(tmp_path, "commit", "-q", "-m", "claude")
    return tmp_path, base


def test_diff_of_a_changed_file_has_the_change_and_no_control_characters(repo):
    path, base = repo
    text, truncated = diff_file(path, base, "a.txt")
    assert "+zwei geändert" in text and "-zwei" in text and not truncated
    assert "\x1b" not in text and "\x07" not in text


def test_new_file_diff(repo):
    path, base = repo
    assert "+neu" in diff_file(path, base, "neu.txt")[0]


@pytest.mark.parametrize("bad", ["b.txt", "../a.txt", "--output=x", "-p", "gibt-es-nicht", "", "a.txt ", "./a.txt"])
def test_only_exactly_changed_files_are_allowed(repo, bad):
    path, base = repo
    with pytest.raises(GitError):
        diff_file(path, base, bad)


def test_output_option_never_writes_a_file(repo):
    path, base = repo
    with pytest.raises(GitError):
        diff_file(path, base, "--output=pwned.txt")
    assert not (path / "pwned.txt").exists()


def test_long_diffs_are_truncated(tmp_path):
    sh(tmp_path, "init", "-q")
    (tmp_path / "g.txt").write_text("x\n", encoding="utf-8")
    sh(tmp_path, "add", "-A")
    sh(tmp_path, "commit", "-q", "-m", "base")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True).stdout.strip()
    (tmp_path / "g.txt").write_text("y" * (MAX_DIFF_CHARS + 5000) + "\n", encoding="utf-8")
    sh(tmp_path, "add", "-A")
    sh(tmp_path, "commit", "-q", "-m", "gross")
    text, truncated = diff_file(tmp_path, base, "g.txt")
    assert truncated and len(text) == MAX_DIFF_CHARS


def test_only_read_only_git_subcommands_are_used(repo):
    path, base = repo
    seen = []

    def spy(args, cwd):
        seen.append(args[0])
        return review.run_git(args, cwd)
    diff_file(path, base, "a.txt", git=spy)
    assert set(seen) <= {"diff"}


# --- API ---------------------------------------------------------------------------------------------------------

TOKEN = new_token()


def api(sessions):
    core = ApiCore(TOKEN)
    register_claude(core, SimpleNamespace(sessions=sessions))
    return lambda **m: json.loads(core.handle(json.dumps({"token": TOKEN, "type": "claude.diff", **m})))


def test_api_returns_diff_with_protected_flag():
    call = api(SimpleNamespace(diff=lambda p: ("+x\n", False)))
    assert call(path="README.md") == {"ok": True, "path": "README.md", "diff": "+x\n", "truncated": False, "protected": False}
    assert call(path="src/kushim/safety/rules.py")["protected"] is True
    assert call(path=".claude/settings.json")["protected"] is True


def test_api_error_codes():
    def boom(p):
        raise GitError("x")
    assert api(SimpleNamespace(diff=boom))(path="a")["error"] == "not_changed"
    assert api(SimpleNamespace(diff=lambda p: None))(path="a")["error"] == "no_session"
    for bad in (None, 5, "", "x" * 401):
        assert api(SimpleNamespace(diff=lambda p: ("", False)))(path=bad)["error"] == "bad_request"


def test_api_needs_token():
    core = ApiCore(TOKEN)
    register_claude(core, SimpleNamespace(sessions=SimpleNamespace(diff=lambda p: ("", False))))
    assert json.loads(core.handle(json.dumps({"type": "claude.diff", "path": "a"})))["error"] == "unauthorized"
