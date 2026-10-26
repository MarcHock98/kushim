# Übergabe 2026-10-26: Neuausrichtung kushim

Kurzfassung für die nächste Sitzung. Plan und Schritte: [ROADMAP.md](../ROADMAP.md). Alte Roadmap: [ROADMAP-v1.md](ROADMAP-v1.md).

## Neue Richtung (Entscheidungen des Nutzers)
- **Ziel:** lokaler „Jarvis“ als Sprach-Vorderseite für **Claude Code**. Claude Code ist die **einzige KI**; kein lokales
  Modell (kein Ollama o. ä.). kushim reicht nur weiter: Stimme → Text → Claude Code → Text → Stimme.
- **Bleibt:** Wake Word, Sprecherprüfung, Whisper (lokal), Piper-TTS, Notaus, Vault (Stimmprofil).
- **Fliegt raus (Phase A, noch nicht gemacht):** Ollama/LLM, Web/Recherche, Timer/Notizen, alte Claude-Steuerung, Tools/Gates.
- **Freigaben per Stimme:** Wenn Claude Code eine Berechtigung braucht, liest kushim sie vor; „ja“ nur bei sicher
  erkannter Stimme; gefährliche Aktionen nur im Terminal.
- **Oberfläche:** zunächst Claude Code selbst (Verlauf, `/model`, `/usage`); eigenes Fenster optional (Phase E).
- **Datenschutz:** Alle Server, die kushim mitbringt, laufen nur auf 127.0.0.1 und senden nichts nach außen. Skills,
  Agents und MCP-Server im Projekt nutzen kein Web, kein Slack, keine Konnektoren. Einzige Verbindung nach außen:
  Claude Code selbst zu Anthropic. Telemetrie von Claude Code aus (`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`).
- **Token sparen über alle Projekte:** Graphify plus globale Regeln über `scripts/claude_setup.py`.

## Was in dieser Sitzung entstand
| Datei | Inhalt |
|---|---|
| `ROADMAP.md` | Roadmap v2: Datenschutz-Regeln, Querschnitt Token (Z1–Z5), Phasen A–E in kleinen Schritten |
| `docs/research/jarvis-projekte.md` | Vergleich fertiger Projekte; Fund: **Claude Code Channels** mit Freigabe-Weiterleitung |
| `docs/research/tokens-sparen.md` | Offizielle Spar-Tipps, Graphify geprüft (Quellcode, Offline-Test) |
| `scripts/claude_setup.py` + Tests | Graphify (fest 0.9.96) + globale Einstellungen + Token-Regeln, `--project`, `--dry-run` |
| `.claude/settings.json` | Projekt: Telemetrie aus, Konnektoren gesperrt, keine automatischen Projekt-MCP-Server |
| `.claude/skills/kushim-routine/SKILL.md` | ohne Slack und Web-Recherche; Fragen lokal im State |
| `tests/test_no_egress_config.py` | prüft Skills, Agents, `.mcp.json`, Einstellungen auf Datenabfluss |

Tests: 932 grün, 1 Fehlschlag nur in der Cloud-Umgebung (`test_audio`, PortAudio fehlt dort), 3 übersprungen.

## Für den Nutzer zu tun
1. **GitHub neu verbinden**, damit gepusht werden kann: https://claude.ai/connect-github (Claude-GitHub-App für
   `MarcHock98/kushim` freigeben). Bis dahin liegen alle Commits nur lokal in der Cloud-Sitzung.
2. **B0 entscheiden:** Channel-Weg (Start mit `--dangerously-load-development-channels`, Research Preview) und lokaler
   Port nur 127.0.0.1 mit Token zwischen kushim und Channel.
3. **Z3:** auf dem PC `py scripts\claude_setup.py --project .` ausführen (vorher `--dry-run` zum Ansehen), danach
   Claude Code neu starten.

## Nächster Schritt für Claude
Nach B0: Phase A1 (alte Sprachbefehle für Werkzeuge entfernen), dann A2–A7, dann B1 (Channel-Prototyp mit `curl` testen).

## Offene Punkte / Hinweise
- Eigene Channels laufen nur in einer interaktiven Sitzung, nicht mit `claude -p`; Freigabe-Weiterleitung erst ab
  Claude Code v2.1.234.
- Graphify: nie API-Schlüssel fremder Anbieter setzen (Graphify würde sie automatisch nutzen); `graph.html` nicht öffnen
  (lädt Code von unpkg.com), das Skript löscht die Datei.
- Hooks im Cloud-Container einzurichten wurde blockiert; die Projekt-Verbindung mit Graphify macht das Skript auf dem PC.
