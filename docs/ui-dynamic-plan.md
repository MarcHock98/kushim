# Plan: Dynamische Oberfläche („Bühne“) für alle Anwendungsfälle

Stand 2026-11-12. Noch nichts davon ist gebaut, das ist der Plan zur Freigabe. Vorgaben des Nutzers: Design „Jarvin Cockpit“.
Ein **rundes 3D-Modell wie bei Jarvis** steht im Ruhezustand groß in der Mitte. Kommt etwas zum Anzeigen, rückt es
**mit Animation** zur Seite, je nachdem, was gezeigt wird. Gezeichnet wird mit **WebGL/three.js**. Formeln setzt
**KaTeX** (lokal gebündelt). Reihenfolge: **3D zuerst**, dann die Inhalte.

## 1. Leitidee: Bühne statt fester Seiten

Die Startseite wird eine **Bühne** mit festen Zonen. Was Claude Code liefert, bekommt einen Platz auf der Bühne. Das 3D-Modell
(„Kern“) ist immer da und wechselt nur Größe und Ort.

| Bühnen-Modus | Wann | Kern (3D) | Inhalt |
|---|---|---|---|
| **Ruhe** | nichts anzuzeigen | groß, mittig | Zustandswort darunter, Verlauf/System dezent an den Rändern |
| **Begleiten** | kurze Antwort, Kennzahl, Karte | mittelgroß, rückt nach links oben | eine Karte rechts daneben |
| **Fokus** | Rechenweg, Dokument, Mail, Recherche, Diagramm | klein, oben links (wie ein Avatar im Gespräch) | Inhalt nimmt die Mitte, Seitenleiste für Quellen/Schritte |
| **Raum** | 3D-Modell, Simulation, Teilchen | Kern wird zum Begleiter oben rechts; die 3D-Szene teilt sich die WebGL-Leinwand mit ihm | Vollfläche-Szene mit Steuerleiste |
| **Wache** | Freigabe, Notaus, Alarm | bleibt, wo er ist, Farbe nach Zustand | hat **immer Vorrang**: Freigabe-Leiste oben, Notaus-Banner |

- **Übergänge**: FLIP-Animation (Ort und Größe), 220 bis 420 ms, `--ease`. Bei weniger Bewegung (`prefers-reduced-motion`)
  ein direkter Wechsel ohne Fahrt.
- **Zurück**: Esc, Knopf „Schließen“ oder die nächste Frage. Jede gezeigte Karte landet im **Verlauf der Bühne**
  (Übersicht), dort kann man sie wieder öffnen.
- **Warteschlange**: Kommen mehrere Inhalte, zeigt die Bühne den neuesten. Die anderen stehen als Reiter darüber,
  es wird nicht gestapelt.
- **Live**: Ein Inhalt mit derselben `id` wird **aktualisiert, nicht neu angelegt** (z. B. Dokument wächst, Modell ändert sich).
- **Notaus oben rechts in jedem Modus**, Freigaben vor jedem Inhalt (Skill-Regeln unverändert).

## 2. Das 3D-Modell (Kern)

**Wie man es am besten erstellt:** Blender ginge so: modellieren, als glTF (`.glb`) exportieren, mit dem `GLTFLoader`
von three.js lokal laden. Für einen Kern, der **auf die Stimme reagiert**, ist ein **prozedurales Modell direkt in three.js**
besser:

- Es ist parametrisch. Pegel, Zustand und Farbe gehen als Werte in einen Shader, ohne Animationen in Blender zu backen.
- Es ist klein (ein paar KB Code statt MB Modell) und braucht kein Blender auf dem Rechner.
- Blender bleibt **optional** für eine feste Hülle oder Details, die man von Hand formen will (`.glb` im Repo, geladen von `'self'`).

**Aufbau** (Schichten, alle auf einer WebGL-Leinwand):
1. **Hülle**: Ikosphäre, deren Oberfläche ein Noise-Vertex-Shader verformt. Ränder leuchten (Fresnel) in `--arc`.
   Der Pegel lässt sie wellen (Sprechen, Zuhören).
2. **Teilchenschale**: ein paar tausend Punkte auf und um die Kugel, die langsam driften. Beim Denken bilden sie umlaufende Bänder.
3. **Ringe**: drei gekippte, dünne Ringe mit Skalenstrichen (wie im Artifact), räumlich drehend.
4. **Kein K** im Kern (das K bleibt nur im Logo).

| Zustand | Bild |
|---|---|
| Bereit | atmet langsam (4 s), Cyan gedämpft |
| Hört zu | Hülle wellt mit **Mikrofon-Pegel**, Farbe Bernstein |
| Denkt nach | Teilchen formen kreisende Bänder, Ringe drehen schneller |
| Spricht | Hülle wellt mit **Ausgabe-Pegel**, Cyan mit Leuchten |
| Freigabe | ruhig, Bernstein, Ringe stehen |
| Alarm | rot, einmal kurz zusammenziehen, dann ruhig |
| Notaus | grau, Ringe offen/gebrochen, Teilchen stehen still |
| Offline | grau, Hülle als Drahtgitter, nichts bewegt sich |

Jeder Zustand bleibt **auch ohne Farbe** erkennbar (Bewegung und Form) und hat das Wort darunter.

**Last** (Whisper braucht die GPU):
- höchstens 60 fps, im Ruhezustand 30;
- pausiert, wenn das Fenster verdeckt oder minimiert ist;
- „Sparmodus“ (weniger Teilchen, 30 fps), solange Whisper rechnet;
- **eine** WebGL-Leinwand für Kern und Szenen.

**Fallback**: Gibt es kein WebGL, zeichnet der bisherige Canvas-2D-Orb (ohne K).

## 3. Katalog der Anwendungsfälle

Erarbeitet, indem ich systematisch Bereiche durchgegangen bin: Gespräch, Wissen, Arbeit, Kommunikation, Technik, Lernen,
Alltag, System. Für jeden Fall: was Claude liefert, wie die Bühne aussieht, und was dabei sicher bleiben muss.

### A. Gespräch und Wissen
| Fall | Art | Bühne | Ansicht |
|---|---|---|---|
| Einfache Frage | `antwort` | Begleiten | Textkarte: Absätze, Aufzählung, Hervorhebung |
| Mathe mit Rechenweg | `rechnung` | Fokus | Aufgabe, nummerierte Schritte (Erklärung + KaTeX-Formel), Ergebnis groß |
| Funktion zeichnen | `graph` | Fokus | Koordinatensystem (SVG), Kurven aus **Stützpunkten von Claude**. Die UI wertet keine Formeln aus |
| Einheiten, Umrechnung | `kennzahlen` | Begleiten | große Zahl, Einheit, Rechenweg klein |
| Statistik, Datenreihe | `diagramm` | Fokus | Linie, Balken, Streuung (SVG, Regeln aus dem `dataviz`-Stil) |
| Vergleich (Produkte, Optionen) | `vergleich` | Fokus | Tabelle mit Spalten je Option, Vor-/Nachteile |
| Zeitstrahl, Geschichte | `zeitstrahl` | Fokus | waagrechte Achse, Ereignisse, Zoom |
| Begriff, Erklärung mit Skizze | `erklaerung` | Fokus | Text + Diagramm-Baustein |
| Übersetzung | `gegenueber` | Fokus | Original und Übersetzung nebeneinander |

### B. Recherche und Markt
| Fall | Art | Bühne | Ansicht |
|---|---|---|---|
| Recherche, mehrere Quellen | `recherche` | Fokus | Zusammenfassung; Aussagen mit Quellennummern [1] [2]; Widersprüche ausdrücklich; Quellenliste rechts |
| Aktienmarkt, Kurse | `markt` | Fokus | Kennzahl-Kacheln (▲▼ + Wort), Kursdiagramm, Tabelle, **„Stand: Uhrzeit“**, Hinweis „keine Anlageberatung“ |
| Nachrichtenlage | `recherche` | Fokus | Schlagzeilen-Liste mit Quelle und Zeit, Zusammenfassung |
| Wetter | `kennzahlen` + `diagramm` | Begleiten | Temperaturverlauf, Regenwahrscheinlichkeit (Daten von Claude) |

Kein Live-Ticker: kushim ruft nichts selbst ab. „Aktualisieren“ ist eine neue Frage an Claude.

### C. Arbeit mit Claude Code (live)
| Fall | Art | Bühne | Ansicht |
|---|---|---|---|
| Auftrag läuft | `fortschritt` | Begleiten | Plan-Schritte mit Haken, aktueller Schritt, benutzte Werkzeuge, Laufzeit |
| Dokument bearbeiten | `dokument` | Fokus | Text links, **Änderungen live** rechts (Diff, eingefügt/gelöscht), Gliederung; Dateien nur aus freigegebenen Ordnern |
| Code ändern | `diff` | Fokus | Dateiliste, Diff, Testergebnis (baut auf dem vorhandenen Claude-Panel auf) |
| Mail lesen/zusammenfassen | `mail` | Fokus | Absender, Betreff, Zusammenfassung, Originaltext **nur als Text**, keine Bilder, keine Links öffnen |
| Mail-Entwurf | `mail-entwurf` | Fokus | An/Betreff/Text genau so, wie er rausgehen würde. **Senden nur über Claude Codes eigenes Werkzeug mit Freigabe** (Freigabe-Leiste mit exaktem Text) |
| Posteingang-Überblick | `liste` | Fokus | Gruppen (wichtig, später, Werbung), je Zeile Absender + Satz |
| Kalender, Termine | `zeitplan` | Begleiten | Tagesleiste mit Blöcken, Konflikte markiert |
| Aufgaben, Timer | `liste` / `timer` | Begleiten | Häkchen-Liste, laufende Timer |

### D. Technik, 3D und Simulation
| Fall | Art | Bühne | Ansicht |
|---|---|---|---|
| 3D-Modell ansehen | `modell` | Raum | three.js-Betrachter: drehen, zoomen, Schnitt, Maße; Datei (`.glb/.gltf/.stl/.obj`) **nur aus freigegebenem Ordner, nur lesen, Größenlimit** |
| 3D-Modell live bearbeiten | `modell` (live) | Raum | Datei ändert sich → Szene lädt neu; Vorher/Nachher-Schieber; geänderte Teile hervorgehoben |
| Pläne, Baupläne, Grundrisse | `plan` | Fokus | 2D-Zeichnung (SVG von Claude oder aus DXF/SVG-Datei im Ordner), Maßketten, Ebenen ein/aus |
| Diagramme (Ablauf, Mindmap, Organigramm) | `graph-netz` | Fokus | Knoten und Kanten von Claude, Layout lokal (ELK, Paket zur Freigabe) |
| Teilchen, Atome, Moleküle | `teilchen` | Raum | Atommodell, Moleküle aus XYZ/PDB-Daten von Claude (Kugeln + Bindungen), Orbital-Wolken als Punktwolke |
| Physik-Simulation | `simulation` | Raum | Szene aus **Parametern** (Pendel, Wurf, Federn, Wellen, Gas in einem Kasten, Planeten). Rechnet lokal im Web Worker, Start/Pause/Regler. Deutlich als **„Simulation“** beschriftet, nicht als Messung |
| Elektronik, Schaltplan | `plan` | Fokus | SVG-Schaltplan von Claude |

### E. Lernen und Alltag
| Fall | Art | Bühne | Ansicht |
|---|---|---|---|
| Lernkarten, Quiz | `quiz` | Fokus | Frage groß, Antwort per Tippen/Sprache, Auflösung |
| Anleitung Schritt für Schritt (Kochen, Reparatur) | `anleitung` | Fokus | ein Schritt groß, „weiter“ per Stimme, Timer pro Schritt |
| Einkaufsliste, Notizen | `liste` | Begleiten | Liste, Häkchen |

### F. System und Sicherheit (gibt es schon, wird Teil der Bühne)
Systemzustand, Gedächtnis, Sicherheit, Freigaben, Notaus. Diese bleiben eigene Ansichten, liefern ihre Daten aber auch als
Bühnen-Karten („Wie ist die Auslastung?“ zeigt die System-Karte im Begleiten-Modus).

## 4. Technik

### 4.1 Protokoll: Werkzeug `zeige` (Channel → kushim → UI)
Claude Code ruft im Channel `zeige` auf. Ein Aufruf beschreibt **eine Ansicht**:

```json
{ "id": "mathe-1", "art": "rechnung", "titel": "Quadratische Gleichung", "modus": "fokus",
  "bausteine": [
    { "typ": "text", "absaetze": ["Löse x² − 5x + 6 = 0."] },
    { "typ": "schritte", "schritte": [
        { "text": "Mitternachtsformel", "formel": "x = \\frac{5 \\pm \\sqrt{25-24}}{2}" },
        { "text": "Ausrechnen", "formel": "x_1 = 3,\\; x_2 = 2" } ] },
    { "typ": "ergebnis", "formel": "x \\in \\{2, 3\\}" } ],
  "quellen": [] }
```

- **Bausteine** (feste Liste, nichts sonst): `text`, `liste`, `formel`, `schritte`, `ergebnis`, `kennzahlen`, `tabelle`,
  `diagramm`, `zeitstrahl`, `vergleich`, `aussagen` (mit Quellennummern), `quellen`, `diff`, `mail`, `datei3d`, `plan2d`,
  `graph-netz`, `teilchen`, `simulation`, `fortschritt`, `timer`, `hinweis`.
- `art` wählt das Layout, `modus` ist nur ein Wunsch, die Bühne entscheidet. Dieselbe `id` aktualisiert, `"schliessen": true` räumt ab.
- **Prüfung im Backend (Python)**: Schema je Baustein, Größenlimits (Text, Zeilen, Punkte, Teilchen), nur erlaubte Felder,
  Zahlen endlich. Was nicht passt, wird abgelehnt (Claude bekommt eine kurze Fehlermeldung), nie halb angezeigt.
- **UI-Seite**: neuer Abfragetyp `stage.get` (neueste Ansichten seit `id`), Abfrage wie beim Verlauf, nichts bei verdecktem Fenster.

### 4.2 Woher Inhalte kommen dürfen
1. **Von Claude Code** über `zeige` (strukturierte Daten).
2. **Dateien aus freigegebenen Claude-Ordnern**, vom Backend gelesen: nur lesen, Typen auf einer Liste, Größenlimit,
   Pfad gegen den Ordner geprüft (wie `folders_api`). Für 3D, Pläne, Dokumente, Diffs.
3. **kushims eigener Zustand** (Avatar, System, Verlauf, Gedächtnis).

Nie: Netz, fremde Bilder, HTML, Skripte, eingebettete Seiten. Links bleiben Text.

### 4.3 Darstellung
- React-Komponente je Baustein, Layout je `art`, alles mit den Tokens aus `tokens.css`.
- **three.js** (MIT): Kern, 3D-Betrachter, Teilchen, Simulation, **eine** WebGL-Leinwand.
- **KaTeX** (MIT): Formeln, Schriften lokal gebündelt, Ausgabe als Text-DOM, kein `innerHTML` aus fremdem Text.
- Diagramme in eigenem SVG, ohne Paket. Netz-Layouts optional mit **elkjs** (EPL-2.0, Freigabe nötig).
- Simulationen im **Web Worker** (`worker-src 'self'`), eigene kleine Integratoren, keine Physik-Engine nötig.

### 4.4 Sicherheit (bleibt wie im Skill)
- Die UI führt nichts aus. Mails senden, Dateien schreiben, Termine anlegen macht **nur Claude Code** mit seinen Freigaben.
  Die Freigabe-Leiste zeigt den exakten Text.
- Fremde Inhalte (Mail, Web) sind Daten: nur als Text, keine Bilder nachladen, keine Links öffnen.
- Geheimnisse (Token, Schlüssel) tauchen nie auf. Dateiinhalte nur aus freigegebenen Ordnern.
- **CSP**: Bleibt bei `'self'` + Loopback-WebSocket. Mögliche Ergänzungen (`worker-src 'self'`, `blob:` für glTF-Texturen)
  nur mit ausdrücklicher Freigabe. `test_ui_rules.py` wird entsprechend erweitert.
- Neue Pakete (three, katex, ggf. elkjs): Versionen festgenagelt, Lockfile, Lizenz und Größe begründet, aus npm (Freigabe).

## 5. Reihenfolge (Phasen)

| Phase | Inhalt | Ergebnis |
|---|---|---|
| **P1** | three.js-Kern (Hülle, Teilchen, Ringe, Zustände, Pegel, Sparmodus, Fallback) + **Bühne** mit den Modi und FLIP-Übergängen | großer 3D-Kern in der Mitte, weicht mit Animation aus |
| **P2** | `zeige` + `stage.get` + Prüfung; Bausteine `text`, `liste`, `formel/schritte/ergebnis` (KaTeX), `kennzahlen`, `tabelle`, `diagramm`, `aussagen/quellen` | Arten `antwort`, `rechnung`, `markt`, `recherche` |
| **P3** | Live-Arbeit: `fortschritt`, `dokument` (Diff live), `diff`, `mail`, `mail-entwurf`, `liste`, `zeitplan`, `timer` | Claude-Aufträge, Dokumente und Mails sichtbar |
| **P4** | 3D-Dateien: Betrachter, Live-Neuladen, Vorher/Nachher, `plan2d` | Arbeit an 3D-Modellen und Plänen |
| **P5** | `teilchen`, `simulation` (Worker), Atome/Moleküle, Physik | Teilchen- und Physik-Animationen |
| **P6** | `graph-netz`, `zeitstrahl`, `vergleich`, `quiz`, `anleitung`, `gegenueber` | restliche Fälle |

Jede Phase: erst Detailplan mit Freigabe, dann bauen. Tests (pytest, Vitest, `test_ui_rules.py`, `test_no_egress.py`),
Screenshots bei 360/800/1440 px, Commit auf eigenem Branch, kein Push.

## 6. Offene Entscheidungen
1. Pakete freigeben: **three.js** und **KaTeX** (schon gewünscht), **elkjs** für Netz-Diagramme (optional).
2. CSP-Ergänzungen `worker-src 'self'` (Simulationen) und `blob:` (glTF mit Texturen).
3. Mail-Fälle: Liefert Claude Code die Mails über seine eigenen Konnektoren? kushim selbst holt keine Mails.
4. Ob der Kern mit einer in Blender geformten Hülle ergänzt werden soll oder rein prozedural bleibt.
