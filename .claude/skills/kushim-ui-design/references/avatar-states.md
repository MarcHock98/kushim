# Avatar: Zustände, Bewegung, Budget

Der Avatar ist das Gesicht von kushim. Form: ein **Keil-K-Kern** (aus `assets/logo.svg`, vereinfacht) in einem ruhigen
Ring aus **Zählmarken** (kleine Punkte wie auf Verwaltungstafeln). Keine Gesichtszüge, kein Roboterkopf. Der Ring trägt
die Information (Pegel, Wellenform), der Kern bleibt ruhig.

## Zustandsautomat
Das Backend sendet `state` (Ereignis). Die UI zeigt genau diese Zustände und erfindet keine.

| Zustand | Auslöser (Backend) | Kern | Ring | Farbe | Textzeile (immer sichtbar) |
|---|---|---|---|---|---|
| `idle` | wartet auf Wake Word | gedimmt, "atmet" (4 s, Skala 1,00 bis 1,03) | Marken ruhig, 20 % Deckkraft | Bernstein gedämpft | "Bereit. Sag „hey kushim“." |
| `listening` | Wake Word erkannt, Aufnahme läuft | hell | Marken **pulsieren mit dem Pegel** (Mikrofon-RMS, geglättet) | Cyan | "Ich höre zu …" |
| `thinking` | STT/LLM läuft | Kern hell, stabil | eine Marke wandert langsam im Kreis (2 s pro Umlauf) | Bernstein | "Ich denke nach …" |
| `speaking` | TTS spielt | hell | Marken als **Wellenform** der Ausgabe (RMS), Barge-in möglich | Bernstein hell | "Ich spreche." |
| `asking` | Freigabe (`ASK`) wartet | Kern hell | Ring geschlossen, langsames Halten (kein Puls) | Bernstein | "Wartet auf deine Freigabe." |
| `alarm` | unbekannte Stimme / Sicherheitsereignis | Kern rot | Ring rot, **einmal** kurz auffüllen, dann ruhig | Rot | "Stimme nicht erkannt. Keine Antwort." |
| `halted` | Notaus aktiv | Kern grau, durchgestrichen | Ring offen | Grau + Rot-Rand | "NOTAUS aktiv. Zum Fortfahren aufheben." |
| `offline` | Backend nicht erreichbar | Kern grau | Ring gestrichelt | Grau | "Backend nicht erreicht." + Knopf "Erneut versuchen" |
| `restricted` | Setup-Schritt übersprungen (Zusatz zu `idle`) | wie `idle` | kleines Schloss am Ring | Bernstein gedämpft | z. B. "Sprechen gesperrt: keine Stimme eingeschrieben." |

Übergänge dauern `--t-base` (220 ms) mit `--ease`; Farbwechsel überblenden, Formwechsel nicht springen lassen.
`alarm` und `halted` haben Vorrang vor allen anderen Zuständen und lassen sich nur durch das Backend verlassen.

## Eingaben
- Pegel/Wellenform kommen als **Strom von Zahlen** (0 bis 1, 20 bis 30 Werte pro Sekunde) vom Backend. **Nie Audio** zur UI.
- Glätten: exponentiell (Anstieg schnell, Abfall langsam), damit nichts flackert.
- Ohne Daten (`offline`) bewegt sich nichts.

## Zeichnen
- Canvas 2D, `devicePixelRatio` beachten, ein `requestAnimationFrame`-Loop, 60 fps nur bei Bewegung; im `idle` auf 30 fps drosseln.
- **Pausieren**, wenn `document.hidden` oder das Fenster minimiert ist (Tauri: Fokus-/Sichtbarkeitsereignis); danach nahtlos weiter.
- Budget: Leerlauf < 2 % CPU, Sprechen < 6 % CPU auf dem Zielrechner, keine Speicherzunahme über Stunden (Objekte
  wiederverwenden, nichts pro Frame allokieren).
- Größen: Overlay 160 px, Dashboard 240 bis 320 px, Setup 120 px. Ring skaliert proportional, Marken min. 3 px.

## Barrierefreiheit
- Der Avatar ist `role="img"` mit `aria-label` = aktuelle Textzeile; die Textzeile ist eine `aria-live="polite"`-Region
  (`alarm` und `halted` als `assertive`).
- `prefers-reduced-motion`: kein Atmen, keine wandernde Marke, kein Auffüllen. Stattdessen **statische Bilder je Zustand**
  (Marken-Anzahl und Farbe zeigen den Zustand, `listening`/`speaking` zeigen einen festen Pegelbalken neben dem Avatar).
- Jeder Zustand unterscheidet sich auch ohne Farbe: Form des Rings (geschlossen/offen/gestrichelt/Schloss/Kreuz) plus Text.

## Tests
- Komponententest je Zustand (Snapshot der Textzeile, `aria-label`, Klassen), Übergangsregeln (`alarm`/`halted` Vorrang).
- Ein Test, dass bei `reduced-motion` keine `requestAnimationFrame`-Schleife läuft.
- Messung der Leerlauf-CPU im Bericht angeben (oder sagen, dass sie nicht messbar war).
