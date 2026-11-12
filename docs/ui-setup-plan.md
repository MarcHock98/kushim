# Setup in der Oberfläche (beim ersten Start, danach wiederholbar)

Stand 2026-11-12 (angepasst: keine Sprecher-Prüfung, kein lokales Sprachmodell, Claude Code ist das Gehirn).
Das Setup erscheint **beim ersten Start** und ist **jederzeit wiederholbar**. Vier Schritte, **alle überspringbar**.
Backend: `src/kushim/setup/` und `api/setup_api.py` (`setup.*`, `audio.devices`, `safety.*`).

## Grundsätze
1. **Dieselbe Logik wie die Kommandozeile** (`kushim doctor`, `memory init`, `voice level`, `wakewords.toml`, Notaus).
2. **Der Nutzer bestätigt jeden Schritt selbst**, nichts läuft automatisch durch.
3. **Geheimnisse bleiben draußen:** Der Vault-Schlüssel erscheint nie im Fenster oder in der API; die UI verweist auf
   `kushim key export` im eigenen Terminal.
4. **Überspringen schaltet nie Sicherheit ab** (Notaus und Grundregeln gelten immer).

## Zustand
`run/setup-state.json` (nicht im Git): je Schritt `done | skipped | open`. Maßgeblich bleiben echte Fakten (Systemcheck,
Vault vorhanden, eigene `wakewords.toml`); die Datei merkt sich nur "übersprungen" und Bestätigungen des Nutzers.

## Die vier Schritte
1. **Systemcheck und Vault:** Punkte von `kushim doctor` als Ampelliste (Modelle, GPU-Bibliotheken, Pakete, Claude Code
   Version und Anmeldung). Vault anlegen, Schlüssel sichern bestätigen. Übersprungen: kein Gedächtnis.
2. **Mikrofon und Lautsprecher:** Geräte wählen, Pegel messen (wie `kushim voice level`). Der Nutzer bestätigt den Schritt
   selbst. Übersprungen: Windows-Standardgeräte und Standard-Pegel.
3. **Wake Words:** Liste aus `wakewords.toml` mit Schaltern und Empfindlichkeit, Wort hinzufügen/entfernen (mindestens eines
   bleibt aktiv). Übersprungen: Standardwörter.
4. **Sicherheit und Notaus:** Grundregeln kurz erklärt, Notaus ausprobieren und bewusst aufheben.

## Eingeschränkter Modus
| Übersprungen | Folge |
|---|---|
| Vault | kein Gedächtnis (Audit, Feedback, Freigabe-Protokoll) |
| Mikrofon/Lautsprecher | Standardgeräte von Windows |
| Wake Words | Standardwörter aus der Vorlage |
| Sicherheit/Notaus | nichts, er wirkt trotzdem |

Es gibt keine Sprecher-Prüfung: Jede Stimme kann Befehle geben. Freigaben (Claude möchte etwas ausführen) gibt es deshalb nie
per Stimme, nur im Claude-Fenster oder in der Freigabe-Leiste der Oberfläche.
