# Loops

Loops laufen zur Laufzeit in Claude Code (`/loop`), sie sind keine Dateien.

## Entwicklungs-Loops

**Sicherheitswache** (alle 30 Minuten während der Entwicklung):
```
/loop 30m Führe .venv\Scripts\python -m pytest -q aus und starte den Agenten safety-auditor auf den ungeprüften Änderungen. Melde nur neue Funde und Testfehler.
```

**Roadmap-Fortschritt** (selbst getaktet, ein Schritt pro Durchlauf):
```
/loop /kushim-next-phase
```
Stoppt bei Entscheidungen, die dir gehören (Hardware, Kosten, Daten nach außen).

**Backup-Kontrolle** (täglich):
```
/loop 24h Prüfe mit `kushima memory info`, ob der Vault lesbar ist und das letzte Backup im Backup-Ziel nicht älter als 24 Stunden ist.
```

## Laufzeit-Loops der KI (später in kushima selbst)
- Nächtliche Reflexion: Gespräche auswerten, Profil-Vorschläge erzeugen (du bestätigst).
- Wöchentlicher Sicherheitsbericht: Audit-Log, abgelehnte Aktionen, auffällige Muster.
- RL-Auswertung: Feedback-Log prüfen, Sicherheitsverletzungen immer negativ werten, Änderungen nur mit deiner Freigabe.
