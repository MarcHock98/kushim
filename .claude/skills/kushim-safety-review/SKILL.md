---
name: kushim-safety-review
description: Use after any change in kushim, before committing. Reviews the diff for new acting code, data egress, harm risks and weakened rules; runs the tests.
---

# kushim Sicherheits-Review

Prüfe den aktuellen Diff gegen diese Checkliste und melde Verstöße mit Datei:Zeile.

1. **Keine eigenen Aktionen:** kushim führt selbst keine Aktionen mit Wirkung aus (seit Roadmap v2 A5); alles mit Wirkung macht Claude Code mit seinen Freigaben (Phase C). Neuer ausführender Code in kushim ist ein Fund und braucht das Ja des Nutzers.
2. **Egress:** Netzwerkcode nur in den Modulen der `ALLOWLIST` (`tests/test_no_egress.py`) und nur zu 127.0.0.1; kushim selbst geht nie ins Internet.
3. **Abgeschwächte Regeln:** Änderungen an `safety/rules.py`, Default-Deny, Fail-Closed, Geldlimit (Standard 0), Notaus? Nur mit ausdrücklicher Nutzerfreigabe.
4. **Prompt Injection:** Fließen Inhalte aus Web/Mail/Dateien in Anweisungen oder Tool-Parameter?
5. **Geheimnisse:** Schlüssel, Tokens, Vault-Daten in Code, Logs, Tests oder Commit? `.gitignore` greift?
6. **Schaden:** Kann die Änderung seelisch, finanziell, körperlich, an Daten, Dritten oder langfristig schaden (Manipulation, Schmeichelei, Abhängigkeit)?
7. **Lernen/RL:** Belohnung nur „gefällt mir“? Sicherheitsverletzung muss immer negativ zählen. Darf das Lernen Regeln ändern? (Nein.)
8. **Tests:** `.venv\Scripts\python -m pytest -q` ausführen; Ergebnis ehrlich berichten.

Ausgabe: Liste der Funde nach Schwere, dann „freigegeben“ oder „nicht freigegeben“.
