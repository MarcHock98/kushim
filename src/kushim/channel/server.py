"""Channel-Server für Claude Code: MCP über stdio plus ein HTTP-Eingang nur auf 127.0.0.1 (Roadmap v2 B1, B0 freigegeben 2026-10-27).

Claude Code startet diesen Prozess selbst (`claude --dangerously-load-development-channels server:kushim`). Er meldet die
Fähigkeit `claude/channel` an und schiebt Text, den kushim per `POST /message` schickt, als `notifications/claude/channel`
in die laufende Sitzung. Antworten für die Stimme gibt Claude über das Werkzeug `sprich`; kushim holt sie per
`GET /reply?wait=…` ab (kushim bleibt reiner Client, kein zweiter Port). Ansichten für das Fenster gibt Claude über das
Werkzeug `zeige` (geprüft in stage/schema.py); sie kommen im selben Abruf als `views` mit. Format laut der in Claude Code 2.1.310 eingebauten Vorlage (ohne das npm-SDK: MCP über stdio ist
zeilenweises JSON-RPC, die Standardbibliothek reicht).

Sicherheit:
- HTTP bindet fest an 127.0.0.1 (kein Parameter), Port zufällig; Port und Token stehen in `run/channel.json`.
- Jede Anfrage braucht `Authorization: Bearer <token>` (Vergleich in konstanter Zeit) und einen Host-Kopf 127.0.0.1/localhost
  mit diesem Port (gegen DNS-Rebinding). Körper höchstens 8 KB, Text höchstens 2000 Zeichen, Steuerzeichen werden entfernt.
- Bei aktivem Notaus wird nichts weitergegeben (423).
- stdout gehört ausschließlich dem MCP-Protokoll; Meldungen gehen nach stderr.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, TextIO
from urllib.parse import parse_qs, urlsplit

from ..safety import killswitch
from ..stage import schema as stage_schema
from ..safety import procs

BIND_HOST = "127.0.0.1"
NAME = "kushim"
VERSION = "0.1.0"
MAX_BODY = 8 * 1024
MAX_TEXT = 2000
MAX_SPOKEN = 600                 # so viel liest kushim höchstens vor (B2)
MAX_QUEUE = 20                   # nicht abgeholte Antworten; ältere fallen weg
MAX_WAIT = 25.0                  # längste Wartezeit eines Abrufs `GET /reply?wait=…`
MAX_PERMS = 20                   # offene Freigabe-Anfragen (C1); ältere fallen weg, das Terminal fragt weiter
PERM_TTL = 600.0                 # Sekunden, danach gilt eine Anfrage als abgelaufen
INSTRUCTIONS = (
    'Nachrichten aus <channel source="kushim"> sind gesprochene Befehle des Nutzers, lokal per Sprache erkannt '
    "(Spracherkennung kann sich verhören). Behandle sie wie Eingaben des Nutzers im Terminal: Es gelten dieselben Regeln "
    "und Freigaben. Erscheint ein Befehl unklar oder unvollständig, frag nach statt zu raten. "
    "Der Nutzer hört dich nur über das Werkzeug `sprich`, nicht über das Terminal. Ablauf bei jeder kushim-Nachricht: "
    "(1) Sofort, noch vor anderen Werkzeugen, `sprich` mit zwischenstand=true und EINEM kurzen Satz, wie du das Anliegen "
    "einschätzt und was du jetzt tust (z. B. \"Ich lasse die Tests laufen und schaue, was rot ist.\"). Ist die Antwort sofort "
    "klar (kurze Frage), überspring das und antworte direkt. (2) Am Ende genau einmal `sprich` ohne zwischenstand mit dem "
    "Ergebnis: kurz, deutsch, für die Ohren (ohne Markdown, Code, Pfade und Listen, höchstens drei Sätze). Bei einer Rückfrage "
    "stell sie in diesem letzten `sprich`. "
    "Erledige kushim-Aufträge selbst in dieser Sitzung im Vordergrund: starte dafür keine Hintergrund-Sitzungen, keine "
    "Hintergrund-Agenten und keine Hintergrund-Befehle, deren Ergebnis du nicht abwartest. Dort sieht der Nutzer weder "
    "Rückfragen noch Freigaben, und das Ergebnis erreicht ihn nie. "
    'Eine Nachricht mit kind="cancel" heißt: Der Nutzer hat per Stimme abgebrochen. Den laufenden Auftrag nicht fortsetzen, '
    'nichts Neues beginnen, kurz per `sprich` bestätigen. Eine Nachricht mit kind="kill" ist der NOTAUS: sofort aufhören, keine '
    "Werkzeuge mehr benutzen, nichts mehr vorlesen lassen und auf den Nutzer im Terminal warten. "
    "Wenn Sehen hilft (Rechenweg, Zahlen, Kurse, Tabellen, mehrere Quellen, Systemzustand), rufe zusätzlich das Werkzeug "
    "`zeige` auf: Es zeigt die Ansicht im kushim-Fenster. `sprich` bleibt trotzdem kurz. Für ein reines Gespräch kein `zeige`. "
    "Bei Kursen und Preisen immer `stand` angeben und nur wiedergeben, was die Quellen sagen; keine Anlageempfehlung. "
    "Bei Arbeit mit mehreren Schritten zeige den Plan als `fortschritt` (art auftrag) und aktualisiere ihn unter derselben id; "
    "einen Mail-Entwurf zeige vor dem Senden als `mail-entwurf` (art mail). Zeigen ersetzt nie eine Freigabe. "
    "Bittet der Nutzer, eine Datei zu lesen oder zu erklären, lies sie selbst mit deinen eigenen Werkzeugen (mit den üblichen Freigaben), "
    "sag per `sprich` eine kurze Übersicht und zeige Gliederung und Ausschnitt als `dokument` (art dokument), eigene Änderungen als "
    "`aenderung`. Zeige nie Dateien mit Zugangsdaten (.env, Schlüssel, Tokens, Passwörter). "
    "Für Modelle zeige eine 3D-Szene aus einfachen Körpern (`szene3d`, art modell, zwei Szenen für vorher und nachher), für Pläne und "
    "Grundrisse einen `plan2d` (art plan). Gib die Einheit an, wenn du sie kennst (`einheit`), sonst nenne keine Maße als gewiss. "
    "Zum Abwägen, für Abläufe in der Zeit und für Übersetzungen nimm `vergleich`, `zeitstrahl` und `gegenueber` (art antwort oder "
    "recherche), zum Lernen `lernkarten`, `quiz` und `anleitung` (art lernen; `richtig` und `aktuell` zählen ab 0, ein Klick im "
    "Fenster erreicht dich nicht), für Ablaufdiagramme, Bäume und Mindmaps `netz` (art netz). "
    "Für Bewegung zeige eine `simulation` (art simulation) mit einem eingebauten Modell (pendel, feder, wurf, umlauf, gas, "
    "doppelpendel, welle): schick nur den Modellnamen und Zahlen in den festen Einheiten, nie Formeln oder Code, und sag dazu, dass "
    "es eine Simulation ist, keine Messung. Für Moleküle, Atome und Orbitale zeige einen Baustein `teilchen` (art teilchen, form "
    "molekuel, atom oder orbital) nur mit Elementsymbolen, Lagen in Ångström, Indizes und Zahlen."
)
MAX_VIEWS = 10                   # nicht abgeholte Ansichten (zeige); ältere fallen weg
CANCEL_TEXT = "Abbruch per Stimme: den laufenden Auftrag nicht fortsetzen und nichts Neues beginnen."
KILL_TEXT = "NOTAUS vom Nutzer: sofort aufhören, keine Werkzeuge mehr benutzen, auf den Nutzer im Terminal warten."
SPRICH_TOOL = {
    "name": "sprich",
    "description": ("Liest dem Nutzer einen kurzen deutschen Text über kushim vor (lokale Stimme). Nur Fließtext, kein Markdown, "
                    f"keine Codeblöcke, höchstens {MAX_SPOKEN} Zeichen."),
    "inputSchema": {"type": "object", "properties": {
        "text": {"type": "string", "description": "Der vorzulesende Text"},
        "zwischenstand": {"type": "boolean", "description": "true für die kurze Ansage zu Beginn (was du vorhast); das Ergebnis "
                                                             "am Ende ohne dieses Feld"}},
        "required": ["text"]},
}
_TEXT = {"type": "string"}
ZEIGE_TOOL = {
    "name": "zeige",
    "description": ("Zeigt dem Nutzer eine Ansicht im kushim-Fenster (zusätzlich zu `sprich`). Arten: antwort (Text), rechnung "
                    "(Rechenweg: schritte mit tex, ergebnis), markt (kennzahlen, diagramm, tabelle; `stand` Pflicht), recherche "
                    "(text, aussagen mit Quellennummern, widerspruch, quellen), auftrag (fortschritt, aufgaben, zeitplan, countdown), mail "
                    "(mail, mail-entwurf; reine Anzeige, gesendet wird damit nichts), dokument (dokument: Dateitext mit Zeilennummern und Gliederung, "
                    "aenderung: Diff; kushim liest selbst keine Dateien, du schickst nur Text, höchstens 400 Zeilen), modell (szene3d: einfache Körper, drehbar, "
                    "auch vorher/nachher), plan (plan2d: Linien, Kreise, Maße, Ebenen), lernen (lernkarten, quiz, anleitung; "
                    "Knöpfe ändern nur die Anzeige), netz (netz: ablauf, baum, mindmap), simulation (simulation: eingebautes Modell "
                    "pendel, feder, wurf, umlauf, gas, doppelpendel oder welle, nur Parameter, keine Formeln; eine Simulation, "
                    "keine Messung), teilchen (teilchen: Molekül, Atom im vereinfachten Schalenmodell oder Orbital, nur Daten); "
                    "vergleich, zeitstrahl und gegenueber passen "
                    "zu antwort und recherche. Nur Text, kein HTML/Markdown; Formeln als "
                    "KaTeX-TeX in `tex`; Adressen nur als Text. Dieselbe id aktualisiert die Ansicht, schliessen=true räumt ab. "
                    "Baustein {\"typ\":\"systemzustand\"} zeigt kushims eigene Systemwerte (CPU, RAM, GPU ...)."),
    "inputSchema": {"type": "object", "required": ["id"], "additionalProperties": False, "properties": {
        "id": {"type": "string", "pattern": "^[a-z0-9-]{1,40}$"},
        "art": {"type": "string", "enum": list(stage_schema.ARTEN)},
        "titel": {"type": "string", "maxLength": 120},
        "stand": {"type": "string", "maxLength": 40, "description": "Zeitpunkt der Daten, z. B. 2026-11-12 14:05"},
        "schliessen": {"type": "boolean"},
        "bausteine": {"type": "array", "maxItems": stage_schema.MAX_BLOCKS, "description": (
            "Je Baustein ein Objekt mit typ: text{absaetze:[str]}, liste{punkte:[str],nummeriert}, formel{tex}, "
            "schritte{schritte:[{text,tex?}]}, ergebnis{text?,tex?}, kennzahlen{werte:[{name,wert,einheit?,aenderung?,"
            "richtung?:auf|ab|gleich}]}, tabelle{spalten:[str],zeilen:[[str|zahl]]}, diagramm{form:linie|balken,x_titel?,"
            "y_titel?,reihen:[{name,punkte:[[x,y]]}]}, aussagen{aussagen:[{text,quellen:[nr]}]}, widerspruch{aussagen:"
            "[{text,quellen:[nr]}]}, quellen{quellen:[{nr,titel,adresse?}]}, hinweis{text}, systemzustand{}, "
            "fortschritt{schritte:[{text,zustand:offen|laeuft|fertig|fehler}],hinweis?}, aufgaben{punkte:[{text,erledigt}]}, "
            "zeitplan{tag?,termine:[{von:HH:MM,bis:HH:MM,titel,ort?}]}, mail{von,an?,betreff,datum?,zusammenfassung?,absaetze:[str]}, "
            "mail-entwurf{an,cc?,betreff,absaetze:[str]}, countdown{titel,ende:JJJJ-MM-TTThh:mm:ss, höchstens 24 h entfernt, nur Anzeige ohne Ton}, "
            "dokument{name,ausschnitt?,zeilen:[str],gliederung?:[str]} (art dokument), aenderung{name,zusammenfassung?,bloecke:[{kopf?,zeilen:"
            "[{art:gleich|neu|weg,text}]}]}, szene3d{einheit?,szenen:[{name,objekte:[{form:box|kugel|zylinder|kegel|torus|ebene,name?,"
            "masse:[Zahlen],position?:[x,y,z],drehung?:[x,y,z in Grad],farbe?:arc|amber|ok|warn|alarm|text|gedaempft} oder "
            "{form:linie,punkte:[[x,y,z]]}]}],hervorheben?:[name],beschriftungen?:[{objekt,text}]} (art modell), "
            "plan2d{einheit?,ebenen?:[name],elemente:[{art:linie|mass{von,bis,text?}|polylinie{punkte,geschlossen}|rechteck{x,y,b,h}|"
            "kreis{x,y,r}|bogen{x,y,r,von,bis}|text{x,y,text,groesse?},ebene?}]} (art plan; höchstens 800 Elemente), "
            "vergleich{optionen:[str] (2 bis 5),kriterien:[{name,werte:[str|zahl] je Option}],vorteile?:[[str]] und nachteile?:[[str]] "
            "je Option,fazit?}, zeitstrahl{ereignisse:[{zeit (Text),titel,text?}],einheit?}, gegenueber{sprachen:[von,nach],"
            "paare:[{original,uebersetzung}]}, lernkarten{karten:[{frage,antwort}]}, quiz{fragen:[{frage,optionen:[str] (2 bis 5),"
            "richtig:Index ab 0,erklaerung?}]}, anleitung{schritte:[{titel,text,sekunden?}],aktuell?:Index ab 0} (art lernen; "
            "Timer nur Anzeige ohne Ton), netz{form:ablauf|baum|mindmap,knoten:[{id:[a-z0-9_-],text,art?:start|ende|entscheidung|"
            "schritt}],kanten:[{von,bis,text?}]} (art netz; baum und mindmap: genau eine Wurzel, je Knoten eine Kante hinein), "
            "simulation{modell:pendel|feder|wurf|umlauf|gas|doppelpendel|welle,parameter:{...},laufzeit?:5 bis 60 s (30),tempo?:Zeitraffer 0,1 bis 100 "
            "(ohne: wählt das Fenster),spur?,beschreibung?} (art simulation; nur Parameter, keine Formeln; parameter je modell: "
            "pendel{laenge m,winkel Grad,anfangsgeschwindigkeit? Grad/s,daempfung? 1/s,g? m/s²}, feder{masse kg,federkonstante N/m,"
            "auslenkung m,daempfung? kg/s}, wurf{geschwindigkeit m/s,winkel Grad,hoehe? m,g? m/s²,luftwiderstand? 1/m}, "
            "umlauf{zentralmasse Sonnenmassen,koerper:[{name,abstand AE,exzentrizitaet?,phase? Grad,masse? 0 bis 0,01 Sonnenmassen,farbe?}] "
            "(1 bis 8),anziehung?:true für gegenseitige Anziehung}, "
            "gas{anzahl (2 bis 300),kasten:[b,h],radius,geschwindigkeit Kastenbreiten/s,schwerkraft?,stoesse?,startwert?}, "
            "doppelpendel{laenge1 m,laenge2 m,masse1? kg,masse2? kg,winkel1 Grad,winkel2 Grad,g? m/s²,daempfung? 1/s}, "
            "welle{wellen:[{amplitude m,wellenlaenge m,frequenz Hz,phase? Grad,richtung?:rechts|links}] (1 bis 3, überlagert),"
            "bereich? m auf der x-Achse (0: automatisch)}; höchstens 2 Simulationen je Ansicht), "
            "teilchen{form:molekuel,name?,atome:[{element:Symbol wie H|He|Og,position:[x,y,z] in Ångström}] (1 bis 300),"
            "bindungen?:[{von,bis:Index ab 0,ordnung?:1|2|3}] (ohne: aus den Abständen),beschriftungen?:[{atom:Index ab 0,text}],"
            "darstellung?:kugel-stab|kalotte} oder {form:atom,element,neutronen?,ladung?:-3 bis 3,schalen?:[Elektronen je Schale] "
            "(Summe = Ordnungszahl minus ladung; über 20 Elektronen Pflicht)} oder {form:orbital,orbital:1s|2s|2p_x|2p_y|2p_z|3s|"
            "3p_x|3p_y|3p_z|3d_xy|3d_xz|3d_yz|3d_x2-y2|3d_z2,punkte?:500 bis 5000,startwert?} (art teilchen; nur Daten, keine Formeln; "
            "höchstens 2 Moleküle oder Orbitale je Ansicht)"),
            "items": {"type": "object", "required": ["typ"], "properties": {"typ": {"type": "string", "enum": list(stage_schema.BLOCKS)}}}},
    }},
}
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_CODE = re.compile(r"```.*?```", re.S)
_MARKS = re.compile(r"[`*_#>|]+|^\s*[-+]\s+|^\s*\d+\.\s+", re.M)


def clean_text(raw: str) -> str:
    """Eine Zeile aus druckbaren Zeichen (Umbrüche werden Leerzeichen, damit nichts die Rahmung im Kontext stört), gekürzt."""
    return " ".join("".join(c if c.isprintable() else " " for c in raw).split())[:MAX_TEXT]


def spoken_text(raw: str) -> str:
    """Text für die Stimme: Codeblöcke weg, Links nur mit ihrem Text, Markdown-Zeichen weg, eine Zeile, höchstens MAX_SPOKEN."""
    text = _MARKS.sub(" ", _LINK.sub(r"\1", _CODE.sub(" ", raw)))
    return clean_text(text)[:MAX_SPOKEN].strip()


class Channel:
    """MCP-Seite: Handshake, Werkzeugliste, Benachrichtigungen. `out` ist stdout (oder ein Testpuffer)."""

    def __init__(self, out: TextIO, log: Callable[[str], None] = lambda s: print(s, file=sys.stderr, flush=True)):
        self.out, self.log = out, log
        self._lock = threading.Lock()
        self.ready = threading.Event()             # erst nach `initialized` dürfen Benachrichtigungen raus
        self._replies: deque[str] = deque(maxlen=MAX_QUEUE)
        self._final = False                        # seit dem letzten Abholen kam ein Ergebnis (nicht nur ein Zwischenstand)
        self.last_final = False                    # beim letzten Abholen war ein Ergebnis dabei
        self._cond = threading.Condition()
        self._perms: dict[str, dict[str, Any]] = {}      # offene Freigabe-Anfragen von Claude (C1), älteste zuerst
        self._fresh: deque[str] = deque()                 # davon noch nicht an kushim gegeben
        self._views: deque[dict[str, Any]] = deque(maxlen=MAX_VIEWS)   # geprüfte Ansichten (zeige), noch nicht abgeholt

    def say(self, text: str, interim: bool = False) -> None:
        with self._cond:
            self._replies.append(text)
            self._final = self._final or not interim
            self._cond.notify_all()

    def take(self, wait: float = 0.0) -> list[str]:
        """Alle wartenden Antworten (älteste zuerst); wartet bis `wait` Sekunden, falls noch keine da ist."""
        return self.take_events(wait)[0]

    def take_events(self, wait: float = 0.0) -> tuple[list[str], list[dict[str, str]]]:
        """(Antworten, neue Freigabe-Anfragen); wartet bis `wait` Sekunden, falls noch nichts da ist. Ob ein Ergebnis dabei
        war, steht danach in `last_final`."""
        with self._cond:
            self._expire()
            if not self._replies and not self._fresh and not self._views and wait > 0:
                self._cond.wait_for(lambda: bool(self._replies or self._fresh or self._views), timeout=min(wait, MAX_WAIT))
                self._expire()
            texts = list(self._replies)
            self._replies.clear()
            self.last_final, self._final = self._final, False
            perms = [{k: v for k, v in self._perms[i].items() if k != "at"} for i in self._fresh if i in self._perms]
            self._fresh.clear()
            return texts, perms

    def _expire(self) -> None:
        now = time.monotonic()
        for rid in [r for r, p in self._perms.items() if now - p["at"] > PERM_TTL]:
            del self._perms[rid]

    def permission_request(self, params: Any) -> None:
        """Claude fragt eine Freigabe an. Alles darin ist fremder Text: nur bereinigt, gekürzt und zum Vorlesen weitergegeben."""
        if not isinstance(params, dict):
            return
        rid = params.get("request_id")
        if not isinstance(rid, str) or not rid or len(rid) > 100 or not rid.isprintable():
            return
        entry = {"request_id": rid, "at": time.monotonic()}
        for key, limit in (("tool_name", 80), ("description", 300), ("input_preview", 500)):
            raw = params.get(key)
            entry[key] = clean_text(raw)[:limit] if isinstance(raw, str) else ""
        with self._cond:
            self._expire()
            if rid in self._perms:
                return
            while len(self._perms) >= MAX_PERMS:                  # älteste offene Anfrage fällt weg (das Terminal fragt weiter)
                del self._perms[next(iter(self._perms))]
            self._perms[rid] = entry
            self._fresh.append(rid)
            self._cond.notify_all()

    def answer(self, request_id: str, behavior: str) -> bool:
        """Antwort auf eine offene Anfrage an Claude senden. Nur bekannte, nicht abgelaufene IDs; jede nur einmal."""
        if behavior not in ("allow", "deny"):
            return False
        with self._cond:
            self._expire()
            if self._perms.pop(request_id, None) is None:
                return False
        self._send({"jsonrpc": "2.0", "method": "notifications/claude/channel/permission",
                    "params": {"request_id": request_id, "behavior": behavior}})
        return True

    def deny_all(self) -> int:
        """Notaus: alle offenen Anfragen ablehnen (fail-closed)."""
        with self._cond:
            ids = list(self._perms)
        return sum(self.answer(rid, "deny") for rid in ids)

    def take_views(self) -> list[dict[str, Any]]:
        """Alle wartenden Ansichten (älteste zuerst), danach ist die Liste leer."""
        with self._cond:
            views = list(self._views)
            self._views.clear()
            return views

    def show(self, raw: Any) -> dict[str, Any]:
        """Werkzeug `zeige`: prüfen, ablegen, kurze Rückmeldung an Claude (bei Fehlern nur ein fester Code)."""
        try:
            view = stage_schema.validate(raw)
        except stage_schema.ViewError as e:
            return {"content": [{"type": "text", "text": f"Ansicht abgelehnt ({e.code}). Bitte Format prüfen."}], "isError": True}
        with self._cond:
            self._views.append(view)
            self._cond.notify_all()
        return {"content": [{"type": "text", "text": "Wird abgeräumt." if view["schliessen"] else "Wird gezeigt."}]}

    def _call_tool(self, params: Any) -> dict[str, Any]:
        params = params if isinstance(params, dict) else {}
        args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if params.get("name") == "zeige":
            return self.show(args)
        if params.get("name") != "sprich":
            return {"content": [{"type": "text", "text": "Unbekanntes Werkzeug."}], "isError": True}
        text = spoken_text(args.get("text")) if isinstance(args.get("text"), str) else ""
        if not text:
            return {"content": [{"type": "text", "text": "Leerer Text, nichts vorgelesen."}], "isError": True}
        self.say(text, interim=args.get("zwischenstand") is True)
        return {"content": [{"type": "text", "text": "Wird vorgelesen."}]}

    def _send(self, msg: dict[str, Any]) -> None:
        line = json.dumps(msg, ensure_ascii=False)
        with self._lock:
            self.out.write(line + "\n")
            self.out.flush()

    def notify(self, text: str, meta: dict[str, str] | None = None) -> None:
        params: dict[str, Any] = {"content": text}
        if meta:
            params["meta"] = meta
        self._send({"jsonrpc": "2.0", "method": "notifications/claude/channel", "params": params})

    def handle(self, msg: Any) -> None:
        if not isinstance(msg, dict):
            return
        method, mid = msg.get("method"), msg.get("id")
        if method == "initialize":
            requested = (msg.get("params") or {}).get("protocolVersion")
            self._send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": requested if isinstance(requested, str) else "2025-06-18",
                "capabilities": {"tools": {}, "experimental": {"claude/channel": {}, "claude/channel/permission": {}}},
                "serverInfo": {"name": NAME, "version": VERSION},
                "instructions": INSTRUCTIONS,
            }})
        elif method == "notifications/initialized":
            self.ready.set()
        elif method == "notifications/claude/channel/permission_request":
            self.permission_request(msg.get("params"))
        elif method == "tools/list":
            self._send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [SPRICH_TOOL, ZEIGE_TOOL]}})
        elif method == "tools/call":
            self._send({"jsonrpc": "2.0", "id": mid, "result": self._call_tool(msg.get("params"))})
        elif method == "ping":
            self._send({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif mid is not None:                       # unbekannte Anfrage: sauber ablehnen, nie raten
            self._send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}})

    def serve_stdio(self, inp: TextIO) -> None:
        for line in inp:
            line = line.strip()
            if not line:
                continue
            try:
                self.handle(json.loads(line))
            except (ValueError, RecursionError):
                self.log("[kushim-channel] ungültige Zeile auf stdin ignoriert")


def make_http(channel: Channel, root: Path, token: str, port: int = 0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        timeout = 5                                   # langsame oder offen gehaltene Verbindungen binden keine Threads

        def log_message(self, fmt: str, *args: Any) -> None:     # nie auf stdout (gehört dem Protokoll)
            pass

        def _reply(self, code: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _allowed(self) -> bool:
            """Host-Kopf und Token prüfen; bei Fehler ist die Antwort schon gesendet."""
            port_now = self.server.server_address[1]
            if self.headers.get("Host", "") not in {f"127.0.0.1:{port_now}", f"localhost:{port_now}"}:
                self._reply(403, {"error": "bad_host"})
                return False
            auth = self.headers.get("Authorization", "")
            if not (auth.startswith("Bearer ") and hmac.compare_digest(auth[7:].encode(), token.encode())):
                self._reply(401, {"error": "unauthorized"})
                return False
            return True

        def _permission(self, data: Any) -> None:
            """`POST /permission {request_id, behavior}`: kushim beantwortet eine offene Freigabe-Anfrage von Claude."""
            if not isinstance(data, dict) or not isinstance(data.get("request_id"), str) or data.get("behavior") not in ("allow", "deny"):
                return self._reply(400, {"error": "bad_request"})
            if killswitch.is_triggered(root):                       # Notaus: nie freigeben
                return self._reply(423, {"error": "kill_switch"})
            if not channel.answer(data["request_id"], data["behavior"]):
                return self._reply(404, {"error": "unknown_request"})     # unbekannt, abgelaufen oder schon beantwortet
            self._reply(202, {"ok": True})

        def do_GET(self) -> None:
            """`GET /reply?wait=S`: kushim holt, was Claude per `sprich` vorlesen lassen will (wartet bis S Sekunden)."""
            if not self._allowed():
                return
            url = urlsplit(self.path)
            if url.path != "/reply":
                return self._reply(404, {"error": "not_found"})
            try:
                wait = float(parse_qs(url.query).get("wait", ["0"])[0])
            except ValueError:
                return self._reply(400, {"error": "bad_wait"})
            if killswitch.is_triggered(root):
                return self._reply(423, {"error": "kill_switch"})
            texts, perms = channel.take_events(max(0.0, min(wait, MAX_WAIT)) if wait == wait else 0.0)     # NaN wird 0
            views = channel.take_views()
            if (texts or perms or views) and killswitch.is_triggered(root):     # Notaus während des Wartens: nichts mehr weitergeben
                return self._reply(423, {"error": "kill_switch"})
            self._reply(200, {"texts": texts, "permissions": perms, "views": views, "final": bool(texts) and channel.last_final})

        def do_POST(self) -> None:
            if not self._allowed():
                return
            if self.path not in ("/message", "/permission"):
                return self._reply(404, {"error": "not_found"})
            try:
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY:
                return self._reply(413, {"error": "too_large"})
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError, RecursionError):
                return self._reply(400, {"error": "bad_json"})
            if self.path == "/permission":
                return self._permission(data)
            kind = data.get("kind", "voice") if isinstance(data, dict) else None
            if kind == "cancel":                                    # fester Text: über diesen Weg kommt nie Fremdtext als Abbruch
                text = CANCEL_TEXT
            elif kind == "voice":
                text = clean_text(data.get("text", "")) if isinstance(data.get("text"), str) else ""
            else:
                return self._reply(400, {"error": "bad_kind"})
            if not text:
                return self._reply(400, {"error": "empty"})
            if killswitch.is_triggered(root):
                return self._reply(423, {"error": "kill_switch"})
            if not channel.ready.is_set():
                return self._reply(503, {"error": "not_ready"})
            channel.notify(text, {"kind": kind})
            self._reply(202, {"ok": True})

    return ThreadingHTTPServer((BIND_HOST, port), Handler)


def watch_kill(channel: Channel, root: Path, stop: threading.Event, interval: float = 1.0) -> None:
    """Meldet den Notaus einmal an Claude (kind="kill"), sobald er ausgelöst wird; nach dem Aufheben wieder scharf."""
    told = False
    while not stop.wait(interval):
        fired = killswitch.is_triggered(root)
        if fired and not told and channel.ready.is_set():
            channel.deny_all()                                  # offene Freigaben: ablehnen (fail-closed)
            channel.notify(KILL_TEXT, {"kind": "kill"})
            told = True
        elif not fired:
            told = False


def other_owner(root: Path) -> int | None:
    """PID eines anderen, noch laufenden kushim-Channels, dem `run/channel.json` gehört; sonst None.

    Claude Code startet für Hintergrund-Sitzungen und Agenten derselben Sitzung weitere Channel-Server (gleiche MCP-
    Konfiguration). Würden sie die Datei überschreiben, spräche kushim mit einem Channel ohne Zuhörer und Claudes
    Antworten gingen verloren (Live-Test 2026-11-11). Darum gilt: Der erste Channel behält die Datei."""
    try:
        pid = json.loads((root / "run" / "channel.json").read_text(encoding="utf-8")).get("pid")
    except (OSError, ValueError, AttributeError):
        return None
    return pid if pid != os.getpid() and procs.pid_alive(pid) else None


def write_info(root: Path, port: int, token: str) -> Path:
    info = root / "run" / "channel.json"
    info.parent.mkdir(parents=True, exist_ok=True)
    tmp = info.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)      # nur der eigene Benutzer (POSIX); Windows: Profil-ACL
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"port": port, "token": token, "pid": os.getpid()}))
    os.replace(tmp, info)                                               # ersetzt auch eine liegengebliebene alte Datei
    return info


def main(root: Path | None = None) -> int:
    root = root or Path(__file__).resolve().parents[3]
    sys.stdout.reconfigure(encoding="utf-8")                  # Claude Code liest UTF-8; Windows-Pipes wären cp1252
    sys.stdin.reconfigure(encoding="utf-8")
    channel = Channel(sys.stdout)
    owner = other_owner(root)
    if owner is not None:                                      # Hintergrund-Sitzung/Agent: nur MCP, kein HTTP, Datei bleibt
        channel.log(f"[kushim-channel] ein anderer kushim-Channel (pid {owner}) ist aktiv; dieser bleibt stumm")
        channel.serve_stdio(sys.stdin)
        return 0
    token = secrets.token_urlsafe(32)
    httpd = make_http(channel, root, token)
    info = write_info(root, httpd.server_address[1], token)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    stop = threading.Event()
    threading.Thread(target=watch_kill, args=(channel, root, stop), daemon=True).start()
    channel.log(f"[kushim-channel] bereit auf {BIND_HOST}:{httpd.server_address[1]} (Token in {info.name})")
    try:
        channel.serve_stdio(sys.stdin)                         # endet, wenn Claude Code den Kanal schließt
    finally:
        stop.set()
        httpd.shutdown()
        try:
            if json.loads(info.read_text(encoding="utf-8")).get("pid") == os.getpid():
                info.unlink()
        except (OSError, ValueError):
            pass
    return 0
