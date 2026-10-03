# Plan: Setup in der Oberfläche (nach dem ersten Start)

Stand 2026-10-04. Entscheidungen des Nutzers: Das Setup erscheint **beim ersten Start** der Anwendung und ist **danach
jederzeit wiederholbar**. Es enthält vier Schritte (unten). **Alles ist überspringbar**, auch Vault und Stimme.

Noch nichts davon ist gebaut: Die Oberfläche (Tauri) steht in Phase 2 der Roadmap. Dieser Plan legt fest, was das
Backend dafür liefern muss und wie die Bildschirme aussehen, damit UI und Backend später zusammenpassen.

## Grundsätze
1. **Dieselbe Logik wie die Kommandozeile.** Das Setup ruft die vorhandenen Funktionen auf (doctor, Vault, Aufnahme,
   Einschreiben, Wake-Word-Config, Notaus). Es gibt keine zweite Implementierung in der UI.
2. **Der Nutzer bestätigt jeden Schritt selbst** (Enter/Klick), nichts läuft automatisch durch. Aufnahmen: Start und
   Ende bestimmt er (wie bei `voice enroll`).
3. **Geheimnisse bleiben draußen.** Der Vault-Schlüssel wird nie im Fenster oder über die API angezeigt; die UI erklärt
   nur die Sicherung und lässt sie bestätigen ("Ich habe den Schlüssel gesichert", mit Hinweis auf `kushim key export`
   im eigenen Terminal). Aufnahmen bleiben lokal; Stimmprofil nur im Vault.
4. **Überspringen heißt nie Sicherheit abschalten.** Siehe "Eingeschränkter Modus".
5. **Ehrliche Anzeige.** Zahlen und Grenzen aus dem Einschreiben (Schwelle, Abstand zu Fremden, Warnung bei geringer
   Trennung) werden gezeigt, nicht beschönigt.

## Ablauf und Auslöser
- **Erkennung "erster Start":** Es fehlt der Vault, das Stimmprofil oder `setup-state.json` (siehe unten) meldet offene
  Schritte. Dann öffnet die UI beim Start das Setup.
- **Wiederholbar:** Einstellungen -> "Setup" zeigt dieselbe Übersicht mit Häkchen je Schritt; jeder Schritt lässt sich
  einzeln neu starten (z. B. Stimme neu einschreiben, Wake Words ändern).
- **Zustand:** `run/setup-state.json` (nicht im Git, nicht sensibel): je Schritt `done | skipped | open` mit Datum.
  Maßgeblich bleiben die echten Fakten (existiert der Vault, gibt es ein Stimmprofil); die Datei merkt sich nur
  "übersprungen", damit die UI nicht bei jedem Start nervt.
- **Übersicht (Startbild des Setups):** Liste der vier Schritte mit Status, "Weiter", "Überspringen", "Später".

## Die vier Schritte

### 1. Systemcheck und Vault/Schlüssel
- Zeigt die Punkte von `kushim doctor` als Ampelliste (Modelle, GPU-Bibliotheken, Ollama, Pakete) mit dem Befehl/Link zur
  Behebung. Fehlende Modelle: Hinweis auf `install.ps1` (die UI lädt nichts selbst nach).
- Vault anlegen (Button; legt auch den Schlüssel im Credential-Manager an). Danach eine Seite "Schlüssel sichern":
  Erklärung, Hinweis auf `kushim key export` im eigenen Terminal, Checkbox "gesichert". Ohne Häkchen kein "Weiter",
  aber "Überspringen" ist erlaubt (mit Warnung "Daten gehen bei Neuinstallation von Windows verloren").
- Übersprungen heißt: kein Gedächtnis, kein Stimmprofil, siehe Eingeschränkter Modus.

### 2. Mikrofon, Lautsprecher und Stimme einschreiben
- Geräte wählen (Liste aus `sounddevice`, Namensteil wird gespeichert), Pegelanzeige live, Testton, kurzer Mikrofon-Test.
- Stimme einschreiben: die 10 Absätze, je Absatz **Start** und **Fertig** (= Enter), danach **Behalten / Neu**. Anzeige
  von Länge und Pegel, Hinweise bei zu leise/übersteuert/zu kurz (wie `check_take`). Fortschritt 1 bis 10.
- Ergebnis: Anzahl Prototypen, deine Werte, Werte der Vergleichsstimmen, Schwelle, **Abstand** und die Warnung bei
  geringer Trennung. Danach "Test": kurze und lange Sätze, Ergebnis je Äußerung (Wert, Schwelle, Länge, "stark"),
  Hinweis, eine zweite Person sprechen zu lassen.
- Übersprungen heißt: kein Sprechen (siehe Eingeschränkter Modus).

### 3. Wake Words
- Liste aus `wakewords.toml` mit Schaltern (an/aus), Empfindlichkeit-Regler je Wort (`threshold`), Wort hinzufügen
  (Buchstaben und Leerzeichen, Prüfung wie im Backend), entfernen (mindestens eines bleibt aktiv).
- Live-Test: Mikrofon läuft, Treffer erscheinen als Anzeige mit Wortname und Zeit; Hinweis auf Schwächen kurzer Wörter und
  Wörter mit gleichem Anfang ("kush"/"kushim").
- Speichern schreibt dieselbe zentrale Datei (`wakewords.toml`), Änderungen gelten ab dem nächsten Start.

### 4. Sicherheit und Notaus
- Kurze Übersicht der Grundregeln (Schäden verboten, lokal zuerst, Bestätigung bei Außenwirkung, Geldlimit 0).
- Notaus ausprobieren: Schaltfläche in der UI, Verknüpfung, Sprachbefehl "Notaus"; jeweils Anzeige "ausgelöst" und
  danach "Aufheben" (bewusster Klick, entspricht `kushim resume`). Der Notaus-Knopf bleibt danach in jedem Fenster sichtbar.

## Eingeschränkter Modus (wenn Schritte übersprungen wurden)
| Übersprungen | Folge | Bleibt unverändert |
|---|---|---|
| Vault | kein Gedächtnis, kein Stimmprofil, kein Sprechen | Notaus, Sicherheitsregeln |
| Stimme | **Sprechen bleibt gesperrt** (fail-closed wie heute); Texteingabe in der UI ist möglich | Wake Word nur als Anzeige, Antworten nur am Bildschirm |
| Wake Words | Standardwörter aus der Vorlage | Rest |
| Mikrofon/Lautsprecher | Standardgeräte von Windows | Rest |
| Sicherheit/Notaus | nichts, er wirkt trotzdem | alles |

Wichtig: "Überspringen" ändert keine Sicherheitsregel. In der Texteingabe gilt weiter: keine Werkzeuge, jede Aktion
läuft über ActionGate und Freigabe-Leiste; Änderungen am Wake-Word-System brauchen in der UI eine Bestätigung per Klick.

## Was das Backend dafür liefern muss
Die Funktionen sind größtenteils vorhanden (CLI). Für die UI nötig:
1. **API-Typen** (WebSocket, 127.0.0.1, Token; Kern steht in `api/protocol.py`): `setup.status`, `vault.init`,
   `vault.key_backup_confirm`, `audio.devices`, `audio.level` (Strom), `audio.test_tone`, `voice.record_start`,
   `voice.record_stop`, `voice.record_keep`, `voice.enroll_compute` (mit Fortschritt), `voice.test`, `wake.get`,
   `wake.set` (validiert über `wakeconfig`), `wake.test` (Strom von Treffern), `safety.kill`, `safety.resume`.
2. **Bibliotheksfunktionen statt CLI-Code:** Die Abläufe in `cli.py` (Einschreiben, Aufnahme-Sitzung, Doctor) in
   wiederverwendbare Funktionen mit Rückrufen für Fortschritt ziehen; CLI und UI rufen dieselben.
3. **Ereignisse:** Server -> UI für Pegel, Aufnahmefortschritt, Trefferanzeige.
4. **`setup-state.json`** lesen/schreiben (Schreibzugriff nur für diese Datei, atomar).
5. Der Schlüssel taucht in keinem API-Typ auf; Aufnahmen werden nie über die API übertragen (nur Pegel und Ergebnisse).

## Tauri-Aufgaben (nach der Toolchain-Installation, vom Nutzer freigegeben, nur offizielle Quellen)
- Fenster mit Logo; Setup-Assistent als Seitenfolge mit Fortschrittsleiste links, Inhalt rechts, unten "Zurück / Überspringen /
  Weiter"; Notaus-Knopf immer oben rechts.
- Pegelanzeige und Trefferanzeige als einfache Balken; Aufnahme-Absatz groß lesbar, Start/Fertig als große Knöpfe, Leertaste/Enter
  als Tastenkürzel.
- Barrierefrei: Tastatur-Bedienung, ausreichender Kontrast, keine reine Farbcodierung (Ampel zusätzlich mit Text).

## Tests
- Backend: API-Typen einzeln mit Fakes (Token, Validierung, Fehlerfälle, kein Schlüssel in Antworten).
- Setup-Logik: "erster Start"-Erkennung (kein Vault, kein Profil, Datei fehlt/kaputt), Überspringen/Wiederholen, atomares Schreiben.
- UI: Komponententests der Schritte mit gefälschtem Backend; manueller Durchlauf durch den Nutzer (Mikrofon).

## Offene Punkte
- Soll die UI später auch Wake Words per Mikrofon anlernen (Aufnahme eigener Beispiele)? Aktuell nur Text und Auswahl.
- Mehrere Profile (z. B. weitere Person im Haushalt)? Heute genau ein Stimmprofil.
- Sprache der Oberfläche: aktuell Deutsch; Englisch später möglich.
