"""Prüfung einer Ansicht für die Bühne (Werkzeug `zeige`, Plan docs/ui-p2-plan.md).

Claude Code schickt eine Ansicht als JSON. Sie ist Eingabe von außen: Hier wird sie streng geprüft und auf eine feste Form
gebracht. Nur bekannte Felder und Bausteine, nur Text und endliche Zahlen, feste Grenzen. Was nicht passt, wird abgelehnt
(kurzer fester Code, nie Teile der Eingabe), nie halb übernommen. Dasselbe Modul prüft im Channel-Server und in der Bridge.
Nur Standardbibliothek.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any, Callable

MAX_JSON = 48 * 1024
ID = re.compile(r"[a-z0-9-]{1,40}")
ARTEN = ("antwort", "rechnung", "markt", "recherche")
MAX_BLOCKS = 12
RICHTUNG = ("auf", "ab", "gleich")


class ViewError(ValueError):
    """Abgelehnt: `code` ist kurz und fest (z. B. "bad_block_3"), damit nichts aus der Eingabe weitergereicht wird."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _text(v: Any, limit: int, code: str, optional: bool = False) -> str:
    if v is None and optional:
        return ""
    if not isinstance(v, str):
        raise ViewError(code)
    clean = " ".join("".join(c if c.isprintable() else " " for c in v).split())
    if not clean and not optional:
        raise ViewError(code)
    if len(clean) > limit:
        raise ViewError(code)
    return clean


def _num(v: Any, code: str) -> float | int:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ViewError(code)
    return v


def _list(v: Any, lo: int, hi: int, code: str) -> list[Any]:
    if not isinstance(v, list) or not lo <= len(v) <= hi:
        raise ViewError(code)
    return v


def _fields(b: dict[str, Any], allowed: set[str], code: str) -> None:
    if set(b) - allowed - {"typ"}:
        raise ViewError(code)


def _cell(v: Any, code: str) -> str | float | int:
    return _text(v, 200, code, optional=True) if isinstance(v, str) else _num(v, code)


def _text_block(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"absaetze"}, c)
    return {"absaetze": [_text(a, 1200, c) for a in _list(b.get("absaetze"), 1, 12, c)]}


def _liste(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"punkte", "nummeriert"}, c)
    nummeriert = b.get("nummeriert", False)
    if not isinstance(nummeriert, bool):
        raise ViewError(c)
    return {"punkte": [_text(p, 300, c) for p in _list(b.get("punkte"), 1, 30, c)], "nummeriert": nummeriert}


def _formel(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"tex"}, c)
    return {"tex": _text(b.get("tex"), 500, c)}


def _schritte(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"schritte"}, c)
    out = []
    for s in _list(b.get("schritte"), 1, 20, c):
        if not isinstance(s, dict) or set(s) - {"text", "tex"}:
            raise ViewError(c)
        out.append({"text": _text(s.get("text"), 400, c), "tex": _text(s.get("tex"), 500, c, optional=True)})
    return {"schritte": out}


def _ergebnis(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"text", "tex"}, c)
    text, tex = _text(b.get("text"), 300, c, optional=True), _text(b.get("tex"), 500, c, optional=True)
    if not text and not tex:
        raise ViewError(c)
    return {"text": text, "tex": tex}


def _kennzahlen(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"werte"}, c)
    out = []
    for k in _list(b.get("werte"), 1, 8, c):
        if not isinstance(k, dict) or set(k) - {"name", "wert", "einheit", "aenderung", "richtung"}:
            raise ViewError(c)
        richtung = k.get("richtung", "")
        if richtung not in ("", *RICHTUNG):
            raise ViewError(c)
        wert = k.get("wert")
        out.append({"name": _text(k.get("name"), 60, c),
                    "wert": _text(wert, 40, c) if isinstance(wert, str) else _num(wert, c),
                    "einheit": _text(k.get("einheit"), 20, c, optional=True),
                    "aenderung": _text(k.get("aenderung"), 30, c, optional=True), "richtung": richtung})
    return {"werte": out}


def _tabelle(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"spalten", "zeilen"}, c)
    spalten = [_text(s, 60, c) for s in _list(b.get("spalten"), 1, 8, c)]
    zeilen = []
    for z in _list(b.get("zeilen"), 1, 50, c):
        if not isinstance(z, list) or len(z) != len(spalten):
            raise ViewError(c)
        zeilen.append([_cell(v, c) for v in z])
    return {"spalten": spalten, "zeilen": zeilen}


def _diagramm(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"form", "x_titel", "y_titel", "reihen"}, c)
    if b.get("form") not in ("linie", "balken"):
        raise ViewError(c)
    reihen = []
    for r in _list(b.get("reihen"), 1, 4, c):
        if not isinstance(r, dict) or set(r) - {"name", "punkte"}:
            raise ViewError(c)
        punkte = []
        for p in _list(r.get("punkte"), 1, 500, c):
            if not isinstance(p, list) or len(p) != 2:
                raise ViewError(c)
            x = _text(p[0], 20, c) if isinstance(p[0], str) else _num(p[0], c)
            punkte.append([x, _num(p[1], c)])
        reihen.append({"name": _text(r.get("name"), 40, c), "punkte": punkte})
    return {"form": b["form"], "x_titel": _text(b.get("x_titel"), 40, c, optional=True),
            "y_titel": _text(b.get("y_titel"), 40, c, optional=True), "reihen": reihen}


def _aussagen(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"aussagen"}, c)
    out = []
    for a in _list(b.get("aussagen"), 1, 20, c):
        if not isinstance(a, dict) or set(a) - {"text", "quellen"}:
            raise ViewError(c)
        nrs = [int(_num(n, c)) for n in _list(a.get("quellen", []), 0, 10, c)]
        out.append({"text": _text(a.get("text"), 600, c), "quellen": nrs})
    return {"aussagen": out}


def _quellen(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"quellen"}, c)
    out, seen = [], set()
    for q in _list(b.get("quellen"), 1, 20, c):
        if not isinstance(q, dict) or set(q) - {"nr", "titel", "adresse"}:
            raise ViewError(c)
        nr = _num(q.get("nr"), c)
        if not float(nr).is_integer() or not 1 <= nr <= 99 or nr in seen:
            raise ViewError(c)
        seen.add(nr)
        out.append({"nr": int(nr), "titel": _text(q.get("titel"), 160, c), "adresse": _text(q.get("adresse"), 300, c, optional=True)})
    return {"quellen": out}


def _hinweis(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"text"}, c)
    return {"text": _text(b.get("text"), 400, c)}


def _systemzustand(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, set(), c)                                  # die Werte liefert kushim selbst (system.stats), nicht Claude
    return {}


BLOCKS: dict[str, Callable[[dict[str, Any], str], dict[str, Any]]] = {
    "text": _text_block, "liste": _liste, "formel": _formel, "schritte": _schritte, "ergebnis": _ergebnis,
    "kennzahlen": _kennzahlen, "tabelle": _tabelle, "diagramm": _diagramm, "aussagen": _aussagen,
    "widerspruch": _aussagen, "quellen": _quellen, "hinweis": _hinweis, "systemzustand": _systemzustand,
}


def validate(raw: Any) -> dict[str, Any]:
    """Gibt die geprüfte Ansicht zurück oder wirft ViewError. Eine Ansicht mit `schliessen: true` braucht nur die `id`."""
    if not isinstance(raw, dict):
        raise ViewError("bad_view")
    try:
        size = len(json.dumps(raw, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        raise ViewError("bad_view") from None
    if size > MAX_JSON:
        raise ViewError("too_large")
    if set(raw) - {"id", "art", "titel", "bausteine", "stand", "schliessen"}:
        raise ViewError("unknown_field")
    vid = raw.get("id")
    if not isinstance(vid, str) or not ID.fullmatch(vid):
        raise ViewError("bad_id")
    close = raw.get("schliessen", False)
    if not isinstance(close, bool):
        raise ViewError("bad_close")
    if close:
        return {"id": vid, "schliessen": True}
    art = raw.get("art")
    if art not in ARTEN:
        raise ViewError("bad_art")
    stand = _text(raw.get("stand"), 40, "bad_stand", optional=True)
    if art == "markt" and not stand:
        raise ViewError("missing_stand")
    blocks = []
    for i, b in enumerate(_list(raw.get("bausteine"), 1, MAX_BLOCKS, "bad_blocks")):
        code = f"bad_block_{i + 1}"
        if not isinstance(b, dict) or b.get("typ") not in BLOCKS:
            raise ViewError(code)
        blocks.append({"typ": b["typ"], **BLOCKS[b["typ"]](b, code)})
    nrs = {q["nr"] for b in blocks if b["typ"] == "quellen" for q in b["quellen"]}
    for i, b in enumerate(blocks):                         # Quellennummern müssen auf eine genannte Quelle zeigen
        if b["typ"] in ("aussagen", "widerspruch") and any(n not in nrs for a in b["aussagen"] for n in a["quellen"]):
            raise ViewError(f"bad_source_{i + 1}")
    return {"id": vid, "art": art, "titel": _text(raw.get("titel"), 120, "bad_title"), "stand": stand,
            "bausteine": blocks, "schliessen": False}
