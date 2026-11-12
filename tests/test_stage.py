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
