# Änderungen an Skills und Agents durch die Routine

Format: Datum, Datei, Grund (ein Satz).

- 2026-10-03, .claude/skills/kushim-routine/SKILL.md: Routine angelegt.
- 2026-10-03, .claude/skills/kushim-routine/SKILL.md: Hinweis ergänzt, dass in der Sitzung angelegte Skills erst nach Neustart registriert sind; Durchlauf dann manuell nach SKILL.md.

- 2026-10-03, ROADMAP.md: STT-Punkt in Logik (erledigt) und Live-Modelltest (offen, Nutzer) geteilt, weil Modell-Download und Mikrofon nicht autonom möglich sind.

- 2026-10-03, tests/test_no_egress.py: ALLOWLIST um net/loopback.py erweitert, auf ausdrückliche Zustimmung des Nutzers; zusätzliche Tests sperren die Liste auf diesen Eintrag und prüfen die Imports des Moduls.

- 2026-10-03, gesamtes Projekt: Eine kurzzeitige Umbenennung des Projekts wurde auf Wunsch des Nutzers komplett rückgängig gemacht (neuer Commit, keine Historie umgeschrieben, da bereits gepusht) und anschließend alle Rückfall-Reste für den kurzzeitigen Namen aus Code, Tests, Installationsskript und Doku entfernt. Name, Paket, CLI, Verknüpfungen und Skills heißen durchgehend `kushim`.

- 2026-10-03, voice/: zentrale Wake-Word-Konfiguration `wakewords.toml` (wakeconfig.py) eingeführt, freie Wörter per KWS-Detektor; `[voice] wake_words` in config.toml und Vault-Speicherung entfernt, damit es nur eine Quelle gibt. Standard-Wörter auf Wunsch des Nutzers ohne "hey jarvis".

- 2026-10-04, voice/: Sprecher-Prüfung neu (profile.py, verify.py): Mehr-Prototypen-Profil, Schwelle aus Daten, Fenster-Prüfung, "stark"-Stufe für Änderungen, kurzes Audio auf 3 s aufgefüllt; Einschreiben aus den 10 Klon-Absätzen; längere Spracheingabe (end_silence_seconds/max_seconds); zusätzlich Piper-MLS-Mehrsprecher-Modell (77 MB, Hugging Face rhasspy/piper-voices, SHA-256 gepinnt) als Vergleichsgruppe. Sicherheitsregeln und Allowlist unverändert.

- 2026-10-04, src/kushim/safety/gate.py: Sprecher-Prüfung gilt jetzt auch für Nur-Lesen-Aktionen mit Außenwirkung (Verschärfung, Lücke beim Test der Web-Recherche gefunden).
- 2026-10-04, ROADMAP.md/docs: Tool-Verwaltung und Web-Recherche-Logik ergänzt; Netz-Modul `net/web.py` wartet auf ausdrückliche Freigabe (Egress-Sperre, docs/tools-plan.md).
- 2026-10-04, voice/: Werkzeuge per Sprache (tool_commands.py): ehrliche Liste aus der Registry statt Erfindung des Sprachmodells, Recherche und Claude-Steuerung mit gesprochenem ja/nein, Ansage wenn Claude fertig ist oder fragt; Einschalten bleibt UI/CLI. Sicherheitsregeln und Allowlists unverändert (Web-Paket nur über cli.py).
- 2026-10-04, .claude/skills/kushim-add-tool/SKILL.md: Abschnitt "Gelernte Fallstricke" (Registry, READ mit Außenwirkung, Prüfer, Freigabe-Text, Netz-Modul nur mit Freigabe, git status nach neuen Ordnern).
- 2026-10-04, .claude/skills/kushim-routine/SKILL.md: Abschnitt "Gelernte Fallstricke (Arbeitsweise)" (Shell/Heredocs, CRLF, live prüfen, messen, hängende Läufe, .gitignore, Egress-Lockerung nur nach Frage).
- 2026-10-04, .gitignore: `tools/` -> `/tools/`, weil sonst `src/kushim/tools/` ignoriert wurde.
- 2026-10-04, tests/test_no_egress.py: ALLOWLIST um `net/web.py` erweitert, auf ausdrückliche Zustimmung des Nutzers ("erstelle eine Websuche mit net/web.py, keine Downloads erlauben"); zusätzliche Tests sperren Importe, Domain/Pfad/Content-Type und das Fehlen jeder Schreibfunktion; Aufrufer nur `cli.py`.
- 2026-10-04, .claude/skills/kushim-add-tool/SKILL.md: Fallstricke zu `Untrusted` (Web-Inhalte nie als Anweisung) und "keine Downloads".
- 2026-10-04, tests/test_no_egress.py: zusätzliche Sperr-Tests für die Claude CLI (nur in `claude_cli/base.py` gefunden; Rechteumgehungs-Flags nur in der Verbotsliste von `claude_cli/ask.py`). Verschärfung, keine Lockerung.
- 2026-10-04, docs: Recherche über Claude (Minimal-Modus) mit Wikipedia als Ersatz; `docs/claude-cli-plan.md` um die zwei Betriebsarten ergänzt.
- 2026-10-04, src/kushim/voice/stt.py: Sperre um die Spracherkennung (Abbruch-Erkennung läuft parallel zur laufenden Antwort); `tasks.py` neu (Abbrechen). Keine Sicherheitsregel gelockert: Abbrechen ist nur Anhalten und lehnt offene Freigaben ab.
- 2026-10-04, src/kushim/web/guard.py: IBAN-Erkennung erkennt jetzt auch eine IBAN, vor der Wörter stehen (Verschärfung; die Websuche blockierte das bisher nur zufällig über die Telefonregel).
- 2026-10-04, tests/test_no_egress.py: Test für Rechteumgehungs-Flags jetzt per Syntaxbaum (nur in `FORBIDDEN_FLAGS`, Docstrings ausgenommen); Aufrufer-Sperre für das Paket `web` auf die bekannten Module erweitert. Keine Lockerung.
- 2026-10-04, .gitignore: `.claude/worktrees/` (Claude-Worktrees).
- 2026-10-04, .claude/skills/kushim-routine und kushim-add-tool: Fallstricke aus dem Claude-CLI-Praxistest (Skripte schreiben Quellcode, Wegwerf-Repo, CLI-Regelschreibweise, Verweigerungen der ganzen Sitzung).
- 2026-10-04, src/kushim/claude_cli/dev.py: `--setting-sources user` im Entwicklungs-Modus (Verschärfung; Selbst-Eskalation über Projekt-Einstellungen am echten Aufruf nachgewiesen und verhindert); tests/test_no_egress.py: Test, dass `ClaudeSessions.start/answer` nur aus control.py aufgerufen werden.

- 2026-10-04, voice/tool_commands.py + config.py: Auf ausdrücklichen Wunsch des Nutzers ("kushim soll direkt handeln") gilt der gesprochene Befehl der verifizierten Stimme als Freigabe für Recherche und Claude-Start (`[tools] direct`, Standard an, `false` bringt Vorschau und "ja" zurück). Prüfer, Hash-Bindung, Gate, Sprecher-Prüfung (Claude-Start stark), Notaus und "abbrechen" unverändert; Antworten an Claude und Erlaubnisse fragen weiter nach.
