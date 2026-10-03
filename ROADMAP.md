# kushim Roadmap

Oberste Regel: Schäden jeder Art sind verboten. Lokal zuerst (Modus A), Claude nur Opt-in (Modus C).

## Phase 0: Fundament
- [x] Verschlüsselter Vault (SQLCipher), einziger Speicherort über `memory.location`
- [x] Migration und rotierende Backups
- [x] EgressGate (Modus A/C)
- [x] ActionGate (Default-Deny, Fail-Closed, Notaus, Audit)
- [x] Statische Egress-Prüfung (`tests/test_no_egress.py`)

## Phase 1: Stimme
- [x] Wake-Word-Logik (openWakeWord/ONNX, Entprellung, Cooldown) und Push-to-Talk-Logik, getestet; Modell lädt, Stille ergibt Score ~0
- [ ] Mikrofon-Aufnahme (Streaming, 16 kHz) anbinden und Wake Word/Hotkey live mit echtem Mikrofon prüfen (neu 2026-10-03: nur vom Nutzer testbar)
- [ ] Eigenes Wake Word "Hey Kushim" trainieren oder "hey_jarvis" nutzen (neu 2026-10-03: Entscheidung des Nutzers)
- [x] Speech-to-Text-Logik (faster-whisper, offline, `voice/stt.py`), mit Fake-Modell getestet
- [ ] Echtes Whisper-Modell lokal ablegen und STT mit Aufnahme prüfen (neu 2026-10-03: Modell-Download >1 GB und Mikrofon, Nutzer entscheidet/testet)
- [x] Sprecherverifikation-Logik (`voice/speaker.py`, fail-closed, Cosine-Score), mit synthetischen Embeddings getestet
- [ ] Embedding-Modell wählen (lokal, z. B. ECAPA/Resemblyzer), Profil im Vault speichern und mit echter Stimme prüfen (neu 2026-10-03: Modellwahl/Download und Live-Test durch den Nutzer)
- [ ] Lokales LLM (Ollama, 7-8B): BLOCKIERT, localhost-HTTP braucht Eintrag in ALLOWLIST von `tests/test_no_egress.py` (nur mit Nutzerzustimmung); Alternative: In-Process-Bibliothek (llama-cpp-python) statt Server (2026-10-03)
- [ ] Lokale Stimme (Piper/Kokoro)
- [x] Barge-in/Gesprächszustand (`voice/dialog.py`), mit Tests
- [ ] Streaming und Latenz unter 1,5 s (braucht echte Komponenten und Messung)

## Phase 2: Oberfläche
- [ ] Backend-API (WebSocket, 127.0.0.1, Token)
- [ ] Tauri-UI mit animiertem Avatar
- [ ] Live-Transkript mit Feedback
- [ ] Freigabe-Leiste und Claude-Vorschau
- [ ] Dashboard, Gedächtnis-Ansicht, Sicherheitsstatus, Notaus

## Phase 3: Tools (jeweils mit ActionSpec und Tests)
- [ ] Recherche/Web
- [ ] Mail und Kalender (lokal)
- [ ] PC-Steuerung (freigegebene Ordner, Papierkorb)
- [ ] Smart Home und Musik
- [ ] Claude als Opt-in (Modus C)

## Phase 4: Lernen
- [ ] Reflexionsschleife und Nutzerprofil
- [ ] Feedback-Log als Trainingsdaten
- [ ] Bandit/RL mit Sicherheits-Reward
- [ ] Tests gegen Manipulation, Schmeichelei, Abhängigkeit

## Phase 5: NAS und Ausbau
- [ ] Gedächtnis-Dienst auf dem NAS (`remote:`-Backend)
- [ ] Optional: LoRA/DPO-Feintuning lokal
