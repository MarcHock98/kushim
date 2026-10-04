# Routine-Zustand

Wird von `/kushim-routine` gepflegt. Keine Geheimnisse, keine Datenpfade.

- Letzter Durchlauf: 2026-10-04: Claude entwickelt Projekt (Teile 1 und 2: Ordner-Freigabe, Worktree, Rückfragen, Übersichten, Diff-Prüfung), am echten Aufruf im Wegwerf-Repo geprüft; Abbruch-Befehl; Claude-Recherche mit Wikipedia-Ersatz. Loop gestoppt (Wunsch des Nutzers), alles lokal gemerged, nicht gepusht. 693 Tests grün
- Seit 2026-10-03 zusätzlich gemerged (alle lokal, nicht gepusht): Notaus beendet auch llama-server, `voice threshold`, Wake Word + Befehl in einem Zug, Gesprächsmodus ohne Wake Word, Unterbrechen (Barge-in) mit echten Pegeln, `voice level`, `kushim gpu`/[gpu], `kushim help`, `kushim`-Befehl im PATH, qwen3.5:9b (think aus), Designer-Skill, Pläne `docs/ui-llm-plan.md`, `docs/tools-plan.md`, `kushim setup`, `kushim tools`, API `setup.*`/`audio.devices`/`safety.*`/`tools.*`
- Aktueller Branch: master (routine/p2-setup-backend, routine/p3-web-plan, fluent-talk, direct-command-fix u. a. gemerged; routine/p1-wake, p1-stt, p1-speaker, p1-dialog, p1-tts, p2-api-core, p2-approvals, p4-bandit, p2-loopback, p1-llm, p1-whisper-model, p1-ollama-setup, branding, p1-piper, p2b-launcher, p2b-icon, p2b-killswitch, p1-pipeline, p1-audio, p1-talk, p1-streaming, p1-wake-only, p1-speaker-model, voice-record, readme-installer gemerged, Branches bleiben)
- Erledigt: Stimmkette (Wake Word, Sprecher, STT, LLM, TTS), Notaus, Launcher, Verknüpfungen, README/Installer, Umbenennung kushim, Wake-Word-Sprachbefehle. 195 Tests grün
- Erledigt zusätzlich: Dialog-/Barge-in-Logik, TTS-Logik, API-Kern (Token/Dispatch), Freigabe-Warteschlange, 136 Tests grün
- 2026-10-04: Branch routine/voice-tools-list: Werkzeuge per Sprache (Liste, Recherche, Claude steuern, Ansagen), 742 Tests grün; Live-Test mit Mikrofon steht aus (Nutzer).
- Nächster Schritt: **Stimmklon mit Chatterbox** (vom Nutzer freigegeben, Auflage: beim Klonen nichts nach außen; Loop erst neu starten, wenn der Nutzer es will). Danach Recherche in die Sprach-Pipeline hängen, Claude entwickelt Projekt (Teile 1 bis 4 laut `docs/claude-cli-plan.md`, vorher Entscheidungen des Nutzers: Rechteprofil, Budget/Zeit, Ordner), Modellwechsel Teil 2, UI-Setup Teil 2, Timer/Notizen. Nutzer: Live-Test `kushim research` (echter Claude-Aufruf, bisher nicht gemacht), Zweite-Person-Test der Sprecher-Prüfung
- Branches bereit zum Push durch den Nutzer: master, routine/p1-wake, routine/p1-stt, routine/p1-speaker, routine/p1-dialog, routine/p1-tts, routine/p2-api-core, routine/p2-approvals, routine/p4-bandit, routine/p2-loopback, routine/p1-llm

## Slack
- Nutzer-ID / Kanal-ID: nicht verwendet. Verbundenes Slack-Konto hat andere Mail (Arbeits-Workspace) als die Git-/Claude-Mail, Empfänger unsicher, daher nichts gesendet

## Offene Fragen an den Nutzer
- 2026-10-04: Websuche nur Wikipedia (de)? Allgemeine Websuche später (z. B. eigener SearXNG auf dem NAS) oder gar nicht? Claude als Rechercheur (Konto/Schlüssel/Monatslimit)? Siehe `docs/tools-plan.md`
- 2026-10-04: Backend-Transport (WebSocket 127.0.0.1) braucht Importe außerhalb des festgelegten Satzes von `net/loopback.py`; Lockerung des Tests nur mit ausdrücklicher Zustimmung (die Freigabe vom 2026-10-03 galt dem Loopback-Client)

## Blockiert
- Live-Mikrofon-Test: nur der Nutzer kann ihn ausführen
- Backend-Transport (WebSocket): wartet auf Freigabe der Egress-Sperre (siehe oben)
- Tauri-UI: Toolchain-Installation (Node/Rust) noch nicht durchgeführt

## Probleme und Versuche
- openwakeword braucht `requests` trotz --no-deps (gelöst, in pyproject-Extra `voice`)

## Entscheidungen des Nutzers
- 2026-10-04: **Claude primär für Recherche (bessere Websuche), Wikipedia als Ersatz**; Claude über die Claude CLI des angemeldeten Nutzers (kein API-Schlüssel); soll in angegebenen, in der UI einstellbaren Ordnern arbeiten, per Sprache gesteuert werden (starten, Rückfragen, Übersichten, nächste Schritte); Plan `docs/claude-cli-plan.md`
- 2026-10-04: **Abbrechen per Sprache** ("abbrechen" beendet den laufenden Befehl) zusätzlich zum Notaus; umgesetzt
- 2026-10-04: Stimmklon mit **Chatterbox** freigegeben, beim Klonen dürfen keine Daten nach außen gehen
- 2026-10-04: Roadmap nach jedem Paket pflegen und am Ende vollständig durchsehen (erledigt)
- 2026-10-04: `net/web.py` freigegeben, **keine Downloads erlauben** (nur Text/JSON, nie auf die Platte); Websuche über Wikipedia (de), Tool standardmäßig aus
- 2026-10-04: **Web-Inhalte dürfen nie als Prompt/Anweisung genutzt werden, um das LLM etwas tun oder Tools nutzen zu lassen**; umgesetzt als Quarantäne (`Untrusted`, werkzeugloser Antwortpfad `web/answer.py`, Tests)
- 2026-10-04: Werkzeuge (Tools) sollen über die UI aktivierbar sein: alle standardmäßig aus, Einschalten nur bewusst durch den Nutzer; erstes Tool Recherche/Web mit Vorschau und Freigabe dessen, was nach außen geht. Umgesetzt (Logik), Netz-Modul wartet auf Freigabe
- 2026-10-04: Modelle bleiben in Ollamas Speicher `models/ollama` (kein Ordner je Modell); Verwaltung in der UI nur über die Ollama-Schnittstelle. LLM `qwen3.5:9b` aktiv (think aus), `qwen2.5:7b` bleibt installiert; GPU bleibt für Whisper und LLM (kein Auslagern auf CPU)
- 2026-10-04: Flüssiges Gespräch: ohne Wake Word nach Antwort (`follow_up_seconds`), Unterbrechen per Sprechen, Wake Word + Befehl in einem Zug; Nutzer meldet "flüssiger"; `listen_seconds` 15 s nach "Ja?"
- 2026-10-04: UI-Planung: Nach dem Start der Anwendung soll ein Setup erscheinen (beim ersten Start, danach wiederholbar), mit Systemcheck+Vault/Schlüssel, Mikrofon/Lautsprecher+Stimme einschreiben, Wake Words, Sicherheit+Notaus; alles überspringbar (Sprechen bleibt ohne Stimmprofil gesperrt). Plan: docs/ui-setup-plan.md
- 2026-10-04: Beim Einschreiben/Aufnehmen will der Nutzer selbst bestätigen, wann ein Absatz fertig ist (Enter), nicht per Stille. Umgesetzt (Standard), `--auto` bleibt
- 2026-10-04: Stimmerkennung neu gestalten: Sprecher-Prüfung UND längere Spracheingabe; Einschreiben mit den 10 Klon-Absätzen (~5 Min); längere Äußerung = sicherer (Änderungen nur bei "stark"). Umgesetzt (Profil v2). Nutzer muss neu einschreiben (`voice enroll`)
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
