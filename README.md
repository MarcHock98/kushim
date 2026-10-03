# kushima

Ein persönlicher KI-Assistent im Stil von Jarvis: Du sprichst mit ihm, er erledigt Dinge für dich, lernt mit der Zeit, wie du denkst, und zeigt Ergebnisse und seinen Zustand in einer eigenen Oberfläche.

**Die Daten gehören dir.** kushima ist lokal-first gebaut: Standardmäßig verlässt nichts deinen PC. Spracherkennung, Sprachmodell und Stimme laufen komplett auf deinem Rechner.

Inhalt: [Was es heute kann](#was-es-heute-kann) · [Voraussetzungen](#voraussetzungen) · [Installation](#installation) · [Erster Start](#erster-start) · [Täglicher Gebrauch](#täglicher-gebrauch) · [Konfiguration](#konfiguration) · [Netzwerk und Datenschutz](#netzwerk-und-datenschutz) · [Eigene Stimme (Klon)](#eigene-stimme-klon) · [Fehlerbehebung](#fehlerbehebung) · [Umbenennung](#umbenennung-von-kushim-zu-kushima) · [Deinstallation](#deinstallation) · [Entwicklung](#entwicklung)

## Was es heute kann

- **Sprechen per Wake Word:** Du sagst das Wake Word („hey jarvis“, einstellbar, mehrere möglich), kushima antwortet „Ja?“ und hört deinen Befehl. Vor dem Wake Word läuft nur ein kleines lokales Erkennungsmodell: keine Spracherkennung, kein LLM, keine Speicherung.
- **Nur auf deine Stimme:** Sprecherverifikation. Fremde Stimmen bekommen keine Antwort. Ohne eingeschriebenes Stimmprofil startet das Sprechen gar nicht.
- **Notaus:** per Desktop-Verknüpfung oder per Sprachbefehl („Notaus“, „stopp alles“). Wirkt für jede Stimme.
- **Lokal:** Whisper (Spracherkennung, GPU), Qwen 2.5 7B über Ollama (nur 127.0.0.1), Piper (deutsche Stimme).
- **Verschlüsseltes Gedächtnis (Vault)** mit Backups, Sicherheitsschicht (ActionGate, Freigaben, Audit).

Noch nicht fertig: Oberfläche mit Avatar, Tools (Web, Mail, Kalender, PC, Smart Home), Lernen, eigene Stimme und eigenes Wake Word „Hey Kushima“. Stand und Pläne: [ROADMAP.md](ROADMAP.md).

## Voraussetzungen

| | |
|---|---|
| System | Windows 10 oder 11 (64 Bit) |
| Grafikkarte | NVIDIA mit mindestens 8 GB VRAM (getestet: RTX 3070), aktueller NVIDIA-Treiber |
| Speicher | mindestens 15 GB frei (Modelle ca. 6 GB, Ollama ca. 2 GB, Python-Umgebung ca. 3 GB) |
| RAM | 16 GB, besser 32 GB |
| Python | 3.11 oder 3.12 von [python.org](https://www.python.org/downloads/) (Haken bei „Add Python to PATH“) |
| Hardware | Mikrofon und Lautsprecher/Kopfhörer |
| Internet | nur für die Installation (ca. 10 GB Download), danach nicht mehr nötig |

Git ist nur nötig, wenn du das Projekt von GitHub holst.

## Installation

### Variante A: ein Befehl (empfohlen)

1. Projekt holen:
   ```powershell
   git clone https://github.com/MarcHock98/kushima.git
   cd kushima
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
5. Ollama laden (Prüfsumme geprüft, Standalone ohne Auto-Updater) und das LLM `qwen2.5:7b` holen
6. Logo-Icon erzeugen
7. Desktop-Verknüpfungen anlegen: **kushima**, **kushima sprechen**, **kushima NOTAUS**
8. Am Ende fragt es, ob es den Vault anlegen und deine Stimme einschreiben soll (nur mit deinem Ja)

Schalter:

| Schalter | Wirkung |
|---|---|
| `-Check` | nur prüfen, was fehlt; ändert und lädt nichts |
| `-NoPrompt` | keine Rückfragen (Vault und Stimme werden dann nicht angelegt) |
| `-SkipLlm` | LLM (4,7 GB) nicht laden |
| `-SkipShortcuts` | keine Desktop-Verknüpfungen |

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

# 3. Ollama (Standalone) und LLM
New-Item -ItemType Directory -Force tools | Out-Null
curl.exe -L -o tools\ollama.zip https://github.com/ollama/ollama/releases/download/v0.35.1/ollama-windows-amd64.zip
#   SHA-256 muss dc50b9ca7f9023c86525012632cd1615b093d0407987444a7f62ecab617e8e93 sein:
Get-FileHash tools\ollama.zip -Algorithm SHA256
Expand-Archive tools\ollama.zip tools\ollama; Remove-Item tools\ollama.zip
$env:OLLAMA_HOST = "127.0.0.1:11434"; $env:OLLAMA_MODELS = "$PWD\models\ollama"
Start-Process tools\ollama\ollama.exe -ArgumentList serve -WindowStyle Hidden
tools\ollama\ollama.exe pull qwen2.5:7b
Stop-Process -Name ollama -Force      # nur den eben gestarteten Server beenden

# 4. Logo-Icon (für die Verknüpfungen)
.\.venv\Scripts\python scripts\make_icon.py

# 5. Kontrolle
.\.venv\Scripts\python -m kushima.cli doctor
```

Die Desktop-Verknüpfungen legt nur `install.ps1` an; von Hand erstellst du Verknüpfungen auf `.venv\Scripts\python.exe` mit den Argumenten `-m kushima.cli start`, `-m kushima.cli talk` und `-m kushima.cli kill`, Arbeitsordner = Projektordner.

## Erster Start

Diese Schritte machst nur du (sie betreffen deinen Schlüssel und deine Stimme). Immer im Projektordner:

1. **Vault anlegen.** Legt den verschlüsselten Speicher an und erzeugt einen Schlüssel im Windows-Credential-Manager:
   ```powershell
   .\.venv\Scripts\python -m kushima.cli memory init
   ```
2. **Schlüssel sichern.** Ohne ihn sind die Daten bei einer Neuinstallation von Windows verloren. Das Ergebnis in deinen Passwortmanager kopieren (nicht in eine Datei im Projekt, nicht in einen Chat):
   ```powershell
   .\.venv\Scripts\python -m kushima.cli key export
   ```
3. **Stimme einschreiben.** Du liest 5 Sätze vor (Text: `docs/voice-recording-text.md`, Teil A). Gespeichert wird nur ein Zahlenvektor im Vault, keine Aufnahme:
   ```powershell
   .\.venv\Scripts\python -m kushima.cli voice enroll
   ```
   Optional ein bestimmtes Mikrofon: `--mic "Arctis 5 Chat"`.
4. **Prüfen, ob dich kushima erkennt** (und andere nicht). Es zeigt Ähnlichkeit und Schwelle pro Satz:
   ```powershell
   .\.venv\Scripts\python -m kushima.cli voice test
   ```
5. **Gesamtkontrolle:**
   ```powershell
   .\.venv\Scripts\python -m kushima.cli doctor
   ```
   Alles `[ok]` heißt: bereit.

## Täglicher Gebrauch

| Aktion | So |
|---|---|
| Starten und sprechen | Desktop-Verknüpfung **kushima sprechen** (oder `python -m kushima.cli talk`). Nach dem Start steht im Fenster, welche Wake Words gelten. |
| Sprechen | Wake Word sagen (Standard „hey jarvis“) → kushima antwortet „Ja?“ → Befehl sprechen. Bleibt es 5 Sekunden still, hört kushima wieder nur aufs Wake Word. |
| Beenden | `Strg+C` im Fenster |
| Nur die lokalen Dienste starten | Verknüpfung **kushima** (startet Ollama nur auf 127.0.0.1; `Strg+C` beendet). Das Sprechen startet sie selbst, wenn nötig. |
| **Notaus** | Verknüpfung **kushima NOTAUS** anklicken oder „Notaus“ / „stopp alles“ sagen. Danach startet kushima erst wieder, wenn du bewusst aufhebst: `python -m kushima.cli resume`. |
| Stimmprofil prüfen / löschen | `python -m kushima.cli voice status` / `voice reset` |
| Backup | `python -m kushima.cli memory backup` |

Geräte wählen (Namensteil genügt): `python -m kushima.cli talk --mic "Arctis 5 Chat" --out "Arctis 5 Game"`. Ohne Angabe gelten die Windows-Standardgeräte.

## Konfiguration

Kopiere `config.example.toml` nach `config.toml` (oder `%APPDATA%\kushima\config.toml`). `config.toml` ist nicht im Git.

```toml
[memory]
location = "local:~/kushima-vault"   # einziger Ort, der den Speicherort kennt

[voice]
wake_words = ["hey_jarvis"]          # mehrere möglich, z. B. ["hey_jarvis", "alexa"]

[privacy]
claude_enabled = false               # Modus A (alles lokal); Claude nur als Opt-in
```

Wake Words: vortrainiert sind `alexa`, `hey_mycroft`, `hey_jarvis`, `hey_rhasspy`, `timer`, `weather`. Eigene Modelle (`.onnx`) legst du nach `models/wakewords/` und trägst nur den Dateinamen ein. Einmalig überschreiben geht mit `talk --wake-words hey_jarvis,alexa`. Ein eigenes „Hey Kushima“ steht auf der [Roadmap](ROADMAP.md).

Vault verschieben (z. B. auf ein anderes Laufwerk): `python -m kushima.cli memory migrate --to "local:D:/kushima-vault"` (verifiziert, der alte Vault bleibt als Rollback).

## Netzwerk und Datenschutz

- **Installation:** Netzwerk nur zu `pypi.org` (Pakete), `github.com` (Ollama, Sprecher-Modell, Wake-Word-Modelle), `huggingface.co` (Whisper, Stimme) und `registry.ollama.ai` (LLM). Alles in festen Versionen, Modelle und Ollama per Größe und SHA-256 geprüft.
- **Betrieb:** kushima arbeitet offline. Der einzige Netzwerkcode im Programm ist `src/kushima/net/loopback.py` und spricht ausschließlich 127.0.0.1 (lokales Ollama). Ein Test (`tests/test_no_egress.py`) verhindert anderen Netzwerkcode.
- **Mikrofon:** Audio bleibt im Arbeitsspeicher und wird nicht gespeichert. Vor dem Wake Word sieht nur das kleine Wake-Word-Modell das Signal.
- **Stimmprofil:** nur ein Zahlenvektor, im verschlüsselten Vault.
- **Schlüssel:** im Windows-Credential-Manager, nie im Vault, nie im Projekt.

## Eigene Stimme (Klon)

Für eine Stimme, die wie du klingt, nimmst du Material auf (nur lokal, Ordner `voice-data/` ist nicht im Git). Text dazu: `docs/voice-recording-text.md`, Teil B.

```powershell
.\.venv\Scripts\python -m kushima.cli voice record --mic "Arctis 5 Chat"
```

Es nimmt 10 Absätze mit 24 kHz auf, prüft Pegel und Länge und überspringt vorhandene (`--redo` überschreibt). Das Klon-Modell selbst folgt, siehe [docs/research/voice-clone.md](docs/research/voice-clone.md).

## Fehlerbehebung

| Problem | Lösung |
|---|---|
| `python -m kushima.cli doctor` zeigt `[FEHLT]` | Der Hinweis dahinter nennt den Befehl. Meist hilft `install.ps1` erneut. |
| „Noch kein Vault“ | `python -m kushima.cli memory init` |
| „Kein Stimmprofil“ beim Sprechen | `python -m kushima.cli voice enroll` |
| „Notaus ist aktiv“ | `python -m kushima.cli resume` |
| kushima erkennt meine Stimme nicht / zu oft nicht | `voice test` zeigt die Werte. Näher ans Mikrofon, ruhiger Raum, dasselbe Mikrofon wie beim Einschreiben. Notfalls `voice reset` und neu einschreiben. |
| `cublas64_12.dll not found` | `install.ps1` erneut (installiert die NVIDIA-Bibliotheken) |
| Nichts passiert beim Wake Word | Mikrofon prüfen (`--mic`), lauter/deutlicher sprechen, anderes Wake Word testen |
| Das erste Antworten dauert lange | Beim ersten Mal lädt das Modell (ca. 30 Sekunden), danach unter einer Sekunde |
| PowerShell blockt `install.ps1` | Genau mit `-ExecutionPolicy Bypass` aufrufen (siehe oben) |
| Ollama-Port belegt | Läuft schon ein Ollama, nutzt kushima es mit; sonst anderen Prozess auf Port 11434 beenden |

## Deinstallation

1. Verknüpfungen vom Desktop löschen.
2. Projektordner löschen (enthält `.venv`, `models`, `tools`). Der Vault liegt separat (`~/kushima-vault`) und bleibt erhalten, bis du ihn selbst löschst.
3. Schlüssel aus dem Credential-Manager entfernen („kushima-vault“) erst, wenn du den Vault wirklich nicht mehr brauchst.

## Umbenennung von kushim zu kushima

Das Projekt hieß früher **kushim**. Wenn du eine ältere Installation hast:

- **Vault und Schlüssel bleiben erhalten.** Ein vorhandener Vault unter `~/kushim-vault` wird weiter benutzt (nichts wird verschoben). Der Schlüssel unter dem alten Namen im Credential-Manager wird gefunden und zusätzlich unter dem neuen Namen abgelegt, der alte Eintrag bleibt als Rückfall.
- Die alten Umgebungsvariablen `KUSHIM_VAULT_KEY` und `KUSHIM_CONFIG` funktionieren weiter, neu sind `KUSHIMA_VAULT_KEY` und `KUSHIMA_CONFIG`. Eine Konfiguration unter `%APPDATA%\kushim` wird weiter gelesen.
- Der Befehl heißt jetzt `kushima` (`python -m kushima.cli ...`). `install.ps1` ersetzt die alten Desktop-Verknüpfungen durch neue.
- Die Skills unter `.claude/skills/` heißen vorerst weiter `kushim-*`.
- Ein GitHub-Repo, das noch `kushim` heißt, benennst du auf GitHub um (Settings → Repository name); danach lokal `git remote set-url origin https://github.com/<dein-name>/kushima.git`. GitHub leitet die alte Adresse automatisch weiter.

## Grundprinzipien

1. **Schäden jeder Art sind verboten:** seelisch, finanziell, körperlich, an Daten und Privatsphäre, an Dritten und langfristig. Im Zweifel nichts tun und fragen. Die Regeln stehen in `src/kushima/safety/rules.py` und können weder von der KI noch vom Lernen geändert werden.
2. **Modus A (Standard):** Alles läuft lokal, nichts geht ins Netz. **Modus C (Opt-in):** Claude nur auf ausdrücklichen Befehl, mit Vorschau des exakten Textes und Bestätigung.
3. **Default-Deny und Fail-Closed:** Unbekannte Aktionen, fehlender Prüfer oder Zweifel führen zu Ablehnung. Geldlimit standardmäßig 0, Zahlungen sind gesperrt, ein Notaus stoppt alles.
4. **Nur du gibst Befehle:** Sprecherverifikation und zweiter Faktor bei riskanten Aktionen. Inhalte aus Web, Mail und Dateien sind nur Daten, nie Anweisungen.
5. **Transparent:** Jede Entscheidung und jeder ausgehende Zugriff steht im verschlüsselten Audit-Log.

## Architektur

| Baustein | Stand |
|---|---|
| Verschlüsselter Vault (SQLCipher), Migration und Backups | fertig |
| `EgressGate`, `ActionGate`, Freigabe-Warteschlange, Notaus, Audit | fertig |
| Statische Prüfung gegen Netzwerkcode außerhalb der Allowlist | fertig |
| Stimme: Wake Word, Sprecherverifikation, Whisper, Ollama, Piper, Satz-Streaming, Barge-in | fertig, im Live-Test |
| Start-Verknüpfungen, `doctor`, Installationsskript | fertig |
| Eigene Stimme (Klon), „Hey Kushima“ | in Arbeit |
| UI (Tauri, Avatar, Dashboard) | geplant |
| Tools (Web, Mail/Kalender, PC, Smart Home) | geplant |
| Lernen (Stil-Bandit fertig, Reflexion, Feedback) | teilweise |
| NAS-Gedächtnis-Dienst | geplant |

## Entwicklung

```powershell
.\.venv\Scripts\python -m pytest -q
```

Gedächtnis-Befehle: `kushima memory init|info|backup|migrate`. Tests brauchen keine Modelle (Hardware-Tests werden übersprungen, wenn Modelle fehlen).

### Skills, Agents und Routine (Claude Code)

- Skills in `.claude/skills/`: `kushim-add-tool`, `kushim-safety-review`, `kushim-next-phase`, `kushim-routine`
- Agents in `.claude/agents/`: `safety-auditor`, `voice-pipeline-dev`, `ui-builder`
- Autonome Entwicklungsroutine: `/loop /kushim-routine` (siehe [docs/LOOPS.md](docs/LOOPS.md)). Sie arbeitet auf eigenen Branches, fragt bei Unklarheiten nach und pflegt die Roadmap. Gepusht wird nur von dir.

## Status

Frühe Entwicklung. Die Sprachkette (Wake Word, nur deine Stimme, lokale Antworten per Stimme) steht und ist im Live-Test; Oberfläche, Tools und eigene Stimme folgen.
