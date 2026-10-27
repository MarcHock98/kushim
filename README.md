# kushim

Ein lokaler „Jarvis“ als Sprach-Vorderseite für **Claude Code**: Du sprichst, kushim erkennt lokal Wake Word, deine Stimme und deinen Befehl, gibt ihn an deine laufende Claude-Code-Sitzung und liest die Antwort vor. Claude Code ist die einzige KI; kushim selbst hat kein Sprachmodell.

**Die Daten gehören dir.** Spracherkennung, Sprecherprüfung und Stimme laufen komplett auf deinem Rechner. Audio verlässt nie den PC; an Anthropic geht nur der erkannte Befehlstext über Claude Code selbst.

Inhalt: [Was es heute kann](#was-es-heute-kann) · [Voraussetzungen](#voraussetzungen) · [Installation](#installation) · [Erster Start](#erster-start) · [Täglicher Gebrauch](#täglicher-gebrauch) · [Konfiguration](#konfiguration) · [Netzwerk und Datenschutz](#netzwerk-und-datenschutz) · [Eigene Stimme (Klon)](#eigene-stimme-klon) · [Fehlerbehebung](#fehlerbehebung) · [Deinstallation](#deinstallation) · [Entwicklung](#entwicklung)

## Was es heute kann

- **Sprechen per Wake Word:** Du sagst eines deiner Wake Words („hey kushim“, „kushim“, „hi kushim“ …, alle in **einer zentralen Datei** einstellbar), kushim antwortet „Ja?“ und hört deinen Befehl. Vor dem Wake Word läuft nur ein kleines lokales Erkennungsmodell: keine Spracherkennung, keine Weitergabe, keine Speicherung.
- **Nur auf deine Stimme:** Sprecherverifikation mit Mehr-Prototypen-Profil aus langer Aufnahme. Fremde Stimmen bekommen keine Antwort. Längere Äußerungen werden in Fenstern geprüft (sicherer). Ohne eingeschriebenes Stimmprofil startet das Sprechen gar nicht.
- **Notaus:** per Desktop-Verknüpfung oder per Sprachbefehl („Notaus“, „stopp alles“). Wirkt für jede Stimme.
- **Lokal:** Whisper (Spracherkennung, GPU), Piper (deutsche Stimme), optional eigene Stimme (Klon).
- **Verschlüsseltes Gedächtnis (Vault)** für das Stimmprofil, mit Backups.

**Umbau (Roadmap v2):** Die alten lokalen Werkzeuge (Ollama-Sprachmodell, Websuche, Timer, Notizen, eigene Claude-Läufe) sind entfernt. Die Brücke zu Claude Code (Channel) steht: kushim gibt Befehle an die laufende Claude-Code-Sitzung und liest Claudes Antwort vor. Ein gemeinsamer Startbefehl (`kushim start`) und Freigaben per Stimme folgen. Stand und Pläne: [ROADMAP.md](ROADMAP.md).

## Voraussetzungen

| | |
|---|---|
| System | Windows 10 oder 11 (64 Bit) |
| Grafikkarte | NVIDIA mit mindestens 8 GB VRAM (getestet: RTX 3070), aktueller NVIDIA-Treiber |
| Speicher | mindestens 10 GB frei (Modelle ca. 2 GB, Python-Umgebung ca. 3 GB, optional Stimmklon mehr) |
| RAM | 16 GB, besser 32 GB |
| Python | 3.11 oder 3.12 von [python.org](https://www.python.org/downloads/) (Haken bei „Add Python to PATH“) |
| Hardware | Mikrofon und Lautsprecher/Kopfhörer |
| Internet | für die Installation; im Betrieb nur Claude Code selbst (zu Anthropic) |
| Claude Code | installiert und angemeldet (`claude`), siehe [ROADMAP.md](ROADMAP.md) Phase B |

Git ist nur nötig, wenn du das Projekt von GitHub holst.

## Installation

### Variante A: ein Befehl (empfohlen)

1. Projekt holen:
   ```powershell
   git clone https://github.com/MarcHock98/kushim.git
   cd kushim
   ```
   (Oder die ZIP von GitHub entpacken und im Ordner ein PowerShell-Fenster öffnen.)
2. Installationsskript starten:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\install.ps1
   ```

Das Skript macht der Reihe nach und ist jederzeit wiederholbar (Vorhandenes wird übersprungen):

1. Voraussetzungen prüfen (Python, NVIDIA-GPU, Speicherplatz)
2. Python-Umgebung `.venv` anlegen
3. Python-Pakete in festen Versionen installieren
4. Modelle laden und per SHA-256 prüfen: Whisper large-v3-turbo, deutsche Piper-Stimme, Sprecher-Modell, Wake-Word-Modelle
5. Logo-Icon erzeugen
6. Desktop-Verknüpfungen anlegen: **kushim start**, **kushim App**, **kushim sprechen**, **kushim NOTAUS**
7. Am Ende fragt es, ob es den Vault anlegen und deine Stimme einschreiben soll (nur mit deinem Ja)

Schalter:

| Schalter | Wirkung |
|---|---|
| `-Check` | nur prüfen, was fehlt; ändert und lädt nichts |
| `-NoPrompt` | keine Rückfragen (Vault und Stimme werden dann nicht angelegt) |
| `-SkipShortcuts` | keine Desktop-Verknüpfungen |
| `-SkipPath` | den Befehl `kushim` nicht in den Benutzer-PATH eintragen (nachträglich: `.\scripts\add-path.ps1`, entfernen: `-Remove`) |

Danach weiter bei [Erster Start](#erster-start).

### Variante B: von Hand, Schritt für Schritt

Dasselbe wie das Skript, einzeln im Projektordner (PowerShell):

```powershell
# 1. Umgebung und Pakete
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e ".[dev,voice]"
.\.venv\Scripts\python -m pip install "openwakeword==0.6.0" --no-deps

# 2. Modelle (Whisper, Stimme, Sprecher, Wake Words), mit Prüfsummen
.\.venv\Scripts\python scripts\fetch_models.py

# 3. Logo-Icon (für die Verknüpfungen)
.\.venv\Scripts\python scripts\make_icon.py

# 4. Kontrolle
.\.venv\Scripts\python -m kushim.cli doctor
```

Die Desktop-Verknüpfungen legt nur `install.ps1` an; von Hand erstellst du Verknüpfungen auf `.venv\Scripts\python.exe` mit den Argumenten `-m kushim.cli talk` und `-m kushim.cli kill`, Arbeitsordner = Projektordner.

Von früheren Versionen können `tools\ollama`, `models\ollama` und die Verknüpfung **kushim** übrig sein; kushim braucht sie nicht mehr, du kannst sie löschen.

## Erster Start

Diese Schritte machst nur du (sie betreffen deinen Schlüssel und deine Stimme). Immer im Projektordner:

1. **Vault anlegen.** Legt den verschlüsselten Speicher an und erzeugt einen Schlüssel im Windows-Credential-Manager:
   ```powershell
   .\.venv\Scripts\python -m kushim.cli memory init
   ```
2. **Schlüssel sichern.** Ohne ihn sind die Daten bei einer Neuinstallation von Windows verloren. Das Ergebnis in deinen Passwortmanager kopieren (nicht in eine Datei im Projekt, nicht in einen Chat):
   ```powershell
   .\.venv\Scripts\python -m kushim.cli key export
   ```
3. **Stimme einschreiben.** Du liest die 10 Absätze aus `docs/voice-recording-text.md` (Teil B, etwa 5 Minuten) vor. Daraus entsteht dein Stimmprofil: viele Stimmabdrücke aus 3-Sekunden-Fenstern, gebündelt zu mehreren Prototypen, mit einer aus deinen Daten berechneten Schwelle. Im Vault liegen nur Zahlenvektoren. **Dieselben Aufnahmen** (`voice-data/clone/`, nicht im Git) dienen später für den Stimmklon, du sprichst nur einmal.
   ```powershell
   .\.venv\Scripts\python -m kushim.cli voice enroll
   ```
   **So läuft jeder Absatz:** Enter drücken, kurz warten und vorlesen, am Ende des Absatzes selbst Enter drücken (kein Zeitlimit durch Stille; Tastenklick vorn und hinten wird abgeschnitten). Danach „Enter = behalten“ oder „r + Enter“ zum Neuaufnehmen. Wer lieber die Stille das Ende bestimmen lässt: `--auto`.

   Optional ein bestimmtes Mikrofon: `--mic "Arctis 5 Chat"`. Alles neu aufnehmen: `--record`. Das alte kurze Einschreiben (5 Sätze, weniger robust): `--quick`.
4. **Prüfen, ob dich kushim erkennt** (und andere nicht). Es zeigt pro Äußerung Ähnlichkeit, Schwelle, Länge, Fenster und ob die Prüfung „stark“ war. Teste kurze und lange Sätze und lass einmal eine zweite Person sprechen:
   ```powershell
   .\.venv\Scripts\python -m kushim.cli voice test
   ```
5. **Gesamtkontrolle:**
   ```powershell
   .\.venv\Scripts\python -m kushim.cli doctor
   ```
   Alles `[ok]` heißt: bereit.

## Täglicher Gebrauch

| Aktion | So |
|---|---|
| Oberfläche öffnen | Desktop-Verknüpfung **kushim App** (oder `kushim app`): startet Sprache und API im Hintergrund, öffnet das Fenster und beendet beim Schließen alles, was sie selbst gestartet hat. `kushim app --no-voice` öffnet nur das Fenster mit der API (ohne Mikrofon). Einmalig bauen: `cd ui` und `npx tauri build --no-bundle` (braucht Node und Rust). |
| **Mit Claude sprechen** | Desktop-Verknüpfung **kushim start** (oder `kushim start [ordner]`): öffnet Claude Code mit dem kushim-Channel in einem eigenen Fenster im freigegebenen Arbeitsordner (`kushim claude add <name> <pfad>`) und startet das Zuhören. Im Claude-Fenster einmal den Hinweis zum Entwicklungs-Channel bestätigen. Diese Claude-Sitzung lädt nur den kushim-Server (keine anderen MCP-Server), Telemetrie aus. `kushim doctor` prüft Version (ab 2.1.234) und Anmeldung. |
| Starten und sprechen | Desktop-Verknüpfung **kushim sprechen** (oder `python -m kushim.cli talk`). Nach dem Start steht im Fenster, welche Wake Words gelten. |
| Sprechen | Wake Word und Befehl in einem Zug sagen („hey kushim, wie spät ist es?“), kushim sagt „Ich geb's an Claude.“ und liest Claudes Antwort vor (Claude Code muss mit dem kushim-Channel laufen; braucht Claude länger, kommt die Antwort später von selbst). Sagst du nur das Wake Word, kommt nach `command_wait_seconds` (Standard 1,5) ein „Ja?“ und kushim wartet `listen_seconds` (Standard 4) auf den Befehl; bleibt es still, hört kushim wieder nur aufs Wake Word. |
| Beenden | `Strg+C` im Fenster |
| **Notaus** | Verknüpfung **kushim NOTAUS** anklicken oder „Notaus“ / „stopp alles“ sagen. Danach startet kushim erst wieder, wenn du bewusst aufhebst: `python -m kushim.cli resume`. |
| Wake Words ändern | In der zentralen Datei `wakewords.toml` (siehe unten); gilt ab dem nächsten Start. |
| Stimmprofil prüfen / löschen | `python -m kushim.cli voice status` / `voice reset` |
| Backup | `python -m kushim.cli memory backup` |

Geräte wählen (Namensteil genügt): `python -m kushim.cli talk --mic "Arctis 5 Chat" --out "Arctis 5 Game"`. Ohne Angabe gelten die Windows-Standardgeräte.

## Konfiguration

Kopiere `config.example.toml` nach `config.toml` (oder `%APPDATA%\kushim\config.toml`). `config.toml` ist nicht im Git.

**Arbeitsordner für Claude:** `kushim claude add <name> <pfad>` gibt einen Git-Ordner frei (Home, Laufwerk, System, AppData und der Vault gehen nie), `kushim claude folders` zeigt sie, `kushim claude remove <name>` entzieht die Freigabe. `kushim claude check` prüft, ob die Claude CLI da und angemeldet ist. Die Brücke, über die kushim Befehle an Claude Code gibt, folgt (Roadmap Phase B).

**Abbrechen:** Sag "abbrechen" (auch "brich das ab", "vergiss es"), und kushim beendet die laufende Sprachausgabe. Das geht ohne Sprecher-Prüfung (Abbrechen ist sicher). Im Terminal bricht Strg+C ab. Das ist **nicht der Notaus**: Abbrechen sperrt nichts, der Notaus hält alles an und sperrt bis `kushim resume`.

**Grafikkarten:** `kushim gpu` zeigt die erkannten NVIDIA-Karten und welche Whisper nutzt (bei mehreren: die größte). Anpassen unter `[gpu]` in `config.toml` (`whisper = "auto" | "cpu" | "1"`).

```toml
[memory]
location = "local:~/kushim-vault"   # einziger Ort, der den Speicherort kennt

[privacy]
claude_enabled = false               # alter Schalter (Modus C); wird mit der Brücke zu Claude Code neu geregelt
```

### Wake Words: eine zentrale Datei

Alle Wake Words stehen **nur** in `wakewords.toml` im Projektordner. Fehlt sie, gilt die mitgelieferte Vorlage `wakewords.example.toml` (nicht ändern, sondern kopieren). Die Datei ist nicht im Git.

```toml
[settings]
cooldown_seconds = 2.0      # Ruhezeit nach einem Treffer
command_wait_seconds = 1.5  # Wake Word und Befehl in einem Zug: so lange wartet kushim auf den Befehl, bevor es "Ja?" sagt
listen_seconds = 4.0        # nach "Ja?" (nur Wake Word gesagt): so lange wartet kushim auf den Beginn deines Befehls
end_silence_seconds = 0.9   # so lange Stille beendet deine Äußerung (länger = Denkpausen erlaubt)
max_seconds = 60.0          # längste einzelne Äußerung
follow_up_seconds = 8.0     # Gespräch: nach einer Antwort so lange ohne Wake Word zuhören (0 = aus); "das war's" beendet es
barge_in = true             # Unterbrechen: Dazwischensprechen stoppt kushim sofort (Kopfhörer empfohlen)
barge_in_level = 250.0      # Mikrofonpegel, ab dem es als Unterbrechen zählt (höher = unempfindlicher, z. B. bei Lautsprechern)
speech_level = 200.0        # Mikrofonpegel, ab dem es als Sprechen zählt; passt es nicht zu deinem Mikrofon: `kushim voice level --apply`
preroll_seconds = 1.0       # so viel Audio VOR dem Wake Word (nur im Speicher) kommt zum Befehl dazu, damit der Anfang nicht fehlt
barge_in_ms = 240           # so lange muss der Pegel anhalten

[[wakeword]]
name = "hey kushim"         # beliebiges Wort/Wendung: nur Buchstaben und Leerzeichen
engine = "kws"              # "kws" = freies Wort ohne Training
enabled = true
threshold = 0.15            # optional; kleiner = empfindlicher (Standard 0.15)
boost = 2.0                 # optional; größer = leichter erkannt (Standard 2.0)

[[wakeword]]
name = "alexa"
engine = "openwakeword"     # vortrainiert: alexa, hey_mycroft, hey_jarvis, hey_rhasspy, timer, weather
enabled = false             # oder eigene .onnx-Datei aus models/wakewords/
```

Standard sind deine sechs Wörter „hey kushim“, „kushim“, „kush“, „hallo kush“, „hi kushim“ und „kushi“. Ohne Änderung läuft kein „hey jarvis“.

- Änderungen gelten ab dem nächsten Start von `kushim talk`. Eine fehlerhafte Datei wird nicht ignoriert: `talk` startet nicht und nennt den Fehler.
- Einmalig überschreiben (ohne die Datei zu ändern): `talk --wake-words "hey kushim,kushim"`.
- **Zuverlässigkeit (ehrlich):** Die freien Wörter nutzen ein kleines englisches Erkennungsmodell, das nicht auf Deutsch oder deinen Namen trainiert ist. In Tests mit künstlicher deutscher Stimme wurden 11 von 18 Aufrufen erkannt, bei 0 Fehlalarmen in 10 normalen Sätzen. Mit deiner echten Stimme kann das besser oder schlechter sein; deshalb ist es einstellbar (`threshold`, `boost`). Sehr kurze Wörter („kush“, „kushi“) lösen leichter versehentlich aus, und Wörter mit gleichem Anfang (kush/kushim) lassen sich nicht sicher unterscheiden. Eine Fehlauslösung öffnet nur das Zuhören: Befehle brauchen weiter deine Stimme.

Vault verschieben (z. B. auf ein anderes Laufwerk): `python -m kushim.cli memory migrate --to "local:D:/kushim-vault"` (verifiziert, der alte Vault bleibt als Rollback).

## Netzwerk und Datenschutz

- **Installation:** Netzwerk nur zu `pypi.org` (Pakete), `github.com` (Sprecher-Modell, Wake-Word-Modelle) und `huggingface.co` (Whisper, Stimme). Alles in festen Versionen, Modelle per Größe und SHA-256 geprüft.
- **Betrieb:** kushim selbst geht nie ins Internet. Sein Netzwerkcode spricht ausschließlich 127.0.0.1: `src/kushim/net/server.py` (API für die eigene Oberfläche) und `src/kushim/net/loopback.py` (für die kommende Brücke zu Claude Code). Ein Test (`tests/test_no_egress.py`) verhindert anderen Netzwerkcode. Nach außen spricht nur Claude Code selbst (zu Anthropic).
- **Mikrofon:** Audio bleibt im Arbeitsspeicher und wird nicht gespeichert. Vor dem Wake Word sieht nur das kleine Wake-Word-Modell das Signal.
- **Stimmprofil:** nur ein Zahlenvektor, im verschlüsselten Vault.
- **Schlüssel:** im Windows-Credential-Manager, nie im Vault, nie im Projekt.

## Eigene Stimme (Klon)

Für eine Stimme, die wie du klingt, nimmst du Material auf (nur lokal, Ordner `voice-data/` ist nicht im Git). Text dazu: `docs/voice-recording-text.md`, Teil B.

```powershell
.\.venv\Scripts\python -m kushim.cli voice record --mic "Arctis 5 Chat"
```

Es nimmt 10 Absätze mit 24 kHz auf. Du startest und beendest jeden Absatz selbst mit Enter und kannst ihn behalten oder neu aufnehmen (`--auto`: Ende per Stille). Es prüft Pegel und Länge und überspringt vorhandene (`--redo` überschreibt). Das Klon-Modell selbst folgt, siehe [docs/research/voice-clone.md](docs/research/voice-clone.md).

## Fehlerbehebung

| Problem | Lösung |
|---|---|
| `python -m kushim.cli doctor` zeigt `[FEHLT]` | Der Hinweis dahinter nennt den Befehl. Meist hilft `install.ps1` erneut. |
| „Noch kein Vault“ | `python -m kushim.cli memory init` |
| „Kein Stimmprofil“ beim Sprechen | `python -m kushim.cli voice enroll` |
| „Notaus ist aktiv“ | `python -m kushim.cli resume` |
| kushim erkennt meine Stimme nicht / zu oft nicht | `voice test` zeigt die Werte. Näher ans Mikrofon, ruhiger Raum, dasselbe Mikrofon wie beim Einschreiben. Sehr kurze Äußerungen („ja“) sind unzuverlässig: lieber ganze Sätze. Notfalls `python -m kushim.cli voice enroll --record` und neu aufnehmen. |
| `cublas64_12.dll not found` | `install.ps1` erneut (installiert die NVIDIA-Bibliotheken) |
| Nichts passiert beim Wake Word | Mikrofon prüfen (`--mic`), deutlicher sprechen, in `wakewords.toml` `threshold` senken (z. B. 0.10) oder mehr Wörter aktivieren |
| Wake Word löst zu oft aus | `threshold` erhöhen (z. B. 0.25) oder kurze Wörter wie „kush“ ausschalten (`enabled = false`) |
| Das erste Antworten dauert lange | Beim ersten Mal lädt Whisper sein Modell auf die Grafikkarte, danach geht es schneller |
| PowerShell blockt `install.ps1` | Genau mit `-ExecutionPolicy Bypass` aufrufen (siehe oben) |

## Deinstallation

1. Verknüpfungen vom Desktop löschen.
2. Projektordner löschen (enthält `.venv`, `models`, `tools`). Der Vault liegt separat (`~/kushim-vault`) und bleibt erhalten, bis du ihn selbst löschst.
3. Schlüssel aus dem Credential-Manager entfernen („kushim-vault“) erst, wenn du den Vault wirklich nicht mehr brauchst.

## Grundprinzipien

1. **Schäden jeder Art sind verboten:** seelisch, finanziell, körperlich, an Daten und Privatsphäre, an Dritten und langfristig. Im Zweifel nichts tun und fragen. Die Regeln stehen in `src/kushim/safety/rules.py` und können weder von der KI noch vom Lernen geändert werden.
2. **Nichts nach außen außer Claude Code:** kushim selbst spricht nur 127.0.0.1. Claude Code ist die einzige KI und die einzige Verbindung nach außen (Befehlstext an Anthropic); Audio verlässt nie den PC.
3. **Default-Deny und Fail-Closed:** Unbekannte Aktionen, fehlender Prüfer oder Zweifel führen zu Ablehnung. Geldlimit standardmäßig 0, Zahlungen sind gesperrt, ein Notaus stoppt alles.
4. **Nur du gibst Befehle:** Sprecherverifikation und zweiter Faktor bei riskanten Aktionen. Inhalte aus Web, Mail und Dateien sind nur Daten, nie Anweisungen.
5. **Transparent:** Jede Entscheidung und jeder ausgehende Zugriff steht im verschlüsselten Audit-Log.

## Architektur

| Baustein | Stand |
|---|---|
| Verschlüsselter Vault (SQLCipher), Migration und Backups | fertig |
| Notaus, Audit, Grundregeln (`safety/rules.py`) | fertig |
| Statische Prüfung gegen Netzwerkcode außerhalb der Allowlist | fertig |
| Stimme: Wake Word, Sprecherverifikation, Whisper, Piper, Satz-Streaming, Barge-in | fertig, im Live-Test |
| Start-Verknüpfungen, `doctor`, Installationsskript | fertig |
| Eigene Stimme (Klon) | gebaut, Hörtest offen |
| UI (Tauri, Avatar, Transkript, Notaus, Ordner) | fertig, wird auf Claude Code umgestellt (Phase E) |
| Brücke zu Claude Code (Channel), Freigaben per Stimme | geplant (Phase B, C) |

## Entwicklung

```powershell
.\.venv\Scripts\python -m pytest -q
```

Gedächtnis-Befehle: `kushim memory init|info|backup|migrate`. Tests brauchen keine Modelle (Hardware-Tests werden übersprungen, wenn Modelle fehlen).

### Skills, Agents und Routine (Claude Code)

- Skills in `.claude/skills/`: `kushim-safety-review`, `kushim-ui-design`, `kushim-next-phase`, `kushim-routine`
- Agents in `.claude/agents/`: `safety-auditor`, `voice-pipeline-dev`, `ui-builder`
- Autonome Entwicklungsroutine: `/loop /kushim-routine` (siehe [docs/LOOPS.md](docs/LOOPS.md)). Sie arbeitet auf eigenen Branches, fragt bei Unklarheiten nach und pflegt die Roadmap. Gepusht wird nur von dir.

## Status

Umbau auf Claude Code. Die Sprachkette (Wake Word, nur deine Stimme, Whisper, Piper) steht; die Brücke zu Claude Code und Freigaben per Stimme folgen.
