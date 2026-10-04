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
