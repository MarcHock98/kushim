"""Schutzprüfung der Werkstatt: darf ein Werkstatt-Zweig nach master?

`pruefe` ist eine reine Funktion. Sie wertet die Ausgabe von `git diff --raw -M -C` (oder `git diff --name-status -M`) und von
`git diff --numstat` zwischen `base` und `head` aus, dazu je Datei Größe, Modus und hinzugefügte Zeilen (`Datei`).
`pruefe_commits` liest diese Angaben nur lesend aus einem lokalen Repo (git als Argumentliste, kein Shell, verstecktes Fenster,
Zeitlimit) und ruft `pruefe` auf.

Die Regeln stehen fest im Code, nicht in einer Konfiguration; dieses Modul liegt selbst unter einem geschützten Pfad
(`src/kushim/werkstatt/**`). Jeder Grund ist ein fester Code mit Pfad, nie Dateiinhalt. Im Zweifel lehnt die Prüfung ab:
unlesbare Zeilen, fehlende Angaben, fremde Status, ungewöhnliche Pfade.
"""
from __future__ import annotations

import difflib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..procflags import hidden

# --- Feste Codes --------------------------------------------------------------------------------------------------

GESCHUETZT = "GESCHUETZT"                      # geschützter Pfad geändert, angelegt, gelöscht, umbenannt oder kopiert
PFAD_UNGUELTIG = "PFAD_UNGUELTIG"              # `..`, `.`, Backslash, absolut, `:`, Steuerzeichen, Nicht-ASCII, `~1`, Punkt/Leerzeichen am Ende
SYMLINK = "SYMLINK"                            # Modus 120000
SUBMODUL = "SUBMODUL"                          # Modus 160000
TYPWECHSEL = "TYPWECHSEL"                      # Status T (Datei <-> Symlink <-> Submodul)
TEST_GELOESCHT = "TEST_GELOESCHT"              # bestehende Testdatei gelöscht
TEST_UMBENANNT = "TEST_UMBENANNT"              # bestehende Testdatei umbenannt (alter Pfad verschwindet)
TEST_ZEILEN_GELOESCHT = "TEST_ZEILEN_GELOESCHT"  # bestehende Testdatei: gelöschte Zeilen laut numstat
TEST_MARKER = "TEST_MARKER"                    # hinzugefügte Zeile mit skip/xfail/.only(/todo( ...
TEST_BINAER = "TEST_BINAER"                    # Binärdatei unter den Tests
ABHAENGIGKEIT = "ABHAENGIGKEIT"                # Paketliste, Lockdatei, Paketarchiv oder Paketordner
AUSFUEHRBAR = "AUSFUEHRBAR"                    # .exe, .dll, .pyd, .bat, .ps1, .pyc ...
ZU_GROSS = "ZU_GROSS"                          # eine Datei über MAX_DATEI_BYTES
GESAMT_ZU_GROSS = "GESAMT_ZU_GROSS"            # alle Dateien zusammen über MAX_GESAMT_BYTES
ZU_VIELE_DATEIEN = "ZU_VIELE_DATEIEN"          # mehr als MAX_DATEIEN Einträge
INHALT_FEHLT = "INHALT_FEHLT"                  # keine Angaben (Größe, Zeilen) zu einer Datei
NUMSTAT_FEHLT = "NUMSTAT_FEHLT"                # Testdatei ohne numstat-Zeile
INKONSISTENT = "INKONSISTENT"                  # numstat nennt einen Pfad, den name-status nicht kennt
STATUS_UNBEKANNT = "STATUS_UNBEKANNT"          # Status U, X, B oder unbekannt
ZEILE_UNLESBAR = "ZEILE_UNLESBAR"              # Zeile passt in kein bekanntes Format
GIT_FEHLER = "GIT_FEHLER"                      # git nicht gefunden, Fehler oder Zeitlimit
REF_UNGUELTIG = "REF_UNGUELTIG"                # base/head kein gültiger Name oder kein Commit
BASIS_KEIN_VORFAHR = "BASIS_KEIN_VORFAHR"      # base ist kein Vorfahr von head

CODES = frozenset({GESCHUETZT, PFAD_UNGUELTIG, SYMLINK, SUBMODUL, TYPWECHSEL, TEST_GELOESCHT, TEST_UMBENANNT,
                   TEST_ZEILEN_GELOESCHT, TEST_MARKER, TEST_BINAER, ABHAENGIGKEIT, AUSFUEHRBAR, ZU_GROSS, GESAMT_ZU_GROSS,
                   ZU_VIELE_DATEIEN, INHALT_FEHLT, NUMSTAT_FEHLT, INKONSISTENT, STATUS_UNBEKANNT, ZEILE_UNLESBAR, GIT_FEHLER,
                   REF_UNGUELTIG, BASIS_KEIN_VORFAHR})

# --- Grenzen ------------------------------------------------------------------------------------------------------

MAX_DATEI_BYTES = 200 * 1024
MAX_GESAMT_BYTES = 2 * 1024 * 1024
MAX_DATEIEN = 300
GIT_TIMEOUT_S = 30

# --- Geschützte Pfade (verglichen in Kleinschreibung, mit `/`, ohne `.`-Teile) -----------------------------------------

# Ordner samt Inhalt. Unter `src/kushim/` zählt auch ein gleichnamiges Modul daneben (`safety.py`, `safety.pyd`), weil Python
# es statt des Pakets laden könnte.
GESCHUETZTE_ORDNER = (
    "src/kushim/safety", "src/kushim/channel", "src/kushim/werkstatt", "src/kushim/net", "src/kushim/claude_cli",
    "ui/src-tauri", ".claude", "scripts", ".github", "run", "models", "tools", "bin",
)
GESCHUETZTE_DATEIEN = frozenset({
    "tests/test_ui_rules.py", "tests/test_rules.py", "tests/test_killswitch.py",
    "pyproject.toml", "ui/package.json", "ui/package-lock.json", "ui/vite.config.ts", "ui/index.html", "ui/src/test-setup.ts",
    "install.ps1",
})
GESCHUETZTE_MUSTER = (
    re.compile(r"tests/test_no_egress[^/]*\.py"),
    re.compile(r"tests/test_werkstatt_[^/]*\.py"),
)
# Dateinamen, die in jeder Tiefe geschützt sind: Test-Sammlung und -Konfiguration, Start-Hooks von Python, Vite/Vitest,
# kushim-Konfiguration, alles, was mit `.git` beginnt (.gitignore, .gitattributes, .gitmodules, ein `.git`-Ordner).
GESCHUETZTE_NAMEN = (
    re.compile(r"conftest\.py"), re.compile(r"\.?pytest\.ini"), re.compile(r"tox\.ini"), re.compile(r"setup\.(cfg|py)"),
    re.compile(r"noxfile\.py"), re.compile(r"(site|user)customize\.py"), re.compile(r".*\.pth"),
    re.compile(r"(vite|vitest)\.(config|workspace)\.[^/]*"),
    re.compile(r"config[^/]*\.toml"), re.compile(r"wakewords[^/]*\.toml"),
    re.compile(r"\.git.*"),
)

# Abhängigkeiten: Paketlisten, Lockdateien, Paketarchive, Paketordner.
ABHAENGIGKEIT_NAMEN = (
    re.compile(r".*requirements.*\.(txt|in)"), re.compile(r"constraints.*\.txt"), re.compile(r"pipfile(\.lock)?"),
    re.compile(r"(poetry|uv|pdm)\.lock"), re.compile(r"pyproject\.toml"), re.compile(r"setup\.(cfg|py)"),
    re.compile(r"package(-lock)?\.json"), re.compile(r"npm-shrinkwrap\.json"), re.compile(r"yarn\.lock"), re.compile(r"\.yarnrc.*"),
    re.compile(r"pnpm-(lock|workspace)\.yaml"), re.compile(r"bun\.lockb?"), re.compile(r"\.npmrc"), re.compile(r"deno\.jsonc?"),
    re.compile(r"cargo\.(toml|lock)"), re.compile(r"environment\.ya?ml"),
    re.compile(r".*\.(whl|egg|tgz|nupkg|jar|crate)"),
)
ABHAENGIGKEIT_ORDNER = frozenset({"node_modules", "site-packages", "dist-packages", ".venv", "venv"})

AUSFUEHRBAR_ENDUNGEN = frozenset({
    "exe", "dll", "pyd", "so", "dylib", "sys", "bat", "cmd", "com", "ps1", "psm1", "psd1", "vbs", "vbe", "wsf", "hta", "scr",
    "msi", "lnk", "reg", "cpl", "pyc", "pyo",
})

# Testdateien: alles unter einem Ordner `tests`/`__tests__` und die üblichen Namen (pytest, vitest).
_TEST_NAME = re.compile(r"test_[^/]*\.py|[^/]*_test\.py|[^/]*\.(test|spec)\.[^/]+|test-setup\.[^/]+")
# Hinzugefügte Zeilen in Testdateien: nichts, was Tests überspringt, erwartet scheitern lässt, fokussiert oder abschaltet.
TEST_MARKER_MUSTER = re.compile(
    r"skip|xfail|expectedfailure|__test__|pytest\s*\.\s*exit|"
    r"\.\s*only\s*\(|\btodo\s*\(|\.\s*fails\s*\(|\b(?:xit|xtest|xdescribe|fdescribe|fit)\s*\(",
    re.IGNORECASE,
)

MODUS_SYMLINK = "120000"
MODUS_SUBMODUL = "160000"


@dataclass(frozen=True)
class Grund:
    code: str
    pfad: str = ""

    def __str__(self) -> str:
        return f"{self.code} {self.pfad}".rstrip()


@dataclass(frozen=True)
class Ergebnis:
    ok: bool
    gruende: tuple[Grund, ...] = ()


@dataclass(frozen=True)
class Datei:
    """Angaben zum Stand in `head`: Größe in Bytes, Modus (z. B. "100644") und die hinzugefügten Zeilen (nur für Tests nötig)."""
    groesse: int | None = None
    modus: str | None = None
    neue_zeilen: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Eintrag:
    status: str
    alt: str | None          # alter Pfad (M, D, R, C, T); None bei A
    neu: str | None          # neuer Pfad (A, M, R, C, T); None bei D
    modus_alt: str | None = None
    modus_neu: str | None = None
    sha_alt: str | None = None
    sha_neu: str | None = None


class _Unlesbar(ValueError):
    pass


# --- Pfade ----------------------------------------------------------------------------------------------------------

_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def _entquote(pfad: str) -> str:
    """Hebt die C-Schreibweise von git auf (`"a\\tb"`, `"\\303\\244"`)."""
    if not (len(pfad) >= 2 and pfad[0] == '"' and pfad[-1] == '"'):
        if pfad.startswith('"'):
            raise _Unlesbar(pfad)
        return pfad
    inner, out, i = pfad[1:-1], bytearray(), 0
    while i < len(inner):
        c = inner[i]
        if c != "\\":
            out += c.encode("utf-8", "surrogateescape")
            i += 1
            continue
        if i + 1 >= len(inner):
            raise _Unlesbar(pfad)
        n = inner[i + 1]
        if n in _ESCAPES:
            out.append(_ESCAPES[n])
            i += 2
        elif re.fullmatch(r"[0-7]{3}", inner[i + 1:i + 4]):
            out.append(int(inner[i + 1:i + 4], 8) & 0xFF)
            i += 4
        else:
            raise _Unlesbar(pfad)
    return out.decode("utf-8", "replace")


def _normiere(pfad: str) -> tuple[str, bool]:
    """Vergleichsschlüssel (Kleinschreibung wie unter Windows, `/`, ohne `.`/`..`) und ob der Pfad auffällig ist."""
    auffaellig = False
    if not pfad or any(ord(c) < 0x20 or ord(c) > 0x7E for c in pfad):
        auffaellig = True                                    # Steuerzeichen, Nicht-ASCII (Unicode-Tricks), U+FFFD
    if "\\" in pfad or ":" in pfad or pfad.startswith("/"):
        auffaellig = True                                    # Backslash, Laufwerk, NTFS-Datenstrom, absolut
    teile: list[str] = []
    for teil in pfad.replace("\\", "/").split("/"):
        if teil in ("", "."):
            auffaellig = auffaellig or teil == "." or bool(teile)
            continue
        if teil == "..":
            auffaellig = True
            if teile:
                teile.pop()
            continue
        sauber = teil.rstrip(" .")                           # Windows ignoriert Punkte und Leerzeichen am Ende
        if sauber != teil or re.search(r"~\d", sauber):      # ... und kennt Kurznamen wie SAFETY~1
            auffaellig = True
        if not sauber:
            continue
        teile.append(sauber.upper().casefold())              # upper() zuerst: "ı"/"ſ" wie NTFS auf i/s
    if not teile:
        auffaellig = True
    return "/".join(teile), auffaellig


def _anzeige(pfad: str) -> str:
    """Pfad für den Grund: nur druckbares ASCII, gekürzt. Nie Dateiinhalt."""
    s = "".join(c if 0x20 <= ord(c) <= 0x7E else "?" for c in pfad)
    return s if len(s) <= 200 else s[:197] + "..."


def _name(schluessel: str) -> str:
    return schluessel.rsplit("/", 1)[-1]


def ist_geschuetzt(schluessel: str) -> bool:
    """`schluessel` ist ein normierter Pfad (siehe `_normiere`)."""
    for ordner in GESCHUETZTE_ORDNER:
        if schluessel == ordner or schluessel.startswith(ordner + "/"):
            return True
        if ordner.startswith("src/kushim/") and schluessel.startswith(ordner + "."):
            return True
    if schluessel in GESCHUETZTE_DATEIEN or any(m.fullmatch(schluessel) for m in GESCHUETZTE_MUSTER):
        return True
    teile = schluessel.split("/")
    if any(t.startswith(".git") for t in teile):
        return True
    return any(m.fullmatch(teile[-1]) for m in GESCHUETZTE_NAMEN)


def ist_test(schluessel: str) -> bool:
    teile = schluessel.split("/")
    return any(t in ("tests", "__tests__") for t in teile[:-1]) or bool(_TEST_NAME.fullmatch(teile[-1]))


def _ist_abhaengigkeit(schluessel: str) -> bool:
    teile = schluessel.split("/")
    return any(t in ABHAENGIGKEIT_ORDNER for t in teile[:-1]) or any(m.fullmatch(teile[-1]) for m in ABHAENGIGKEIT_NAMEN)


def _ist_ausfuehrbar(schluessel: str) -> bool:
    name = _name(schluessel)
    return "." in name and name.rsplit(".", 1)[1] in AUSFUEHRBAR_ENDUNGEN


# --- Ausgaben von git lesen -----------------------------------------------------------------------------------------

_STATUS = re.compile(r"([ACDMRTUXB])(\d{0,3})")
_MODUS = re.compile(r"[0-7]{6}")
_SHA = re.compile(r"[0-9a-f]{4,64}\.{0,3}")


def _lies_name_status(text: str) -> list[_Eintrag]:
    """Zeilen von `--raw` (`:100644 100644 sha sha M\\tpfad`) oder `--name-status` (`M\\tpfad`). Wirft `_Unlesbar`."""
    eintraege = []
    for zeile in text.split("\n"):
        zeile = zeile.rstrip("\r")
        if not zeile.strip():
            continue
        kopf, sep, rest = zeile.partition("\t")
        if not sep:
            raise _Unlesbar(zeile)
        pfade = [_entquote(p) for p in rest.split("\t")]
        felder = kopf.split()
        modus_alt = modus_neu = sha_alt = sha_neu = None
        if kopf.startswith(":"):
            if len(felder) != 5 or not (_MODUS.fullmatch(felder[0][1:]) and _MODUS.fullmatch(felder[1])
                                        and _SHA.fullmatch(felder[2]) and _SHA.fullmatch(felder[3])):
                raise _Unlesbar(zeile)
            modus_alt, modus_neu, sha_alt, sha_neu = felder[0][1:], felder[1], felder[2], felder[3]
            felder = felder[4:]
        if len(felder) != 1:
            raise _Unlesbar(zeile)
        m = _STATUS.fullmatch(felder[0])
        if not m:
            raise _Unlesbar(zeile)
        status = m.group(1)
        if status in "RC":
            if len(pfade) != 2:
                raise _Unlesbar(zeile)
            alt, neu = pfade
        else:
            if len(pfade) != 1:
                raise _Unlesbar(zeile)
            alt = None if status == "A" else pfade[0]
            neu = None if status == "D" else pfade[0]
        eintraege.append(_Eintrag(status, alt, neu, modus_alt, modus_neu, sha_alt, sha_neu))
    return eintraege


_KLAMMER = re.compile(r"(.*)\{(.*) => (.*)\}(.*)")


def _lies_numstat(text: str) -> list[tuple[int | None, int | None, list[str]]]:
    """Zeilen `hinzu\\tweg\\tpfad` (`-\\t-` bei Binärdateien); Umbenennungen als `alt => neu` oder `a/{x => y}/b`.
    Liefert (hinzu, weg, [pfade]); bei Umbenennung [alt, neu]. Wirft `_Unlesbar`."""
    zeilen = []
    for zeile in text.split("\n"):
        zeile = zeile.rstrip("\r")
        if not zeile.strip():
            continue
        teile = zeile.split("\t", 2)
        if len(teile) != 3 or not all(re.fullmatch(r"\d+|-", t) for t in teile[:2]):
            raise _Unlesbar(zeile)
        hinzu, weg = (None if t == "-" else int(t) for t in teile[:2])
        pfad = teile[2]
        if pfad.startswith('"') or " => " not in pfad:
            zeilen.append((hinzu, weg, [_entquote(pfad)]))
            continue
        m = _KLAMMER.fullmatch(pfad)
        if m:
            vor, a, b, nach = m.groups()
            alt, neu = (re.sub("/+", "/", vor + x + nach) for x in (a, b))
        else:
            alt, _, neu = pfad.partition(" => ")
        zeilen.append((hinzu, weg, [alt, neu]))
    return zeilen


# --- Die Prüfung ----------------------------------------------------------------------------------------------------

def pruefe(name_status: str, numstat: str, dateien: dict[str, Datei] | None) -> Ergebnis:
    """Prüft einen Diff `base..head`.

    `name_status`: Ausgabe von `git diff --raw -M -C` (mit Modi) oder `git diff --name-status -M`.
    `numstat`: Ausgabe von `git diff --numstat` (am besten `--no-renames`).
    `dateien`: je neuem Pfad die Angaben in `head` (`Datei`); fehlt sie oder ein Eintrag, lehnt die Prüfung ab.
    """
    gruende: list[Grund] = []

    def grund(code: str, pfad: str = "") -> None:
        g = Grund(code, _anzeige(pfad))
        if g not in gruende:
            gruende.append(g)

    try:
        eintraege = _lies_name_status(name_status)
    except _Unlesbar:
        return Ergebnis(False, (Grund(ZEILE_UNLESBAR, "name-status"),))
    try:
        stat = _lies_numstat(numstat)
    except _Unlesbar:
        return Ergebnis(False, (Grund(ZEILE_UNLESBAR, "numstat"),))

    if len(eintraege) > MAX_DATEIEN:
        grund(ZU_VIELE_DATEIEN)

    # numstat je normiertem Pfad (bei Umbenennungen zählt die Zeile für den neuen Pfad)
    stat_je_pfad: dict[str, tuple[int | None, int | None]] = {}
    stat_pfade: list[tuple[str, str]] = []
    for hinzu, weg, pfade in stat:
        for p in pfade:
            stat_pfade.append((p, _normiere(p)[0]))
        schluessel = _normiere(pfade[-1])[0]
        alt = stat_je_pfad.get(schluessel)
        if alt is not None:     # dieselbe Datei zweimal (z. B. Umbenennung und Kopie): Summen bilden, Binär bleibt Binär
            hinzu = None if alt[0] is None or hinzu is None else alt[0] + hinzu
            weg = None if alt[1] is None or weg is None else alt[1] + weg
        stat_je_pfad[schluessel] = (hinzu, weg)

    angaben: dict[str, Datei] | None = None
    if dateien is not None:
        angaben = {_normiere(k)[0]: v for k, v in dateien.items()}

    bekannte: set[str] = set()
    gesamt = 0
    for e in eintraege:
        pfade = [p for p in (e.alt, e.neu) if p is not None]
        for p in pfade:
            schluessel, auffaellig = _normiere(p)
            bekannte.add(schluessel)
            if auffaellig:
                grund(PFAD_UNGUELTIG, p)
            if ist_geschuetzt(schluessel):
                grund(GESCHUETZT, p)
            if _ist_abhaengigkeit(schluessel):
                grund(ABHAENGIGKEIT, p)

        if e.status not in "ACDMRT":
            grund(STATUS_UNBEKANNT, pfade[0] if pfade else "")
            continue
        if e.status == "T":
            grund(TYPWECHSEL, pfade[0])
        for modus in (e.modus_alt, e.modus_neu):
            if modus == MODUS_SYMLINK:
                grund(SYMLINK, pfade[-1])
            elif modus == MODUS_SUBMODUL:
                grund(SUBMODUL, pfade[-1])

        # bestehende Testdateien: nie löschen, nie wegbenennen, keine Zeile löschen
        if e.alt is not None and ist_test(_normiere(e.alt)[0]):
            if e.status == "D":
                grund(TEST_GELOESCHT, e.alt)
            elif e.status == "R":
                grund(TEST_UMBENANNT, e.alt)

        if e.neu is None:
            continue
        neu_schluessel = _normiere(e.neu)[0]
        if _ist_ausfuehrbar(neu_schluessel):
            grund(AUSFUEHRBAR, e.neu)

        datei = None if angaben is None else angaben.get(neu_schluessel)
        if datei is None:
            grund(INHALT_FEHLT, e.neu)
        else:
            if datei.modus == MODUS_SYMLINK:
                grund(SYMLINK, e.neu)
            elif datei.modus == MODUS_SUBMODUL:
                grund(SUBMODUL, e.neu)
            if datei.groesse is None:
                grund(INHALT_FEHLT, e.neu)
            elif e.modus_neu != MODUS_SUBMODUL and datei.modus != MODUS_SUBMODUL:
                if datei.groesse > MAX_DATEI_BYTES:
                    grund(ZU_GROSS, e.neu)
                gesamt += max(0, datei.groesse)

        if ist_test(neu_schluessel):
            zahlen = stat_je_pfad.get(neu_schluessel)
            if zahlen is None:
                grund(NUMSTAT_FEHLT, e.neu)
            else:
                hinzu, weg = zahlen
                if hinzu is None or weg is None:
                    grund(TEST_BINAER, e.neu)
                elif e.status in "MT" and weg > 0:
                    grund(TEST_ZEILEN_GELOESCHT, e.neu)
            if datei is not None and any(TEST_MARKER_MUSTER.search(z) for z in datei.neue_zeilen):
                grund(TEST_MARKER, e.neu)

    if gesamt > MAX_GESAMT_BYTES:
        grund(GESAMT_ZU_GROSS)
    for roh, schluessel in stat_pfade:
        if schluessel not in bekannte:
            grund(INKONSISTENT, roh)

    return Ergebnis(not gruende, tuple(gruende))


# --- Nur lesender git-Leser -----------------------------------------------------------------------------------------

_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")


def _ref_ok(ref: str) -> bool:
    return bool(_REF.fullmatch(ref)) and ".." not in ref and "//" not in ref and not ref.endswith((".lock", "/", "."))


def _git_programm() -> str | None:
    """git nur aus absoluten PATH-Einträgen, nie aus dem aktuellen Ordner (Windows sucht sonst dort zuerst)."""
    name = "git.exe" if os.name == "nt" else "git"
    for ordner in os.environ.get("PATH", "").split(os.pathsep):
        ordner = ordner.strip().strip('"')
        if ordner and os.path.isabs(ordner):
            kandidat = os.path.join(ordner, name)
            if os.path.isfile(kandidat):
                return kandidat
    return None


def _git(programm: str, repo: Path, args: list[str], eingabe: bytes | None = None, codes: tuple[int, ...] = (0,)) -> tuple[int, bytes]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "GIT_CONFIG_NOSYSTEM": "1"})
    befehl = [programm, "--no-pager", "-c", "core.quotepath=false", "-c", "core.fsmonitor=false", "-C", str(repo), *args]
    r = subprocess.run(befehl, input=eingabe, capture_output=True, timeout=GIT_TIMEOUT_S, check=False, shell=False,
                       cwd=str(repo), env=env, **hidden())
    if r.returncode not in codes:
        raise RuntimeError("git")
    return r.returncode, r.stdout


def _commit(programm: str, repo: Path, ref: str) -> str | None:
    try:
        _, out = _git(programm, repo, ["rev-parse", "--verify", "--quiet", "--end-of-options", ref + "^{commit}"])
    except RuntimeError:
        return None
    sha = out.decode("ascii", "replace").strip()
    return sha if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha) else None


def _hinzugefuegt(alt: bytes, neu: bytes) -> tuple[str, ...]:
    a = alt.decode("utf-8", "replace").splitlines()
    b = neu.decode("utf-8", "replace").splitlines()
    zeilen: list[str] = []
    for tag, _, _, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("insert", "replace"):
            zeilen.extend(b[j1:j2])
    return tuple(zeilen)


def pruefe_commits(repo: str | os.PathLike[str], base: str, head: str) -> Ergebnis:
    """Prüft `base..head` in einem lokalen Repo, nur lesend. `base` muss ein Vorfahr von `head` sein (dann ist der Diff genau
    das, was ein Merge nach master bringt). Nach einem Merge erneut mit dem alten und neuen master-Stand aufrufen."""
    programm = _git_programm()
    if programm is None:
        return Ergebnis(False, (Grund(GIT_FEHLER),))
    if not (_ref_ok(base) and _ref_ok(head)):
        return Ergebnis(False, (Grund(REF_UNGUELTIG),))
    try:
        ordner = Path(repo).resolve(strict=True)
        if not ordner.is_dir():
            return Ergebnis(False, (Grund(GIT_FEHLER),))
        alt, neu = _commit(programm, ordner, base), _commit(programm, ordner, head)
        if alt is None or neu is None:
            return Ergebnis(False, (Grund(REF_UNGUELTIG),))
        code, _ = _git(programm, ordner, ["merge-base", "--is-ancestor", alt, neu], codes=(0, 1))
        if code != 0:
            return Ergebnis(False, (Grund(BASIS_KEIN_VORFAHR),))
        diff = ["diff", "--no-ext-diff", "--no-textconv", "--no-color"]
        _, roh = _git(programm, ordner, [*diff, "--raw", "--no-abbrev", "-M", "-C", alt, neu, "--"])
        _, num = _git(programm, ordner, [*diff, "--numstat", "--no-renames", alt, neu, "--"])
        roh_text, num_text = roh.decode("utf-8", "replace"), num.decode("utf-8", "replace")
        try:
            eintraege = _lies_name_status(roh_text)
        except _Unlesbar:
            return pruefe(roh_text, num_text, None)
        if len(eintraege) > MAX_DATEIEN:
            return pruefe(roh_text, num_text, None)

        # Größen aller neuen Blobs in einem Aufruf (Submodule haben keinen Blob)
        blobs = sorted({e.sha_neu for e in eintraege if e.neu is not None and e.sha_neu and e.modus_neu != MODUS_SUBMODUL})
        groessen: dict[str, int] = {}
        if blobs:
            _, out = _git(programm, ordner, ["cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"],
                          eingabe=("\n".join(blobs) + "\n").encode("ascii"))
            for zeile in out.decode("ascii", "replace").splitlines():
                teile = zeile.split()
                if len(teile) == 3 and teile[1] == "blob" and teile[2].isdigit():
                    groessen[teile[0]] = int(teile[2])

        dateien: dict[str, Datei] = {}
        for e in eintraege:
            if e.neu is None:
                continue
            groesse = groessen.get(e.sha_neu or "")
            neue: tuple[str, ...] = ()
            if (ist_test(_normiere(e.neu)[0]) and groesse is not None and groesse <= MAX_DATEI_BYTES
                    and e.modus_neu not in (MODUS_SYMLINK, MODUS_SUBMODUL)):
                _, inhalt = _git(programm, ordner, ["cat-file", "blob", e.sha_neu])
                vorher = b""
                if e.alt is not None and e.sha_alt and e.modus_alt not in (MODUS_SYMLINK, MODUS_SUBMODUL) \
                        and groessen.get(e.sha_alt, 0) <= MAX_DATEI_BYTES and set(e.sha_alt) != {"0"}:
                    _, vorher = _git(programm, ordner, ["cat-file", "blob", e.sha_alt])
                neue = _hinzugefuegt(vorher, inhalt)
            dateien[e.neu] = Datei(groesse=groesse, modus=e.modus_neu, neue_zeilen=neue)
        return pruefe(roh_text, num_text, dateien)
    except (OSError, RuntimeError, subprocess.SubprocessError, UnicodeError, ValueError):
        return Ergebnis(False, (Grund(GIT_FEHLER),))
