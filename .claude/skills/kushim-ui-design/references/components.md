# Komponenten

Alle nur mit Tokens. Jede Komponente hat Zustände: Normal, Hover, Fokus (`--focus-ring`), Aktiv, Deaktiviert, Fehler,
und einen Komponententest. Klickfläche >= `--hit` (44 px), auch wenn das Zeichen kleiner ist.

## Knöpfe
| Variante | Aussehen | Einsatz |
|---|---|---|
| Primär | Fläche `--amber`, Text `--amber-ink`, `--r-pill` | genau eine pro Bereich (Weiter, Erlauben) |
| Sekundär | transparent, 1 px `--line-strong`, Text `--text` | Zurück, Ablehnen, Überspringen |
| Ghost | nur Text `--text-muted`, Unterstreichung bei Hover | Nebenaktionen |
| Gefahr | Fläche `--alarm`, Text `--alarm-ink` | **nur** Notaus und endgültiges Löschen |
Deaktiviert: 40 % Deckkraft **und** `aria-disabled` mit Grund im Tooltip ("Erst den Schlüssel sichern"). Hover hellt 6 % auf,
Aktiv dunkelt 6 % ab, Übergang `--t-fast`. Lädt: Text bleibt, kleiner Fortschrittsring, Breite ändert sich nicht.

## Ampelzeile (Status)
Icon (✓ ! ✕ als SVG, nicht Emoji) + Wort ("In Ordnung", "Achtung", "Fehler") + Farbe + Detailtext + optional Behebungs-Link.
Reihenfolge der Dringlichkeit: Fehler, Achtung, in Ordnung. Nie nur ein farbiger Punkt.

## Pegel- und Trefferbalken
Horizontaler Balken in `--bg-3`, Füllung `--cyan` (Eingang) oder `--amber` (Ausgang), Schwelle als senkrechter Strich mit
Beschriftung, Zahl rechts (`--font-mono`). Glätten wie beim Avatar. `role="meter"` mit `aria-valuenow/min/max`.
Treffer (Wake Word): Zeile "hey kushim, 14:03:22" erscheint 3 s, danach in einer Liste.

## Transkript-Blase
Rand links 3 px (Cyan = Du, Bernstein = kushim), Text `--fs-md`, Zeitstempel `--fs-xs` muted, max. Breite 70 ch. Fließtext
als Text rendern (React-Standard, nie HTML einsetzen). Aktionen (Kopieren, Daumen) erscheinen bei Hover **und** Fokus.

## Toast
Unten mittig, `--bg-3`, 1 px `--line`, 4 s (Fehler bleibt bis Klick), `role="status"` (Fehler `role="alert"`), Aktion
"Rückgängig" wo möglich. Maximal 3 gestapelt, nie über Notaus oder Freigabe-Leiste.

## Dialog
Nur für Entscheidungen, die den Fluss unterbrechen müssen (Notaus aufheben, endgültig löschen, Vault zurücksetzen).
Fokusfalle, Esc schließt (= Abbrechen), Hintergrund 60 % abgedunkelt, Titel = Frage, Knopf-Text = Verb ("Löschen",
nicht "OK"). Standardfokus auf die sichere Wahl.

## Eingabefelder
Beschriftung **über** dem Feld (nie nur Platzhalter), Rahmen `--line-strong`, Fokus Amber-Ring, Fehler `--alarm` + Text unter
dem Feld + `aria-describedby`. Texteingabe für kushim: mehrzeilig wachsend bis 6 Zeilen, Enter sendet.

## Karten, Chips, Tabs
Karte siehe `screens.md`. Chip: `--r-pill`, 1 px Linie, Icon + Text. Tabs: Pfeiltasten wechseln, aktiver Tab mit 2 px Amber-
Unterstreichung **und** fettem Text. Seitenleiste: aktives Element mit Amber-Balken links und Text.

## Icons
Eigene kleine SVG-Sätze (24 px Raster, 1,75 px Strich, runde Enden), eingebettet, `aria-hidden` wenn Text daneben steht,
sonst `aria-label`. Keine Icon-Fonts, keine externen Sprites.

## Bewegung
Nur `--t-fast/base/slow` und `--ease`. Erlaubt: Ein-/Ausblenden, 8 px Verschieben, Skalieren bis 3 %. Verboten: Springen,
Schütteln, Parallax, Dauer-Glühen. Bei `prefers-reduced-motion` ohne Dauer.

## Dateiaufbau (Vorschlag für `ui/`)
```
ui/
  src/styles/tokens.css        # Kopie aus dem Skill, nie abweichen
  src/components/              # eine Datei je Komponente + .test.tsx
  src/screens/                 # Overlay, Dashboard, Memory, Security, Setup
  src/avatar/                  # Zustandsautomat (rein, testbar) + Canvas-Zeichnung
  src/backend/client.ts        # einzige Stelle mit WebSocket (127.0.0.1, Token im Speicher)
  src/backend/mock.ts          # gefälschtes Backend für Entwicklung und Tests
```
`client.ts` ist die **einzige** Netzwerkstelle; ein Test prüft, dass sonst nirgends `fetch`, `XMLHttpRequest`, `WebSocket`
oder `http(s)://` außer `ws://127.0.0.1` vorkommt.
