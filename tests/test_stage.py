"""Bühne (P2): Schema der Ansichten, Werkzeug `zeige` im Channel, Weg über die Bridge, API `stage.get`, Notaus."""
import io
import json
import threading

import pytest

from kushim.api.protocol import ApiCore, new_token
from kushim.api.stage_api import register_stage
from kushim.channel import bridge as br
from kushim.channel import server as ch
from kushim.safety import killswitch
from kushim.stage import schema
from kushim.stage.store import MAX_VIEWS, ViewStore

TOKEN = "t" * 32

MATHE = {"id": "mathe-1", "art": "rechnung", "titel": "Gleichung", "bausteine": [
    {"typ": "text", "absaetze": ["Löse x² − 5x + 6 = 0."]},
    {"typ": "schritte", "schritte": [{"text": "Mitternachtsformel", "tex": "x = \\frac{5 \\pm 1}{2}"}, {"text": "Ausrechnen"}]},
    {"typ": "ergebnis", "tex": "x \\in \\{2, 3\\}"}]}
MARKT = {"id": "dax", "art": "markt", "titel": "DAX", "stand": "2026-11-12 14:05", "bausteine": [
    {"typ": "kennzahlen", "werte": [{"name": "DAX", "wert": 19420.5, "einheit": "Pkt", "aenderung": "+0,8 %", "richtung": "auf"}]},
    {"typ": "diagramm", "form": "linie", "x_titel": "Tag", "reihen": [{"name": "DAX", "punkte": [["Mo", 19200], ["Di", 19420.5]]}]},
    {"typ": "tabelle", "spalten": ["Titel", "Kurs"], "zeilen": [["SAP", 231.4], ["Siemens", 188]]}]}
RECHERCHE = {"id": "r", "art": "recherche", "titel": "Frage", "bausteine": [
    {"typ": "aussagen", "aussagen": [{"text": "A stimmt.", "quellen": [1, 2]}]},
    {"typ": "widerspruch", "aussagen": [{"text": "Bei B uneinig.", "quellen": [2]}]},
    {"typ": "quellen", "quellen": [{"nr": 1, "titel": "Eins", "adresse": "https://example.org/a"}, {"nr": 2, "titel": "Zwei"}]}]}


# --- Schema -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("view", [MATHE, MARKT, RECHERCHE,
                                  {"id": "s", "art": "antwort", "titel": "System", "bausteine": [{"typ": "systemzustand"}]},
                                  {"id": "x", "schliessen": True}])
def test_valid_views_pass_and_keep_their_content(view):
    v = schema.validate(view)
    assert v["id"] == view["id"]
    if not view.get("schliessen"):
        assert [b["typ"] for b in v["bausteine"]] == [b["typ"] for b in view["bausteine"]]


def test_text_is_cleaned_to_one_line_of_printable_characters():
    v = schema.validate({"id": "a", "art": "antwort", "titel": "T\x1b[2J", "bausteine": [{"typ": "text", "absaetze": ["a\nb\tc <b>x</b>"]}]})
    assert v["titel"] == "T [2J" and v["bausteine"][0]["absaetze"] == ["a b c <b>x</b>"]      # bleibt Text, die UI zeigt ihn als Text


def bad(code, **change):
    view = {**MATHE, **change}
    with pytest.raises(schema.ViewError) as e:
        schema.validate(view)
    assert e.value.code == code


def test_rejections_have_short_fixed_codes():
    bad("bad_id", id="Mit Leerzeichen")
    bad("bad_id", id="x" * 41)
    bad("bad_art", art="html")
    bad("unknown_field", onclick="x")
    bad("bad_blocks", bausteine=[])
    bad("bad_blocks", bausteine=[{"typ": "text", "absaetze": ["a"]}] * 13)
    bad("bad_block_1", bausteine=[{"typ": "iframe", "src": "x"}])
    bad("bad_block_1", bausteine=[{"typ": "text", "absaetze": ["a"], "html": "<b>"}])
    bad("bad_block_1", bausteine=[{"typ": "text", "absaetze": ["x" * 1201]}])
    bad("bad_block_1", bausteine=[{"typ": "formel", "tex": "x" * 501}])
    bad("bad_block_1", bausteine=[{"typ": "diagramm", "form": "linie", "reihen": [{"name": "a", "punkte": [[1, float("nan")]]}]}])
    bad("bad_block_1", bausteine=[{"typ": "diagramm", "form": "torte", "reihen": [{"name": "a", "punkte": [[1, 1]]}]}])
    bad("bad_block_1", bausteine=[{"typ": "tabelle", "spalten": ["a", "b"], "zeilen": [["nur eins"]]}])
    bad("bad_block_1", bausteine=[{"typ": "kennzahlen", "werte": [{"name": "a", "wert": True}]}])
    bad("bad_block_1", bausteine=[{"typ": "kennzahlen", "werte": [{"name": "a", "wert": 1, "richtung": "seitwärts"}]}])
    bad("bad_block_1", bausteine=[{"typ": "systemzustand", "werte": {"cpu": 99}}])            # Werte nur von kushim selbst
    bad("bad_source_1", bausteine=[{"typ": "aussagen", "aussagen": [{"text": "a", "quellen": [3]}]}])
    bad("too_large", bausteine=[{"typ": "text", "absaetze": ["x" * 1200] * 12}] * 4)
    with pytest.raises(schema.ViewError) as e:
        schema.validate({**MARKT, "stand": ""})
    assert e.value.code == "missing_stand"
    with pytest.raises(schema.ViewError):
        schema.validate(["keine", "ansicht"])


# --- Store und API ------------------------------------------------------------------------------------

def test_store_updates_by_id_closes_and_keeps_at_most_max_views():
    s = ViewStore()
    s.put(schema.validate(MATHE))
    s.put(schema.validate(MARKT))
    s.put(schema.validate({**MATHE, "titel": "Neu"}))                       # gleiche id: ersetzt, neue Nummer
    items, last = s.since(0)
    assert [i["id"] for i in items] == ["dax", "mathe-1"] and items[-1]["titel"] == "Neu" and last == 3
    assert s.since(3) == ([], 3)
    s.put(schema.validate({"id": "dax", "schliessen": True}))
    assert s.since(3)[0][0]["schliessen"] is True
    for i in range(MAX_VIEWS + 5):
        s.put(schema.validate({**MATHE, "id": f"v{i}"}))
    assert len(s.since(0)[0]) == MAX_VIEWS


def test_stage_get_api_and_kill_switch(tmp_path):
    core, token, s = ApiCore(token := new_token()), token, ViewStore()
    register_stage(core, s, tmp_path)
    ask = lambda **m: json.loads(core.handle(json.dumps({"token": token, "type": "stage.get", **m})))
    s.put(schema.validate(MATHE))
    r = ask(since=0)
    assert r["ok"] and r["last"] == 1 and r["items"][0]["art"] == "rechnung"
    assert ask(since=1)["items"] == []
    assert ask(since=-1) == {"ok": False, "error": "bad_since"} and ask(since="0")["ok"] is False
    killswitch.trigger(tmp_path)
    assert ask(since=0)["items"] == []                                        # Notaus: nichts mehr zeigen


# --- Channel-Werkzeug und Bridge ----------------------------------------------------------------------

def call(c, out, args):
    c.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "zeige", "arguments": args}})
    return json.loads(out.getvalue().splitlines()[-1])["result"]


def test_zeige_tool_is_listed_validates_and_queues():
    out = io.StringIO()
    c = ch.Channel(out, log=lambda s: None)
    c.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    tools = {t["name"]: t for t in json.loads(out.getvalue().splitlines()[-1])["result"]["tools"]}
    assert set(tools) == {"sprich", "zeige"} and "systemzustand" in tools["zeige"]["description"]
    assert "zeige" in ch.INSTRUCTIONS
    r = call(c, out, {"id": "BAD"})
    assert r["isError"] is True and "bad_id" in r["content"][0]["text"] and c.take_views() == []
    assert call(c, out, MATHE)["content"][0]["text"] == "Wird gezeigt."
    assert [v["id"] for v in c.take_views()] == ["mathe-1"] and c.take_views() == []


@pytest.fixture
def channel(tmp_path):
    out = io.StringIO()
    c = ch.Channel(out, log=lambda s: None)
    c.ready.set()
    httpd = ch.make_http(c, tmp_path, TOKEN)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    ch.write_info(tmp_path, httpd.server_address[1], TOKEN)
    yield c, out, tmp_path
    httpd.shutdown()


def test_views_travel_through_the_real_channel_into_the_bridge_store(channel):
    c, out, root = channel
    b = br.Bridge(root)
    c.show(MARKT)
    c._views.append({"id": "kaputt", "art": "html"})                          # an der ersten Prüfung vorbei: die Bridge prüft erneut
    c.say("Hier der DAX.")
    assert b.fetch() == ("ok", ["Hier der DAX."])
    items, _ = b.stage.since(0)
    assert [i["id"] for i in items] == ["dax"]


def test_no_views_pass_while_the_kill_switch_is_active(channel):
    c, out, root = channel
    b = br.Bridge(root)
    c.show(MATHE)
    killswitch.trigger(root)
    assert b.fetch()[0] != "ok" and b.stage.since(0)[0] == []


# --- P3a: Aufträge, Listen, Zeitplan, Mail, Countdown (docs/ui-p3-plan.md) ---------------------------

def _soon(minutes=10):
    from datetime import datetime, timedelta
    return (datetime.now() + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def p3(typ, art="auftrag", **fields):
    return {"id": "p3", "art": art, "titel": "T", "bausteine": [{"typ": typ, **fields}]}


STEPS = [{"text": "Tests lesen", "zustand": "fertig"}, {"text": "Fehler beheben", "zustand": "laeuft"}, {"text": "Committen"}]
MAIL = dict(von="Anna <anna@example.org>", betreff="Termin", absaetze=["Hallo,", "passt Dienstag?"])
DRAFT = dict(an="anna@example.org", betreff="Re: Termin", absaetze=["Ja, Dienstag passt."])


def test_p3a_blocks_pass_and_get_a_fixed_shape():
    b = schema.validate(p3("fortschritt", schritte=STEPS))["bausteine"][0]
    assert [s["zustand"] for s in b["schritte"]] == ["fertig", "laeuft", "offen"] and b["hinweis"] == ""
    b = schema.validate(p3("aufgaben", punkte=[{"text": "Milch", "erledigt": True}, {"text": "Brot"}]))["bausteine"][0]
    assert b["punkte"] == [{"text": "Milch", "erledigt": True}, {"text": "Brot", "erledigt": False}]
    b = schema.validate(p3("zeitplan", tag="Dienstag", termine=[{"von": "14:00", "bis": "15:00", "titel": "B"},
                                                               {"von": "09:30", "bis": "10:00", "titel": "A", "ort": "Büro"}]))["bausteine"][0]
    assert [t["titel"] for t in b["termine"]] == ["A", "B"] and b["termine"][0]["ort"] == "Büro"     # nach Zeit sortiert
    b = schema.validate(p3("mail", art="mail", **MAIL))["bausteine"][0]
    assert b["von"] == MAIL["von"] and b["absaetze"] == MAIL["absaetze"] and b["an"] == "" and b["zusammenfassung"] == ""
    b = schema.validate(p3("mail-entwurf", art="mail", **DRAFT))["bausteine"][0]
    assert b == {"typ": "mail-entwurf", "an": DRAFT["an"], "cc": "", "betreff": DRAFT["betreff"], "absaetze": DRAFT["absaetze"]}


def test_mail_text_loses_control_and_direction_characters():
    tricky = "Rechnung" + chr(0x202e) + "fdp.exe" + chr(0) + chr(27) + "[31m rot" + chr(10) + "zweite Zeile"
    b = schema.validate(p3("mail", art="mail", von="x", betreff="y" + chr(0x200f), absaetze=[tricky]))["bausteine"][0]
    text = b["absaetze"][0] + b["betreff"]
    assert all(ch.isprintable() for ch in text) and chr(0x202e) not in text and chr(10) not in text
    assert "Rechnung" in text and "zweite Zeile" in text


def test_countdown_accepts_only_a_plain_iso_time():
    for ende in (_soon(), "2026-11-12T12:00", "2026-11-12T12:00:03+01:00", "2026-11-12T11:00:03Z"):
        assert schema.validate(p3("countdown", titel="Tee", ende=ende))["bausteine"][0] == {"typ": "countdown", "titel": "Tee", "ende": ende}
    for ende in ("morgen", "", None, 1794522000, "2026-13-01T10:00:00", "2026-11-32T10:00:00", "2026-11-12T24:00:00",
                 "2026-11-12T10:60:00", "2026-11-12 10:00:00", "2026-11-12T10:00:00+0100", "2026-11-12T10:00:00 ", "9" * 41,
                 "2026-11-12T10:00:00<script>", "٢٠٢٦-11-12T10:00:00"):
        with pytest.raises(schema.ViewError):
            schema.validate(p3("countdown", titel="Tee", ende=ende))
    with pytest.raises(schema.ViewError):
        schema.validate(p3("countdown", ende=_soon()))                                                # ohne Titel


@pytest.mark.parametrize("typ,fields", [
    ("fortschritt", dict(schritte=[])),
    ("fortschritt", dict(schritte=[{"text": "x", "zustand": "fast fertig"}])),
    ("fortschritt", dict(schritte=[{"text": "x", "befehl": "rm"}])),
    ("fortschritt", dict(schritte=[{"text": "x"}] * 21)),
    ("fortschritt", dict(schritte=[{"text": "x" * 201}])),
    ("fortschritt", dict(schritte=STEPS, prozent=50)),
    ("aufgaben", dict(punkte=[{"text": "x", "erledigt": "ja"}])),
    ("aufgaben", dict(punkte=[{"text": "x"}] * 41)),
    ("aufgaben", dict(punkte=["x"])),
    ("zeitplan", dict(termine=[{"von": "9:00", "bis": "10:00", "titel": "A"}])),
    ("zeitplan", dict(termine=[{"von": "24:00", "bis": "25:00", "titel": "A"}])),
    ("zeitplan", dict(termine=[{"von": "10:00", "bis": "10:00", "titel": "A"}])),
    ("zeitplan", dict(termine=[{"von": "11:00", "bis": "10:00", "titel": "A"}])),
    ("zeitplan", dict(termine=[{"von": "10:00", "bis": "10:60", "titel": "A"}])),
    ("zeitplan", dict(termine=[{"von": "١٠:٠٠", "bis": "11:00", "titel": "A"}])),
    ("zeitplan", dict(termine=[{"von": 600, "bis": "11:00", "titel": "A"}])),
    ("zeitplan", dict(termine=[{"von": "10:00", "bis": "11:00", "titel": "A", "link": "x"}])),
    ("zeitplan", dict(termine=[{"von": "10:00", "bis": "11:00", "titel": "A"}] * 31)),
    ("mail", {**MAIL, "von": ""}),
    ("mail", {**MAIL, "html": "<b>x</b>"}),
    ("mail", {**MAIL, "anhang": "rechnung.pdf"}),
    ("mail", {**MAIL, "absaetze": ["x" * 1500] * 5}),
    ("mail", {**MAIL, "absaetze": "Hallo"}),
    ("mail", {**MAIL, "absaetze": ["x"] * 41}),
    ("mail-entwurf", {**DRAFT, "an": ""}),
    ("mail-entwurf", {**DRAFT, "senden": True}),
    ("mail-entwurf", {**DRAFT, "bcc": "x@example.org"}),
    ("mail-entwurf", {**DRAFT, "absaetze": []}),
])
def test_p3a_rejections(typ, fields):
    with pytest.raises(schema.ViewError) as e:
        schema.validate(p3(typ, **fields))
    assert e.value.code == "bad_block_1"


def test_zeige_tool_names_the_new_kinds_and_tells_claude_showing_is_not_an_approval():
    assert {"auftrag", "mail"} <= set(ch.ZEIGE_TOOL["inputSchema"]["properties"]["art"]["enum"])
    kinds = ch.ZEIGE_TOOL["inputSchema"]["properties"]["bausteine"]["items"]["properties"]["typ"]["enum"]
    assert {"fortschritt", "aufgaben", "zeitplan", "mail", "mail-entwurf", "countdown"} <= set(kinds)
    assert "gesendet wird damit nichts" in ch.ZEIGE_TOOL["description"] and "ohne Ton" in ch.ZEIGE_TOOL["inputSchema"]["properties"]["bausteine"]["description"]
    assert "Zeigen ersetzt nie eine Freigabe" in ch.INSTRUCTIONS


def test_p3a_views_travel_through_the_real_channel_into_the_bridge_store(channel):
    c, out, root = channel
    view = {"id": "job", "art": "auftrag", "titel": "Tests grün machen", "bausteine": [{"typ": "fortschritt", "schritte": STEPS}]}
    b = br.Bridge(root)
    call(c, out, view)
    c.say("Ich fange an.")
    assert b.fetch() == ("ok", ["Ich fange an."])
    got = b.stage.since(0)[0]
    assert got[0]["art"] == "auftrag" and got[0]["bausteine"][0]["schritte"][1]["zustand"] == "laeuft"


# --- P3b: Dokumente und Änderungen (docs/ui-p3b-plan.md) ----------------------------------------------

CODE = ["def rechne(a, b):", "    if a > b:", chr(9) + "return a", "", "    return b"]
DIFF = [{"kopf": "rechne", "zeilen": [{"art": "gleich", "text": "def rechne(a, b):"}, {"art": "weg", "text": "    return a"},
                                     {"art": "neu", "text": "    return max(a, b)"}]}]


def doc(typ, **fields):
    return {"id": "d", "art": "dokument", "titel": "T", "bausteine": [{"typ": typ, **fields}]}


def test_p3b_blocks_pass_and_keep_indentation():
    b = schema.validate(doc("dokument", name="src/app.py", ausschnitt="Zeilen 1 bis 5", zeilen=CODE,
                            gliederung=["rechne"]))["bausteine"][0]
    assert b["zeilen"] == ["def rechne(a, b):", "    if a > b:", "    return a", "", "    return b"]
    assert b["gliederung"] == ["rechne"] and b["ausschnitt"] == "Zeilen 1 bis 5"
    b = schema.validate(doc("aenderung", name="src/app.py", zusammenfassung="max statt a", bloecke=DIFF))["bausteine"][0]
    assert [z["art"] for z in b["bloecke"][0]["zeilen"]] == ["gleich", "weg", "neu"] and b["bloecke"][0]["zeilen"][1]["text"] == "    return a"


def test_p3b_lines_lose_control_and_direction_characters_but_keep_blank_lines():
    tricky = "x = 1" + chr(0x202e) + "# gedreht" + chr(0) + chr(27) + "[31m"
    b = schema.validate(doc("dokument", name="a.py", zeilen=[tricky, "", "   "]))["bausteine"][0]
    assert all(ch.isprintable() for line in b["zeilen"] for ch in line) and b["zeilen"][1:] == ["", ""]
    assert chr(0x202e) not in b["zeilen"][0] and b["zeilen"][0].startswith("x = 1")


@pytest.mark.parametrize("name", [".env", ".env.local", "config/.env.prod", "server.pem", "my.key", "id_rsa", "id_ed25519.pub",
                                  "C:" + chr(92) + "Users" + chr(92) + "x" + chr(92) + ".ssh" + chr(92) + "config", "a/.aws/credentials",
                                  "credentials.json", "secrets.yaml", "Passwords.md", "token.txt", "tokens.json", "run/channel.json",
                                  "run/api.json", ".npmrc", ".netrc"])
def test_p3b_names_that_look_like_credentials_are_rejected(name):
    with pytest.raises(schema.ViewError) as e:
        schema.validate(doc("dokument", name=name, zeilen=["x"]))
    assert e.value.code == "bad_block_1"
    with pytest.raises(schema.ViewError):
        schema.validate(doc("aenderung", name=name, bloecke=DIFF))


@pytest.mark.parametrize("name", ["src/app.py", "README.md", "ui/src/styles/tokens.css", "docs/token-plan.md", "keyboard.ts"])
def test_p3b_ordinary_names_pass(name):
    assert schema.validate(doc("dokument", name=name, zeilen=["x"]))["bausteine"][0]["name"] == name


@pytest.mark.parametrize("typ,fields", [
    ("dokument", dict(name="a.py", zeilen=[])),
    ("dokument", dict(name="a.py", zeilen=["x"] * 401)),
    ("dokument", dict(name="a.py", zeilen=["x" * 401])),
    ("dokument", dict(name="a.py", zeilen=[5])),
    ("dokument", dict(name="", zeilen=["x"])),
    ("dokument", dict(name="a.py", zeilen=["x"], gliederung=["g"] * 31)),
    ("dokument", dict(name="a.py", zeilen=["x"], pfad="C:/geheim")),
    ("dokument", dict(name="a.py", zeilen=["x"], html="<b>")),
    ("aenderung", dict(name="a.py", bloecke=[])),
    ("aenderung", dict(name="a.py", bloecke=[{"zeilen": [{"art": "kaputt", "text": "x"}]}])),
    ("aenderung", dict(name="a.py", bloecke=[{"zeilen": [{"art": "neu", "text": "x", "stil": "fett"}]}])),
    ("aenderung", dict(name="a.py", bloecke=[{"zeilen": ["x"]}])),
    ("aenderung", dict(name="a.py", bloecke=[{"zeilen": []}])),
    ("aenderung", dict(name="a.py", bloecke=[{"zeilen": [{"art": "neu", "text": "x"}] * 300}] * 2)),     # zusammen über 400
    ("aenderung", dict(name="a.py", bloecke=[{"zeilen": [{"art": "neu", "text": "x"}]}] * 21)),
    ("aenderung", dict(name="a.py", bloecke=DIFF, befehl="git apply")),
])
def test_p3b_rejections(typ, fields):
    with pytest.raises(schema.ViewError) as e:
        schema.validate(doc(typ, **fields))
    assert e.value.code == "bad_block_1"


def test_zeige_tool_names_the_document_blocks_and_tells_claude_how_to_read_on_request():
    assert "dokument" in ch.ZEIGE_TOOL["inputSchema"]["properties"]["art"]["enum"]
    kinds = ch.ZEIGE_TOOL["inputSchema"]["properties"]["bausteine"]["items"]["properties"]["typ"]["enum"]
    assert {"dokument", "aenderung"} <= set(kinds)
    assert "eigenen Werkzeugen" in ch.INSTRUCTIONS and "Zugangsdaten" in ch.INSTRUCTIONS
    assert "liest selbst keine Dateien" in ch.ZEIGE_TOOL["description"]


# --- P4a: 3D-Szene und Plan (docs/ui-p4-plan.md) -----------------------------------------------------

BOX = {"form": "box", "name": "Boden 1", "masse": [80, 2, 30], "position": [0, 10, 0], "farbe": "amber"}


def scene(*scenes, **extra):
    return {"id": "m", "art": "modell", "titel": "T", "bausteine": [
        {"typ": "szene3d", "einheit": "cm", "szenen": list(scenes) or [{"name": "jetzt", "objekte": [BOX]}], **extra}]}


def plan(elements, **extra):
    return {"id": "p", "art": "plan", "titel": "T", "bausteine": [{"typ": "plan2d", "elemente": elements, **extra}]}


def test_p4a_scene_passes_and_gets_a_fixed_shape():
    objs = [BOX, {"form": "kugel", "name": "Ball", "masse": [5]}, {"form": "zylinder", "masse": [2, 10], "drehung": [90, 0, 0]},
            {"form": "kegel", "masse": [2, 4]}, {"form": "torus", "masse": [5, 1]}, {"form": "ebene", "masse": [10, 10]},
            {"form": "linie", "name": "Achse", "punkte": [[0, 0, 0], [0, 100, 0]], "farbe": "gedaempft"}]
    b = schema.validate(scene({"name": "vorher", "objekte": objs}, {"name": "nachher", "objekte": [BOX]},
                              hervorheben=["Boden 1"], beschriftungen=[{"objekt": "Ball", "text": "Spielzeug"}]))["bausteine"][0]
    first = b["szenen"][0]["objekte"]
    assert first[1] == {"form": "kugel", "name": "Ball", "farbe": "arc", "masse": [5], "position": [0, 0, 0], "drehung": [0, 0, 0]}
    assert first[2]["name"] == "" and first[2]["drehung"] == [90, 0, 0] and first[6]["punkte"] == [[0, 0, 0], [0, 100, 0]]
    assert b["einheit"] == "cm" and b["hervorheben"] == ["Boden 1"] and b["beschriftungen"][0]["text"] == "Spielzeug"


def test_p4a_plan_passes_and_gets_a_fixed_shape():
    els = [{"art": "linie", "von": [0, 0], "bis": [10, 0], "ebene": "Wände"}, {"art": "polylinie", "punkte": [[0, 0], [5, 5], [0, 5]], "geschlossen": True},
           {"art": "rechteck", "x": 1, "y": 1, "b": 3, "h": 2}, {"art": "kreis", "x": 5, "y": 5, "r": 1}, {"art": "bogen", "x": 0, "y": 0, "r": 2, "von": 0, "bis": 90},
           {"art": "text", "x": 1, "y": 1, "text": "Küche"}, {"art": "mass", "von": [0, -2], "bis": [10, -2], "ebene": "Maße"}]
    b = schema.validate(plan(els, einheit="m", ebenen=["Wände", "Maße"]))["bausteine"][0]
    assert b["ebenen"] == ["Wände", "Maße"] and b["einheit"] == "m"
    assert b["elemente"][0] == {"art": "linie", "ebene": "Wände", "von": [0, 0], "bis": [10, 0]}
    assert b["elemente"][1]["geschlossen"] is True and b["elemente"][1]["ebene"] == ""
    assert b["elemente"][5]["groesse"] == 0 and b["elemente"][6]["text"] == "" and b["elemente"][6]["ebene"] == "Maße"


def objs(n):
    return [{"form": "box", "name": f"o{i}", "masse": [1, 1, 1]} for i in range(n)]


@pytest.mark.parametrize("change", [
    {"farbe": "#ff0000"}, {"farbe": "rot"}, {"farbe": 5}, {"form": "dodekaeder"}, {"form": "skript"}, {"masse": [80, 2]},
    {"masse": [80, 2, 0]}, {"masse": [80, -2, 30]}, {"masse": [80, 2, float("inf")]}, {"masse": [80, 2, float("nan")]},
    {"masse": [80, 2, 1_000_001]}, {"masse": [True, 2, 3]}, {"masse": ["80", 2, 3]}, {"position": [0, 0]}, {"position": [0, 0, 2_000_000]},
    {"position": [0, 0, None]}, {"drehung": [1, 2, 3, 4]}, {"name": "x" * 41}, {"name": 5}, {"url": "https://boese.example"}, {"material": "x"},
])
def test_p4a_scene_rejections_for_objects(change):
    with pytest.raises(schema.ViewError) as e:
        schema.validate(scene({"name": "s", "objekte": [{**BOX, **change}]}))
    assert e.value.code == "bad_block_1"


@pytest.mark.parametrize("make", [
    lambda: scene(),                                                                                  # gültig als Gegenprobe wird unten geprüft
    lambda: scene({"name": "s", "objekte": []}),
    lambda: scene({"name": "s", "objekte": objs(151)}),
    lambda: scene(*[{"name": f"s{i}", "objekte": objs(1)} for i in range(4)]),
    lambda: scene(*[{"name": f"s{i}", "objekte": objs(101)} for i in range(3)]),                   # zusammen 303, über 300
    lambda: scene({"name": "s", "objekte": [BOX, BOX]}),                                              # doppelter Name
    lambda: scene({"name": "s", "objekte": [BOX], "stil": "x"}),
    lambda: scene({"name": "", "objekte": [BOX]}),
    lambda: scene({"name": "s", "objekte": [BOX]}, hervorheben=["Gibt es nicht"]),
    lambda: scene({"name": "s", "objekte": [BOX]}, beschriftungen=[{"objekt": "Gibt es nicht", "text": "x"}]),
    lambda: scene({"name": "s", "objekte": [BOX]}, beschriftungen=[{"objekt": "Boden 1", "text": "x", "html": "<b>"}]),
    lambda: scene({"name": "s", "objekte": [BOX]}, hervorheben=["Boden 1"] * 21),
    lambda: scene({"name": "s", "objekte": [{"form": "linie", "punkte": [[0, 0, 0]]}]}),
    lambda: scene({"name": "s", "objekte": [{"form": "linie", "punkte": [[0, 0]] * 2}]}),
    lambda: scene({"name": "s", "objekte": [{"form": "linie", "punkte": [[0, 0, 0]] * 51}]}),
    lambda: scene({"name": "s", "objekte": [{"form": "linie", "punkte": [[0, 0, 0]] * 2, "position": [0, 0, 0]}]}),
    lambda: scene({"name": "s", "objekte": [BOX]}, einheit="x" * 9),
])
def test_p4a_scene_rejections(make):
    view = make()
    if view["bausteine"][0]["szenen"] == [{"name": "jetzt", "objekte": [BOX]}] and "hervorheben" not in view["bausteine"][0]:
        assert schema.validate(view)["bausteine"][0]["szenen"][0]["name"] == "jetzt"                 # Gegenprobe: der Standardfall ist gültig
        return
    with pytest.raises(schema.ViewError) as e:
        schema.validate(view)
    assert e.value.code == "bad_block_1"


def test_p4a_plan_rejections():
    ok = {"art": "linie", "von": [0, 0], "bis": [1, 1]}
    bad = [
        plan([]), plan([ok] * 801), plan([{**ok, "art": "spline"}]), plan([{**ok, "ebene": "Wände"}]),                  # Ebene nicht benannt
        plan([{**ok, "ebene": "Zaun"}], ebenen=["Wände"]), plan([ok], ebenen=["a"] * 2), plan([ok], ebenen=[f"e{i}" for i in range(11)]),
        plan([{**ok, "von": [0]}]), plan([{**ok, "bis": [0, 0, 0]}]), plan([{**ok, "bis": [0, float("nan")]}]), plan([{**ok, "bis": [0, 2_000_000]}]),
        plan([{**ok, "farbe": "rot"}]), plan([{"art": "rechteck", "x": 0, "y": 0, "b": 0, "h": 1}]),
        plan([{"art": "kreis", "x": 0, "y": 0, "r": -1}]), plan([{"art": "bogen", "x": 0, "y": 0, "r": 1, "von": 0, "bis": 4000}]),
        plan([{"art": "polylinie", "punkte": [[0, 0]]}]), plan([{"art": "polylinie", "punkte": [[0, 0]] * 201}]),
        plan([{"art": "polylinie", "punkte": [[0, 0], [1, 1]], "geschlossen": "ja"}]),
        plan([{"art": "text", "x": 0, "y": 0, "text": ""}]), plan([{"art": "text", "x": 0, "y": 0, "text": "x" * 81}]),
        plan([{"art": "text", "x": 0, "y": 0, "text": "x", "groesse": -1}]), plan([{"art": "mass", "von": [0, 0], "bis": [1, 1], "svg": "<svg onload=x>"}]),
        plan([ok], einheit="x" * 9),
    ]
    for view in bad:
        with pytest.raises(schema.ViewError) as e:
            schema.validate(view)
        assert e.value.code == "bad_block_1"


def test_p4a_text_in_scene_and_plan_loses_control_characters():
    tricky = "Küche" + chr(0x202e) + "xx" + chr(0) + chr(27)
    p = schema.validate(plan([{"art": "text", "x": 0, "y": 0, "text": tricky}]))["bausteine"][0]["elemente"][0]["text"]
    s = schema.validate(scene({"name": "s", "objekte": [{**BOX, "name": tricky}]}))["bausteine"][0]["szenen"][0]["objekte"][0]["name"]
    for text in (p, s):
        assert text.startswith("Küche") and all(ch.isprintable() for ch in text) and chr(0x202e) not in text


def test_zeige_tool_names_the_scene_and_plan_blocks():
    props = ch.ZEIGE_TOOL["inputSchema"]["properties"]
    assert {"modell", "plan"} <= set(props["art"]["enum"])
    assert {"szene3d", "plan2d"} <= set(props["bausteine"]["items"]["properties"]["typ"]["enum"])
    assert "szene3d" in props["bausteine"]["description"] and "plan2d" in props["bausteine"]["description"]
    assert "3D" in ch.INSTRUCTIONS and "Grundriss" in ch.INSTRUCTIONS and "Einheit" in ch.INSTRUCTIONS


# --- P6: Vergleich, Zeitstrahl, Gegenüberstellung, Lernen, Netz (docs/ui-p6-plan.md) -------------------

VERGLEICH = dict(optionen=["Bahn", "Auto"], kriterien=[{"name": "Kosten", "werte": [49, "120 €"]}, {"name": "Zeit", "werte": ["4 h", 3.5]}],
                 vorteile=[["entspannt"], []], nachteile=[[], ["Stau", "Parken"]], fazit="Bahn, wenn es keine Eile hat.")
ZEITSTRAHL = dict(ereignisse=[{"zeit": "1989", "titel": "Mauerfall"}, {"zeit": "März 2020", "titel": "Lockdown", "text": "Erste Welle"},
                              {"zeit": "1789", "titel": "Revolution"}], einheit="Jahre")
GEGENUEBER = dict(sprachen=["Deutsch", "Arabisch"], paare=[{"original": "Guten Morgen", "uebersetzung": "صباح الخير"}])
KARTEN = dict(karten=[{"frage": "Hauptstadt von Frankreich?", "antwort": "Paris"}])
QUIZ = dict(fragen=[{"frage": "2 + 2?", "optionen": ["3", "4", "5"], "richtig": 1, "erklaerung": "Zwei und zwei."},
                    {"frage": "Erde rund?", "optionen": ["ja", "nein"], "richtig": 0}])
ANLEITUNG = dict(schritte=[{"titel": "Wasser kochen", "text": "Einen Liter aufsetzen.", "sekunden": 300}, {"titel": "Aufgießen", "text": "Über den Tee."}])
KNOTEN = [{"id": "a", "text": "Start", "art": "start"}, {"id": "b", "text": "Prüfen", "art": "entscheidung"},
          {"id": "c", "text": "Ja-Weg"}, {"id": "d", "text": "Ende", "art": "ende"}]
KANTEN = [{"von": "a", "bis": "b"}, {"von": "b", "bis": "c", "text": "ja"}, {"von": "b", "bis": "d", "text": "nein"}]


def p6(typ, art="lernen", **fields):
    return {"id": "p6", "art": art, "titel": "T", "bausteine": [{"typ": typ, **fields}]}


def p6_block(typ, art="lernen", **fields):
    return schema.validate(p6(typ, art, **fields))["bausteine"][0]


def test_p6_blocks_pass_and_get_a_fixed_shape():
    b = p6_block("vergleich", "antwort", **VERGLEICH)
    assert b["optionen"] == ["Bahn", "Auto"] and b["kriterien"][0]["werte"] == [49, "120 €"] and b["nachteile"][1] == ["Stau", "Parken"]
    b = p6_block("vergleich", "recherche", optionen=["A", "B", "C"], kriterien=[{"name": "x", "werte": [1, 2, ""]}])
    assert b["vorteile"] == [[], [], []] and b["nachteile"] == [[], [], []] and b["fazit"] == ""
    b = p6_block("zeitstrahl", "antwort", **ZEITSTRAHL)
    assert [e["zeit"] for e in b["ereignisse"]] == ["1989", "März 2020", "1789"]                     # Reihenfolge wie geschickt
    assert b["ereignisse"][0]["text"] == "" and b["einheit"] == "Jahre"
    assert p6_block("zeitstrahl", "antwort", ereignisse=[{"zeit": "1", "titel": "t"}])["einheit"] == ""
    b = p6_block("gegenueber", "antwort", **GEGENUEBER)
    assert b == {"typ": "gegenueber", "sprachen": ["Deutsch", "Arabisch"], "paare": GEGENUEBER["paare"]}
    assert p6_block("lernkarten", **KARTEN) == {"typ": "lernkarten", "karten": KARTEN["karten"]}
    b = p6_block("quiz", **QUIZ)
    assert [f["richtig"] for f in b["fragen"]] == [1, 0] and b["fragen"][1]["erklaerung"] == ""
    b = p6_block("anleitung", **ANLEITUNG)
    assert b["aktuell"] == 0 and [s["sekunden"] for s in b["schritte"]] == [300, 0]
    assert p6_block("anleitung", aktuell=1, **ANLEITUNG)["aktuell"] == 1
    b = p6_block("netz", "netz", form="ablauf", knoten=KNOTEN, kanten=KANTEN)
    assert b["knoten"][2] == {"id": "c", "text": "Ja-Weg", "art": ""} and b["kanten"][0] == {"von": "a", "bis": "b", "text": ""}
    assert p6_block("netz", "netz", form="mindmap", knoten=[{"id": "mitte", "text": "Thema"}])["kanten"] == []
    for form in ("baum", "mindmap"):
        assert p6_block("netz", "netz", form=form, knoten=KNOTEN, kanten=KANTEN)["form"] == form
    loop = KANTEN + [{"von": "c", "bis": "a", "text": "nochmal"}]
    assert len(p6_block("netz", "netz", form="ablauf", knoten=KNOTEN, kanten=loop)["kanten"]) == 4        # Ablauf darf Kreise haben


@pytest.mark.parametrize("typ,fields", [("vergleich", VERGLEICH), ("zeitstrahl", ZEITSTRAHL), ("gegenueber", GEGENUEBER),
                                        ("lernkarten", KARTEN), ("quiz", QUIZ), ("anleitung", ANLEITUNG),
                                        ("netz", dict(form="baum", knoten=KNOTEN, kanten=KANTEN))])
def test_p6_checked_views_pass_the_second_check_unchanged(typ, fields):
    once = schema.validate(p6(typ, **fields))                                    # die Bridge prüft das Ergebnis des Channels erneut
    assert schema.validate(once) == once


def _tree(n):
    return dict(form="baum", knoten=[{"id": f"n{i}", "text": "x"} for i in range(n)], kanten=[{"von": "n0", "bis": f"n{i}"} for i in range(1, n)])


Q = {"frage": "f", "optionen": ["a", "b"], "richtig": 0}
S = {"titel": "t", "text": "x"}
K2 = [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}]
K3 = K2 + [{"id": "c", "text": "C"}]


@pytest.mark.parametrize("typ,fields", [
    # vergleich
    ("vergleich", {**VERGLEICH, "optionen": ["nur eine"], "kriterien": [{"name": "k", "werte": [1]}], "vorteile": [[]], "nachteile": [[]]}),
    ("vergleich", {"optionen": list("abcdef"), "kriterien": [{"name": "k", "werte": [1] * 6}]}),
    ("vergleich", {**VERGLEICH, "optionen": ["x" * 81, "b"]}),
    ("vergleich", {**VERGLEICH, "optionen": ["", "b"]}),
    ("vergleich", {**VERGLEICH, "optionen": "Bahn, Auto"}),
    ("vergleich", {**VERGLEICH, "kriterien": []}),
    ("vergleich", {**VERGLEICH, "kriterien": [{"name": "k", "werte": [1, 2]}] * 16}),
    ("vergleich", {**VERGLEICH, "kriterien": [{"name": "x" * 81, "werte": [1, 2]}]}),
    ("vergleich", {**VERGLEICH, "kriterien": [{"name": "k", "werte": [1]}]}),                          # werte: falsche Länge
    ("vergleich", {**VERGLEICH, "kriterien": [{"name": "k", "werte": [1, 2, 3]}]}),
    ("vergleich", {**VERGLEICH, "kriterien": [{"name": "k", "werte": ["x" * 201, 2]}]}),
    ("vergleich", {**VERGLEICH, "kriterien": [{"name": "k", "werte": [float("inf"), 2]}]}),
    ("vergleich", {**VERGLEICH, "kriterien": [{"name": "k", "werte": [float("-inf"), 2]}]}),
    ("vergleich", {**VERGLEICH, "kriterien": [{"name": "k", "werte": [1, float("nan")]}]}),
    ("vergleich", {**VERGLEICH, "kriterien": [{"name": "k", "werte": [True, 2]}]}),
    ("vergleich", {**VERGLEICH, "kriterien": [{"name": "k", "werte": [None, 2]}]}),
    ("vergleich", {**VERGLEICH, "kriterien": [{"name": "k", "werte": [1, 2], "farbe": "rot"}]}),
    ("vergleich", {**VERGLEICH, "vorteile": [["a"]]}),                                                   # äußere Länge falsch
    ("vergleich", {**VERGLEICH, "nachteile": [[], [], []]}),
    ("vergleich", {**VERGLEICH, "vorteile": [["a"] * 7, []]}),
    ("vergleich", {**VERGLEICH, "vorteile": [["x" * 201], []]}),
    ("vergleich", {**VERGLEICH, "vorteile": [[""], []]}),
    ("vergleich", {**VERGLEICH, "vorteile": ["a", "b"]}),
    ("vergleich", {**VERGLEICH, "fazit": "x" * 401}),
    ("vergleich", {**VERGLEICH, "fazit": 5}),
    ("vergleich", {**VERGLEICH, "empfehlung": "Bahn"}),
    # zeitstrahl
    ("zeitstrahl", {"ereignisse": []}),
    ("zeitstrahl", {"ereignisse": [{"zeit": "1", "titel": "t"}] * 41}),
    ("zeitstrahl", {"ereignisse": [{"zeit": "x" * 41, "titel": "t"}]}),
    ("zeitstrahl", {"ereignisse": [{"zeit": 1989, "titel": "t"}]}),
    ("zeitstrahl", {"ereignisse": [{"zeit": "1", "titel": "x" * 121}]}),
    ("zeitstrahl", {"ereignisse": [{"zeit": "1", "titel": ""}]}),
    ("zeitstrahl", {"ereignisse": [{"zeit": "1", "titel": "t", "text": "x" * 401}]}),
    ("zeitstrahl", {"ereignisse": [{"zeit": "1", "titel": "t", "bild": "x.png"}]}),
    ("zeitstrahl", {**ZEITSTRAHL, "einheit": "x" * 41}),
    ("zeitstrahl", {**ZEITSTRAHL, "sortiert": True}),
    # gegenueber
    ("gegenueber", {**GEGENUEBER, "sprachen": ["Deutsch"]}),
    ("gegenueber", {**GEGENUEBER, "sprachen": ["a", "b", "c"]}),
    ("gegenueber", {**GEGENUEBER, "sprachen": ["x" * 21, "b"]}),
    ("gegenueber", {**GEGENUEBER, "sprachen": ["", "b"]}),
    ("gegenueber", {**GEGENUEBER, "sprachen": "de-ar"}),
    ("gegenueber", {**GEGENUEBER, "paare": []}),
    ("gegenueber", {**GEGENUEBER, "paare": [{"original": "a", "uebersetzung": "b"}] * 41}),
    ("gegenueber", {**GEGENUEBER, "paare": [{"original": "x" * 601, "uebersetzung": "b"}]}),
    ("gegenueber", {**GEGENUEBER, "paare": [{"original": "a", "uebersetzung": "x" * 601}]}),
    ("gegenueber", {**GEGENUEBER, "paare": [{"original": "a"}]}),
    ("gegenueber", {**GEGENUEBER, "paare": [{"original": "a", "uebersetzung": "b", "dir": "rtl"}]}),
    ("gegenueber", {**GEGENUEBER, "richtung": "rtl"}),
    # lernkarten
    ("lernkarten", {"karten": []}),
    ("lernkarten", {"karten": [{"frage": "f", "antwort": "a"}] * 31}),
    ("lernkarten", {"karten": [{"frage": "x" * 401, "antwort": "a"}]}),
    ("lernkarten", {"karten": [{"frage": "f", "antwort": "x" * 401}]}),
    ("lernkarten", {"karten": [{"frage": "f"}]}),
    ("lernkarten", {"karten": [{"frage": "f", "antwort": 42}]}),
    ("lernkarten", {"karten": [{"frage": "f", "antwort": "a", "gewusst": True}]}),
    ("lernkarten", {"karten": ["f"]}),
    ("lernkarten", {**KARTEN, "speichern": True}),
    # quiz
    ("quiz", {"fragen": []}),
    ("quiz", {"fragen": [Q] * 21}),
    ("quiz", {"fragen": [{**Q, "frage": "x" * 301}]}),
    ("quiz", {"fragen": [{**Q, "optionen": ["a"]}]}),
    ("quiz", {"fragen": [{**Q, "optionen": list("abcdef")}]}),
    ("quiz", {"fragen": [{**Q, "optionen": ["x" * 201, "b"]}]}),
    ("quiz", {"fragen": [{**Q, "richtig": 2}]}),                                                         # zeigt auf keine Option
    ("quiz", {"fragen": [{**Q, "richtig": -1}]}),
    ("quiz", {"fragen": [{**Q, "richtig": True}]}),                                                      # bool ist keine Zahl
    ("quiz", {"fragen": [{**Q, "richtig": False}]}),
    ("quiz", {"fragen": [{**Q, "richtig": 1.0}]}),
    ("quiz", {"fragen": [{**Q, "richtig": "1"}]}),
    ("quiz", {"fragen": [{"frage": "f", "optionen": ["a", "b"]}]}),
    ("quiz", {"fragen": [{**Q, "erklaerung": "x" * 401}]}),
    ("quiz", {"fragen": [{**Q, "punkte": 3}]}),
    ("quiz", {**QUIZ, "ergebnis": 2}),
    # anleitung
    ("anleitung", {"schritte": []}),
    ("anleitung", {"schritte": [S] * 31}),
    ("anleitung", {"schritte": [{**S, "titel": "x" * 121}]}),
    ("anleitung", {"schritte": [{**S, "text": "x" * 601}]}),
    ("anleitung", {"schritte": [{"titel": "t"}]}),
    ("anleitung", {"schritte": [{**S, "sekunden": 86401}]}),
    ("anleitung", {"schritte": [{**S, "sekunden": -5}]}),
    ("anleitung", {"schritte": [{**S, "sekunden": 1.5}]}),
    ("anleitung", {"schritte": [{**S, "sekunden": True}]}),
    ("anleitung", {"schritte": [{**S, "sekunden": False}]}),
    ("anleitung", {"schritte": [{**S, "sekunden": "60"}]}),
    ("anleitung", {"schritte": [{**S, "sekunden": float("nan")}]}),
    ("anleitung", {"schritte": [{**S, "sekunden": None}]}),
    ("anleitung", {"schritte": [{**S, "sekunden": 10**400}]}),
    ("anleitung", {"schritte": [{**S, "sekunden": 0.0}]}),                                               # nur echte ganze Zahlen
    ("anleitung", {"schritte": [{**S, "sekunden": 60.0}]}),
    ("anleitung", {"schritte": [{**S, "ton": "gong"}]}),
    ("anleitung", {"schritte": [S, S], "aktuell": 2}),                                                   # kein dritter Schritt
    ("anleitung", {"schritte": [S], "aktuell": -1}),
    ("anleitung", {"schritte": [S], "aktuell": True}),
    ("anleitung", {"schritte": [S], "aktuell": 0.0}),
    ("anleitung", {"schritte": [S], "aktuell": None}),
    ("anleitung", {**ANLEITUNG, "autoplay": True}),
    # netz
    ("netz", {"form": "kreis", "knoten": K2, "kanten": []}),
    ("netz", {"knoten": K2, "kanten": []}),
    ("netz", {"form": "ablauf", "knoten": []}),
    ("netz", {"form": "ablauf", "knoten": [{"id": f"n{i}", "text": "x"} for i in range(61)]}),
    ("netz", {"form": "ablauf", "knoten": [{"id": "A", "text": "x"}]}),
    ("netz", {"form": "ablauf", "knoten": [{"id": "x" * 25, "text": "x"}]}),
    ("netz", {"form": "ablauf", "knoten": [{"id": "", "text": "x"}]}),
    ("netz", {"form": "ablauf", "knoten": [{"id": "a b", "text": "x"}]}),
    ("netz", {"form": "ablauf", "knoten": [{"id": 1, "text": "x"}]}),
    ("netz", {"form": "ablauf", "knoten": [{"id": "a", "text": "x"}, {"id": "a", "text": "y"}]}),       # doppelte id
    ("netz", {"form": "ablauf", "knoten": [{"id": "a", "text": "x" * 81}]}),
    ("netz", {"form": "ablauf", "knoten": [{"id": "a", "text": ""}]}),
    ("netz", {"form": "ablauf", "knoten": [{"id": "a", "text": "x", "art": "raute"}]}),
    ("netz", {"form": "ablauf", "knoten": [{"id": "a", "text": "x", "farbe": "rot"}]}),
    ("netz", {"form": "ablauf", "knoten": [{"id": "a", "text": "x", "art": None}]}),
    ("netz", {"form": "ablauf", "knoten": [{"id": "a", "text": "x", "art": []}]}),
    ("netz", {"form": "ablauf", "knoten": K2, "kanten": None}),
    ("netz", {"form": "ablauf", "knoten": K2, "kanten": [{"von": "a", "bis": "z"}]}),                    # Kante ins Leere
    ("netz", {"form": "ablauf", "knoten": K2, "kanten": [{"von": "z", "bis": "a"}]}),
    ("netz", {"form": "ablauf", "knoten": K2, "kanten": [{"von": ["a"], "bis": "b"}]}),
    ("netz", {"form": "ablauf", "knoten": K2, "kanten": [{"von": "a"}]}),
    ("netz", {"form": "ablauf", "knoten": K2, "kanten": [{"von": "a", "bis": "a"}]}),                    # Schleife auf sich selbst
    ("netz", {"form": "ablauf", "knoten": K2, "kanten": [{"von": "a", "bis": "b", "text": "x" * 41}]}),
    ("netz", {"form": "ablauf", "knoten": K2, "kanten": [{"von": "a", "bis": "b", "stil": "dick"}]}),
    ("netz", {"form": "ablauf", "knoten": K2, "kanten": [{"von": "a", "bis": "b"}] * 121}),
    ("netz", {"form": "ablauf", "knoten": K2, "kanten": [], "layout": "dagre"}),
    ("netz", {"form": "baum", "knoten": K2, "kanten": []}),                                              # zwei Wurzeln
    ("netz", {"form": "baum", "knoten": K3, "kanten": [{"von": "a", "bis": "b"}]}),
    ("netz", {"form": "baum", "knoten": K2, "kanten": [{"von": "a", "bis": "b"}, {"von": "b", "bis": "a"}]}),      # Kreis, keine Wurzel
    ("netz", {"form": "baum", "knoten": K3, "kanten": [{"von": "a", "bis": "c"}, {"von": "b", "bis": "c"}]}),      # zwei Eltern
    ("netz", {"form": "baum", "knoten": K2, "kanten": [{"von": "a", "bis": "b"}, {"von": "a", "bis": "b"}]}),
    ("netz", {"form": "baum", "knoten": K3 + [{"id": "d", "text": "D"}],
              "kanten": [{"von": "a", "bis": "b"}, {"von": "c", "bis": "d"}, {"von": "d", "bis": "c"}]}),             # Kreis abseits der Wurzel
    ("netz", {"form": "mindmap", "knoten": K2, "kanten": []}),
    ("netz", {"form": "mindmap", "knoten": K3, "kanten": [{"von": "a", "bis": "c"}, {"von": "b", "bis": "c"}]}),
])
def test_p6_rejections(typ, fields):
    with pytest.raises(schema.ViewError) as e:
        schema.validate(p6(typ, **fields))
    assert e.value.code == "bad_block_1"


@pytest.mark.parametrize("typ,fields", [
    ("vergleich", {"optionen": ["x" * 80] * 5, "kriterien": [{"name": "x" * 80, "werte": ["x" * 200] * 5}] * 15,
                   "vorteile": [["x" * 200] * 6] * 5, "fazit": "x" * 400}),
    ("zeitstrahl", {"ereignisse": [{"zeit": "x" * 40, "titel": "x" * 120, "text": "x" * 400}] * 40, "einheit": "x" * 40}),
    ("gegenueber", {"sprachen": ["x" * 20] * 2, "paare": [{"original": "x" * 600, "uebersetzung": "x" * 600}] * 10}),
    ("lernkarten", {"karten": [{"frage": "x" * 400, "antwort": "x" * 400}] * 30}),
    ("quiz", {"fragen": [{"frage": "x" * 300, "optionen": ["x" * 200] * 5, "richtig": 4, "erklaerung": "x" * 400}] * 20}),
    ("anleitung", {"schritte": [{"titel": "x" * 120, "text": "x" * 300, "sekunden": 86400}] * 30, "aktuell": 29}),
    ("anleitung", {"schritte": [{"titel": "t", "text": "x", "sekunden": 1}]}),
    ("netz", {"form": "ablauf", "knoten": [{"id": f"k{i:022d}", "text": "x" * 80} for i in range(60)],
              "kanten": [{"von": f"k{i % 60:022d}", "bis": f"k{(i + 1) % 60:022d}", "text": "x" * 40} for i in range(120)]}),
    ("netz", _tree(60)),
    ("gegenueber", {"sprachen": ["de", "en"], "paare": [{"original": "Hallo", "uebersetzung": "Hello"}] * 40}),
    ("netz", {"form": "ablauf", "knoten": [{"id": "a", "text": "x", "art": ""}]}),
    ("netz", {"form": "ablauf", "knoten": K2}),                                                          # ohne kanten
])
def test_p6_limits_are_inclusive(typ, fields):
    assert schema.validate(p6(typ, **fields))["bausteine"][0]["typ"] == typ


def test_p6_forty_long_pairs_are_too_large_for_one_view():
    with pytest.raises(schema.ViewError) as e:
        schema.validate(p6("gegenueber", sprachen=["de", "en"], paare=[{"original": "x" * 600, "uebersetzung": "y" * 600}] * 40))
    assert e.value.code == "too_large"


def test_p6_empty_or_control_only_cells_in_werte_become_empty_like_in_tabelle():
    werte = p6_block("vergleich", "antwort", optionen=["a", "b"], kriterien=[{"name": "k", "werte": ["", chr(0x202e) + chr(0)]}])["kriterien"][0]["werte"]
    assert werte == ["", ""]
    assert p6_block("tabelle", "antwort", spalten=["a", "b"], zeilen=[["", chr(0x202e) + chr(0)]])["zeilen"][0] == ["", ""]


JUNK = chr(0x202e) + chr(0) + chr(27) + chr(0x2066) + chr(10)
V2 = dict(optionen=["a", "b"], kriterien=[{"name": "k", "werte": [1, 2]}])


@pytest.mark.parametrize("typ,fields", [
    ("vergleich", {**V2, "optionen": [JUNK, "b"]}),
    ("vergleich", {**V2, "kriterien": [{"name": JUNK, "werte": [1, 2]}]}),
    ("vergleich", {**V2, "vorteile": [[JUNK], []]}),
    ("zeitstrahl", {"ereignisse": [{"zeit": JUNK, "titel": "t"}]}),
    ("zeitstrahl", {"ereignisse": [{"zeit": "1", "titel": JUNK}]}),
    ("gegenueber", {"sprachen": [JUNK, "b"], "paare": [{"original": "a", "uebersetzung": "b"}]}),
    ("gegenueber", {"sprachen": ["a", "b"], "paare": [{"original": JUNK, "uebersetzung": "b"}]}),
    ("gegenueber", {"sprachen": ["a", "b"], "paare": [{"original": "a", "uebersetzung": JUNK}]}),
    ("lernkarten", {"karten": [{"frage": JUNK, "antwort": "a"}]}),
    ("lernkarten", {"karten": [{"frage": "f", "antwort": JUNK}]}),
    ("quiz", {"fragen": [{**Q, "frage": JUNK}]}),
    ("quiz", {"fragen": [{**Q, "optionen": ["a", JUNK]}]}),
    ("anleitung", {"schritte": [{"titel": JUNK, "text": "x"}]}),
    ("anleitung", {"schritte": [{"titel": "t", "text": JUNK}]}),
    ("netz", {"form": "ablauf", "knoten": [{"id": "a", "text": JUNK}]}),
])
def test_p6_required_text_of_only_control_or_direction_characters_is_rejected(typ, fields):
    with pytest.raises(schema.ViewError) as e:
        schema.validate(p6(typ, **fields))
    assert e.value.code == "bad_block_1"


def _deep(n=5000):
    v: list = []
    for _ in range(n):
        v = [v]
    return v


@pytest.mark.parametrize("view", [
    lambda: p6("text", "antwort", absaetze=_deep()),
    lambda: p6("quiz", fragen=_deep()),
    lambda: {**p6("netz", "netz", form="ablauf", knoten=K2), "bausteine": _deep()},
    lambda: {"id": "x", "art": "antwort", "titel": "T", "bausteine": [{"typ": "text", "absaetze": ["a"]}], "tief": _deep()},
])
def test_deeply_nested_input_is_a_view_error_not_a_crash(view):
    with pytest.raises(schema.ViewError) as e:
        schema.validate(view())
    assert e.value.code == "too_large"


@pytest.mark.parametrize("fields", [
    _tree(60),                                                                                           # Stern
    dict(form="baum", knoten=[{"id": f"n{i}", "text": "x"} for i in range(60)], kanten=[{"von": f"n{i}", "bis": f"n{i + 1}"} for i in range(59)]),
    dict(form="ablauf", knoten=[{"id": f"n{i}", "text": "x"} for i in range(60)],
         kanten=[{"von": f"n{i % 60}", "bis": f"n{(i * 7 + 1) % 60}"} for i in range(120) if i % 60 != (i * 7 + 1) % 60]),
])
def test_p6_netz_checks_stay_fast(fields):
    import time
    start = time.perf_counter()
    for _ in range(10):
        schema.validate(p6("netz", "netz", **fields))
    assert time.perf_counter() - start < 0.5


def test_p6_text_loses_control_and_direction_characters():
    tricky = "Paris" + chr(0x202e) + "sirap" + chr(0x2066) + chr(0) + chr(27) + "[31m" + chr(10) + "Ende"
    texts = [p6_block("lernkarten", karten=[{"frage": tricky, "antwort": tricky}])["karten"][0]["antwort"],
             p6_block("gegenueber", "antwort", sprachen=[tricky[:12], "b"], paare=[{"original": tricky, "uebersetzung": "x"}])["paare"][0]["original"],
             p6_block("quiz", fragen=[{"frage": tricky, "optionen": [tricky, "b"], "richtig": 0}])["fragen"][0]["optionen"][0],
             p6_block("netz", "netz", form="ablauf", knoten=[{"id": "a", "text": tricky}])["knoten"][0]["text"],
             p6_block("zeitstrahl", "antwort", ereignisse=[{"zeit": "1", "titel": tricky}])["ereignisse"][0]["titel"],
             p6_block("vergleich", "antwort", optionen=[tricky, "b"], kriterien=[{"name": "k", "werte": [tricky, 1]}])["kriterien"][0]["werte"][0],
             p6_block("anleitung", schritte=[{"titel": "t", "text": tricky}])["schritte"][0]["text"]]
    for text in texts:
        assert text.startswith("Paris") and text.endswith("Ende") and all(c.isprintable() for c in text)
        assert chr(0x202e) not in text and chr(0x2066) not in text and chr(10) not in text and chr(27) not in text
    with pytest.raises(schema.ViewError):                                       # nur Steuerzeichen: leer, also abgelehnt
        schema.validate(p6("lernkarten", karten=[{"frage": chr(0x202e) + chr(0), "antwort": "a"}]))


# --- P5a: Simulation mit festen Modellen (docs/ui-p5-plan.md) ------------------------------------------

SIM_MIN = {
    "pendel": {"laenge": 1, "winkel": 30},
    "feder": {"masse": 1, "federkonstante": 10, "auslenkung": 0.2},
    "wurf": {"geschwindigkeit": 20, "winkel": 45},
    "umlauf": {"zentralmasse": 1, "koerper": [{"name": "Erde", "abstand": 1}]},
    "gas": {"anzahl": 50, "kasten": [100, 60], "radius": 1, "geschwindigkeit": 0.5},
}
SIM_FILLED = {                                                                    # was die Oberfläche aus SIM_MIN bekommt
    "pendel": {"laenge": 1, "winkel": 30, "anfangsgeschwindigkeit": 0, "daempfung": 0, "g": 9.81},
    "feder": {"masse": 1, "federkonstante": 10, "auslenkung": 0.2, "daempfung": 0},
    "wurf": {"geschwindigkeit": 20, "winkel": 45, "hoehe": 0, "g": 9.81, "luftwiderstand": 0},
    "umlauf": {"zentralmasse": 1, "koerper": [{"name": "Erde", "abstand": 1, "exzentrizitaet": 0, "phase": 0, "farbe": "arc"}]},
    "gas": {"anzahl": 50, "kasten": [100, 60], "radius": 1, "geschwindigkeit": 0.5, "schwerkraft": 0, "stoesse": True, "startwert": 1},
}
SIM_FULL = {
    "pendel": {"laenge": 2.5, "winkel": -45, "anfangsgeschwindigkeit": 90, "daempfung": 0.2, "g": 1.62},
    "feder": {"masse": 0.5, "federkonstante": 200, "auslenkung": -0.1, "daempfung": 1.5},
    "wurf": {"geschwindigkeit": 30, "winkel": -10, "hoehe": 50, "g": 9.81, "luftwiderstand": 0.01},
    "umlauf": {"zentralmasse": 1, "koerper": [{"name": "Merkur", "abstand": 0.39, "exzentrizitaet": 0.21, "phase": 10, "farbe": "amber"},
                                               {"name": "Erde", "abstand": 1, "exzentrizitaet": 0.017, "phase": 200, "farbe": "ok"},
                                               {"name": "Mars", "abstand": 1.52, "exzentrizitaet": 0.09, "phase": 359.5, "farbe": "alarm"}]},
    "gas": {"anzahl": 120, "kasten": [200, 100], "radius": 1.5, "geschwindigkeit": 2, "schwerkraft": 9.81, "stoesse": False,
            "startwert": 42},
}


def sim(modell, parameter, art="simulation", **extra):
    return {"id": "sim", "art": art, "titel": "T", "bausteine": [{"typ": "simulation", "modell": modell, "parameter": parameter, **extra}]}


def sim_block(modell, parameter, **extra):
    return schema.validate(sim(modell, parameter, **extra))["bausteine"][0]


def sim_bad(modell, parameter, **extra):
    with pytest.raises(schema.ViewError) as e:
        schema.validate(sim(modell, parameter, **extra))
    assert e.value.code == "bad_block_1"


@pytest.mark.parametrize("modell", list(SIM_MIN))
def test_p5a_minimal_simulation_gets_every_default(modell):
    assert sim_block(modell, SIM_MIN[modell]) == {"typ": "simulation", "modell": modell, "parameter": SIM_FILLED[modell],
                                                  "laufzeit": 30, "tempo": 0, "spur": True, "beschreibung": ""}


@pytest.mark.parametrize("modell", list(SIM_FULL))
def test_p5a_full_simulation_keeps_every_value(modell):
    b = sim_block(modell, SIM_FULL[modell], laufzeit=60, tempo=2.5, spur=False, beschreibung="Ohne Reibung.")
    assert b == {"typ": "simulation", "modell": modell, "parameter": SIM_FULL[modell], "laufzeit": 60, "tempo": 2.5, "spur": False,
                 "beschreibung": "Ohne Reibung."}


@pytest.mark.parametrize("art", ["antwort", "lernen", "recherche", "modell"])
def test_p5a_simulation_block_works_in_every_kind(art):
    assert schema.validate(sim("pendel", SIM_MIN["pendel"], art=art))["bausteine"][0]["modell"] == "pendel"


@pytest.mark.parametrize("modell", list(SIM_MIN))
@pytest.mark.parametrize("extra", [{}, {"laufzeit": 5, "tempo": 100, "spur": False, "beschreibung": "x" * 400}])
def test_p5a_checked_simulations_pass_the_second_check_unchanged(modell, extra):
    for params in (SIM_MIN[modell], SIM_FULL[modell]):
        once = schema.validate(sim(modell, params, **extra))
        assert schema.validate(once) == once


SIM_EDGES = [  # (modell, Änderung gegenüber SIM_MIN, gültig)
    ("pendel", {"laenge": 0.05}, True), ("pendel", {"laenge": 100}, True), ("pendel", {"laenge": 0.0499}, False), ("pendel", {"laenge": 100.01}, False),
    ("pendel", {"winkel": -170}, True), ("pendel", {"winkel": 170}, True), ("pendel", {"winkel": -170.01}, False), ("pendel", {"winkel": 170.01}, False),
    ("pendel", {"anfangsgeschwindigkeit": -720}, True), ("pendel", {"anfangsgeschwindigkeit": 720}, True),
    ("pendel", {"anfangsgeschwindigkeit": -720.1}, False), ("pendel", {"anfangsgeschwindigkeit": 720.1}, False),
    ("pendel", {"daempfung": 0}, True), ("pendel", {"daempfung": 5}, True), ("pendel", {"daempfung": -0.001}, False), ("pendel", {"daempfung": 5.001}, False),
    ("pendel", {"g": 0.1}, True), ("pendel", {"g": 100}, True), ("pendel", {"g": 0.099}, False), ("pendel", {"g": 100.1}, False),
    ("feder", {"masse": 0.001}, True), ("feder", {"masse": 1000}, True), ("feder", {"masse": 0.00099}, False), ("feder", {"masse": 1000.1}, False),
    ("feder", {"federkonstante": 0.001}, True), ("feder", {"federkonstante": 1_000_000, "masse": 1000}, True),
    ("feder", {"federkonstante": 0.00099}, False), ("feder", {"federkonstante": 1_000_001, "masse": 1000}, False),
    ("feder", {"auslenkung": -10}, True), ("feder", {"auslenkung": 10}, True), ("feder", {"auslenkung": -10.01}, False), ("feder", {"auslenkung": 10.01}, False),
    ("feder", {"daempfung": 0}, True), ("feder", {"daempfung": 10_000}, True), ("feder", {"daempfung": -0.1}, False), ("feder", {"daempfung": 10_000.1}, False),
    ("feder", {"masse": 0.001, "federkonstante": 15}, True),                       # Schwingungsdauer 0,0513 s
    ("feder", {"masse": 0.001, "federkonstante": 16}, False),                      # 0,0497 s: zu kurz
    ("feder", {"masse": 0.001, "federkonstante": 1_000_000}, False),               # 0,0002 s
    ("feder", {"masse": 1000, "federkonstante": 0.04}, True),                      # 993 s
    ("feder", {"masse": 1000, "federkonstante": 0.039}, False),                    # 1006 s: zu lang
    ("feder", {"masse": 1000, "federkonstante": 0.001}, False),                    # 6283 s
    ("wurf", {"geschwindigkeit": 0.1}, True), ("wurf", {"geschwindigkeit": 1000}, True),
    ("wurf", {"geschwindigkeit": 0.099}, False), ("wurf", {"geschwindigkeit": 1000.1}, False),
    ("wurf", {"winkel": 90}, True), ("wurf", {"winkel": -90, "hoehe": 10}, True), ("wurf", {"winkel": 90.1}, False),
    ("wurf", {"winkel": -90.1, "hoehe": 10}, False),
    ("wurf", {"hoehe": 10_000}, True), ("wurf", {"hoehe": -0.1}, False), ("wurf", {"hoehe": 10_000.1}, False),
    ("wurf", {"g": 0.1}, True), ("wurf", {"g": 100}, True), ("wurf", {"g": 0.099}, False), ("wurf", {"g": 100.1}, False),
    ("wurf", {"luftwiderstand": 0}, True), ("wurf", {"luftwiderstand": 1}, True), ("wurf", {"luftwiderstand": -0.01}, False),
    ("wurf", {"luftwiderstand": 1.01}, False),
    ("wurf", {"hoehe": 0, "winkel": 0.001}, True), ("wurf", {"hoehe": 0, "winkel": 0}, False), ("wurf", {"hoehe": 0, "winkel": -10}, False),
    ("wurf", {"hoehe": 0.0, "winkel": 0.0}, False), ("wurf", {"winkel": -1}, False),                     # ohne hoehe gilt 0
    ("wurf", {"hoehe": 0.5, "winkel": 0}, True), ("wurf", {"hoehe": 0.5, "winkel": -90}, True),
    ("umlauf", {"zentralmasse": 0.01}, True), ("umlauf", {"zentralmasse": 100}, True), ("umlauf", {"zentralmasse": 0.0099}, False),
    ("umlauf", {"zentralmasse": 100.1}, False),
    ("umlauf", {"koerper": [{"name": "a", "abstand": 0.01}]}, True), ("umlauf", {"koerper": [{"name": "a", "abstand": 1000}]}, True),
    ("umlauf", {"koerper": [{"name": "a", "abstand": 0.0099}]}, False), ("umlauf", {"koerper": [{"name": "a", "abstand": 1000.1}]}, False),
    ("umlauf", {"koerper": [{"name": "a", "abstand": 1, "exzentrizitaet": 0.95}]}, True),
    ("umlauf", {"koerper": [{"name": "a", "abstand": 1, "exzentrizitaet": 0.951}]}, False),
    ("umlauf", {"koerper": [{"name": "a", "abstand": 1, "exzentrizitaet": -0.01}]}, False),
    ("umlauf", {"koerper": [{"name": "a", "abstand": 1, "phase": 360}]}, True),
    ("umlauf", {"koerper": [{"name": "a", "abstand": 1, "phase": 360.1}]}, False),
    ("umlauf", {"koerper": [{"name": "a", "abstand": 1, "phase": -0.1}]}, False),
    ("umlauf", {"koerper": [{"name": "x" * 30, "abstand": 1}]}, True), ("umlauf", {"koerper": [{"name": "x" * 31, "abstand": 1}]}, False),
    ("umlauf", {"koerper": [{"name": "", "abstand": 1}]}, False), ("umlauf", {"koerper": [{"name": chr(0x202e), "abstand": 1}]}, False),
    ("umlauf", {"koerper": [{"abstand": 1}]}, False), ("umlauf", {"koerper": [{"name": "a"}]}, False),
    ("umlauf", {"koerper": [{"name": "a", "abstand": 1}, {"name": "b", "abstand": 100}]}, True),          # Verhältnis genau 100
    ("umlauf", {"koerper": [{"name": "a", "abstand": 0.01}, {"name": "b", "abstand": 1}]}, True),
    ("umlauf", {"koerper": [{"name": "a", "abstand": 1}, {"name": "b", "abstand": 100.1}]}, False),
    ("umlauf", {"koerper": [{"name": "a", "abstand": 0.01}, {"name": "b", "abstand": 1000}]}, False),
    ("umlauf", {"koerper": [{"name": f"k{i}", "abstand": 1 + i} for i in range(8)]}, True),
    ("umlauf", {"koerper": [{"name": f"k{i}", "abstand": 1 + i} for i in range(9)]}, False),
    ("umlauf", {"koerper": []}, False), ("umlauf", {"koerper": {"name": "a", "abstand": 1}}, False), ("umlauf", {"koerper": ["Erde"]}, False),
    ("umlauf", {"koerper": [{"name": "Erde", "abstand": 1}, {"name": "Erde", "abstand": 2}]}, False),
    ("umlauf", {"koerper": [{"name": "Erde", "abstand": 1}, {"name": " Erde" + chr(10), "abstand": 2}]}, False),   # gleich nach dem Säubern
    ("umlauf", {"koerper": [{"name": "Neuer Mond", "abstand": 1}, {"name": "Neuer" + chr(9) + " Mond", "abstand": 2}]}, False),
    ("umlauf", {"koerper": [{"name": "Erde", "abstand": 1}, {"name": "erde", "abstand": 2}]}, True),
    ("umlauf", {"koerper": [{"name": "a", "abstand": 1, "masse": 5}]}, False),
    ("gas", {"anzahl": 2}, True), ("gas", {"anzahl": 300}, True), ("gas", {"anzahl": 1}, False), ("gas", {"anzahl": 301}, False),
    ("gas", {"anzahl": 50.0}, False), ("gas", {"anzahl": True}, False), ("gas", {"anzahl": "50"}, False),
    ("gas", {"kasten": [1, 1], "radius": 0.05, "anzahl": 2}, True), ("gas", {"kasten": [1000, 1000]}, True),
    ("gas", {"kasten": [0.99, 1], "radius": 0.01}, False), ("gas", {"kasten": [1000.1, 1000]}, False),
    ("gas", {"kasten": [100, 1000]}, True), ("gas", {"kasten": [1000, 100]}, True),                         # Seitenverhältnis genau 10
    ("gas", {"kasten": [99.9, 1000]}, False), ("gas", {"kasten": [10, 101], "radius": 0.1}, False),        # über 10
    ("gas", {"kasten": [100]}, False), ("gas", {"kasten": [100, 60, 10]}, False), ("gas", {"kasten": "100x60"}, False),
    ("gas", {"kasten": [100, "60"]}, False),
    ("gas", {"radius": 3}, True), ("gas", {"radius": 3.01}, False), ("gas", {"radius": 0}, False), ("gas", {"radius": -1}, False),   # 5 % von 60 = 3
    ("gas", {"radius": 0.0001}, True),
    ("gas", {"anzahl": 63, "radius": 3}, True),                                    # 1781 von 1800 Flächeneinheiten
    ("gas", {"anzahl": 64, "radius": 3}, False),                                   # 1810: Kasten zu voll
    ("gas", {"anzahl": 300, "radius": 3}, False),
    ("gas", {"geschwindigkeit": 10}, True), ("gas", {"geschwindigkeit": 0.001}, True), ("gas", {"geschwindigkeit": 0}, False),
    ("gas", {"geschwindigkeit": 10.01}, False), ("gas", {"geschwindigkeit": -1}, False),
    ("gas", {"schwerkraft": 0}, True), ("gas", {"schwerkraft": 100}, True), ("gas", {"schwerkraft": -0.1}, False), ("gas", {"schwerkraft": 100.1}, False),
    ("gas", {"stoesse": False}, True), ("gas", {"stoesse": "ja"}, False), ("gas", {"stoesse": 1}, False), ("gas", {"stoesse": None}, False),
    ("gas", {"startwert": 0}, True), ("gas", {"startwert": 2_147_483_647}, True), ("gas", {"startwert": -1}, False),
    ("gas", {"startwert": 2_147_483_648}, False), ("gas", {"startwert": 1.0}, False), ("gas", {"startwert": True}, False),
    ("gas", {"startwert": "1"}, False),
]


@pytest.mark.parametrize("modell,change,ok", SIM_EDGES)
def test_p5a_limits_just_inside_pass_and_just_outside_are_rejected(modell, change, ok):
    params = {**SIM_MIN[modell], **change}
    if ok:
        got = sim_block(modell, params)["parameter"]
        if modell != "umlauf":
            assert got == {**SIM_FILLED[modell], **change}
        else:
            assert len(got["koerper"]) == len(params["koerper"]) and got["zentralmasse"] == params["zentralmasse"]
    else:
        sim_bad(modell, params)


@pytest.mark.parametrize("extra,ok", [
    ({"laufzeit": 5}, True), ({"laufzeit": 60}, True), ({"laufzeit": 4.9}, False), ({"laufzeit": 60.1}, False), ({"laufzeit": "30"}, False),
    ({"tempo": 0}, True), ({"tempo": 0.0}, True), ({"tempo": 0.1}, True), ({"tempo": 100}, True), ({"tempo": 0.05}, False),
    ({"tempo": 100.1}, False), ({"tempo": -1}, False), ({"tempo": None}, False),
    ({"spur": False}, True), ({"spur": "ja"}, False), ({"spur": 0}, False),
    ({"beschreibung": "x" * 400}, True), ({"beschreibung": "x" * 401}, False), ({"beschreibung": 5}, False),
    ({"formel": "sin(x)"}, False), ({"code": "while(1){}"}, False), ({"regler": ["laenge"]}, False),
])
def test_p5a_block_fields_have_limits(extra, ok):
    if ok:
        assert sim_block("pendel", SIM_MIN["pendel"], **extra)["modell"] == "pendel"
    else:
        sim_bad("pendel", SIM_MIN["pendel"], **extra)


@pytest.mark.parametrize("modell", ["doppelpendel", "welle", "teilchen", "Pendel", "", None, 5, True, ["pendel"], {"pendel": 1}])
def test_p5a_unknown_models_are_rejected(modell):
    sim_bad(modell, SIM_MIN["pendel"])


@pytest.mark.parametrize("parameter", [None, [], ["laenge", 1], "laenge=1", 1, True])
def test_p5a_parameter_must_be_an_object(parameter):
    sim_bad("pendel", parameter)
    with pytest.raises(schema.ViewError):
        schema.validate({"id": "s", "art": "simulation", "titel": "T", "bausteine": [{"typ": "simulation", "modell": "pendel"}]})


@pytest.mark.parametrize("modell", list(SIM_MIN))
@pytest.mark.parametrize("extra", [{"formel": "sin(x)"}, {"code": "x"}, {"Laenge": 1}, {"masse_2": 1}])
def test_p5a_unknown_parameters_are_rejected(modell, extra):
    sim_bad(modell, {**SIM_MIN[modell], **extra})


@pytest.mark.parametrize("modell,field", [(m, f) for m, p in SIM_MIN.items() for f in p])
def test_p5a_missing_required_parameters_are_rejected(modell, field):
    sim_bad(modell, {k: v for k, v in SIM_MIN[modell].items() if k != field})
    sim_bad(modell, {**SIM_MIN[modell], field: None})


def _sim_numeric_fields():
    for m, spec in schema.SIM_ZAHLEN.items():
        for f in spec:
            yield lambda v, m=m, f=f: sim(m, {**SIM_MIN[m], f: v})
    for f in schema.SIM_KOERPER:
        yield lambda v, f=f: sim("umlauf", {"zentralmasse": 1, "koerper": [{"name": "a", "abstand": 1, f: v}]})
    for f in ("anzahl", "radius", "geschwindigkeit", "schwerkraft", "startwert"):
        yield lambda v, f=f: sim("gas", {**SIM_MIN["gas"], f: v})
    yield lambda v: sim("gas", {**SIM_MIN["gas"], "kasten": [v, 60]})
    yield lambda v: sim("pendel", SIM_MIN["pendel"], laufzeit=v)
    yield lambda v: sim("pendel", SIM_MIN["pendel"], tempo=v)


SIM_NUMERIC = list(_sim_numeric_fields())


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 10**400, -10**400, True, False, "1", None, [1]])
@pytest.mark.parametrize("make", SIM_NUMERIC)
def test_p5a_non_finite_and_non_numbers_are_rejected_everywhere(make, value):
    with pytest.raises(schema.ViewError) as e:
        schema.validate(make(value))
    assert e.value.code == "bad_block_1"


@pytest.mark.parametrize("farbe", list(schema.PALETTE))
def test_p5a_every_palette_colour_passes(farbe):
    assert sim_block("umlauf", {"zentralmasse": 1, "koerper": [{"name": "a", "abstand": 1, "farbe": farbe}]})["parameter"]["koerper"][0]["farbe"] == farbe


@pytest.mark.parametrize("farbe", ["rot", "#ff0000", "", None, 5, True, ["arc"], {"arc": 1}, "ARC"])
def test_p5a_bad_colours_are_rejected(farbe):
    sim_bad("umlauf", {"zentralmasse": 1, "koerper": [{"name": "a", "abstand": 1, "farbe": farbe}]})


def test_p5a_body_names_lose_control_characters():
    b = sim_block("umlauf", {"zentralmasse": 1, "koerper": [{"name": "Erde" + chr(0x202e) + chr(0) + "x", "abstand": 1}]})
    name = b["parameter"]["koerper"][0]["name"]
    assert name.startswith("Erde") and all(ch.isprintable() for ch in name) and chr(0x202e) not in name


def test_zeige_tool_names_the_simulation_kind_block_and_models():
    props = ch.ZEIGE_TOOL["inputSchema"]["properties"]
    assert "simulation" in props["art"]["enum"] and "simulation" in props["bausteine"]["items"]["properties"]["typ"]["enum"]
    desc = props["bausteine"]["description"]
    for name in ("pendel", "feder", "wurf", "umlauf", "gas", "laenge", "federkonstante", "auslenkung", "geschwindigkeit", "zentralmasse",
                 "koerper", "abstand", "exzentrizitaet", "kasten", "radius", "stoesse", "startwert", "laufzeit", "tempo", "spur"):
        assert name in desc
    assert "keine Formeln" in desc and "keine Formeln" in ch.ZEIGE_TOOL["description"] and "keine Messung" in ch.ZEIGE_TOOL["description"]
    assert all(m in ch.INSTRUCTIONS for m in ("simulation", "pendel", "feder", "wurf", "umlauf", "gas"))
    assert "nie Formeln oder Code" in ch.INSTRUCTIONS and "keine Messung" in ch.INSTRUCTIONS


def test_p5a_simulation_is_listed_by_tools_list_and_travels_through_the_real_channel_into_the_bridge_store(channel):
    c, out, root = channel
    c.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    zeige = {t["name"]: t for t in json.loads(out.getvalue().splitlines()[-1])["result"]["tools"]}["zeige"]
    assert "simulation" in zeige["inputSchema"]["properties"]["art"]["enum"]
    assert "simulation" in zeige["inputSchema"]["properties"]["bausteine"]["items"]["properties"]["typ"]["enum"]
    assert all(m in zeige["inputSchema"]["properties"]["bausteine"]["description"] for m in SIM_MIN)
    b = br.Bridge(root)
    assert call(c, out, sim("gas", SIM_MIN["gas"]))["content"][0]["text"] == "Wird gezeigt."
    r = call(c, out, {**sim("pendel", {"laenge": 1, "winkel": 30, "formel": "sin(x)"}), "id": "kaputt"})
    assert r["isError"] is True and "bad_block_1" in r["content"][0]["text"] and "sin" not in r["content"][0]["text"]
    c.say("Hier das Gas.")
    assert b.fetch() == ("ok", ["Hier das Gas."])
    got = {i["id"]: i for i in b.stage.since(0)[0]}
    assert set(got) == {"sim"} and got["sim"]["art"] == "simulation"
    assert got["sim"]["bausteine"][0]["parameter"] == SIM_FILLED["gas"] and got["sim"]["bausteine"][0]["tempo"] == 0


# --- Härtung: jede Eingabe endet als Ansicht oder ViewError, nie als anderer Fehler -----------------------

def _view(typ, art="antwort", **fields):
    return {"id": "h", "art": art, "titel": "T", "bausteine": [{"typ": typ, **fields}]}


def test_auditor_inputs_are_view_errors():
    for view in (_view("vergleich", optionen=["a", "b"], kriterien=[{"name": "k", "werte": [10**400, 1]}]),
                 _view("x") | {"bausteine": [{"typ": [1]}]},_view("x") | {"bausteine": [{"typ": {"a": 1}}]}):
        with pytest.raises(schema.ViewError) as e:
            schema.validate(view)
        assert e.value.code == "bad_block_1"


HUGE_FIELDS = [
    lambda n: _view("kennzahlen", werte=[{"name": "a", "wert": n}]),
    lambda n: _view("tabelle", spalten=["a"], zeilen=[[n]]),
    lambda n: _view("diagramm", form="linie", reihen=[{"name": "a", "punkte": [[n, 1]]}]),
    lambda n: _view("diagramm", form="linie", reihen=[{"name": "a", "punkte": [[1, n]]}]),
    lambda n: _view("aussagen", aussagen=[{"text": "a", "quellen": [n]}]),
    lambda n: _view("quellen", quellen=[{"nr": n, "titel": "a"}]),
    lambda n: _view("szene3d", art="modell", szenen=[{"name": "s", "objekte": [{**BOX, "masse": [n, 1, 1]}]}]),
    lambda n: _view("szene3d", art="modell", szenen=[{"name": "s", "objekte": [{**BOX, "position": [n, 0, 0]}]}]),
    lambda n: _view("szene3d", art="modell", szenen=[{"name": "s", "objekte": [{**BOX, "drehung": [0, n, 0]}]}]),
    lambda n: _view("szene3d", art="modell", szenen=[{"name": "s", "objekte": [{"form": "linie", "punkte": [[0, 0, n], [1, 1, 1]]}]}]),
    lambda n: _view("plan2d", art="plan", elemente=[{"art": "linie", "von": [n, 0], "bis": [1, 1]}]),
    lambda n: _view("plan2d", art="plan", elemente=[{"art": "rechteck", "x": 0, "y": n, "b": 1, "h": 1}]),
    lambda n: _view("plan2d", art="plan", elemente=[{"art": "rechteck", "x": 0, "y": 0, "b": n, "h": 1}]),
    lambda n: _view("plan2d", art="plan", elemente=[{"art": "kreis", "x": 0, "y": 0, "r": n}]),
    lambda n: _view("plan2d", art="plan", elemente=[{"art": "bogen", "x": 0, "y": 0, "r": 1, "von": n, "bis": 1}]),
    lambda n: _view("plan2d", art="plan", elemente=[{"art": "polylinie", "punkte": [[0, 0], [n, 1]]}]),
    lambda n: _view("plan2d", art="plan", elemente=[{"art": "text", "x": 0, "y": 0, "text": "a", "groesse": n}]),
    lambda n: _view("plan2d", art="plan", elemente=[{"art": "mass", "von": [0, 0], "bis": [1, n]}]),
    lambda n: _view("vergleich", optionen=["a", "b"], kriterien=[{"name": "k", "werte": [1, n]}]),
    lambda n: _view("quiz", art="lernen", fragen=[{**Q, "richtig": n}]),
    lambda n: _view("anleitung", art="lernen", schritte=[{**S, "sekunden": n}]),
    lambda n: _view("anleitung", art="lernen", schritte=[S], aktuell=n),
    *SIM_NUMERIC,
]


@pytest.mark.parametrize("n", [10**400, -10**400])
@pytest.mark.parametrize("make", HUGE_FIELDS)
def test_huge_integers_in_every_numeric_field_are_rejected(make, n):
    with pytest.raises(schema.ViewError) as e:
        schema.validate(make(n))
    assert e.value.code.startswith("bad_")


ENUM_FIELDS = [
    lambda v: {"id": "h", "art": v, "titel": "T", "bausteine": [{"typ": "text", "absaetze": ["a"]}]},
    lambda v: {"id": v, "art": "antwort", "titel": "T", "bausteine": [{"typ": "text", "absaetze": ["a"]}]},
    lambda v: {"id": "h", "schliessen": v},
    lambda v: _view(v),
    lambda v: _view("liste", punkte=["a"], nummeriert=v),
    lambda v: _view("kennzahlen", werte=[{"name": "a", "wert": 1, "richtung": v}]),
    lambda v: _view("diagramm", form=v, reihen=[{"name": "a", "punkte": [[1, 1]]}]),
    lambda v: _view("fortschritt", schritte=[{"text": "a", "zustand": v}]),
    lambda v: _view("aufgaben", punkte=[{"text": "a", "erledigt": v}]),
    lambda v: _view("zeitplan", termine=[{"von": v, "bis": "11:00", "titel": "a"}]),
    lambda v: _view("countdown", titel="a", ende=v),
    lambda v: _view("aenderung", name="a.py", bloecke=[{"zeilen": [{"art": v, "text": "x"}]}]),
    lambda v: _view("szene3d", art="modell", szenen=[{"name": "s", "objekte": [{**BOX, "form": v}]}]),
    lambda v: _view("szene3d", art="modell", szenen=[{"name": "s", "objekte": [{**BOX, "farbe": v}]}]),
    lambda v: _view("szene3d", art="modell", szenen=[{"name": "s", "objekte": [BOX]}], hervorheben=[v]),
    lambda v: _view("plan2d", art="plan", elemente=[{"art": v, "von": [0, 0], "bis": [1, 1]}]),
    lambda v: _view("plan2d", art="plan", elemente=[{"art": "linie", "von": [0, 0], "bis": [1, 1], "ebene": v}], ebenen=["a"]),
    lambda v: _view("plan2d", art="plan", elemente=[{"art": "polylinie", "punkte": [[0, 0], [1, 1]], "geschlossen": v}]),
    lambda v: _view("netz", art="netz", form=v, knoten=K2),
    lambda v: _view("netz", art="netz", form="ablauf", knoten=[{"id": "a", "text": "A", "art": v}]),
    lambda v: _view("netz", art="netz", form="ablauf", knoten=[{"id": v, "text": "A"}]),
    lambda v: _view("netz", art="netz", form="ablauf", knoten=K2, kanten=[{"von": v, "bis": "b"}]),
    lambda v: _view("netz", art="netz", form="baum", knoten=K2, kanten=[{"von": "a", "bis": v}]),
    lambda v: sim(v, SIM_MIN["pendel"]),
    lambda v: sim("pendel", SIM_MIN["pendel"], spur=v),
    lambda v: sim("gas", {**SIM_MIN["gas"], "stoesse": v}),
    lambda v: sim("umlauf", {"zentralmasse": 1, "koerper": [{"name": "a", "abstand": 1, "farbe": v}]}),
    lambda v: sim("umlauf", {"zentralmasse": 1, "koerper": [{"name": v, "abstand": 1}]}),
]


@pytest.mark.parametrize("value", [[1], {"a": 1}, ["auf"], {"linie": 1}])
@pytest.mark.parametrize("make", ENUM_FIELDS)
def test_unhashable_values_in_enum_like_fields_are_view_errors(make, value):
    with pytest.raises(schema.ViewError):
        schema.validate(make(value))


def _fuzz_examples():
    els = [{"art": "linie", "von": [0, 0], "bis": [10, 0], "ebene": "W"}, {"art": "polylinie", "punkte": [[0, 0], [5, 5]], "geschlossen": True},
           {"art": "rechteck", "x": 1, "y": 1, "b": 3, "h": 2}, {"art": "kreis", "x": 5, "y": 5, "r": 1},
           {"art": "bogen", "x": 0, "y": 0, "r": 2, "von": 0, "bis": 90}, {"art": "text", "x": 1, "y": 1, "text": "K", "groesse": 2},
           {"art": "mass", "von": [0, -2], "bis": [10, -2], "text": "10"}]
    return [MATHE, MARKT, RECHERCHE, p3("fortschritt", schritte=STEPS), p3("aufgaben", punkte=[{"text": "M", "erledigt": True}]),
            p3("zeitplan", termine=[{"von": "09:30", "bis": "10:00", "titel": "A", "ort": "B"}]), p3("mail", art="mail", **MAIL),
            p3("mail-entwurf", art="mail", **DRAFT), p3("countdown", titel="Tee", ende="2026-11-12T12:00"),
            doc("dokument", name="a.py", zeilen=CODE, gliederung=["g"]), doc("aenderung", name="a.py", bloecke=DIFF),
            scene({"name": "v", "objekte": [BOX, {"form": "linie", "name": "L", "punkte": [[0, 0, 0], [1, 1, 1]]}]},
                  hervorheben=["Boden 1"], beschriftungen=[{"objekt": "L", "text": "x"}]),
            plan(els, einheit="m", ebenen=["W"]), p6("vergleich", "antwort", **VERGLEICH), p6("zeitstrahl", "antwort", **ZEITSTRAHL),
            p6("gegenueber", "antwort", **GEGENUEBER), p6("lernkarten", **KARTEN), p6("quiz", **QUIZ), p6("anleitung", aktuell=1, **ANLEITUNG),
            p6("netz", "netz", form="baum", knoten=KNOTEN, kanten=KANTEN),
            *[sim(m, SIM_FULL[m], laufzeit=45, tempo=3, spur=False, beschreibung="b") for m in SIM_FULL],
            *[sim(m, SIM_MIN[m]) for m in SIM_MIN]]


def _paths(v, path=()):
    yield path
    if isinstance(v, dict):
        for k, x in v.items():
            yield from _paths(x, path + (k,))
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from _paths(x, path + (i,))


def test_seeded_fuzz_only_returns_views_or_raises_view_errors():
    import copy
    import random
    rnd = random.Random(6)
    junk = [None, True, False, 0, -1, 1.5, float("nan"), float("inf"), float("-inf"), 10**400, -10**400, 2**63, "", "x" * 2000,
            "\ud800", "a\udfffb", chr(0x202e), [], [None], [[1]], {}, {"a": 1}, {"typ": [1]}, ["auf"], "linie", "baum", "a", "n0",
            "gas", "pendel", "umlauf", 0.05, 1000, 100.0]
    examples = _fuzz_examples()
    for _ in range(3000):
        view = copy.deepcopy(rnd.choice(examples))
        for _ in range(rnd.randint(1, 3)):
            path = rnd.choice(list(_paths(view))[1:])
            parent = view
            for key in path[:-1]:
                parent = parent[key]
            if rnd.random() < 0.15 and isinstance(parent, dict):
                parent.pop(path[-1])
                break
            parent[path[-1]] = copy.deepcopy(rnd.choice(junk))
        try:
            got = schema.validate(view)
        except schema.ViewError as e:
            assert isinstance(e.code, str) and len(e.code) <= 20
            continue
        assert schema.validate(got) == got


def test_zeige_tool_names_the_p6_kinds_and_blocks():
    props = ch.ZEIGE_TOOL["inputSchema"]["properties"]
    assert {"lernen", "netz"} <= set(props["art"]["enum"])
    new = {"vergleich", "zeitstrahl", "gegenueber", "lernkarten", "quiz", "anleitung", "netz"}
    assert new <= set(props["bausteine"]["items"]["properties"]["typ"]["enum"])
    assert all(n in props["bausteine"]["description"] for n in new) and "Index ab 0" in props["bausteine"]["description"]
    assert all(n in ch.INSTRUCTIONS for n in new) and "ab 0" in ch.INSTRUCTIONS


def test_p6_views_are_listed_by_tools_list_and_travel_through_the_real_channel_into_the_bridge_store(channel):
    c, out, root = channel
    c.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    zeige = {t["name"]: t for t in json.loads(out.getvalue().splitlines()[-1])["result"]["tools"]}["zeige"]
    assert {"quiz", "netz", "vergleich"} <= set(zeige["inputSchema"]["properties"]["bausteine"]["items"]["properties"]["typ"]["enum"])
    b = br.Bridge(root)
    assert call(c, out, p6("quiz", **QUIZ))["content"][0]["text"] == "Wird gezeigt."
    assert call(c, out, {**p6("netz", art="netz", form="baum", knoten=KNOTEN, kanten=KANTEN), "id": "n"})["content"][0]["text"] == "Wird gezeigt."
    c.say("Hier dein Quiz.")
    assert b.fetch() == ("ok", ["Hier dein Quiz."])
    got = {i["id"]: i for i in b.stage.since(0)[0]}
    assert got["p6"]["bausteine"][0]["fragen"][0]["richtig"] == 1 and got["n"]["art"] == "netz"
