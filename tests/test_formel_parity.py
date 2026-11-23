"""P7 Stufe 1: Die Oberfläche (ui/src/lib/formel.ts) führt dieselben Befehle aus wie stage/formel.py. Gelesen wird die TS-Datei nur
als Text: Jeder Opcode, Operator und Funktionsname aus Python steht dort als Zeichenkette, und es gibt keine weiteren
Math-Funktionen. Die Werte selbst prüft die Oberfläche mit tests/fixtures/formel_vektoren.json."""
import re
from pathlib import Path

import pytest

from kushim.stage import formel

TS = Path(__file__).resolve().parents[1] / "ui" / "src" / "lib" / "formel.ts"
# Math-Funktionen, die es in JavaScript gibt, in der Formelsprache aber nicht (dürfen in formel.ts nicht als Name vorkommen)
FREMD = ("pow", "random", "exp2", "cbrt", "log2", "log1p", "expm1", "trunc", "round", "fround", "asinh", "acosh", "atanh",
         "imul", "clz32", "eval", "Function")


def _quoted() -> set[str]:
    if not TS.exists():
        pytest.skip("ui/src/lib/formel.ts gibt es noch nicht (baut die UI-Seite von P7 Stufe 1); dann prüft dieser Test die Listen")
    text = TS.read_text(encoding="utf-8")
    return set(re.findall(r"""["'`]([^"'`\n]{1,8})["'`]""", text))


def test_opcodes_and_operators_appear_in_formel_ts():
    quoted = _quoted()
    assert set(formel.OPCODES) <= quoted, set(formel.OPCODES) - quoted
    assert set(formel.OPERATOREN) <= quoted, set(formel.OPERATOREN) - quoted


def test_function_names_appear_in_formel_ts_and_no_others():
    quoted = _quoted()
    assert set(formel.FUNKTIONEN) <= quoted, set(formel.FUNKTIONEN) - quoted
    assert not set(FREMD) & quoted, set(FREMD) & quoted
