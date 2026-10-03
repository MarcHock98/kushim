# Abnahme-Checkliste (vor jedem Merge von UI-Änderungen)

Jeder Punkt wird **geprüft und belegt** (Befehl, Test, Screenshot), nicht angenommen. Nicht Prüfbares (Mikrofon, fehlende
Toolchain) ausdrücklich als "nicht geprüft" melden.

## Sicherheit
- [ ] Notaus sichtbar in jedem Fenster/Modus, ein Klick, kein Bestätigungsdialog; Aufheben getrennt mit Bestätigung
- [ ] Freigabe-Leiste zeigt den exakten Text, Ablaufzeit, Standardfokus auf Ablehnen, Esc = Ablehnen, kein "Immer"
- [ ] Kein Schlüssel, Token, Stimmprofil oder Audio in UI, Logs, Fehlern, `localStorage` (Suche im Code und im Bundle)
- [ ] Nur `ws://127.0.0.1`: Test auf `fetch`/`XMLHttpRequest`/`http(s)://`; keine CDNs, Fonts, Bilder oder Skripte von außen
- [ ] Kein `innerHTML`/`dangerouslySetInnerHTML`; fremde Texte als Text; Links erst nach Klick
- [ ] Die UI führt nichts selbst aus (nur Anfragen); neue Anfrage-Typen sind im Backend im Default-Deny-Dispatch registriert
- [ ] Alarm, Notaus und Offline sind erkennbar ohne Farbe

## Gestaltung
- [ ] Nur Tokens (`rg "#[0-9a-fA-F]{3,6}" ui/src --glob '!tokens.css'` ist leer)
- [ ] `python .claude/skills/kushim-ui-design/scripts/contrast.py ui/src/styles/tokens.css` besteht
- [ ] Eine Hauptsache je Bildschirm, ein Primärknopf je Bereich, 4-px-Raster, Text >= 12 px (Fließtext 16 px)
- [ ] Alle Zustände vorhanden: leer, lädt, Erfolg, Fehler, offline, Notaus, eingeschränkt
- [ ] Texte Deutsch, Du-Form, ohne Ausrufezeichen/Emoji; Fehler nennen den nächsten Schritt; Dezimalkomma

## Bedienung und Barrierefreiheit
- [ ] Alles per Tastatur erreichbar, Reihenfolge logisch, Fokusring immer sichtbar, Klickflächen >= 44 px
- [ ] Dialoge/Freigabe: Fokusfalle, Esc, Fokus kehrt zurück
- [ ] Screenreader: Avatar `role="img"` + Live-Region, Balken `role="meter"`, Status mit Text, Toasts `status`/`alert`
- [ ] `prefers-reduced-motion` und `prefers-contrast: more` geprüft (statische Zustandsbilder, kräftigere Linien)
- [ ] Skalierung 200 % und Fensterbreiten 360, 800, 1440 px ohne Abschneiden (Screenshots abgelegt oder beschrieben)

## Leistung
- [ ] Avatar pausiert bei verdecktem/minimiertem Fenster; Leerlauf-CPU < 2 % (gemessen) und kein Speicherwachstum
- [ ] Kein WebGL ohne Begründung; Bundle ohne unnötige Pakete (Größe im Bericht)

## Tests und Abschluss
- [ ] Komponententests je Komponente und je Avatar-Zustand; Setup-Schritte mit Mock-Backend
- [ ] `pytest` grün (inkl. `tests/test_no_egress.py`), UI-Tests grün
- [ ] `kushim-safety-review` ausgeführt, Ergebnis im Bericht
- [ ] Roadmap/Doku aktualisiert, lokal gemergt, **nicht gepusht**
