# STT: faster-whisper

- Frage: Welche lokale Spracherkennung für Phase 1?
- Quelle: PyPI `faster-whisper` 1.2.1 (SYSTRAN, MIT-Lizenz, weit verbreitet), geprüft per `pip index` am 2026-10-03.
- Fazit: Version gepinnt. Modell wird nie automatisch geladen (`local_files_only=True`), damit Modus A ohne Netzwerk bleibt.
  Das CTranslate2-Modell (z. B. large-v3-turbo, >1 GB) legt der Nutzer selbst lokal ab; Download vorher mit ihm abstimmen.
- Datum: 2026-10-03

## Update 2026-10-03: Modell geladen
- Repo `mobiuslabsgmbh/faster-whisper-large-v3-turbo` (von faster-whisper selbst als `large-v3-turbo` referenziert; HF-Konto inzwischen `dropbox-dash`, MIT, ~1,9 Mio. Downloads). Dateien: model.bin, JSON, keine Skripte/Pickle. Korrektur: Es ist nicht Systran.
- Ablage `models/whisper-large-v3-turbo` (in .gitignore). Laden auf CUDA/float16 klappt.
- Leak-Test: Laden und Erkennen mit gesperrten Sockets (connect/getaddrinfo blockiert) und HF_HUB_OFFLINE=1 ohne Netzwerkversuch.
