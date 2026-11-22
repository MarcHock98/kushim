# Plan P6: Lernen, Anleitungen, Vergleiche, Zeitstrahl, Übersetzung, Diagramme

Stand 2026-11-13. Teil von `docs/ui-dynamic-plan.md`, Fortsetzung von P3 bis P4. **Gebaut am 2026-11-22 (P6a und P6b) nach den Empfehlungen aus Abschnitt 7.**
Ziel: Die restlichen Anwendungsfälle des Katalogs (Abschnitte A und E) zeigen, dazu Diagramme wie Abläufe und Mindmaps.
P6 braucht **keinen** Dateizugriff von kushim und **kein neues Paket** (empfohlen).

## 1. Vorschlag: P6 in zwei Teile schneiden

| Teil | Bausteine | Aufwand | Besonderheit |
|---|---|---|---|
| **P6a** | `vergleich`, `zeitstrahl`, `gegenueber`, `lernkarten`, `quiz`, `anleitung` | mittel, wie P3a | erste Bausteine mit **Bedienelementen**, die nur die Anzeige ändern (Abschnitt 3) |
| **P6b** | `netz` (Ablauf, Baum, Mindmap) | größer | braucht eine Anordnung der Knoten (eigener kleiner Algorithmus, Abschnitt 4) |

Empfehlung: **erst P6a**, dann P6b. Alles in P6 läuft wie bisher: Claude Code schickt geprüftes JSON über `zeige`, kushim zeigt.

## 2. P6a: die Bausteine

Zwei neue Arten: **`lernen`** (Lernkarten, Quiz, Anleitung) und **`netz`** (erst P6b). `vergleich`, `zeitstrahl` und `gegenueber`
laufen in den vorhandenen Arten `antwort` und `recherche`. Neue Bausteine sind überall einsetzbar, die Art wählt nur Beschriftung und Layout.

| `typ` | Inhalt | Grenzen | Darstellung |
|---|---|---|---|
| `vergleich` | `optionen: [str]` (2 bis 5), `kriterien: [{name, werte: [str\|zahl]}]`, je Option `vorteile?` und `nachteile?: [str]`, `fazit?` | ≤ 15 Kriterien, Texte ≤ 200 | Tabelle mit einer Spalte je Option; darunter je Option Vor- und Nachteile als Listen mit den Wörtern **„dafür“** und **„dagegen“** |
| `zeitstrahl` | `ereignisse: [{zeit, titel, text?}]`, `einheit?` | ≤ 40 Ereignisse; `zeit` ist Text („1789“, „März 2020“) | **Senkrechte Liste mit Linie** (auch am Handy lesbar), Zeit links, Titel und Text rechts; in Reihenfolge, wie Claude sie schickt |
| `gegenueber` | `sprachen: [von, nach]` (Text ≤ 20), `paare: [{original, uebersetzung}]` | ≤ 40 Paare | zwei Spalten nebeneinander (am Handy untereinander), `dir="auto"` je Text, damit rechts-nach-links-Schrift richtig steht |
| `lernkarten` | `karten: [{frage, antwort}]` | ≤ 30 Karten | eine Karte groß: Frage, Knopf **„Antwort zeigen“**, dann Antwort und **„gewusst“** / **„nochmal“**; Zähler „Karte 3 von 12“; am Ende eine Zusammenfassung |
| `quiz` | `fragen: [{frage, optionen: [str], richtig: Zahl, erklaerung?}]` | ≤ 20 Fragen, 2 bis 5 Optionen | Frage als Auswahlliste (Radio), Knopf **„Prüfen“**, Rückmeldung in **Worten** („richtig“ / „falsch, richtig ist …“) mit Erklärung; Ergebnis am Ende |
| `anleitung` | `schritte: [{titel, text, sekunden?}]`, `aktuell?: Zahl` | ≤ 30 Schritte | **ein Schritt groß**, „Weiter“ und „Zurück“ (Knöpfe und Pfeiltasten), Fortschritt „Schritt 2 von 8“, Gesamtliste aufklappbar; Timer siehe Abschnitt 3 |

## 3. Wichtig: Bedienelemente, die nur die Anzeige ändern

Bisher war jede Ansicht reine Anzeige (nichts außer „Schließen“ anklickbar). `lernkarten`, `quiz` und `anleitung` brauchen Knöpfe.
Regeln, damit das sicher und unauffällig bleibt:
- Ein Klick ändert **nur den Zustand der Ansicht im Fenster** (welche Karte, welche Antwort gewählt). Er ruft **nie** die API auf,
  sendet nichts an Claude und schreibt nichts in den Vault. Ein Test prüft das (gesendete Nachrichten bleiben gleich).
- **Ergebnisse werden nicht gespeichert** (kein Lernfortschritt über das Fenster hinaus). Schließen oder eine neue Ansicht setzt alles zurück.
- **Per Stimme**: „weiter“, „nächste Frage“, „Antwort“ gehen wie jede Spracheingabe an Claude. Claude kann dieselbe Ansicht mit
  derselben `id` aktualisieren (`aktuell` bei der Anleitung, die nächste Karte beim Lernen). So funktionieren Stimme und Klick nebeneinander.
- **Die Lösung steckt in den Daten**: Bei Lernkarten und Quiz kennt die Ansicht die richtigen Antworten schon, man könnte sie im
  Fenster nachsehen. Für Lernen ist das üblich und unschädlich. Wer Fragen von Claude einzeln und geheim gestellt bekommen will,
  nutzt das Gespräch (Claude fragt per `sprich`, du antwortest per Stimme) statt dieser Bausteine.
- Alles bleibt mit Tastatur bedienbar, Zustände stehen als Wort da, nie nur als Farbe. Bei „weniger Bewegung“ gibt es keine Animation (kein Umdrehen der Karte).

**Timer in der Anleitung** (`sekunden` je Schritt): Ein Knopf „Timer starten“ zeigt die Restzeit wie der `countdown` (nur Anzeige).
**Ohne Ton**, wie beim Countdown. Ein Ton wäre eine neue Fähigkeit von kushim (Klang abspielen) und ist deine Entscheidung (Abschnitt 7).

## 4. P6b: `netz` (Ablauf, Baum, Mindmap)

| Feld | Regel |
|---|---|
| `form` | `ablauf` (von oben nach unten, mit Verzweigungen), `baum` (Organigramm, hierarchisch), `mindmap` (Mitte mit Ästen) |
| `knoten` | ≤ 60: `{id, text, art?: start\|ende\|entscheidung\|schritt}` |
| `kanten` | ≤ 120: `{von, bis, text?}`; `von` und `bis` müssen Knoten sein |
| Prüfung | eindeutige `id`s, keine Kante ins Leere, höchstens eine Wurzel bei `baum` |

- **Die Anordnung rechnet die Oberfläche selbst** mit einem kleinen eigenen Algorithmus (Schichten für `ablauf`, sauberer Baum für
  `baum`, Strahlen um die Mitte für `mindmap`), etwa 150 Zeilen, **ohne Paket**. Das ist weniger mächtig als ELK, reicht aber für 60 Knoten.
- Gezeichnet als eigenes SVG aus Zahlen (wie `plan2d`): Knoten als Kästen, Kanten als Linien mit Pfeil, Text als Textknoten.
  Zoom und Verschieben mit Knöpfen und Tasten, wie beim Plan.
- **Barrierefrei**: Die Knoten stehen zusätzlich als verschachtelte Liste („A führt zu B und C“), damit Vorleser den Aufbau haben.

## 5. Sicherheit
- Kein Dateizugriff, kein neuer API-Typ, kein neues Paket, keine Änderung an CSP, ALLOWLIST oder Tauri-Rechten.
- Prüfung zweimal (Channel-Server und Bridge) in `stage/schema.py`: feste Formen, Grenzen, endliche Zahlen, Texte ohne Steuer- und
  Richtungs-Umkehrzeichen (die Schrift-Richtung setzt `dir="auto"`, nicht Claude), unbekannte Felder abgelehnt, `richtig` muss auf
  eine vorhandene Option zeigen, Kanten müssen auf vorhandene Knoten zeigen.
- Kein HTML, keine Links, keine Bilder. Fremdsprachiger Text (Übersetzung) ist nur Text.

## 6. Tests und Dateien
- **Python**: Schema je Baustein (jede Grenze, falsche Typen, `richtig` außerhalb, Zeilen mit falscher Spaltenzahl, Kanten ins Leere,
  doppelte `id`), `tools/list` nennt die neuen Bausteine.
- **Vitest**: jede Darstellung; Lernkarten (Zähler, Antwort erst nach Klick, Zusammenfassung); Quiz (Rückmeldung in Worten, richtig und
  falsch, nur eine Auswahl, Ergebnis); Anleitung (Weiter/Zurück, Grenzen, Pfeiltasten, Timer zählt herunter und endet in Worten);
  **kein Klick sendet etwas** (gesendete Nachrichten bleiben unverändert); Eingaben bleiben Text; Zeitstrahl in Reihenfolge; Vergleich
  mit „dafür“/„dagegen“; Gegenüberstellung mit `dir="auto"`; für `netz`: Anordnung (keine Überlappung, jede Kante hat zwei Enden).
- **Ansehen**: Mock-Demo um je ein Beispiel erweitern, im Browser bei 375, 800 und 1440 px (Fokus, Tastatur, Zählerstände).
- **Dateien**: `stage/schema.py`, `channel/server.py` (Beschreibung, ein Satz), `ui/src/lib/stage.ts`, neu `ui/src/components/stage/Learn.tsx`
  (Lernkarten, Quiz, Anleitung), `Compare.tsx` (Vergleich, Zeitstrahl, Gegenüberstellung), später `Net.tsx` und `lib/layout.ts`,
  `ViewCard.tsx`, `lib/mock.ts`, `styles/app.css`, Tests.

## 7. Entscheidungen für dich
1. **Schnitt**: erst P6a, dann P6b (Diagramme)? Empfehlung: ja.
2. **Lernen mit Klicks**: Lernkarten und Quiz mit Knöpfen im Fenster, Lösungen in den Daten (Empfehlung), oder Lernen nur im Gespräch?
3. **Ton für Timer**: Die Anleitung zeigt den Timer **ohne Ton** (Empfehlung). Soll kushim stattdessen einen Ton oder eine Ansage
   machen, wenn er abläuft? Das wäre eine neue Fähigkeit (Klang abspielen) mit eigenem Plan.
4. **Diagramme**: eigene kleine Anordnung ohne Paket (Empfehlung) oder das Paket `elkjs` (EPL-2.0, mächtiger, größer, braucht deine Freigabe)?
5. **Übersetzung**: kushim liest nur die deutsche Seite vor, denn die Piper-Stimme ist deutsch und spricht Fremdsprachen schlecht. Recht so?
6. **Lernstand**: nichts speichern (Empfehlung) oder später im verschlüsselten Vault merken, welche Karten sitzen?
