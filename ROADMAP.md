# kushim Roadmap v2: lokaler Jarvis vor Claude Code

Ziel (Nutzerwunsch 2026-10-26): Per Sprachbefehl Claude Code nutzen. kushim hört lokal zu (Wake Word, Sprecherprüfung, Whisper),
gibt den Befehl an eine fortlaufende Claude-Code-Sitzung (`claude -p`, Anmeldung des Nutzers, kein API-Schlüssel), liest die
Antwort lokal vor (Piper) und zeigt alles in einer eigenen Oberfläche: Verlauf, Modellwahl, Verbrauch, Freigaben, Notaus.

Oberste Regel: Schäden jeder Art sind verboten. **Sprachdaten verlassen nie den PC.** An Anthropic geht nur der erkannte Befehlstext
(das ist der Zweck). Die alte Roadmap liegt in [docs/ROADMAP-v1.md](docs/ROADMAP-v1.md).

Arbeitsweise: immer nur einen Schritt, danach Tests (`pytest`), Sicherheitsprüfung (`kushim-safety-review`), Commit. Schritte mit
**(Nutzer)** kann nur der Nutzer erledigen (Mikrofon, echte Stimme, Entscheidung).

## Phase A: Aufräumen (nur löschen, nichts Neues)
Bleibt: Wake Word (`voice/trigger.py`, `wakeconfig.py`, `wakebuild.py`), Sprecherprüfung (`speaker.py`, `verify.py`, `embedder.py`,
`profile.py`, `enrollment.py`, `voiceprint.py`, `recorder.py`, `levels.py`), Audio (`audio.py`, `bargein.py`, `dialog.py`),
Whisper (`stt.py`), TTS (`tts.py`, `clone.py`), Gesprächsschleife (`talk.py`, `pipeline.py`), Notaus (`safety/killswitch.py`),
Abbrechen (`tasks.py`), Vault (`memory/`, für das Stimmprofil), `config.py`, `cli.py`, `doctor.py`, `tests/test_no_egress.py`.

- [ ] A1 Sprachbefehle für alte Werkzeuge entfernen: `voice/tool_commands.py`, `timer_commands.py`, `note_commands.py`,
      `commands.py`, `wake_commands.py` samt Tests; `talk.py`/`cli.py` ohne sie lauffähig. Tests grün
- [ ] A2 Web und Recherche entfernen: `web/`, `research.py`, `net/web.py` samt Tests und ALLOWLIST-Einträgen in `test_no_egress.py`
- [ ] A3 Timer und Notizen entfernen: `timers.py` samt Tests und CLI-Befehlen
- [ ] A4 Alte Claude-Steuerung entfernen: `claude_cli/` bis auf `base.py` (CLI finden, Anmeldung prüfen, saubere Umgebung) und
      `folders.py` (sichere Arbeitsordner), samt `api/claude_api.py` und Tests
- [ ] A5 Werkzeug-Verwaltung und Gates entfernen: `tools/`, `privacy.py`, `safety/gate.py`, `safety/approvals.py`, `api/tools_api.py`,
      `api/tasks_api.py`; `safety/rules.py` bleibt (Grundsätze)
- [ ] A6 Lokales Sprachmodell entfernen: `llm/`, `launcher.py` (Ollama), `api/llm_api.py`, `[llm]` in der Konfiguration, Ollama aus
      `install.ps1`, `fetch_models.py`, `doctor.py`; `gpu.py` nur noch für Whisper
- [ ] A7 Rest prüfen: `learning/`, `setup/`, `api/setup_api.py` entfernen oder behalten (Setup-Status bleibt nützlich für die UI);
      README „Was es heute kann“ kürzen; `kushim help` zeigt nur noch vorhandene Befehle

## Phase B: Sprache → Claude Code (im Terminal nutzbar)
- [ ] B1 `claude_code/runner.py`: ein Zug = `claude -p <text> --output-format stream-json --verbose [--resume <id>] [--model <m>]`
      im freigegebenen Arbeitsordner, saubere Umgebung (`clean_env`), `--setting-sources user`; liest Ereignisse (Text, Werkzeug,
      Ergebnis, Sitzungs-ID, Kosten, Tokens, abgelehnte Berechtigungen). Tests mit gefälschtem Prozess
- [ ] B2 Abbrechen und Notaus beenden den Claude-Prozess samt Kindprozessen (`tasks.py`, `killswitch.py`); Zeitgrenze je Zug
- [ ] B3 Sitzung fortsetzen: Sitzungs-ID in `run/claude-voice.json`; „neue Sitzung“ per Sprache und CLI
- [ ] B4 Vorlesefreundlich: `--append-system-prompt` (Deutsch, kurz, kein Markdown/Code in der gesprochenen Antwort); Text vor der
      TTS bereinigen (Codeblöcke, Links, Tabellen raus, Hinweis „Details in der Oberfläche“)
- [ ] B5 In die Pipeline hängen: `Pipeline.chat` wird der Claude-Code-Runner; kurze Quittung „Ich frag Claude.“ bei langen Zügen
- [ ] B6 `kushim talk` startet ohne Ollama; `kushim doctor` prüft Claude CLI und Anmeldung (Abo)
- [ ] B7 Live-Test **(Nutzer)**: Wake Word → Frage → Claude antwortet → wird vorgelesen; Abbrechen und Notaus während eines Zugs

## Phase C: Berechtigungen per Stimme
- [ ] C1 Abgelehnte Berechtigungen aus dem Ergebnis lesen (`permission_denials`) und in kurze, sprechbare Beschreibungen übersetzen
      („Claude möchte den Befehl npm test ausführen“, „Claude möchte die Datei app.py ändern“)
- [ ] C2 Erlaubnis-Regel genau zuschneiden: Bash nur der genaue Befehl, Datei nur der genaue Pfad im Arbeitsordner, Web nur die Domain;
      nie `bypassPermissions`, nie Platzhalter für ganze Werkzeuge; Liste gefährlicher Befehle, die nie per Stimme freigebbar sind
- [ ] C3 Rückfrage per Stimme: „Erlauben?“ → „ja“ nur mit stark verifizierter Stimme, „nein“/Stille = abgelehnt, Ablaufzeit;
      danach Sitzung mit `--allowedTools <Regel>` fortsetzen („Erlaubnis erteilt, mach weiter“)
- [ ] C4 Gültigkeit: „einmal“ (nur dieser Zug) oder „für diese Sitzung“; nie dauerhaft in Claude-Einstellungen schreiben
- [ ] C5 Alle Freigaben lokal protokollieren (was, wann, Sprecher-Score), ohne Audio
- [ ] C6 Live-Test **(Nutzer)**: Claude will einen Befehl ausführen → per Stimme erlauben → Claude macht weiter

## Phase D: Modell und Verbrauch (Backend)
- [ ] D1 Modellwahl: `[claude] model` in der Konfiguration, `kushim claude model <opus|sonnet|haiku>`, per Stimme
      („nimm Sonnet“), gilt ab dem nächsten Zug
- [ ] D2 Verbrauch je Zug und Sitzung aus `result` (Kosten, Ein-/Ausgabe-Tokens, Cache, Dauer) lokal mitschreiben
- [ ] D3 Rate-Limit-Stand aus den Ereignissen der CLI lesen (falls geliefert) und anzeigen; sonst klar „nicht verfügbar“
- [ ] D4 `kushim claude usage`: Übersicht heute/Sitzung im Terminal

## Phase E: Schnittstelle für die Oberfläche
- [ ] E1 **Entscheidung (Nutzer):** lokaler WebSocket nur auf 127.0.0.1 mit Token freigeben? (ohne Ja keine UI)
- [ ] E2 Transport in `net/` (nur Loopback, Token, Default-Deny-Dispatch aus `api/protocol.py`); `test_no_egress.py` angepasst
- [ ] E3 Ereignisse an die UI: Zustand (hört/denkt/spricht), Transkript, Claude-Text live, Werkzeug-Aufrufe, Freigabe-Anfragen,
      Verbrauch, Modell, Notaus
- [ ] E4 Befehle von der UI: Text senden, Abbrechen, Freigabe erteilen/ablehnen, Modell wählen, neue Sitzung, Notaus/Fortsetzen

## Phase F: Oberfläche (Tauri, Design aus `.claude/skills/kushim-ui-design/`)
- [ ] F1 Tauri-Grundgerüst (Toolchain nur aus offiziellen Quellen), Verbindung zum Backend, Statusanzeige
- [ ] F2 Avatar mit Zuständen (hört/denkt/spricht/gesperrt)
- [ ] F3 Gesprächsverlauf: eigene Befehle, Claude-Antworten mit Markdown/Code, Werkzeug-Aufrufe aufklappbar
- [ ] F4 Freigabe-Leiste: Anfrage anzeigen, Erlauben/Ablehnen per Klick, parallel zur Stimme
- [ ] F5 Modellwahl (Opus/Sonnet/Haiku) in der Kopfzeile
- [ ] F6 Verbrauch: Kosten/Tokens je Zug, Sitzung, heute; Rate-Limit-Stand
- [ ] F7 Notaus-Knopf, Arbeitsordner-Auswahl, Texteingabe als Ersatz zur Stimme
- [ ] F8 Setup-Assistent: Mikrofon, Stimme einschreiben, Wake Words, Claude-Anmeldung prüfen
- [ ] F9 Live-Test **(Nutzer)** der ganzen App

## Später / offen
- [ ] Sprecher-Prüfung mit einer zweiten echten Person prüfen **(Nutzer)**
- [ ] Eigene Stimme (Klon) Hörtest **(Nutzer)**: `kushim voice clone-test`
- [ ] Echo-Unterdrückung für Lautsprecher-Betrieb
- [ ] Optional: Microsoft Copilot Cowork / Claude Cowork als zweites Ziel (keine API, nur über Fenster-Einfügen, z. B. mit Handy)
