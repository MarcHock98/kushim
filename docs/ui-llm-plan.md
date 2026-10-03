# Plan: Sprachmodell in der Oberfläche wechseln

Stand 2026-10-04. Ziel: Das lokale LLM lässt sich in der UI mit wenigen Klicks wechseln, sicher und umkehrbar, ohne
Terminal. Heute geht es nur per `kushim llm set <name>` und `install.ps1 -Llm <name>` (CLI). Noch nichts davon ist in der UI
gebaut (Tauri steht in Phase 2); dieser Plan legt Bildschirm, Ablauf und Backend-Bedarf fest. Gestaltung: Skill
`kushim-ui-design`.

## Grundsätze
1. **Dieselbe Logik wie die Kommandozeile.** UI und CLI rufen dieselben Funktionen auf (neu: `llm/manage.py`), keine zweite
   Implementierung in der UI.
2. **Ein Wechsel ist umkehrbar und verändert erst etwas, wenn die Probe gelingt.** Scheitert sie, bleibt das alte Modell aktiv.
   "Zurück zu <vorher>" ist immer ein Klick entfernt.
3. **Ein Modell ändert keine Regeln.** ActionGate, Freigabe-Leiste, Notaus, Sprecherprüfung und Systemprompt bleiben gleich.
   Das LLM liefert nur Text und hat keine Werkzeuge.
4. **Alles läuft über Loopback.** Ollama nur auf 127.0.0.1 (wie im Launcher). Die UI spricht nur mit dem Backend, das
   Backend nur mit Ollama über `net/loopback.py`.
5. **Laden aus dem Netz ist eine Außenwirkung** und läuft deshalb nur mit Freigabe (siehe unten). Wechseln zwischen
   bereits installierten Modellen braucht kein Netz.
6. **Ehrliche Anzeige.** Größe, Geschwindigkeit und Speicherbedarf als gemessene Zahlen, nicht als Versprechen.

## Bildschirm: Einstellungen > Sprachmodell
Aufbau von oben nach unten:
1. **Aktuelles Modell** (Karte): Name, Größe auf der Platte, Status ("Geladen", "Bereit", "Nicht installiert"), letzte
   gemessene Antwortzeit (erster Satz in s), Hinweis "gilt für Gespräch und Texteingabe".
2. **Installierte Modelle** (Liste, aus Ollama über Loopback): je Zeile Name, Größe, Datum, Knopf **Verwenden**; das
   aktive trägt ein Häkchen **und** das Wort "Aktiv". Entfernen (Papierkorb-Symbol mit Text) nur für nicht aktive Modelle,
   mit Freigabe.
3. **Modell hinzufügen:** Eingabefeld für den Ollama-Namen (z. B. `qwen3.5:9b`), Prüfung wie im Backend (`validate_model`)
   mit Fehlertext unter dem Feld, dazu eine kleine **Vorschlagsliste** aus einer lokalen Datei (`docs/llm-candidates.md`
   wird bei Bedarf vom Nutzer gepflegt; kein Netzabruf der Liste). Knopf **Laden …** öffnet die Freigabe-Leiste.
4. **Probe vor dem Umschalten:** Wahl eines Modells (Verwenden) startet im Hintergrund eine Probe und zeigt das Ergebnis,
   bevor der Wechsel gilt (siehe Ablauf).
5. **Hinweiszeile** (ruhig): "Andere Modelle antworten anders gut. Sicherheitsregeln bleiben gleich."

Zustände: leer (kein Modell installiert: Erklärung + "Modell hinzufügen"), lädt (Fortschrittsbalken mit Zahl, Abbrechen),
Fehler (Grund + nächster Schritt), Backend offline, Notaus aktiv (alle Knöpfe aus, Banner), eingeschränkter Modus.

## Ablauf Wechsel (Verwenden)
1. UI sendet `llm.set {model}`. Backend prüft den Namen (`validate_model`) und ob das Modell installiert ist
   (`manifest_rel`). Nein: Fehler "Nicht installiert. Laden?" mit Knopf.
2. **Probe** (Zeitlimit 60 s, nur Loopback): Modell laden (`warm_up`), eine feste kurze Frage ("Antworte mit einem Wort: ok")
   stellen, Zeit bis zum ersten Token und bis zum Ende messen. Gescheitert (Speicher voll, Zeitüberschreitung, leere
   Antwort): Fehler mit Zahlen, **nichts ändert sich**.
3. **Ergebnis anzeigen:** "Antwort in 0,4 s, erster Satz nach 0,2 s" und bei Auffälligkeit ein Hinweis ("langsamer als das
   bisherige Modell, 2,1 s gegen 0,3 s").
4. Der Nutzer bestätigt **Jetzt verwenden**. Backend schreibt `[llm] model` atomar in `config.toml` (`Config.set_llm_model`,
   alte Zeile merkt es sich für "Zurück") und tauscht das Modell **zwischen zwei Antworten** aus (nie mitten in einer
   Antwort). Das alte Modell wird entladen (`keep_alive` 0), das neue bleibt warm.
5. Audit-Eintrag: `llm_model_changed alt->neu`. Toast "Sprachmodell: neu (zurück zu alt)".
6. **Rückweg:** "Zurück zu <vorher>" wiederholt dieselben Schritte (mit Probe) für das vorherige Modell.

## Ablauf Laden (aus dem Netz)
- **Freigabe-Leiste** (`ASK`): "Modell `qwen3.5:9b` von registry.ollama.ai laden." mit Zeilen Quelle (nur diese Domain),
  Zielordner (`models/ollama`), freier Speicher auf der Platte, Hinweis "mehrere GB, kann Minuten dauern". Knöpfe
  **Ablehnen** (Standard) und **Laden**.
- Ausführung im Backend über die Ollama-Schnittstelle (`/api/pull`, nur Loopback); der Netzzugriff geschieht im
  Ollama-Prozess zu `registry.ollama.ai`. Fortschritt (Bytes, Prozent) als Ereignisstrom, **Abbrechen** jederzeit, **Notaus
  bricht ab**. Nach dem Laden: automatisch Prüfsumme/Manifest vorhanden (`doctor`-Logik), dann Angebot zur Probe.
- Vorab-Prüfung: freier Speicher >= Größe + 2 GB, sonst Ablehnung mit Zahlen. Die Größe liefert Ollama beim Start des
  Ladens; ist sie zu groß, wird sofort abgebrochen.
- **Fremde Quellen** (`hf.co/...` oder `Nutzer/Modell`): `validate_model` erlaubt sie, die UI verlangt zusätzlich eine
  zweite Bestätigung mit Warnung ("Gewichte eines Dritten, nicht aus der offiziellen Bibliothek"). Standardvorschläge
  stammen nur aus der offiziellen Bibliothek.
- Entfernen: `llm.remove {model}` über `ASK`, nie das aktive Modell, nie das letzte installierte.

## Was das Backend dafür liefern muss
1. **`llm/manage.py`** (neu, von CLI und UI genutzt): `installed(root)` (liest Ollama `/api/tags`, Rückfall auf Manifest-Ordner),
   `probe(client)`, `activate(cfg, client, name)` (Probe + atomar schreiben + Austausch), `rollback(cfg)`,
   `pull(client, name, progress)` und `remove(client, name)` mit Abbruch/Notaus. `kushim llm set` ruft `activate` auf.
2. **API-Typen** (WebSocket 127.0.0.1, Token, Default-Deny; Kern `api/protocol.py`): `llm.get`, `llm.list`, `llm.probe`,
   `llm.set`, `llm.rollback`, `llm.pull` (ASK, Strom), `llm.pull_cancel`, `llm.remove` (ASK). Ereignisse: `llm.progress`,
   `llm.changed`. Fehler neutral, keine Pfade nach außen.
3. **Aktions-Registrierung:** `llm.pull` und `llm.remove` als `ActionSpec` (Außenwirkung bzw. Löschen, Standard `ASK`);
   `llm.set` und `llm.rollback` als umkehrbar mit Probe (`REVERSIBLE`, ohne Rückfrage, weil lokal und umkehrbar).
4. **Austausch zur Laufzeit:** `Pipeline` hält das Modell über ein Objekt, das zwischen Antworten getauscht werden kann
   (heute fest in `build_live`); der Tausch ist unter einer Sperre, damit nie eine halbe Antwort wechselt.
5. **Zustand:** Das vorherige Modell steht in `run/llm-state.json` (nicht im Git, nicht sensibel) für "Zurück".
6. Der Vault-Schlüssel, Token und Aufnahmen tauchen in keinem dieser Typen auf.

## Gestaltung (Skill `kushim-ui-design`)
Karten statt Tabellen, ein Primärknopf je Bereich (Verwenden bzw. Laden), Ampelzeilen mit Text für Status, Fortschritt als
Balken mit Zahl (`role="meter"`), Freigabe-Leiste wie in `screens.md`, Texte Deutsch und Du-Form. Modellname in
`--font-mono`. Kein Dark Pattern: kein vorausgewähltes Laden, Standardfokus auf Ablehnen.

## Tests
- Backend mit Fake-Ollama (Loopback-Server wie in `tests/test_ollama.py`): Namen-Validierung, Probe erfolgreich/gescheitert
  (Config bleibt unverändert), atomares Schreiben, Rückweg, Austausch zwischen zwei Antworten (nie mittendrin), Pull mit
  Fortschritt/Abbruch/Notaus, zu wenig Speicher, Entfernen des aktiven Modells verweigert.
- API: Default-Deny, Token, `llm.pull`/`llm.remove` ohne Freigabe verweigert, neutrale Fehler.
- `tests/test_no_egress.py` bleibt grün; der Netzzugriff läuft nur im Ollama-Prozess.
- UI: Komponententest mit Mock-Backend für alle Zustände; manueller Durchlauf durch den Nutzer.

## Offene Punkte (Entscheidung beim Nutzer)
1. **Darf die UI Modelle laden?** Empfehlung: ja, nur mit Freigabe-Leiste und nur von `registry.ollama.ai`; sonst bleibt es bei
   `install.ps1 -Llm`.
2. **Automatischer Vorschlag nach Hardware?** Die RTX 3070 (8 GB) teilt sich den Speicher mit Whisper; die UI könnte größere
   Modelle als "könnte knapp werden" markieren. Empfehlung: nur als Hinweis nach der Probe, keine Sperre.
3. **Mehrere Modelle für verschiedene Aufgaben** (schnell für Gespräch, groß für Recherche)? Heute genau ein Modell.
