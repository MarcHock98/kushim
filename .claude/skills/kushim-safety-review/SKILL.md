---
name: kushim-safety-review
description: Use after any change in kushim, before committing. Reviews the diff for safety-gate bypasses, data egress, harm risks and weakened rules; runs the tests.
---

# kushim Sicherheits-Review

Prüfe den aktuellen Diff gegen diese Checkliste und melde Verstöße mit Datei:Zeile.

1. **Gate-Umgehung:** Läuft jede Aktion mit Wirkung durch `ActionGate.check`? Neue Aktionen ohne `ActionSpec`?
2. **Egress:** Neue Netzwerk-Importe oder -Aufrufe außerhalb von `EgressGate`? Standard bleibt Modus A (`claude_enabled = false`).
3. **Abgeschwächte Regeln:** Änderungen an `safety/rules.py`, Default-Deny, Fail-Closed, Geldlimit (Standard 0), Notaus? Nur mit ausdrücklicher Nutzerfreigabe.
4. **Prompt Injection:** Fließen Inhalte aus Web/Mail/Dateien in Anweisungen oder Tool-Parameter?
5. **Geheimnisse:** Schlüssel, Tokens, Vault-Daten in Code, Logs, Tests oder Commit? `.gitignore` greift?
6. **Schaden:** Kann die Änderung seelisch, finanziell, körperlich, an Daten, Dritten oder langfristig schaden (Manipulation, Schmeichelei, Abhängigkeit)?
7. **Lernen/RL:** Belohnung nur „gefällt mir“? Sicherheitsverletzung muss immer negativ zählen. Darf das Lernen Regeln ändern? (Nein.)
8. **Tests:** `.venv\Scripts\python -m pytest -q` ausführen; Ergebnis ehrlich berichten.

Ausgabe: Liste der Funde nach Schwere, dann „freigegeben“ oder „nicht freigegeben“.
