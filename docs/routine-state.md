# Routine-Zustand

Wird von `/kushim-routine` gepflegt. Keine Geheimnisse, keine Datenpfade.

- Letzter Durchlauf: 2026-10-03 (/loop kushim-routine, STT)
- Aktueller Branch: master (routine/p1-wake, p1-stt, p1-speaker, p1-dialog, p1-tts, p2-api-core, p2-approvals, p4-bandit, p2-loopback, p1-llm, p1-whisper-model, p1-ollama-setup, branding, p1-piper, p2b-launcher, p2b-icon gemerged, Branches bleiben)
- Erledigt: Wake-Word-Logik + Push-to-Talk (src/kushim/voice/trigger.py), 21 Tests grün, Modell hey_jarvis (ONNX) lädt
- Erledigt zusätzlich: Dialog-/Barge-in-Logik, TTS-Logik, API-Kern (Token/Dispatch), Freigabe-Warteschlange, 97 Tests grün
- Erledigt zusätzlich: Dialog-/Barge-in-Logik, TTS-Logik, API-Kern (Token/Dispatch), Freigabe-Warteschlange, 97 Tests grün
- Erledigt zusätzlich: Dialog-/Barge-in-Logik, TTS-Logik, API-Kern (Token/Dispatch), Freigabe-Warteschlange, 97 Tests grün
- Nächster Schritt: Tauri/Node (offizielle Quellen, Netzwerkverhalten prüfen), Wake-Word-Training "Hey Kushim", Backend/Notaus im Launcher. Desktop-Verknüpfung liegt auf dem Desktop des Nutzers (startet `python -m kushim.cli start`)
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
- 2026-10-03: Start-Anwendung und Logo gewünscht; Umsetzung später nach Plan (Launcher zuerst, dann Tauri), Logo nur lokal
- 2026-10-03: Whisper large-v3-turbo laden; LLM qwen2.5:7b (Ollama) laden; Hardware RTX 3070 8 GB, 31 GB RAM
- 2026-10-03: localhost erlauben (ALLOWLIST: nur net/loopback.py, nur Loopback), umgesetzt
- 2026-10-03: eigenes Wake Word "Hey Kushim" trainieren
- 2026-10-03: privates Projekt, TTS offline: Empfehlung Piper (GPL-3 stört bei privater Nutzung nicht, gute deutsche Stimmen)
- 2026-10-03: Tauri/Node installieren und Whisper-Modell laden erlaubt, nur offizielle Quellen, Pakete/Modelle auf Datenabfluss prüfen
- Modus A (lokal) Standard, Modus C (Claude auf Befehl) Opt-in
- Gedächtnis zunächst lokal, später NAS (Modell noch offen)
- Oberste Regel: Schäden jeder Art sind verboten
