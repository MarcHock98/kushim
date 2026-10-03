# Routine-Zustand

Wird von `/kushim-routine` gepflegt. Keine Geheimnisse, keine Datenpfade.

- Letzter Durchlauf: 2026-10-03 (manuell nach SKILL.md, Skill noch nicht registriert)
- Aktueller Branch: routine/p1-wake
- Erledigt: Wake-Word-Logik + Push-to-Talk (src/kushim/voice/trigger.py), 21 Tests grün, Modell hey_jarvis (ONNX) lädt
- Nächster Schritt: Phase 1, Speech-to-Text (faster-whisper); Mikrofon-Streaming braucht Live-Test durch den Nutzer
- Branches bereit zum Push durch den Nutzer: keine (routine/p1-wake noch nicht gemerged)

## Slack
- Nutzer-ID / Kanal-ID: (noch nicht ermittelt)

## Offene Fragen an den Nutzer
- Wake Word: "hey_jarvis" nutzen oder eigenes "Hey Kushim" trainieren? (noch nicht gesendet, nicht blockierend)

## Blockiert
- Live-Mikrofon-Test: nur der Nutzer kann ihn ausführen

## Probleme und Versuche
- openwakeword braucht `requests` trotz --no-deps (gelöst, in pyproject-Extra `voice`)

## Entscheidungen des Nutzers
- Modus A (lokal) Standard, Modus C (Claude auf Befehl) Opt-in
- Gedächtnis zunächst lokal, später NAS (Modell noch offen)
- Oberste Regel: Schäden jeder Art sind verboten
