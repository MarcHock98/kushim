"""P7 Stufe 1: Formelsprache für `sim_eigen` (stage/formel.py, Plan docs/ui-p7-plan.md). Grammatik, Grenzen, Namen, RPN-Format,
Auswertung wie JavaScript, feste Testvektoren (dieselbe Datei nutzt die Oberfläche), Zufallstest."""
import json
import math
import random
import re
import time
from pathlib import Path

import pytest

from kushim.stage import formel, schema

VEKTOREN = json.loads((Path(__file__).parent / "fixtures" / "formel_vektoren.json").read_text(encoding="utf-8"))
ABC = ["a", "b", "c", "x", "y"]


def ok(text, namen=ABC):
    return formel.kompiliere(text, namen)


def err(text, namen=ABC):
    with pytest.raises(formel.FormelError) as e:
        formel.kompiliere(text, namen)
    return e.value.code


def bal(k, leaf="a"):
    """Summe aus k Blättern als ausgeglichener Baum (geringe Tiefe): 2k-1 Knoten."""
    if k == 1:
        return leaf
    h = k // 2
    return "(" + bal(h, leaf) + "+" + bal(k - h, leaf) + ")"


# --- Festes Format ------------------------------------------------------------------------------------------

def test_the_fixed_rpn_format_lists_exactly_the_agreed_opcodes_operators_and_functions():
    assert formel.OPCODES == ("c", "v", "o", "f")
    assert formel.OPERATOREN == ("+", "-", "*", "/", "^", "neg", "<", "<=", ">", ">=", "==", "!=")
    assert formel.FUNKTIONEN == {
        "sin": 1, "cos": 1, "tan": 1, "asin": 1, "acos": 1, "atan": 1, "sinh": 1, "cosh": 1, "tanh": 1, "exp": 1, "log": 1,
        "log10": 1, "sqrt": 1, "abs": 1, "sign": 1, "floor": 1, "ceil": 1, "atan2": 2, "min": 2, "max": 2, "hypot": 2, "mod": 2,
        "clamp": 3, "wenn": 3}
    assert formel.KONSTANTEN == {"pi": math.pi}
    assert (formel.MAX_ZEICHEN, formel.MAX_KNOTEN, formel.MAX_TIEFE, formel.MAX_ZAHL, formel.MAX_NAME) == (200, 64, 16, 1e12, 24)


def test_a_formula_compiles_to_rpn_and_tex_only():
    f = ok("-2^2 + pi*x")
    assert set(f) == {"rpn", "tex"}
    assert f["rpn"] == [["c", 2.0], ["c", 2.0], ["o", "^"], ["o", "neg"], ["c", math.pi], ["v", 3], ["o", "*"], ["o", "+"]]
    assert f["tex"] == r"-2^{2} + \pi \cdot x"
    assert all(isinstance(s, list) and len(s) == 2 and s[0] in formel.OPCODES for s in f["rpn"])


# --- Grammatik ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "1", "a", "pi", "1.5", "0.25e-3", "2E+5", "12e3", "-a", "+a", "--a", "-+-a", "a+b", "a-b", "a*b", "a/b", "a^b", "a^-b", "a*-b",
    "a<b", "a<=b", "a>b", "a>=b", "a==b", "a!=b", "(a<b)<c", "a < b + c", "sin(a)", "atan2(a, b)", "clamp(x, a, b)",
    "wenn(a > b, a, b)", "min(max(a, b), c)", "((a))", "  a  +  b  ", "x_1", "a_b_c", "sin(a)^2", "2^3^2", "-2^2", "a - -b",
    "hypot(x, y) / (1 + abs(a))", "mod(a, b)", "sign(a) * floor(b) + ceil(c)", "wenn(a, b, c) == 1", "log10(a) + log(b) + exp(c)",
    "1000000000000", "1e12", "a+b<c-a",
])
def test_grammar_accepts(text):
    names = ABC + ["x_1", "a_b_c"]
    assert formel.kompiliere(text, names)["rpn"]


@pytest.mark.parametrize("text,code", [
    ("", "leer"), ("   ", "leer"), ("a b", "erwartet_operator@2"), ("2x", "erwartet_operator@1"), ("a+", "unerwartetes_ende@2"),
    ("(a", "erwartet_klammer@2"), ("a)", "erwartet_operator@1"), ("()", "erwartet_wert@1"), ("sin()", "erwartet_wert@4"),
    ("a<b<c", "vergleich_verkettet@3"), ("a==b!=c", "vergleich_verkettet@4"), ("a=b", "zeichen@1"), ("!a", "zeichen@0"),
    ("a**b", "erwartet_wert@2"), (".5", "zeichen@0"), ("5.", "zeichen@1"), ("1.e3", "zeichen@1"), ("a,b", "erwartet_operator@1"),
    ("_a", "zeichen@0"), ("sin(a,)", "erwartet_wert@6"), ("f(a)", "unbekannte_funktion@0"), ("q", "unbekannter_name@0"),
    ("sin", "funktion_ohne_klammern@0"), ("a(1)", "unbekannte_funktion@0"), ("pi(1)", "unbekannte_funktion@0"),
    ("sin(a, b)", "stelligkeit@0"), ("atan2(a)", "stelligkeit@0"), ("clamp(a, b)", "stelligkeit@0"), ("wenn(a, b)", "stelligkeit@0"),
    ("min(a, b, c, x)", "stelligkeit@0"), ("1e999", "zahl@0"), ("a + 1e999", "zahl@4"), ("1000000000001", "zahl@0"),
    ("1.0000000001e12", "zahl@0"), ("a; b", "zeichen@1"), ("a & b", "zeichen@2"), ("a % b", "zeichen@2"), ("[a]", "zeichen@0"),
    ("a'", "zeichen@1"), ('"a"', "zeichen@0"), ("a\\b", "zeichen@1"), ("{a}", "zeichen@0"), ("a.b", "zeichen@1"),
    ("__import__", "zeichen@0"), ("eval(a)", "unbekannte_funktion@0"), ("a=>b", "zeichen@1"),
])
def test_grammar_rejects_with_a_fixed_code(text, code):
    assert err(text) == code


def test_number_with_a_four_digit_exponent_is_rejected():
    with pytest.raises(formel.FormelError):
        ok("1e1000")


def test_precedence_and_associativity():
    assert ok("2^3^2")["rpn"] == ok("2^(3^2)")["rpn"]                  # rechtsassoziativ
    assert ok("-2^2")["rpn"] == ok("-(2^2)")["rpn"]                    # unäres Minus vor Potenz: -4
    assert ok("a-b-c")["rpn"] == ok("(a-b)-c")["rpn"]
    assert ok("a/b*c")["rpn"] == ok("(a/b)*c")["rpn"]
    assert ok("-a*b")["rpn"] == ok("(-a)*b")["rpn"]
    assert ok("a+b<c")["rpn"] == ok("(a+b)<c")["rpn"]
    assert ok("a^-b^c")["rpn"] == ok("a^(-(b^c))")["rpn"]
    assert ok("+a")["rpn"] == [["v", 0]]                               # unäres Plus erzeugt keinen Knoten


# --- Grenzen je ±1 ------------------------------------------------------------------------------------------

def test_length_limit():
    assert ok("a" + " " * 199)["rpn"] == [["v", 0]]
    assert err("a" + " " * 200) == "zu_lang"


def test_node_limit():
    assert len(ok("-" + bal(32))["rpn"]) == 64
    assert err(bal(33)) == "zu_viele_knoten"


def test_depth_limit():
    assert ok("+".join(["a"] * 16))["rpn"]                             # Kette: Tiefe 16
    assert err("+".join(["a"] * 17)) == "zu_tief"
    assert ok("-" * 15 + "a")["rpn"]
    assert err("-" * 16 + "a") == "zu_tief"


def test_parser_depth_limit_counts_redundant_brackets():
    assert ok("(" * 39 + "a" + ")" * 39)["rpn"] == [["v", 0]]
    assert err("(" * 41 + "a" + ")" * 41).startswith("zu_tief@")


@pytest.mark.parametrize("deep", ["(" * 10_000 + "1" + ")" * 10_000, "-" * 10_000 + "1", "sin(" * 10_000 + "1" + ")" * 10_000,
                                  "1" + "^1" * 10_000, "+" * 10_000 + "1"], ids=["klammern", "minus", "funktion", "potenz", "plus"])
def test_ten_thousand_levels_are_rejected_fast_without_recursion_error(deep):
    t0 = time.perf_counter()
    with pytest.raises(formel.FormelError) as e:
        formel.lies(deep, limit=None)                                   # ohne Längengrenze: nur der Tiefenzähler schützt
    assert time.perf_counter() - t0 < 0.05
    assert e.value.code.startswith("zu_tief")


def test_ten_thousand_levels_in_a_view_are_a_view_error_fast():
    view = {"id": "t", "art": "simulation", "titel": "T", "bausteine": [{
        "typ": "sim_eigen", "name": "n", "form": "ode", "zustand": [{"name": "u", "start": 1}],
        "ableitungen": {"u": "(" * 10_000 + "u" + ")" * 10_000}, "darstellung": [{"form": "zeitreihe", "groessen": ["u"]}]}]}
    t0 = time.perf_counter()
    with pytest.raises(schema.ViewError) as e:
        schema.validate(view)
    assert time.perf_counter() - t0 < 0.05
    assert e.value.code == "bad_block_1" and e.value.detail == "ableitungen.0:zu_lang"


def test_number_limit():
    assert ok("1000000000000")["rpn"] == [["c", 1e12]] and ok("999999999999.9")["rpn"]
    assert err("1000000000000.1") == "zahl@0"


def test_name_length_limit():
    assert ok("a" * 24, ["a" * 24])["rpn"] == [["v", 0]]
    assert err("a" * 25, ["a" * 25]) == "name_zu_lang@0"
    assert formel.name_ok("a" * 24) and not formel.name_ok("a" * 25)


def test_argument_count_limit():
    assert ok("clamp(a, b, c)")["rpn"][-1] == ["f", "clamp"]
    assert err("clamp(a, b, c, x)") == "stelligkeit@0"


@pytest.mark.parametrize("name", ["sin", "pi", "wenn", "mod", "1a", "_a", "a-b", "", "a" * 25, "ä", "a b", None, 1, ["a"], "x" + chr(0)])
def test_reserved_or_malformed_names_are_not_names(name):
    assert not formel.name_ok(name)


# --- Zeichen: Unicode, Homoglyphen, Steuerzeichen -------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "a" + chr(0x0430),                     # kyrillisches a
    chr(0xff53) + "in(a)",                 # Vollbreite s
    "a" + chr(0x2212) + "b",               # mathematisches Minus
    "a" + chr(0xb7) + "b",                 # Mittelpunkt
    "a" + chr(0xd7) + "b",                 # Malzeichen
    chr(0x3c0),                            # griechisches pi
    "a" + chr(0xb2),                       # hochgestellte 2
    "a" + chr(0) + "b", "a" + chr(10) + "+b", "a" + chr(9) + "+b", "a" + chr(13), chr(27) + "[2J",
    "a" + chr(0x202e) + "b", "a" + chr(0x200b), "a" + chr(0xa0) + "+b", "a" + chr(0x2066), "a" + chr(0xfeff),
    chr(0x661),                            # arabisch-indische 1 (isdigit)
    "a" + chr(0x1d400),                    # mathematisches A
    "\ud800",
])
def test_non_ascii_homoglyphs_and_control_characters_are_rejected(text):
    assert err(text, ABC).startswith("zeichen@")


# --- Namen je Platz ---------------------------------------------------------------------------------------------

def test_names_resolve_to_their_env_index_and_unknown_names_are_rejected():
    env = ["t", "phi", "w", "g"]
    assert ok("g*phi + t", env)["rpn"] == [["v", 3], ["v", 1], ["o", "*"], ["v", 0], ["o", "+"]]
    assert err("G", env) == "unbekannter_name@0"                        # Groß und klein verschieden
    assert err("phi + omega", env) == "unbekannter_name@6"


def test_known_rpn_is_checked_again_on_the_second_pass():
    env = ["t", "u", "k"]
    f = ok("-k*u + sin(t)", env)
    assert formel.kompiliere(f, env) == f
    assert formel.kompiliere(json.loads(json.dumps(f)), env) == f


@pytest.mark.parametrize("change", [
    lambda f: {**f, "tex": f["tex"] + " "}, lambda f: {**f, "tex": "x"}, lambda f: {**f, "tex": None}, lambda f: {"rpn": f["rpn"]},
    lambda f: {**f, "extra": 1}, lambda f: {**f, "rpn": f["rpn"] + [["c", 1.0]]}, lambda f: {**f, "rpn": f["rpn"][:-1]},
    lambda f: {**f, "rpn": [["v", 3]]}, lambda f: {**f, "rpn": [["v", -1]]}, lambda f: {**f, "rpn": [["v", True]]},
    lambda f: {**f, "rpn": [["v", 1.0]]}, lambda f: {**f, "rpn": [["c", float("nan")]]}, lambda f: {**f, "rpn": [["c", float("inf")]]},
    lambda f: {**f, "rpn": [["c", -1.0]]}, lambda f: {**f, "rpn": [["c", -0.0]]}, lambda f: {**f, "rpn": [["c", 1e13]]},
    lambda f: {**f, "rpn": [["c", 10**400]]}, lambda f: {**f, "rpn": [["c", True]]}, lambda f: {**f, "rpn": [["c", "1"]]},
    lambda f: {**f, "rpn": [["o", "+"]]}, lambda f: {**f, "rpn": [["c", 1.0], ["o", "pow"]]}, lambda f: {**f, "rpn": [["c", 1.0], ["f", "eval"]]},
    lambda f: {**f, "rpn": [["c", 1.0], ["f", "atan2"]]}, lambda f: {**f, "rpn": [["x", 1]]}, lambda f: {**f, "rpn": [["c", 1.0, 2]]},
    lambda f: {**f, "rpn": [("c", 1.0)]}, lambda f: {**f, "rpn": []}, lambda f: {**f, "rpn": "c 1"}, lambda f: {**f, "rpn": [[["c"], 1]]},
    lambda f: {**f, "rpn": [["c", 1.0]] * 65}, lambda f: {**f, "rpn": [["o", ["+"]]]}, lambda f: {**f, "rpn": [["f", {"sin": 1}]]},
])
def test_tampered_rpn_or_tex_is_rejected(change):
    env = ["t", "u", "k"]
    with pytest.raises(formel.FormelError):
        formel.kompiliere(change(ok("-k*u + sin(t)", env)), env)


def test_rpn_deeper_than_sixteen_is_rejected_on_the_second_pass():
    env = ["u"]
    deep = [["v", 0]] + [["o", "neg"]] * 16
    with pytest.raises(formel.FormelError) as e:
        formel.aus_rpn(deep, 1)
    assert e.value.code == "zu_tief"
    assert formel.aus_rpn(deep[:-1], 1)


@pytest.mark.parametrize("value", [None, 1, 1.5, True, ["a"], {"x": 1}, b"a"])
def test_non_text_formulas_are_rejected(value):
    with pytest.raises(formel.FormelError):
        formel.kompiliere(value, ABC)


# --- Hilfsgrößen: nur frühere, also kein Zyklus -------------------------------------------------------------------

def _hilf_view(hilf, ableitung="h0"):
    return {"id": "h", "art": "simulation", "titel": "T", "bausteine": [{
        "typ": "sim_eigen", "name": "n", "form": "ode", "zustand": [{"name": "u", "start": 1}], "hilf": hilf,
        "ableitungen": {"u": ableitung}, "darstellung": [{"form": "zeitreihe", "groessen": ["u"]}]}]}


def test_helpers_may_use_earlier_helpers():
    got = schema.validate(_hilf_view([{"name": "h0", "formel": "2*u"}, {"name": "h1", "formel": "h0 + 1"}], "h1"))
    b = got["bausteine"][0]
    assert b["env"] == {"ode": ["t", "u", "h0", "h1"]} and b["hilf"][1]["formel"]["rpn"] == [["v", 2], ["c", 1.0], ["o", "+"]]


@pytest.mark.parametrize("hilf,detail", [
    ([{"name": "h0", "formel": "h0 + 1"}], "hilf.0.formel:unbekannter_name@0"),                               # sich selbst
    ([{"name": "h0", "formel": "h1"}, {"name": "h1", "formel": "u"}], "hilf.0.formel:unbekannter_name@0"),    # spätere
    ([{"name": "h0", "formel": "h1"}, {"name": "h1", "formel": "h0"}], "hilf.0.formel:unbekannter_name@0"),   # Zyklus
])
def test_helpers_cannot_form_a_cycle(hilf, detail):
    with pytest.raises(schema.ViewError) as e:
        schema.validate(_hilf_view(hilf))
    assert e.value.code == "bad_block_1" and e.value.detail == detail


# --- Kein Eingabetext in Fehlercodes --------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["qzxv + 1", "qzxv(1)", "1 + qzxv", "a qzxv", "qzxv" * 7, "sin(qzxv, 1)", "q" * 30])
def test_error_codes_never_contain_input_text(text):
    code = err(text)
    assert "qzxv" not in code and "qqq" not in code
    assert re.fullmatch(r"[a-z_]+(@[0-9]+)?", code), code


# --- Auswertung und Testvektoren --------------------------------------------------------------------------------

def _same(got, want):
    if isinstance(want, str):
        return {"nan": math.isnan(got), "inf": got == math.inf, "-inf": got == -math.inf}[want]
    return abs(got - want) <= 1e-12 * max(1.0, abs(want))


def test_vectors_file_has_at_least_sixty_entries_in_the_fixed_shape():
    assert len(VEKTOREN) >= 60
    for v in VEKTOREN:
        assert set(v) == {"name", "formel", "env_namen", "env", "rpn", "tex", "wert"}          # env: Werte, env_namen: Namen
        assert len(v["env_namen"]) == len(v["env"]) and v["name"] == v["formel"]
        assert isinstance(v["wert"], float) or v["wert"] in ("nan", "inf", "-inf")
    assert len({v["formel"] for v in VEKTOREN}) == len(VEKTOREN)


@pytest.mark.parametrize("v", VEKTOREN, ids=[v["formel"] for v in VEKTOREN])
def test_vectors_compile_to_the_same_rpn_and_tex_and_evaluate_to_the_same_value(v):
    f = formel.kompiliere(v["formel"], v["env_namen"])
    assert f == {"rpn": v["rpn"], "tex": v["tex"]}
    assert _same(formel.auswerten(f["rpn"], [float(x) for x in v["env"]]), v["wert"])
    assert formel.kompiliere(f, v["env_namen"]) == f                                    # zweite Prüfung: gleiche Form


def test_vectors_cover_every_function_operator_and_the_plan_examples():
    used = {(op, arg) for v in VEKTOREN for op, arg in v["rpn"] if op in ("o", "f")}
    assert {("o", o) for o in formel.OPERATOREN} <= used
    assert {("f", f) for f in formel.FUNKTIONEN} <= used
    texts = {v["formel"] for v in VEKTOREN}
    assert {"-2^2", "2^3^2", "mod(-7, 3)", "mod(7, -3)", "wenn(a>0, b, c)", "1/0", "0/0"} <= texts
    assert {"w", "-g/l*sin(phi) - d*w", "l*sin(phi)", "-l*cos(phi)", "0.5*(l*w)^2 + g*l*(1-cos(phi))"} <= texts     # Pendel
    assert {"a*B - b*B*R", "dd*B*R - c*R", "dd*B - c*log(B) + b*R - a*log(R)"} <= texts                          # Räuber-Beute
    assert {"s*(y-x)", "x*(r-z) - y", "x*y - bb*z"} <= texts                                                       # Lorenz
    assert {"-c*vx", "-m*g - c*vy"} <= texts                                                                       # Federkette


@pytest.mark.parametrize("text,want", [
    ("1/0", math.inf), ("-1/0", -math.inf), ("1/(-0)", -math.inf), ("(-0)^-1", -math.inf), ("0^-1", math.inf),
    ("10^400", math.inf), ("(-10)^401", -math.inf), ("exp(1000)", math.inf), ("log(0)", -math.inf), ("sinh(1000)", math.inf),
    ("-sinh(1000)", -math.inf), ("sinh(-1000)", -math.inf), ("cosh(-1000)", math.inf),
])
def test_division_by_zero_and_overflow_give_infinity_not_an_error(text, want):
    assert formel.auswerten(ok(text)["rpn"], [0.0] * 5) == want


@pytest.mark.parametrize("text", ["0/0", "sqrt(-1)", "log(-1)", "asin(2)", "acos(-2)", "sin(1/0)", "cos(1/0)", "tan(1/0)",
                                  "(-8)^(1/3)", "1^(0/0)", "(-1)^(1/0)", "min(0/0, 1)", "max(1, 0/0)", "mod(1, 0)", "log10(-1)"])
def test_undefined_results_are_nan_like_javascript(text):
    assert math.isnan(formel.auswerten(ok(text)["rpn"], [0.0] * 5))


def test_signed_zero_follows_javascript():
    ev = lambda t: formel.auswerten(ok(t)["rpn"], [0.0] * 5)
    assert math.copysign(1, ev("ceil(-0.5)")) == -1 and math.copysign(1, ev("min(0, -0)")) == -1
    assert math.copysign(1, ev("max(-0, 0)")) == 1 and math.copysign(1, ev("sign(-0)")) == -1 and math.copysign(1, ev("floor(-0)")) == -1


def test_wenn_evaluates_both_branches_and_treats_nan_as_true():
    ev = lambda t: formel.auswerten(ok(t)["rpn"], [0.0] * 5)
    assert ev("wenn(1, 2, 1/0)") == 2 and ev("wenn(0, 1/0, 3)") == 3 and ev("wenn(0/0, 4, 5)") == 4


# --- Zufallstest ------------------------------------------------------------------------------------------------

_BAUSTEINE = ["a", "b", "x", "y", "pi", "sin", "atan2", "clamp", "wenn", "mod", "q", "1", "0", "2.5", "1e3", "1e999", "(", ")", ",",
              "+", "-", "*", "/", "^", "<", "<=", ">", ">=", "==", "!=", "=", "!", " ", ".", "_", "e", "E", chr(0x3c0), chr(0),
              chr(0x202e), "sqrt", "log", "abs", "floor", "9" * 14, "a" * 25]


def _zufallsformel(rnd, tiefe=0):
    """Meist gültige Formel aus der Grammatik, damit der Zufallstest auch den Weg bis zur Auswertung trifft."""
    r = rnd.random()
    if tiefe > 4 or r < 0.3:
        return rnd.choice(["a", "b", "x", "y", "pi", "0", "1", "2.5", "1e3", "0.001"])
    if r < 0.45:
        return rnd.choice(["-", "+", ""]) + "(" + _zufallsformel(rnd, tiefe + 1) + ")"
    if r < 0.75:
        op = rnd.choice(["+", "-", "*", "/", "^", "<", "<=", ">", ">=", "==", "!="])
        return "(" + _zufallsformel(rnd, tiefe + 1) + op + _zufallsformel(rnd, tiefe + 1) + ")"
    name = rnd.choice(list(formel.FUNKTIONEN))
    n = formel.FUNKTIONEN[name] if rnd.random() < 0.9 else rnd.randint(1, 3)
    return name + "(" + ", ".join(_zufallsformel(rnd, tiefe + 1) for _ in range(n)) + ")"


def test_fuzz_two_thousand_random_formulas_never_crash():
    rnd = random.Random(7)
    accepted = 0
    for i in range(2000):
        if i % 2:
            text = "".join(rnd.choice(_BAUSTEINE) for _ in range(rnd.randint(0, 40)))
        else:
            text = _zufallsformel(rnd)
            if rnd.random() < 0.3:                                         # einzelne Zeichen kaputt machen
                k = rnd.randrange(len(text) + 1)
                text = text[:k] + rnd.choice(_BAUSTEINE) + text[k + 1:]
        try:
            f = formel.kompiliere(text, ABC)
        except formel.FormelError as e:
            assert re.fullmatch(r"[a-z_]+(@[0-9]+)?", e.code), e.code
            continue
        accepted += 1
        assert len(f["rpn"]) <= formel.MAX_KNOTEN and isinstance(f["tex"], str)
        assert isinstance(formel.auswerten(f["rpn"], [1.5, -2.0, 0.0, 3.0, -0.5]), float)
        assert formel.kompiliere(f, ABC) == f
    assert accepted > 50                                                  # der Test prüft auch gültige Formeln, nicht nur Fehler


def test_fuzz_random_rpn_never_crashes():
    rnd = random.Random(8)
    steps = [["c", 1.0], ["c", 0.0], ["c", -1.0], ["c", True], ["v", 0], ["v", 4], ["v", 5], ["o", "+"], ["o", "neg"], ["o", "^"],
             ["f", "sin"], ["f", "clamp"], ["f", "wenn"], ["x", 1], [1, 2], "c", None, ["c"], ["o", "**"]]
    for _ in range(2000):
        rpn = [rnd.choice(steps) for _ in range(rnd.randint(0, 12))]
        try:
            baum = formel.aus_rpn(rpn, 5)
        except formel.FormelError:
            continue
        assert baum
        assert isinstance(formel.auswerten(rpn, [1.0] * 5), float)
