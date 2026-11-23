# Plan P5: Teilchen, Atome, Moleküle und Physik-Simulationen

Stand 2026-11-22. Teil von `docs/ui-dynamic-plan.md`, nach P4a (`docs/ui-p4-plan.md`) und neben P6 (`docs/ui-p6-plan.md`).
**P5a gebaut am 2026-11-22 nach den Empfehlungen aus Abschnitt 12 (vom Nutzer freigegeben). P5b gebaut am 2026-11-23, ebenfalls nach den Empfehlungen.** Ziel: Claude Code kann eine laufende Physik-Simulation (Pendel, Feder, Wurf, Umlaufbahn,
Gas im Kasten) und Atome, Moleküle und Orbitale im kushim-Fenster zeigen. P5 braucht **keinen** Dateizugriff von kushim, **kein
neues Paket** und **keine Änderung an der CSP** (alles empfohlen). Eine Abweichung vom Gesamtplan: Dort stand „Web Worker“. Hier
empfehle ich den Hauptthread mit festem Zeitschritt (Abschnitt 4).

## 1. Vorschlag: P5 in zwei Teile schneiden

| Teil | Bausteine | Aufwand | Besonderheit |
|---|---|---|---|
| **P5a** | `simulation` mit fünf festen Modellen: `pendel`, `feder`, `wurf`, `umlauf`, `gas` | etwa wie P4a, etwas mehr wegen der Taktschleife und der Physik-Tests | erste Ansicht, die sich **von selbst bewegt**. Darum gibt es feste Grenzen für die Last, einen automatischen Stopp und ein Standbild bei „weniger Bewegung“ |
| **P5b** | `teilchen` (Molekül, Schalenmodell, Orbital-Wolke), dazu für `simulation`: Regler, Tempo, `doppelpendel`, `welle` | etwas weniger als P4a (three.js und Kamera gibt es schon, kein Dauertakt) | 3D wie in P4a: Es wird nur gezeichnet, wenn sich etwas ändert |

Empfehlung: **erst P5a**. Das Neue und Riskante ist die Dauer-Animation neben Whisper. Das soll zuerst sauber stehen und begrenzt sein.
Die Ansicht bleibt in der Karte wie bei P4a. Ein Vollbild „Raum“ kommt erst, wenn dir die Karte zu klein ist.

## 2. Grundsatz: Parameter statt Code

Claude schickt **nur den Namen eines eingebauten Modells und Zahlen**. Er schickt keine Formeln, keine Bewegungsgleichungen, keine
Shader, keine Skripte und keine Funktionen. Gründe:
- **Kein `eval`, kein Interpreter.** Die CSP (`script-src 'self'`, ohne `'unsafe-eval'`) sperrt `eval` und `new Function` schon heute.
  Ein selbst geschriebener Formel-Parser würde diesen Schutz umgehen: Er wäre ein Interpreter in unserem eigenen Code, also ein neuer
  Weg, Eingaben von außen „ausführen“ zu lassen. Das bauen wir nicht.
- **Keine Lastfalle.** Eine freie Formel kann beliebig teuer oder instabil sein (Division durch null, Werte laufen gegen unendlich).
  Feste Modelle haben geprüfte Rechenverfahren und Grenzen, die das Backend vorher nachrechnet.
- **Testbar.** Jedes Modell hat Vergleichswerte aus Lehrbuchformeln (Abschnitt 10).
- Gleiche Linie wie bisher: Die Oberfläche wertet keine Formeln aus (Gesamtplan, Fall „Funktion zeichnen“).

Wer ein Modell braucht, das es nicht gibt, bekommt von Claude eine Erklärung, ein `diagramm` mit Stützpunkten oder eine `szene3d`.

> **Nachtrag 2026-11-23: für `sim_eigen` aufgehoben am 2026-11-23.** Grund: Der Nutzer hat entschieden, dass Claude eigene
> Simulationen beschreiben darf, wenn kein eingebautes Modell passt (P7, `docs/ui-p7-plan.md`). Der Parser steht nicht in der
> Oberfläche, sondern im Backend (`src/kushim/stage/formel.py`, eigene feste Importliste, kein `eval`, kein `ast`, Tiefenzähler).
> Die Oberfläche bekommt nur geprüfte Befehlsfolgen (RPN) für eine Stapelmaschine mit festen Befehlen und parst nie Text; die CSP
> bleibt unverändert. Für alle anderen Bausteine, auch `simulation`, gilt dieser Abschnitt weiter: nur Modellnamen und Zahlen.

## 3. P5a: Baustein `simulation`

Neue Art **`simulation`**, Beschriftung „Simulation“. Die Ansicht trägt immer sichtbar den festen Satz **„Simulation, keine Messung“**.
Diesen Satz setzt die Oberfläche, Claude kann ihn nicht entfernen.

| Feld | Regel |
|---|---|
| `modell` | genau eines von `pendel`, `feder`, `wurf`, `umlauf`, `gas` |
| `parameter` | Objekt mit den Feldern des Modells (Tabelle unten), unbekannte Felder abgelehnt, Pflichtfelder fehlen = abgelehnt |
| `laufzeit` | 5 bis 60 Sekunden echte Zeit bis zum automatischen Stopp, Standard 30 |
| `tempo` | Zeitraffer 0,1 bis 100; ohne Angabe wählt die Oberfläche das Tempo so, dass eine Schwingung, ein Flug oder der innerste Umlauf etwa 3 bis 6 s dauert |
| `spur` | ja/nein, Standard ja (Bahn als Linie, höchstens 600 Punkte je Körper) |
| `beschreibung` | Text ≤ 400, optional; erscheint unter dem Bild und in der Textfassung |
| Einheiten | fest: SI (m, s, kg); bei `umlauf` AE, Jahre, Sonnenmassen; bei `gas` „Einheiten“. Claude wählt keine Einheit |
| Zahlen | endlich, keine Wahrheitswerte als Zahl, Grenzen je Feld |

| `modell` | Parameter (Grenzen) | Rechnung | Kennwerte in Worten |
|---|---|---|---|
| `pendel` | `laenge` 0,05 bis 100 m; `winkel` -170 bis 170 Grad; `anfangsgeschwindigkeit` -720 bis 720 Grad/s (0); `daempfung` 0 bis 5 1/s (0); `g` 0,1 bis 100 m/s² (9,81) | fester Schritt, Verlet (hält die Energie ohne Dämpfung stabil) | Schwingungsdauer (kleine Winkel), Winkel jetzt, Energie in Prozent des Starts |
| `feder` | `masse` 0,001 bis 1000 kg; `federkonstante` 0,001 bis 1 000 000 N/m; `auslenkung` -10 bis 10 m; `daempfung` 0 bis 10 000 kg/s (0); zusätzlich: Schwingungsdauer zwischen 0,05 und 1000 s | fester Schritt, Verlet | Schwingungsdauer, Auslenkung jetzt, Energie |
| `wurf` | `geschwindigkeit` 0,1 bis 1000 m/s; `winkel` -90 bis 90 Grad; `hoehe` 0 bis 10 000 m; `g` (9,81); `luftwiderstand` 0 bis 1 pro m (0); bei Höhe 0 muss der Winkel > 0 sein | ohne Luftwiderstand geschlossene Formel, mit Luftwiderstand fester Schritt; endet beim Aufprall | Reichweite, Gipfelhöhe, Flugzeit (vorab gerechnet, damit der Bildausschnitt nicht springt) |
| `umlauf` | `zentralmasse` 0,01 bis 100 Sonnenmassen; `koerper` 1 bis 8: `{name ≤ 30, abstand 0,01 bis 1000 AE (große Halbachse), exzentrizitaet 0 bis 0,95, phase 0 bis 360 Grad, farbe}`; größte durch kleinste Halbachse ≤ 100; Namen eindeutig | geschlossene Lösung (Kepler-Gleichung), daher keine Drift. Die Körper ziehen sich gegenseitig **nicht** an (Hinweis in der Ansicht) | Umlaufzeit je Körper in Jahren, Abstand jetzt |
| `gas` | `anzahl` 2 bis 300; `kasten [b, h]` 1 bis 1000, Seitenverhältnis ≤ 10; `radius` > 0 und ≤ 5 % der kürzeren Seite; alle Teilchen zusammen ≤ 30 % der Fläche; `geschwindigkeit` > 0 bis 10 Kastenbreiten/s; `schwerkraft` 0 bis 100 (0); `stoesse` ja/nein (ja); `startwert` 0 bis 2 147 483 647 (1) | fester Schritt, elastische Stöße über ein Raster, Startlagen aus dem Startwert (nie Zufall ohne Startwert) | mittlere Geschwindigkeit, Energie, Verteilung der Geschwindigkeiten als kleines Balkendiagramm (10 Klassen, einmal je Sekunde neu) |

`farbe` gibt es nur aus der Palette (`arc`, `amber`, `ok`, `warn`, `alarm`, `text`, `gedaempft`), wie bei `szene3d`. „Freie Teilchen mit
Schwerkraft und Stößen“ ist `gas` mit `schwerkraft` > 0. Eine Ansicht mit derselben `id` ersetzt die Simulation und startet sie neu.

## 4. Wo gerechnet und gezeichnet wird

**Rechnen: im Hauptthread mit festem Zeitschritt (Empfehlung).** Ein Schritt dauert immer gleich lang in Simulationszeit (zum
Beispiel 1/1000 s beim Pendel). Die Bildrate bestimmt nur, wie viele Schritte je Bild gerechnet werden. Darum verläuft eine Simulation
auf jedem Rechner gleich. Gründe gegen den Worker:
- Die Grenzen machen die Rechnung klein: höchstens 300 Teilchen mit wenigen Schritten je Bild, das ist im Hauptthread voraussichtlich
  unter 1 ms je Bild (wird im Browser gemessen). Bei 300 Teilchen kostet das Hin- und Herschicken der Lagen an einen Worker etwa so viel wie
  das Rechnen selbst.
- **Keine Frage an die CSP.** Die CSP hat kein `worker-src`. Nach den CSP-Regeln gilt dann `script-src 'self'`. Ein Worker aus einer
  eigenen Datei wäre also wohl schon erlaubt, ein Worker aus `blob:` (so baut Vite „eingebettete“ Worker) nicht. Wie sich WebView2 in
  Tauri dabei verhält, lässt sich ohne das echte Fenster nicht prüfen.
- Vitest (jsdom) kennt keine Worker. Die Rechenlogik bleibt eine reine Funktion und ist direkt testbar.

Falls später deutlich mehr Teilchen gewünscht sind: Worker aus eigener Datei, dazu ausdrücklich `worker-src 'self'` in die CSP
(verschärft nur, was ohnehin gilt) und `test_ui_rules.py` anpassen. Das wäre eine eigene Freigabe.

**Zeichnen: Canvas 2D, nicht three.js (Empfehlung).** Alle fünf Modelle sind eben (Pendel, Wurf und Bahnen in einer Ebene, Gas im
Rechteck). Der Design-Skill sagt: „kein WebGL, solange Canvas 2D reicht“. Damit entsteht kein zweiter WebGL-Kontext neben dem Kern.
Texte von Claude (Namen, Beschreibung) stehen nur im DOM, nie im Bild, wie bei P4a.

## 5. Last: Grenzen neben Whisper (RTX 3070, 8 GB)

Die GPU-Last des P4a-Betrachters ist noch nicht gemessen. Darum gilt hier: lieber zu streng, lockern kann man nach deiner Messung.

| Regel | Wert |
|---|---|
| Bildrate | höchstens 30 fps (wie der Kern im Ruhezustand), Pixeldichte höchstens 1,5 |
| Rechenarbeit je Bild | Körper × Teilschritte ≤ 4000 (zum Beispiel 300 Teilchen × 8 Schritte = 2400). Reicht das nicht für das gewünschte Tempo, läuft die Zeit langsamer und die Ansicht sagt in Worten „Zeitlupe, Rechengrenze erreicht“ |
| Automatischer Stopp | nach `laufzeit` (Standard 30 s, höchstens 60 s) sichtbarer Laufzeit. Das letzte Bild bleibt stehen, dazu „angehalten nach 30 s“ und „Neu starten“ |
| Pause | keine Schleife, kein Bild, null Last |
| Fenster verdeckt oder minimiert | kein Schritt, kein Bild; danach geht es weiter, ohne die verpasste Zeit nachzuholen |
| Außer Sicht gescrollt | kein Bild (`IntersectionObserver`) |
| Anderer Reiter, andere Seite, Schließen | die Ansicht wird abgebaut, die Simulation endet; beim Zurückkommen beginnt sie von vorn (so arbeitet `ViewCard` schon heute: nur die gezeigte Ansicht ist geladen) |
| Neue Frage | beim Zuhören schließt die Bühne die Ansicht schon heute (`App.tsx`). Whisper rechnet erst danach, also ohne laufende Simulation |
| Vorausrechnung | für Bildausschnitt, Kennwerte und Standbild höchstens 200 000 Körper-Schritte, einmal beim Öffnen |
| Fehler | wird eine Zahl nicht endlich: sofort Stopp mit „Simulation instabil, angehalten“, nie ein Bild mit kaputten Werten |

Die Oberfläche prüft die Grenzen ein zweites Mal selbst (Schutz, falls das Backend umgangen würde, etwa in der Mock-Demo).

## 6. Bedienung und weniger Bewegung

- **Knöpfe in P5a**: „Pause“/„Weiter“ und „Neu starten“, mit Tab, Enter und Leertaste bedienbar, ≥ 44 px. Wie bei P6 ändert ein
  Klick **nur den Zustand der Ansicht**. Er ruft nie die API auf, sendet nichts an Claude und speichert nichts. Ein Test prüft das.
- **Start**: Die Simulation läuft beim Zeigen los (du hast sie ja verlangt) und hält nach der Laufzeit von selbst an. Weil sie länger als
  5 Sekunden läuft, gibt es immer Pause (Regel „anhalten, stoppen, ausblenden“ der Barrierefreiheit).
- **Zustand in Worten**: „läuft“, „pausiert“, „angehalten nach 30 s“, „gelandet nach 4,2 s“, „Zeitlupe“. Wechsel werden einmal
  angesagt (`aria-live="polite"`), die laufenden Zahlen nicht (sie würden Vorleser überfluten).
- **Textfassung für Vorleser** bei jeder Simulation: Modell, Parameter und gerechnete Kennwerte als Satz, zum Beispiel „Pendel, Länge
  1 m, Start bei 30 Grad, ohne Dämpfung. Schwingungsdauer etwa 2,0 s.“ Dazu die Kennwerte als Tabelle.
- **Weniger Bewegung** (`prefers-reduced-motion`): keine Animation. Stattdessen ein Standbild, das die Bewegung zeigt, plus die Textfassung:
  Pendel und Feder mit Ausgangslage und Lage-Zeit-Kurve über drei Schwingungen; Wurf mit ganzer Bahn, Gipfel und Aufprall markiert;
  Umlauf mit allen Bahnen und den Körpern in Startlage; Gas mit Startbild und der Verteilung nach 10 s gerechneter Zeit.
  Ein Knopf „Trotzdem abspielen“ ist möglich, weil du dann selbst wählst (Entscheidung 6).

## 7. P5b: `teilchen` und Ergänzungen

Neue Art **`teilchen`**. Ein Baustein mit `form`:

| `form` | Felder und Grenzen | Darstellung |
|---|---|---|
| `molekuel` | `name?` ≤ 60; `atome` 1 bis 300 `{element, position [x,y,z]}`, `element` aus der festen Liste der 118 Symbole, Lage in Ångström, Betrag ≤ 200; `bindungen?` 0 bis 400 `{von, bis, ordnung 1\|2\|3}` (Indizes vorhanden, `von` ≠ `bis`, keine doppelten); `beschriftungen?` ≤ 20 `{atom, text ≤ 40}`; `darstellung` `kugel-stab` oder `kalotte` | three.js wie P4a, nur Zeichnen bei Änderung; Kugeln und Stäbe als wenige gebündelte Netze. Ohne `bindungen` rechnet die Oberfläche sie aus Abständen und festen Atomradien. Summenformel, Atom- und Bindungszahl als Text, Atomliste als Tabelle |
| `atom` | `element`; `neutronen?` 0 bis 200; `ladung` -3 bis 3 (0); `schalen?` bis 7 Zahlen je 0 bis 32, Summe = Ordnungszahl minus Ladung; ohne `schalen` nur bis Ordnungszahl 20 (Regel 2, 8, 8, 2), darüber Pflicht | eigenes SVG, **statisch**, beschriftet als „vereinfachtes Schalenmodell“ (kreisende Elektronen würden eine falsche Vorstellung zeigen) |
| `orbital` | `orbital` aus fester Liste (1s, 2s, 2p_x, 2p_y, 2p_z, 3s, 3p_x, 3p_y, 3p_z, 3d_xy, 3d_xz, 3d_yz, 3d_x2-y2, 3d_z2); `punkte` 500 bis 5000 (2500); `startwert` | Punktwolke aus der **fest eingebauten** Wasserstoff-Formel, gezogen mit Startwert; Vorzeichen in zwei Palettenfarben **und** als Wort („Phase plus/minus“) |

Atomfarben nur aus der Palette, angelehnt an die üblichen Farben (Sauerstoff `alarm`, Stickstoff `arc`, Wasserstoff `text`, Kohlenstoff
`gedaempft`, Schwefel `warn`, Halogene `ok`, sonst `amber`). Das Symbol steht immer als Text daneben, nie nur Farbe. 300 Atome sind
etwa 15 KB, also weit unter der Grenze von 48 KB je Ansicht. Die kleine Kamerabahn aus `Model3D.tsx` wird in eine gemeinsame Datei gezogen;
die P4a-Tests müssen dabei grün bleiben.

Ergänzungen für `simulation` in P5b: **Regler** für ein bis zwei Hauptwerte je Modell (zum Beispiel Pendellänge), nur innerhalb der
Schema-Grenzen, nur Anzeigezustand; **Tempo** halb/normal/doppelt; `doppelpendel` (chaotisch, darum mit Energie-Anzeige);
`welle` (bis zu drei überlagerte Sinuswellen, geschlossen gerechnet); gegenseitige Anziehung bei `umlauf` (bis 8 Körper).

## 8. Pakete

**Kein neues Paket** (Empfehlung). three.js 0.170.0 ist da (für P5b). Die Integratoren werden selbst geschrieben, etwa 250 Zeilen: Verlet,
Kepler-Gleichung, Stöße mit Raster, ein kleiner Zufallsgenerator mit Startwert. Alternativen und ihr Preis:
- **matter.js** (2D-Physik, MIT): rund 80 KB, kann starre Körper, die wir nicht brauchen; eigene Zeitsteuerung, die an die Grenzen
  aus Abschnitt 5 angepasst werden müsste. Neue Abhängigkeit mit Freigabe und Lockfile.
- **Rapier, cannon-es** (3D-Physik): Rapier läuft als WebAssembly und bräuchte `'wasm-unsafe-eval'` in der CSP, also eine Lockerung.
  Nicht empfohlen.
- **Molekül-Betrachter** (3Dmol.js, NGL): groß und mit eigenen Ladern für Dateien und Adressen, die gesperrt werden müssten. Für Kugeln und
  Stäbe reicht three.js.

## 9. Sicherheit

- Kein Dateizugriff, kein neuer API-Typ, kein neues Paket, keine Änderung an CSP, ALLOWLIST oder Tauri-Rechten.
- Claude schickt nur Modellnamen und Zahlen (Abschnitt 2). Es gibt kein `eval`, kein `new Function`, keinen Formel-Parser, keine Shader von
  außen, keinen Worker und kein WebAssembly. Regeltests sperren das.
- Prüfung zweimal (Channel-Server und Bridge) in `stage/schema.py`, nur Standardbibliothek (die erlaubte Liste in `test_no_egress.py`
  bleibt `__future__`, `json`, `math`, `re`, `typing`; die Elementliste ist eine feste Konstante). Feste Modelle und Formen, Grenzen je Feld,
  endliche Zahlen, Palettenfarben, Texte ohne Steuer- und Richtungszeichen, unbekannte Felder abgelehnt. Abgeleitete Prüfungen:
  Schwingungsdauer der Feder, Belegung des Kastens, Verhältnis der Bahnen, Bindungs-Indizes, Summe der Schalen. Fehler als kurzer
  fester Code, nie mit Teilen der Eingabe.
- Grenzen wirken doppelt: im Backend und noch einmal in der Oberfläche (Rechenarbeit je Bild, Stopp, Abbruch bei nicht endlichen Werten).
- Knöpfe und Regler ändern nur die Anzeige. Nichts wird gesendet oder gespeichert.
- Der Satz „Simulation, keine Messung“ und Hinweise wie „ohne gegenseitige Anziehung“ kommen von der Oberfläche, nicht von Claude.

## 10. Tests und Dateien

- **Python** (`tests/test_stage.py`, `tests/test_channel.py`): jede Grenze je Modell und Form (knapp innen, knapp außen), unbekanntes Modell,
  unbekannte und fehlende Parameter, `NaN`, unendlich, `true` als Zahl, Feder mit zu kurzer Schwingungsdauer, zu voller Kasten, Wurf ohne
  Flugbahn, Bahnverhältnis > 100, doppelte Körpernamen; für P5b unbekanntes Element, Bindung ins Leere, auf sich selbst oder doppelt, falsche
  Schalensumme, unbekanntes Orbital, 300 Atome bleiben unter 48 KB; `tools/list` nennt die neuen Bausteine; die Bridge nimmt nur Gültiges.
- **Vitest, Rechenlogik** (`physics.test.ts`): gleiche Eingabe gibt nach 10 000 Schritten genau dieselben Zahlen; Gas mit gleichem Startwert
  gleich, mit anderem verschieden; kein `Math.random`. Energie: Pendel und Feder ohne Dämpfung weichen über 60 s Simulationszeit um weniger
  als 0,1 % ab; Gas ohne Schwerkraft hält die Bewegungsenergie bei Stößen; mit Dämpfung fällt die Energie nur. Vergleich mit Lehrbuchformeln:
  Pendel bei kleinem Winkel 2π√(L/g), Feder 2π√(m/k), Wurf ohne Luftwiderstand (Reichweite, Gipfel, Flugzeit), Umlaufzeit √(a³/M) und Abstand im
  sonnennächsten Punkt a(1-e), je auf 0,5 % genau.
- **Vitest, Taktschleife und Ansicht** (`simulation.test.tsx`, mit falschem `requestAnimationFrame` und falscher Uhr): nie mehr als 30 Bilder je
  Sekunde; Rechenarbeit je Bild nie über der Grenze, dann „Zeitlupe“ in Worten; Stopp nach der Laufzeit; verdecktes Fenster rechnet nichts und holt
  nichts nach; nicht endlicher Wert stoppt mit Hinweis; Pause und Weiter wechseln das Wort, Neu starten setzt auf den Anfang; weniger Bewegung:
  keine Schleife, Standbild und Textfassung da; „Simulation, keine Messung“ immer sichtbar; **kein Klick sendet etwas** (gesendete Nachrichten
  bleiben gleich); ohne Canvas oder WebGL ein Hinweistext statt Absturz. P5b: Summenformel, Bindungen aus Abständen (Wasser, Ethanol),
  Orbital-Punkte gleich bei gleichem Startwert.
- **Regeln** (`tests/test_ui_rules.py`): kein `eval`, `new Function`, `WebAssembly`, `Worker`, `importScripts` in `ui/src`; `ShaderMaterial` nur in
  `Core3D.tsx`; kein `Math.random` in `lib/physics.ts` und `lib/chem.ts`; CSP ohne `unsafe-eval`, `wasm-unsafe-eval`, `blob:` und `worker-src`.
- **Ansehen**: Mock-Demo um Pendel, Wurf und Gas erweitern (P5b: Wasser, Ethanol, 2p_z); im Browser bei 375, 800 und 1440 px; Zeit je Bild
  (Rechnen und Zeichnen) im Browser messen.
- **Dateien P5a**: `src/kushim/stage/schema.py`, `src/kushim/channel/server.py` (Beschreibung, ein Satz in `INSTRUCTIONS`), `ui/src/lib/stage.ts`,
  neu `ui/src/lib/physics.ts` (Modelle, Integratoren, Startwert-Zufall), neu `ui/src/lib/simLoop.ts` (Takt, Grenzen, Stopp, Sichtbarkeit), neu
  `ui/src/components/stage/Simulation.tsx`, `ViewCard.tsx`, `lib/mock.ts`, `styles/app.css`, Tests.
- **Dateien P5b**: zusätzlich neu `ui/src/lib/chem.ts`, `ui/src/lib/orbitCamera.ts` (aus `Model3D.tsx` gezogen), `Molecule3D.tsx`, `AtomShells.tsx`.

## 11. Was ohne dich nicht prüfbar ist

1. **GPU- und CPU-Last neben Whisper und Piper** im echten Fenster auf der RTX 3070. Das ist auch für P4a noch offen. Gemessen wird nur die
   Zeit je Bild im Browser, nicht in WebView2 und nicht mit Whisper.
2. Ob WebView2 in Tauri ein nur **verdecktes** (nicht minimiertes) Fenster als verborgen meldet. Wenn nicht, läuft die Simulation dahinter bis
   zum automatischen Stopp weiter.
3. Ob die Windows-Einstellung „Animationseffekte“ in WebView2 als „weniger Bewegung“ ankommt.
4. Wie ein Vorleser (Sprachausgabe, NVDA) die Textfassung und die Zustandswechsel vorliest.
5. Ob Claude Code im echten Aufruf passende Modelle und Werte innerhalb der Grenzen wählt.
6. Wie flüssig 30 fps auf deinem Bildschirm wirken (hohe Bildwiederholrate, Skalierung).
7. Ob die Ansicht beim Nachhören ohne Wake Word gleich nach der Antwort schließt. Das betrifft alle Ansichten, nicht nur P5.

## 12. Entscheidungen für dich
1. **Schnitt**: erst P5a (Simulation), dann P5b (Moleküle, Atome, Orbitale, Regler)? Empfehlung: ja.
2. **Modelle in P5a**: reichen Pendel, Feder, Wurf, Umlaufbahn und Gas im Kasten für den Anfang? Empfehlung: ja, Doppelpendel und Welle in P5b.
3. **Ort der Rechnung**: Hauptthread mit festem Zeitschritt, keine CSP-Änderung (Empfehlung), oder Web Worker mit ausdrücklichem `worker-src 'self'`?
4. **Zeichnen**: Canvas 2D für Simulationen (Empfehlung, weniger GPU, kein zweiter WebGL-Kontext) oder three.js für alles?
5. **Start und Stopp**: läuft beim Zeigen los und hält nach 30 s an (Empfehlung), oder startet erst auf Knopfdruck? Ist 30 s (höchstens 60 s) recht?
6. **Weniger Bewegung**: Standbild mit Textfassung und einem Knopf „Trotzdem abspielen“ (Empfehlung) oder nur das Standbild ohne Knopf?
7. **Pakete**: kein neues Paket, eigene kleine Integratoren (Empfehlung), oder matter.js (größer, eigene Freigabe)?
8. **Atomfarben**: Palettenfarben angelehnt an die üblichen Farben, Symbol immer als Text (Empfehlung). Recht so?
