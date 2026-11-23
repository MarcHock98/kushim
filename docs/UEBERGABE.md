# Übergabe 2026-11-12: schlanker Sprachassistent mit Claude Code als Gehirn

Plan: [ROADMAP.md](../ROADMAP.md). Frühere Übergaben stehen in der Git-Historie dieser Datei.

## Stand
- **Start:** `kushim` (oder Verknüpfung **kushim**) öffnet Claude Code mit dem kushim-Channel im Fenster „kushim-Claude“,
  startet das Zuhören und die Oberfläche. Fenster zu = alles aus. `kushim start --no-ui` ohne Oberfläche.
- **Kette:** Wake Word (KWS für eigene Wörter, OpenWakeWord für fertige Wörter) → Whisper → Claude Code (Channel, Antwort
  über das Werkzeug `sprich`) → Kokoro „Martin“ (eigener Worker-Prozess, `voice/ttsworker.py`). „abbrechen“, „das war's“, „beende dich“, Notaus.
- **Keine Sprecher-Prüfung:** jede Stimme kann Befehle geben. Freigaben nie per Stimme: Claude-Fenster oder Freigabe-Leiste
  der Oberfläche; Anfragen werden einmal angesagt.
- **Gedächtnis:** verschlüsselter Vault (Audit, Feedback, Freigabe-Protokoll, Gedächtnis-Ansicht der UI) bleibt.
- **Netz:** kushim selbst nur 127.0.0.1 (ALLOWLIST `net/loopback.py`, `net/server.py`, `channel/server.py`).

## Entfernt seit der letzten Übergabe (Nutzerwünsche)
Stimmklon (Code, Doku, `tools/chatterbox`, Aufnahmen), Sprecher-Prüfung (Einschreiben, Profil, Modelle), Freigaben per
Stimme (`permission_voice`, `voice_policy`), `sanitize.py`, alte Pläne und Recherchen (Git-Historie), alte Modelle
`models/speaker` und `models/piper-cohort` (Papierkorb), der Schalter „Modus C“ (`claude_enabled`, `kushim claude enable/disable`,
Chip und Zeile in der Oberfläche; die Sicherheitsanzeige nennt jetzt fest „Gehirn: Claude Code“). Telemetrie-Sperre aus `.claude/settings.json` (für Remote Control).

## Oberfläche (UI-Branch, hier gemerged)
Design „Jarvin Cockpit“ (Artifact des Nutzers), Details und Pläne: `docs/ui-dynamic-plan.md`, `docs/ui-p2-plan.md`.
- **Aussehen:** Tokens in `ui/src/styles/tokens.css` (Kopie im Skill `kushim-ui-design`, Kontrastskript angepasst). Cyan = kushim,
  Bernstein = Nutzer und Freigaben, Rot nur Alarm und Notaus. Lokale Schriften (Bahnschrift, Segoe UI Variable, Cascadia Mono).
- **Logo:** Mini-Orb, erzeugt von `scripts/make_icon.py` (SVG, PNG, ICO, Header); Tauri-Icons per `npx tauri icon`.
- **3D-Kern (P1):** `ui/src/components/Core3D.tsx`, three.js 0.170.0 (lazy geladen), ohne K; ohne WebGL der 2D-Orb `Avatar.tsx`.
  Bühne: im Gespräch nur der große Kern; zeigt Claude etwas, rückt er klein zur Seite (View Transition).
- **Systemzustand:** API `system.stats` (`src/kushim/api/system_api.py`, nur lokale Windows-Messwerte, `nvidia-smi`), Panel
  `SystemPanel.tsx`; Claude zeigt es über den Baustein `systemzustand`.
- **`zeige` (P2, größtenteils fertig):** Werkzeug im Channel, Schema `src/kushim/stage/schema.py` (zweimal geprüft: Channel und
  Bridge), `stage.get` (`api/stage_api.py`), Ansichten antwort, rechnung (KaTeX 0.16.11, `trust: false`), markt, recherche
  (`ui/src/components/stage/*`). `/reply` liefert jetzt `texts`, `permissions`, `views`, `final`.
- **Verlauf und Claude-Panel** stehen in der Übersicht (auf dem Start nur der Kern). Demo im Browser: `?mock&demo`.

## Offen
- **P2 zu Ende:** Vitest-Tests je Ansicht und der Regeltest für KaTeX sind da (`ui/src/views.test.tsx`,
  `tests/test_ui_rules.py`). Im Browser (`?mock&demo`, Dev-Server `kushim-ui` in
  `.claude/launch.json`) bei 375/800/1440 px angesehen; dabei behoben: Karte und Hauptbereich teilten die Klasse `view`
  (jetzt `view-card`), Diagramm-Linie lief über das Gitter, Achsentitel überdeckte eine Zahl. Offen: echtes Tauri-Fenster
  und GPU-Last neben Whisper (nicht gemessen). Danach P3 bis P6 laut `docs/ui-dynamic-plan.md` (je erst Detailplan, dann OK).
- **P3a ist gebaut** (`docs/ui-p3-plan.md`, Abschnitt 8): Arten `auftrag` und `mail`, Bausteine `fortschritt`, `aufgaben`,
  `zeitplan`, `mail`, `mail-entwurf`, `countdown` (Schema, Channel-Beschreibung, `ui/src/components/stage/Live.tsx`). Das alte
  Claude-Panel ist entfernt, `FolderPanel.tsx` zeigt die Ordner. Offen: echter Aufruf durch Claude Code, Tauri-Fenster;
  P3b (Dokument und Diff aus Dateien) braucht einen eigenen Plan mit Audit.
- Zwei Wackler-Tests behoben (nur Tests geändert): Der 413-Test im Channel schickt keinen großen Körper mehr mit (der Server
  schloss mitten im Senden, 1 von 400 Läufen brach ab); der UI-Test zur Knopfsperre prüft im selben Schritt, in dem die
  Leiste erscheint. Beim UI-Test ist die Ursache plausibel, aber nicht nachgestellt.
- **P3b ist gebaut** (`docs/ui-p3b-plan.md`, Abschnitt 8): Art `dokument`, Bausteine `dokument` und `aenderung`, Sperre für
  Dateinamen mit Zugangsdaten. kushim liest selbst keine Dateien; „lies mir die Datei und gib eine Übersicht“ erledigt Claude Code
  (Hinweis in `INSTRUCTIONS`). Phase D der Roadmap ist geschlossen (2026-11-13). Offen: echter Aufruf durch Claude Code,
  Tauri-Fenster, nächste UI-Phasen P4 bis P6 (je erst Plan, dann OK).
- **P4a ist gebaut** (`docs/ui-p4-plan.md`, Abschnitt 8): 3D-Szene aus einfachen Körpern (`szene3d`, art `modell`) mit Drehen,
  Schnitt, Vorher/Nachher und Objektliste, und Plan aus Linien, Kreisen, Maßen (`plan2d`, art `plan`) mit Ebenen und Zoom.
  Fehler in einem Baustein leeren das Fenster nicht mehr (`BlockGuard`). Offen: GPU-Last des Betrachters neben Whisper,
  Tauri-Fenster, echter Aufruf durch Claude Code; P4b (echte `.stl`/`.glb`-Dateien) nur auf Wunsch; P5 und P6 je erst Plan.
- **P6:** Detailplan `docs/ui-p6-plan.md` liegt zur Freigabe vor (P6a: Vergleich, Zeitstrahl, Übersetzung, Lernkarten, Quiz, Anleitung;
  P6b: Diagramme wie Abläufe und Mindmaps mit eigener Anordnung). Sechs Entscheidungen am Ende, u. a. Ton für Timer.
- Nutzerregel: bei UI-Arbeit erst ein Plan, dann die Freigabe, dann der Code.
- Z3 für den Nutzer: `py scripts\claude_setup.py --project . --statusline --test-hook`.
