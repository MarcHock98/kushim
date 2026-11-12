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
`models/speaker` und `models/piper-cohort` (Papierkorb). Telemetrie-Sperre aus `.claude/settings.json` (für Remote Control).

## Offen
- UI-Design auf Branch `claude/ui-design-artifact-b1cd06` (neues Design, Systemzustand-Panel, Logo, Plan für dynamische UI
  in `docs/ui-dynamic-plan.md`): nicht gemerged, wartet auf das OK des Nutzers.
- „Modus C“-Schalter (`claude_enabled`) noch in Config und UI-Sicherheitsanzeige: entfernen, sobald das UI-Design gemerged ist
  (sonst Konflikt mit dem UI-Branch).
- Z3 für den Nutzer: `py scripts\claude_setup.py --project . --statusline --test-hook`.
