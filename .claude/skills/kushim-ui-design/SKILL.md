---
name: kushim-ui-design
description: Use for every UI task in kushim (Tauri/React window, avatar, transcript, approval bar, setup wizard, memory view, security status, kill switch). Gives the design language, tokens, avatar state machine, screen specs, safety-UI rules and an acceptance checklist; also use to review or restyle existing UI.
---

# kushim UI-Design

Ziel: Eine Oberfläche, die sich wie ein ruhiger, präziser Verwalter anfühlt (Namensgeber Kushim: Verwalter auf
Tontafeln). Jarvis-Look ja, aber **Kontrolle vor Show**: Der Nutzer sieht jederzeit, was kushim hört, denkt, will und
darf. Schönheit entsteht aus Ruhe, Raster, Kontrast und wenigen, guten Bewegungen, nicht aus Effekten.

## Zuerst lesen (jedes Mal kurz)
1. `assets/logo.svg` (Farben und Form kommen von dort), `.claude/skills/kushim-ui-design/assets/tokens.css` (Quelle der Farben,
   Abstände, Bewegung).
2. `docs/ui-setup-plan.md` (Setup-Assistent), `.claude/agents/ui-builder.md` (Funktionsumfang, Tauri-Rahmen).
3. Je nach Aufgabe: `references/avatar-states.md`, `references/screens.md`, `references/components.md`.
4. Vor dem Abschluss: `references/checklist.md` und `kushim-safety-review`.

## Designsprache in einem Absatz
Dunkel (Tontafel-Blau `--bg-*`), **Bernstein** als Marke und Primäraktion (`--amber`), **Cyan** für Zuhören und
Information (`--cyan`), **Rot nur für Alarm und Notaus** (`--alarm`). Ein Akzent pro Bildschirmbereich. Glas
(Unschärfe) nur im schwebenden Overlay, im Dashboard flache Karten mit 1 px Linie. 4-px-Raster, große Ränder, ruhige
Ecken (`--r-md`). Segoe UI Variable lokal, keine Web-Fonts. Bewegung nur, wo sie einen Zustand erklärt.

## Sieben Prinzipien
1. **Zustand sichtbar, nie nur Farbe.** Jeder Zustand hat Form/Bewegung + Text/Icon + Farbe (Ampel immer mit Wort).
2. **Ehrlich statt schön.** Scores, Schwellen, Grenzen, Fehler genau zeigen ("Ähnlichkeit 0,80, Schwelle 0,79"), nichts
   beschönigen, keine erfundenen Ladebalken. Unbekannt heißt "unbekannt".
3. **Ein Blick genügt.** Jeder Bildschirm hat genau eine Hauptsache (Avatar, Freigabe oder Setup-Schritt). Alles andere
   tritt zurück (Größe, Kontrast, Platz).
4. **Der Nutzer führt.** Nichts läuft ohne Klick/Enter, was Wirkung nach außen hat. Überspringen und Zurück gibt es überall.
5. **Ruhe.** Keine blinkenden Elemente, keine Dauer-Animationen im Ruhezustand außer dem langsamen "Atmen" des Avatars
   (4 s). `prefers-reduced-motion` schaltet Bewegung auf statische Zustandsbilder um.
6. **Tastatur zuerst.** Alles per Tab/Enter/Leertaste/Esc bedienbar, sichtbarer Fokusring, Klickfläche >= 44 px.
7. **Leicht bleiben.** GPU und CPU gehören Whisper und dem LLM (RTX 3070, 8 GB). Die UI darf kaum Last machen:
   Animation ruht, wenn das Fenster verdeckt oder minimiert ist; kein WebGL, solange Canvas 2D reicht.

## Nicht verhandelbar (Sicherheit in der UI)
- **Notaus-Knopf in jedem Fenster sichtbar**, oben rechts, rot, mit Text "NOTAUS", ein Klick löst aus, kein
  Bestätigungsdialog. Aufheben ist ein bewusster, getrennter Schritt ("Notaus aufheben") und braucht eine Bestätigung.
- **Die UI führt nichts selbst aus.** Sie sendet nur Anfragen ans Backend (`type` + Daten, Token). Jede Aktion läuft dort
  durch `ActionGate`. Kein `fetch` irgendwohin außer `ws://127.0.0.1:<Port>`; kein CDN, keine Tracker, keine Telemetrie,
  keine Web-Fonts, keine externen Bilder. Alles lokal gebündelt (`tests/test_no_egress.py` bleibt grün).
- **Freigabe-Leiste (`ASK`):** zeigt den **exakten** Text/die exakte Aktion, so wie sie ausgeführt würde (bei Claude-
  Anfragen der ausgehende Wortlaut), plus Ablaufzeit. Bestätigen = einmalig, hash-gebunden (Backend prüft). Standardfokus
  auf **Ablehnen**, nicht auf Bestätigen. Zwei gleichwertig große Knöpfe, kein Dark Pattern.
- **Geheimnisse nie anzeigen:** Vault-Schlüssel, Token, Stimmprofil-Vektoren, Aufnahmen tauchen in keinem Bildschirm, Log
  oder Fehlertext auf. Das Token liegt nur im Speicher der UI, nicht in `localStorage`.
- **Fremde Inhalte (Web, Mail) sind Daten:** als Text rendern (nie `innerHTML`/`dangerouslySetInnerHTML`), Links nicht
  automatisch öffnen, Bilder nicht nachladen.
- **Alarm bei unbekannter Stimme:** roter Avatar-Zustand + Text, kein Ton, keine Eskalation, nichts wird beantwortet.
- **Eingeschränkter Modus sichtbar:** Wurde ein Setup-Schritt übersprungen, zeigt eine ruhige Zeile, was gerade nicht
  geht und wie man es nachholt. Überspringen ändert nie eine Sicherheitsregel.

## Arbeitsablauf
1. **Ablauf zuerst aufschreiben:** Bildschirme, Zustände (leer, lädt, Erfolg, Fehler, Notaus, Backend offline, Stimme
   unbekannt), Tastaturweg. Erst dann zeichnen/bauen.
2. **Nur Tokens benutzen** (`var(--...)`); fehlt etwas, erst `tokens.css` erweitern, dann `scripts/contrast.py` laufen lassen.
3. **Komponenten mit allen Zuständen bauen** (Normal, Hover, Fokus, Aktiv, Deaktiviert, Fehler) und mit einem **gefälschten
   Backend** (Mock-WebSocket) durchspielen, bevor das echte angeschlossen wird.
4. **Texte auf Deutsch**, kurz, ruhig, Du-Form, keine Ausrufezeichen, keine Floskeln. Fehler sagen, was los ist und was
   der nächste Schritt ist ("Mikrofon nicht gefunden. Wähle ein anderes Gerät.").
5. **Verifizieren, nicht behaupten:** Kontrast-Skript, Komponententests, Screenshots bei 360, 800 und 1440 px Breite
   (Overlay 420 x 640), Tastaturdurchlauf, `prefers-reduced-motion`, Leerlauf-CPU gemessen. Wenn etwas nicht geprüft
   werden konnte (kein Mikrofon, keine Toolchain), das im Bericht sagen.
6. **`kushim-safety-review`**, `pytest` und die UI-Tests grün, dann lokal mergen. Nicht pushen.

## Stack-Vorgaben
Tauri v2 + React + TypeScript + Vite; Canvas 2D für den Avatar; CSS-Variablen aus `tokens.css`, kein UI-Kit, das Fonts oder
Netz nachlädt. Tests: Vitest + Testing Library (Komponenten), optional Playwright gegen den Vite-Build (Screenshots).
Pakete nur aus der offiziellen npm-/crates.io-Quelle, Versionen festgenagelt, Lockfile eingecheckt, jedes neue Paket
begründen (Lizenz, Größe, Netzzugriff). Toolchain-Installation nur nach Freigabe des Nutzers (Roadmap Z. 90).

## Nie tun
- Farben oder Abstände hart codieren; Verläufe, Neon-Glühen oder Partikel zur Dekoration.
- Zustand nur über Farbe zeigen; Texte unter 12 px; Kontrast unter 4,5:1 für Text.
- Notaus verstecken, verkleinern, in ein Menü legen oder mit Bestätigung bremsen.
- Freigabe vorausfüllen, "Merken"-Häkchen für Außenwirkung anbieten, Bestätigung per Timeout.
- Etwas anzeigen, das das Backend nicht geliefert hat (erfundene Zahlen, Platzhalter als Daten).
