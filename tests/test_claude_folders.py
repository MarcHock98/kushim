"""Sichere Arbeitsordner für Claude (`claude_cli/folders.py`) und ihre Konfiguration."""
import os
import subprocess
from pathlib import Path

import pytest

from kushim.claude_cli import folders
from kushim.claude_cli.folders import Folder, parse, parse_entry, resolve, validate_path, vault_path
from kushim.config import Config

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


# --- Registry und Konfiguration ------------------------------------------------------------------

def test_claude_folders_roundtrip_keeps_the_rest_and_ignores_junk(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('[llm]\nmodel = "qwen2.5:7b"\n\n[claude]\nfolders = []\n', encoding="utf-8")
    c = Config.load(f)
    assert c.claude_folders == ()
    c.set_claude_folders(["kushim|C:/Users/x/kushim", "web|C:/Users/x/Mein Projekt"])
    again = Config.load(f)
    assert again.claude_folders == ("kushim|C:/Users/x/kushim", "web|C:/Users/x/Mein Projekt")
    assert not list(tmp_path.glob("*.tmp")) and f.read_text(encoding="utf-8").count("[claude]") == 1
    for bad in (["ohne-trenner"], ["a|b\nc|d"], [5]):
        with pytest.raises(ValueError):
            c.set_claude_folders(bad)
    assert Config.load(f).claude_folders == again.claude_folders                     # Fehler ändern nichts
    for junk in ('[claude]\nfolders = "kushim|C:/x"\n', '[claude]\nfolders = [1, "ohne"]\n', "[claude]\nfolders = [[1]]\n"):
        f.write_text(junk, encoding="utf-8")
        assert Config.load(f).claude_folders == ()
    g = tmp_path / "neu.toml"
    Config(path=g).set_claude_folders(["a|C:/a"])
    assert Config.load(g).claude_folders == ("a|C:/a",)
