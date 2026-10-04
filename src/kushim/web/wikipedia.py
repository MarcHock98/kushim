"""Wikipedia (de) als erste Quelle: URL-Bau, URL-Prüfung und Antwort-Parser (ohne Netzwerk).

Eine einzige Anfrage (MediaWiki-API, nur GET): `generator=search` mit `prop=extracts` liefert bis zu 3 Treffer mit Einleitungstext.
Antwortform am 2026-10-04 geprüft: `query.pages.<pageid>.{pageid, ns, title, index, extract}`, keine URL im Treffer
(die Artikeladresse wird aus dem Titel gebaut). `check_url` ist die feste Grenze: nur diese Domain, nur HTTPS, nur dieser Pfad.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from .sanitize import clean_text

HOST = "de.wikipedia.org"
PATH = "/w/api.php"
MAX_BODY = 1_000_000
MAX_HITS = 3
_ALLOWED_PARAMS = {"action", "generator", "gsrsearch", "gsrlimit", "prop", "exintro", "explaintext", "exlimit",
                   "exchars", "format", "utf8"}
_FIXED = {"action": "query", "generator": "search", "prop": "extracts", "format": "json"}


@dataclass(frozen=True)
class Hit:
    title: str
    url: str
    extract: str             # bereits bereinigt und gekürzt
    raw: str = ""            # Rohtext (nur für die Prüfung auf Einschleus-Muster, nie an das LLM)


def build_url(query: str) -> str:
    params = {"action": "query", "generator": "search", "gsrsearch": query, "gsrlimit": MAX_HITS, "prop": "extracts",
              "exintro": 1, "explaintext": 1, "exlimit": MAX_HITS, "exchars": 800, "format": "json", "utf8": 1}
    return f"https://{HOST}{PATH}?{urlencode(params)}"


def check_url(url: str) -> str:
    """Wirft ValueError, wenn die Adresse nicht GENAU die erlaubte Form hat. Gibt die Adresse zurück."""
    u = urlsplit(url)
    ok = (u.scheme == "https" and (u.hostname or "").lower() == HOST and u.port in (None, 443)
          and not u.username and not u.password and u.path == PATH and not u.fragment)
    if not ok:
        raise ValueError("Adresse nicht erlaubt")
    pairs = parse_qsl(u.query, keep_blank_values=True)
    keys = [k for k, _ in pairs]
    if not set(keys) <= _ALLOWED_PARAMS or len(keys) != len(set(keys)):      # nur bekannte Parameter, keiner doppelt
        raise ValueError("Unerlaubte Parameter")
    values = dict(pairs)
    if any(values.get(k) != v for k, v in _FIXED.items()):                    # nur lesende Suche, nie action=edit o. ä.
        raise ValueError("Unerlaubte Parameterwerte")
    return url


def article_url(title: str) -> str:
    return f"https://{HOST}/wiki/" + quote(title.replace(" ", "_"), safe="_()")


def parse(body: str) -> list[Hit]:
    """Antwort der API -> Treffer in Reihenfolge von `index`. Unerwartetes wird übersprungen, nie geraten."""
    if len(body) > MAX_BODY:
        raise ValueError("Antwort zu groß")
    try:
        data = json.loads(body)
        pages = data["query"]["pages"]
    except (ValueError, KeyError, TypeError):
        return []                                  # keine Treffer ("query" fehlt) oder unlesbar
    if not isinstance(pages, dict):
        return []
    items = []
    for page in pages.values():
        if not isinstance(page, dict) or not isinstance(page.get("title"), str) or not isinstance(page.get("extract"), str):
            continue
        index = page.get("index")
        items.append((index if isinstance(index, int) else 10**6, page["title"], page["extract"]))
    items.sort(key=lambda t: t[0])
    return [Hit(clean_text(title, 120), article_url(title), clean_text(extract, 600), raw=title + "\n" + extract)
            for _, title, extract in items[:MAX_HITS]]
