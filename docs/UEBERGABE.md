# Übergabe 2026-10-27 (Abend): Sprach-Brücke zu Claude Code läuft, Freigaben angefangen

Kurzfassung für die nächste Sitzung. Plan: [ROADMAP.md](../ROADMAP.md). Zustand der Routine: [routine-state.md](routine-state.md).
Frühere Übergaben stehen in der Git-Historie dieser Datei.

## Stand in einem Satz
`kushim start` öffnet Claude Code mit dem kushim-Channel im Fenster „kushim-Claude“, kushim hört per Wake Word zu, gibt
Befehle an Claude und liest Claudes Antwort vor. **Live vom Nutzer bestätigt (B7).** Tests: 561 grün.

## Was heute dazukam (je ein Branch, lokal nach master gemerged, nicht gepusht)
| Schritt | Ergebnis |
|---|---|
| A5 | alte Gates (`ActionGate`, `EgressGate`, Werkzeug-Verwaltung) entfernt, vom Nutzer freigegeben; `tests/test_rules.py` sichert `safety/rules.py` |
| B0 | Nutzer-Entscheidung: Channel-Weg und Port nur 127.0.0.1 mit Token |
| B1 | `src/kushim/channel/server.py`: MCP über stdio + HTTP nur 127.0.0.1 mit Token (Python-stdlib statt npm-SDK); Safety-Audit freigegeben, 5 Funde behoben |
| B2 | Werkzeug `sprich`; kushim holt Antworten per `GET /reply` ab (kein zweiter Port) |
| B3 | `channel/bridge.py` (kushim-Seite, nur über `net/loopback.py`) |
| B4 | `voice/claude_chat.py`: „Ich geb's an Claude.“, Antwort vorlesen, Abruf alle 2 s, nach 3 min spätere Ansage |
| B5 | `kushim start`, `channel/launch.py`, `doctor` prüft Claude-Version und Anmeldung, Verknüpfung „kushim start“ im Installer |
| B5+ | Fenster bleibt sichtbar (`cmd /k`, Titel „kushim-Claude“); **Fenster zu = alles aus**, kushim aus = Claude-Sitzung aus; `kushim claude show` holt die Sitzung zurück |
| B6 | „abbrechen“ schickt `kind=cancel` an Claude, Notaus meldet `kind=kill` und lehnt offene Freigaben ab (sofort unterbrechen kann nur Esc) |
| B7 | **Live-Test bestanden** (Nutzer: „Ja er antwortet“) |
| C1 | Channel nimmt Freigabe-Anfragen von Claude an (`permission_request`), reicht sie über `GET /reply` weiter, `POST /permission` beantwortet; kushim beantwortet noch nichts selbst |

Netzwerk-Test strenger: `http.server`, `socketserver`, `asyncio`, `ssl` u. a. nur in ALLOWLIST-Modulen; ALLOWLIST =
`net/loopback.py`, `net/server.py`, `channel/server.py` (B0); Loopback-Client nur von der Brücke benutzt.

## Wichtige Erkenntnisse (Claude Code 2.1.311, aus der installierten `claude.exe` gelesen, ohne Netz)
- Channel: `experimental: {"claude/channel": {}}`, Nachrichten `notifications/claude/channel {content, meta}`; Freigaben:
  `claude/channel/permission`, `…/permission_request {request_id, tool_name, description, input_preview}`, Antwort
  `…/permission {request_id, behavior: allow|deny}`. Einen Unterbrechen-Befehl gibt es nicht.
- Start: `claude --session-id <uuid> --name kushim --strict-mcp-config --mcp-config run/kushim-mcp.json
  --dangerously-load-development-channels server:kushim` (Bestätigungsdialog beim Start).
- Claude Code führt Sitzungen über einen **Hintergrund-Dienst** aus: Fenster zu heißt nicht Sitzung zu.
  `claude stop`/`attach` brauchen die **kurze Job-ID** (erste 8 Zeichen der Sitzungs-ID, siehe `claude agents --json`).

## Aufgeräumt am Ende
Alle kushim-Prozesse gestoppt (Zuhören, Claude-Sitzung `060815a8` per `claude stop`, Channel, Attach-Fenster).
Der Hintergrund-Dienst von Claude Code läuft weiter (trägt andere Sitzungen des Nutzers). `run/channel.json` entfernt.

## Nächste Schritte
1. **C2** sprechbare Beschreibung („Claude möchte den Befehl npm test ausführen. Erlauben?“) aus `bridge.permissions`.
2. **C3** Antwort per Stimme: „ja“ nur bei stark verifizierter Stimme, sonst nichts senden (Terminal-Dialog bleibt).
3. **C4** Sperrliste: Löschen, `git push --force`, Daten senden, Einstellungen nie per Stimme (auch im Channel prüfen).
4. **C0** Freigabe-Leiste der UI an Channel-Freigaben; danach **Phase E** (UI auf Claude Code umstellen).

## Für den Nutzer
- Neu starten mit `kushim start` (der Code von heute wirkt erst nach Neustart). Fenster schließen beendet alles.
- **Z3** noch offen: `py scripts\claude_setup.py --project . --statusline --test-hook` (vorher `--dry-run`).
- Papierkorb leeren, wenn die Ollama-Ordner (~16 GB) endgültig weg sollen.
- Pushen: `master` ist lokal voraus (der Nutzer pusht selbst).
