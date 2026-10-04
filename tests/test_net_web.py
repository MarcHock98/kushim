import ssl

import pytest

from kushim.net import web
from kushim.net.web import WebDenied, check_url, fetch_text

GOOD = "https://de.wikipedia.org/w/api.php?action=query&generator=search&gsrsearch=Eiffelturm&prop=extracts&format=json"


class FakeResponse:
    def __init__(self, status=200, headers=None, body=b'{"query": {}}'):
        headers = {"Content-Type": "application/json"} if headers is None else headers      # {} heißt: gar keine Header
        self.status, self._headers, self._body = status, {k.lower(): v for k, v in headers.items()}, body
        self.read_calls = []

    def getheader(self, name, default=None):
        return self._headers.get(name.lower(), default)

    def read(self, n=-1):
        self.read_calls.append(n)
        return self._body if n < 0 else self._body[:n]


class FakeConn:
    def __init__(self, response=None, error=None):
        self.response, self.error = response or FakeResponse(), error
        self.requests, self.closed = [], False

    def request(self, method, target, headers=None):
        self.requests.append((method, target, headers or {}))
        if self.error:
            raise self.error

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def run(response=None, error=None, url=GOOD):
    conn = FakeConn(response, error)
    return fetch_text(url, connect=lambda host, timeout: conn), conn


# --- Adress-Grenze -------------------------------------------------------------------------------

def test_check_url_accepts_only_the_exact_form():
    assert check_url(GOOD) == ("de.wikipedia.org", "/w/api.php?action=query&generator=search&gsrsearch=Eiffelturm&prop=extracts&format=json")


@pytest.mark.parametrize("bad", [
    "http://de.wikipedia.org/w/api.php?a=1",
    "https://en.wikipedia.org/w/api.php?a=1",
    "https://de.wikipedia.org.evil.com/w/api.php?a=1",
    "https://evil.com/w/api.php?a=1",
    "https://wikipedia.org/w/api.php?a=1",
    "https://user:pw@de.wikipedia.org/w/api.php?a=1",
    "https://de.wikipedia.org:8443/w/api.php?a=1",
    "https://de.wikipedia.org/w/index.php?a=1",
    "https://de.wikipedia.org/wiki/Eiffelturm",
    "https://de.wikipedia.org/w/api.php?a=1#frag",
    "ftp://de.wikipedia.org/w/api.php",
    "file:///C:/Windows/win.ini",
    "//de.wikipedia.org/w/api.php",
    "https://de.wikipedia.org/w/api.php?" + "a" * 2100,
    "", None, 5,
])
def test_check_url_refuses_everything_else(bad):
    with pytest.raises(WebDenied):
        check_url(bad)


def test_nothing_is_connected_for_a_refused_url():
    def never(host, timeout):
        pytest.fail("Verbindung trotz abgelehnter Adresse")
    with pytest.raises(WebDenied):
        fetch_text("https://evil.com/w/api.php", connect=never)


# --- Normaler Abruf ------------------------------------------------------------------------------

def test_a_plain_get_without_cookies_credentials_or_compression():
    text, conn = run(FakeResponse(body='{"query": {"pages": {}}}'.encode()))
    assert text == '{"query": {"pages": {}}}' and conn.closed
    (method, target, headers), = conn.requests
    assert method == "GET" and target.startswith("/w/api.php?")
    assert "Cookie" not in headers and "Authorization" not in headers
    assert headers["Accept-Encoding"] == "identity" and headers["Accept"] == "application/json"
    assert "kushim" in headers["User-Agent"] and "@" not in headers["User-Agent"]          # keine persönlichen Daten


def test_content_type_parameters_and_case_are_fine():
    text, _ = run(FakeResponse(headers={"Content-Type": "Application/JSON; charset=utf-8"}, body="Höhe".encode()))
    assert text == "Höhe"


# --- Keine Downloads -----------------------------------------------------------------------------

@pytest.mark.parametrize("ctype", ["application/octet-stream", "application/zip", "application/pdf", "application/x-msdownload",
                                   "text/html", "text/plain", "image/png", "video/mp4", "application/javascript", ""])
def test_anything_but_json_text_is_refused_as_a_download(ctype):
    headers = {"Content-Type": ctype} if ctype else {}
    with pytest.raises(WebDenied, match="keine Downloads"):
        run(FakeResponse(headers=headers, body=b"MZ\x90\x00binary"))


def test_attachment_and_compressed_responses_are_refused():
    with pytest.raises(WebDenied, match="Download"):
        run(FakeResponse(headers={"Content-Type": "application/json", "Content-Disposition": 'attachment; filename="x.json"'}))
    with pytest.raises(WebDenied, match="Komprimiert"):
        run(FakeResponse(headers={"Content-Type": "application/json", "Content-Encoding": "gzip"}))


def test_size_limit_is_enforced_by_header_and_by_actual_bytes():
    with pytest.raises(WebDenied, match="zu groß"):
        run(FakeResponse(headers={"Content-Type": "application/json", "Content-Length": str(web.MAX_BYTES + 1)}))
    big = FakeResponse(body=b"x" * (web.MAX_BYTES + 5))                       # lügt oder verschweigt die Länge
    with pytest.raises(WebDenied, match="zu groß"):
        run(big)
    assert big.read_calls == [web.MAX_BYTES + 1]                              # nie mehr als Limit + 1 gelesen
    text, _ = run(FakeResponse(body=b"x" * web.MAX_BYTES))                    # genau am Limit: erlaubt
    assert len(text) == web.MAX_BYTES


# --- Fehler und Weiterleitungen ------------------------------------------------------------------

@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirects_are_never_followed(status):
    with pytest.raises(WebDenied, match="Weiterleitung"):
        run(FakeResponse(status=status, headers={"Location": "https://evil.com/x", "Content-Type": "application/json"}))


@pytest.mark.parametrize("status", [204, 400, 403, 404, 429, 500, 503])
def test_other_statuses_are_errors(status):
    with pytest.raises(WebDenied, match="Server meldet"):
        run(FakeResponse(status=status))


@pytest.mark.parametrize("error", [TimeoutError("C:\\geheim"), ConnectionResetError("x"), ssl.SSLError("Zertifikat falsch"),
                                    OSError("de.wikipedia.org nicht erreichbar")])
def test_connection_errors_are_neutral_and_the_connection_is_closed(error):
    conn = FakeConn(error=error)
    with pytest.raises(WebDenied) as e:
        fetch_text(GOOD, connect=lambda host, timeout: conn)
    assert str(e.value) == "Verbindung fehlgeschlagen" and conn.closed
    assert "geheim" not in str(e.value) and "wikipedia" not in str(e.value)


# --- Echte Verbindungsparameter (ohne zu verbinden) ----------------------------------------------

def test_real_connection_verifies_certificates_on_port_443(monkeypatch):
    seen = {}

    def fake(host, port, timeout=None, context=None):
        seen.update(host=host, port=port, timeout=timeout, context=context)
        return FakeConn()
    monkeypatch.setattr(web.http.client, "HTTPSConnection", fake)
    web._connect("de.wikipedia.org", 7.0)
    assert seen["host"] == "de.wikipedia.org" and seen["port"] == 443 and seen["timeout"] == 7.0
    assert seen["context"].verify_mode == ssl.CERT_REQUIRED and seen["context"].check_hostname is True
