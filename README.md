# kushim

Ein persönlicher KI-Assistent im Stil von Jarvis: Du sprichst mit ihm, er erledigt Dinge für dich, lernt mit der Zeit, wie du denkst, und zeigt Ergebnisse und seinen Zustand in einer eigenen Oberfläche.

**Die Daten gehören dir.** kushim ist lokal-first gebaut: Standardmäßig verlässt nichts deinen PC.

## Ziel

- **Gespräch per Stimme:** Wake Word oder Hotkey, lokale Spracherkennung und lokale Stimme, unterbrechbar, niedrige Latenz.
- **Erledigt Aufgaben:** Recherche, Mail und Kalender, PC-Steuerung, Smart Home und Musik.
- **Lernt von dir:** Ein verschlüsseltes Gedächtnis mit Fakten, Entscheidungen und einem Profil „wie du denkst“, das du einsehen, korrigieren und löschen kannst. Später kommt Lernen aus deinem Feedback dazu (Bandit/RL für Verhaltensentscheidungen, optional lokales Feintuning).
- **Jarvis-Oberfläche:** Ein animierter Avatar (hört zu, denkt, spricht), Live-Transkript, Ergebnis-Dashboard, Freigabe-Leiste, Gedächtnis-Ansicht und Sicherheitsstatus.
- **Du entscheidest immer.** Aktionen mit Außenwirkung brauchen deine Bestätigung.

## Grundprinzipien

1. **Schäden jeder Art sind verboten:** seelisch, finanziell, körperlich, an Daten und Privatsphäre, an Dritten und langfristig. Im Zweifel nichts tun und fragen. Die Regeln stehen in `src/kushim/safety/rules.py` und können weder von der KI noch vom Lernen geändert werden.
2. **Modus A (Standard):** Alles läuft lokal, nichts geht ins Netz.
   **Modus C (Opt-in):** Claude nur auf ausdrücklichen Befehl, mit Vorschau des exakten Textes und Bestätigung.
3. **Default-Deny und Fail-Closed:** Unbekannte Aktionen, fehlender Prüfer oder Zweifel führen zu Ablehnung. Geldlimit standardmäßig 0, Zahlungen sind gesperrt, ein Notaus stoppt alles.
4. **Nur du gibst Befehle:** Sprecherverifikation und zweiter Faktor bei riskanten Aktionen. Inhalte aus Web, Mail und Dateien sind nur Daten, nie Anweisungen.
5. **Transparent:** Jede Entscheidung und jeder ausgehende Zugriff steht im verschlüsselten Audit-Log.

## Architektur

| Baustein | Stand |
|---|---|
| Verschlüsselter Vault (SQLCipher), ein konfigurierbarer Speicherort, Migration und Backups (später NAS) | fertig |
| `EgressGate`: Modus A/C für alles, was nach außen geht | fertig |
| `ActionGate`: Risikostufen, Prüfer, Limits, Notaus, Audit | fertig |
| Statische Prüfung gegen Netzwerkcode außerhalb der Allowlist | fertig |
| Stimme: Wake Word, STT, Sprecherverifikation, lokales LLM, lokale Stimme | geplant |
| UI (Tauri, Avatar, Dashboard) | geplant |
| Tools (Web, Mail/Kalender, PC, Smart Home) | geplant |
| Lernen (Reflexion, Bandit/RL mit Sicherheits-Reward) | geplant |
| NAS-Gedächtnis-Dienst | geplant |

Details und Fortschritt: [ROADMAP.md](ROADMAP.md)

Zielhardware: Windows 11, NVIDIA RTX 3070 (8 GB VRAM), 31 GB RAM.

## Gedächtnis und Speicherort

Das Gedächtnis ist ein in sich geschlossener „Vault“-Ordner. Der Speicherort steht an genau einer Stelle: `memory.location` in `config.toml`.

```
vault/
  manifest.json   # Schema-Version, Embedding-Modell, Vault-ID
  memory.db       # verschlüsselt (SQLCipher)
  vectors/  episodes/  blobs/
```

Der Schlüssel liegt im Windows Credential Manager, nie im Vault. Hinweis: Eine SQLite-Datei sollte nicht direkt auf einem Netzlaufwerk (SMB/NFS) laufen. Fürs NAS ist ein eigener Gedächtnis-Dienst (`remote:`) vorgesehen; bis dahin gibt es verschlüsselte Backups aufs NAS.

## Entwicklung

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m pytest -q
```

Konfiguration: `config.example.toml` nach `config.toml` kopieren.

```powershell
kushim memory init                          # Vault anlegen
kushim memory info                          # Zustand anzeigen
kushim memory backup                        # Snapshot ins Backup-Ziel
kushim memory migrate --to "local:D:/vault" # Vault verschieben, verifiziert, mit Rollback
```

### Skills, Agents und Routine (Claude Code)

- Skills in `.claude/skills/`: `kushim-add-tool`, `kushim-safety-review`, `kushim-next-phase`, `kushim-routine`
- Agents in `.claude/agents/`: `safety-auditor`, `voice-pipeline-dev`, `ui-builder`
- Autonome Entwicklungsroutine: `/loop /kushim-routine` (siehe [docs/LOOPS.md](docs/LOOPS.md)). Sie arbeitet auf eigenen Branches, fragt bei Unklarheiten per Slack nach und pflegt die Roadmap.

## Status

Frühe Entwicklung. Fundament und Sicherheitsschicht stehen, Stimme, UI und Tools folgen.
