# Änderungen an Skills und Agents durch die Routine

Format: Datum, Datei, Grund (ein Satz).

- 2026-10-03, .claude/skills/kushim-routine/SKILL.md: Routine angelegt.
- 2026-10-03, .claude/skills/kushim-routine/SKILL.md: Hinweis ergänzt, dass in der Sitzung angelegte Skills erst nach Neustart registriert sind; Durchlauf dann manuell nach SKILL.md.

- 2026-10-03, ROADMAP.md: STT-Punkt in Logik (erledigt) und Live-Modelltest (offen, Nutzer) geteilt, weil Modell-Download und Mikrofon nicht autonom möglich sind.

- 2026-10-03, tests/test_no_egress.py: ALLOWLIST um net/loopback.py erweitert, auf ausdrückliche Zustimmung des Nutzers; zusätzliche Tests sperren die Liste auf diesen Eintrag und prüfen die Imports des Moduls.

- 2026-10-03, gesamtes Projekt: Umbenennung kushim -> kushima auf Wunsch des Nutzers (Paket, Doku, Tests, Verknüpfungen). Sicherheitsdateien nur im Namen geändert; Notaus-Wörter um beide Schreibweisen ergänzt; Vault/Schlüssel/Env/Konfig rückwärts-kompatibel; Skill-Namen bewusst unverändert, damit /loop weiter funktioniert.

- 2026-10-03, gesamtes Projekt: Umbenennung kushim -> kushima auf Wunsch des Nutzers rückgängig gemacht (neuer Commit, keine History umgeschrieben, da bereits gepusht). Paket, CLI, Doku, Tests, Verknüpfungen wieder `kushim`; `kushima` nur noch als Rückfall für Schlüssel (Service `kushima-vault`), Env `KUSHIMA_*`, Konfig-Ordner und Vault-Pfad. Sicherheitsdateien nur im Namen geändert.
