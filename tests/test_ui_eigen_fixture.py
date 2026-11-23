"""P7 Stufe 1: Die Demo-Ansichten der Oberfläche (`ui/src/fixtures/eigen_ansichten.json`, in `mock.ts` als EIGEN_DEMOS) sind genau das,
was das Backend aus den vier Beispielen des Plans (docs/ui-p7-plan.md, 2.5) macht. Die Eingaben stehen hier; die Datei entsteht mit
`schema.validate` und wird neu geschrieben mit:

    PYTHONPATH=src python tests/test_ui_eigen_fixture.py
"""
import json
from pathlib import Path

import pytest

from kushim.stage import schema

FIXTURE = Path(__file__).resolve().parents[1] / "ui" / "src" / "fixtures" / "eigen_ansichten.json"

PENDEL = {"name": "Gedämpftes Pendel", "form": "ode",
          "beschreibung": "Ein Fadenpendel mit Reibung, losgelassen bei 1,2 rad. Die Reibung wächst mit der Geschwindigkeit.",
          "parameter": [{"name": "g", "wert": 9.81, "min": 0.1, "max": 30, "einheit": "m/s²"},
                        {"name": "l", "wert": 1, "min": 0.1, "max": 10, "einheit": "m"},
                        {"name": "d", "wert": 0.2, "min": 0, "max": 5, "einheit": "1/s"}],
          "zustand": [{"name": "phi", "start": 1.2, "einheit": "rad"}, {"name": "w", "start": 0, "einheit": "rad/s"}],
          "ableitungen": {"phi": "w", "w": "-g/l*sin(phi) - d*w"},
          "darstellung": [{"form": "koerper", "x": "l*sin(phi)", "y": "-l*cos(phi)", "anker": [0, 0]},
                          {"form": "zeitreihe", "groessen": ["phi"]}],
          "kennwerte": [{"name": "Energie je Masse", "formel": "0.5*(l*w)^2 + g*l*(1-cos(phi))", "einheit": "J/kg"}]}
RAEUBER = {"name": "Räuber und Beute", "form": "ode",
           "beschreibung": "Beute B vermehrt sich, Räuber R fressen sie. Beide Bestände schwanken gegeneinander versetzt.",
           "parameter": [{"name": n, "wert": w, "min": 0, "max": 5, "einheit": "1/Jahr"}
                         for n, w in (("a", 1.1), ("b", 0.4), ("c", 0.4), ("dd", 0.1))],
           "zustand": [{"name": "B", "start": 10, "einheit": "Tiere"}, {"name": "R", "start": 5, "einheit": "Tiere"}],
           "ableitungen": {"B": "a*B - b*B*R", "R": "dd*B*R - c*R"}, "erhaltung": "dd*B - c*log(B) + b*R - a*log(R)",
           "darstellung": [{"form": "zeitreihe", "groessen": ["B", "R"]}, {"form": "phasenraum", "x": "B", "y": "R"}]}
LORENZ = {"name": "Lorenz-System", "form": "ode", "dt": 0.005,
          "beschreibung": "Drei gekoppelte Größen nach Lorenz. Die Bahn wechselt unregelmäßig zwischen zwei Schleifen.",
          "parameter": [{"name": "s", "wert": 10, "min": 0, "max": 50}, {"name": "r", "wert": 28, "min": 0, "max": 100},
                        {"name": "bb", "wert": 2.6667, "min": 0, "max": 10}],
          "zustand": [{"name": "x", "start": 1}, {"name": "y", "start": 1}, {"name": "z", "start": 1}],
          "ableitungen": {"x": "s*(y-x)", "y": "x*(r-z) - y", "z": "x*y - bb*z"},
          "darstellung": [{"form": "phasenraum", "x": "x", "y": "z"}, {"form": "zeitreihe", "groessen": ["x"]}]}
KETTE = {"name": "Federkette", "form": "teilchen", "anzahl": 12, "start": "linie", "kasten": [4, 3], "waende": "reflektieren",
         "beschreibung": "Zwölf Massen, mit Federn verbunden, die äußeren fest. Die Kette hängt unter ihrem Gewicht durch.",
         "fest": [0, 11], "masse": 0.1,                                     # im Plan als Parameter m; m ist im Teilchen-Platz die Masse
         "parameter": [{"name": "g", "wert": 9.81, "min": 0, "max": 30, "einheit": "m/s²"},
                       {"name": "c", "wert": 0.3, "min": 0, "max": 5, "einheit": "kg/s"}],
         "kraft": {"fx": "-c*vx", "fy": "-m*g - c*vy"}, "federn": {"kette": True, "k": 40, "l0": 0.25, "daempfung": 0.05},
         "darstellung": [{"form": "koerper"}]}
PENDEL_TITEL = "Gedämpftes Pendel (eigene Simulation, Beispiel)"


def _view(vid, titel, fields):
    return schema.validate({"id": vid, "art": "simulation", "titel": titel, "bausteine": [{"typ": "sim_eigen", **fields}]})


def build():
    """Die Datei, wie das Backend sie liefert: vier Ansichten und dieselbe Pendel-Ansicht mit Dämpfung 0,5 (gleiche id)."""
    return {
        "hinweis": "Erzeugt mit schema.validate aus den vier Beispielen des P7-Plans (docs/ui-p7-plan.md, 2.5). "
                   "Neu schreiben: PYTHONPATH=src python tests/test_ui_eigen_fixture.py",
        "ansichten": [_view("eigen-pendel", PENDEL_TITEL, PENDEL),
                      _view("eigen-raeuber", "Räuber und Beute (eigene Simulation, Beispiel)", RAEUBER),
                      _view("eigen-lorenz", "Lorenz-System (eigene Simulation, Beispiel)", LORENZ),
                      _view("eigen-kette", "Federkette (eigene Simulation, Beispiel)", KETTE)],
        "geaendert": _view("eigen-pendel", PENDEL_TITEL,
                           {**PENDEL, "parameter": [*PENDEL["parameter"][:2], {**PENDEL["parameter"][2], "wert": 0.5}]}),
    }


DATA = json.loads(FIXTURE.read_text(encoding="utf-8"))
VIEWS = [*DATA["ansichten"], DATA["geaendert"]]


def test_fixture_is_exactly_what_the_backend_makes_of_the_plan_examples():
    assert DATA == build()


def test_fixture_has_the_four_plan_examples_and_one_changed_pendulum():
    assert [v["id"] for v in DATA["ansichten"]] == ["eigen-pendel", "eigen-raeuber", "eigen-lorenz", "eigen-kette"]
    assert [v["bausteine"][0]["form"] for v in DATA["ansichten"]] == ["ode", "ode", "ode", "teilchen"]
    alt, neu = DATA["ansichten"][0], DATA["geaendert"]
    assert neu["id"] == alt["id"] and neu["titel"] == alt["titel"]
    werte = lambda v: {p["name"]: p["wert"] for p in v["bausteine"][0]["parameter"]}   # noqa: E731
    assert werte(alt) == {"g": 9.81, "l": 1, "d": 0.2} and werte(neu) == {"g": 9.81, "l": 1, "d": 0.5}
    rest = lambda v: {k: x for k, x in v["bausteine"][0].items() if k != "parameter"}   # noqa: E731
    assert rest(alt) == rest(neu)


@pytest.mark.parametrize("view", VIEWS, ids=lambda v: v["id"])
def test_fixture_views_pass_the_second_check_unchanged(view):
    assert schema.validate(view) == view
    assert schema.validate(json.loads(json.dumps(view))) == view


@pytest.mark.parametrize("view", VIEWS, ids=lambda v: v["id"])
def test_fixture_views_hold_no_formula_text(view):
    text = json.dumps(view, ensure_ascii=False)
    for formel in ("sin(phi)", "a*B", "s*(y-x)", "-c*vx", "-m*g", "log(B)"):
        assert formel not in text


if __name__ == "__main__":                                                   # einmal neu schreiben (CRLF wie im Repo)
    text = json.dumps(build(), ensure_ascii=False, indent=1) + "\n"
    FIXTURE.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    print(f"{FIXTURE} geschrieben")
