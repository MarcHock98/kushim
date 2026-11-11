"""Sperrliste für Freigaben per Stimme (src/kushim/channel/voice_policy.py, Roadmap v2 C4)."""
import json

import pytest

from kushim.channel import voice_policy as vp
from kushim.channel.bridge import Permission


def perm(tool, **fields):
    preview = "{ " + ", ".join(f"{json.dumps(k)}: {json.dumps(v)}" for k, v in fields.items()) + " }"
    return Permission.parse({"request_id": "r1", "tool_name": tool, "description": "", "input_preview": preview})


ALLOWED = [
    "npm test", "npm run build", "npm run test:unit", "python -m pytest -q", "py -m pytest tests/test_x.py -k perm",
    ".venv/Scripts/python -m pytest -q 2>&1", "git status", "git diff", "git log --oneline -5", "git add src/app.py",
    "git commit -m 'Fix tests'", "git branch feature/x", "git stash", "ls -la", "dir", "cat README.md",
    "pytest -q > /dev/null 2>&1", "grep -n def src/app.py | head -20", "cd ui && npm test", "git show HEAD~1",
    "sed -n 1,40p src/app.py", "npm run lint", "npm run typecheck", "python -m ruff check src", "python tools/check.py",
]

BLOCKED = [
    # Löschen, Überschreiben, Verschieben
    "rm -rf build", "rm file.txt", "del /q *.tmp", "Remove-Item -Recurse dist", "rmdir out", "mv a.py b.py",
    "echo hi > README.md", "cat x >> y.txt", "Set-Content a.txt 'x'", "git clean -fdx", "git rm app.py",
    "git reset --hard HEAD~1", "git checkout -- .", "git restore app.py", "git branch -D feature", "git stash drop",
    "find . -name '*.pyc' | xargs rm", "truncate -s 0 log.txt", "cp a.py b.py", "copy a b", "Copy-Item a b",
    "sed -i s/a/b/ app.py", "sed --in-place=.bak s/a/b/ x", "perl -pi -e s/a/b/ x", "tar xf a.tar", "Add-Content a x",
    "npm run deploy", "npm run release", "npm run", "npm exec x", "python -m kushim.cli resume", "python -m",
    "py -m venv .venv",
    # Push und Netz
    "git push", "git push --force origin master", "git push -f", "git pull", "git fetch", "git remote add x url",
    "curl https://example.org", "wget http://x", "Invoke-WebRequest https://x", "scp a host:", "ssh host",
    "gh pr create", "npm publish", "npm install left-pad", "npm i", "pip install requests", "python -m pip install x",
    "npx some-tool", "uv pip install x", "docker push img", "python -m http.server",
    # Einstellungen, System
    "git config user.email x", "git -c core.hooksPath=x commit", "setx PATH x", "reg add HKCU\\x", "chmod 777 a",
    "icacls a /grant x", "shutdown /s", "taskkill /f /im python.exe", "Stop-Process -Name x", "claude mcp add x",
    "kushim resume", "Set-ExecutionPolicy Bypass", "schtasks /create", "export FOO=1", "set FOO=1",
    # versteckte Ausführung
    "bash -c 'rm -rf /'", "sh script.sh", "powershell -enc ZQBj", "cmd /c del x", "python -c 'import os'",
    "node -e 'x'", "eval $X", "echo $(cat a)", "echo `id`", "iex (gc a.ps1)", "source env.sh", ". ./x.sh",
    # außerhalb, Geheimnisse
    "cat ../other/secret.txt", "ls ~", "type C:\\Windows\\win.ini", "cat /etc/passwd", "cat .env", "type .ssh\\id_rsa",
    "echo $env:USERPROFILE", "dir %USERPROFILE%", "cat config/token.txt", "",
]


@pytest.mark.parametrize("cmd", ALLOWED)
def test_everyday_commands_may_be_allowed_by_voice(cmd):
    assert vp.shell_reason(cmd) is None, cmd
    assert vp.blocked(perm("Bash", command=cmd), None) is None


@pytest.mark.parametrize("cmd", BLOCKED)
def test_dangerous_commands_are_terminal_only(cmd):
    assert vp.shell_reason(cmd) is not None, cmd
    assert vp.blocked(perm("PowerShell", command=cmd), None) is not None


def test_multiline_and_chained_commands_check_every_part():
    assert vp.shell_reason("npm test\nrm -rf dist") is not None
    assert vp.shell_reason("npm test; git push") is not None
    assert vp.shell_reason("npm test || del x") is not None
    assert vp.shell_reason("npm test & curl x") is not None
    assert vp.shell_reason("FOO=1 rm x") is not None                      # Umgebungs-Zuweisung davor hilft nicht


def test_other_tools_are_never_allowed_by_voice(tmp_path):
    for tool in ("WebFetch", "WebSearch", "Agent", "Task", "Grep", "mcp__srv__send", "TodoWrite", ""):
        assert vp.blocked(perm(tool, url="https://x", command="ls", file_path=str(tmp_path / "a.py")), tmp_path)
    assert vp.blocked(perm("Bash"), tmp_path) == "kein Befehl"
    assert vp.blocked(perm("Edit"), tmp_path) == "kein Pfad"


def test_files_only_inside_the_work_folder(tmp_path):
    work = tmp_path / "proj"
    (work / "src").mkdir(parents=True)
    ok = [str(work / "src" / "app.py"), "src/app.py", "README.md", str(work / "ui" / "neu.tsx")]
    for p in ok:
        assert vp.blocked(perm("Edit", file_path=p), work) is None, p
        assert vp.blocked(perm("Write", file_path=p), work) is None, p
    assert vp.blocked(perm("NotebookEdit", notebook_path="a.ipynb"), work) is None
    bad = [str(tmp_path / "other.py"), "../other.py", "src/../../x.py", str(work), "C:\\Windows\\system.ini",
           str(tmp_path / "proj2" / "a.py")]
    for p in bad:
        assert vp.blocked(perm("Edit", file_path=p), work) is not None, p


def test_unknown_work_folder_blocks_all_files(tmp_path):
    assert vp.blocked(perm("Read", file_path=str(tmp_path / "a.py")), None) == "Arbeitsordner unbekannt"


def test_protected_folders_settings_keys_and_kushims_own_rules(tmp_path):
    for p in (".git/config", ".claude/settings.json", "sub/.git/hooks/pre-commit", ".env", ".env.local", ".mcp.json",
              "config.toml", "wakewords.toml", "certs/server.pem", "a.key", "src/kushim/safety/rules.py",
              "tests/test_no_egress.py", "docs/STOP", "run/channel.json", ".vscode/settings.json", "settings.local.json"):
        assert vp.blocked(perm("Write", file_path=p), tmp_path) is not None, p


def test_symlink_out_of_the_folder_is_caught(tmp_path):
    work, outside = tmp_path / "proj", tmp_path / "outside"
    work.mkdir()
    outside.mkdir()
    try:
        (work / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks brauchen unter Windows besondere Rechte")
    assert vp.blocked(perm("Edit", file_path="link/a.py"), work) == "außerhalb des Arbeitsordners"


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
