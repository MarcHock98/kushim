# Routine-Zustand

Wird von `/kushim-routine` gepflegt. Keine Geheimnisse, keine Datenpfade.

- Letzter Durchlauf: 2026-10-03 (/loop kushim-routine, STT)
- Aktueller Branch: master (routine/p1-wake und routine/p1-stt gemerged, Branches bleiben)
- Erledigt: Wake-Word-Logik + Push-to-Talk (src/kushim/voice/trigger.py), 21 Tests grün, Modell hey_jarvis (ONNX) lädt
- Erledigt zusätzlich: STT-Logik voice/stt.py, 25 Tests grün, faster-whisper 1.2.1 gepinnt
- Nächster Schritt: Phase 1, Sprecherverifikation (lokal, Logik mit Fakes testbar)
- Branches bereit zum Push durch den Nutzer: master, routine/p1-wake, routine/p1-stt

## Slack
- Nutzer-ID / Kanal-ID: (noch nicht ermittelt)

## Offene Fragen an den Nutzer
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
