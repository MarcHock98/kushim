# kushim Roadmap v2: lokaler Jarvis vor Claude Code

Ziel (Nutzerwunsch 2026-10-26): Per Sprachbefehl Claude Code nutzen. kushim hört lokal zu (Wake Word, Sprecherprüfung, Whisper),
gibt den Befehl über einen lokalen Channel in die laufende Claude-Code-Sitzung (Anmeldung des Nutzers, kein API-Schlüssel),
liest die Antwort lokal vor (Piper) und nimmt Freigaben per Stimme entgegen. Oberfläche ist zunächst Claude Code selbst
(Verlauf, Modell, Verbrauch); ein eigenes Fenster ist optional (Phase E).

Oberste Regel: Schäden jeder Art sind verboten. **Sprachdaten verlassen nie den PC.** An Anthropic geht nur der erkannte Befehlstext
(das ist der Zweck). Die alte Roadmap liegt in [docs/ROADMAP-v1.md](docs/ROADMAP-v1.md).

## Datenschutz-Grundregeln (Nutzerwunsch 2026-10-26, gelten für jeden Schritt)
1. Jeder Server, den kushim mitbringt oder startet (Channel, Brücke, Ollama, Whisper, Piper), bindet nur an **127.0.0.1** und
   enthält **keinen Code, der nach außen sendet** (keine Telemetrie, keine Updates, keine Cloud-Fallbacks, keine Downloads im
   Betrieb). Geprüft statisch durch `tests/test_no_egress.py` und im Test mit gesperrtem Netzwerk.
2. Fremde Werkzeuge nur mit abgeschalteter Außenkommunikation: Claude Code mit `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`
   (keine Telemetrie, Fehlerberichte, Auto-Updates); Web-Werkzeuge (`WebSearch`, `WebFetch`) gesperrt, solange der Nutzer nichts
   anderes entscheidet.
3. Downloads (Modelle, Pakete) nur bei der Installation, aus offiziellen Quellen, mit Prüfsumme.
4. **Entschieden (2026-10-26):** Claude Code mit Anthropics Modellen ist die einzige KI. Kein lokales Modell (kein Ollama o. ä.).
   Alles andere in kushim ist nur Weitergabe (Stimme → Text → Claude Code → Text → Stimme). Einzige Verbindung nach außen ist
   die von Claude Code selbst zu Anthropic (Befehlstext und was Claude für die Aufgabe liest).

Arbeitsweise: immer nur einen Schritt, danach Tests (`pytest`), Sicherheitsprüfung (`kushim-safety-review`), Commit. Schritte mit
**(Nutzer)** kann nur der Nutzer erledigen (Mikrofon, echte Stimme, Entscheidung).

## Querschnitt: Token sparen (alle Projekte), Grundlage: [docs/research/tokens-sparen.md](docs/research/tokens-sparen.md)
- [x] Z1 Recherche Token-Sparen und Graphify (Quellcode auf Netzzugriffe geprüft, am Repo mit gesperrtem Netz getestet)
- [x] Z2 `scripts/claude_setup.py`: Graphify (feste Version) + globale Einstellungen + Token-Regeln, `--project`, `--dry-run`; Tests
- [ ] Z3 **(Nutzer)** auf dem PC ausführen: `py scripts\claude_setup.py --project .` (danach Claude Code neu starten)
- [ ] Z4 Statuszeile mit Kontext-Füllstand, Kosten und Modell (global)
- [ ] Z5 Hook, der lange Testausgaben auf Fehlschläge kürzt (global)

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

## Phase B: Brücke zu Claude Code (Channel), Grundlage: [docs/research/jarvis-projekte.md](docs/research/jarvis-projekte.md)
Aufbau: `claude` läuft interaktiv (das ist die Oberfläche: Verlauf, `/model`, `/usage`, Freigabe-Dialog). Claude Code startet
den kushim-Channel (lokaler MCP-Server, stdio). kushim (Python) spricht mit dem Channel nur über 127.0.0.1 mit Token.

- [ ] B0 **Entscheidung (Nutzer):** Channel-Weg (Research Preview, Start mit `--dangerously-load-development-channels`) statt
      eigener `claude -p`-Steuerung? Und: lokaler HTTP-Port nur auf 127.0.0.1 mit Token zwischen kushim und Channel erlaubt?
      (Claude Code als einzige KI ist entschieden, siehe Datenschutz-Regel 4)
- [ ] B1 Prototyp ohne Sprache: Channel-Server `channel/` (Bun oder Node, offizielles `@modelcontextprotocol/sdk`, Versionen fest),
      `claude/channel`-Fähigkeit, nimmt Text per `POST 127.0.0.1` an (Token-Prüfung) und schiebt ihn in die Sitzung; Test mit `curl`
- [ ] B2 Antwort-Werkzeug `sprich` (kurzer deutscher Text, ohne Markdown, höchstens 600 Zeichen), gibt den Text an kushim;
      `instructions` sagen Claude, wann es `sprich` nutzt (Zusammenfassung am Ende eines Zugs)
- [ ] B3 kushim-Seite `bridge/` (Python, nur Loopback): Text senden, Ereignisse empfangen (Antwort, Freigabe-Anfrage, Status);
      `tests/test_no_egress.py` erlaubt nur 127.0.0.1; Tests mit gefälschtem Channel
- [ ] B4 In die Pipeline hängen: `Pipeline.chat` schickt den Befehl über die Brücke, spricht die `sprich`-Antwort mit Piper;
      kurze Quittung „Ich geb's an Claude.“; Mikrofon während der eigenen Ausgabe stumm
- [ ] B5 Startskript `kushim start`: startet `claude` mit dem Channel im gewählten Arbeitsordner und `kushim talk` dazu;
      `kushim doctor` prüft Claude-Version (mindestens 2.1.234), Anmeldung, Bun/Node
- [ ] B6 Abbrechen („abbrechen“) schickt Escape/Abbruch an die Sitzung, Notaus beendet kushim und schaltet den Channel stumm
- [ ] B7 Live-Test **(Nutzer)**: Wake Word → Befehl → Claude arbeitet im Terminal sichtbar → Antwort wird vorgelesen

## Phase C: Freigaben per Stimme (offizielle Freigabe-Weiterleitung)
- [ ] C1 Channel meldet `claude/channel/permission` an und reicht `permission_request` (request_id, tool_name, description,
      input_preview) an kushim weiter; Inhalte gelten als nicht vertrauenswürdig (nur vorlesen, nie ausführen)
- [ ] C2 Sprechbare Beschreibung: „Claude möchte den Befehl npm test ausführen. Erlauben?“, „… die Datei app.py ändern …“
- [ ] C3 Antwort per Stimme: „ja“ nur mit **stark** verifizierter Stimme, „nein“/Stille/Zeitablauf = nichts senden (Terminal-Dialog
      bleibt offen); Ergebnis als `allow`/`deny` mit der request_id zurück
- [ ] C4 Sperrliste: gefährliche Aktionen (Löschen, `git push --force`, Daten senden, Einstellungen ändern) nie per Stimme
      freigebbar, nur im Terminal (Idee aus voice-mod)
- [ ] C5 Protokoll jeder Freigabe lokal (was, wann, Sprecher-Score, Ergebnis), ohne Audio
- [ ] C6 Live-Test **(Nutzer)**: Claude will einen Befehl ausführen → per Stimme erlauben → Claude macht weiter

## Phase D: Modell und Verbrauch
Claude Code zeigt beides schon selbst (`/model`, `/usage`, Statuszeile). Hier nur die Sprach-Seite:
- [ ] D1 Statuszeile von Claude Code (`statusLine` in den Benutzer-Einstellungen) zeigt Modell, Kosten der Sitzung und kushim-Zustand
      (hört / denkt / spricht / gesperrt); Einstellung nur mit Ja des Nutzers schreiben
- [ ] D2 Sprachbefehle „welches Modell?“, „wie viel Verbrauch?“ werden lokal aus den Statusdaten beantwortet
- [ ] D3 Modell per Stimme wechseln („nimm Sonnet“): prüfen, ob ein Channel `/model` auslösen darf; sonst nur Hinweis

## Phase E: Eigene Oberfläche (optional, erst nach B–D entscheiden)
- [ ] E1 **Entscheidung (Nutzer):** Reicht Claude Code als Oberfläche plus Statuszeile, oder eigenes Fenster?
- [ ] E2 Falls ja: kleines Fenster (Tauri, Design aus `.claude/skills/kushim-ui-design/`) mit Avatar, letztem Befehl,
      Freigabe-Leiste (Klick parallel zur Stimme), Notaus-Knopf, Verbrauch
- [ ] E3 Setup-Assistent: Mikrofon, Stimme einschreiben, Wake Words, Claude-Anmeldung prüfen

## Später / offen
- [ ] Sprecher-Prüfung mit einer zweiten echten Person prüfen **(Nutzer)**
- [ ] Eigene Stimme (Klon) Hörtest **(Nutzer)**: `kushim voice clone-test`
- [ ] Echo-Unterdrückung für Lautsprecher-Betrieb
- [ ] Optional: Microsoft Copilot Cowork / Claude Cowork als zweites Ziel (keine API, nur über Fenster-Einfügen, z. B. mit Handy)
