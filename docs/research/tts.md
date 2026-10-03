# TTS: Piper

- Entscheidung Nutzer 2026-10-03: privat, offline, beste Wahl. Piper (Kokoro hat kaum deutsche Stimmen).
- Paket: PyPI `piper-tts` 1.8.0, Autor The Home Assistant Authors (OHF-voice/piper1-gpl), GPL-3.0-or-later, Kernabhängigkeiten nur onnxruntime und pathvalidate. `http_server.py` gehört zum optionalen Extra und wird nicht genutzt. GPL gilt bei Weitergabe; bei rein privater Nutzung unkritisch, vor einer Veröffentlichung neu prüfen.
- Stimme: `rhasspy/piper-voices`, `de/de_DE/thorsten/high` (onnx ca. 114 MB plus JSON), Ablage `models/piper` (git-ignoriert).
- Leak-Test 2026-10-03: Laden und Synthese mit blockierten Sockets/DNS ohne Netzwerkversuch, ca. 1 s für 2,4 s Audio.
- Datum: 2026-10-03
