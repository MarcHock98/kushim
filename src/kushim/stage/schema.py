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
ARTEN = ("antwort", "rechnung", "markt", "recherche", "auftrag", "mail", "dokument")
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


BLOCKS: dict[str, Callable[[dict[str, Any], str], dict[str, Any]]] = {
    "text": _text_block, "liste": _liste, "formel": _formel, "schritte": _schritte, "ergebnis": _ergebnis,
    "kennzahlen": _kennzahlen, "tabelle": _tabelle, "diagramm": _diagramm, "aussagen": _aussagen,
    "widerspruch": _aussagen, "quellen": _quellen, "hinweis": _hinweis, "systemzustand": _systemzustand,
    "fortschritt": _fortschritt, "aufgaben": _aufgaben, "zeitplan": _zeitplan, "mail": _mail,
    "mail-entwurf": _mail_entwurf, "countdown": _countdown, "dokument": _dokument, "aenderung": _aenderung,
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
