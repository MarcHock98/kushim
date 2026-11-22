"""Prüfung einer Ansicht für die Bühne (Werkzeug `zeige`, Pläne docs/ui-p2-plan.md und docs/ui-p3-plan.md).

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
ARTEN = ("antwort", "rechnung", "markt", "recherche", "auftrag", "mail", "dokument", "modell", "plan", "lernen", "netz",
         "simulation", "teilchen")
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
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ViewError(code)
    try:
        finite = math.isfinite(v)
    except OverflowError:                                  # ganze Zahl, die keine endliche Kommazahl mehr ist (z. B. 10**400)
        finite = False
    if not finite:
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


ZUSTAND = ("offen", "laeuft", "fertig", "fehler")
MAIL_CHARS = 6000
ISO_TIME = re.compile("([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2})(?::([0-9]{2}))?(Z|[+-][0-9]{2}:[0-9]{2})?")


def _fortschritt(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"schritte", "hinweis"}, c)
    out = []
    for s in _list(b.get("schritte"), 1, 20, c):
        if not isinstance(s, dict) or set(s) - {"text", "zustand"} or s.get("zustand", "offen") not in ZUSTAND:
            raise ViewError(c)
        out.append({"text": _text(s.get("text"), 200, c), "zustand": s.get("zustand", "offen")})
    return {"schritte": out, "hinweis": _text(b.get("hinweis"), 300, c, optional=True)}


def _aufgaben(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"punkte"}, c)
    out = []
    for p in _list(b.get("punkte"), 1, 40, c):
        if not isinstance(p, dict) or set(p) - {"text", "erledigt"} or not isinstance(p.get("erledigt", False), bool):
            raise ViewError(c)
        out.append({"text": _text(p.get("text"), 200, c), "erledigt": p.get("erledigt", False)})
    return {"punkte": out}


def _clock(v: Any, c: str) -> str:
    """Uhrzeit `HH:MM` (00:00 bis 23:59), sonst abgelehnt."""
    if not isinstance(v, str) or len(v) != 5 or v[2] != ":" or not (v[:2] + v[3:]).isascii() or not (v[:2] + v[3:]).isdigit():
        raise ViewError(c)
    if int(v[:2]) > 23 or int(v[3:]) > 59:
        raise ViewError(c)
    return v


def _zeitplan(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"tag", "termine"}, c)
    out = []
    for t in _list(b.get("termine"), 1, 30, c):
        if not isinstance(t, dict) or set(t) - {"von", "bis", "titel", "ort"}:
            raise ViewError(c)
        von, bis = _clock(t.get("von"), c), _clock(t.get("bis"), c)
        if bis <= von:
            raise ViewError(c)
        out.append({"von": von, "bis": bis, "titel": _text(t.get("titel"), 120, c), "ort": _text(t.get("ort"), 80, c, optional=True)})
    return {"tag": _text(b.get("tag"), 40, c, optional=True), "termine": sorted(out, key=lambda t: (t["von"], t["bis"]))}


def _mail_text(b: dict[str, Any], c: str) -> list[str]:
    """Der Text einer Mail als Absätze (fremder Inhalt: nur druckbare Zeichen, je Absatz eine Zeile, insgesamt begrenzt)."""
    paras = [_text(a, 1500, c) for a in _list(b.get("absaetze"), 1, 40, c)]
    if sum(len(p) for p in paras) > MAIL_CHARS:
        raise ViewError(c)
    return paras


def _mail(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"von", "an", "betreff", "datum", "zusammenfassung", "absaetze"}, c)
    return {"von": _text(b.get("von"), 200, c), "an": _text(b.get("an"), 300, c, optional=True),
            "betreff": _text(b.get("betreff"), 200, c), "datum": _text(b.get("datum"), 40, c, optional=True),
            "zusammenfassung": _text(b.get("zusammenfassung"), 600, c, optional=True), "absaetze": _mail_text(b, c)}


def _mail_entwurf(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"an", "cc", "betreff", "absaetze"}, c)
    return {"an": _text(b.get("an"), 300, c), "cc": _text(b.get("cc"), 300, c, optional=True),
            "betreff": _text(b.get("betreff"), 200, c), "absaetze": _mail_text(b, c)}


def _countdown(b: dict[str, Any], c: str) -> dict[str, Any]:
    """Nur eine Anzeige (kushim hat keine Timer und klingelt nicht). Hier wird nur die Form der Endzeit geprüft
    (`JJJJ-MM-TTThh:mm[:ss]`, optional mit Zone; ohne Zone gilt die Ortszeit). Die Oberfläche zeigt nur Zeiten, die
    höchstens 24 Stunden entfernt sind, sonst „Zeit unbekannt“."""
    _fields(b, {"titel", "ende"}, c)
    raw = b.get("ende")
    m = ISO_TIME.fullmatch(raw) if isinstance(raw, str) else None
    if not m:
        raise ViewError(c)
    _, month, day, hour, minute, second = (int(g) if g else 0 for g in m.groups()[:6])
    if not (1 <= month <= 12 and 1 <= day <= 31 and hour <= 23 and minute <= 59 and second <= 59):
        raise ViewError(c)
    return {"titel": _text(b.get("titel"), 80, c), "ende": raw}


SECRET_SEGMENT = re.compile(
    r"(\.env.*|.*\.(pem|key|pfx|p12|kdbx|keystore|ppk)|id_(rsa|ed25519|ecdsa|dsa).*|credentials.*|.*(secret|password|passwd).*|tokens?(\.(txt|json|env|key|yaml|yml|toml))?|"
    r"\.netrc|\.npmrc|\.pypirc|channel\.json|api\.json|\.ssh|\.aws|\.gnupg)", re.I)
MAX_DOC_LINES = 400
LINE_CHARS = 400


def _file_name(v: Any, c: str) -> str:
    """Beschriftung einer Datei (nur Text, es wird nichts geöffnet). Namen, die nach Zugangsdaten aussehen, werden abgelehnt:
    ein Netz gegen Versehen, kein Beweis (den Inhalt durchsucht niemand nach Geheimnissen)."""
    name = _text(v, 200, c)
    parts = [p for p in re.split(r"[\\/]", name) if p]
    if any(SECRET_SEGMENT.fullmatch(p) for p in parts):
        raise ViewError(c)
    return name


def _code_line(v: Any, c: str) -> str:
    """Eine Zeile Dateitext: Einrückung bleibt (Tabs werden zu vier Leerzeichen), Steuer- und Richtungszeichen werden zu
    Leerzeichen, Leerzeilen sind erlaubt."""
    if not isinstance(v, str):
        raise ViewError(c)
    line = "".join(ch if ch.isprintable() else " " for ch in v.replace(chr(9), "    ")).rstrip()
    if len(line) > LINE_CHARS:
        raise ViewError(c)
    return line


def _dokument(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"name", "ausschnitt", "zeilen", "gliederung"}, c)
    lines = [_code_line(z, c) for z in _list(b.get("zeilen"), 1, MAX_DOC_LINES, c)]
    outline = [_text(g, 120, c) for g in _list(b.get("gliederung", []), 0, 30, c)]
    return {"name": _file_name(b.get("name"), c), "ausschnitt": _text(b.get("ausschnitt"), 80, c, optional=True),
            "zeilen": lines, "gliederung": outline}


ZEILEN_ART = ("gleich", "neu", "weg")


def _aenderung(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"name", "zusammenfassung", "bloecke"}, c)
    blocks, total = [], 0
    for blk in _list(b.get("bloecke"), 1, 20, c):
        if not isinstance(blk, dict) or set(blk) - {"kopf", "zeilen"}:
            raise ViewError(c)
        lines = []
        for z in _list(blk.get("zeilen"), 1, MAX_DOC_LINES, c):
            if not isinstance(z, dict) or set(z) - {"art", "text"} or z.get("art") not in ZEILEN_ART:
                raise ViewError(c)
            lines.append({"art": z["art"], "text": _code_line(z.get("text", ""), c)})
        total += len(lines)
        if total > MAX_DOC_LINES:
            raise ViewError(c)
        blocks.append({"kopf": _text(blk.get("kopf"), 120, c, optional=True), "zeilen": lines})
    return {"name": _file_name(b.get("name"), c), "zusammenfassung": _text(b.get("zusammenfassung"), 400, c, optional=True),
            "bloecke": blocks}


PALETTE = ("arc", "amber", "ok", "warn", "alarm", "text", "gedaempft")
FORMEN = {"box": 3, "kugel": 1, "zylinder": 2, "kegel": 2, "torus": 2, "ebene": 2}      # Zahl der Maße je Körper
COORD_MAX = 1_000_000
MAX_SCENES, MAX_OBJECTS, MAX_OBJECTS_TOTAL = 3, 150, 300
MAX_PLAN_ELEMENTS, MAX_LAYERS = 800, 10


def _coord(v: Any, c: str, positive: bool = False) -> float | int:
    n = _num(v, c)
    if abs(n) > COORD_MAX or (positive and n <= 0):
        raise ViewError(c)
    return n


def _point(v: Any, dims: int, c: str) -> list[float | int]:
    return [_coord(x, c) for x in _list(v, dims, dims, c)]


def _farbe(v: Any, c: str) -> str:
    if v not in PALETTE:
        raise ViewError(c)
    return v


def _object3d(o: Any, c: str) -> dict[str, Any]:
    if not isinstance(o, dict):
        raise ViewError(c)
    form = o.get("form")
    if not isinstance(form, str):
        raise ViewError(c)
    if form == "linie":
        _fields(o, {"form", "name", "punkte", "farbe"}, c)
        extra: dict[str, Any] = {"punkte": [_point(p, 3, c) for p in _list(o.get("punkte"), 2, 50, c)]}
    elif form in FORMEN:
        _fields(o, {"form", "name", "masse", "position", "drehung", "farbe"}, c)
        n = FORMEN[form]
        extra = {"masse": [_coord(x, c, positive=True) for x in _list(o.get("masse"), n, n, c)],
                 "position": _point(o.get("position", [0, 0, 0]), 3, c), "drehung": _point(o.get("drehung", [0, 0, 0]), 3, c)}
    else:
        raise ViewError(c)
    return {"form": form, "name": _text(o.get("name"), 40, c, optional=True), "farbe": _farbe(o.get("farbe", "arc"), c), **extra}


def _szene3d(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"einheit", "szenen", "hervorheben", "beschriftungen"}, c)
    scenes, total, names = [], 0, set()
    for sz in _list(b.get("szenen"), 1, MAX_SCENES, c):
        if not isinstance(sz, dict) or set(sz) - {"name", "objekte"}:
            raise ViewError(c)
        objs = [_object3d(o, c) for o in _list(sz.get("objekte"), 1, MAX_OBJECTS, c)]
        own = [o["name"] for o in objs if o["name"]]
        if len(own) != len(set(own)):                    # Namen sind die Schlüssel für Hervorheben und Vergleich
            raise ViewError(c)
        names.update(own)
        total += len(objs)
        scenes.append({"name": _text(sz.get("name"), 40, c), "objekte": objs})
    if total > MAX_OBJECTS_TOTAL:
        raise ViewError(c)
    highlight = [_text(n, 40, c) for n in _list(b.get("hervorheben", []), 0, 20, c)]
    labels = []
    for lb in _list(b.get("beschriftungen", []), 0, 20, c):
        if not isinstance(lb, dict) or set(lb) - {"objekt", "text"}:
            raise ViewError(c)
        labels.append({"objekt": _text(lb.get("objekt"), 40, c), "text": _text(lb.get("text"), 60, c)})
    if any(n not in names for n in highlight) or any(lb["objekt"] not in names for lb in labels):
        raise ViewError(c)
    return {"einheit": _text(b.get("einheit"), 8, c, optional=True), "szenen": scenes, "hervorheben": highlight,
            "beschriftungen": labels}


def _plan_element(e: Any, layers: set[str], c: str) -> dict[str, Any]:
    if not isinstance(e, dict):
        raise ViewError(c)
    art = e.get("art")
    ebene = _text(e.get("ebene"), 30, c, optional=True)
    if ebene and ebene not in layers:
        raise ViewError(c)
    if art == "linie" or art == "mass":
        _fields(e, {"art", "ebene", "von", "bis"} | ({"text"} if art == "mass" else set()), c)
        out = {"von": _point(e.get("von"), 2, c), "bis": _point(e.get("bis"), 2, c)}
        if art == "mass":
            out["text"] = _text(e.get("text"), 40, c, optional=True)
    elif art == "polylinie":
        _fields(e, {"art", "ebene", "punkte", "geschlossen"}, c)
        closed = e.get("geschlossen", False)
        if not isinstance(closed, bool):
            raise ViewError(c)
        out = {"punkte": [_point(p, 2, c) for p in _list(e.get("punkte"), 2, 200, c)], "geschlossen": closed}
    elif art == "rechteck":
        _fields(e, {"art", "ebene", "x", "y", "b", "h"}, c)
        out = {"x": _coord(e.get("x"), c), "y": _coord(e.get("y"), c), "b": _coord(e.get("b"), c, True), "h": _coord(e.get("h"), c, True)}
    elif art == "kreis":
        _fields(e, {"art", "ebene", "x", "y", "r"}, c)
        out = {"x": _coord(e.get("x"), c), "y": _coord(e.get("y"), c), "r": _coord(e.get("r"), c, True)}
    elif art == "bogen":
        _fields(e, {"art", "ebene", "x", "y", "r", "von", "bis"}, c)
        out = {"x": _coord(e.get("x"), c), "y": _coord(e.get("y"), c), "r": _coord(e.get("r"), c, True),
               "von": _coord(e.get("von"), c), "bis": _coord(e.get("bis"), c)}
        if abs(out["von"]) > 3600 or abs(out["bis"]) > 3600:
            raise ViewError(c)
    elif art == "text":
        _fields(e, {"art", "ebene", "x", "y", "text", "groesse"}, c)
        size = e.get("groesse", 0)
        out = {"x": _coord(e.get("x"), c), "y": _coord(e.get("y"), c), "text": _text(e.get("text"), 80, c),
               "groesse": 0 if size == 0 else _coord(size, c, True)}
    else:
        raise ViewError(c)
    return {"art": art, "ebene": ebene, **out}


def _plan2d(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"einheit", "ebenen", "elemente"}, c)
    layers = [_text(n, 30, c) for n in _list(b.get("ebenen", []), 0, MAX_LAYERS, c)]
    if len(layers) != len(set(layers)):
        raise ViewError(c)
    elems = [_plan_element(e, set(layers), c) for e in _list(b.get("elemente"), 1, MAX_PLAN_ELEMENTS, c)]
    return {"einheit": _text(b.get("einheit"), 8, c, optional=True), "ebenen": layers, "elemente": elems}


# --- P6: Vergleich, Zeitstrahl, Gegenüberstellung, Lernen, Netz (docs/ui-p6-plan.md) ---------------------

NETZ_FORM = ("ablauf", "baum", "mindmap")
KNOTEN_ART = ("start", "ende", "entscheidung", "schritt")
NODE_ID = re.compile(r"[a-z0-9_-]{1,24}")


def _int(v: Any, lo: int, hi: int, code: str) -> int:
    """Eine ganze Zahl (kein bool, keine Kommazahl) zwischen lo und hi."""
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ViewError(code)
    return v


def _item(v: Any, allowed: set[str], c: str) -> dict[str, Any]:
    if not isinstance(v, dict) or set(v) - allowed:
        raise ViewError(c)
    return v


def _vergleich(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"optionen", "kriterien", "vorteile", "nachteile", "fazit"}, c)
    optionen = [_text(o, 80, c) for o in _list(b.get("optionen"), 2, 5, c)]
    n = len(optionen)
    kriterien = []
    for k in _list(b.get("kriterien"), 1, 15, c):
        k = _item(k, {"name", "werte"}, c)
        kriterien.append({"name": _text(k.get("name"), 80, c), "werte": [_cell(w, c) for w in _list(k.get("werte"), n, n, c)]})

    def per_option(key: str) -> list[list[str]]:              # je Option eine Liste, parallel zu `optionen`
        raw = b.get(key)
        if raw is None:
            return [[] for _ in optionen]
        return [[_text(p, 200, c) for p in _list(lst, 0, 6, c)] for lst in _list(raw, n, n, c)]

    return {"optionen": optionen, "kriterien": kriterien, "vorteile": per_option("vorteile"),
            "nachteile": per_option("nachteile"), "fazit": _text(b.get("fazit"), 400, c, optional=True)}


def _zeitstrahl(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"ereignisse", "einheit"}, c)
    out = []
    for e in _list(b.get("ereignisse"), 1, 40, c):            # Reihenfolge bleibt, wie Claude sie schickt
        e = _item(e, {"zeit", "titel", "text"}, c)
        out.append({"zeit": _text(e.get("zeit"), 40, c), "titel": _text(e.get("titel"), 120, c),
                    "text": _text(e.get("text"), 400, c, optional=True)})
    return {"ereignisse": out, "einheit": _text(b.get("einheit"), 40, c, optional=True)}


def _gegenueber(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"sprachen", "paare"}, c)
    sprachen = [_text(s, 20, c) for s in _list(b.get("sprachen"), 2, 2, c)]
    paare = []
    for p in _list(b.get("paare"), 1, 40, c):
        p = _item(p, {"original", "uebersetzung"}, c)
        paare.append({"original": _text(p.get("original"), 600, c), "uebersetzung": _text(p.get("uebersetzung"), 600, c)})
    return {"sprachen": sprachen, "paare": paare}


def _lernkarten(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"karten"}, c)
    out = []
    for k in _list(b.get("karten"), 1, 30, c):
        k = _item(k, {"frage", "antwort"}, c)
        out.append({"frage": _text(k.get("frage"), 400, c), "antwort": _text(k.get("antwort"), 400, c)})
    return {"karten": out}


def _quiz(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"fragen"}, c)
    out = []
    for f in _list(b.get("fragen"), 1, 20, c):
        f = _item(f, {"frage", "optionen", "richtig", "erklaerung"}, c)
        optionen = [_text(o, 200, c) for o in _list(f.get("optionen"), 2, 5, c)]
        out.append({"frage": _text(f.get("frage"), 300, c), "optionen": optionen,
                    "richtig": _int(f.get("richtig"), 0, len(optionen) - 1, c),      # Index ab 0
                    "erklaerung": _text(f.get("erklaerung"), 400, c, optional=True)})
    return {"fragen": out}


def _anleitung(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"schritte", "aktuell"}, c)
    out = []
    for s in _list(b.get("schritte"), 1, 30, c):
        s = _item(s, {"titel", "text", "sekunden"}, c)
        out.append({"titel": _text(s.get("titel"), 120, c), "text": _text(s.get("text"), 600, c),
                    "sekunden": _int(s.get("sekunden", 0), 0, 86400, c)})    # 0: kein Timer (nur Anzeige, ohne Ton)
    return {"schritte": out, "aktuell": _int(b.get("aktuell", 0), 0, len(out) - 1, c)}    # Index ab 0


def _netz(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"form", "knoten", "kanten"}, c)
    form = b.get("form")
    if form not in NETZ_FORM:
        raise ViewError(c)
    knoten, ids = [], set()
    for k in _list(b.get("knoten"), 1, 60, c):
        k = _item(k, {"id", "text", "art"}, c)
        kid, art = k.get("id"), k.get("art", "")
        if not isinstance(kid, str) or not NODE_ID.fullmatch(kid) or kid in ids or art not in ("", *KNOTEN_ART):
            raise ViewError(c)
        ids.add(kid)
        knoten.append({"id": kid, "text": _text(k.get("text"), 80, c), "art": art})
    kanten = []
    for e in _list(b.get("kanten", []), 0, 120, c):
        e = _item(e, {"von", "bis", "text"}, c)
        von, bis = e.get("von"), e.get("bis")
        if not isinstance(von, str) or not isinstance(bis, str) or von not in ids or bis not in ids or von == bis:   # keine Kante ins Leere, keine Schleife auf sich selbst
            raise ViewError(c)
        kanten.append({"von": von, "bis": bis, "text": _text(e.get("text"), 40, c, optional=True)})
    if form in ("baum", "mindmap"):                           # genau eine Wurzel (bei der Mindmap die Mitte), sonst je eine Kante hinein
        incoming = {i: 0 for i in ids}
        children: dict[str, list[str]] = {i: [] for i in ids}
        for e in kanten:
            incoming[e["bis"]] += 1
            children[e["von"]].append(e["bis"])
        roots = [i for i, n in incoming.items() if n == 0]
        if len(roots) != 1 or any(n > 1 for n in incoming.values()):
            raise ViewError(c)
        seen, todo = set(), [roots[0]]                       # alle von der Wurzel erreichbar: dann gibt es keinen Kreis
        while todo:
            node = todo.pop()
            seen.add(node)
            todo.extend(children[node])
        if seen != ids:
            raise ViewError(c)
    return {"form": form, "knoten": knoten, "kanten": kanten}


# --- P5a: Simulation mit festen Modellen (docs/ui-p5-plan.md) ---------------------------------------------
# Claude schickt nur den Namen eines eingebauten Modells und Zahlen, nie Formeln oder Code. Die Einheiten sind fest
# (SI; bei umlauf AE und Sonnenmassen; bei gas Kastenbreiten je Sekunde). Fehlende Felder mit Standard werden ergänzt,
# damit die Oberfläche immer jedes Feld bekommt.

SIM_MODELLE = ("pendel", "feder", "wurf", "umlauf", "gas", "doppelpendel", "welle")
SIM_ZAHLEN: dict[str, dict[str, tuple[float, float, float | None]]] = {      # Feld: (von, bis, Standard; None = Pflicht)
    "pendel": {"laenge": (0.05, 100, None), "winkel": (-170, 170, None), "anfangsgeschwindigkeit": (-720, 720, 0),
               "daempfung": (0, 5, 0), "g": (0.1, 100, 9.81)},
    "feder": {"masse": (0.001, 1000, None), "federkonstante": (0.001, 1_000_000, None), "auslenkung": (-10, 10, None),
              "daempfung": (0, 10_000, 0)},
    "wurf": {"geschwindigkeit": (0.1, 1000, None), "winkel": (-90, 90, None), "hoehe": (0, 10_000, 0), "g": (0.1, 100, 9.81),
             "luftwiderstand": (0, 1, 0)},
    "umlauf": {"zentralmasse": (0.01, 100, None)},
    "doppelpendel": {"laenge1": (0.05, 100, None), "laenge2": (0.05, 100, None), "masse1": (0.01, 1000, 1), "masse2": (0.01, 1000, 1),
                     "winkel1": (-180, 180, None), "winkel2": (-180, 180, None), "g": (0.1, 100, 9.81), "daempfung": (0, 5, 0)},
}
SIM_KOERPER = {"abstand": (0.01, 1000, None), "exzentrizitaet": (0, 0.95, 0), "phase": (0, 360, 0), "masse": (0, 0.01, 0)}
SIM_WELLE = {"amplitude": (0.001, 100, None), "wellenlaenge": (0.01, 1000, None), "frequenz": (0.01, 100, None), "phase": (0, 360, 0)}
WELLE_RICHTUNG = ("rechts", "links")
MAX_SIM_KOERPER, MAX_TEILCHEN, MAX_STARTWERT, MAX_WELLEN = 8, 300, 2_147_483_647, 3


def _bounded(v: Any, lo: float, hi: float, c: str) -> float | int:
    n = _num(v, c)
    if not lo <= n <= hi:
        raise ViewError(c)
    return n


def _zahlen(p: dict[str, Any], spec: dict[str, tuple[float, float, float | None]], c: str) -> dict[str, Any]:
    """Die Zahlenfelder nach `spec`, in dieser Reihenfolge; ein fehlendes Pflichtfeld ist None und wird abgelehnt."""
    return {k: _bounded(p.get(k, std), lo, hi, c) for k, (lo, hi, std) in spec.items()}


def _sim_pendel(p: dict[str, Any], c: str) -> dict[str, Any]:
    _item(p, set(SIM_ZAHLEN["pendel"]), c)
    return _zahlen(p, SIM_ZAHLEN["pendel"], c)


def _sim_feder(p: dict[str, Any], c: str) -> dict[str, Any]:
    _item(p, set(SIM_ZAHLEN["feder"]), c)
    out = _zahlen(p, SIM_ZAHLEN["feder"], c)
    if not 0.05 <= 2 * math.pi * math.sqrt(out["masse"] / out["federkonstante"]) <= 1000:     # Schwingungsdauer in s
        raise ViewError(c)
    return out


def _sim_wurf(p: dict[str, Any], c: str) -> dict[str, Any]:
    _item(p, set(SIM_ZAHLEN["wurf"]), c)
    out = _zahlen(p, SIM_ZAHLEN["wurf"], c)
    if out["hoehe"] == 0 and out["winkel"] <= 0:                                          # vom Boden aus: sonst kein Flug
        raise ViewError(c)
    return out


def _sim_umlauf(p: dict[str, Any], c: str) -> dict[str, Any]:
    _item(p, {"zentralmasse", "koerper", "anziehung"}, c)
    anziehung = p.get("anziehung", False)                                                # P5b: gegenseitige Anziehung der Körper
    if not isinstance(anziehung, bool):
        raise ViewError(c)
    koerper, names = [], set()
    for k in _list(p.get("koerper"), 1, MAX_SIM_KOERPER, c):
        k = _item(k, {"name", "abstand", "exzentrizitaet", "phase", "masse", "farbe"}, c)
        name = _text(k.get("name"), 30, c)
        if name in names:
            raise ViewError(c)
        names.add(name)
        koerper.append({"name": name, **_zahlen(k, SIM_KOERPER, c), "farbe": _farbe(k.get("farbe", "arc"), c)})
    abstand = [k["abstand"] for k in koerper]
    if max(abstand) / min(abstand) > 100:
        raise ViewError(c)
    return {**_zahlen(p, SIM_ZAHLEN["umlauf"], c), "koerper": koerper, "anziehung": anziehung}


def _sim_gas(p: dict[str, Any], c: str) -> dict[str, Any]:
    _item(p, {"anzahl", "kasten", "radius", "geschwindigkeit", "schwerkraft", "stoesse", "startwert"}, c)
    anzahl = _int(p.get("anzahl"), 2, MAX_TEILCHEN, c)
    kasten = [_bounded(x, 1, 1000, c) for x in _list(p.get("kasten"), 2, 2, c)]
    if max(kasten) / min(kasten) > 10:
        raise ViewError(c)
    radius = _num(p.get("radius"), c)
    if not 0 < radius <= 0.05 * min(kasten) or anzahl * math.pi * radius ** 2 > 0.3 * kasten[0] * kasten[1]:
        raise ViewError(c)
    speed = _num(p.get("geschwindigkeit"), c)
    if not 0 < speed <= 10:
        raise ViewError(c)
    stoesse = p.get("stoesse", True)
    if not isinstance(stoesse, bool):
        raise ViewError(c)
    return {"anzahl": anzahl, "kasten": kasten, "radius": radius, "geschwindigkeit": speed,
            "schwerkraft": _bounded(p.get("schwerkraft", 0), 0, 100, c), "stoesse": stoesse,
            "startwert": _int(p.get("startwert", 1), 0, MAX_STARTWERT, c)}


def _sim_doppelpendel(p: dict[str, Any], c: str) -> dict[str, Any]:
    _item(p, set(SIM_ZAHLEN["doppelpendel"]), c)
    return _zahlen(p, SIM_ZAHLEN["doppelpendel"], c)


def _sim_welle(p: dict[str, Any], c: str) -> dict[str, Any]:
    _item(p, {"wellen", "bereich"}, c)
    wellen = []
    for w in _list(p.get("wellen"), 1, MAX_WELLEN, c):
        w = _item(w, {*SIM_WELLE, "richtung"}, c)
        richtung = w.get("richtung", "rechts")
        if not isinstance(richtung, str) or richtung not in WELLE_RICHTUNG:
            raise ViewError(c)
        wellen.append({**_zahlen(w, SIM_WELLE, c), "richtung": richtung})
    bereich = _num(p.get("bereich", 0), c)                                               # 0: die Oberfläche wählt den Ausschnitt
    if bereich != 0 and not 0.01 <= bereich <= 10_000:
        raise ViewError(c)
    return {"wellen": wellen, "bereich": bereich}


SIM_PARAMETER: dict[str, Callable[[dict[str, Any], str], dict[str, Any]]] = {
    "pendel": _sim_pendel, "feder": _sim_feder, "wurf": _sim_wurf, "umlauf": _sim_umlauf, "gas": _sim_gas,
    "doppelpendel": _sim_doppelpendel, "welle": _sim_welle,
}


def _simulation(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"modell", "parameter", "laufzeit", "tempo", "spur", "beschreibung"}, c)
    modell, p = b.get("modell"), b.get("parameter")
    if not isinstance(modell, str) or modell not in SIM_PARAMETER or not isinstance(p, dict):
        raise ViewError(c)
    tempo = _num(b.get("tempo", 0), c)                                                    # 0: die Oberfläche wählt das Tempo
    if tempo != 0 and not 0.1 <= tempo <= 100:
        raise ViewError(c)
    spur = b.get("spur", True)
    if not isinstance(spur, bool):
        raise ViewError(c)
    return {"modell": modell, "parameter": SIM_PARAMETER[modell](p, c), "laufzeit": _bounded(b.get("laufzeit", 30), 5, 60, c),
            "tempo": tempo, "spur": spur, "beschreibung": _text(b.get("beschreibung"), 400, c, optional=True)}


# --- P5b: Teilchen (Molekül, Atom im Schalenmodell, Orbital; docs/ui-p5-plan.md Abschnitt 7) -----------------
# Nur Daten: Elementsymbole aus fester Liste, Lagen in Ångström, Indizes, Zahlen. Die Oberfläche zeichnet daraus;
# die Orbital-Formel ist dort fest eingebaut, Claude nennt nur den Namen des Orbitals.

ELEMENTE = (
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca",
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr",
    "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
    "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm",
    "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds", "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
)                                                                                        # Ordnungszahl = Stelle + 1
ORDNUNGSZAHL = {s: i + 1 for i, s in enumerate(ELEMENTE)}
DARSTELLUNG = ("kugel-stab", "kalotte")
ORBITALE = ("1s", "2s", "2p_x", "2p_y", "2p_z", "3s", "3p_x", "3p_y", "3p_z", "3d_xy", "3d_xz", "3d_yz", "3d_x2-y2", "3d_z2")
MAX_ATOME, MAX_BINDUNGEN, MAX_ATOM_LABELS, LAGE_MAX = 300, 400, 20, 200
SCHALEN_REGEL = (2, 8, 8, 2)                                                             # einfache Regel bis 20 Elektronen
MAX_SCHALEN, SCHALE_MAX = 7, 32
MAX_SIM_PRO_ANSICHT, MAX_WEBGL_PRO_ANSICHT = 2, 2                                         # Last: Simulationen und 3D-Teilchen je Ansicht


def _element(v: Any, c: str) -> str:
    if not isinstance(v, str) or v not in ORDNUNGSZAHL:
        raise ViewError(c)
    return v


def _molekuel(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"form", "name", "atome", "bindungen", "beschriftungen", "darstellung"}, c)
    atome = []
    for a in _list(b.get("atome"), 1, MAX_ATOME, c):
        a = _item(a, {"element", "position"}, c)
        atome.append({"element": _element(a.get("element"), c),
                      "position": [_bounded(x, -LAGE_MAX, LAGE_MAX, c) for x in _list(a.get("position"), 3, 3, c)]})
    last = len(atome) - 1
    bindungen, paare = [], set()
    for e in _list(b.get("bindungen", []), 0, MAX_BINDUNGEN, c):                       # leer: die Oberfläche leitet sie aus Abständen ab
        e = _item(e, {"von", "bis", "ordnung"}, c)
        von, bis = _int(e.get("von"), 0, last, c), _int(e.get("bis"), 0, last, c)       # Index ab 0, nur vorhandene Atome
        paar = (min(von, bis), max(von, bis))
        if von == bis or paar in paare:                                                  # keine Bindung auf sich selbst, keine doppelte
            raise ViewError(c)
        paare.add(paar)
        bindungen.append({"von": von, "bis": bis, "ordnung": _int(e.get("ordnung", 1), 1, 3, c)})
    labels = []
    for lb in _list(b.get("beschriftungen", []), 0, MAX_ATOM_LABELS, c):
        lb = _item(lb, {"atom", "text"}, c)
        labels.append({"atom": _int(lb.get("atom"), 0, last, c), "text": _text(lb.get("text"), 40, c)})
    darstellung = b.get("darstellung", "kugel-stab")
    if not isinstance(darstellung, str) or darstellung not in DARSTELLUNG:
        raise ViewError(c)
    return {"name": _text(b.get("name"), 60, c, optional=True), "atome": atome, "bindungen": bindungen, "beschriftungen": labels,
            "darstellung": darstellung}


def _atom(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"form", "element", "neutronen", "ladung", "schalen"}, c)
    element = _element(b.get("element"), c)
    neutronen = _int(b.get("neutronen", -1), -1, 200, c)                                 # -1: nicht angegeben
    ladung = _int(b.get("ladung", 0), -3, 3, c)
    elektronen = ORDNUNGSZAHL[element] - ladung
    if elektronen < 0:
        raise ViewError(c)
    if "schalen" in b:
        schalen = [_int(s, 0, SCHALE_MAX, c) for s in _list(b["schalen"], 0, MAX_SCHALEN, c)]
        if sum(schalen) != elektronen:
            raise ViewError(c)
    elif elektronen <= sum(SCHALEN_REGEL):
        schalen, rest = [], elektronen
        for platz in SCHALEN_REGEL:
            if rest <= 0:
                break
            schalen.append(min(platz, rest))
            rest -= schalen[-1]
    else:                                                                                # über 20 Elektronen: Schalen sind Pflicht
        raise ViewError(c)
    return {"element": element, "neutronen": neutronen, "ladung": ladung, "schalen": schalen}


def _orbital(b: dict[str, Any], c: str) -> dict[str, Any]:
    _fields(b, {"form", "orbital", "punkte", "startwert"}, c)
    orbital = b.get("orbital")
    if not isinstance(orbital, str) or orbital not in ORBITALE:
        raise ViewError(c)
    return {"orbital": orbital, "punkte": _int(b.get("punkte", 2500), 500, 5000, c),
            "startwert": _int(b.get("startwert", 1), 0, MAX_STARTWERT, c)}


TEILCHEN_FORMEN: dict[str, Callable[[dict[str, Any], str], dict[str, Any]]] = {
    "molekuel": _molekuel, "atom": _atom, "orbital": _orbital,
}
WEBGL_FORMEN = ("molekuel", "orbital")


def _teilchen(b: dict[str, Any], c: str) -> dict[str, Any]:
    form = b.get("form")
    if not isinstance(form, str) or form not in TEILCHEN_FORMEN:
        raise ViewError(c)
    return {"form": form, **TEILCHEN_FORMEN[form](b, c)}


BLOCKS: dict[str, Callable[[dict[str, Any], str], dict[str, Any]]] = {
    "text": _text_block, "liste": _liste, "formel": _formel, "schritte": _schritte, "ergebnis": _ergebnis,
    "kennzahlen": _kennzahlen, "tabelle": _tabelle, "diagramm": _diagramm, "aussagen": _aussagen,
    "widerspruch": _aussagen, "quellen": _quellen, "hinweis": _hinweis, "systemzustand": _systemzustand,
    "fortschritt": _fortschritt, "aufgaben": _aufgaben, "zeitplan": _zeitplan, "mail": _mail,
    "mail-entwurf": _mail_entwurf, "countdown": _countdown, "dokument": _dokument, "aenderung": _aenderung,
    "szene3d": _szene3d, "plan2d": _plan2d, "vergleich": _vergleich, "zeitstrahl": _zeitstrahl, "gegenueber": _gegenueber,
    "lernkarten": _lernkarten, "quiz": _quiz, "anleitung": _anleitung, "netz": _netz, "simulation": _simulation,
    "teilchen": _teilchen,
}


def validate(raw: Any) -> dict[str, Any]:
    """Gibt die geprüfte Ansicht zurück oder wirft ViewError. Eine Ansicht mit `schliessen: true` braucht nur die `id`.
    Letzte Sicherung: Jeder andere Fehler wird zu ViewError("bad_view"), damit keine Eingabe den Channel oder die Bridge beendet."""
    try:
        return _validate(raw)
    except ViewError:
        raise
    except Exception:
        raise ViewError("bad_view") from None


def _validate(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ViewError("bad_view")
    try:
        size = len(json.dumps(raw, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        raise ViewError("bad_view") from None
    except RecursionError:                                 # sehr tief verschachtelt: wie zu groß behandeln, nie ein Absturz
        raise ViewError("too_large") from None
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
    blocks, sims, webgl = [], 0, 0
    for i, b in enumerate(_list(raw.get("bausteine"), 1, MAX_BLOCKS, "bad_blocks")):
        code = f"bad_block_{i + 1}"
        if not isinstance(b, dict) or not isinstance(b.get("typ"), str) or b["typ"] not in BLOCKS:
            raise ViewError(code)
        block = {"typ": b["typ"], **BLOCKS[b["typ"]](b, code)}
        sims += block["typ"] == "simulation"
        webgl += block["typ"] == "teilchen" and block["form"] in WEBGL_FORMEN
        if sims > MAX_SIM_PRO_ANSICHT or webgl > MAX_WEBGL_PRO_ANSICHT:                 # Last: der erste Baustein über der Grenze
            raise ViewError(code)
        blocks.append(block)
    nrs = {q["nr"] for b in blocks if b["typ"] == "quellen" for q in b["quellen"]}
    for i, b in enumerate(blocks):                         # Quellennummern müssen auf eine genannte Quelle zeigen
        if b["typ"] in ("aussagen", "widerspruch") and any(n not in nrs for a in b["aussagen"] for n in a["quellen"]):
            raise ViewError(f"bad_source_{i + 1}")
    view = {"id": vid, "art": art, "titel": _text(raw.get("titel"), 120, "bad_title"), "stand": stand,
            "bausteine": blocks, "schliessen": False}
    if len(json.dumps(view, ensure_ascii=False).encode("utf-8")) > MAX_JSON:            # ergänzte Standardwerte: die zweite Prüfung muss sie tragen
        raise ViewError("too_large")
    return view
