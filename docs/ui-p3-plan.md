# Plan P3: Live-Arbeit sichtbar machen (Aufträge, Listen, Mails, Dokumente)

Stand 2026-11-12. Teil von `docs/ui-dynamic-plan.md`. **P3a ist gebaut (2026-11-12, vom Nutzer freigegeben); P3b ist offen.** Baut auf P2 auf (`zeige`,
`stage/schema.py`, `stage.get`, `ViewCard.tsx`). Ziel: Wenn Claude Code länger arbeitet, etwas plant oder eine Mail vorlegt,
sieht man das im kushim-Fenster, statt nur einen Satz zu hören.

## 1. Vorschlag: P3 in zwei Teile schneiden

| Teil | Inhalt | Neuer Datenweg? | Risiko |
|---|---|---|---|
| **P3a** | `fortschritt`, `aufgaben` (Liste mit Haken), `zeitplan`, `mail`, `mail-entwurf`, `countdown` | nein, alles kommt als geprüfter Text über `zeige` | gering |
| **P3b** | `dokument` und `diff` (Dateiinhalt und Änderungen live) | ja: Das Backend liest Dateien aus freigegebenen Ordnern | höher, eigener Plan mit Sicherheits-Audit |

Empfehlung: **erst P3a bauen**, P3b danach mit eigenem Detailplan. Grund: P3a braucht keinen neuen Lesezugriff auf Dateien
und kein neues Paket. P3b braucht Pfadprüfung, Größenlimits und einen Prüflauf des `safety-auditor`.

Der Rest dieses Plans beschreibt P3a.

## 2. Grundsätze (unverändert aus P2)
- Die Oberfläche **zeigt nur**. Senden, Schreiben, Anlegen macht allein Claude Code mit seinen eigenen Freigaben.
- Alles ist **Text**: kein HTML, keine Links zum Anklicken, keine Bilder, nichts wird nachgeladen.
- Kein neuer Port, kein Netz, kein neues Paket. Geprüft wird zweimal (Channel-Server und Bridge) in `stage/schema.py`.
- Dieselbe `id` aktualisiert eine Ansicht (so wächst ein Fortschritt), `schliessen` räumt ab, Notaus räumt alles ab.

## 3. Neue Arten und Bausteine

Zwei neue Arten (wählen das Layout): **`auftrag`** und **`mail`**. Die übrigen Bausteine laufen in der Art `antwort`.

| `typ` | Inhalt | Grenzen | Darstellung |
|---|---|---|---|
| `fortschritt` | `schritte: [{text, zustand: offen/laeuft/fertig/fehler}]`, `hinweis?` | ≤ 20 Schritte × 200 Zeichen | Liste mit Symbol **und** Wort je Zustand; der laufende Schritt ist hervorgehoben; Zähler „3 von 7 fertig“ |
| `aufgaben` | `punkte: [{text, erledigt: bool}]` | ≤ 40 × 200 | Liste mit Haken (nur Anzeige, nicht anklickbar) |
| `zeitplan` | `tag: str`, `termine: [{von, bis, titel, ort?}]` (Zeiten als `HH:MM`) | ≤ 30 Termine | Tagesleiste mit Blöcken; Überschneidungen mit Wort „überschneidet sich“ markiert |
| `mail` | `von`, `an?`, `betreff`, `datum?`, `zusammenfassung?`, `text` | Text ≤ 6000 Zeichen | Kopfzeilen, Zusammenfassung oben, Originaltext darunter in fester Breite; fester Hinweis **„Fremder Inhalt, nur Text“** |
| `mail-entwurf` | `an`, `cc?`, `betreff`, `text` | Text ≤ 6000 | Genau so, wie er rausgehen würde; fester Hinweis **„Entwurf, noch nicht gesendet. Gesendet wird nur in Claude Code mit deiner Freigabe.“** |
| `countdown` | `titel`, `ende: ISO-Zeit` | Ende höchstens 24 h entfernt | Restzeit, zählt in der Oberfläche herunter; bei 0 steht „abgelaufen“ |

Zu klären (siehe Abschnitt 7):
- `countdown` ist **nur eine Anzeige**. kushim hat seit Roadmap A3 keine eigenen Timer mehr und klingelt nicht. Ein Wecker
  mit Ton wäre eine neue Fähigkeit von kushim und braucht deine Entscheidung.
- `mail` und `mail-entwurf` zeigen nur, was Claude Code liefert. kushim holt selbst keine Mails und sendet keine.

## 4. Verhalten auf der Bühne
- **`auftrag`**: Der Kern bleibt klein links, rechts der Fortschritt. Claude aktualisiert dieselbe `id` nach jedem Schritt.
  Kommt eine Freigabe-Anfrage, hat die Freigabe-Leiste wie immer Vorrang und steht über der Ansicht.
- **`mail`**: Kopf oben, Text in einer scrollbaren Spalte mit höchstens 70 Zeichen Zeilenlänge.
- Hinweis an Claude in `INSTRUCTIONS` (ein Satz): „Bei Arbeit mit mehreren Schritten zeige den Plan als `fortschritt` und
  aktualisiere ihn; einen Mail-Entwurf zeige vor dem Senden als `mail-entwurf`.“
- **Altes Claude-Panel** (`ClaudePanel.tsx` in der Übersicht): Es ruft API-Typen, die es seit Roadmap A4 nicht mehr gibt, und
  zeigt deshalb nur „nicht verfügbar“. Vorschlag: mit P3a entfernen, die Art `auftrag` ersetzt es. Die Ordner-Verwaltung
  (`FolderManager`) bleibt als eigene Karte in der Übersicht.

## 5. Sicherheit
- Mail-Text ist fremder Inhalt: nur als Text, Steuerzeichen und Richtungs-Umkehrzeichen (RTL-Override) werden im Schema
  entfernt, Adressen bleiben Text.
- Der Entwurf zeigt den **exakten** Text. Stimmt er später nicht mit dem überein, was Claude Code senden will, sieht man das
  in der Freigabe-Anfrage von Claude Code; die Oberfläche gibt selbst nichts frei, was sie nicht schon heute freigibt.
- `countdown`: Die Endzeit wird im Schema geprüft (gültiges Datum, nicht in der Vergangenheit, höchstens 24 h), die
  Oberfläche rechnet nur die Anzeige.
- Keine Änderung an CSP, ALLOWLIST, Tauri-Rechten.

## 6. Tests und Dateien
- **Python**: Schema je Baustein (jede Grenze, falsche Typen, unbekannte Felder, ungültige Zustände und Zeiten,
  Steuerzeichen in Mails), `tools/list` nennt die neuen Arten, Bridge nimmt nur Gültiges.
- **Vitest**: jede Darstellung, Zustand mit Wort, Zähler, Überschneidung, beide festen Hinweise, Countdown mit falscher Uhr
  (abgelaufen), Live-Update eines Fortschritts, nichts ist anklickbar außer „Schließen“.
- **Ansehen**: Mock-Demo um einen Auftrag und eine Mail erweitern, im Browser bei 375, 800 und 1440 px prüfen.
- **Dateien**: `src/kushim/stage/schema.py`, `src/kushim/channel/server.py` (Beschreibung von `zeige`, ein Satz in
  `INSTRUCTIONS`), `ui/src/lib/stage.ts`, `ui/src/components/stage/` (neu: `Progress.tsx`, `Schedule.tsx`, `Mail.tsx`,
  `Countdown.tsx`), `ViewCard.tsx`, `lib/mock.ts`, `styles/app.css`, Tests. Entfällt: `ClaudePanel.tsx` samt Tests (falls
  freigegeben).

## 7. Entscheidungen für dich
1. **Schnitt**: erst P3a (dieser Plan), P3b (Dokument und Diff aus Dateien) später mit eigenem Plan? Empfehlung: ja.
2. **Countdown**: nur Anzeige ohne Ton (Empfehlung), oder ganz weglassen?
3. **Mail**: `mail` und `mail-entwurf` jetzt mitbauen, oder erst, wenn du Claude Code mit einem Mail-Konnektor nutzt?
   Empfehlung: mitbauen, es ist reine Anzeige.
4. **Altes Claude-Panel** entfernen? Empfehlung: ja.

## 8. Stand nach dem Bau von P3a
- Alle vier Empfehlungen wurden übernommen (Schnitt, Countdown ohne Ton, Mail-Ansichten, altes Claude-Panel entfernt).
- Abweichungen vom Plan: Der Mail-Text kommt als `absaetze: [str]` (höchstens 40 Absätze, zusammen 6000 Zeichen) statt als
  ein Feld `text`. Die Endzeit des Countdowns prüft das Schema nur der Form nach (`JJJJ-MM-TTThh:mm[:ss]`, optional mit
  Zone); die Grenze von 24 Stunden setzt die Oberfläche (sonst „Zeit unbekannt“). Grund: `stage/schema.py` darf laut
  `test_no_egress.py` nur eine feste Liste von Standardmodulen laden, `datetime` gehört nicht dazu, und diese Liste
  ändert nur der Nutzer.
- Die Bausteine liegen in einer Datei `ui/src/components/stage/Live.tsx`; die Ordner-Verwaltung steht in `FolderPanel.tsx`.
- Geprüft: 586 Python-Tests, 92 UI-Tests, Mock-Demo im Browser bei 375, 800 und 1440 px. Nicht geprüft: echtes
  Tauri-Fenster, echter Aufruf durch Claude Code über den Channel.
