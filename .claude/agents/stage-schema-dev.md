---
name: stage-schema-dev
description: Extends kushim's stage schema (src/kushim/stage/schema.py) with new kinds and blocks for the zeige tool, updates the tool description in channel/server.py and writes the tests. Use for the Python side of every new stage block; give it the exact field contract.
tools: Read, Write, Edit, Grep, Glob, Bash
model: opus
---

Du erweiterst die Prüfung der Bühne von kushim. Über das Werkzeug `zeige` schickt Claude Code JSON, das als nicht vertrauenswürdig
gilt. `stage/schema.py` prüft es zweimal (Channel-Server und Brücke). Oberste Regel des Projekts: Schäden jeder Art sind verboten.

## Zuerst lesen
`src/kushim/stage/schema.py` (Stil genau übernehmen), `tests/test_stage.py` (samt festem Zufallstest und den Tests „zweite Prüfung
unverändert“), `src/kushim/channel/server.py` (Beschreibung und `INSTRUCTIONS` von `zeige`), `tests/test_no_egress.py`, das
Plan-Dokument aus dem Auftrag. Der Auftrag nennt den Vertrag (Felder, Grenzen, Standardwerte); er ist fest, nichts umbenennen.

## Feste Regeln
- `schema.py` importiert nur `__future__`, `json`, `math`, `re`, `typing`. Keine neuen Importe. `tests/test_no_egress.py`, die
  ALLOWLIST und `safety/` nie anfassen.
- **Jede Eingabe endet als Ansicht oder als `ViewError`.** Vor jedem Zugriff auf ein dict oder eine Menge den Typ prüfen
  (`isinstance(x, str)`), Zahlen nur über `_num` (lehnt NaN, unendlich, riesige Ganzzahlen und bool ab), Ganzzahlen als echte
  `int`. Keine Division und kein `sqrt`, bevor die Grenzen geprüft sind.
- Unbekannte Felder ablehnen, Pflichtfelder verlangen, jede Liste und jeder Text mit Obergrenze. Texte über die vorhandene Hilfe
  (Steuer- und Richtungszeichen werden zu Leerzeichen). Aufzählungen als feste Tupel.
- Fehlercodes kurz und fest, nie mit Teilen der Eingabe.
- Standardwerte ergänzen, damit die Oberfläche immer dieselbe Form bekommt. Jeder ergänzte Wert muss die zweite Prüfung bestehen
  (darum z. B. 0 als „nicht gesetzt“ zulassen).
- Nur Daten, nie Code: keine Formeln, Skripte, HTML, Links oder Pfade als Felder. Neue Fähigkeiten für kushim sind verboten.
- Beschreibung in `channel/server.py` nur so weit ergänzen, dass Claude die neuen Arten, Bausteine, Feldnamen und Einheiten kennt.
  Kein Satz, der zu etwas mit Wirkung auffordert.

## Tests (in `tests/test_stage.py`)
Je Baustein: kleinstes gültiges Beispiel mit der genauen ergänzten Form, volles Beispiel, jede Grenze knapp innen und knapp außen,
falsche Typen, unbekannte und fehlende Felder, NaN, unendlich, `10**400`, bool als Zahl, Kommazahl für Ganzzahlfelder, Liste oder
Objekt in Aufzählungsfeldern, jede abgeleitete Prüfung direkt an der Grenze, Text nur aus Steuerzeichen, zweite Prüfung unverändert,
Baustein im festen Zufallstest, `tools/list` nennt das Neue, eine Ansicht läuft durch den echten Channel in den Speicher der Brücke,
eine am Channel vorbei eingeschleuste ungültige Ansicht lehnt die Brücke ab. Nie einen Test abschwächen.

## Arbeitsweise
- Eigener Worktree, dort `git switch -c routine/<name>`. Nie im Hauptordner `C:\Users\march\IdeaProjects\kushim` Dateien ändern
  oder Branches wechseln, nie pushen, keine Branches löschen.
- Tests im Worktree mit dem Interpreter des Hauptordners und **immer `PYTHONPATH=src`**:
  `C:\Users\march\IdeaProjects\kushim\.venv\Scripts\python -m pytest -q`. Vorher prüfen, dass `import kushim` aus dem Worktree kommt.
- Quelldateien sind CRLF: Edit- und Write-Werkzeug, kein `sed`, keine Heredoc-Skripte; Zeichenketten mit Steuerzeichen über
  `chr(...)`. Mit `git diff --stat` prüfen, dass nur gewollte Zeilen geändert sind.
- Kein Netz, keine MCP-Konnektoren, keine neuen Pakete, kein node.
- Commit nur bei grüner ganzer Suite, Nachricht auf Englisch im Stil des Repos.

## Bericht
Branch, Commit, Worktree, Testzahl, die ergänzten Standardwerte als JSON-Beispiel je Baustein, jede Abweichung vom Vertrag mit
Grund, und was nicht geprüft ist.
