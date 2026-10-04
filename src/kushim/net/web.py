"""Netz-Modul der Web-Recherche: die einzige Stelle neben net/loopback.py mit Zugriff auf das Internet.

Vom Nutzer am 2026-10-04 ausdrücklich freigegeben ("erstelle eine Websuche mit net/web.py, keine Downloads erlauben"),
ALLOWLIST in tests/test_no_egress.py. Die Grenzen sind fest und werden von Tests gesperrt:

- Nur HTTPS-GET zu `ALLOWED_HOSTS` (genau diese Domain, keine Subdomains) und nur auf `ALLOWED_PATHS`.
- Zertifikatsprüfung an, kein Proxy, keine Cookies, keine Anmeldedaten, KEINE Weiterleitungen (3xx = Fehler).
- KEINE DOWNLOADS: nur JSON-Text (`ALLOWED_CONTENT_TYPES`), `Content-Disposition: attachment` und jede andere Art
  (Binärdaten, Archive, PDF, Programme) werden abgelehnt; komprimierte Antworten ebenfalls. Es wird nie etwas auf die
  Platte geschrieben (kein `open`, kein `shutil`, kein `tempfile`): die Antwort lebt nur im Arbeitsspeicher.
- Höchstens `MAX_BYTES` Antwort, `TIMEOUT` Sekunden.
Neue Domains oder Pfade nur per Codeänderung und Test, nie zur Laufzeit, nie durch Inhalte oder das LLM.
Aufgerufen wird `fetch_text` nur nach Vorschau und Freigabe (web/search.py, ApprovalQueue).
"""
from __future__ import annotations

import http.client
import ssl
from typing import Any, Callable
from urllib.parse import urlsplit

ALLOWED_HOSTS = frozenset({"de.wikipedia.org"})
ALLOWED_PATHS = frozenset({"/w/api.php"})
ALLOWED_CONTENT_TYPES = frozenset({"application/json"})
MAX_BYTES = 1_000_000
MAX_URL = 2000
TIMEOUT = 10.0
USER_AGENT = "kushim/0.1 (private local assistant; read-only queries)"      # Wikipedia verlangt einen beschreibenden Namen


class WebDenied(Exception):
    """Abruf nicht erlaubt oder fehlgeschlagen. Der Text nennt nur den Grund, nie Adressen oder Antwortinhalte."""


def check_url(url: str) -> tuple[str, str]:
    """(Host, Pfad mit Query) oder WebDenied. Nur https, nur erlaubte Domain und Pfad, keine Zugangsdaten, kein Fragment."""
    if not isinstance(url, str) or len(url) > MAX_URL:
        raise WebDenied("Adresse ungültig")
    u = urlsplit(url)
    host = (u.hostname or "").lower()
    if (u.scheme != "https" or host not in ALLOWED_HOSTS or u.port not in (None, 443) or u.username or u.password
            or u.fragment or u.path not in ALLOWED_PATHS):
        raise WebDenied("Adresse nicht erlaubt")
    return host, u.path + (f"?{u.query}" if u.query else "")


def _connect(host: str, timeout: float) -> Any:
    ctx = ssl.create_default_context()                  # Zertifikat und Hostname werden geprüft
    return http.client.HTTPSConnection(host, 443, timeout=timeout, context=ctx)


def fetch_text(url: str, timeout: float = TIMEOUT, connect: Callable[[str, float], Any] = _connect) -> str:
    """Holt eine Antwort als Text (nur JSON). Wirft WebDenied bei allem, was nicht genau passt. Schreibt nie auf die Platte."""
    host, target = check_url(url)
    conn = connect(host, timeout)
    try:
        conn.request("GET", target, headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                             "Accept-Encoding": "identity", "Connection": "close"})
        resp = conn.getresponse()
        if 300 <= resp.status < 400:
            raise WebDenied("Weiterleitung nicht erlaubt")
        if resp.status != 200:
            raise WebDenied(f"Server meldet {resp.status}")
        ctype = (resp.getheader("Content-Type") or "").split(";")[0].strip().lower()
        if ctype not in ALLOWED_CONTENT_TYPES:
            raise WebDenied("Antwort ist kein Text (keine Downloads erlaubt)")
        if "attachment" in (resp.getheader("Content-Disposition") or "").lower():
            raise WebDenied("Download abgelehnt")
        if (resp.getheader("Content-Encoding") or "identity").strip().lower() != "identity":
            raise WebDenied("Komprimierte Antwort abgelehnt")
        declared = resp.getheader("Content-Length")
        if declared and declared.isdigit() and int(declared) > MAX_BYTES:
            raise WebDenied("Antwort zu groß")
        data = resp.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise WebDenied("Antwort zu groß")
        return data.decode("utf-8", errors="replace")
    except WebDenied:
        raise
    except (OSError, http.client.HTTPException, ssl.SSLError):     # keine Details (Adressen, Systemtexte) nach außen
        raise WebDenied("Verbindung fehlgeschlagen")
    finally:
        try:
            conn.close()
        except Exception:                                # noqa: BLE001
            pass
