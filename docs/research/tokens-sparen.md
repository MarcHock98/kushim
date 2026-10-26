# Recherche: Weniger Tokens in Claude Code verbrauchen (Stand 2026-10-26)

Ziel des Nutzers: sparsam arbeiten, **über alle Projekte**, und dabei keine Daten nach außen.
Hauptquelle: offizielle Doku [Manage costs effectively](https://code.claude.com/docs/en/costs). Ergänzend:
[KDnuggets](https://kdnuggets.com/7-practical-ways-to-reduce-claude-code-token-usage),
[Composio](https://composio.dev/blog/ways-to-cut-token-consumption-in-claude-code),
[Analytics Vidhya](https://www.analyticsvidhya.com/blog/2026/05/tips-for-claude-code-token-saving/).

## Warum Tokens verloren gehen
- **Jede Anfrage schickt den ganzen Verlauf mit.** Werkzeug-Ergebnisse (gelesene Dateien, Testausgaben) bleiben im Kontext
  und kosten bei jeder weiteren Nachricht (aus dem Cache günstiger, aber nicht gratis).
- **Pause länger als die Cache-Lebensdauer:** die nächste Nachricht verarbeitet den ganzen Kontext neu.
- **`/compact` ist selbst eine große Anfrage**; `/clear` kostet nichts.
- **CLAUDE.md wird bei jeder Anfrage mitgeschickt** (unter 200 Zeilen halten); Skills laden nur Name und Beschreibung, den
  Rest erst bei Bedarf.
- **Hintergrund:** Schleifen (`/loop`, geplante Aufgaben), Subagenten, Agent-Teams (~7-fach), Ziel-Nachfragen,
  Vorschläge für den nächsten Prompt.

## Was wirkt (nach Nutzen sortiert)
| Maßnahme | Wie |
|---|---|
| Zwischen Aufgaben neu anfangen | `/clear` (vorher `/rename`, später `/resume`) |
| Passendes Modell und Denkaufwand | Sonnet für das Meiste, Opus nur für schwere Planung; `/effort` senken für einfache Aufgaben; Subagenten mit `model: haiku` |
| Gezielt fragen | „Validierung in `login()` in auth.ts“ statt „verbessere den Code“ |
| Code-Graph statt Dateien lesen | **Graphify** (siehe unten) oder Code-Intelligence-Plugins (LSP) für typisierte Sprachen |
| Ausgaben vorfiltern | Hook, der Testausgaben auf Fehlschläge kürzt; `grep`/`head` statt ganzer Logs |
| Laute Arbeit auslagern | Subagent liest Logs/Tests, gibt nur eine Zusammenfassung zurück |
| CLAUDE.md schlank | Spezielles in Skills verschieben; Abschnitt „Compact instructions“ |
| Wenige MCP-Server | Ungenutzte in `/mcp` abschalten; CLI-Werkzeuge sind sparsamer |
| Früh korrigieren | Esc, `/rewind`; Planmodus (Shift+Tab) vor großen Änderungen |
| Messen | `/usage` (mit Empfehlungen, Taste `f` wendet sie an), `/context`, Statuszeile |

## Graphify ([safishamsi/graphify](https://github.com/safishamsi/graphify), Apache-2.0, PyPI `graphifyy` 0.9.96)
- Baut aus dem Projekt einen Wissensgraphen. **Code wird lokal mit tree-sitter zerlegt: 0 Tokens, kein Netz.**
  Claude fragt den Graphen (`graphify query/explain/path`), statt viele Dateien zu lesen.
- Geprüft am kushim-Repo mit gesperrtem Netzwerk: 172 Dateien, 2458 Knoten, 6354 Kanten, 135 Gruppen, „Token cost: 0“.
  Beispiel „Wie prüft die Pipeline den Sprecher?“: Antwort ~6,6 KB statt 17 KB für die drei Quelldateien; der größte Gewinn
  ist, dass Claude die richtigen Stellen findet, statt zu suchen. Die Werbezahl „71-fach weniger“ gilt für große, gemischte
  Sammlungen und ist nicht unabhängig geprüft.
- **Netz/Datenschutz (Quellcode gelesen):** Kern, Abfrage-Server (`graphify.serve`, MCP über stdio) und Abfrageprotokoll
  (standardmäßig aus) sind lokal. Netz nur bei ausdrücklichen Befehlen: `graphify add <url>`, `graphify clone <github-url>`,
  YouTube/yt-dlp, und `--backend` (direkte APIs von Gemini, OpenAI, Kimi, DeepSeek, Anthropic). **Gefahr:** ist ein
  API-Schlüssel eines fremden Anbieters gesetzt, nimmt Graphify ihn automatisch für Beschriftungen/Dokumente. Das
  Einrichtungsskript entfernt diese Schlüssel aus der Umgebung von Graphify. `graph.html` lädt beim Öffnen eine
  Bibliothek von unpkg.com; das Skript löscht die Datei.
- Dokumente/Bilder (nicht Code) werden im Skill über Claude-Code-Subagenten ausgewertet: das geht an Anthropic wie jede
  Claude-Code-Arbeit, kostet aber Tokens; für Code nicht nötig.

## Umsetzung für alle Projekte
`scripts/claude_setup.py` (wiederholbar, mit Sicherungen, `--dry-run`):
1. Graphify in fester Version installieren und als Skill anmelden (`graphify install`).
2. `~/.claude/settings.json`: `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` (keine Telemetrie, Fehlerberichte,
   Auto-Updates), `GRAPHIFY_QUERY_LOG_DISABLE=1`.
3. `~/.claude/CLAUDE.md`: kurzer Regelblock (Graph zuerst, gezielt lesen, Ausgaben filtern, Subagenten, kurz antworten,
   keine Daten nach außen, Compact instructions).
4. Pro Projekt mit `--project PFAD`: Graph bauen, `graphify claude install --project` (Regeln + Such-Hooks, die vor
   grep/Lesen auf den Graphen hinweisen), Git-Hooks halten den Graphen nach Commits aktuell, `graphify-out/` ignorieren.

Offen: Statuszeile mit Kontext-Füllstand und Kosten; Hook zum Kürzen von Testausgaben (Beispiel in der offiziellen Doku).
