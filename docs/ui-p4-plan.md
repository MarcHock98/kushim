# Plan P4: 3D-Modelle und Pläne ansehen

Stand 2026-11-13. Teil von `docs/ui-dynamic-plan.md`, Fortsetzung von P3 (`docs/ui-p3-plan.md`, `docs/ui-p3b-plan.md`).
**Noch nicht gebaut, zur Freigabe.** Ziel: Claude Code kann ein Modell oder einen Plan im kushim-Fenster zeigen. Man dreht,
zoomt, schneidet, schaltet Ebenen und sieht, was sich geändert hat (vorher und nachher).

## 1. Vorschlag: P4 in zwei Teile schneiden (wie P3)

| Teil | Woher kommen die Daten | Neuer Zugriff von kushim | Was geht | Risiko |
|---|---|---|---|---|
| **P4a** | Claude Code schickt eine **Szene aus einfachen Körpern** und einen **Plan aus Linien, Kreisen und Maßen** über `zeige` | keiner | Regale, Räume, Bauteile, Grundrisse, Schaltpläne, Skizzen; vorher/nachher | gering |
| **P4b** | kushim liest eine **echte Datei** (`.stl`, `.glb`) aus einem freigegebenen Ordner | ja: lesender Dateizugriff, Binärdaten | echte CAD-Modelle, Neuladen bei Dateiänderung | höher, Audit nötig |

Empfehlung: **erst P4a**. Damit sind die meisten Anwendungsfälle abgedeckt („zeig mir das Regal, 80 mal 30 mal 180“,
„Grundriss der Wohnung mit Maßen“, „vorher und nachher“), und kushim bekommt keine neue Fähigkeit. P4b nur, wenn du echte
CAD-Dateien ansehen willst. Dann mit eigenem Plan und Sicherheits-Audit (Abschnitt 6).

Ehrlich zur Grenze von P4a: Ein echtes Modell aus einer Datei mit tausenden Dreiecken kann Claude so nicht schicken. Eine
Ansicht darf höchstens 48 KB groß sein, und die Verbindung zur Oberfläche lässt Nachrichten bis 64 KB zu. Dafür bräuchte es P4b.

## 2. P4a: zwei neue Bausteine

Neue Arten: **`modell`** (3D-Betrachter) und **`plan`** (2D-Zeichnung). Beide Bausteine laufen in einer Ansicht dieser Art.

### 2.1 `szene3d`: einfache Körper, drehbar

| Feld | Regel |
|---|---|
| `einheit` | Text ≤ 8 (z. B. „cm“); ohne Angabe zeigt der Betrachter „Einheit unbekannt“ bei Maßen |
| `szenen` | 1 bis 3 Szenen `{name, objekte}`, z. B. „vorher“ und „nachher“ |
| `objekte` | je Szene höchstens 150 Objekte |
| Objekt | `form` (box, kugel, zylinder, kegel, torus, ebene, linie), `name` (≤ 40), `masse` (Zahlen je Form, z. B. box `[b, h, t]`, kugel `[r]`), `position [x,y,z]`, `drehung [x,y,z]` in Grad, `farbe` aus der Palette |
| `farbe` | nur Namen: `arc`, `amber`, `ok`, `warn`, `alarm`, `text`, `gedaempft` (keine freien Farben, alles bleibt im Designsystem) |
| `hervorheben` | Liste von Objektnamen, die betont werden (Rand und Leuchten) |
| `beschriftungen` | höchstens 20 `{objekt, text}`, als Text neben dem Körper (kein HTML) |
| Zahlen | endlich, Betrag ≤ 1 000 000; `masse` > 0 |

Betrachter (`three.js`, schon im Projekt, lokal gebündelt):
- **Drehen, Zoomen, Verschieben** mit Maus oder Touch **und** mit Tasten und Knöpfen (Pfeile, plus/minus, „Ansicht zurücksetzen“),
  damit nichts nur mit der Maus geht. `OrbitControls` kommt aus dem vorhandenen Paket `three` (`examples/jsm`), kein neues Paket.
- **Schnitt**: ein Regler schneidet das Modell entlang einer Achse (Clipping-Ebene), Achse wählbar (x, y, z).
- **Maße**: Zeigt die Hüllmaße (Breite, Höhe, Tiefe) in der Einheit von Claude; ohne Einheit „Einheit unbekannt“.
- **Vorher/Nachher**: bei zwei Szenen ein Schieber, der von „vorher“ zu „nachher“ überblendet; Namen, die nur in einer Szene
  vorkommen oder sich verändert haben, werden hervorgehoben und als Liste in Worten genannt („neu: Boden 4; verändert: Seitenwand“).
  Es gibt eine Schaltfläche „Nebeneinander/Überblenden“ als Alternative zum Schieber.
- **Barrierefrei**: Die Szene hat eine Textbeschreibung (`aria-label` aus Namen und Maßen) und eine Objektliste als Tabelle
  zum Aufklappen, denn ein 3D-Bild allein sagt Vorlesern nichts.

### 2.2 `plan2d`: Zeichnung aus Linien, Kreisen und Maßen

| Feld | Regel |
|---|---|
| `einheit` | wie oben |
| `ebenen` | höchstens 10 Namen (z. B. „Wände“, „Möbel“, „Maße“); im Betrachter einzeln ein- und ausschaltbar |
| `elemente` | höchstens 1500, je `{art, ebene, …}` |
| Arten | `linie {von, bis}`, `polylinie {punkte, geschlossen}`, `rechteck {x, y, b, h}`, `kreis {x, y, r}`, `bogen {x, y, r, von, bis}`, `text {x, y, text, groesse}`, `mass {von, bis, text?}` |
| `mass` | Maßlinie mit Pfeilen; ohne `text` rechnet der Betrachter die Länge selbst aus den Punkten |
| Zahlen | endlich, Betrag ≤ 1 000 000 |

Gezeichnet wird als **eigenes SVG aus Zahlen**, ohne Paket. **Nie** wird SVG-Text von Claude übernommen (SVG kann Skripte und
fremde Verweise enthalten). Texte stehen als Textknoten, Striche behalten unabhängig vom Zoom ihre Dicke. Zoomen und
Verschieben mit Mausrad/Ziehen **und** mit Knöpfen und Tasten. Eine Tabelle der Ebenen mit Anzahl der Elemente ist
aufklappbar (für Vorleser).

### 2.3 Wie Claude davon erfährt
Ein Satz in `INSTRUCTIONS` und die Beschreibung von `zeige` nennen die neuen Bausteine. Typische Anfragen: „Zeig mir das Regal
in 3D“, „Zeichne den Grundriss“, „Zeig mir vorher und nachher“. Claude baut die Szene aus seinem Wissen oder aus Dateien, die er
selbst gelesen hat (zum Beispiel OpenSCAD- oder SVG-Quelltext), und schickt nur das geprüfte JSON.

## 3. Last und Sicherheit (P4a)
- **GPU** (Whisper braucht sie): Der Betrachter rendert **nur bei Änderung** (Drehen, Regler), nicht im Dauertakt. Er wird
  nur erzeugt, solange die Ansicht offen ist, und beim Schließen sauber freigegeben (`dispose`). Pixeldichte höchstens 1,5.
  Verdecktes Fenster: nichts. Der Kern bleibt auf seinen 30 fps.
- **Prüfung** zweimal (Channel-Server und Bridge) in `stage/schema.py`, nur Standardbibliothek: feste Formen, Grenzen,
  endliche Zahlen, nur Palettenfarben, Texte ohne Steuer- und Richtungszeichen, unbekannte Felder werden abgelehnt.
- Kein neuer Dateizugriff, kein neuer API-Typ, kein neues Paket, keine Änderung an CSP, ALLOWLIST oder Tauri-Rechten.
- Eine Szene kann nichts ausführen: Es gibt weder Skripte noch Formeln noch Verweise, nur Zahlen und Namen.

## 4. Tests und Dateien (P4a)
- **Python**: Schema je Körper und Element (Grenzen, falsche Typen, nicht endliche Zahlen, unbekannte Farben, zu viele
  Objekte, unbekannte Felder), `tools/list` nennt die neuen Bausteine, Bridge nimmt nur Gültiges.
- **Vitest**: Hüllmaße richtig berechnet, Maßlinie rechnet die Länge, Ebenen ein/aus, Vorher/Nachher nennt neu und verändert in
  Worten, Objektliste als Tabelle, nichts anklickbar außer den Bedienelementen, ohne WebGL ein Hinweistext statt Absturz.
- **Ansehen**: Mock-Demo um ein Regal (vorher/nachher) und einen Grundriss erweitern; im Browser bei 375, 800 und 1440 px,
  Frame-Zeit grob messen. **Nicht messbar ohne dich**: GPU-Last neben Whisper im echten Fenster.
- **Dateien**: `stage/schema.py`, `channel/server.py` (Beschreibung, ein Satz), `ui/src/lib/stage.ts`, neu
  `ui/src/components/stage/Model3D.tsx` und `Plan2D.tsx`, `ViewCard.tsx`, `lib/mock.ts`, `styles/app.css`, Tests.

## 5. Zum Vergleich: wann P4a nicht reicht
Du willst eine echte Datei (`.stl`, `.glb`) ansehen oder die Ansicht soll sich **von selbst** neu laden, wenn die Datei sich
ändert. Das geht nur mit P4b.

## 6. P4b (nur zur Entscheidung, noch kein Detailplan)
- **Neue Fähigkeit**: kushim liest Binärdateien aus freigegebenen Ordnern. Nur lesen, nur Endungen `.stl` und `.glb`, höchstens
  16 MB, nie `.git`, `run`, Namen mit Zugangsdaten (gleiche Sperre wie `stage/schema.py`), keine Verknüpfungen, kein UNC.
- **Nur benannte Dateien**: Die Oberfläche fragt nie mit freiem Pfad. Der Pfad steht in einer von Claude geschickten Ansicht
  (`datei3d {ordner, pfad}`), wird dort gegen die freigegebenen Ordner geprüft und danach über die Ansichts-`id` abgeholt.
- **Verbindung**: Nachrichten sind auf 64 KB begrenzt, große Dateien müssten in Stücken abgeholt werden (`file.chunk`) oder die
  Grenze müsste für diesen einen Typ angehoben werden. Beides ist eine Änderung am Netzserver und braucht deine Freigabe.
- **Neuladen**: Abfrage der Änderungszeit alle 2 Sekunden (nur bei sichtbarem Fenster), bei Änderung wird neu geladen; die
  vorherige Fassung bleibt für „vorher/nachher“ im Speicher.
- **Lader**: `STLLoader` und `GLTFLoader` aus dem vorhandenen Paket `three`. Alle Materialien werden durch eigene Palettenfarben
  ersetzt, Texturen entfallen (die CSP erlaubt kein `blob:`, das bleibt so). `.gltf` mit externen Dateien wird abgelehnt.
  Eckenzahl begrenzt (z. B. 500 000), Fehler beim Lesen zeigen Text, nie einen Absturz.
- **Pflicht**: Prüflauf des `safety-auditor` vor dem Mergen, weil kushim erstmals Binärdateien des Nutzers parst.
- Geänderte Teile hervorheben geht bei `.glb` über Knotennamen, bei `.stl` (ein Netz) nur als Geisterbild der alten Fassung.

## 7. Entscheidungen für dich
1. **Schnitt**: erst P4a (dieser Plan), P4b später und nur auf Wunsch? Empfehlung: ja.
2. **Reichen die Körper** (Quader, Kugel, Zylinder, Kegel, Torus, Ebene, Linie) und die Plan-Elemente für den Anfang?
3. **Schnitt-Regler und Maße** in P4a mitbauen? Empfehlung: ja, beides.
4. **Ansicht in der Karte** (wie alle bisherigen Ansichten, Kern bleibt klein links) oder zusätzlich ein **Vollbild „Raum“**,
   in dem die Szene die ganze Bühne füllt? Empfehlung: erst die Karte, Vollbild später, wenn sie dir zu klein ist.
5. **Einheiten**: Ohne Angabe von Claude steht „Einheit unbekannt“. Recht so?
6. **P4b**: Willst du echte CAD-Dateien ansehen? Wenn ja, welche Formate (Empfehlung `.stl` und `.glb`; `.dxf` für Pläne später)?
