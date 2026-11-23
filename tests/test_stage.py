"""Bühne (P2): Schema der Ansichten, Werkzeug `zeige` im Channel, Weg über die Bridge, API `stage.get`, Notaus."""
import io
import json
import math
import re
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
    "doppelpendel": {"laenge1": 1, "laenge2": 1, "winkel1": 120, "winkel2": -10},
    "welle": {"wellen": [{"amplitude": 1, "wellenlaenge": 2, "frequenz": 0.5}]},
}
SIM_FILLED = {                                                                    # was die Oberfläche aus SIM_MIN bekommt
    "pendel": {"laenge": 1, "winkel": 30, "anfangsgeschwindigkeit": 0, "daempfung": 0, "g": 9.81},
    "feder": {"masse": 1, "federkonstante": 10, "auslenkung": 0.2, "daempfung": 0},
    "wurf": {"geschwindigkeit": 20, "winkel": 45, "hoehe": 0, "g": 9.81, "luftwiderstand": 0},
    "umlauf": {"zentralmasse": 1, "koerper": [{"name": "Erde", "abstand": 1, "exzentrizitaet": 0, "phase": 0, "masse": 0, "farbe": "arc"}],
               "anziehung": False},
    "gas": {"anzahl": 50, "kasten": [100, 60], "radius": 1, "geschwindigkeit": 0.5, "schwerkraft": 0, "stoesse": True, "startwert": 1},
    "doppelpendel": {"laenge1": 1, "laenge2": 1, "masse1": 1, "masse2": 1, "winkel1": 120, "winkel2": -10, "g": 9.81, "daempfung": 0},
    "welle": {"wellen": [{"amplitude": 1, "wellenlaenge": 2, "frequenz": 0.5, "phase": 0, "richtung": "rechts"}], "bereich": 0},
}
SIM_FULL = {
    "pendel": {"laenge": 2.5, "winkel": -45, "anfangsgeschwindigkeit": 90, "daempfung": 0.2, "g": 1.62},
    "feder": {"masse": 0.5, "federkonstante": 200, "auslenkung": -0.1, "daempfung": 1.5},
    "wurf": {"geschwindigkeit": 30, "winkel": -10, "hoehe": 50, "g": 9.81, "luftwiderstand": 0.01},
    "umlauf": {"zentralmasse": 1, "koerper": [{"name": "Merkur", "abstand": 0.39, "exzentrizitaet": 0.21, "phase": 10, "masse": 1.7e-7,
                                                "farbe": "amber"},
                                               {"name": "Erde", "abstand": 1, "exzentrizitaet": 0.017, "phase": 200, "masse": 3e-6, "farbe": "ok"},
                                               {"name": "Mars", "abstand": 1.52, "exzentrizitaet": 0.09, "phase": 359.5, "masse": 0.01,
                                                "farbe": "alarm"}],
               "anziehung": True},
    "gas": {"anzahl": 120, "kasten": [200, 100], "radius": 1.5, "geschwindigkeit": 2, "schwerkraft": 9.81, "stoesse": False,
            "startwert": 42},
    "doppelpendel": {"laenge1": 1.5, "laenge2": 0.5, "masse1": 2, "masse2": 0.5, "winkel1": 180, "winkel2": -90, "g": 1.62, "daempfung": 0.1},
    "welle": {"wellen": [{"amplitude": 0.5, "wellenlaenge": 4, "frequenz": 1, "phase": 90, "richtung": "links"},
                         {"amplitude": 0.5, "wellenlaenge": 4, "frequenz": 1, "phase": 0, "richtung": "rechts"},
                         {"amplitude": 0.1, "wellenlaenge": 1.5, "frequenz": 3, "phase": 360, "richtung": "rechts"}], "bereich": 20},
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
    # P5b: Doppelpendel
    ("doppelpendel", {"laenge1": 0.05}, True), ("doppelpendel", {"laenge1": 100}, True),
    ("doppelpendel", {"laenge1": 0.0499}, False), ("doppelpendel", {"laenge1": 100.01}, False),
    ("doppelpendel", {"laenge2": 0.05}, True), ("doppelpendel", {"laenge2": 100}, True),
    ("doppelpendel", {"laenge2": 0.0499}, False), ("doppelpendel", {"laenge2": 100.01}, False),
    ("doppelpendel", {"masse1": 0.01}, True), ("doppelpendel", {"masse1": 1000}, True),
    ("doppelpendel", {"masse1": 0.0099}, False), ("doppelpendel", {"masse1": 1000.1}, False), ("doppelpendel", {"masse1": 0}, False),
    ("doppelpendel", {"masse2": 0.01}, True), ("doppelpendel", {"masse2": 1000}, True),
    ("doppelpendel", {"masse2": 0.0099}, False), ("doppelpendel", {"masse2": 1000.1}, False),
    ("doppelpendel", {"winkel1": -180}, True), ("doppelpendel", {"winkel1": 180}, True),
    ("doppelpendel", {"winkel1": -180.01}, False), ("doppelpendel", {"winkel1": 180.01}, False),
    ("doppelpendel", {"winkel2": -180}, True), ("doppelpendel", {"winkel2": 180}, True),
    ("doppelpendel", {"winkel2": -180.01}, False), ("doppelpendel", {"winkel2": 180.01}, False),
    ("doppelpendel", {"winkel1": 0, "winkel2": 0}, True),                          # Ruhelage: gültig, die Oberfläche zeigt Stillstand
    ("doppelpendel", {"g": 0.1}, True), ("doppelpendel", {"g": 100}, True), ("doppelpendel", {"g": 0.099}, False),
    ("doppelpendel", {"g": 100.1}, False),
    ("doppelpendel", {"daempfung": 0}, True), ("doppelpendel", {"daempfung": 5}, True),
    ("doppelpendel", {"daempfung": -0.001}, False), ("doppelpendel", {"daempfung": 5.001}, False),
    ("doppelpendel", {"laenge": 1}, False), ("doppelpendel", {"masse3": 1}, False), ("doppelpendel", {"winkel": 10}, False),
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


@pytest.mark.parametrize("modell", ["Doppelpendel", "Welle", "wellen", "doppel-pendel", "teilchen", "molekuel", "Pendel", "", None, 5, True,
                                    ["pendel"], {"pendel": 1}])
def test_p5a_unknown_models_are_rejected(modell):
    sim_bad(modell, SIM_MIN["pendel"])


@pytest.mark.parametrize("modell", list(SIM_MIN))
def test_p5b_parameters_of_another_model_are_rejected(modell):                  # P5b: doppelpendel und welle sind jetzt Modelle
    for other in SIM_MIN:
        if other != modell:
            sim_bad(modell, SIM_MIN[other])


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
    for f in schema.SIM_WELLE:                                                     # P5b
        yield lambda v, f=f: sim("welle", {"wellen": [{**SIM_MIN["welle"]["wellen"][0], f: v}]})
    yield lambda v: sim("welle", {**SIM_MIN["welle"], "bereich": v})
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


def test_p5a_description_loses_control_characters_and_collapses_whitespace():
    text = "Ohne" + chr(0x202e) + chr(0) + chr(10) + "Reibung" + chr(9) + "  und   mehr."
    got = sim_block("pendel", SIM_MIN["pendel"], beschreibung="  " + text + chr(10))["beschreibung"]
    assert got == "Ohne Reibung und mehr."
    assert all(ch.isprintable() for ch in got) and chr(0x202e) not in got and chr(0) not in got and chr(10) not in got


def test_p5a_description_limit_counts_after_cleaning():
    assert len(sim_block("pendel", SIM_MIN["pendel"], beschreibung=" " * 50 + "x" * 400 + chr(10) * 50)["beschreibung"]) == 400
    assert len(sim_block("pendel", SIM_MIN["pendel"], beschreibung="x" * 200 + " " * 5 + "x" * 199)["beschreibung"]) == 400   # 405 roh, 400 gesäubert
    sim_bad("pendel", SIM_MIN["pendel"], beschreibung="x" * 200 + chr(0x202e) + "x" * 200)                       # das Zeichen wird zum Leerzeichen: 401
    sim_bad("pendel", SIM_MIN["pendel"], beschreibung=chr(10) + "x" * 401)


def test_p5a_bridge_drops_invalid_simulations_that_got_past_the_channel(channel):
    c, out, root = channel
    b = br.Bridge(root)
    c.show(sim("gas", SIM_MIN["gas"]))
    c._views.append({**sim("pendel", {"laenge": 1, "winkel": 30, "formel": "sin(x)"}), "id": "unbekannt"})          # unbekannter Parameter
    c._views.append({**sim("pendel", {"laenge": 1000, "winkel": 30}), "id": "zu-gross"})                           # außerhalb der Grenzen
    c.say("Hier das Gas.")
    assert b.fetch() == ("ok", ["Hier das Gas."])
    assert [i["id"] for i in b.stage.since(0)[0]] == ["sim"]


GAS_AREA_RADIUS = math.sqrt(30 / (300 * math.pi))                                  # 300 Teilchen füllen genau 30 % von 10 x 10


@pytest.mark.parametrize("factor,ok", [(0.999, True), (1.001, False)])
def test_p5a_gas_area_near_thirty_percent(factor, ok):
    params = {"anzahl": 300, "kasten": [10, 10], "radius": factor * GAS_AREA_RADIUS, "geschwindigkeit": 1}
    assert GAS_AREA_RADIUS < 0.05 * 10                                             # die 5-%-Regel greift hier nicht
    if ok:
        assert sim_block("gas", params)["parameter"]["radius"] == params["radius"]
    else:
        sim_bad("gas", params)


@pytest.mark.parametrize("kasten", [[100, float("nan")], [float("nan"), 100], [100, 10**400], [10**400, 100]])
def test_p5a_gas_box_rejects_nan_and_huge_integers(kasten):
    sim_bad("gas", {**SIM_MIN["gas"], "kasten": kasten})


def test_p5a_gas_box_short_side_first_passes():
    assert sim_block("gas", {**SIM_MIN["gas"], "kasten": [60, 100]})["parameter"]["kasten"] == [60, 100]


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


# --- P5b: Ergänzungen der Simulation (welle, umlauf mit Anziehung; docs/ui-p5-plan.md Abschnitt 7) -----------

W1 = SIM_MIN["welle"]["wellen"][0]


@pytest.mark.parametrize("change,ok", [
    ({"amplitude": 0.001}, True), ({"amplitude": 100}, True), ({"amplitude": 0.00099}, False), ({"amplitude": 100.01}, False),
    ({"amplitude": 0}, False), ({"amplitude": -1}, False),
    ({"wellenlaenge": 0.01}, True), ({"wellenlaenge": 1000}, True), ({"wellenlaenge": 0.0099}, False), ({"wellenlaenge": 1000.1}, False),
    ({"wellenlaenge": 0}, False),
    ({"frequenz": 0.01}, True), ({"frequenz": 100}, True), ({"frequenz": 0.0099}, False), ({"frequenz": 100.01}, False), ({"frequenz": 0}, False),
    ({"phase": 0}, True), ({"phase": 360}, True), ({"phase": -0.01}, False), ({"phase": 360.01}, False),
    ({"richtung": "rechts"}, True), ({"richtung": "links"}, True), ({"richtung": "Links"}, False), ({"richtung": "oben"}, False),
    ({"richtung": ""}, False), ({"richtung": None}, False), ({"richtung": 1}, False), ({"richtung": True}, False),
    ({"richtung": ["links"]}, False), ({"richtung": {"links": 1}}, False),
    ({"formel": "sin(x)"}, False), ({"funktion": "cos"}, False), ({"geschwindigkeit": 1}, False),
])
def test_p5b_wave_limits_just_inside_pass_and_just_outside_are_rejected(change, ok):
    params = {"wellen": [{**W1, **change}]}
    if ok:
        got = sim_block("welle", params)["parameter"]
        assert got == {"wellen": [{**SIM_FILLED["welle"]["wellen"][0], **change}], "bereich": 0}
        assert schema.validate(sim("welle", got)) == schema.validate(sim("welle", params))
    else:
        sim_bad("welle", params)


@pytest.mark.parametrize("field", ["amplitude", "wellenlaenge", "frequenz"])
def test_p5b_wave_required_fields(field):
    sim_bad("welle", {"wellen": [{k: v for k, v in W1.items() if k != field}]})
    sim_bad("welle", {"wellen": [{**W1, field: None}]})


@pytest.mark.parametrize("params,ok", [
    ({"wellen": [W1]}, True), ({"wellen": [W1, W1]}, True), ({"wellen": [W1, W1, W1]}, True), ({"wellen": [W1] * 4}, False),
    ({"wellen": []}, False), ({"wellen": W1}, False), ({"wellen": "sin"}, False), ({"wellen": [None]}, False), ({"wellen": [[1, 2, 3]]}, False),
    ({}, False), ({"wellen": None}, False),
    ({"wellen": [W1], "bereich": 0}, True), ({"wellen": [W1], "bereich": 0.0}, True), ({"wellen": [W1], "bereich": 0.01}, True),
    ({"wellen": [W1], "bereich": 10_000}, True), ({"wellen": [W1], "bereich": 0.0099}, False), ({"wellen": [W1], "bereich": 0.005}, False),
    ({"wellen": [W1], "bereich": 1e-300}, False), ({"wellen": [W1], "bereich": 10_000.1}, False), ({"wellen": [W1], "bereich": -1}, False),
    ({"wellen": [W1], "bereich": -0.01}, False), ({"wellen": [W1], "bereich": None}, False), ({"wellen": [W1], "bereich": "auto"}, False),
    ({"wellen": [W1], "skript": "x"}, False),
])
def test_p5b_wave_list_and_range(params, ok):
    if ok:
        got = sim_block("welle", params)["parameter"]
        assert len(got["wellen"]) == len(params["wellen"]) and got["bereich"] == params.get("bereich", 0)
        assert schema.validate(sim("welle", got))["bausteine"][0]["parameter"] == got
    else:
        sim_bad("welle", params)


ERDE = {"name": "Erde", "abstand": 1}


@pytest.mark.parametrize("params,ok", [
    ({"zentralmasse": 1, "koerper": [ERDE], "anziehung": True}, True), ({"zentralmasse": 1, "koerper": [ERDE], "anziehung": False}, True),
    ({"zentralmasse": 1, "koerper": [ERDE], "anziehung": 1}, False), ({"zentralmasse": 1, "koerper": [ERDE], "anziehung": "ja"}, False),
    ({"zentralmasse": 1, "koerper": [ERDE], "anziehung": None}, False), ({"zentralmasse": 1, "koerper": [ERDE], "anziehung": [True]}, False),
    ({"zentralmasse": 1, "koerper": [{**ERDE, "masse": 0}]}, True), ({"zentralmasse": 1, "koerper": [{**ERDE, "masse": 0.01}]}, True),
    ({"zentralmasse": 1, "koerper": [{**ERDE, "masse": 3e-6}]}, True), ({"zentralmasse": 1, "koerper": [{**ERDE, "masse": 0.0101}]}, False),
    ({"zentralmasse": 1, "koerper": [{**ERDE, "masse": -1e-9}]}, False), ({"zentralmasse": 1, "koerper": [{**ERDE, "masse": "0"}]}, False),
    ({"zentralmasse": 1, "anziehung": True, "koerper": [{"name": f"k{i}", "abstand": 1 + i, "masse": 0.01} for i in range(8)]}, True),
    ({"zentralmasse": 1, "anziehung": True, "koerper": [{"name": f"k{i}", "abstand": 1 + i} for i in range(9)]}, False),
    ({"zentralmasse": 1, "anziehung": True, "koerper": [ERDE, {"name": "b", "abstand": 100.1}]}, False),   # alte Regeln gelten weiter
    ({"zentralmasse": 1, "anziehung": True, "koerper": [ERDE, ERDE]}, False),
    ({"zentralmasse": 1, "koerper": [ERDE], "gravitation": True}, False), ({"zentralmasse": 1, "koerper": [{**ERDE, "masse2": 0}]}, False),
])
def test_p5b_orbit_attraction_and_body_masses(params, ok):
    if ok:
        got = sim_block("umlauf", params)["parameter"]
        assert got["anziehung"] is params.get("anziehung", False)
        assert [k["masse"] for k in got["koerper"]] == [k.get("masse", 0) for k in params["koerper"]]
        assert schema.validate(sim("umlauf", got))["bausteine"][0]["parameter"] == got
    else:
        sim_bad("umlauf", params)


# --- P5b: Baustein teilchen (Molekül, Atom, Orbital) ---------------------------------------------------------

WASSER = [{"element": "O", "position": [0, 0, 0]}, {"element": "H", "position": [0.757, 0.586, 0]},
          {"element": "H", "position": [-0.757, 0.586, 0]}]
T_MIN = {
    "molekuel": {"atome": [{"element": "H", "position": [0, 0, 0]}]},
    "atom": {"element": "Na"},
    "orbital": {"orbital": "2p_z"},
}
T_FILLED = {                                                                      # was die Oberfläche aus T_MIN bekommt
    "molekuel": {"name": "", "atome": [{"element": "H", "position": [0, 0, 0]}], "bindungen": [], "beschriftungen": [],
                 "darstellung": "kugel-stab"},
    "atom": {"element": "Na", "neutronen": -1, "ladung": 0, "schalen": [2, 8, 1]},
    "orbital": {"orbital": "2p_z", "punkte": 2500, "startwert": 1},
}
T_FULL = {
    "molekuel": {"name": "Wasser", "atome": WASSER, "bindungen": [{"von": 0, "bis": 1, "ordnung": 1}, {"von": 2, "bis": 0, "ordnung": 2}],
                 "beschriftungen": [{"atom": 0, "text": "Sauerstoff"}, {"atom": 2, "text": "H"}], "darstellung": "kalotte"},
    "atom": {"element": "Fe", "neutronen": 30, "ladung": 2, "schalen": [2, 8, 14]},
    "orbital": {"orbital": "3d_x2-y2", "punkte": 5000, "startwert": 2_147_483_647},
}


def teil(form, fields, art="teilchen"):
    return {"id": "t", "art": art, "titel": "T", "bausteine": [{"typ": "teilchen", "form": form, **fields}]}


def teil_block(form, fields):
    return schema.validate(teil(form, fields))["bausteine"][0]


def teil_bad(form, fields):
    with pytest.raises(schema.ViewError) as e:
        schema.validate(teil(form, fields))
    assert e.value.code == "bad_block_1"


def atoms(n):
    return [{"element": "C", "position": [i % 10, (i // 10) % 10, i // 100]} for i in range(n)]


@pytest.mark.parametrize("form", list(T_MIN))
def test_p5b_minimal_teilchen_gets_every_default(form):
    assert teil_block(form, T_MIN[form]) == {"typ": "teilchen", "form": form, **T_FILLED[form]}


@pytest.mark.parametrize("form", list(T_FULL))
def test_p5b_full_teilchen_keeps_every_value(form):
    assert teil_block(form, T_FULL[form]) == {"typ": "teilchen", "form": form, **T_FULL[form]}


@pytest.mark.parametrize("form", list(T_MIN))
@pytest.mark.parametrize("art", ["teilchen", "antwort", "lernen", "recherche"])
def test_p5b_teilchen_works_in_every_kind_and_passes_the_second_check_unchanged(form, art):
    for fields in (T_MIN[form], T_FULL[form]):
        once = schema.validate(teil(form, fields, art=art))
        assert schema.validate(once) == once and once["art"] == art


def test_p5b_element_table_has_118_unique_symbols_and_atomic_numbers():
    assert len(schema.ELEMENTE) == 118 and len(set(schema.ELEMENTE)) == 118 and isinstance(schema.ELEMENTE, tuple)
    assert all(isinstance(s, str) and 1 <= len(s) <= 2 and s.isascii() and s[0].isupper() and (len(s) == 1 or s[1].islower())
               for s in schema.ELEMENTE)
    for sym, z in {"H": 1, "He": 2, "C": 6, "N": 7, "O": 8, "Na": 11, "Cl": 17, "Ca": 20, "Sc": 21, "Fe": 26, "Br": 35, "Ag": 47, "I": 53,
                   "Xe": 54, "Au": 79, "Hg": 80, "Pb": 82, "U": 92, "Pu": 94, "Fl": 114, "Og": 118}.items():
        assert schema.ORDNUNGSZAHL[sym] == z and schema.ELEMENTE[z - 1] == sym


ALL_ELEMENTS = (                                                                  # von Hand ausgeschrieben, unabhängig von schema.py
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag "
    "Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa "
    "U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og"
).split()


def test_p5b_element_table_matches_the_written_out_list_and_z_is_index_plus_one():
    assert len(ALL_ELEMENTS) == 118 and schema.ELEMENTE == tuple(ALL_ELEMENTS)
    assert schema.ORDNUNGSZAHL == {s: i + 1 for i, s in enumerate(ALL_ELEMENTS)}
    for i, sym in enumerate(ALL_ELEMENTS):
        assert schema.ORDNUNGSZAHL[sym] == i + 1


@pytest.mark.parametrize("axis", [0, 1, 2])
@pytest.mark.parametrize("sign", [1, -1])
def test_p5b_position_limit_on_every_side_of_every_axis(axis, sign):
    def mol(v):
        return {"atome": [{"element": "H", "position": [v if j == axis else 0 for j in range(3)]}]}
    assert teil_block("molekuel", mol(sign * 200))["atome"][0]["position"][axis] == sign * 200
    assert teil_block("molekuel", mol(sign * 200.0))["atome"][0]["position"][axis] == sign * 200
    teil_bad("molekuel", mol(sign * 200.001))
    teil_bad("molekuel", mol(sign * 201))


def test_p5b_indices_at_three_hundred_atoms():
    a = atoms(300)
    got = teil_block("molekuel", {"atome": a, "bindungen": [{"von": 0, "bis": 299}, {"von": 299, "bis": 298}],
                                  "beschriftungen": [{"atom": 299, "text": "letztes"}, {"atom": 0, "text": "erstes"}]})
    assert got["bindungen"][0] == {"von": 0, "bis": 299, "ordnung": 1} and got["beschriftungen"][0]["atom"] == 299
    teil_bad("molekuel", {"atome": a, "bindungen": [{"von": 0, "bis": 300}]})
    teil_bad("molekuel", {"atome": a, "bindungen": [{"von": 300, "bis": 0}]})
    teil_bad("molekuel", {"atome": a, "beschriftungen": [{"atom": 300, "text": "x"}]})


def test_filled_defaults_of_an_older_block_are_size_checked_at_the_exact_boundary():
    werte = [{"name": f"k{i}", "wert": i} for i in range(8)]                     # ohne einheit, aenderung, richtung: werden ergänzt

    def view(n):                                                                   # n Zeichen Fülltext, Absätze zu 1200
        paras = ["y" * min(1200, n - i) for i in range(0, n, 1200)]
        return {"id": "k", "art": "markt", "titel": "T", "stand": "heute", "bausteine": [
            {"typ": "kennzahlen", "werte": werte}, *[{"typ": "text", "absaetze": paras[j:j + 12]} for j in range(0, len(paras), 12)]]}

    def size(v):
        return len(json.dumps(v, ensure_ascii=False).encode("utf-8"))

    def ok(n):
        try:
            schema.validate(view(n))
            return True
        except schema.ViewError as e:
            assert e.code == "too_large"
            return False

    lo, hi = 1, schema.MAX_JSON                                                    # ok(lo), nicht ok(hi): die Grenze suchen
    assert ok(lo) and not ok(hi)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    over, under = view(hi), view(lo)
    assert size(over) - size(under) == 1                                          # genau ein Byte Unterschied in der Eingabe
    assert size(over) <= schema.MAX_JSON - 300                                    # die Eingabe allein wäre klein genug ...
    with pytest.raises(schema.ViewError) as e:                                     # ... erst die ergänzten Felder machen sie zu groß
        schema.validate(over)
    assert e.value.code == "too_large"
    once = schema.validate(under)
    assert size(once) == schema.MAX_JSON and schema.validate(once) == once
    assert once["bausteine"][0]["werte"][0] == {"name": "k0", "wert": 0, "einheit": "", "aenderung": "", "richtung": ""}


def _schalen_for(z):
    return [min(32, z - 32 * i) for i in range((z + 31) // 32)] or []


@pytest.mark.parametrize("sym", list(schema.ELEMENTE))
def test_p5b_every_element_passes_in_molecule_and_atom(sym):
    assert teil_block("molekuel", {"atome": [{"element": sym, "position": [0, 0, 0]}]})["atome"][0]["element"] == sym
    z = schema.ORDNUNGSZAHL[sym]
    got = teil_block("atom", {"element": sym, "schalen": _schalen_for(z)})
    assert got["element"] == sym and sum(got["schalen"]) == z


@pytest.mark.parametrize("element", ["h", "HE", "he", "hE", "Xx", "Uue", "D", "T", "", " H", "H ", "H" + chr(0), "Na+", None, 1, 1.0, True,
                                     ["H"], {"H": 1}, ("H",)])
def test_p5b_unknown_elements_and_wrong_case_are_rejected(element):
    teil_bad("molekuel", {"atome": [{"element": element, "position": [0, 0, 0]}]})
    teil_bad("atom", {"element": element})


@pytest.mark.parametrize("element,ladung,schalen", [
    ("H", 0, [1]), ("He", 0, [2]), ("Li", 0, [2, 1]), ("C", 0, [2, 4]), ("Ne", 0, [2, 8]), ("Na", 0, [2, 8, 1]), ("Ar", 0, [2, 8, 8]),
    ("K", 0, [2, 8, 8, 1]), ("Ca", 0, [2, 8, 8, 2]), ("H", 1, []), ("Li", 3, []), ("Na", 1, [2, 8]), ("Cl", -1, [2, 8, 8]),
    ("K", -1, [2, 8, 8, 2]), ("Ca", 2, [2, 8, 8]), ("Ca", 3, [2, 8, 7]), ("O", -2, [2, 8]), ("N", -3, [2, 8]),
])
def test_p5b_missing_shells_are_filled_by_the_simple_rule(element, ladung, schalen):
    got = teil_block("atom", {"element": element, "ladung": ladung})
    assert got == {"typ": "teilchen", "form": "atom", "element": element, "neutronen": -1, "ladung": ladung, "schalen": schalen}
    assert schema.validate(teil("atom", got)) == schema.validate(teil("atom", {"element": element, "ladung": ladung}))


@pytest.mark.parametrize("element,ladung", [("Sc", 0), ("Ca", -1), ("K", -3), ("Fe", 0), ("Og", 0), ("Ti", 1), ("V", 2),
                                            ("Sc", 1), ("Sc", 2), ("Sc", 3), ("Ti", 2), ("Ti", 3), ("V", 3), ("Fe", 3)])
def test_p5b_shells_are_required_above_atomic_number_twenty_or_twenty_electrons(element, ladung):
    teil_bad("atom", {"element": element, "ladung": ladung})                    # die einfache Regel 2, 8, 8, 2 stimmt nur bis Ca
    z = schema.ORDNUNGSZAHL[element] - ladung
    assert teil_block("atom", {"element": element, "ladung": ladung, "schalen": _schalen_for(z)})["schalen"] == _schalen_for(z)


@pytest.mark.parametrize("fields,ok", [
    ({"element": "Ti", "ladung": 2, "schalen": [2, 8, 10]}, True), ({"element": "Sc", "schalen": [2, 8, 9, 2]}, True),
    ({"element": "Og", "schalen": [2, 8, 18, 32, 32, 18, 8]}, True), ({"element": "Og", "schalen": [2, 8, 18, 32, 32, 18, 7, 1]}, False),
    ({"element": "Og", "schalen": [2, 8, 18, 32, 33, 17, 8]}, False),                                    # über 32 in einer Schale
    ({"element": "Na", "schalen": [2, 8, 1]}, True), ({"element": "Na", "schalen": [2, 8, 2]}, False), ({"element": "Na", "schalen": [2, 8]}, False),
    ({"element": "Na", "schalen": [2, 0, 9]}, True), ({"element": "Na", "schalen": [11]}, True), ({"element": "Na", "schalen": [1, 8, 1]}, False),
    ({"element": "Na", "ladung": 1, "schalen": [2, 8]}, True), ({"element": "Na", "ladung": 1, "schalen": [2, 8, 1]}, False),
    ({"element": "Cl", "ladung": -1, "schalen": [2, 8, 8]}, True), ({"element": "Cl", "ladung": -1, "schalen": [2, 8, 7]}, False),
    ({"element": "H", "ladung": 1, "schalen": []}, True), ({"element": "H", "schalen": []}, False),
    ({"element": "H", "ladung": 2}, False), ({"element": "H", "ladung": 2, "schalen": []}, False),        # weniger als null Elektronen
    ({"element": "He", "ladung": 3}, False), ({"element": "Li", "ladung": 3}, True),
    ({"element": "Na", "schalen": [2, 8, -1, 2]}, False), ({"element": "Na", "schalen": [2, 8, 1.0]}, False),
    ({"element": "Na", "schalen": [2, 8, True]}, False), ({"element": "Na", "schalen": [2, 8, "1"]}, False),
    ({"element": "Na", "schalen": None}, False), ({"element": "Na", "schalen": "2,8,1"}, False), ({"element": "Na", "schalen": {"1": 2}}, False),
    ({"element": "Na", "schalen": [[2], 8, 1]}, False),
    ({"element": "Na", "neutronen": -1}, True), ({"element": "Na", "neutronen": 0}, True), ({"element": "Na", "neutronen": 12}, True),
    ({"element": "Na", "neutronen": 200}, True), ({"element": "Na", "neutronen": 201}, False), ({"element": "Na", "neutronen": -2}, False),
    ({"element": "Na", "neutronen": 12.0}, False), ({"element": "Na", "neutronen": True}, False), ({"element": "Na", "neutronen": None}, False),
    ({"element": "Na", "ladung": -3}, True), ({"element": "Na", "ladung": 3}, True), ({"element": "Na", "ladung": -4}, False),
    ({"element": "Na", "ladung": 4}, False), ({"element": "Na", "ladung": 1.0}, False), ({"element": "Na", "ladung": False}, False),
])
def test_p5b_atom_shells_neutrons_and_charge(fields, ok):
    if ok:
        got = teil_block("atom", fields)
        assert got["element"] == fields["element"] and got["neutronen"] == fields.get("neutronen", -1)
        assert got["ladung"] == fields.get("ladung", 0) and sum(got["schalen"]) == schema.ORDNUNGSZAHL[fields["element"]] - got["ladung"]
        if "schalen" in fields:
            assert got["schalen"] == fields["schalen"]
    else:
        teil_bad("atom", fields)


def test_p5b_atom_without_element_is_rejected():
    teil_bad("atom", {})
    teil_bad("atom", {"schalen": [1]})


def _bonds(n):                                                                     # die ersten n Paare (i, j) mit i < j
    pairs = [(i, j) for i in range(30) for j in range(i + 1, 30)]
    return [{"von": i, "bis": j} for i, j in pairs[:n]]


@pytest.mark.parametrize("fields,ok", [
    ({"atome": atoms(1)}, True), ({"atome": atoms(300)}, True), ({"atome": atoms(301)}, False), ({"atome": []}, False),
    ({"atome": WASSER[0]}, False), ({"atome": "H2O"}, False), ({"atome": None}, False), ({}, False), ({"atome": [None]}, False),
    ({"atome": [["H", [0, 0, 0]]]}, False),
    ({"atome": [{"element": "H", "position": [200, -200, 200]}]}, True), ({"atome": [{"element": "H", "position": [-200, 0, 0]}]}, True),
    ({"atome": [{"element": "H", "position": [200.001, 0, 0]}]}, False), ({"atome": [{"element": "H", "position": [0, -200.001, 0]}]}, False),
    ({"atome": [{"element": "H", "position": [0, 0, 1e9]}]}, False), ({"atome": [{"element": "H", "position": [0.5, -1.25, 3]}]}, True),
    ({"atome": [{"element": "H", "position": [0, 0]}]}, False), ({"atome": [{"element": "H", "position": [0, 0, 0, 0]}]}, False),
    ({"atome": [{"element": "H", "position": []}]}, False), ({"atome": [{"element": "H", "position": "0,0,0"}]}, False),
    ({"atome": [{"element": "H", "position": {"x": 0, "y": 0, "z": 0}}]}, False), ({"atome": [{"element": "H"}]}, False),
    ({"atome": [{"position": [0, 0, 0]}]}, False), ({"atome": [{"element": "H", "position": [0, 0, 0], "farbe": "arc"}]}, False),
    ({"atome": [{"element": "H", "position": [0, 0, 0], "ladung": 1}]}, False),
    ({"atome": WASSER, "bindungen": []}, True), ({"atome": WASSER, "bindungen": [{"von": 0, "bis": 2}]}, True),
    ({"atome": WASSER, "bindungen": [{"von": 0, "bis": 3}]}, False), ({"atome": WASSER, "bindungen": [{"von": 3, "bis": 0}]}, False),   # ins Leere
    ({"atome": WASSER, "bindungen": [{"von": -1, "bis": 0}]}, False), ({"atome": WASSER, "bindungen": [{"von": 0, "bis": -3}]}, False),
    ({"atome": WASSER, "bindungen": [{"von": 1, "bis": 1}]}, False),                                     # auf sich selbst
    ({"atome": WASSER, "bindungen": [{"von": 0, "bis": 1}, {"von": 0, "bis": 1}]}, False),                # doppelt
    ({"atome": WASSER, "bindungen": [{"von": 0, "bis": 1}, {"von": 1, "bis": 0}]}, False),                # doppelt, umgekehrt
    ({"atome": WASSER, "bindungen": [{"von": 0, "bis": 1, "ordnung": 1}, {"von": 1, "bis": 0, "ordnung": 2}]}, False),
    ({"atome": WASSER, "bindungen": [{"von": 0, "bis": 1}, {"von": 0, "bis": 2}, {"von": 1, "bis": 2}]}, True),
    ({"atome": WASSER, "bindungen": [{"von": 0, "bis": 1, "ordnung": 3}]}, True), ({"atome": WASSER, "bindungen": [{"von": 0, "bis": 1, "ordnung": 0}]}, False),
    ({"atome": WASSER, "bindungen": [{"von": 0, "bis": 1, "ordnung": 4}]}, False),
    ({"atome": WASSER, "bindungen": [{"von": 0, "bis": 1, "ordnung": 1.5}]}, False),
    ({"atome": WASSER, "bindungen": [{"von": 0, "bis": 1, "ordnung": "2"}]}, False),
    ({"atome": WASSER, "bindungen": [{"von": "0", "bis": 1}]}, False), ({"atome": WASSER, "bindungen": [{"von": 0}]}, False),
    ({"atome": WASSER, "bindungen": [{"bis": 1}]}, False), ({"atome": WASSER, "bindungen": [[0, 1]]}, False),
    ({"atome": WASSER, "bindungen": [{"von": 0, "bis": 1, "laenge": 1}]}, False), ({"atome": WASSER, "bindungen": {"von": 0, "bis": 1}}, False),
    ({"atome": WASSER, "bindungen": None}, False),
    ({"atome": atoms(30), "bindungen": _bonds(400)}, True), ({"atome": atoms(30), "bindungen": _bonds(401)}, False),
    ({"atome": WASSER, "beschriftungen": [{"atom": 2, "text": "H"}]}, True), ({"atome": WASSER, "beschriftungen": [{"atom": 3, "text": "H"}]}, False),
    ({"atome": WASSER, "beschriftungen": [{"atom": -1, "text": "H"}]}, False), ({"atome": WASSER, "beschriftungen": [{"atom": 0}]}, False),
    ({"atome": WASSER, "beschriftungen": [{"text": "O"}]}, False), ({"atome": WASSER, "beschriftungen": [{"atom": 0, "text": ""}]}, False),
    ({"atome": WASSER, "beschriftungen": [{"atom": 0, "text": "x" * 40}]}, True),
    ({"atome": WASSER, "beschriftungen": [{"atom": 0, "text": "x" * 41}]}, False),
    ({"atome": WASSER, "beschriftungen": [{"atom": 0, "text": "O", "farbe": "ok"}]}, False),
    ({"atome": WASSER, "beschriftungen": [{"atom": i % 3, "text": "a"} for i in range(20)]}, True),
    ({"atome": WASSER, "beschriftungen": [{"atom": i % 3, "text": "a"} for i in range(21)]}, False),
    ({"atome": WASSER, "beschriftungen": None}, False), ({"atome": WASSER, "beschriftungen": "O"}, False),
    ({"atome": WASSER, "darstellung": "kugel-stab"}, True), ({"atome": WASSER, "darstellung": "kalotte"}, True),
    ({"atome": WASSER, "darstellung": "Kalotte"}, False), ({"atome": WASSER, "darstellung": "stab"}, False),
    ({"atome": WASSER, "darstellung": ""}, False), ({"atome": WASSER, "darstellung": None}, False),
    ({"atome": WASSER, "name": "x" * 60}, True), ({"atome": WASSER, "name": "x" * 61}, False), ({"atome": WASSER, "name": 5}, False),
    ({"atome": WASSER, "name": ["Wasser"]}, False),
])
def test_p5b_molecule_limits(fields, ok):
    if ok:
        got = teil_block("molekuel", fields)
        assert len(got["atome"]) == len(fields["atome"]) and len(got["bindungen"]) == len(fields.get("bindungen", []))
        assert all(b["ordnung"] in (1, 2, 3) for b in got["bindungen"]) and got["darstellung"] == fields.get("darstellung", "kugel-stab")
        assert schema.validate(teil("molekuel", {k: v for k, v in got.items() if k not in ("typ", "form")}))["bausteine"][0] == got
    else:
        teil_bad("molekuel", fields)


def test_p5b_molecule_bonds_get_order_one_and_keep_their_direction():
    got = teil_block("molekuel", {"atome": WASSER, "bindungen": [{"von": 1, "bis": 0}, {"von": 0, "bis": 2, "ordnung": 2}]})
    assert got["bindungen"] == [{"von": 1, "bis": 0, "ordnung": 1}, {"von": 0, "bis": 2, "ordnung": 2}]


@pytest.mark.parametrize("orbital", list(schema.ORBITALE))
def test_p5b_every_orbital_passes(orbital):
    assert teil_block("orbital", {"orbital": orbital}) == {"typ": "teilchen", "form": "orbital", "orbital": orbital, "punkte": 2500,
                                                            "startwert": 1}


def test_p5b_orbital_list_is_fixed():
    assert schema.ORBITALE == ("1s", "2s", "2p_x", "2p_y", "2p_z", "3s", "3p_x", "3p_y", "3p_z", "3d_xy", "3d_xz", "3d_yz", "3d_x2-y2", "3d_z2")


@pytest.mark.parametrize("fields,ok", [
    ({"orbital": "1s", "punkte": 500}, True), ({"orbital": "1s", "punkte": 5000}, True), ({"orbital": "1s", "punkte": 499}, False),
    ({"orbital": "1s", "punkte": 5001}, False), ({"orbital": "1s", "punkte": 2500.0}, False), ({"orbital": "1s", "punkte": True}, False),
    ({"orbital": "1s", "startwert": 0}, True), ({"orbital": "1s", "startwert": 2_147_483_647}, True),
    ({"orbital": "1s", "startwert": -1}, False), ({"orbital": "1s", "startwert": 2_147_483_648}, False),
    ({"orbital": "1s", "startwert": 1.0}, False), ({"orbital": "1s", "startwert": "1"}, False),
    ({"orbital": "2p"}, False), ({"orbital": "2P_z"}, False), ({"orbital": "2pz"}, False), ({"orbital": "4s"}, False), ({"orbital": "3d_x2y2"}, False),
    ({"orbital": "3d_x2-y2 "}, False), ({"orbital": ""}, False), ({"orbital": None}, False), ({"orbital": 1}, False), ({"orbital": True}, False),
    ({"orbital": ["1s"]}, False), ({"orbital": {"1s": 1}}, False), ({}, False), ({"punkte": 500}, False),
    ({"orbital": "1s", "formel": "exp(-r)"}, False), ({"orbital": "1s", "shader": "void main(){}"}, False),
])
def test_p5b_orbital_limits(fields, ok):
    if ok:
        got = teil_block("orbital", fields)
        assert got == {"typ": "teilchen", "form": "orbital", "orbital": "1s", "punkte": fields.get("punkte", 2500),
                       "startwert": fields.get("startwert", 1)}
    else:
        teil_bad("orbital", fields)


@pytest.mark.parametrize("form", ["Molekuel", "molekül", "atome", "Orbital", "", None, 1, True, ["atom"], {"atom": 1}])
def test_p5b_unknown_forms_are_rejected(form):
    teil_bad(form, T_MIN["atom"])


def test_p5b_teilchen_without_form_is_rejected():
    with pytest.raises(schema.ViewError) as e:
        schema.validate({"id": "t", "art": "teilchen", "titel": "T", "bausteine": [{"typ": "teilchen", **T_MIN["molekuel"]}]})
    assert e.value.code == "bad_block_1"


@pytest.mark.parametrize("form", list(T_MIN))
@pytest.mark.parametrize("extra", [{"formel": "x"}, {"skript": "x"}, {"html": "<b>"}, {"adresse": "https://example.org"}, {"pfad": "C:/x"},
                                   {"datei": "x.pdb"}, {"Name": "x"}])
def test_p5b_unknown_fields_are_rejected_per_form(form, extra):
    teil_bad(form, {**T_MIN[form], **extra})


@pytest.mark.parametrize("form,other", [("molekuel", {"element": "H"}), ("molekuel", {"orbital": "1s"}), ("atom", {"atome": WASSER}),
                                        ("atom", {"punkte": 500}), ("orbital", {"element": "H"}), ("orbital", {"darstellung": "kalotte"}),
                                        ("orbital", {"schalen": [1]})])
def test_p5b_fields_of_another_form_are_rejected(form, other):
    teil_bad(form, {**T_MIN[form], **other})


def _teilchen_numeric_fields():
    for i in range(3):
        yield lambda v, i=i: teil("molekuel", {"atome": [{"element": "H", "position": [v if j == i else 0 for j in range(3)]}]})
    yield lambda v: teil("molekuel", {"atome": WASSER, "bindungen": [{"von": v, "bis": 1}]})
    yield lambda v: teil("molekuel", {"atome": WASSER, "bindungen": [{"von": 0, "bis": v}]})
    yield lambda v: teil("molekuel", {"atome": WASSER, "bindungen": [{"von": 0, "bis": 1, "ordnung": v}]})
    yield lambda v: teil("molekuel", {"atome": WASSER, "beschriftungen": [{"atom": v, "text": "x"}]})
    yield lambda v: teil("atom", {"element": "Na", "neutronen": v})
    yield lambda v: teil("atom", {"element": "Na", "ladung": v})
    yield lambda v: teil("atom", {"element": "Na", "schalen": [2, 8, v]})
    yield lambda v: teil("orbital", {"orbital": "1s", "punkte": v})
    yield lambda v: teil("orbital", {"orbital": "1s", "startwert": v})


TEILCHEN_NUMERIC = list(_teilchen_numeric_fields())


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 10**400, -10**400, True, False, "1", None, [1], {"a": 1}])
@pytest.mark.parametrize("make", TEILCHEN_NUMERIC)
def test_p5b_non_finite_and_non_numbers_are_rejected_everywhere(make, value):
    with pytest.raises(schema.ViewError) as e:
        schema.validate(make(value))
    assert e.value.code == "bad_block_1"


@pytest.mark.parametrize("make,valid", [(TEILCHEN_NUMERIC[3], 0), (TEILCHEN_NUMERIC[4], 2), (TEILCHEN_NUMERIC[5], 2), (TEILCHEN_NUMERIC[6], 1),
                                        (TEILCHEN_NUMERIC[7], 12), (TEILCHEN_NUMERIC[8], 0), (TEILCHEN_NUMERIC[9], 1),
                                        (TEILCHEN_NUMERIC[10], 2500), (TEILCHEN_NUMERIC[11], 7)])
def test_p5b_integer_fields_take_only_real_integers(make, valid):
    once = schema.validate(make(valid))                                           # als ganze Zahl gültig ...
    assert schema.validate(once) == once
    with pytest.raises(schema.ViewError) as e:                                    # ... als Kommazahl mit gleichem Wert abgelehnt
        schema.validate(make(float(valid)))
    assert e.value.code == "bad_block_1"


def test_p5b_text_in_teilchen_loses_control_characters_and_control_only_label_is_rejected():
    got = teil_block("molekuel", {"atome": WASSER, "name": JUNK + "Wasser" + chr(0x202e) + chr(0) + "  H2O" + JUNK,
                                  "beschriftungen": [{"atom": 0, "text": "Sauer" + chr(0x2066) + "stoff" + chr(10)}]})
    assert got["name"] == "Wasser H2O" and got["beschriftungen"][0]["text"] == "Sauer stoff"
    assert teil_block("molekuel", {"atome": WASSER, "name": JUNK})["name"] == ""               # name ist frei: leer
    teil_bad("molekuel", {"atome": WASSER, "beschriftungen": [{"atom": 0, "text": JUNK}]})     # Beschriftung braucht Text
    teil_bad("molekuel", {"atome": WASSER, "beschriftungen": [{"atom": 0, "text": "x" * 20 + chr(0x202e) + "x" * 20}]})   # 41 nach dem Säubern


def _big_molecule():
    pos = -199.12345678901234                                                      # lange Kommazahlen in jeder Lage
    return {"name": "N" * 60, "atome": [{"element": "He", "position": [pos, pos, pos]} for _ in range(300)],
            "beschriftungen": [{"atom": 299 - i, "text": "x" * 40} for i in range(20)], "darstellung": "kalotte"}


def test_p5b_three_hundred_atoms_with_full_positions_stay_under_the_view_size_limit():
    view = teil("molekuel", _big_molecule())
    size = len(json.dumps(view, ensure_ascii=False).encode("utf-8"))
    out = schema.validate(view)
    out_size = len(json.dumps(out, ensure_ascii=False).encode("utf-8"))
    assert size < schema.MAX_JSON and out_size < schema.MAX_JSON and size < 31_000             # gemessen: 30 369 Byte
    assert schema.validate(out) == out and len(out["bausteine"][0]["atome"]) == 300
    full = _big_molecule()                                                         # dazu 400 Bindungen mit ordnung: 45 950 Byte
    full["bindungen"] = [{"von": a, "bis": a + d, "ordnung": 3} for a in range(300) for d in (1, 2) if a + d < 300][:400]
    out = schema.validate(teil("molekuel", full))
    assert len(json.dumps(out, ensure_ascii=False).encode("utf-8")) < schema.MAX_JSON and len(out["bausteine"][0]["bindungen"]) == 400


def test_p5b_three_hundred_and_one_atoms_are_rejected():
    fields = _big_molecule()
    fields["atome"].append({"element": "H", "position": [0, 0, 0]})
    teil_bad("molekuel", fields)


def test_p5b_filled_defaults_never_push_a_view_over_the_size_limit_of_the_second_check():
    mol = {"atome": [{"element": "H", "position": [0, 0, i]} for i in range(30)], "bindungen": _bonds(400)}   # ohne ordnung
    pad = {"typ": "text", "absaetze": ["x" * 1200] * 12}

    def view(extra):                                                               # extra Zeichen Fülltext in Absätzen zu 1200
        paras = ["y" * min(1200, extra - i) for i in range(0, extra, 1200)]
        return {"id": "v", "art": "teilchen", "titel": "T", "bausteine": [{"typ": "teilchen", "form": "molekuel", **mol},
                                                                          pad, pad, {"typ": "text", "absaetze": paras}]}

    def size(v):
        return len(json.dumps(v, ensure_ascii=False).encode("utf-8"))

    extra = schema.MAX_JSON - size(view(1)) - 1000
    raw = view(extra)
    assert schema.MAX_JSON - 1100 <= size(raw) <= schema.MAX_JSON                  # Eingabe knapp unter der Grenze ...
    with pytest.raises(schema.ViewError) as e:                                     # ... ergänzt (400 x "ordnung": 1) aber darüber
        schema.validate(raw)
    assert e.value.code == "too_large"
    ok = view(extra - 6000)                                                        # 400 x 14 Byte = 5600: passt noch
    once = schema.validate(ok)
    assert size(once) <= schema.MAX_JSON and schema.validate(once) == once


def p5_view(*blocks):
    return {"id": "v", "art": "teilchen", "titel": "T", "bausteine": list(blocks)}


SIM_B = {"typ": "simulation", "modell": "pendel", "parameter": SIM_MIN["pendel"]}
MOL_B = {"typ": "teilchen", "form": "molekuel", **T_MIN["molekuel"]}
ORB_B = {"typ": "teilchen", "form": "orbital", **T_MIN["orbital"]}
ATOM_B = {"typ": "teilchen", "form": "atom", **T_MIN["atom"]}
TEXT_B = {"typ": "text", "absaetze": ["a"]}
SZ_B = {"typ": "szene3d", "szenen": [{"name": "s", "objekte": [BOX]}]}
PLAN_B = {"typ": "plan2d", "elemente": [{"art": "kreis", "x": 0, "y": 0, "r": 1}]}


@pytest.mark.parametrize("blocks,code", [
    ([SIM_B, SIM_B], None), ([SIM_B, SIM_B, SIM_B], "bad_block_3"), ([SIM_B, TEXT_B, SIM_B, TEXT_B, SIM_B], "bad_block_5"),
    ([MOL_B, MOL_B], None), ([ORB_B, ORB_B], None), ([MOL_B, ORB_B], None), ([MOL_B, MOL_B, MOL_B], "bad_block_3"),
    ([ORB_B, ORB_B, ORB_B], "bad_block_3"), ([MOL_B, ATOM_B, ORB_B, ATOM_B, MOL_B], "bad_block_5"),
    ([ATOM_B] * 12, None),                                                          # Atome sind statisches SVG: keine Grenze außer 12 Bausteinen
    ([SIM_B, SIM_B, MOL_B, ORB_B, ATOM_B, ATOM_B, TEXT_B], None),                  # gemischt: jede Grenze für sich
    ([SIM_B, MOL_B, SIM_B, ORB_B, ATOM_B, SIM_B], "bad_block_6"), ([SIM_B, MOL_B, SIM_B, ORB_B, ATOM_B, ORB_B], "bad_block_6"),
    ([MOL_B, SIM_B, ORB_B, SIM_B, MOL_B, SIM_B], "bad_block_5"),                    # der erste Baustein über einer Grenze
    # szene3d nutzt auch WebGL: zählt mit Molekül und Orbital zusammen
    ([SZ_B, SZ_B], None), ([SZ_B, SZ_B, SZ_B], "bad_block_3"), ([SZ_B, MOL_B], None), ([ORB_B, SZ_B], None),
    ([SZ_B, MOL_B, ORB_B], "bad_block_3"), ([MOL_B, ORB_B, SZ_B], "bad_block_3"), ([ORB_B, SZ_B, ATOM_B, SZ_B], "bad_block_4"),
    ([SZ_B, SIM_B, SIM_B, MOL_B, ATOM_B, TEXT_B], None), ([SZ_B, SIM_B, SZ_B, SIM_B, SIM_B], "bad_block_5"),
    ([SZ_B, PLAN_B, PLAN_B, PLAN_B, SZ_B], None),                                    # plan2d ist SVG: zählt nicht
])
def test_p5b_at_most_two_simulations_and_two_webgl_particles_per_view(blocks, code):
    if code is None:
        once = schema.validate(p5_view(*blocks))
        assert len(once["bausteine"]) == len(blocks) and schema.validate(once) == once
    else:
        with pytest.raises(schema.ViewError) as e:
            schema.validate(p5_view(*blocks))
        assert e.value.code == code


def test_zeige_tool_names_the_teilchen_kind_block_forms_and_new_models():
    props = ch.ZEIGE_TOOL["inputSchema"]["properties"]
    assert "teilchen" in props["art"]["enum"] and "teilchen" in props["bausteine"]["items"]["properties"]["typ"]["enum"]
    desc = props["bausteine"]["description"]
    for name in ("teilchen", "molekuel", "atome", "element", "position", "Ångström", "bindungen", "ordnung", "beschriftungen", "darstellung",
                 "kugel-stab", "kalotte", "neutronen", "ladung", "schalen", "orbital", "3d_x2-y2", "3d_z2", "punkte", "startwert",
                 "doppelpendel", "laenge1", "laenge2", "masse1", "masse2", "winkel1", "winkel2", "welle", "wellen", "amplitude",
                 "wellenlaenge", "frequenz", "Hz", "richtung", "rechts", "links", "bereich", "anziehung", "Sonnenmassen", "Index ab 0"):
        assert name in desc, name
    assert "teilchen" in ch.ZEIGE_TOOL["description"] and "keine Formeln" in ch.ZEIGE_TOOL["description"]
    assert all(m in ch.INSTRUCTIONS for m in ("teilchen", "molekuel", "atom", "orbital", "doppelpendel", "welle"))
    assert "nie Formeln oder Code" in ch.INSTRUCTIONS and "keine Messung" in ch.INSTRUCTIONS


def test_p5b_teilchen_is_listed_by_tools_list_and_travels_through_the_real_channel_into_the_bridge_store(channel):
    c, out, root = channel
    c.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    zeige = {t["name"]: t for t in json.loads(out.getvalue().splitlines()[-1])["result"]["tools"]}["zeige"]
    assert "teilchen" in zeige["inputSchema"]["properties"]["art"]["enum"]
    assert "teilchen" in zeige["inputSchema"]["properties"]["bausteine"]["items"]["properties"]["typ"]["enum"]
    assert all(n in zeige["inputSchema"]["properties"]["bausteine"]["description"] for n in (*T_MIN, "doppelpendel", "welle", "anziehung"))
    b = br.Bridge(root)
    view = p5_view({"typ": "teilchen", "form": "molekuel", "name": "Wasser", "atome": WASSER}, ATOM_B, ORB_B,
                   {"typ": "simulation", "modell": "welle", "parameter": SIM_MIN["welle"]})
    assert call(c, out, view)["content"][0]["text"] == "Wird gezeigt."
    r = call(c, out, {**teil("molekuel", {"atome": WASSER, "bindungen": [{"von": 0, "bis": 7}]}), "id": "kaputt"})
    assert r["isError"] is True and "bad_block_1" in r["content"][0]["text"]
    r = call(c, out, {**p5_view(MOL_B, ORB_B, MOL_B), "id": "zu-viele"})
    assert r["isError"] is True and "bad_block_3" in r["content"][0]["text"]
    c.say("Hier das Wassermolekül.")
    assert b.fetch() == ("ok", ["Hier das Wassermolekül."])
    got = {i["id"]: i for i in b.stage.since(0)[0]}
    assert set(got) == {"v"} and got["v"]["art"] == "teilchen"
    blocks = got["v"]["bausteine"]
    assert blocks[0] == {"typ": "teilchen", "form": "molekuel", "name": "Wasser", "atome": WASSER, "bindungen": [], "beschriftungen": [],
                         "darstellung": "kugel-stab"}
    assert blocks[1] == {"typ": "teilchen", **T_FILLED["atom"], "form": "atom"} and blocks[2] == {"typ": "teilchen", "form": "orbital", **T_FILLED["orbital"]}
    assert blocks[3]["parameter"] == SIM_FILLED["welle"]


def test_p5b_bridge_drops_invalid_teilchen_that_got_past_the_channel(channel):
    c, out, root = channel
    b = br.Bridge(root)
    c.show(teil("atom", T_MIN["atom"]))
    c._views.append({**teil("molekuel", {"atome": WASSER, "bindungen": [{"von": 0, "bis": 0}]}), "id": "selbst"})       # Bindung auf sich selbst
    c._views.append({**teil("atom", {"element": "Na", "schalen": [2, 8, 2]}), "id": "summe"})                         # falsche Schalensumme
    c._views.append({**teil("molekuel", {"atome": [{"element": "Xx", "position": [0, 0, 0]}]}), "id": "element"})      # unbekanntes Element
    c._views.append({**teil("orbital", {"orbital": "4f"}), "id": "orbital"})                                           # unbekanntes Orbital
    c._views.append({**p5_view(SIM_B, SIM_B, SIM_B), "id": "drei-sim"})                                               # über der Grenze je Ansicht
    c._views.append({**teil("atom", {"element": "Sc"}), "id": "ohne-schalen"})                                        # über 20 ohne Schalen
    c.say("Hier das Atom.")
    assert b.fetch() == ("ok", ["Hier das Atom."])
    assert [i["id"] for i in b.stage.since(0)[0]] == ["t"]


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
    *TEILCHEN_NUMERIC,
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
    lambda v: sim("umlauf", {"zentralmasse": 1, "koerper": [ERDE], "anziehung": v}),
    lambda v: sim("welle", {"wellen": [{**W1, "richtung": v}]}),
    lambda v: teil(v, T_MIN["atom"]),
    lambda v: teil("molekuel", {"atome": [{"element": v, "position": [0, 0, 0]}]}),
    lambda v: teil("molekuel", {"atome": WASSER, "darstellung": v}),
    lambda v: teil("molekuel", {"atome": WASSER, "name": v}),
    lambda v: teil("molekuel", {"atome": WASSER, "beschriftungen": [{"atom": 0, "text": v}]}),
    lambda v: teil("atom", {"element": v}),
    lambda v: teil("orbital", {"orbital": v}),
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
            *[sim(m, SIM_MIN[m]) for m in SIM_MIN],
            *[teil(f, T_FULL[f]) for f in T_FULL], *[teil(f, T_MIN[f]) for f in T_MIN],
            teil("atom", {"element": "H", "ladung": 1}), p5_view(SIM_B, MOL_B, ORB_B, ATOM_B, SIM_B),
            *[se(f) for f in SE_ALL], *[schema.validate(se(f)) for f in SE_ALL]]           # P7: auch die schon geprüfte Form


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
            "gas", "pendel", "umlauf", 0.05, 1000, 100.0, "doppelpendel", "welle", "links", "molekuel", "atom", "orbital", "H", "Og",
            "kalotte", "3d_z2", "teilchen", "simulation", 2, 3, 300, 32, 7, -3]
    examples = _fuzz_examples()
    for _ in range(4000):
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


# --- P7 Stufe 1: eigene Simulation als Daten (`sim_eigen`, docs/ui-p7-plan.md) ---------------------------------

SE_MIN_ODE = {"name": "Zerfall", "form": "ode", "zustand": [{"name": "u", "start": 1}], "ableitungen": {"u": "-u"},
              "darstellung": [{"form": "zeitreihe", "groessen": ["u"]}]}
SE_FILLED_ODE = {                                                                  # was die Oberfläche aus SE_MIN_ODE bekommt
    "typ": "sim_eigen", "form": "ode", "name": "Zerfall", "beschreibung": "", "parameter": [], "dt": 0.01, "laufzeit": 30, "tempo": 1,
    "spur": True, "zustand": [{"name": "u", "start": 1, "einheit": ""}], "hilf": [],
    "ableitungen": {"u": {"rpn": [["v", 1], ["o", "neg"]], "tex": "-u"}}, "kennwerte": [], "erhaltung": None,
    "darstellung": [{"form": "zeitreihe", "groessen": ["u"]}], "env": {"ode": ["t", "u"]}, "integrator": "rk4", "kosten": 8}
SE_MIN_TEIL = {"name": "Staub", "form": "teilchen", "anzahl": 1, "kasten": [1, 1], "darstellung": [{"form": "koerper"}]}
SE_FILLED_TEIL = {
    "typ": "sim_eigen", "form": "teilchen", "name": "Staub", "beschreibung": "", "parameter": [], "dt": 0.005, "laufzeit": 30, "tempo": 1,
    "spur": True, "anzahl": 1, "start": "linie", "punkte": [], "startwert": 1, "masse": 1, "kraft": None, "paar": None, "federn": None,
    "fest": [], "waende": "reflektieren", "kasten": [1, 1], "kennwerte": [], "erhaltung": None, "darstellung": [{"form": "koerper"}],
    "env": {"kraft": ["t", "x", "y", "vx", "vy", "m"], "paar": ["r"]}, "integrator": "verlet", "kosten": 0}
SE_PENDEL = {"name": "Gedämpftes Pendel", "form": "ode", "beschreibung": "Pendel mit Reibung.",
             "parameter": [{"name": "g", "wert": 9.81, "min": 0.1, "max": 30, "einheit": "m/s²"},
                           {"name": "l", "wert": 1, "min": 0.1, "max": 10, "einheit": "m"},
                           {"name": "d", "wert": 0.2, "min": 0, "max": 5, "einheit": "1/s"}],
             "zustand": [{"name": "phi", "start": 1.2, "einheit": "rad"}, {"name": "w", "start": 0, "einheit": "rad/s"}],
             "ableitungen": {"phi": "w", "w": "-g/l*sin(phi) - d*w"},
             "darstellung": [{"form": "koerper", "x": "l*sin(phi)", "y": "-l*cos(phi)", "anker": [0, 0]}, {"form": "zeitreihe", "groessen": ["phi"]}],
             "kennwerte": [{"name": "Energie", "formel": "0.5*(l*w)^2 + g*l*(1-cos(phi))", "einheit": "J/kg"}]}
SE_RAEUBER = {"name": "Räuber und Beute", "form": "ode",
              "parameter": [{"name": n, "wert": w, "min": 0, "max": 5} for n, w in (("a", 1.1), ("b", 0.4), ("c", 0.4), ("dd", 0.1))],
              "zustand": [{"name": "B", "start": 10}, {"name": "R", "start": 5}],
              "ableitungen": {"B": "a*B - b*B*R", "R": "dd*B*R - c*R"}, "erhaltung": "dd*B - c*log(B) + b*R - a*log(R)",
              "darstellung": [{"form": "zeitreihe", "groessen": ["B", "R"]}, {"form": "phasenraum", "x": "B", "y": "R"}]}
SE_LORENZ = {"name": "Lorenz", "form": "ode", "dt": 0.005,
             "parameter": [{"name": "s", "wert": 10, "min": 0, "max": 50}, {"name": "r", "wert": 28, "min": 0, "max": 100},
                           {"name": "bb", "wert": 2.6667, "min": 0, "max": 10}],
             "zustand": [{"name": "x", "start": 1}, {"name": "y", "start": 1}, {"name": "z", "start": 1}],
             "ableitungen": {"x": "s*(y-x)", "y": "x*(r-z) - y", "z": "x*y - bb*z"},
             "darstellung": [{"form": "phasenraum", "x": "x", "y": "z"}, {"form": "zeitreihe", "groessen": ["x"]}]}
SE_KETTE = {"name": "Federkette", "form": "teilchen", "anzahl": 12, "start": "linie", "kasten": [4, 3], "waende": "reflektieren",
            "fest": [0, 11], "masse": 0.1,                                     # im Plan als Parameter m; m ist im Teilchen-Platz die Masse
            "parameter": [{"name": "g", "wert": 9.81, "min": 0, "max": 30}, {"name": "c", "wert": 0.3, "min": 0, "max": 5}],
            "kraft": {"fx": "-c*vx", "fy": "-m*g - c*vy"}, "federn": {"kette": True, "k": 40, "l0": 0.25, "daempfung": 0.05},
            "darstellung": [{"form": "koerper"}]}
SE_GAS = {"name": "Abstoßende Teilchen", "form": "teilchen", "anzahl": 3, "start": "liste", "kasten": [10, 5], "waende": "periodisch",
          "punkte": [[1, 1], [2, 2, 0.5, -0.5], [3, 1]], "masse": 2, "startwert": 7, "dt": 0.001, "laufzeit": 60, "tempo": 2.5, "spur": False,
          "beschreibung": "Drei Teilchen.", "parameter": [{"name": "k", "wert": 1, "min": 0, "max": 10, "einheit": "N m²"}],
          "paar": {"f_r": "k/r^2", "reichweite": 4, "mindestabstand": 0.1}, "federn": {"paare": [[0, 2]], "k": 5, "l0": 1},
          "fest": [1], "darstellung": [{"form": "koerper"}, {"form": "pfeile"}]}
SE_ALL = [SE_MIN_ODE, SE_MIN_TEIL, SE_PENDEL, SE_RAEUBER, SE_LORENZ, SE_KETTE, SE_GAS]
SE_JUNK = chr(0x202e) + chr(0) + chr(27) + chr(0x2066) + chr(10)


def se(fields, art="simulation"):
    return {"id": "se", "art": art, "titel": "Eigene Simulation", "bausteine": [{"typ": "sim_eigen", **fields}]}


def se_block(fields):
    return schema.validate(se(fields))["bausteine"][0]


def se_bad(fields, detail=None):
    with pytest.raises(schema.ViewError) as e:
        schema.validate(se(fields))
    assert e.value.code == "bad_block_1", e.value.code
    if detail is not None:
        assert e.value.detail == detail, e.value.detail
    return e.value


def ode(**kw):
    return {**SE_MIN_ODE, **kw}


def teil2(**kw):
    return {**SE_MIN_TEIL, **kw}


def _states(n):
    return {"zustand": [{"name": f"u{i}", "start": 0} for i in range(n)], "ableitungen": {f"u{i}": "0" for i in range(n)},
            "darstellung": [{"form": "zeitreihe", "groessen": ["u0"]}]}


def _bal(k, leaf):
    if k == 1:
        return leaf
    return "(" + _bal(k // 2, leaf) + "+" + _bal(k - k // 2, leaf) + ")"


def test_p7_minimal_ode_gets_every_default():
    assert se_block(SE_MIN_ODE) == SE_FILLED_ODE


def test_p7_minimal_particles_get_every_default():
    assert se_block(SE_MIN_TEIL) == SE_FILLED_TEIL


def test_p7_pendulum_example_keeps_every_value_and_gets_rpn_tex_and_env():
    b = se_block(SE_PENDEL)
    assert b["env"] == {"ode": ["t", "phi", "w", "g", "l", "d"]}
    assert [p["name"] for p in b["parameter"]] == ["g", "l", "d"] and b["parameter"][0] == SE_PENDEL["parameter"][0]
    assert b["ableitungen"]["phi"] == {"rpn": [["v", 2]], "tex": "w"}
    assert b["ableitungen"]["w"]["rpn"] == [["v", 3], ["o", "neg"], ["v", 4], ["o", "/"], ["v", 1], ["f", "sin"], ["o", "*"], ["v", 5],
                                            ["v", 2], ["o", "*"], ["o", "-"]]
    assert b["darstellung"][0]["anker"] == [0, 0] and b["darstellung"][1] == {"form": "zeitreihe", "groessen": ["phi"]}
    assert b["kennwerte"][0]["name"] == "Energie" and b["kennwerte"][0]["einheit"] == "J/kg"
    assert b["beschreibung"] == "Pendel mit Reibung." and b["integrator"] == "rk4" and b["kosten"] == 4 * (1 + 11)
    assert "-g/l" not in json.dumps(b)                                         # kein Formeltext in der geprüften Ansicht


def test_p7_predator_prey_lorenz_and_spring_chain_examples_pass():
    rb = se_block(SE_RAEUBER)
    assert rb["erhaltung"]["rpn"][-1] == ["o", "-"] and rb["darstellung"][1] == {"form": "phasenraum", "x": "B", "y": "R"}
    assert se_block(SE_LORENZ)["dt"] == 0.005
    k = se_block(SE_KETTE)
    assert k["federn"] == {"paare": [[i, i + 1] for i in range(11)], "k": 40, "l0": 0.25, "daempfung": 0.05}
    assert k["env"]["kraft"] == ["t", "x", "y", "vx", "vy", "m", "g", "c"] and k["masse"] == 0.1
    assert k["integrator"] == "euler_semi" and k["kosten"] == (4 + 8) * 12


def test_p7_full_particle_example_keeps_every_value():
    b = se_block(SE_GAS)
    assert b["punkte"] == [[1, 1, 0, 0], [2, 2, 0.5, -0.5], [3, 1, 0, 0]] and b["start"] == "liste" and b["startwert"] == 7
    assert b["paar"]["reichweite"] == 4 and b["paar"]["mindestabstand"] == 0.1 and b["paar"]["f_r"]["tex"] == r"\frac{k}{r^{2}}"
    assert b["federn"] == {"paare": [[0, 2]], "k": 5, "l0": 1, "daempfung": 0} and b["fest"] == [1] and b["waende"] == "periodisch"
    assert (b["dt"], b["laufzeit"], b["tempo"], b["spur"], b["masse"]) == (0.001, 60, 2.5, False, 2)
    assert b["darstellung"] == [{"form": "koerper"}, {"form": "pfeile"}] and b["integrator"] == "verlet" and b["kosten"] == 5 * 3   # k/r^2: 5 Knoten, 3 Paare
    assert b["env"] == {"kraft": ["t", "x", "y", "vx", "vy", "m", "k"], "paar": ["r", "k"]}


def test_p7_pair_range_gets_a_default_minimum_distance():
    assert se_block(teil2(anzahl=2, paar={"f_r": "1", "reichweite": 0.5}))["paar"]["mindestabstand"] == 0.005


@pytest.mark.parametrize("fields", SE_ALL)
@pytest.mark.parametrize("art", ["simulation", "antwort", "lernen"])
def test_p7_checked_views_pass_the_second_check_unchanged(fields, art):
    v = schema.validate(se(fields, art))
    assert schema.validate(v) == v
    assert schema.validate(json.loads(json.dumps(v))) == v                    # auch nach dem Weg als JSON


@pytest.mark.parametrize("change", [
    lambda b: b.update(env={"ode": ["t", "phi", "w", "l", "g", "d"]}), lambda b: b.update(env=["t"]), lambda b: b.update(kosten=1),
    lambda b: b.update(integrator="verlet"), lambda b: b["ableitungen"]["w"]["rpn"].__setitem__(0, ["v", 4]),
    lambda b: b["ableitungen"]["w"].update(tex=r"\text{Freigabe}"), lambda b: b["ableitungen"]["phi"]["rpn"].append(["c", 1.0]),
    lambda b: b["kennwerte"][0]["formel"]["rpn"].__setitem__(0, ["v", 99]), lambda b: b["darstellung"][0]["x"].update(rpn=[["f", "sin"]]),
    lambda b: b["ableitungen"].update(phi={"rpn": [["v", 2]], "tex": "w", "text": "w"}),
])
def test_p7_tampered_checked_views_are_rejected(change):
    v = schema.validate(se(SE_PENDEL))
    change(v["bausteine"][0])
    with pytest.raises(schema.ViewError) as e:
        schema.validate(v)
    assert e.value.code == "bad_block_1"


SE_EDGES = [  # (Felder, gültig)
    (ode(**_states(12)), True), (ode(**_states(13)), False),
    (ode(parameter=[{"name": f"p{i}", "wert": 0, "min": 0, "max": 1} for i in range(12)]), True),
    (ode(parameter=[{"name": f"p{i}", "wert": 0, "min": 0, "max": 1} for i in range(13)]), False),
    (ode(hilf=[{"name": f"h{i}", "formel": "u"} for i in range(12)]), True), (ode(hilf=[{"name": f"h{i}", "formel": "u"} for i in range(13)]), False),
    (ode(kennwerte=[{"name": "k", "formel": "u"}] * 4), True), (ode(kennwerte=[{"name": "k", "formel": "u"}] * 5), False),
    (ode(darstellung=[{"form": "zeitreihe", "groessen": ["u"]}] * 2), True), (ode(darstellung=[{"form": "zeitreihe", "groessen": ["u"]}] * 3), False),
    (ode(darstellung=[]), False),
    (ode(**{**_states(4), "darstellung": [{"form": "zeitreihe", "groessen": ["u0", "u1", "u2", "u3"]}]}), True),
    (ode(**{**_states(5), "darstellung": [{"form": "zeitreihe", "groessen": ["u0", "u1", "u2", "u3", "u4"]}]}), False),
    (ode(darstellung=[{"form": "zeitreihe", "groessen": []}]), False),
    (ode(ableitungen={"u": "u" + " " * 199}), True), (ode(ableitungen={"u": "u" + " " * 200}), False),
    (ode(ableitungen={"u": "u"}, hilf=[{"name": f"h{i}", "formel": _bal(25, "u")} for i in range(11)] + [{"name": "hz", "formel": "-" + _bal(30, "u")}]), True),
    (ode(ableitungen={"u": "-u"}, hilf=[{"name": f"h{i}", "formel": _bal(25, "u")} for i in range(11)] + [{"name": "hz", "formel": "-" + _bal(30, "u")}]), False),
    (teil2(anzahl=300), True), (teil2(anzahl=301), False), (teil2(anzahl=0), False),
    (teil2(anzahl=100, paar={"f_r": "1", "reichweite": 1}), True), (teil2(anzahl=101, paar={"f_r": "1", "reichweite": 1}), False),
    (teil2(anzahl=300, federn={"paare": [[i, j] for i in range(30) for j in range(i + 1, 30)][:400], "k": 1, "l0": 0}), True),
    (teil2(anzahl=300, federn={"paare": [[i, j] for i in range(30) for j in range(i + 1, 30)][:401], "k": 1, "l0": 0}), False),
    (teil2(anzahl=100, paar={"f_r": "-" + _bal(15, "r"), "reichweite": 1}, kraft={"fx": _bal(4, "x"), "fy": "-" + _bal(4, "y")}), True),
    (teil2(anzahl=100, paar={"f_r": "-" + _bal(15, "r"), "reichweite": 1}, kraft={"fx": "-" + _bal(4, "x"), "fy": "-" + _bal(4, "y")}), False),
    (ode(dt=1e-5), True), (ode(dt=0.99e-5), False), (ode(dt=1), True), (ode(dt=1.001), False), (ode(dt=0), False),
    (ode(laufzeit=5), True), (ode(laufzeit=4.99), False), (ode(laufzeit=60), True), (ode(laufzeit=60.01), False),
    (ode(tempo=0.1), True), (ode(tempo=0.099), False), (ode(tempo=100), True), (ode(tempo=100.1), False), (ode(tempo=0), False),
    (teil2(kasten=[0.1, 0.1]), True), (teil2(kasten=[0.0999, 0.1]), False), (teil2(kasten=[1000, 1000]), True),
    (teil2(kasten=[1000.1, 1000]), False), (teil2(kasten=[1, 10]), True), (teil2(kasten=[1, 10.01]), False), (teil2(kasten=[1]), False),
    (ode(parameter=[{"name": "p", "wert": 1, "min": 1, "max": 2}]), True), (ode(parameter=[{"name": "p", "wert": 2, "min": 1, "max": 2}]), True),
    (ode(parameter=[{"name": "p", "wert": 0.99, "min": 1, "max": 2}]), False), (ode(parameter=[{"name": "p", "wert": 1, "min": 1, "max": 1}]), False),
    (ode(parameter=[{"name": "p", "wert": 0, "min": -1e12, "max": 1e12}]), True),
    (ode(parameter=[{"name": "p", "wert": 0, "min": -1.0001e12, "max": 1}]), False),
    (ode(zustand=[{"name": "u", "start": 1e9}]), True), (ode(zustand=[{"name": "u", "start": -1.000001e9}]), False),
    (teil2(masse=1e6), True), (teil2(masse=1.0001e6), False), (teil2(masse=0), False), (teil2(masse=-1), False),
    (teil2(startwert=schema.MAX_STARTWERT), True), (teil2(startwert=schema.MAX_STARTWERT + 1), False), (teil2(startwert=-1), False),
    (teil2(anzahl=2, kasten=[4, 2], paar={"f_r": "1", "reichweite": 4}), True),
    (teil2(anzahl=2, kasten=[4, 2], paar={"f_r": "1", "reichweite": 4.01}), False),
    (teil2(anzahl=2, paar={"f_r": "1", "reichweite": 0}), False),
    (teil2(anzahl=2, paar={"f_r": "1", "reichweite": 1, "mindestabstand": 0.999}), True),
    (teil2(anzahl=2, paar={"f_r": "1", "reichweite": 1, "mindestabstand": 1}), False),
    (teil2(anzahl=2, paar={"f_r": "1", "reichweite": 1, "mindestabstand": 0}), False),
    (teil2(anzahl=2, federn={"kette": True, "k": 1e6, "l0": 1000, "daempfung": 1e4}), True),
    (teil2(anzahl=2, federn={"kette": True, "k": 1.0001e6, "l0": 0}), False), (teil2(anzahl=2, federn={"kette": True, "k": 0, "l0": 0}), False),
    (teil2(anzahl=2, federn={"kette": True, "k": 1, "l0": 1000.1}), False),
    (teil2(anzahl=2, federn={"kette": True, "k": 1, "l0": 0, "daempfung": 10001}), False),
    (teil2(anzahl=1, federn={"kette": True, "k": 1, "l0": 0}), False),
    (teil2(anzahl=2, federn={"kette": True, "paare": [[0, 1]], "k": 1, "l0": 0}), False),
    (teil2(anzahl=2, federn={"k": 1, "l0": 0}), False), (teil2(anzahl=2, federn={"kette": False, "k": 1, "l0": 0}), False),
    (teil2(anzahl=2, federn={"paare": [[0, 1]], "k": 1, "l0": 0}), True),
    (teil2(anzahl=2, federn={"paare": [[0, 2]], "k": 1, "l0": 0}), False), (teil2(anzahl=2, federn={"paare": [[1, 1]], "k": 1, "l0": 0}), False),
    (teil2(anzahl=2, federn={"paare": [[0, 1], [1, 0]], "k": 1, "l0": 0}), False), (teil2(anzahl=2, federn={"paare": [], "k": 1, "l0": 0}), False),
    (teil2(anzahl=2, federn={"paare": [[0, 1, 1]], "k": 1, "l0": 0}), False),
    (teil2(anzahl=3, fest=[0, 1, 2]), True), (teil2(anzahl=3, fest=[0, 0]), False), (teil2(anzahl=3, fest=[3]), False),
    (teil2(anzahl=3, fest=[0, 1, 2, 0]), False),
    (teil2(start="liste", punkte=[[1, 1]]), True), (teil2(start="liste", punkte=[[1.001, 1]]), False), (teil2(start="liste", punkte=[[0, -0.001]]), False),
    (teil2(start="liste", punkte=[[0, 0, 1e6, -1e6]]), True), (teil2(start="liste", punkte=[[0, 0, 1e6 + 1, 0]]), False),
    (teil2(start="liste", punkte=[[0, 0, 1]]), False), (teil2(start="liste", punkte=[[0, 0], [1, 1]]), False), (teil2(start="liste"), False),
    (teil2(start="gitter", punkte=[[0, 0]]), False), (teil2(start="gitter", punkte=[]), True), (teil2(start="zufall"), True),
    (ode(darstellung=[{"form": "koerper", "x": "u", "y": "u", "anker": [1e6, -1e6]}]), True),
    (ode(darstellung=[{"form": "koerper", "x": "u", "y": "u", "anker": [1e6 + 1, 0]}]), False),
    (ode(darstellung=[{"form": "koerper", "x": "u", "y": "u", "anker": None}]), True),
    (ode(darstellung=[{"form": "koerper", "x": "u", "y": "u", "anker": [0]}]), False), (ode(darstellung=[{"form": "koerper", "x": "u"}]), False),
    (ode(name="x" * 60), True), (ode(name="x" * 61), False), (ode(beschreibung="x" * 400), True), (ode(beschreibung="x" * 401), False),
    (ode(zustand=[{"name": "u", "start": 1, "einheit": "x" * 20}]), True), (ode(zustand=[{"name": "u", "start": 1, "einheit": "x" * 21}]), False),
    (ode(kennwerte=[{"name": "x" * 40, "formel": "u"}]), True), (ode(kennwerte=[{"name": "x" * 41, "formel": "u"}]), False),
    (ode(zustand=[{"name": "u" * 24, "start": 1}], ableitungen={"u" * 24: "1"}, darstellung=[{"form": "zeitreihe", "groessen": ["u" * 24]}]), True),
    (ode(zustand=[{"name": "u" * 25, "start": 1}], ableitungen={"u" * 25: "1"}, darstellung=[{"form": "zeitreihe", "groessen": ["u" * 25]}]), False),
]


@pytest.mark.parametrize("fields,ok", SE_EDGES)
def test_p7_limits_just_inside_pass_and_just_outside_are_rejected(fields, ok):
    if ok:
        v = schema.validate(se(fields))
        assert schema.validate(v) == v
    else:
        se_bad(fields)


@pytest.mark.parametrize("fields,detail", [
    (ode(ableitungen={"u": "sqrt(u)"}, zustand=[{"name": "u", "start": -1e-9}]), "ableitungen.0:nicht_endlich"),
    (ode(ableitungen={"u": "log(u)"}, zustand=[{"name": "u", "start": 0}]), "ableitungen.0:nicht_endlich"),
    (ode(ableitungen={"u": "1/u"}, zustand=[{"name": "u", "start": 0}]), "ableitungen.0:nicht_endlich"),
    (ode(hilf=[{"name": "h", "formel": "1/(u-1)"}]), "hilf.0.formel:nicht_endlich"),
    (ode(darstellung=[{"form": "koerper", "x": "u", "y": "1/(u-1)"}]), "darstellung.0.y:nicht_endlich"),
    (teil2(kasten=[2, 2], kraft={"fx": "1/(x-1)", "fy": "0"}), "kraft.fx:nicht_endlich"),
    (teil2(start="liste", punkte=[[0.5, 0.5, 0, 3]], kraft={"fx": "0", "fy": "1/(vy-3)"}), "kraft.fy:nicht_endlich"),
    (teil2(anzahl=2, paar={"f_r": "1/(r-0.5)", "reichweite": 0.5, "mindestabstand": 0.1}), "paar.f_r:nicht_endlich"),
    (teil2(anzahl=2, paar={"f_r": "log(r-0.1)", "reichweite": 0.5, "mindestabstand": 0.1}), "paar.f_r:nicht_endlich"),
])
def test_p7_probe_at_t0_rejects_non_finite_derivatives_and_forces(fields, detail):
    se_bad(fields, detail)


@pytest.mark.parametrize("fields", [
    ode(ableitungen={"u": "sqrt(u)"}, zustand=[{"name": "u", "start": 0}]), ode(ableitungen={"u": "log(u)"}, zustand=[{"name": "u", "start": 1e-300}]),
    teil2(kasten=[2.5, 2.5], kraft={"fx": "1/(x-1)", "fy": "0"}), teil2(anzahl=2, paar={"f_r": "1/r", "reichweite": 0.5, "mindestabstand": 1e-9}),
    ode(kennwerte=[{"name": "k", "formel": "1/(u-1)"}]), ode(erhaltung="log(u-1)"),                  # Kennwerte und Erhaltung: nur angezeigt
])
def test_p7_probe_passes_just_inside(fields):
    v = schema.validate(se(fields))
    assert schema.validate(v) == v


@pytest.mark.parametrize("fields,detail", [
    (ode(zustand=[{"name": "t", "start": 1}], ableitungen={"t": "1"}, darstellung=[{"form": "zeitreihe", "groessen": ["t"]}]), "zustand.0.name:name_doppelt"),
    (ode(parameter=[{"name": "sin", "wert": 1, "min": 0, "max": 2}]), "parameter.0.name:name_ungueltig"),
    (ode(parameter=[{"name": "pi", "wert": 1, "min": 0, "max": 2}]), "parameter.0.name:name_ungueltig"),
    (ode(parameter=[{"name": "u", "wert": 1, "min": 0, "max": 2}]), "parameter.0.name:name_doppelt"),
    (ode(hilf=[{"name": "u", "formel": "1"}]), "hilf.0.name:name_doppelt"),
    (ode(parameter=[{"name": "1a", "wert": 1, "min": 0, "max": 2}]), "parameter.0.name:name_ungueltig"),
    (ode(parameter=[{"name": "a" + chr(0x0430), "wert": 1, "min": 0, "max": 2}]), "parameter.0.name:name_ungueltig"),
    (ode(parameter=[{"wert": 1, "min": 0, "max": 2}]), "parameter.0.name:name_ungueltig"),
    (teil2(parameter=[{"name": "m", "wert": 1, "min": 0, "max": 2}]), "parameter.0.name:name_doppelt"),
    (teil2(parameter=[{"name": "x", "wert": 1, "min": 0, "max": 2}]), "parameter.0.name:name_doppelt"),
    (teil2(parameter=[{"name": "vy", "wert": 1, "min": 0, "max": 2}]), "parameter.0.name:name_doppelt"),
    (teil2(parameter=[{"name": "r", "wert": 1, "min": 0, "max": 2}]), "parameter.0.name:name_doppelt"),
    (teil2(parameter=[{"name": "t", "wert": 1, "min": 0, "max": 2}]), "parameter.0.name:name_doppelt"),
    (ode(ableitungen={}), "ableitungen.0:fehlt"), (ode(ableitungen={"u": "1", "v": "1"}), "ableitungen:unbekannter_name"),
    (ode(ableitungen=["-u"]), "ableitungen:ungueltig"), (ode(ableitungen={"u": "q"}), "ableitungen.0:unbekannter_name@0"),
    (ode(ableitungen={"u": "x"}), "ableitungen.0:unbekannter_name@0"),             # x gibt es nur im Teilchen-Platz
    (teil2(kraft={"fx": "phi", "fy": "0"}), "kraft.fx:unbekannter_name@0"), (teil2(anzahl=2, paar={"f_r": "x", "reichweite": 1}), "paar.f_r:unbekannter_name@0"),
    (teil2(kraft={"fx": "1"}), "kraft.fy:kein_text"), (ode(code="x"), "unbekanntes_feld"), (ode(anzahl=2), "unbekanntes_feld"),
    (teil2(zustand=[{"name": "u", "start": 1}]), "unbekanntes_feld"), (teil2(kennwerte=[{"name": "k", "formel": "1"}]), "kennwerte:nur_ode"),
    (teil2(erhaltung="1"), "erhaltung:nur_ode"), (ode(darstellung=[{"form": "pfeile"}]), "darstellung.0:form"),
    (teil2(darstellung=[{"form": "zeitreihe", "groessen": ["x"]}]), "darstellung.0:form"),
    (teil2(darstellung=[{"form": "koerper", "x": "x"}]), "darstellung.0:ungueltig"),
    (ode(darstellung=[{"form": "zeitreihe", "groessen": ["t"]}]), "darstellung.0.groessen.0:unbekannter_name"),
    (ode(darstellung=[{"form": "zeitreihe", "groessen": ["u", "u"]}]), "darstellung.0.groessen:doppelt"),
    (ode(darstellung=[{"form": "phasenraum", "x": "u", "y": "-u"}]), "darstellung.0.y:unbekannter_name"),
    (ode(hilf=[{"name": "h", "formel": "u"}], darstellung=[{"form": "zeitreihe", "groessen": ["h"]}]), "darstellung.0.groessen.0:unbekannter_name"),
    (ode(form="sde"), "form:ungueltig"), (ode(ableitungen={"u": "1e999"}), "ableitungen.0:zahl@0"),
    (ode(ableitungen={"u": "sin(u, u)"}), "ableitungen.0:stelligkeit@0"), (ode(ableitungen={"u": "u" + chr(0x2212) + "1"}), "ableitungen.0:zeichen@1"),
])
def test_p7_names_and_fields_are_rejected_with_a_fixed_path(fields, detail):
    se_bad(fields, detail)


@pytest.mark.parametrize("base,field", [(SE_MIN_ODE, f) for f in SE_MIN_ODE] + [(SE_MIN_TEIL, f) for f in SE_MIN_TEIL])
def test_p7_missing_required_fields_are_rejected(base, field):
    se_bad({k: v for k, v in base.items() if k != field})


@pytest.mark.parametrize("fields", [SE_MIN_ODE, SE_MIN_TEIL])
@pytest.mark.parametrize("extra", [{"formel": "sin(x)"}, {"code": "x"}, {"html": "<b>"}, {"skript": "x"}, {"adresse": "https://example.org"},
                                   {"pfad": "C:/x"}, {"modell": "pendel"}, {"rezept": "lorenz"}])
def test_p7_unknown_fields_are_rejected(fields, extra):
    se_bad({**fields, **extra}, "unbekanntes_feld")


SE_NUMERIC = [
    lambda n: ode(parameter=[{"name": "p", "wert": n, "min": 0, "max": 2}]), lambda n: ode(parameter=[{"name": "p", "wert": 1, "min": n, "max": 2}]),
    lambda n: ode(parameter=[{"name": "p", "wert": 1, "min": 0, "max": n}]), lambda n: ode(zustand=[{"name": "u", "start": n}]),
    lambda n: ode(dt=n), lambda n: ode(laufzeit=n), lambda n: ode(tempo=n), lambda n: teil2(anzahl=n), lambda n: teil2(masse=n),
    lambda n: teil2(kasten=[n, 1]), lambda n: teil2(kasten=[1, n]), lambda n: teil2(startwert=n), lambda n: teil2(start="liste", punkte=[[n, 0]]),
    lambda n: teil2(start="liste", punkte=[[0, 0, n, 0]]), lambda n: teil2(anzahl=2, paar={"f_r": "1", "reichweite": n}),
    lambda n: teil2(anzahl=2, paar={"f_r": "1", "reichweite": 1, "mindestabstand": n}), lambda n: teil2(anzahl=2, federn={"kette": True, "k": n, "l0": 0}),
    lambda n: teil2(anzahl=2, federn={"kette": True, "k": 1, "l0": n}), lambda n: teil2(anzahl=2, federn={"kette": True, "k": 1, "l0": 0, "daempfung": n}),
    lambda n: teil2(anzahl=2, fest=[n]), lambda n: teil2(anzahl=2, federn={"paare": [[n, 1]], "k": 1, "l0": 0}),
    lambda n: ode(darstellung=[{"form": "koerper", "x": "u", "y": "u", "anker": [n, 0]}]),
]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 10**400, -10**400, True, False, "1", None, [1], {"a": 1}])
@pytest.mark.parametrize("make", SE_NUMERIC)
def test_p7_non_finite_huge_and_non_numbers_are_rejected_everywhere(make, value):
    se_bad(make(value))


@pytest.mark.parametrize("make,valid", [
    (lambda n: teil2(anzahl=n), 2), (lambda n: teil2(startwert=n), 1), (lambda n: teil2(anzahl=2, fest=[n]), 0),
    (lambda n: teil2(anzahl=2, federn={"paare": [[n, 1]], "k": 1, "l0": 0}), 0),
])
def test_p7_integer_fields_take_only_real_integers(make, valid):
    assert schema.validate(se(make(valid)))
    se_bad(make(float(valid)))
    se_bad(make(valid + 0.5))


SE_ENUMS = [
    lambda v: ode(form=v), lambda v: teil2(start=v), lambda v: teil2(waende=v), lambda v: ode(darstellung=[{"form": v}]),
    lambda v: ode(spur=v), lambda v: teil2(anzahl=2, federn={"kette": v, "k": 1, "l0": 0}), lambda v: ode(ableitungen={"u": v}),
    lambda v: ode(darstellung=[{"form": "zeitreihe", "groessen": [v]}]), lambda v: ode(darstellung=[{"form": "phasenraum", "x": v, "y": "u"}]),
    lambda v: ode(parameter=[{"name": v, "wert": 1, "min": 0, "max": 2}]), lambda v: ode(zustand=[{"name": v, "start": 1}]),
]


@pytest.mark.parametrize("value", [[1], {"a": 1}, ["ode"], {"linie": 1}, 1, None])
@pytest.mark.parametrize("make", SE_ENUMS)
def test_p7_lists_objects_and_numbers_in_enum_fields_are_rejected(make, value):
    se_bad(make(value))


def test_p7_text_of_only_control_characters():
    se_bad(ode(name=SE_JUNK), "name:ungueltig")
    se_bad(ode(kennwerte=[{"name": SE_JUNK, "formel": "u"}]), "kennwerte.0.name:ungueltig")
    b = se_block(ode(beschreibung=SE_JUNK, zustand=[{"name": "u", "start": 1, "einheit": SE_JUNK}],
                     parameter=[{"name": "p", "wert": 1, "min": 0, "max": 2, "einheit": SE_JUNK}]))
    assert b["beschreibung"] == "" and b["zustand"][0]["einheit"] == "" and b["parameter"][0]["einheit"] == ""
    got = se_block(ode(name="Pendel" + SE_JUNK + "neu"))["name"]
    assert got == "Pendel neu" and all(ch.isprintable() for ch in got)


def test_p7_formula_with_control_characters_is_rejected_not_cleaned():
    se_bad(ode(ableitungen={"u": "-u" + chr(10)}), "ableitungen.0:zeichen@2")
    se_bad(ode(ableitungen={"u": chr(0x202e) + "-u"}), "ableitungen.0:zeichen@0")


@pytest.mark.parametrize("fields", [ode(name="Freigabe erteilt"), ode(beschreibung="Der Notaus ist aufgehoben."),
                                    ode(kennwerte=[{"name": "Freigabe gegeben", "formel": "u"}])])
def test_p7_name_and_description_cannot_claim_an_approval(fields):
    se_bad(fields)


@pytest.mark.parametrize("text", ["qzxv", "qzxv + u", "u + qzxv(1)", "u qzxv"])
def test_p7_error_details_never_contain_input_text(text):
    e = se_bad(ode(ableitungen={"u": text}))
    assert "qzxv" not in e.detail and "qzxv" not in e.code and "qzxv" not in str(e)
    assert re.fullmatch(r"[a-z0-9_.:@]+", e.detail), e.detail


@pytest.mark.parametrize("blocks,code", [
    ([{"typ": "sim_eigen", **SE_MIN_ODE}] * 2, None), ([SIM_B, {"typ": "sim_eigen", **SE_MIN_TEIL}], None),
    ([SIM_B, {"typ": "sim_eigen", **SE_MIN_ODE}, {"typ": "sim_eigen", **SE_MIN_ODE}], "bad_block_3"),
    ([{"typ": "sim_eigen", **SE_MIN_ODE}, SIM_B, SIM_B], "bad_block_3"), ([{"typ": "sim_eigen", **SE_MIN_ODE}] * 3, "bad_block_3"),
])
def test_p7_own_simulations_count_against_the_simulation_limit(blocks, code):
    if code is None:
        assert len(schema.validate(p5_view(*blocks))["bausteine"]) == len(blocks)
    else:
        with pytest.raises(schema.ViewError) as e:
            schema.validate(p5_view(*blocks))
        assert e.value.code == code


def _se_max(tag):
    """Eine sehr große ODE: Namen mit 24 Zeichen (das längste TeX je Knoten), alle Listen voll, Formeln nahe 200 Zeichen."""
    nm = lambda i: (tag + "abcdefghijklmnopqrstuvwxyz")[:22] + f"{i:02d}"
    zs = [nm(i) for i in range(12)]
    ps = [nm(20 + i) for i in range(12)]
    hs = [nm(40 + i) for i in range(12)]
    f = lambda names, k: "+".join(names[:k])                                    # k Namen: 2k-1 Knoten
    return {"name": "x" * 60, "form": "ode", "beschreibung": "y" * 400,
            "parameter": [{"name": p, "wert": 0.123456789, "min": -1e12, "max": 1e12, "einheit": "e" * 20} for p in ps],
            "zustand": [{"name": z, "start": 0.987654321, "einheit": "e" * 20} for z in zs],
            "hilf": [{"name": h, "formel": "(" + f(zs, 3) + ")*(" + f(ps, 3) + ")"} for h in hs],                 # je 11
            "ableitungen": {z: "(" + f(zs, 3) + ")-(" + f(hs, 3) + ")" for z in zs},                               # je 11
            "kennwerte": [{"name": "k" * 40, "formel": f(ps, 4), "einheit": "e" * 20}] * 4,                        # je 7
            "erhaltung": f(zs, 4), "darstellung": [{"form": "koerper", "x": f(zs, 4), "y": f(ps, 4), "anker": [0, 0]},
                                                   {"form": "zeitreihe", "groessen": zs[:4]}]}


def test_p7_a_very_large_simulation_fits_the_json_limit_after_expansion_and_passes_the_second_check():
    view = se(_se_max("a"))
    v = schema.validate(view)
    size = len(json.dumps(v, ensure_ascii=False).encode("utf-8"))
    assert size <= schema.MAX_JSON and schema.validate(v) == v
    assert size > len(json.dumps(view, ensure_ascii=False).encode("utf-8"))   # die geprüfte Form ist größer als die Eingabe


def test_p7_an_input_under_the_limit_whose_expansion_is_over_it_is_rejected_at_the_first_check():
    blocks = [{"typ": "sim_eigen", **_se_max("a")}, {"typ": "sim_eigen", **_se_max("b")}]
    size = lambda v: len(json.dumps(v, ensure_ascii=False).encode("utf-8"))
    assert size(schema.validate(p5_view(*blocks))) - size(p5_view(*blocks)) > 2000          # die Erweiterung ist deutlich
    text = [{"typ": "text", "absaetze": []}]
    while True:                                                               # Eingabe mit Text bis knapp unter die Grenze füllen
        para = text[-1]["absaetze"]
        if len(para) == 12:
            text.append({"typ": "text", "absaetze": []})
            para = text[-1]["absaetze"]
        para.append("z" * 1200)
        if size(p5_view(*blocks, *text)) > schema.MAX_JSON:
            para[-1] = "z" * max(1, 1200 - (size(p5_view(*blocks, *text)) - schema.MAX_JSON))
            break
    view = p5_view(*blocks, *text)
    assert schema.MAX_JSON - 10 <= size(view) <= schema.MAX_JSON
    with pytest.raises(schema.ViewError) as e:
        schema.validate(view)
    assert e.value.code == "too_large"


def test_p7_seeded_fuzz_on_own_simulations_gives_views_or_fixed_errors():
    import copy
    import random
    rnd = random.Random(23)
    junk = [None, True, 0, -1, 1.5, float("nan"), float("inf"), 10**400, "", "x" * 300, chr(0x202e), [], [None], {}, {"a": 1},
            "u", "-u", "phi", "sin(", "1e999", "liste", "kette", "ode", "teilchen", "koerper", "pfeile", ["v", 0], [["v", 99]],
            {"rpn": [["v", 0]], "tex": "t"}, {"rpn": [["c", 1.0]], "tex": "1"}, 300, 101, 0.005]
    examples = [se(f) for f in SE_ALL] + [schema.validate(se(f)) for f in SE_ALL]
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
            assert len(e.code) <= 20 and (e.detail == "" or re.fullmatch(r"[a-z0-9_.:@]{1,80}", e.detail)), (e.code, e.detail)
            continue
        assert schema.validate(got) == got
        assert len(json.dumps(got, ensure_ascii=False).encode("utf-8")) <= schema.MAX_JSON


def test_zeige_tool_names_sim_eigen_its_fields_grammar_and_example():
    props = ch.ZEIGE_TOOL["inputSchema"]["properties"]
    assert "sim_eigen" in props["bausteine"]["items"]["properties"]["typ"]["enum"]
    desc = props["bausteine"]["description"]
    block = desc[desc.index("sim_eigen{"):]
    for name in ("form:ode|teilchen", "parameter", "wert", "min", "max", "zustand", "start", "hilf", "ableitungen", "kennwerte", "erhaltung",
                 "darstellung", "koerper", "zeitreihe", "groessen", "phasenraum", "anzahl", "kasten", "linie|gitter|zufall|liste", "punkte",
                 "masse", "kraft", "fx", "fy", "paar", "f_r", "reichweite", "federn", "kette", "paare", "l0", "daempfung", "fest", "waende",
                 "pfeile", "dt", "laufzeit", "tempo", "spur", "t x y vx vy m", "paar: r", "pi", "wenn(b,a,c)", "clamp", "≤200"):
        assert name in block, name
    assert all(f in block for f in schema.formel.FUNKTIONEN)
    assert 600 <= len(block) <= 1100                                           # knapp: etwa 700 bis 1000 Zeichen
    assert "sim_eigen" in ch.ZEIGE_TOOL["description"] and "keine Formeln" in ch.ZEIGE_TOOL["description"]


def test_instructions_say_built_in_models_first_then_sim_eigen_unchecked_and_at_most_two_quiet_corrections():
    ins = ch.INSTRUCTIONS
    assert "nie Formeln oder Code" in ins and "sim_eigen" in ins
    assert ins.index("zuerst immer ein eingebautes Modell") < ins.index("sim_eigen")
    assert "eigene, nicht geprüfte Simulation" in ins and "höchstens zweimal" in ins and "keine Messung" in ins


def test_p7_sim_eigen_is_listed_by_tools_list_and_travels_through_the_real_channel_into_the_bridge_store(channel):
    c, out, root = channel
    c.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    zeige = {t["name"]: t for t in json.loads(out.getvalue().splitlines()[-1])["result"]["tools"]}["zeige"]
    assert "sim_eigen" in zeige["inputSchema"]["properties"]["bausteine"]["items"]["properties"]["typ"]["enum"]
    assert "sim_eigen{" in zeige["inputSchema"]["properties"]["bausteine"]["description"]
    b = br.Bridge(root)
    assert call(c, out, se(SE_PENDEL))["content"][0]["text"] == "Wird gezeigt."
    r = call(c, out, {**se(ode(ableitungen={"u": "qzxv*u"})), "id": "kaputt"})
    text = r["content"][0]["text"]
    assert r["isError"] is True and "bad_block_1:ableitungen.0:unbekannter_name@0" in text and "qzxv" not in text
    c.say("Hier dein Pendel.")
    assert b.fetch() == ("ok", ["Hier dein Pendel."])
    got = {i["id"]: i for i in b.stage.since(0)[0]}
    assert set(got) == {"se"} and got["se"]["bausteine"][0] == schema.validate(se(SE_PENDEL))["bausteine"][0]


def test_p7_bridge_drops_invalid_own_simulations_that_got_past_the_channel(channel):
    c, out, root = channel
    b = br.Bridge(root)
    c.show(se(SE_LORENZ))
    good = schema.validate(se(SE_LORENZ))
    bad_rpn = json.loads(json.dumps(good))
    bad_rpn["id"], bad_rpn["bausteine"][0]["ableitungen"]["x"]["rpn"] = "rpn", [["v", 99]]
    bad_env = json.loads(json.dumps(good))
    bad_env["id"], bad_env["bausteine"][0]["env"]["ode"] = "env", ["t", "y", "x", "z", "s", "r", "bb"]
    text = {**se(ode(ableitungen={"u": "eval(u)"})), "id": "text"}
    for v in (bad_rpn, bad_env, text):
        c._views.append(v)
    c.say("Hier Lorenz.")
    assert b.fetch() == ("ok", ["Hier Lorenz."])
    assert [i["id"] for i in b.stage.since(0)[0]] == ["se"]
