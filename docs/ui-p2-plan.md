# Plan P2: Claude Code zeigt Inhalte (`zeige`)

Stand 2026-11-12. Teil von `docs/ui-dynamic-plan.md`. Ziel: Claude Code kann neben dem Vorlesen (`sprich`) etwas **zeigen**.
Die Bühne wechselt dann in den Zeige-Modus: Der Kern rückt zur Seite, der Inhalt kommt in die Mitte. Vier Arten:
`antwort`, `rechnung`, `markt`, `recherche`. Noch nicht gebaut, zur Freigabe.

## 1. Weg der Daten

```
Claude Code ──tools/call "zeige"──▶ Channel-Server (stdio, prüft) ──GET /reply──▶ Bridge (kushim talk, prüft erneut)
     └─ sprich (kurz vorlesen)                                     └─ "views" neben "texts"     └─ ViewStore (letzte 20)
                                                                                                   │
UI ◀── stage.get {since} ── API (127.0.0.1, Token) ◀──────────────────────────────────────────────┘
```

- **Kein neuer Port, kein Netz.** `zeige` läuft über denselben Channel wie `sprich`. Die Antwort auf `GET /reply` bekommt
  ein Feld `views`. Die Bridge legt sie wie die Freigaben in eine eigene Liste (`bridge.views`). Die Signatur von `fetch`
  bleibt gleich, deshalb muss `voice/claude_chat.py` (Bereich der anderen Sitzung) nicht geändert werden.
- **Zweimal prüfen**: im Channel-Server (Claude bekommt eine kurze Fehlermeldung, wenn etwas nicht passt) und in der Bridge
  (Verteidigung in der Tiefe). Gemeinsames Modul `src/kushim/stage/schema.py`, nur Standardbibliothek.
- **Notaus**: Wie bei `texts` gibt `GET /reply` dann `423` zurück, es werden keine Ansichten weitergegeben. Die UI räumt die
  Bühne bei Notaus ab.
- Neuer API-Typ **`stage.get`** (`since` → neue/aktualisierte Ansichten), registriert über `extra(core, store)` in `cli.py`
  (zwei Zeilen; `kushim serve` ohne Sprachdienst kennt ihn nicht, die UI zeigt dann einfach nichts).
- Hinweis an Claude in `INSTRUCTIONS`: „Wenn Sehen hilft (Rechenweg, Zahlen, Tabellen, mehrere Quellen), rufe zusätzlich
  `zeige` auf; `sprich` bleibt kurz.“

## 2. Das Werkzeug `zeige`

```json
{ "id": "mathe-1", "art": "rechnung", "titel": "Quadratische Gleichung",
  "bausteine": [ { "typ": "...", ... } ], "stand": "2026-11-12 14:05", "schliessen": false }
```

| Feld | Regel |
|---|---|
| `id` | `[a-z0-9-]{1,40}`; dieselbe `id` **aktualisiert** die Ansicht |
| `art` | `antwort`, `rechnung`, `markt`, `recherche` (wählt das Layout) |
| `titel` | Text, ≤ 120 Zeichen |
| `bausteine` | 1 bis 12 Bausteine aus der Liste unten |
| `stand` | Text ≤ 40 (Pflicht bei `markt`, sonst optional) |
| `schliessen` | `true` räumt die Ansicht ab |
| Gesamtgröße | ≤ 48 KB JSON |

**Bausteine** (nur diese; alles Text, nie HTML):

| `typ` | Inhalt | Grenzen |
|---|---|---|
| `text` | `absaetze: [str]` | ≤ 12 × 1200 Zeichen |
| `liste` | `punkte: [str]`, `nummeriert: bool` | ≤ 30 × 300 |
| `formel` | `tex: str` (KaTeX) | ≤ 500 Zeichen |
| `schritte` | `[{text, tex?}]` | ≤ 20 Schritte |
| `ergebnis` | `text?`, `tex?` | groß hervorgehoben |
| `kennzahlen` | `[{name, wert, einheit?, aenderung?, richtung?: auf/ab/gleich}]` | ≤ 8; Richtung als ▲▼ **und** Wort |
| `tabelle` | `spalten: [str]`, `zeilen: [[str|zahl]]` | ≤ 8 Spalten × 50 Zeilen |
| `diagramm` | `form: linie/balken`, `x_titel`, `y_titel`, `reihen: [{name, punkte: [[x, y]]}]` | ≤ 4 Reihen × 500 Punkte, Zahlen endlich |
| `aussagen` | `[{text, quellen: [nr]}]` | ≤ 20; Nummern müssen in `quellen` existieren |
| `widerspruch` | `[{text, quellen: [nr]}]` | wo sich Quellen widersprechen |
| `quellen` | `[{nr, titel, adresse}]` | ≤ 20; Adresse **nur als Text**, kein Link |
| `hinweis` | `text` | z. B. Einschränkungen |

## 3. Ansichten je Art (Zeige-Modus, Kern klein links)

| Art | Aufbau |
|---|---|
| `antwort` | Titel, Text/Liste groß und ruhig lesbar (max. 70 Zeichen Zeilenlänge) |
| `rechnung` | Aufgabe (Text/Formel) oben, **nummerierte Schritte** mit Erklärung und KaTeX-Formel, **Ergebnis** groß in Cyan |
| `markt` | Kennzahl-Kacheln oben (▲ steigt / ▼ fällt, Wort + Farbe), Diagramm groß, Tabelle darunter, „Stand: …“ gut sichtbar, fester Hinweis **„Nur zur Information, keine Anlageberatung.“** |
| `recherche` | Zusammenfassung, Aussagen mit hochgestellten Quellennummern, Kasten „Quellen widersprechen sich“ falls vorhanden, Quellenliste rechts (unter 1000 px darunter) |

- **Dialog bleibt Dialog**: Nur `zeige` (und die Systemfrage, siehe Entscheidung 3) schaltet um.
- **Live**: Dieselbe `id` ersetzt den Inhalt ohne neue Fahrt (z. B. eine Recherche, die wächst).
- **Mehrere Ansichten**: Die neueste ist offen, die übrigen als Reiter darüber (höchstens 5).
- **Übersicht**: Die tote Karte „Ergebnisse“ (alter Typ `dashboard.get`) wird zur Liste **„Gezeigt“**. Ein Klick öffnet die
  Ansicht wieder auf der Bühne.
- Esc, Schließen oder die nächste Frage führen zurück zum Dialog.

## 4. Pakete und Regeln
- **KaTeX 0.16.11** (MIT, ~4 MB entpackt, im Build ~280 KB JS + Schriften als lokale Dateien). Aufruf mit `katex.render`
  in ein Element (DOM, **kein** `innerHTML`), `trust: false` (kein `\href`, `\url`, `\html…`), `throwOnError: false`, `maxSize`,
  `maxExpand`. Fehlerhafte Formel → als Text gezeigt mit dem Wort „Formel fehlerhaft“.
- Diagramme: eigenes SVG, kein Paket. Achsen, Gitter in `--line`, Reihen in `--arc`, `--amber`, dann gestrichelt (Unterscheidung nicht nur über Farbe).
- CSP bleibt unverändert. KaTeX-Schriften kommen von `'self'`, Inline-Styles von KaTeX deckt das vorhandene `style-src 'unsafe-inline'` ab.
- `test_ui_rules.py`: Ein Test sichert ab, dass `katex` nur mit `trust: false` aufgerufen wird.

## 5. Tests
- **Python**: Schema (jede Grenze, falsche Typen, unbekannte Bausteine/Felder, Quellennummern), Channel-Werkzeug
  (`tools/list` enthält `zeige`, Fehlertexte), `GET /reply` mit `views`, Notaus → 423, Bridge nimmt nur Gültiges, `stage.get`.
- **Vitest**: jede Art rendert, nur Text (kein `<b>` aus Eingaben), KaTeX-Fehler als Text, Diagramm-SVG mit Punkten,
  Markt-Hinweis und Stand, Widerspruchs-Kasten, Live-Update gleicher `id`, Reiter, Esc/Schließen, Notaus räumt ab, Übersicht „Gezeigt“.
- Mock: Beispiele für alle vier Arten (`?mock&demo`), Screenshots bei 375/800/1440 px.

## 6. Dateien
`src/kushim/stage/schema.py`, `src/kushim/stage/store.py`, `src/kushim/api/stage_api.py`, `channel/server.py` (Werkzeug,
`views`), `channel/bridge.py` (`views`), `cli.py` (2 Zeilen), Tests; UI: `components/stage/*` (je Art und Baustein),
`App.tsx`, `lib/mock.ts`, `styles/app.css`, Tests.
