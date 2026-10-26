# Recherche: Jarvis-ähnliche Projekte (Stand 2026-10-26)

Frage des Nutzers: Gibt es fertige Systeme, die man lokal betreiben kann, statt neu zu bauen? Ziel: Sprachsteuerung für
Claude Code, Sprachdaten bleiben auf dem PC, Freigaben per Stimme, Oberfläche mit Modell und Verbrauch.

Geprüft wurde der Quellcode (flacher Klon, nur gelesen, nichts ausgeführt).

## 1. Sprachsteuerung speziell für Claude Code

| Projekt | Lizenz | System | Wie der Text zu Claude kommt | Antwort hören | Sprecherprüfung | Freigabe per Stimme | Bewertung |
|---|---|---|---|---|---|---|---|
| [Parsec1498/claude-code-voice-mod](https://github.com/Parsec1498/claude-code-voice-mod) | MIT | Windows | Claude-Code-Plugin („Mod“) mit Panel, schickt den Text als Prompt in den Chat | optional Piper, nur ein Block „🔊 Speak:“ am Ende der Antwort | nein | nein: im sicheren Modus nur per Knopf/Tippen; Sperrliste für gefährliche Aktionen | Am weitesten. Aber nur Ukrainisch/Englisch, Wake Word über Dauer-Whisper (jede Rede wird lokal transkribiert), keine Sprecherprüfung |
| [angel007111/voxcode](https://github.com/angel007111/voxcode) | MIT | Windows | **Channel** (MCP-Server, `claude/channel`) über HTTP 127.0.0.1 | Werkzeug `say` | ja (SpeechBrain ECAPA, lernt nach 3 Befehlen) | nein | Gute Architektur, aber Sprachausgabe über **Google Cloud TTS / edge-tts = Cloud**, Russisch |
| [jjacke13/claude-talk](https://github.com/jjacke13/claude-talk) | keine Lizenz-Datei | Linux (Windows ungetestet) | Channel-Plugin | Piper | nein | nein | Sauber, aber ohne Lizenz nicht wiederverwendbar |
| [EmmN/claude-voice](https://github.com/EmmN/claude-voice) | keine Lizenz-Datei | WSL | Hooks + tmux, mehrere Sitzungen per Name | Piper, Zusammenfassung über lokales Ollama | nein | nein | Interessante Ideen (Sitzungen per Name), nicht wiederverwendbar |
| [Lasimeri/voice-079](https://github.com/Lasimeri/voice-079) | MIT | Linux/KDE | tippt per `uinput` ins Terminal | Stop-Hook, erster Absatz | ja (sherpa-onnx) | nein | Echo-Unterdrückung (PipeWire) gute Idee, sonst Linux-only |
| [Ashton-Sidhu/claude-whisper](https://github.com/Ashton-Sidhu/claude-whisper) | BSD-3 | macOS | Agent SDK (braucht API-Schlüssel) | nein | nein | nein | passt nicht (Mac, API-Schlüssel) |
| [sefermavi4243-droid/dikte](https://github.com/sefermavi4243-droid/dikte) | GPL-3 | Linux/Mac/Win | Diktat + Einfügen | ja | nein | nein | sehr groß (45 000 Zeilen), GPL |

## 2. Allgemeine „Jarvis“-Assistenten (lokales LLM statt Claude Code)

[FarhanFarooqui122/J.A.R.V.I.S.](https://github.com/FarhanFarooqui122/J.A.R.V.I.S.), [PanPenek/JarvisAi](https://github.com/PanPenek/JarvisAi),
[ndunl075/Jarvis](https://github.com/ndunl075/Jarvis), [vigneshwaran484/Jarvis](https://github.com/vigneshwaran484/Jarvis),
[chuyong-1/Jarvis](https://github.com/chuyong-1/Jarvis), [Shaan-alpha/jarvis-py](https://github.com/Shaan-alpha/jarvis-py):
alle derselbe Aufbau wie das alte kushim (openWakeWord → faster-whisper → Ollama/llama.cpp → Piper/Kokoro, teils HUD-Oberfläche).
Keines steuert Claude Code; das alte kushim ist bei Sicherheit (Sprecherprüfung, Notaus, Freigaben, Tests) bereits weiter.
[Home Assistant Assist](https://www.home-assistant.io/integrations/wyoming/) (Wyoming, openWakeWord, Whisper, Piper) ist die
ausgereifteste lokale Sprachkette, aber für Smart Home gebaut.

## 3. Der wichtigste Fund: Claude Code Channels mit Freigabe-Weiterleitung

Offizielle Schnittstelle von Claude Code ([Channels reference](https://code.claude.com/docs/en/channels-reference)), Research Preview:

- Ein **Channel** ist ein lokaler MCP-Server, den Claude Code selbst startet (stdio). Er schiebt Nachrichten
  (`notifications/claude/channel`) in die **laufende, interaktive Sitzung**, und Claude kann über ein eigenes Werkzeug
  (z. B. `sprich`) antworten.
- **Freigaben weiterleiten** (`claude/channel/permission`): Will Claude ein Werkzeug nutzen, das eine Freigabe braucht
  (Bash, Write, Edit …), bekommt der Channel `permission_request` mit `request_id`, `tool_name`, `description`, `input_preview`.
  Der Channel antwortet mit `allow`/`deny`. Das Terminal-Fenster bleibt parallel offen; die erste Antwort gilt.
  **Genau das ist „Berechtigung per Stimme geben“**, ohne Tricks und ohne die Sitzung neu zu starten.
- Ab Claude Code v2.1.234 (installiert: 2.1.310) werden Freigaben nur an registrierte Channels gesendet und Schlüssel maskiert.
- Einschränkungen: Research Preview; eigene Channels nur mit `claude --dangerously-load-development-channels server:<name>`
  (Bestätigungsdialog beim Start); nur interaktive Sitzung, nicht mit `-p`; bei Team/Enterprise muss der Admin Channels erlauben.
- Die Oberfläche ist dann Claude Code selbst: Verlauf, `/model`, `/usage`, Freigabe-Dialog, Statuszeile.

## 4. Empfehlung

Kein fertiges Projekt erfüllt alle Anforderungen (Deutsch, Sprecherprüfung, Sprachausgabe lokal, Freigabe per Stimme).
Am wenigsten neuer Code entsteht so:

**kushim-Sprachteil behalten** (Wake Word ohne Dauer-Transkription, Sprecherprüfung, Whisper, deutsche Piper-Stimme, Notaus,
alles getestet) **+ ein kleiner Channel-Server** als Brücke zu Claude Code. Ideen und, wo die Lizenz es erlaubt (MIT), Code
übernehmen:

- voice-mod: Sprech-Block am Ende der Antwort, Sperrliste gefährlicher Aktionen, Abbruch-Wort, Mikrofon während der eigenen
  Ausgabe stumm
- voxcode: Channel über HTTP 127.0.0.1, Werkzeug `say`, Wächter hält die Sitzung am Leben (`--resume`)
- voice-079: Echo-Unterdrückung als späterer Schritt

Die eigene Tauri-Oberfläche wird damit optional: Claude Code zeigt Verlauf, Modell und Verbrauch schon selbst. kushim braucht
anfangs nur eine Statuszeile oder ein kleines Fenster mit seinem Zustand (hört / denkt / spricht / gesperrt).

Zum schnellen Ausprobieren ohne eigenen Code: voice-mod installieren (Englisch-Modus), um das Gefühl für Sprachsteuerung von
Claude Code zu bekommen. Deutsch, Sprecherprüfung und Freigabe per Stimme fehlen dort.
