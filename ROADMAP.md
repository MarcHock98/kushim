# kushim Roadmap v2: lokaler Jarvis vor Claude Code

Ziel (Nutzerwunsch 2026-10-26): Per Sprachbefehl Claude Code nutzen. kushim hört lokal zu (Wake Word, Sprecherprüfung, Whisper),
gibt den Befehl über einen lokalen Channel in die laufende Claude-Code-Sitzung (Anmeldung des Nutzers, kein API-Schlüssel),
liest die Antwort lokal vor (Piper) und nimmt Freigaben per Stimme entgegen. Oberfläche ist zunächst Claude Code selbst
(Verlauf, Modell, Verbrauch); ein eigenes Fenster ist optional (Phase E).

Oberste Regel: Schäden jeder Art sind verboten. **Sprachdaten verlassen nie den PC.** An Anthropic geht nur der erkannte Befehlstext
(das ist der Zweck). Die alte Roadmap (v1) steht in der Git-Historie.

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
- [x] Z4 Statuszeile mit Kontext-Füllstand, Kosten und Modell (global): `scripts/statusline.py`, einrichten mit
      `py scripts\claude_setup.py --statusline` (2026-10-26, 509 grün). Kosten liefert Claude Code 2.1.310 nicht; gezeigt werden
      stattdessen die Abo-Grenzen (5h/7d), Kosten nur, falls das Feld kommt. Live in Claude Code ansehen: **(Nutzer)**
- [x] Z5 Hook, der lange Testausgaben auf Fehlschläge kürzt (global): `scripts/trim_test_output.py`, einrichten mit
      `py scripts\claude_setup.py --test-hook` (2026-10-26, 536 grün, echter Lauf in Git Bash). Setzt nie eine Freigabe, nur
      den umgeschriebenen Befehl. Live in Claude Code ansehen: **(Nutzer)**

> **Stand nach dem Abgleich mit GitHub (2026-10-26):** Auf `master` kamen 35 Commits aus der alten Roadmap dazu, die beim
> Aufräumen berücksichtigt werden müssen: eine fertige **Tauri-Oberfläche** (`ui/`: Avatar, NOTAUS, Freigabe-Leiste,
> Live-Transkript, Gedächtnis, Sicherheitsstatus, Dashboard, Claude-Bereich mit Ordnern und Diff-Ansicht), der lokale
> **WebSocket-Server** (`net/server.py`, nur 127.0.0.1, vom Nutzer freigegeben), `kushim app`, Feedback-Log und
> `kushim behavior`. Vor jedem A-Schritt prüfen, welche UI-Teile und API-Typen daran hängen; die UI ist die Basis für
> Phase E (wiederverwenden statt neu bauen).

## Phase A: Aufräumen (nur löschen, nichts Neues)
Bleibt: Wake Word (`voice/trigger.py`, `wakeconfig.py`, `wakebuild.py`), Sprecherprüfung (`speaker.py`, `verify.py`, `embedder.py`,
`profile.py`, `enrollment.py`, `voiceprint.py`, `recorder.py`, `levels.py`), Audio (`audio.py`, `bargein.py`, `dialog.py`),
Whisper (`stt.py`), TTS (`tts.py`), Gesprächsschleife (`talk.py`, `pipeline.py`), Notaus (`safety/killswitch.py`),
Abbrechen (`tasks.py`), Vault (`memory/`, für das Stimmprofil), `config.py`, `cli.py`, `doctor.py`, `tests/test_no_egress.py`.

- [x] A1 Sprachbefehle für alte Werkzeuge entfernen: `voice/tool_commands.py`, `timer_commands.py`, `note_commands.py`,
      `commands.py`, `wake_commands.py` samt Tests; `talk.py`/`cli.py` ohne sie lauffähig. Tests grün (2026-10-26, 884 grün).
      Mit entfernt: `api/approvals_api.py` und `api/dashboard_api.py` (hingen nur an den Sprachbefehlen). Die UI zeigt
      Freigabe-Leiste und Übersicht bis Phase C/E als „nicht verfügbar“; der Haken `Pipeline.commands` bleibt für B4/D2
- [x] A2 Web und Recherche entfernen: `web/`, `research.py`, `net/web.py` samt Tests und ALLOWLIST-Einträgen in `test_no_egress.py`
      (2026-10-26, 750 grün). Mit entfernt: `claude_cli/ask.py`, `kushim search`/`research`. Behalten und verschoben:
      `sanitize.py` (Paketwurzel, für C1/C2) und `claude_cli/guard.py` (geht mit A4). Die Werkzeug-Einträge `web.search`
      und `claude.research` in `tools/registry.py` fallen erst mit A5
- [x] A3 Timer und Notizen entfernen: `timers.py` samt Tests und CLI-Befehlen (2026-10-26, 733 grün; CLI-Befehle gab es
      keine, Notizen lebten nur in `note_commands.py` aus A1). Gespeicherte Notizen im Vault und `run/timers.json` bleiben
      unangetastet (Daten des Nutzers); Werkzeug-Einträge `timer.local`/`notes.local` fallen mit A5
- [x] A4 Alte Claude-Steuerung entfernen: `claude_cli/` bis auf `base.py` (CLI finden, Anmeldung prüfen, saubere Umgebung) und
      `folders.py` (sichere Arbeitsordner), samt `api/claude_api.py` und Tests (2026-10-26, 578 grün). `kushim claude` kann
      noch check/enable/disable/folders/add/remove; Ordner-Tests jetzt in `tests/test_claude_folders.py`. Die UI zeigt den
      Claude-Bereich bis Phase B/E als „nicht verfügbar“ (Ordner-Verwaltung `claude.folder_*` geht weiter)
- [x] A5 Werkzeug-Verwaltung und Gates entfernen: `tools/`, `privacy.py`, `safety/gate.py`, `safety/approvals.py`, `api/tools_api.py`,
      `api/tasks_api.py`; `safety/rules.py` bleibt (Grundsätze). Vom Nutzer freigegeben am 2026-10-27, erledigt (495 grün):
      dazu `kushim tools`, `[tools]` in der Konfiguration; neuer Test `tests/test_rules.py` sperrt die Rückkehr der Gates.
      Skills/Agents auf „kushim führt selbst nichts aus, Netz nur ALLOWLIST/127.0.0.1“ umgestellt, `kushim-add-tool` veraltet
- [x] A6 Lokales Sprachmodell entfernen: `llm/`, `launcher.py` (Ollama), `api/llm_api.py`, `[llm]` in der Konfiguration, Ollama aus
      `install.ps1`, `fetch_models.py`, `doctor.py`; `gpu.py` nur noch für Whisper (2026-10-26, 506 grün). Mit entfernt:
      `kushim start|llm|behavior`, `learning/behavior.py`, Verknüpfung `kushim.lnk`. `kushim talk` antwortet bis B4 mit
      „Ich bin noch nicht mit Claude verbunden.“; `kill_tree` liegt jetzt in `procflags.py`. Auf dem PC bleiben
      `tools/ollama`, `models/ollama` und die alte Desktop-Verknüpfung `kushim.lnk` liegen (Löschen macht der Nutzer)
- [x] A7 Rest prüfen: `learning/`, `setup/`, `api/setup_api.py` entfernen oder behalten (Setup-Status bleibt nützlich für die UI);
      README „Was es heute kann“ kürzen; `kushim help` zeigt nur noch vorhandene Befehle (2026-10-26, 500 grün). Entfernt:
      `learning/` (Stil-Bandit ohne Nutzer). Behalten: `setup/`, `api/setup_api.py` (UI) und **`net/loopback.py`**: hat seit A6
      keine Nutzer, ist aber genau der 127.0.0.1-Client, den B3 braucht (sonst später neue ALLOWLIST-Freigabe nötig).
      Neuer Test: `kushim help` nennt nur vorhandene Befehle. README auf Claude Code umgeschrieben

## Phase B: Brücke zu Claude Code (Channel), Grundlage: [docs/research/jarvis-projekte.md](docs/research/jarvis-projekte.md)
Aufbau: `claude` läuft interaktiv (das ist die Oberfläche: Verlauf, `/model`, `/usage`, Freigabe-Dialog). Claude Code startet
den kushim-Channel (lokaler MCP-Server, stdio). kushim (Python) spricht mit dem Channel nur über 127.0.0.1 mit Token.

- [x] B0 **Entscheidung (Nutzer, 2026-10-27: ja, beides):** Channel-Weg (Research Preview, Start mit `--dangerously-load-development-channels`) statt
      eigener `claude -p`-Steuerung? Und: lokaler HTTP-Port nur auf 127.0.0.1 mit Token zwischen kushim und Channel erlaubt?
      (Claude Code als einzige KI ist entschieden, siehe Datenschutz-Regel 4)
- [x] B1 Prototyp ohne Sprache: Channel-Server `channel/` (Bun oder Node, offizielles `@modelcontextprotocol/sdk`, Versionen fest),
      `claude/channel`-Fähigkeit, nimmt Text per `POST 127.0.0.1` an (Token-Prüfung) und schiebt ihn in die Sitzung; Test mit `curl`
      (2026-10-27, 509 grün, `curl` 401/202 geprüft). **Abweichung mit Grund:** `src/kushim/channel/server.py` in Python-Standardbibliothek
      statt Bun/Node + SDK: MCP über stdio ist zeilenweises JSON-RPC, so gibt es keinen npm-Download und die Netzwerk-Tests greifen.
      Start: `python -m kushim.channel`; Port/Token in `run/channel.json`. Safety-Audit freigegeben, 5 Funde behoben.
      Mit echter Claude-Code-Sitzung noch nicht geprüft (braucht B5 und den Nutzer am Terminal)
- [x] B2 Antwort-Werkzeug `sprich` (kurzer deutscher Text, ohne Markdown, höchstens 600 Zeichen), gibt den Text an kushim;
      `instructions` sagen Claude, wann es `sprich` nutzt (Zusammenfassung am Ende eines Zugs) (2026-10-27, 513 grün). Rückweg:
      kushim holt per `GET /reply?wait=…` (Token, gleicher Port) ab, statt selbst zu lauschen: kein zweiter Port, keine neue
      ALLOWLIST-Stelle. Für B3 heißt das: `bridge/` sendet `POST /message` und fragt `GET /reply` über `net/loopback.py`
- [x] B3 kushim-Seite `bridge/` (Python, nur Loopback): Text senden, Ereignisse empfangen (Antwort, Freigabe-Anfrage, Status);
      `tests/test_no_egress.py` erlaubt nur 127.0.0.1; Tests mit gefälschtem Channel (2026-10-27, 531 grün): `channel/bridge.py`,
      Tests gegen den echten Channel-Server im selben Prozess. Freigabe-Anfragen folgen mit C1 über denselben Abholweg
- [x] B4 In die Pipeline hängen: `Pipeline.chat` schickt den Befehl über die Brücke, spricht die `sprich`-Antwort mit Piper;
      kurze Quittung „Ich geb's an Claude.“; Mikrofon während der eigenen Ausgabe stumm (2026-10-27, 537 grün):
      `voice/claude_chat.py`, Abruf alle 2 s (Abbrechen/Notaus greifen schnell), nach 3 min Hinweis und spätere Ansage.
      Mikrofon: bleibt wie bisher über Barge-in geregelt (`barge_in = false` in `wakewords.toml` hört während der Ausgabe
      gar nicht zu); echte Echo-Unterdrückung steht unter „Später“. Live nicht geprüft (braucht B5 und den Nutzer)
- [x] B5 Startskript `kushim start`: startet `claude` mit dem Channel im gewählten Arbeitsordner und `kushim talk` dazu;
      `kushim doctor` prüft Claude-Version (mindestens 2.1.234), Anmeldung, Bun/Node (2026-10-27, 550 grün; Bun/Node entfällt,
      der Channel ist Python). `channel/launch.py`, `--strict-mcp-config` (nur der kushim-Server), Telemetrie aus, eigenes Fenster;
      Verknüpfung „kushim start“ im Installer. Echter Start mit Bestätigungsdialog nicht geprüft: das ist B7 **(Nutzer)**
- [x] B6 Abbrechen („abbrechen“) schickt Escape/Abbruch an die Sitzung, Notaus beendet kushim und schaltet den Channel stumm
      (2026-10-27, 552 grün). Ein Channel kann einen laufenden Zug nicht unterbrechen (Claude Code kennt nur Nachricht und
      Freigabe): „abbrechen“ schickt `kind="cancel"` (fester Text), der Notaus meldet Claude einmal `kind="kill"` und sperrt
      alles Weitere. Sofort unterbrechen bleibt Esc im Claude-Fenster (README). Live nicht geprüft **(Nutzer)**
- [x] B7 Live-Test **(Nutzer)**: Wake Word → Befehl → Claude arbeitet im Terminal sichtbar → Antwort wird vorgelesen
      (2026-10-27: vom Nutzer mit `kushim start` bestätigt, „Ja er antwortet“)

## Phase C: Freigaben per Stimme (offizielle Freigabe-Weiterleitung)
> **Stand 2026-11-12 (Nutzerwunsch):** Die Sprecher-Prüfung wurde entfernt, damit auch die Freigaben per Stimme.
> **C3 und C4 sind zurückgebaut** (`voice/permission_voice.py`, `channel/voice_policy.py` gelöscht). Es bleiben C0 (Leiste
> in der Oberfläche), C1 (Weiterleitung), C2 (Ansage, endet immer mit „Bitte im Terminal bestätigen.“) und C5 (Protokoll,
> nur noch Entscheidungen aus der Oberfläche, ohne Sprecher-Score). Freigegeben wird im Claude-Fenster oder in der Leiste.
- [x] C0 (2026-11-11, Python 778 und UI 61 grün, Safety-Audit freigegeben; echtes Tauri-Fenster nicht geprüft; gekürzte
      Vorschau: in der UI nur Ablehnen; Knöpfe nach jedem Wechsel 700 ms gesperrt; Entscheidungen im Protokoll C5) Freigabe-Leiste der UI (`approvals.get`/`approvals.decide`, gleiche Regeln: exakter Text, Hash, `confirm`) neu an die
      Channel-Freigaben hängen (ergänzt 2026-10-26: der alte Unterbau fiel mit A1 weg)
- [x] C1 Channel meldet `claude/channel/permission` an und reicht `permission_request` (request_id, tool_name, description,
      input_preview) an kushim weiter; Inhalte gelten als nicht vertrauenswürdig (nur vorlesen, nie ausführen)
      (2026-10-27, 561 grün): Anfragen kommen über `GET /reply` (`permissions`), Antwort `POST /permission`; kushim
      beantwortet noch nichts selbst, Notaus lehnt alles Offene ab
- [x] C2 Sprechbare Beschreibung: „Claude möchte den Befehl npm test ausführen. Erlauben?“, „… die Datei app.py ändern …“
      (2026-11-11, 573 grün): `channel/speakable.py` liest `input_preview` (Format aus Claude Code 2.1.321), `ClaudeChat`
      sagt jede Anfrage einmal an (in der Runde und im Leerlauf). Bis C3 endet die Ansage mit „Bitte im Terminal
      bestätigen.“ statt „Erlauben?“ (`announce(ask=True)` schaltet um). Nicht geprüft: Aussprache mit Piper (nur Nutzer).
- [x] C3 ~~Antwort per Stimme~~ (gebaut 2026-11-11, **entfernt 2026-11-12**, siehe oben): „ja“ nur mit **stark** verifizierter Stimme, „nein“/Stille/Zeitablauf = nichts senden (Terminal-Dialog
      bleibt offen); Ergebnis als `allow`/`deny` mit der request_id zurück. Ergänzt 2026-11-11 (Review C2): ein gekürzt
      vorgelesener Befehl („und so weiter“) oder eine gekürzte `input_preview` („elided“, „…“) ist nie per Stimme freigebbar
      (2026-11-11): `voice/permission_voice.py`. Nur feste Sätze („Ja, das erlaube ich“), ein bloßes „ja“ ist zu kurz für
      „stark“ (Nachfrage). Gilt nur für die zuletzt gestellte Frage, 60 s. kushim sendet nie „deny“ (nur der Notaus).
      Nach einer Frage endet die Runde, damit zugehört wird; Claudes Antwort kommt später als Meldung. Mit der geklonten
      eigenen Stimme als Ausgabe keine Freigaben per Stimme (Echo könnte die Sprecher-Prüfung bestehen).
- [x] C4 ~~Sperrliste~~ ~~Erlaubt-Liste~~ (gebaut 2026-11-11, **entfernt 2026-11-12**, siehe oben) (umgebaut nach dem Safety-Audit 2026-11-11: die Sperrliste war mit Schleifen,
      `python -Bc`, .NET-Aufrufen u. a. umgehbar): `channel/voice_policy.py` prüft die Rohdaten. Per Stimme nur: ein einfacher
      Befehl aus Tests/Prüfwerkzeugen (`npm test`, `npm run test|build|lint|typecheck|check`, `pytest`, `python -m pytest|…`),
      lesendes Git mit Options-Liste (`show`/`diff` nur mit `--stat` oder Pfaden), `ls`/`dir`/`pwd`, Lesen von Dateien im
      Arbeitsordner ohne Geheimnisse. Schreiben/Ändern, Web, MCP, Agenten nie per Stimme. Ohne Arbeitsordner (`kushim start`
      gibt ihn an `talk`) gar nichts. Pfade werden ohne Netzzugriff geprüft. Drei Audit-Runden.
      **Restrisiko (bewusst):** Tests und Prüfwerkzeuge führen Code des Repos aus (`conftest.py`, `package.json`-Skripte).
      Hat Claude solche Dateien ohne Terminal-Dialog geändert (Modus „acceptEdits“), führt ein „ja“ diesen Code aus. Darum
      Freigaben per Stimme nur im Standard-Modus von Claude Code benutzen.
- [x] C5 Protokoll jeder Freigabe lokal (was, wann, Sprecher-Score, Ergebnis), ohne Audio (2026-11-11): `channel/approval_log.py`
      im verschlüsselten Vault (Audit), Stimme und Oberfläche, `kushim claude approvals` zeigt es. Die Kurzbeschreibung kann
      Teile eines Befehls enthalten (z. B. ein Token im Klartext); sie liegt nur verschlüsselt im Vault.
- [x] C7 ~~Token-Dateien (`run/channel.json`, `run/api.json`) aus dem Projektordner verlegen~~
      (Safety-Audit 2026-11-11, B5): Arbeitet Claude im kushim-Repo selbst, könnte es die Token lesen und sich über Channel
      oder API selbst Freigaben geben. **Entscheidung Nutzer 2026-11-11: so lassen, nur Warnung** bei `kushim start`
      (bewusst akzeptiertes Restrisiko; Verlegen nach `%LOCALAPPDATA%\kushim\run` bleibt möglich, wenn gewünscht).
- [ ] C6 Live-Test **(Nutzer)**: Claude will einen Befehl ausführen → per Stimme erlauben → Claude macht weiter

## Phase D: Modell und Verbrauch
Claude Code zeigt beides schon selbst (`/model`, `/usage`, Statuszeile). Hier nur die Sprach-Seite:
> **Geschlossen 2026-11-13** (Empfehlung der Routine, der Nutzer sagte „mach weiter“; jederzeit wieder zu öffnen): D1 gilt
> durch Z4 als erledigt, ohne kushim-Zustand (die Zeile wird nur nach jeder Antwort neu gezeichnet und wäre veraltet).
> D2 und D3 entfallen: Nach dem Modell kann man Claude fragen, den Verbrauch zeigt die Statuszeile.
- [x] D1 (durch Z4, ohne kushim-Zustand) Statuszeile von Claude Code (`statusLine` in den Benutzer-Einstellungen) zeigt Modell, Kosten der Sitzung und kushim-Zustand
      (hört / denkt / spricht / gesperrt); Einstellung nur mit Ja des Nutzers schreiben
- [x] ~~D2~~ (entfällt, siehe oben) Sprachbefehle „welches Modell?“, „wie viel Verbrauch?“ werden lokal aus den Statusdaten beantwortet
- [x] ~~D3~~ (entfällt, siehe oben) Modell per Stimme wechseln („nimm Sonnet“): prüfen, ob ein Channel `/model` auslösen darf; sonst nur Hinweis

## Phase E: Eigene Oberfläche (optional, erst nach B–D entscheiden)
- [x] E1 (2026-11-12: Nutzer entschied „UI bleibt“, Pläne `docs/ui-dynamic-plan.md`, `docs/ui-p2-plan.md`) **Entscheidung (Nutzer):** Reicht Claude Code als Oberfläche plus Statuszeile, oder die vorhandene Tauri-UI (`ui/`)
      weiterverwenden und auf den Channel umstellen (Empfehlung: weiterverwenden)?
- [x] E2 (2026-11-23, kompakter Modus und Verbrauch, `docs/ui-e2e3-plan.md`; echtes Fenster nicht geprüft) Falls ja: kleines Fenster (Tauri, Design aus `.claude/skills/kushim-ui-design/`) mit Avatar, letztem Befehl,
      Freigabe-Leiste (Klick parallel zur Stimme), Notaus-Knopf, Verbrauch
- [x] E3 (2026-11-23, Setup-Assistent mit sechs Schritten; echtes Mikrofon nicht geprüft) Setup-Assistent: Mikrofon, ~~Stimme einschreiben~~ (Sprecher-Prüfung entfernt 2026-11-12), Wake Words, Claude-Anmeldung prüfen

## Phase F: Selbst erweitern (Plan `docs/ui-p7-plan.md`, Entscheidungen des Nutzers 2026-11-23)
- [ ] F1 Stufe 1 „Simulation als Daten“: Baustein `sim_eigen` mit kleiner Formelsprache (`stage/formel.py`, Pratt-Parser mit
      Tiefenzähler, kein `eval`/`ast`), festes RPN-Format, Probe bei t0, Prüfung zweimal; UI führt nur geprüfte RPN aus
      (`formel.ts`, `eigenSim.ts`). Python-Seite gebaut am 2026-11-23 (Branch `routine/p7-formel`), UI-Engine auf `routine/p7-engine`;
      Zusammenführen, Ansicht `EigenSimulation.tsx`, Mock und echtes Fenster offen
- [ ] F2 Rezeptbuch: geprüfte Rezepte (`stage/rezepte/*.json`, `rezepte.py`), Claude schickt nur Rezeptname und Parameter
- [ ] F3 Werkstatt: Werkzeug `entwickle` (nur Vorschlag), Karte Annehmen/Ablehnen (nie per Stimme), sichtbares Fenster
      „kushim-Werkstatt“ (eigene Claude-Code-Sitzung, Opus, ohne Channel/MCP/Web, Standard-Freigabemodus), geschützte Pfade per
      Deny-Regeln, Notaus beendet die Werkstatt
- [ ] F4 Übernahme und Rückgängig: Merge nur im Werkstatt-Fenster nach dem Dialog von Claude Code (kushim merged nie), Schutzprüfung
      nur als Anzeige, Rückgängig per Revert (auch CLI), danach neu bauen oder neu starten

## Später / offen
- [x] ~~Sprecher-Prüfung mit einer zweiten echten Person prüfen~~ (entfällt: Sprecher-Prüfung entfernt 2026-11-12)
- [x] ~~Eigene Stimme (Klon) Hörtest **(Nutzer)**: `kushim voice clone-test`~~ (2026-11-11: Stimmklon auf Wunsch des Nutzers komplett entfernt)
- [ ] Echo-Unterdrückung für Lautsprecher-Betrieb
- [ ] Optional: Microsoft Copilot Cowork / Claude Cowork als zweites Ziel (keine API, nur über Fenster-Einfügen, z. B. mit Handy)
