"""Kleine Formelsprache für den Baustein `sim_eigen` (P7 Stufe 1, Plan docs/ui-p7-plan.md).

Claude schickt Formeltext. Er ist Eingabe von außen: Hier wird er in Zeichen zerlegt, mit einem Pratt-Parser (mit Tiefenzähler,
ohne `ast`, ohne `eval`, ohne Rekursion über eine feste Tiefe hinaus) gelesen, jeder Name gegen die feste Namensliste seines
Platzes geprüft und in eine feste Befehlsfolge (RPN) übersetzt. Die Oberfläche bekommt nur RPN und TeX, nie den Formeltext.
Fehler sind kurze feste Codes mit Stelle (`unbekannter_name@14`), nie mit Teilen der Eingabe. Nur Standardbibliothek.

Grammatik (nur ASCII):
    formel  := vergl
    vergl   := summe (("<"|"<="|">"|">="|"=="|"!=") summe)?       Ergebnis 1 oder 0, nicht verkettbar
    summe   := produkt (("+"|"-") produkt)*
    produkt := unaer (("*"|"/") unaer)*
    unaer   := ("-"|"+") unaer | potenz
    potenz  := atom ("^" unaer)?                                     rechtsassoziativ, -2^2 = -4
    atom    := zahl | name | name "(" formel ("," formel){0,2} ")" | "(" formel ")"
    zahl    := [0-9]+("."[0-9]+)?([eE][+-]?[0-9]{1,3})?               endlich, höchstens 1e12
    name    := [a-zA-Z][a-zA-Z0-9_]{0,23}

FESTES RPN-FORMAT (die Oberfläche, ui/src/lib/formel.ts, setzt genau dieses um):
    Eine Formel wird zu {"rpn": [[op, arg], ...], "tex": str}. Ausgewertet wird mit einem Stapel von links nach rechts:
    ["c", zahl]  legt die Konstante auf den Stapel (endlich, 0 bis 1e12; `pi` wird zur Zahl 3.141592653589793)
    ["v", i]     legt env[i] auf den Stapel (i ganz, 0 <= i < Länge von env)
    ["o", s]     s aus + - * / ^ < <= > >= == != (binär: nimmt b, dann a vom Stapel, legt a s b ab) oder neg (unär: -a).
                 Vergleiche ergeben 1.0 oder 0.0. ^ ist Math.pow.
    ["f", name]  feste Stelligkeit: sin cos tan asin acos atan sinh cosh tanh exp log log10 sqrt abs sign floor ceil je 1,
                 atan2 min max hypot mod je 2, clamp wenn je 3. Argumente in Schreibreihenfolge (das letzte liegt oben).
                 log ist der natürliche Logarithmus. mod(a,b) = a - b*floor(a/b). clamp(x,a,b) = min(max(x,a),b).
                 wenn(b,a,c): b != 0 ergibt a, sonst c (beide Zweige werden ausgewertet; NaN != 0, also a).
    Am Ende liegt genau ein Wert auf dem Stapel. Mathematik wie IEEE 754 und JavaScript `Math.*`: Division durch 0 ergibt
    ±Infinity oder NaN, das ist kein Fehler (die Laufzeit hält bei nicht endlichen Werten an).
    env je Platz (schreibt das Schema als Feld `env` in die geprüfte Ansicht):
    ODE: [t, zustand..., parameter..., hilf...] (Hilfsgrößen der Reihe nach ausgewertet und in env geschrieben);
    Teilchen-Kraft: [t, x, y, vx, vy, m, parameter...]; Paarkraft: [r, parameter...].
"""
from __future__ import annotations

import math
import re
from typing import Any

MAX_ZEICHEN, MAX_KNOTEN, MAX_TIEFE, MAX_ZAHL, MAX_NAME = 200, 64, 16, 1e12, 24
PARSE_TIEFE = 40                                         # Rekursion des Parsers (Klammern, Vorzeichen), weit unter Pythons Grenze
OPCODES = ("c", "v", "o", "f")
OPERATOREN = ("+", "-", "*", "/", "^", "neg", "<", "<=", ">", ">=", "==", "!=")
VERGLEICHE = ("<", "<=", ">", ">=", "==", "!=")
FUNKTIONEN: dict[str, int] = {
    "sin": 1, "cos": 1, "tan": 1, "asin": 1, "acos": 1, "atan": 1, "sinh": 1, "cosh": 1, "tanh": 1, "exp": 1, "log": 1,
    "log10": 1, "sqrt": 1, "abs": 1, "sign": 1, "floor": 1, "ceil": 1,
    "atan2": 2, "min": 2, "max": 2, "hypot": 2, "mod": 2,
    "clamp": 3, "wenn": 3,
}
KONSTANTEN = {"pi": math.pi}
RESERVIERT = frozenset(FUNKTIONEN) | frozenset(KONSTANTEN)
NAME = re.compile(r"[a-zA-Z][a-zA-Z0-9_]{0,23}")
_ZAHL = re.compile(r"[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]{1,3})?")
_NAME_ROH = re.compile(r"[a-zA-Z][a-zA-Z0-9_]*")
_OPS2 = ("<=", ">=", "==", "!=")
_OPS1 = ("+", "-", "*", "/", "^", "(", ")", ",", "<", ">")
_ERLAUBT = frozenset("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_.+-*/^(),<>=! ")
_BP = {"<": (1, 2), "<=": (1, 2), ">": (1, 2), ">=": (1, 2), "==": (1, 2), "!=": (1, 2),
       "+": (3, 4), "-": (3, 4), "*": (5, 6), "/": (5, 6), "^": (9, 7)}       # (links, rechts); ^ rechtsassoziativ
_BP_UNAER = 7                                                                 # bindet schwächer als ^, stärker als * und /
_INF, _NAN = float("inf"), float("nan")


class FormelError(ValueError):
    """Abgelehnt: `code` ist fest, höchstens mit einer Stelle (`zeichen@3`), nie mit Teilen der Eingabe."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def name_ok(v: Any) -> bool:
    """Ein Name für Zustand, Parameter oder Hilfsgröße: Form wie oben und keine Funktion oder Konstante."""
    return isinstance(v, str) and NAME.fullmatch(v) is not None and v not in RESERVIERT


# --- Zerlegen und Lesen -------------------------------------------------------------------------------------

def zerlege(text: str) -> list[tuple[str, Any, int]]:
    """Text -> Liste (art, wert, stelle); art ist "zahl", "name" oder "op". Nur die erlaubten ASCII-Zeichen."""
    out: list[tuple[str, Any, int]] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch not in _ERLAUBT:
            raise FormelError(f"zeichen@{i}")
        if ch == " ":
            i += 1
            continue
        if ch.isdigit():
            m = _ZAHL.match(text, i)
            assert m is not None
            wert = float(m.group())
            if not math.isfinite(wert) or wert > MAX_ZAHL:
                raise FormelError(f"zahl@{i}")
            out.append(("zahl", wert, i))
            i = m.end()
        elif ch.isalpha():
            m = _NAME_ROH.match(text, i)
            assert m is not None
            if len(m.group()) > MAX_NAME:
                raise FormelError(f"name_zu_lang@{i}")
            out.append(("name", m.group(), i))
            i = m.end()
        elif text.startswith(_OPS2, i):
            out.append(("op", text[i:i + 2], i))
            i += 2
        elif ch in _OPS1:
            out.append(("op", ch, i))
            i += 1
        else:                                                # "=", "!", "." oder "_" allein
            raise FormelError(f"zeichen@{i}")
    return out


class _Leser:
    """Pratt-Parser über die Zeichenliste. Baum: ("c", zahl) | ("n", name, stelle) | ("o", op, kinder) | ("ruf", name, args, stelle)."""

    def __init__(self, tokens: list[tuple[str, Any, int]], ende: int):
        self.t, self.i, self.ende = tokens, 0, ende

    def _peek(self) -> tuple[str, Any, int] | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def _stelle(self) -> int:
        tok = self._peek()
        return tok[2] if tok else self.ende

    def _ist(self, op: str) -> bool:
        tok = self._peek()
        return tok is not None and tok[0] == "op" and tok[1] == op

    def _erwarte(self, op: str) -> None:
        if not self._ist(op):
            raise FormelError(f"erwartet_{'klammer' if op == ')' else 'komma'}@{self._stelle()}")
        self.i += 1

    def ausdruck(self, min_bp: int, tiefe: int) -> tuple:
        if tiefe > PARSE_TIEFE:
            raise FormelError(f"zu_tief@{self._stelle()}")
        tok = self._peek()
        if tok is None:
            raise FormelError(f"unerwartetes_ende@{self.ende}")
        art, wert, stelle = tok
        self.i += 1
        if art == "zahl":
            links: tuple = ("c", wert)
        elif art == "name":
            if self._ist("("):
                self.i += 1
                args = [self.ausdruck(0, tiefe + 1)]
                while self._ist(","):
                    self.i += 1
                    if len(args) == 3:
                        raise FormelError(f"stelligkeit@{stelle}")
                    args.append(self.ausdruck(0, tiefe + 1))
                self._erwarte(")")
                links = ("ruf", wert, args, stelle)
            else:
                links = ("n", wert, stelle)
        elif wert == "(":
            links = self.ausdruck(0, tiefe + 1)
            self._erwarte(")")
        elif wert in ("-", "+"):
            innen = self.ausdruck(_BP_UNAER, tiefe + 1)
            links = ("o", "neg", [innen]) if wert == "-" else innen
        else:
            raise FormelError(f"erwartet_wert@{stelle}")
        vergleich = False
        while True:
            tok = self._peek()
            if tok is None or tok[0] != "op" or tok[1] not in _BP:
                break
            op = tok[1]
            lbp, rbp = _BP[op]
            if lbp < min_bp:
                break
            if op in VERGLEICHE:
                if vergleich:
                    raise FormelError(f"vergleich_verkettet@{tok[2]}")
                vergleich = True
            self.i += 1
            rechts = self.ausdruck(rbp, tiefe + 1)
            links = ("o", op, [links, rechts])
        return links


def lies(text: Any, limit: int | None = MAX_ZEICHEN) -> tuple:
    """Formeltext -> Baum mit offenen Namen. `limit=None` nur für Tests des Tiefenzählers."""
    if not isinstance(text, str):
        raise FormelError("kein_text")
    if limit is not None and len(text) > limit:
        raise FormelError("zu_lang")
    tokens = zerlege(text)
    if not tokens:
        raise FormelError("leer")
    leser = _Leser(tokens, len(text))
    baum = leser.ausdruck(0, 0)
    if leser.i != len(tokens):
        raise FormelError(f"erwartet_operator@{tokens[leser.i][2]}")
    return baum


def _aufloesen(baum: tuple, namen: list[str]) -> tuple:
    """Offene Namen und Funktionsaufrufe gegen die Namensliste des Platzes prüfen. Baum: ("c", x) | ("v", i) | ("o", op, k) | ("f", name, k)."""
    art = baum[0]
    if art == "c":
        return baum
    if art == "n":
        name, stelle = baum[1], baum[2]
        if name in KONSTANTEN:
            return ("c", KONSTANTEN[name])
        if name in namen:
            return ("v", namen.index(name))
        raise FormelError(f"{'funktion_ohne_klammern' if name in FUNKTIONEN else 'unbekannter_name'}@{stelle}")
    if art == "ruf":
        name, args, stelle = baum[1], baum[2], baum[3]
        if name not in FUNKTIONEN:
            raise FormelError(f"unbekannte_funktion@{stelle}")
        if len(args) != FUNKTIONEN[name]:
            raise FormelError(f"stelligkeit@{stelle}")
        return ("f", name, [_aufloesen(a, namen) for a in args])
    return ("o", baum[1], [_aufloesen(k, namen) for k in baum[2]])


# --- RPN ----------------------------------------------------------------------------------------------------

def _zu_rpn(baum: tuple, out: list[list[Any]]) -> None:
    if baum[0] in ("c", "v"):
        out.append([baum[0], baum[1]])
        return
    for k in baum[2]:
        _zu_rpn(k, out)
    out.append([baum[0], baum[1]])


def _stelligkeit(op: str, arg: Any) -> int:
    if op == "o":
        return 1 if arg == "neg" else 2
    if op == "f":
        return FUNKTIONEN[arg]
    return 0


def aus_rpn(rpn: Any, n_env: int) -> tuple:
    """Geprüfte Befehlsfolge -> Baum. Prüft Form, bekannte Befehle, Indizes, Stapel (kein Unterlauf, am Ende genau ein Wert),
    Knotenzahl und Tiefe. Fehler `rpn@k` (k: Stelle in der Folge) oder `zu_viele_knoten`, `zu_tief`."""
    if not isinstance(rpn, list) or not rpn:
        raise FormelError("rpn")
    if len(rpn) > MAX_KNOTEN:
        raise FormelError("zu_viele_knoten")
    stapel: list[tuple[tuple, int]] = []                       # (Baum, Tiefe)
    for k, schritt in enumerate(rpn):
        if not isinstance(schritt, list) or len(schritt) != 2 or not isinstance(schritt[0], str):
            raise FormelError(f"rpn@{k}")
        op, arg = schritt
        if op == "c":
            if isinstance(arg, bool) or not isinstance(arg, (int, float)):
                raise FormelError(f"rpn@{k}")
            try:
                x = float(arg)
            except OverflowError:
                raise FormelError(f"rpn@{k}") from None
            if not math.isfinite(x) or not 0 <= x <= MAX_ZAHL or math.copysign(1.0, x) < 0:
                raise FormelError(f"rpn@{k}")
            stapel.append((("c", x), 1))
        elif op == "v":
            if isinstance(arg, bool) or not isinstance(arg, int) or not 0 <= arg < n_env:
                raise FormelError(f"rpn@{k}")
            stapel.append((("v", arg), 1))
        elif (op == "o" and isinstance(arg, str) and arg in OPERATOREN) or (op == "f" and isinstance(arg, str) and arg in FUNKTIONEN):
            n = _stelligkeit(op, arg)
            if len(stapel) < n:
                raise FormelError(f"rpn@{k}")
            kinder = stapel[len(stapel) - n:]
            del stapel[len(stapel) - n:]
            tiefe = 1 + max(t for _, t in kinder)
            if tiefe > MAX_TIEFE:
                raise FormelError("zu_tief")
            stapel.append(((op, arg, [b for b, _ in kinder]), tiefe))
        else:
            raise FormelError(f"rpn@{k}")
    if len(stapel) != 1:
        raise FormelError(f"rpn@{len(rpn) - 1}")
    return stapel[0][0]


def _pruefe_baum(baum: tuple) -> list[list[Any]]:
    """Baum -> RPN, mit Grenzen für Knoten und Tiefe (die Tiefe des Parsers ist schon begrenzt)."""
    rpn: list[list[Any]] = []
    _zu_rpn(baum, rpn)
    if len(rpn) > MAX_KNOTEN:
        raise FormelError("zu_viele_knoten")
    tiefen: list[int] = []
    for op, arg in rpn:
        n = _stelligkeit(op, arg)
        t = 1 + max(tiefen[len(tiefen) - n:]) if n else 1
        del tiefen[len(tiefen) - n:]
        if t > MAX_TIEFE:
            raise FormelError("zu_tief")
        tiefen.append(t)
    return rpn


def kompiliere(eingabe: Any, namen: list[str]) -> dict[str, Any]:
    """Formeltext (von Claude) oder schon geprüfte Form {"rpn", "tex"} (zweite Prüfung) -> {"rpn", "tex"}.
    Bei der geprüften Form wird die RPN neu geprüft und das TeX neu erzeugt; es muss genau gleich sein."""
    if isinstance(eingabe, str):
        baum = _aufloesen(lies(eingabe), namen)
        rpn = _pruefe_baum(baum)
        return {"rpn": rpn, "tex": tex(baum, namen)}
    if isinstance(eingabe, dict):
        if set(eingabe) != {"rpn", "tex"}:
            raise FormelError("form")
        baum = aus_rpn(eingabe["rpn"], len(namen))
        rpn = _pruefe_baum(baum)
        out = tex(baum, namen)
        if eingabe["tex"] != out:
            raise FormelError("tex")
        return {"rpn": rpn, "tex": out}
    raise FormelError("kein_text")


def nutzt(rpn: list[list[Any]], indizes: set[int]) -> bool:
    """Liest die Formel einen dieser env-Plätze?"""
    return any(op == "v" and arg in indizes for op, arg in rpn)


def kosten(knoten: int, stufen: int, koerper: int) -> int:
    """Knotenauswertungen je Schritt: Knoten x Stufen (RK4: 4, sonst 1) x Körper oder Paare."""
    return knoten * stufen * koerper


# --- TeX ----------------------------------------------------------------------------------------------------

_GRIECHISCH = frozenset((
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa", "lambda", "mu", "nu", "xi", "rho",
    "sigma", "tau", "upsilon", "phi", "chi", "psi", "omega", "Gamma", "Delta", "Theta", "Lambda", "Xi", "Sigma", "Upsilon",
    "Phi", "Psi", "Omega", "varphi", "vartheta", "varepsilon"))
_TEX_F1 = {"sin": r"\sin", "cos": r"\cos", "tan": r"\tan", "asin": r"\arcsin", "acos": r"\arccos", "atan": r"\arctan",
           "sinh": r"\sinh", "cosh": r"\cosh", "tanh": r"\tanh", "exp": r"\exp", "log": r"\ln", "log10": r"\log_{10}",
           "sign": r"\operatorname{sign}"}
_TEX_F = {"atan2": r"\operatorname{atan2}", "min": r"\min", "max": r"\max", "hypot": r"\operatorname{hypot}",
          "mod": r"\operatorname{mod}", "clamp": r"\operatorname{clamp}", "wenn": r"\operatorname{wenn}"}
_TEX_VERGL = {"<": "<", "<=": r"\le", ">": ">", ">=": r"\ge", "==": "=", "!=": r"\ne"}
_RANG = {"<": 1, "<=": 1, ">": 1, ">=": 1, "==": 1, "!=": 1, "+": 2, "-": 2, "*": 3, "/": 6, "neg": 4, "^": 5}


def _tex_name(name: str) -> str:
    basis, _, rest = name.partition("_")
    if not basis:
        basis = name
    kopf = "\\" + basis if basis in _GRIECHISCH else (basis if len(basis) == 1 else r"\mathrm{" + basis + "}")
    return kopf + (r"_{\mathrm{" + rest.replace("_", r"\_") + "}}" if rest else "")


def _tex_zahl(x: float) -> str:
    if x == math.pi:
        return r"\pi"
    if x.is_integer() and x < 1e15:
        return str(int(x))
    s = repr(x)
    if "e" in s:
        mantisse, _, hoch = s.partition("e")
        return mantisse + r" \cdot 10^{" + str(int(hoch)) + "}"
    return s


def _rang(baum: tuple) -> int:
    if baum[0] == "o":
        return _RANG[baum[1]]
    if baum[0] == "c" and r"\cdot" in _tex_zahl(baum[1]):
        return 3
    return 7


def _klammer(s: str) -> str:
    return r"\left(" + s + r"\right)"


def tex(baum: tuple, namen: list[str]) -> str:
    """Baum -> KaTeX-TeX (nur zur Anzeige; die Oberfläche zeigt es mit trust:false)."""
    art = baum[0]
    if art == "c":
        return _tex_zahl(baum[1])
    if art == "v":
        return _tex_name(namen[baum[1]])
    k = baum[2]
    if art == "f":
        args = [tex(a, namen) for a in k]
        name = baum[1]
        if name == "sqrt":
            return r"\sqrt{" + args[0] + "}"
        if name == "abs":
            return r"\left|" + args[0] + r"\right|"
        if name == "floor":
            return r"\left\lfloor " + args[0] + r" \right\rfloor"
        if name == "ceil":
            return r"\left\lceil " + args[0] + r" \right\rceil"
        kopf = _TEX_F1.get(name) or _TEX_F[name]
        return kopf + _klammer(", ".join(args))
    op = baum[1]
    if op == "neg":
        innen = tex(k[0], namen)
        return "-" + (_klammer(innen) if _rang(k[0]) <= 4 else innen)
    a, b = tex(k[0], namen), tex(k[1], namen)
    ra, rb = _rang(k[0]), _rang(k[1])
    if op == "/":
        return r"\frac{" + a + "}{" + b + "}"
    if op == "^":
        return (a if ra >= 7 else _klammer(a)) + "^{" + b + "}"
    if op in _TEX_VERGL:
        return (a if ra > 1 else _klammer(a)) + " " + _TEX_VERGL[op] + " " + (b if rb > 1 else _klammer(b))
    if op in ("+", "-"):
        rechts_klammer = rb < 2 or rb == 4 or (op == "-" and rb == 2)
        return (a if ra >= 2 else _klammer(a)) + f" {op} " + (_klammer(b) if rechts_klammer else b)
    links_klammer, rechts_klammer = ra < 3, rb < 3 or rb == 4                  # "*"
    return (_klammer(a) if links_klammer else a) + r" \cdot " + (_klammer(b) if rechts_klammer else b)


# --- Auswertung (für die Probe im Schema und die Testvektoren; die Oberfläche rechnet selbst) ------------------

def _ungerade_ganz(y: float) -> bool:
    return math.isfinite(y) and y == math.floor(y) and abs(y) < 2.0 ** 53 and int(y) % 2 == 1


def _pow(x: float, y: float) -> float:
    """Wie JavaScript Math.pow (ECMAScript Number::exponentiate)."""
    if y != y:
        return _NAN
    if y == 0:
        return 1.0
    if x != x:
        return _NAN
    if abs(x) == 1 and math.isinf(y):
        return _NAN
    try:
        return math.pow(x, y)
    except OverflowError:
        return -_INF if x < 0 and _ungerade_ganz(y) else _INF
    except ValueError:
        if x == 0:                                           # 0 hoch negativ
            return math.copysign(_INF, x) if _ungerade_ganz(y) else _INF
        return _NAN                                          # negative Basis, nicht ganze Hochzahl


def _div(a: float, b: float) -> float:
    try:
        return a / b
    except ZeroDivisionError:
        if a != a or a == 0:
            return _NAN
        return math.copysign(_INF, a) * math.copysign(1.0, b)


def _floor(x: float) -> float:
    if x == 0 or not math.isfinite(x):
        return x
    return float(math.floor(x))


def _ceil(x: float) -> float:
    if x == 0 or not math.isfinite(x):
        return x
    r = float(math.ceil(x))
    return -0.0 if r == 0 else r                             # ceil(-0.5) = -0 wie in JavaScript


def _min(a: float, b: float) -> float:
    if a != a or b != b:
        return _NAN
    if a == b:
        return a if math.copysign(1.0, a) < 0 else b
    return a if a < b else b


def _max(a: float, b: float) -> float:
    if a != a or b != b:
        return _NAN
    if a == b:
        return b if math.copysign(1.0, a) < 0 else a
    return a if a > b else b


def _sicher(f: Any, ueberlauf: Any = None) -> Any:
    def g(x: float) -> float:
        try:
            return f(x)
        except OverflowError:
            return ueberlauf(x) if ueberlauf else _INF
        except ValueError:
            return _NAN
    return g


def _log(f: Any) -> Any:
    def g(x: float) -> float:
        if x != x or x < 0:
            return _NAN
        if x == 0:
            return -_INF
        return f(x)
    return g


def _sign(x: float) -> float:
    if x != x or x == 0:
        return x
    return 1.0 if x > 0 else -1.0


_F: dict[str, Any] = {
    "sin": _sicher(math.sin), "cos": _sicher(math.cos), "tan": _sicher(math.tan), "asin": _sicher(math.asin),
    "acos": _sicher(math.acos), "atan": math.atan, "sinh": _sicher(math.sinh, lambda x: math.copysign(_INF, x)),
    "cosh": _sicher(math.cosh), "tanh": math.tanh, "exp": _sicher(math.exp), "log": _log(math.log), "log10": _log(math.log10),
    "sqrt": lambda x: _NAN if x < 0 else math.sqrt(x), "abs": abs, "sign": _sign, "floor": _floor, "ceil": _ceil,
    "atan2": math.atan2, "min": _min, "max": _max, "hypot": math.hypot,
    "mod": lambda a, b: a - b * _floor(_div(a, b)),
    "clamp": lambda x, a, b: _min(_max(x, a), b),
    "wenn": lambda b, a, c: a if b != 0 else c,
}
_O: dict[str, Any] = {
    "+": lambda a, b: a + b, "-": lambda a, b: a - b, "*": lambda a, b: a * b, "/": _div, "^": _pow,
    "<": lambda a, b: 1.0 if a < b else 0.0, "<=": lambda a, b: 1.0 if a <= b else 0.0,
    ">": lambda a, b: 1.0 if a > b else 0.0, ">=": lambda a, b: 1.0 if a >= b else 0.0,
    "==": lambda a, b: 1.0 if a == b else 0.0, "!=": lambda a, b: 1.0 if a != b else 0.0,
}


def auswerten(rpn: list[list[Any]], env: list[float]) -> float:
    """Stapelmaschine über eine geprüfte RPN (aus `kompiliere`). Nicht endliche Ergebnisse sind erlaubt (IEEE)."""
    stapel: list[float] = []
    for op, arg in rpn:
        if op == "c":
            stapel.append(float(arg))
        elif op == "v":
            stapel.append(float(env[arg]))
        elif op == "o" and arg == "neg":
            stapel.append(-stapel.pop())
        else:
            n = 2 if op == "o" else FUNKTIONEN[arg]
            args = stapel[len(stapel) - n:]
            del stapel[len(stapel) - n:]
            stapel.append(float((_O[arg] if op == "o" else _F[arg])(*args)))
    return stapel[0]
