# Übergabe 2026-11-12: schlanker Sprachassistent mit Claude Code als Gehirn

Plan: [ROADMAP.md](../ROADMAP.md). Frühere Übergaben stehen in der Git-Historie dieser Datei.

## Stand
- **Start:** `kushim` (oder Verknüpfung **kushim**) öffnet Claude Code mit dem kushim-Channel im Fenster „kushim-Claude“,
  startet das Zuhören und die Oberfläche. Fenster zu = alles aus. `kushim start --no-ui` ohne Oberfläche.
- **Kette:** Wake Word (KWS für eigene Wörter, OpenWakeWord für fertige Wörter) → Whisper → Claude Code (Channel, Antwort
  über das Werkzeug `sprich`) → Piper. „abbrechen“, „das war's“, „beende dich“, Notaus.
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
- **P2 zu Ende:** Vitest-Tests je Ansicht (Formelfehler als Text, Diagramm, Markt-Hinweis, Widerspruchs-Kasten, Live-Update,
  Reiter), ein UI-Regeltest für KaTeX `trust: false`, Screenshots bei 375/800/1440 px, echtes Tauri-Fenster und GPU-Last
  neben Whisper prüfen (nicht gemessen). Danach P3 bis P6 laut `docs/ui-dynamic-plan.md` (je erst Detailplan, dann OK).
- Nutzerregel: bei UI-Arbeit erst ein Plan, dann die Freigabe, dann der Code.
- Z3 für den Nutzer: `py scripts\claude_setup.py --project . --statusline --test-hook`.
