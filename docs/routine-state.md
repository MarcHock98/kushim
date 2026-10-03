# Routine-Zustand

Wird von `/kushim-routine` gepflegt. Keine Geheimnisse, keine Datenpfade.

- Letzter Durchlauf: 2026-10-03 (/loop kushim-routine, Wake-Word-Sprachbefehle; Loop auf Wunsch des Nutzers danach gestoppt)
- Aktueller Branch: master (routine/p1-wake, p1-stt, p1-speaker, p1-dialog, p1-tts, p2-api-core, p2-approvals, p4-bandit, p2-loopback, p1-llm, p1-whisper-model, p1-ollama-setup, branding, p1-piper, p2b-launcher, p2b-icon, p2b-killswitch, p1-pipeline, p1-audio, p1-talk, p1-streaming, p1-wake-only, p1-speaker-model, voice-record, readme-installer gemerged, Branches bleiben)
- Erledigt: Stimmkette (Wake Word, Sprecher, STT, LLM, TTS), Notaus, Launcher, Verknüpfungen, README/Installer, Umbenennung kushim, Wake-Word-Sprachbefehle. 195 Tests grün
- Erledigt zusätzlich: Dialog-/Barge-in-Logik, TTS-Logik, API-Kern (Token/Dispatch), Freigabe-Warteschlange, 136 Tests grün
- Nächster Schritt: Nutzer: Live-Test der Wake Words (`kushim talk`), danach `threshold`/`boost` in `wakewords.toml` nachstellen. Autonom danach: Stimmklon (Torch/CUDA >2 GB, vorher fragen), Tauri/Node-UI
- Branches bereit zum Push durch den Nutzer: master, routine/p1-wake, routine/p1-stt, routine/p1-speaker, routine/p1-dialog, routine/p1-tts, routine/p2-api-core, routine/p2-approvals, routine/p4-bandit, routine/p2-loopback, routine/p1-llm

## Slack
- Nutzer-ID / Kanal-ID: nicht verwendet. Verbundenes Slack-Konto hat andere Mail (Arbeits-Workspace) als die Git-/Claude-Mail, Empfänger unsicher, daher nichts gesendet

## Offene Fragen an den Nutzer
- (keine)

## Blockiert
- Live-Mikrofon-Test: nur der Nutzer kann ihn ausführen

## Probleme und Versuche
- openwakeword braucht `requests` trotz --no-deps (gelöst, in pyproject-Extra `voice`)

## Entscheidungen des Nutzers
- 2026-10-03: Wake Words: "hey kushim", "kushim", "kush", "hallo kush", "hi kushim", "kushi"; kein "hey jarvis"; alles in einer zentralen Config (`wakewords.toml`). Umgesetzt mit freier Erkennung (kws), Trefferquote nur auf synthetischer Stimme gemessen
- 2026-10-03: Eine kurzzeitige Umbenennung wurde zurückgenommen, alle Reste entfernt. Name bleibt **kushim** (Paket `kushim`, CLI `python -m kushim.cli`). Das zusätzliche Schlüsselbund-Duplikat hat der Nutzer selbst gelöscht; der Hauptschlüssel `kushim-vault` ist vorhanden
- 2026-10-03: Nutzer pusht selbst (kein Push durch die Routine, auch nicht auf Zuruf; Befehl wurde abgebrochen); README mit 1:1-Anleitung und Installationsskript gewünscht, umgesetzt; Umbenennung auf kushim (inkl. GitHub-Repo) gewünscht, noch offen. Der Vault existiert bereits (`~/kushim-vault`, Schlüssel unter Service `kushim-vault`): beim Umbenennen Rückwärts-Kompatibilität nötig
- 2026-10-03: Wake Words per Sprache: Auswahl vortrainierter Wörter plus eigenes lokales Training neuer Wörter (Hintergrund, nur verifizierte Stimme, Bestätigung)
- 2026-10-03: Wake Words sollen per Sprache an kushim gesagt und gespeichert werden können (Umsetzungsweg offen)
- 2026-10-03: Stimme: eigene Stimme klonen (Einsprechen, lokales Training/Klon, nur eigene Aufnahmen); Stimmprofil für die Sprecherverifikation im verschlüsselten Vault, Einschreiben per `kushim voice enroll`
- 2026-10-03: F9/Push-to-Talk entfernt; nur Wake Word; kushim darf vor dem Wake Word nicht als LLM mithören; Wake Word allein löst eine Antwort aus; mehrere Wake Words einstellbar
- 2026-10-03: Sprecherverifikation ist wichtig: kushim soll nur auf die Stimme des Nutzers reagieren
- 2026-10-03: Wunsch nach flüssigerer Stimme, ggf. mit eigener Stimme (Einsprechen und Training)
- 2026-10-03: Live-Test `kushim talk` vom Nutzer als funktionierend gemeldet
- 2026-10-03: Live-Test mit Systemstandard-Geräten; Desktop-Verknüpfung `kushim sprechen.lnk` (talk, F9) angelegt
- 2026-10-03: Notaus als Windows-Verknüpfung und/oder Sprachbefehl; beides umgesetzt (Verknüpfung auf dem Desktop, Sprache wartet auf Pipeline)
- 2026-10-03: Start-Anwendung und Logo gewünscht; Umsetzung später nach Plan (Launcher zuerst, dann Tauri), Logo nur lokal
- 2026-10-03: Whisper large-v3-turbo laden; LLM qwen2.5:7b (Ollama) laden; Hardware RTX 3070 8 GB, 31 GB RAM
- 2026-10-03: localhost erlauben (ALLOWLIST: nur net/loopback.py, nur Loopback), umgesetzt
- 2026-10-03: eigenes Wake Word "Hey Kushim" trainieren
- 2026-10-03: privates Projekt, TTS offline: Empfehlung Piper (GPL-3 stört bei privater Nutzung nicht, gute deutsche Stimmen)
- 2026-10-03: Tauri/Node installieren und Whisper-Modell laden erlaubt, nur offizielle Quellen, Pakete/Modelle auf Datenabfluss prüfen
- Modus A (lokal) Standard, Modus C (Claude auf Befehl) Opt-in
- Gedächtnis zunächst lokal, später NAS (Modell noch offen)
- Oberste Regel: Schäden jeder Art sind verboten
