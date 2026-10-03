# Routine-Zustand

Wird von `/kushim-routine` gepflegt. Keine Geheimnisse, keine Datenpfade.

- Letzter Durchlauf: 2026-10-03 (/loop kushim-routine, STT)
- Aktueller Branch: master (routine/p1-wake, p1-stt, p1-speaker, p1-dialog, p1-tts gemerged, Branches bleiben)
- Erledigt: Wake-Word-Logik + Push-to-Talk (src/kushim/voice/trigger.py), 21 Tests grün, Modell hey_jarvis (ONNX) lädt
- Erledigt zusätzlich: STT-Logik voice/stt.py, 25 Tests grün, faster-whisper 1.2.1 gepinnt
- Erledigt zusätzlich: Sprecherverifikation-Logik, 33 Tests grün
- Erledigt zusätzlich: Dialog-/Barge-in-Logik, TTS-Logik (Satz-Streaming), 41 Tests grün
- Nächster Schritt: alle autonomen Phase-1-Punkte erledigt; weiter mit Phase 2 (Backend-API-Logik) und auf Nutzerentscheidungen warten (LLM-Weg, Whisper-/TTS-/Embedding-Modelle, Wake Word)
- Branches bereit zum Push durch den Nutzer: master, routine/p1-wake, routine/p1-stt, routine/p1-speaker, routine/p1-dialog, routine/p1-tts

## Slack
- Nutzer-ID / Kanal-ID: nicht verwendet. Verbundenes Slack-Konto hat andere Mail (Arbeits-Workspace) als die Git-/Claude-Mail, Empfänger unsicher, daher nichts gesendet

## Offene Fragen an den Nutzer
- LLM: localhost-HTTP (Ollama) in ALLOWLIST erlauben oder In-Process llama-cpp-python? (nur im Terminal, blockiert Lokales LLM)
- Whisper-Modell: welches (z. B. large-v3-turbo, >1 GB) und Download freigeben? (noch nicht gesendet, nicht blockierend)
- Wake Word: "hey_jarvis" nutzen oder eigenes "Hey Kushim" trainieren? (noch nicht gesendet, nicht blockierend)

## Blockiert
- Live-Mikrofon-Test: nur der Nutzer kann ihn ausführen

## Probleme und Versuche
- openwakeword braucht `requests` trotz --no-deps (gelöst, in pyproject-Extra `voice`)

## Entscheidungen des Nutzers
- Modus A (lokal) Standard, Modus C (Claude auf Befehl) Opt-in
- Gedächtnis zunächst lokal, später NAS (Modell noch offen)
- Oberste Regel: Schäden jeder Art sind verboten
