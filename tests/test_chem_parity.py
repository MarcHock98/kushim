"""Die Elementliste der Oberfläche (ui/src/lib/chem.ts) muss genau der des Schemas entsprechen.

Sonst nimmt das Backend ein Element an, das die Oberfläche nicht kennt (oder umgekehrt), und die
Ansicht zeigt „ungültig“ für gültige Daten. Der Test liest chem.ts nur als Text.
"""
from __future__ import annotations

import re
from pathlib import Path

from kushim.stage import schema

ROOT = Path(__file__).resolve().parents[1]
CHEM = ROOT / "ui" / "src" / "lib" / "chem.ts"
PHYSICS = ROOT / "ui" / "src" / "lib" / "physics.ts"


def _symbols_in_chem() -> list[str]:
    text = CHEM.read_text(encoding="utf-8")
    # Tabelle DATEN: Zeilen der Form ["H", "Wasserstoff", 0.31, 1.2]
    start = text.index("DATEN")
    end = text.index("export const ELEMENTE")
    return re.findall(r"""\[\s*"([A-Z][a-z]?)"\s*,\s*"[^"]+"\s*,""", text[start:end])


def test_chem_elements_match_the_schema_exactly():
    symbols = _symbols_in_chem()
    assert len(symbols) == 118
    assert tuple(symbols) == tuple(schema.ELEMENTE)


def test_chem_orbitals_match_the_schema():
    text = CHEM.read_text(encoding="utf-8")
    for name in ("1s", "2s", "2p_x", "2p_y", "2p_z", "3s", "3p_x", "3p_y", "3p_z",
                 "3d_xy", "3d_xz", "3d_yz", "3d_x2-y2", "3d_z2"):
        assert f'"{name}"' in text
