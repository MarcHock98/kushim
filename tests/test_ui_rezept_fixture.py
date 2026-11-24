"""P7 Stufe 1b: Die Rezept-Ansichten der Oberfläche (`ui/src/fixtures/rezept_ansichten.json`) sind genau das, was das Backend aus
`{typ: "sim_eigen", rezept: name}` für jedes Rezept im Buch macht (stage/rezepte/*.json). `ui/src/rezepte.test.ts` lässt sie mit der
echten Engine einige Sekunden rechnen. Die Datei entsteht mit `schema.validate` und wird neu geschrieben mit:

    PYTHONPATH=src python tests/test_ui_rezept_fixture.py
"""
import json
from pathlib import Path

import pytest

from kushim.stage import rezepte, schema

FIXTURE = Path(__file__).resolve().parents[1] / "ui" / "src" / "fixtures" / "rezept_ansichten.json"


def _view(name):
    return schema.validate({"id": "rezept-" + name.replace("_", "-"), "art": "simulation", "titel": rezepte.hole(name)["name"],
                            "bausteine": [{"typ": "sim_eigen", "rezept": name}]})


def build():
    """Je Rezept eine Ansicht, in der Reihenfolge von `rezepte.namen()`."""
    return {
        "hinweis": "Erzeugt mit schema.validate aus den Rezepten in src/kushim/stage/rezepte/ (je Rezept {typ: sim_eigen, rezept: name}). "
                   "Neu schreiben: PYTHONPATH=src python tests/test_ui_rezept_fixture.py",
        "ansichten": [_view(n) for n in rezepte.namen()],
    }


DATA = json.loads(FIXTURE.read_text(encoding="utf-8")) if FIXTURE.exists() else {}     # fehlt sie, scheitert der erste Test


def test_fixture_is_exactly_what_the_backend_makes_of_every_recipe():
    assert DATA == build()


def test_fixture_has_one_view_per_recipe():
    assert [v["bausteine"][0]["rezept"] for v in DATA["ansichten"]] == list(rezepte.namen())
    assert len(rezepte.namen()) >= 8 and {"lorenz", "raeuber_beute", "pendel_gedaempft", "federkette"} <= set(rezepte.namen())


@pytest.mark.parametrize("view", DATA.get("ansichten", []), ids=lambda v: v["id"])
def test_fixture_views_pass_the_second_check_unchanged(view):
    assert schema.validate(view) == view
    assert schema.validate(json.loads(json.dumps(view))) == view


@pytest.mark.parametrize("view", DATA.get("ansichten", []), ids=lambda v: v["id"])
def test_fixture_views_hold_no_formula_text(view):
    def texte(v, key=""):                                                     # alle Texte außer TeX (das darf wie die Formel aussehen)
        if isinstance(v, dict):
            return [t for k, x in v.items() if k != "tex" for t in texte(x, k)]
        if isinstance(v, list):
            return [t for x in v for t in texte(x, key)]
        return [v] if isinstance(v, str) else []

    roh = rezepte.hole(view["bausteine"][0]["rezept"])
    formeln = [*roh.get("ableitungen", {}).values(), roh.get("erhaltung") or "", (roh.get("paar") or {}).get("f_r", "")]
    formeln += [(roh.get("kraft") or {}).get(k, "") for k in ("fx", "fy")]
    formeln += [h["formel"] for h in roh.get("hilf", [])] + [k["formel"] for k in roh.get("kennwerte", [])]
    formeln += [d[a] for d in roh["darstellung"] if d["form"] == "koerper" and "x" in d for a in ("x", "y")]
    erlaubt = {"", "0"}                                                       # leer, ein Name oder eine Zahl ist kein Formeltext
    erlaubt |= {z["name"] for z in roh.get("zustand", [])}
    assert not (set(formeln) - erlaubt) & set(texte(view))


if __name__ == "__main__":                                                   # einmal neu schreiben (CRLF wie im Repo)
    text = json.dumps(build(), ensure_ascii=False, indent=1) + "\n"
    FIXTURE.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    print(f"{FIXTURE} geschrieben")
