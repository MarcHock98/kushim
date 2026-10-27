# Übergabe 2026-10-27: Phase A aufgeräumt, Token-Werkzeuge fertig

Kurzfassung für die nächste Sitzung. Plan und Schritte: [ROADMAP.md](../ROADMAP.md). Zustand der Routine:
[routine-state.md](routine-state.md). Vorige Übergabe (Neuausrichtung, 2026-10-26) steht in der Git-Historie dieser Datei.

## Richtung (unverändert)
kushim ist die lokale Sprach-Vorderseite für **Claude Code**: Wake Word, Sprecherprüfung, Whisper, Piper bleiben lokal;
Claude Code ist die einzige KI. kushim selbst geht nie ins Internet (nur 127.0.0.1), Audio verlässt nie den PC.

## Was in dieser Sitzung entstand (Loop `/kushim-routine`, je ein Branch, lokal gemerged)
| Schritt | Ergebnis |
|---|---|
| A1 | alte Sprachbefehle (Werkzeuge, Timer, Notizen, Wake Words) und `approvals_api`/`dashboard_api` entfernt |
| A2 | Websuche, Recherche, `net/web.py`, `claude_cli/ask.py` entfernt; ALLOWLIST ohne `net/web.py`, Test sperrt Internet-Module; `sanitize.py` behalten (für C1/C2) |
| A3 | `timers.py` entfernt (Daten des Nutzers unangetastet) |
| A4 | alte Claude-Steuerung (`claude -p`-Läufe) entfernt; `base.py`, `folders.py` bleiben; Test: kushim startet keine Claude-Läufe |
| A6 | Ollama/lokales Modell entfernt (`llm/`, Launcher, `kushim start/llm/behavior`, Installer-Teil); `talk` antwortet bis B4 „Ich bin noch nicht mit Claude verbunden.“ |
| A7 | `learning/` entfernt, README und `kushim help` auf Claude Code umgestellt; `net/loopback.py` **bewusst behalten** (braucht B3) |
| Z4 | Statuszeile `scripts/statusline.py` (Modell, Kontext, Abo-Grenzen 5h/7d) |
| Z5 | Hook `scripts/trim_test_output.py` kürzt lange Testausgaben, setzt nie eine Freigabe |

Tests: **536 grün** (Windows, lokal). Sicherheits-Review je Schritt: freigegeben, Sicherheitstests nur strenger gefasst.

## Für den Nutzer zu tun
1. **A5 entscheiden:** `ActionGate`, `EgressGate`, `approvals.py`, `tools/`, `tools_api`/`tasks_api` wie in der Roadmap entfernen
   (Empfehlung) oder Gates behalten? `safety/rules.py`, Notaus und `test_no_egress.py` bleiben in jedem Fall.
2. **B0 entscheiden:** Channel-Weg (`--dangerously-load-development-channels`, Research Preview) und lokaler Port nur auf
   127.0.0.1 mit Token. Davon hängt die ganze Phase B ab.
3. **Z3 + Z4 + Z5 einrichten** (auf dem PC, ändert `~/.claude`, legt vorher Sicherungen an), danach Claude Code neu starten:
   `py scripts\claude_setup.py --project . --statusline --test-hook` (vorher mit `--dry-run` ansehen).
4. **Live prüfen:** `kushim talk` mit Mikrofon (antwortet jetzt nur mit dem festen Hinweis), Statuszeile und Hook in Claude Code.
5. **Aufräumen (optional):** `tools\ollama`, `models\ollama` (mehrere GB) und die Desktop-Verknüpfung `kushim.lnk` werden nicht
   mehr gebraucht.

## Nächster Schritt für Claude
Nach A5: A5 umsetzen. Nach B0: B1 (Channel-Prototyp `channel/`, Text per `POST 127.0.0.1` mit Token, Test mit `curl`),
dann B2–B4 (Antwort-Werkzeug `sprich`, Brücke `bridge/` über `net/loopback.py`, in `Pipeline.chat` statt `not_connected`).
Die UI zeigt Freigabe-Leiste, Übersicht und Claude-Bereich bis C0/E als „nicht verfügbar“ (C0 in der Roadmap ergänzt).

## Hinweise
- Wissen über Claude Code ohne Netz: Beschreibungen stecken in der installierten `claude.exe` (2.1.310), mit Python/`mmap` lesen.
- Windows: Ausgaben für Claude Code als UTF-8-Bytes schreiben; Tests mit Git Bash, nicht der WSL-`bash` aus System32.
- Schreib-Skripte per Heredoc verschlucken Backslashes (dreimal passiert): Edit-Werkzeug nehmen.
