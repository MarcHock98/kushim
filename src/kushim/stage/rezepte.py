"""Rezeptbuch für `sim_eigen` (Plan P7 Stufe 1b, docs/ui-p7-plan.md Abschnitt 3).

Bewährte Beschreibungen eigener Simulationen liegen als JSON im festen Paketordner `stage/rezepte/` (Eingabeform eines `sim_eigen`
ohne `typ`, mit Formeltext). Sie werden einmal beim Import geladen: nur Dateien mit Namen `[a-z0-9_]{1,32}.json` direkt in diesem
Ordner, keine Verknüpfungen, höchstens MAX_BYTES groß, höchstens MAX_REZEPTE Stück. Jedes Rezept wird wie eine Ansicht von Claude mit
`schema.validate` geprüft; ein ungültiges wird mit festem Fehlercode ausgelassen (`fehler()`, die Tests melden es), der Start scheitert
daran nie. Danach trägt das Modul das Buch in `schema` ein (schema.py liest selbst keine Dateien).

Pfade von außen gibt es nicht: `hole(name)` sucht nur im geladenen Buch. Nur Standardbibliothek, kein Netz; hier wird nichts
geschrieben, ausgeführt oder gesendet.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import schema

ORDNER = Path(__file__).resolve().parent / "rezepte"
NAME = re.compile(r"[a-z0-9_]{1,32}")
MAX_BYTES = 16 * 1024
MAX_REZEPTE = 24
NICHT_IM_REZEPT = ("typ", "rezept", "env", "kosten", "integrator")   # Eingabeform: kein Typ, kein Verweis, nichts Abgeleitetes


def _keine_konstante(_: str) -> Any:
    raise ValueError("NaN/Infinity")


def _lies(datei: Path, ordner: Path) -> dict[str, Any] | str:
    """Ein Rezept als dict oder ein fester Fehlercode."""
    try:
        if datei.is_symlink() or not datei.is_file() or datei.resolve().parent != ordner.resolve():
            return "keine_datei"
        if datei.stat().st_size > MAX_BYTES:
            return "zu_gross"
        with datei.open("rb") as f:
            daten = f.read(MAX_BYTES + 1)
    except OSError:
        return "lesefehler"
    if len(daten) > MAX_BYTES:
        return "zu_gross"
    try:
        roh = json.loads(daten.decode("utf-8"), parse_constant=_keine_konstante)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return "kein_json"
    if not isinstance(roh, dict):
        return "kein_objekt"
    if any(k in roh for k in NICHT_IM_REZEPT):
        return "feld"
    try:
        schema.validate({"id": "rezept", "art": "simulation", "titel": "Rezept", "bausteine": [{"typ": "sim_eigen", **roh}]})
    except schema.ViewError as e:
        return f"ungueltig:{e}"
    return roh


def _lade(ordner: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Alle Rezepte aus `ordner` (nur zum Laden beim Import und für Tests). Gibt Buch und Fehler (Dateiname -> Code) zurück."""
    buch: dict[str, dict[str, Any]] = {}
    fehler: dict[str, str] = {}
    try:
        eintraege = sorted(ordner.iterdir(), key=lambda p: p.name)
    except OSError:
        return buch, {"": "kein_ordner"}
    for datei in eintraege:
        stamm = datei.name[:-5] if datei.name.endswith(".json") else ""
        if not NAME.fullmatch(stamm):
            fehler[datei.name] = "dateiname"
        elif len(buch) >= MAX_REZEPTE:
            fehler[datei.name] = "zu_viele"
        else:
            roh = _lies(datei, ordner)
            if isinstance(roh, str):
                fehler[datei.name] = roh
            else:
                buch[stamm] = roh
    return buch, fehler


_BUCH, _FEHLER = _lade(ORDNER)
schema.rezepte_eintragen(_BUCH)


def namen() -> tuple[str, ...]:
    """Die Namen aller gültigen Rezepte, sortiert."""
    return tuple(sorted(_BUCH))


def hole(name: Any) -> dict[str, Any] | None:
    """Eine Kopie des Rezepts (Eingabeform ohne `typ`) oder None. Sucht nur im geladenen Buch, nie im Dateisystem."""
    if not isinstance(name, str) or not NAME.fullmatch(name) or name not in _BUCH:
        return None
    return json.loads(json.dumps(_BUCH[name]))


def fehler() -> dict[str, str]:
    """Ausgelassene Dateien beim Laden: Dateiname -> fester Fehlercode (leer, wenn alles gültig ist)."""
    return dict(_FEHLER)


def _zahl(x: float | int) -> str:
    return f"{x:g}"


def uebersicht() -> str:
    """Kurzliste für die Beschreibung von `zeige`: je Rezept die Parameter mit Grenzen, z. B. `lorenz(s:0..50,r:0..100,bb:0..10)`."""
    teile = []
    for name in namen():
        params = ",".join(f"{p['name']}:{_zahl(p['min'])}..{_zahl(p['max'])}" for p in _BUCH[name].get("parameter", []))
        teile.append(f"{name}({params})")
    return ", ".join(teile)
