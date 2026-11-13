# Plan P3b: Dokumente und Änderungen aus Dateien zeigen

Stand 2026-11-13. Teil von `docs/ui-dynamic-plan.md`, Fortsetzung von `docs/ui-p3-plan.md`. **Noch nicht gebaut, zur Freigabe.**
Ziel: Wenn Claude Code an einer Datei arbeitet, sieht man im kushim-Fenster den Text und was sich geändert hat.

## 1. Zwei Wege, einer davon ohne neuen Dateizugriff

| Weg | Wer liefert den Inhalt | Neuer Zugriff von kushim | Aufwand | Risiko |
|---|---|---|---|---|
| **A: Claude schickt den Text** | Claude Code über `zeige` (wie bisher alles) | keiner | klein | gering |
| **B: kushim liest die Datei** | Das Backend liest aus einem freigegebenen Ordner | ja: lesender Dateizugriff | mittel | höher, Audit nötig |

**Empfehlung: Weg A.** Claude Code hat die Datei ohnehin gelesen und kennt den Diff. kushim bekommt damit keine neue
Fähigkeit, und es bleibt bei der Regel „kushim zeigt nur, was Claude schickt“. Der Nachteil: Der Inhalt ist auf die
Größe einer Ansicht begrenzt (48 KB), lange Dateien kommen als Ausschnitt.

Weg B wäre nur nötig, wenn du ganze große Dateien oder ein automatisches Neuladen bei jeder Änderung willst. Er steht
unten als Abschnitt 6, damit du vergleichen kannst.

## 2. Weg A: zwei neue Bausteine

Neue Art **`dokument`** (wählt das Layout: Inhalt breit, Gliederung als schmale Spalte).

| `typ` | Inhalt | Grenzen | Darstellung |
|---|---|---|---|
| `dokument` | `name` (Dateiname als Text), `ausschnitt?` (z. B. „Zeilen 40 bis 120“), `zeilen: [str]`, `gliederung?: [str]` | ≤ 400 Zeilen × 400 Zeichen | Text in fester Breite mit Zeilennummern; Gliederung daneben (unter 1000 px darüber) |
| `aenderung` | `name`, `bloecke: [{kopf?, zeilen: [{art: gleich/neu/weg, text}]}]`, `zusammenfassung?` | ≤ 20 Blöcke, zusammen ≤ 400 Zeilen | Diff: neue Zeilen mit „+“ und Farbe, entfernte mit „−“ und Farbe, Zähler „12 neu, 3 entfernt“ |

- Jede Zeile ist **Text**. Es gibt keine Syntax-Hervorhebung über ein Paket, kein HTML, keine Links.
- `name` ist nur eine Beschriftung. kushim öffnet damit nichts und prüft keinen Pfad.
- Dieselbe `id` aktualisiert die Ansicht: So wächst ein Dokument oder ein Diff, während Claude arbeitet („live“ heißt
  hier: nach jedem Schritt von Claude, nicht bei jedem Tastendruck).
- Fester Hinweis unter jeder `aenderung`: **„Anzeige von Claude. Ob die Änderung geschrieben wird, entscheidest du in
  Claude Code.“**

## 3. Sicherheit (Weg A)
- Kein Dateizugriff, kein neuer API-Typ, kein neues Paket, keine Änderung an CSP, ALLOWLIST oder Tauri-Rechten.
- Dateiinhalte können Geheimnisse enthalten (Token, Schlüssel). Sie stehen dann im Fenster, weil Claude sie geschickt
  hat. Dagegen: ein Satz in `INSTRUCTIONS` („zeige keine Dateien mit Zugangsdaten, keine `.env`, keine Schlüssel“) und
  eine einfache Sperre im Schema für `name` (`.env`, `*.pem`, `*.key`, `id_rsa*`, `credentials*`, `run/*.json`). Das ist
  ein Netz, kein Beweis: Der Inhalt selbst wird nicht nach Geheimnissen durchsucht.
- Steuerzeichen und Richtungs-Umkehrzeichen werden wie bei Mails entfernt; Einrückung bleibt erhalten (dafür eine eigene
  Textprüfung, die führende Leerzeichen und Tabs nicht zusammenzieht).
- Ansichten liegen nur im Speicher des Sprachdienstes (letzte 20), nicht im Vault.

## 4. Tests und Dateien
- **Python**: Schema (Grenzen, Arten der Zeilen, gesperrte Namen, Einrückung bleibt, Steuerzeichen weg), `tools/list`.
- **Vitest**: Zeilennummern, „+“ und „−“ als Zeichen **und** Farbe, Zähler, fester Hinweis, Eingaben bleiben Text,
  Live-Update, nichts anklickbar außer „Schließen“.
- **Ansehen**: Mock-Demo um ein Dokument und einen Diff erweitern, im Browser bei 375, 800 und 1440 px.
- **Dateien**: `src/kushim/stage/schema.py`, `src/kushim/channel/server.py` (Beschreibung, ein Satz), `ui/src/lib/stage.ts`,
  neu `ui/src/components/stage/Doc.tsx`, `ViewCard.tsx`, `lib/mock.ts`, `styles/app.css`, Tests.

## 5. Was Weg A nicht kann
- Ganze Dateien über etwa 400 Zeilen (nur Ausschnitte).
- Neuladen, ohne dass Claude etwas schickt.
- Vorher/Nachher-Vergleich, den kushim selbst berechnet (den Diff liefert Claude).

## 6. Zum Vergleich: Weg B (kushim liest selbst)
Neuer API-Typ `file.read` im Backend, nur für Ordner aus `claude_folders`:
- Pfad lexikalisch gegen den Ordner prüfen, dann `resolve()` und erneut prüfen (keine Verknüpfungen nach außen, kein UNC).
- Nur Textdateien von einer Liste von Endungen, Größenlimit (z. B. 256 KB), nie `.env`, Schlüssel, `.git/`, `run/`.
- Diff über `git diff` im Ordner (ein Unterprozess, versteckt, mit Zeitlimit), nur lesend.
- Die Oberfläche fragt nur ab, was Claude per `zeige` benannt hat (`{typ: "datei", ordner, pfad}`), nie freie Pfade.
- Pflicht: Prüflauf des `safety-auditor` vor dem Mergen, weil kushim damit erstmals selbst Dateien des Nutzers liest und
  an die Oberfläche gibt.

## 7. Entscheidungen für dich
1. **Weg A** (Claude schickt Text und Diff; Empfehlung) oder **Weg B** (kushim liest Dateien, mit Audit)?
2. Sperre für Dateinamen mit Zugangsdaten wie in Abschnitt 3 beschrieben? Empfehlung: ja.
3. Reichen 400 Zeilen je Ansicht? Mehr geht nur, wenn die Grenze von 48 KB je Ansicht angehoben wird.
