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
- [ ] Eigenes Wake Word "Hey Kushim" trainieren (Entscheidung Nutzer 2026-10-03; bis dahin hey_jarvis)
- [x] Speech-to-Text-Logik (faster-whisper, offline, `voice/stt.py`), mit Fake-Modell getestet
- [x] Whisper large-v3-turbo lokal (`models/`, git-ignoriert) geladen; läuft auf CUDA, bei gesperrtem Netzwerk getestet (2026-10-03)
- [ ] STT mit echter Sprachaufnahme prüfen (nur Nutzer, Mikrofon)
- [x] Sprecherverifikation-Logik (`voice/speaker.py`, fail-closed, Cosine-Score), mit synthetischen Embeddings getestet
- [ ] Embedding-Modell wählen (lokal, z. B. ECAPA/Resemblyzer), Profil im Vault speichern und mit echter Stimme prüfen (neu 2026-10-03: Modellwahl/Download und Live-Test durch den Nutzer)
- [x] Ollama-Client (`llm/ollama.py`, nur Loopback, nur Text), mit lokalem Fake-Server getestet
- [ ] Ollama installieren und 7-8B-Modell laden (>2 GB, Nutzer fragen) und Live-Test (neu 2026-10-03)
- [x] TTS-Logik (`voice/tts.py`: Satz-Streaming, Abbruch bei Barge-in), Engine austauschbar, getestet
- [ ] TTS-Engine wählen (Kokoro Apache-2.0 bevorzugt; piper-tts ist GPL-3, Lizenz-/Modellwahl und Download beim Nutzer erfragen) und Hörtest (neu 2026-10-03)
- [x] Barge-in/Gesprächszustand (`voice/dialog.py`), mit Tests
- [ ] Streaming und Latenz unter 1,5 s (braucht echte Komponenten und Messung)

## Phase 2: Oberfläche
- [x] Backend-API-Kern (`api/protocol.py`: Token, Default-Deny-Dispatch, neutrale Fehler), getestet
- [ ] Backend-Transport nur auf 127.0.0.1 (Freigabe erteilt 2026-10-03, ALLOWLIST-Eintrag nur für net/loopback.py)
- [ ] Tauri-UI mit animiertem Avatar
- [ ] Live-Transkript mit Feedback
- [x] Freigabe-Warteschlange (`safety/approvals.py`: nur ASK, einmalig, Hash-gebunden, Ablauf, Notaus), getestet
- [ ] Freigabe-Leiste und Claude-Vorschau in der UI (braucht UI-Toolchain)
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
- [x] Bandit über Antwortstile mit Sicherheits-Reward (`learning/bandit.py`: Verstoß = -1, Strafen für Schmeichelei/Abhängigkeit), getestet; lernt nie Berechtigungen
- [ ] Bandit an Feedback-Log (`add_feedback`) und Stil-Auswahl anbinden (braucht LLM-Pipeline) (neu 2026-10-03)
- [ ] Tests gegen Manipulation, Schmeichelei, Abhängigkeit

## Phase 5: NAS und Ausbau
- [ ] Gedächtnis-Dienst auf dem NAS (`remote:`-Backend)
- [ ] Optional: LoRA/DPO-Feintuning lokal
