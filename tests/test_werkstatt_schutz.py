"""Schutzprüfung der Werkstatt (Stufe 2): eine Tabelle von Diffs mit Umgehungsproben und ein Lauf mit einem echten lokalen git-Repo.

Diese Datei ist selbst geschützt (`tests/test_werkstatt_*.py`): ein Werkstatt-Zweig darf sie nicht ändern.
"""
import ast
import os
import subprocess
from pathlib import Path

import pytest

from kushim.werkstatt import schutz
from kushim.werkstatt.schutz import Datei, pruefe, pruefe_commits

SRC = Path(__file__).resolve().parents[1] / "src" / "kushim"
OK = "ok"


def _auto(name_status: str, **extra: Datei) -> dict[str, Datei]:
    """Angaben für jeden neuen Pfad: kleine Textdatei ohne neue Zeilen, einzelne Pfade überschreibbar."""
    dateien = {e.neu: Datei(groesse=100, modus="100644") for e in schutz._lies_name_status(name_status) if e.neu is not None}
    dateien.update(extra)
    return dateien


def _codes(name_status: str, numstat: str = "", **extra: Datei) -> set[tuple[str, str]]:
    ergebnis = pruefe(name_status, numstat, _auto(name_status, **extra))
    assert ergebnis.ok == (not ergebnis.gruende)
    return {(g.code, g.pfad) for g in ergebnis.gruende}


# --- Tabelle: (Name, name-status, numstat, Angaben, erwartete Gründe oder OK) ------------------------------------------

FAELLE = [
    ("rezept neu", "A\tsrc/kushim/stage/rezepte/neu.json", "12\t0\tsrc/kushim/stage/rezepte/neu.json", {}, OK),
    ("ui-komponente", "M\tui/src/components/x.tsx", "3\t1\tui/src/components/x.tsx", {}, OK),
    ("neuer test", "A\ttests/test_neu.py", "2\t0\ttests/test_neu.py",
     {"tests/test_neu.py": Datei(100, "100644", ("def test_neu():", "    assert 1 + 1 == 2"))}, OK),
    ("test ergänzt", "M\ttests/test_stage.py", "4\t0\ttests/test_stage.py",
     {"tests/test_stage.py": Datei(100, "100644", ("def test_mehr():", "    assert True"))}, OK),
    ("harmlos umbenannt", "R100\tsrc/kushim/stage/a.py\tsrc/kushim/stage/b.py",
     "0\t0\tsrc/kushim/stage/{a.py => b.py}", {}, OK),

    ("umbenannt in geschützt", "R100\tsrc/kushim/stage/a.py\tsrc/kushim/safety/a.py", "", {},
     {("GESCHUETZT", "src/kushim/safety/a.py")}),
    ("umbenannt aus geschützt", "R100\tsrc/kushim/safety/rules.py\tsrc/kushim/stage/rules.py", "", {},
     {("GESCHUETZT", "src/kushim/safety/rules.py")}),
    ("umbenannt numstat klammer", "R100\tsrc/kushim/stage/a.py\tsrc/kushim/safety/a.py", "0\t0\tsrc/kushim/{stage => safety}/a.py", {},
     {("GESCHUETZT", "src/kushim/safety/a.py")}),
    ("kopie in geschützt", "C100\tsrc/kushim/stage/a.py\tsrc/kushim/net/a.py", "", {}, {("GESCHUETZT", "src/kushim/net/a.py")}),
    ("großschreibung", "M\tSRC/Kushim/Safety/x.py", "", {}, {("GESCHUETZT", "SRC/Kushim/Safety/x.py")}),
    ("backslash", "A\tsrc\\kushim\\safety\\x.py", "", {},
     {("GESCHUETZT", "src\\kushim\\safety\\x.py"), ("PFAD_UNGUELTIG", "src\\kushim\\safety\\x.py")}),
    ("backslash in git-schreibweise", 'A\t"src\\\\kushim\\\\safety\\\\x.py"', "", {},
     {("GESCHUETZT", "src\\kushim\\safety\\x.py"), ("PFAD_UNGUELTIG", "src\\kushim\\safety\\x.py")}),
    ("punkt-teil", "A\tsrc/kushim/./safety/x.py", "", {},
     {("GESCHUETZT", "src/kushim/./safety/x.py"), ("PFAD_UNGUELTIG", "src/kushim/./safety/x.py")}),
    ("punkt-punkt", "A\tdocs/../src/kushim/safety/x.py", "", {},
     {("GESCHUETZT", "docs/../src/kushim/safety/x.py"), ("PFAD_UNGUELTIG", "docs/../src/kushim/safety/x.py")}),
    ("punkt am ende", "A\tsrc/kushim/safety./x.py", "", {},
     {("GESCHUETZT", "src/kushim/safety./x.py"), ("PFAD_UNGUELTIG", "src/kushim/safety./x.py")}),
    ("kurzname", "A\tsrc/kushim/SAFETY~1/x.py", "", {}, {("PFAD_UNGUELTIG", "src/kushim/SAFETY~1/x.py")}),
    ("ntfs-datenstrom", "M\tsrc/kushim/stage/x.py::$DATA", "", {}, {("PFAD_UNGUELTIG", "src/kushim/stage/x.py::$DATA")}),
    ("unicode langes s", 'A\t"src/kushim/\\305\\277afety/x.py"', "", {},
     {("GESCHUETZT", "src/kushim/?afety/x.py"), ("PFAD_UNGUELTIG", "src/kushim/?afety/x.py")}),
    ("modul neben paket", "A\tsrc/kushim/safety.py", "", {}, {("GESCHUETZT", "src/kushim/safety.py")}),
    ("conftest tief", "A\tsrc/kushim/stage/rezepte/tief/conftest.py", "", {},
     {("GESCHUETZT", "src/kushim/stage/rezepte/tief/conftest.py")}),
    ("schutz.py selbst", "M\tsrc/kushim/werkstatt/schutz.py", "", {}, {("GESCHUETZT", "src/kushim/werkstatt/schutz.py")}),
    ("diese testdatei", "M\ttests/test_werkstatt_schutz.py", "1\t0\ttests/test_werkstatt_schutz.py", {},
     {("GESCHUETZT", "tests/test_werkstatt_schutz.py")}),

    ("testzeile gelöscht", "M\ttests/test_stage.py", "3\t1\ttests/test_stage.py", {}, {("TEST_ZEILEN_GELOESCHT", "tests/test_stage.py")}),
    ("ui-testzeile gelöscht", "M\tui/src/app.test.tsx", "0\t2\tui/src/app.test.tsx", {},
     {("TEST_ZEILEN_GELOESCHT", "ui/src/app.test.tsx")}),
    ("pytest.mark.skip", "M\ttests/test_stage.py", "1\t0\ttests/test_stage.py",
     {"tests/test_stage.py": Datei(100, "100644", ("@pytest.mark.skip(reason='kaputt')",))}, {("TEST_MARKER", "tests/test_stage.py")}),
    ("testdatei gelöscht", "D\ttests/test_stage.py", "0\t50\ttests/test_stage.py", {}, {("TEST_GELOESCHT", "tests/test_stage.py")}),
    ("testdatei umbenannt", "R100\ttests/test_stage.py\ttests/test_buehne.py", "0\t50\ttests/test_stage.py\n50\t0\ttests/test_buehne.py",
     {}, {("TEST_UMBENANNT", "tests/test_stage.py")}),
    ("binär im test", "A\ttests/data/x.bin", "-\t-\ttests/data/x.bin", {}, {("TEST_BINAER", "tests/data/x.bin")}),
    ("test ohne numstat", "M\ttests/test_stage.py", "", {}, {("NUMSTAT_FEHLT", "tests/test_stage.py")}),

    ("symlink", ":000000 120000 0000000000000000000000000000000000000000 1111111111111111111111111111111111111111 A\tsrc/kushim/stage/link",
     "", {}, {("SYMLINK", "src/kushim/stage/link")}),
    ("submodul", ":000000 160000 0000000000000000000000000000000000000000 2222222222222222222222222222222222222222 A\tsrc/kushim/stage/sub",
     "", {}, {("SUBMODUL", "src/kushim/stage/sub")}),
    ("symlink nur in angaben", "A\tsrc/kushim/stage/link", "", {"src/kushim/stage/link": Datei(20, "120000")},
     {("SYMLINK", "src/kushim/stage/link")}),
    ("typwechsel", "T\tsrc/kushim/stage/x.py", "", {}, {("TYPWECHSEL", "src/kushim/stage/x.py")}),

    ("requirements", "A\trequirements.txt", "", {}, {("ABHAENGIGKEIT", "requirements.txt")}),
    ("node_modules", "A\tui/src/node_modules/x/index.js", "", {}, {("ABHAENGIGKEIT", "ui/src/node_modules/x/index.js")}),
    ("paketarchiv", "A\tsrc/kushim/stage/x.whl", "", {}, {("ABHAENGIGKEIT", "src/kushim/stage/x.whl")}),
    ("package.json", "M\tui/package.json", "", {}, {("GESCHUETZT", "ui/package.json"), ("ABHAENGIGKEIT", "ui/package.json")}),
    ("ausführbar", "A\tsrc/kushim/stage/x.pyd", "", {}, {("AUSFUEHRBAR", "src/kushim/stage/x.pyd")}),

    ("zu groß", "A\tsrc/kushim/stage/gross.json", "", {"src/kushim/stage/gross.json": Datei(schutz.MAX_DATEI_BYTES + 1, "100644")},
     {("ZU_GROSS", "src/kushim/stage/gross.json")}),
    ("ohne größe", "A\tsrc/kushim/stage/x.json", "", {"src/kushim/stage/x.json": Datei(None, "100644")},
     {("INHALT_FEHLT", "src/kushim/stage/x.json")}),
    ("numstat fremd", "A\tsrc/kushim/stage/x.json", "1\t0\tsrc/kushim/safety/rules.py", {},
     {("INKONSISTENT", "src/kushim/safety/rules.py")}),
    ("status unbekannt", "U\tsrc/kushim/stage/x.py", "", {}, {("STATUS_UNBEKANNT", "src/kushim/stage/x.py")}),
]


@pytest.mark.parametrize("name,name_status,numstat,extra,erwartet", FAELLE, ids=[f[0] for f in FAELLE])
def test_tabelle(name, name_status, numstat, extra, erwartet):
    gefunden = _codes(name_status, numstat, **extra)
    if erwartet == OK:
        assert gefunden == set(), gefunden
    else:
        assert erwartet <= gefunden, gefunden


# --- Alle geschützten Pfade aus dem Plan, angelegt, geändert und gelöscht -----------------------------------------------

GESCHUETZT = [
    "src/kushim/safety/rules.py", "src/kushim/safety/neu/tief.py", "src/kushim/channel/server.py", "src/kushim/werkstatt/__init__.py",
    "src/kushim/net/x.py", "src/kushim/claude_cli/base.py", "tests/test_no_egress.py", "tests/test_no_egress_config.py",
    "tests/test_ui_rules.py", "tests/test_rules.py", "tests/test_killswitch.py", "tests/test_werkstatt_neu.py", "conftest.py",
    "tests/conftest.py", "ui/src/conftest.py", "pyproject.toml", "ui/package.json", "ui/package-lock.json", "ui/vite.config.ts",
    "ui/index.html", "ui/src-tauri/tauri.conf.json", "ui/src-tauri/src/main.rs", "ui/src/test-setup.ts", ".claude/settings.json",
    ".claude/skills/x/SKILL.md", "scripts/x.py", "install.ps1", "config.toml", "config.example.toml", "wakewords.toml",
    "wakewords.example.toml", ".gitignore", ".gitattributes", ".gitmodules", "ui/.gitignore", ".github/workflows/x.yml",
    "run/channel.json", "models/x.onnx", "tools/x.py", "bin/kushim.cmd", "pytest.ini", "ui/vitest.config.ts", "src/kushim/x.pth",
    "src/sitecustomize.py",
]


@pytest.mark.parametrize("status", ["A", "M", "D"])
@pytest.mark.parametrize("pfad", GESCHUETZT)
def test_jeder_geschuetzte_pfad_ist_gesperrt(status, pfad):
    assert ("GESCHUETZT", pfad) in _codes(f"{status}\t{pfad}")
    assert ("GESCHUETZT", pfad.upper()) in _codes(f"{status}\t{pfad.upper()}")


@pytest.mark.parametrize("pfad", ["src/kushim/stage/rezepte/neu.json", "ui/src/components/x.tsx", "docs/neu.md",
                                  "src/kushim/stage/schema_neu.py", "src/kushim/safetynet.py", "tests/test_stage_neu.py"])
def test_aehnliche_aber_freie_pfade_bleiben_frei(pfad):
    assert ("GESCHUETZT", pfad) not in _codes(f"A\t{pfad}")


@pytest.mark.parametrize("zeile", [
    "@pytest.mark.skip", "pytest.skip('x')", "@pytest.mark.skipif(True, reason='x')", "@pytest.mark.xfail",
    "np = pytest.importorskip('numpy')", "__test__ = False", "pytestmark = pytest.mark.xfail", "pytest.exit('fertig')",
    "@unittest.expectedFailure", "it.only('x', () => {})", "describe.skip('x', () => {})", "it.todo('später')",
    "test.fails('x', () => {})", "xit('x', () => {})", "fdescribe('x', () => {})", "  it . only ('x')",
])
def test_marker_in_hinzugefuegten_testzeilen(zeile):
    for pfad in ("tests/test_stage.py", "ui/src/app.test.tsx", "ui/src/__tests__/x.ts", "tests/fixtures/helfer.py"):
        codes = _codes(f"M\t{pfad}", f"1\t0\t{pfad}", **{pfad: Datei(100, "100644", (zeile,))})
        assert ("TEST_MARKER", pfad) in codes, (pfad, zeile)


def test_marker_ausserhalb_von_tests_zaehlen_nicht():
    pfad = "src/kushim/voice/pause.py"
    assert _codes(f"M\t{pfad}", f"1\t0\t{pfad}", **{pfad: Datei(100, "100644", ("skip = True",))}) == set()


def test_gesamtgrenze():
    zeilen = "\n".join(f"A\tsrc/kushim/stage/rezepte/r{i}.json" for i in range(12))
    dateien = {f"src/kushim/stage/rezepte/r{i}.json": Datei(190 * 1024, "100644") for i in range(12)}
    ergebnis = pruefe(zeilen, "", dateien)
    assert not ergebnis.ok and [g.code for g in ergebnis.gruende] == ["GESAMT_ZU_GROSS"]


def test_zu_viele_dateien():
    zeilen = "\n".join(f"A\tdocs/d{i}.md" for i in range(schutz.MAX_DATEIEN + 1))
    assert "ZU_VIELE_DATEIEN" in {g.code for g in pruefe(zeilen, "", _auto(zeilen)).gruende}


@pytest.mark.parametrize("name_status,numstat,code", [
    ("Q\tsrc/x.py", "", "ZEILE_UNLESBAR"),
    ("M src/x.py", "", "ZEILE_UNLESBAR"),
    ("R100\tnur-ein-pfad.py", "", "ZEILE_UNLESBAR"),
    ('M\t"offen', "", "ZEILE_UNLESBAR"),
    (":100644 100644 abc M\tsrc/x.py", "", "ZEILE_UNLESBAR"),
    ("M\tsrc/x.py", "x\t1\tsrc/x.py", "ZEILE_UNLESBAR"),
])
def test_unlesbares_wird_abgelehnt(name_status, numstat, code):
    ergebnis = pruefe(name_status, numstat, {})
    assert not ergebnis.ok and ergebnis.gruende[0].code == code


def test_ohne_angaben_wird_abgelehnt_und_leerer_diff_ist_ok():
    ergebnis = pruefe("A\tdocs/neu.md", "1\t0\tdocs/neu.md", None)
    assert not ergebnis.ok and {g.code for g in ergebnis.gruende} == {"INHALT_FEHLT"}
    assert pruefe("", "", {}).ok


def test_gruende_sind_feste_codes_mit_pfad_ohne_inhalt():
    geheim = "GEHEIMER_INHALT_4711"
    ergebnis = pruefe("M\ttests/test_stage.py\nA\tsrc/kushim/safety/x.py", "1\t3\ttests/test_stage.py",
                      {"tests/test_stage.py": Datei(100, "100644", (f"pytest.skip('{geheim}')",)),
                       "src/kushim/safety/x.py": Datei(100, "100644", (geheim,))})
    assert not ergebnis.ok
    for g in ergebnis.gruende:
        assert g.code in schutz.CODES and geheim not in str(g) and g.pfad
    # Pfade in den Gründen enthalten nur druckbares ASCII
    g = pruefe('A\t"src/kushim/stage/a\\nb.py"', "", {}).gruende
    assert all(all(0x20 <= ord(c) <= 0x7E for c in x.pfad) for x in g)


# --- schutz.py schützt sich selbst und ist nur lesend --------------------------------------------------------------

def test_schutz_py_liegt_unter_einem_geschuetzten_pfad():
    datei = Path(schutz.__file__).resolve()
    rel = "src/kushim/" + datei.relative_to(SRC).as_posix()
    assert rel == "src/kushim/werkstatt/schutz.py"
    assert schutz.ist_geschuetzt(schutz._normiere(rel)[0])
    assert schutz.ist_geschuetzt(schutz._normiere("tests/" + Path(__file__).name)[0])
    assert "src/kushim/werkstatt" in schutz.GESCHUETZTE_ORDNER


def test_der_git_leser_ist_nur_lesend_ohne_shell_und_ohne_netz():
    quelle = (SRC / "werkstatt" / "schutz.py").read_text(encoding="utf-8")
    baum = ast.parse(quelle)
    aufrufe = [n for n in ast.walk(baum) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and isinstance(n.func.value, ast.Name) and n.func.value.id == "subprocess"]
    assert len(aufrufe) == 1 and aufrufe[0].func.attr == "run"
    kw = {k.arg: k.value for k in aufrufe[0].keywords}
    assert isinstance(kw["shell"], ast.Constant) and kw["shell"].value is False
    assert "timeout" in kw and isinstance(aufrufe[0].args[0], ast.Name)
    module = {a.name for n in ast.walk(baum) if isinstance(n, ast.Import) for a in n.names}
    module |= {n.module or "" for n in ast.walk(baum) if isinstance(n, ast.ImportFrom)}
    assert module <= {"__future__", "difflib", "os", "re", "subprocess", "dataclasses", "pathlib", "procflags"}, module
    # Nur lesende git-Befehle
    befehle = set()
    for n in ast.walk(baum):
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_git":
            liste = n.args[2]
            if isinstance(liste, ast.List):
                erstes = liste.elts[0]
                if isinstance(erstes, ast.Starred):
                    befehle.add("diff")
                else:
                    befehle.add(erstes.value)
    assert befehle == {"rev-parse", "merge-base", "diff", "cat-file"}, befehle
    assert "os.system" not in quelle and "Popen" not in quelle


# --- Integration: echtes lokales git-Repo ---------------------------------------------------------------------------

GIT = schutz._git_programm()


def _git(repo: Path, *args: str, eingabe: bytes | None = None) -> str:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"})
    r = subprocess.run([GIT, "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false",
                        "-C", str(repo), *args], input=eingabe, capture_output=True, check=True, timeout=60, env=env)
    return r.stdout.decode("utf-8").strip()


def _schreibe(repo: Path, pfad: str, text: str) -> None:
    ziel = repo / pfad
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_bytes(text.encode("utf-8"))


def _commit(repo: Path, nachricht: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-verify", "-m", nachricht)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    assert GIT, "git wird für die Werkstatt gebraucht"
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "master")
    _git(r, "config", "user.name", "Test")
    _git(r, "config", "user.email", "test@example.invalid")
    _schreibe(r, "src/kushim/safety/rules.py", "REGEL = 1\n")
    _schreibe(r, "src/kushim/stage/a.py", "A = 1\n")
    _schreibe(r, "tests/test_a.py", "def test_a():\n    assert True\n\n\ndef test_b():\n    assert 2 > 1\n")
    _commit(r, "basis")
    _git(r, "checkout", "-q", "-b", "werkstatt")
    return r


def test_integration_harmloser_zweig_ist_ok(repo):
    _schreibe(repo, "src/kushim/stage/rezepte/neu.json", '{"name": "lorenz"}\n')
    _schreibe(repo, "ui/src/components/x.tsx", "export const X = 1;\n")
    with open(repo / "tests/test_a.py", "a", encoding="utf-8", newline="\n") as f:
        f.write("\n\ndef test_c():\n    assert 3 > 2\n")
    _commit(repo, "harmlos")
    ergebnis = pruefe_commits(repo, "master", "werkstatt")
    assert ergebnis.ok, ergebnis.gruende


def test_integration_verbotener_zweig_nennt_alle_gruende(repo):
    _schreibe(repo, "src/kushim/safety/rules.py", "REGEL = 0\n")
    _schreibe(repo, "tests/test_a.py", "import pytest\n\n\n@pytest.mark.skip\ndef test_a():\n    assert True\n")
    _schreibe(repo, "src/kushim/stage/tief/conftest.py", "collect_ignore = ['x']\n")
    _commit(repo, "böse")
    sha = _git(repo, "hash-object", "-w", "--stdin", eingabe=b"../safety/rules.py")
    _git(repo, "update-index", "--add", "--cacheinfo", f"120000,{sha},src/kushim/stage/link")
    basis = _git(repo, "rev-parse", "master")
    _git(repo, "update-index", "--add", "--cacheinfo", f"160000,{basis},src/kushim/stage/sub")
    _git(repo, "commit", "-q", "--no-verify", "-m", "link und submodul")
    gefunden = {(g.code, g.pfad) for g in pruefe_commits(repo, "master", "werkstatt").gruende}
    assert {("GESCHUETZT", "src/kushim/safety/rules.py"), ("GESCHUETZT", "src/kushim/stage/tief/conftest.py"),
            ("TEST_MARKER", "tests/test_a.py"), ("TEST_ZEILEN_GELOESCHT", "tests/test_a.py"),
            ("SYMLINK", "src/kushim/stage/link"), ("SUBMODUL", "src/kushim/stage/sub")} <= gefunden, gefunden


def test_integration_umbenennen_aus_geschuetztem_ordner(repo):
    _git(repo, "mv", "src/kushim/safety/rules.py", "src/kushim/stage/rules.py")
    _git(repo, "commit", "-q", "--no-verify", "-m", "weg damit")
    gefunden = {(g.code, g.pfad) for g in pruefe_commits(repo, "master", "werkstatt").gruende}
    assert ("GESCHUETZT", "src/kushim/safety/rules.py") in gefunden


def test_integration_grossschreibung_im_baum(repo):
    sha = _git(repo, "hash-object", "-w", "--stdin", eingabe=b"REGEL = 0\n")
    _git(repo, "update-index", "--add", "--cacheinfo", f"100644,{sha},SRC/Kushim/Safety/x.py")
    _git(repo, "commit", "-q", "--no-verify", "-m", "gross")
    gefunden = {(g.code, g.pfad) for g in pruefe_commits(repo, "master", "werkstatt").gruende}
    assert ("GESCHUETZT", "SRC/Kushim/Safety/x.py") in gefunden


def test_integration_testdatei_geloescht_und_binaer(repo):
    _git(repo, "rm", "-q", "tests/test_a.py")
    (repo / "tests" / "data").mkdir(parents=True)
    (repo / "tests" / "data" / "x.bin").write_bytes(bytes(range(256)))
    _commit(repo, "tests weg")
    gefunden = {(g.code, g.pfad) for g in pruefe_commits(repo, "master", "werkstatt").gruende}
    assert {("TEST_GELOESCHT", "tests/test_a.py"), ("TEST_BINAER", "tests/data/x.bin")} <= gefunden, gefunden


def test_integration_refs_und_vorfahr(repo):
    _schreibe(repo, "docs/neu.md", "neu\n")
    _commit(repo, "doku")
    for falsch in ("--output=x", "-p", "master..werkstatt", "", "a b", "master@{1}", "HEAD~1:../x"):
        assert [g.code for g in pruefe_commits(repo, falsch, "werkstatt").gruende] == ["REF_UNGUELTIG"], falsch
    assert [g.code for g in pruefe_commits(repo, "gibtsnicht", "werkstatt").gruende] == ["REF_UNGUELTIG"]
    assert [g.code for g in pruefe_commits(repo, "werkstatt", "master").gruende] == ["BASIS_KEIN_VORFAHR"]
    assert [g.code for g in pruefe_commits(repo.parent / "fehlt", "master", "werkstatt").gruende] == ["GIT_FEHLER"]
    assert pruefe_commits(repo, "master", "werkstatt").ok


def test_integration_git_aufrufe_verstecken_das_fenster(repo, monkeypatch):
    gesehen = []
    echt = subprocess.run

    def spion(argv, **kw):
        gesehen.append((argv[0], kw.get("shell"), kw.get("creationflags"), kw.get("timeout")))
        return echt(argv, **kw)
    monkeypatch.setattr(schutz.subprocess, "run", spion)
    pruefe_commits(repo, "master", "werkstatt")
    assert gesehen and all(os.path.isabs(p) and s is False and t == schutz.GIT_TIMEOUT_S for p, s, _, t in gesehen)
    if os.name == "nt":
        assert all(f == 0x08000000 for _, _, f, _ in gesehen)
