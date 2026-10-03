# kushim Roadmap

Oberste Regel: Schäden jeder Art sind verboten. Lokal zuerst (Modus A), Claude nur Opt-in (Modus C).

## Phase 0: Fundament
- [x] Verschlüsselter Vault (SQLCipher), einziger Speicherort über `memory.location`
- [x] Migration und rotierende Backups
- [x] EgressGate (Modus A/C)
- [x] ActionGate (Default-Deny, Fail-Closed, Notaus, Audit)
- [x] Statische Egress-Prüfung (`tests/test_no_egress.py`)

## Phase 1: Stimme
- [x] Wake-Word-Logik (openWakeWord/ONNX, Entprellung, Cooldown), getestet; Modell lädt, Stille ergibt Score ~0. Push-to-Talk (F9) auf Wunsch des Nutzers wieder entfernt (2026-10-03), inkl. pynput
- [ ] Mikrofon-Aufnahme (Streaming, 16 kHz) anbinden und Wake Word/Hotkey live mit echtem Mikrofon prüfen (neu 2026-10-03: nur vom Nutzer testbar)
- [ ] Eigenes Wake Word "Hey Kushim" trainieren (Entscheidung Nutzer 2026-10-03; bis dahin hey_jarvis)
- [x] Speech-to-Text-Logik (faster-whisper, offline, `voice/stt.py`), mit Fake-Modell getestet
- [x] Whisper large-v3-turbo lokal (`models/`, git-ignoriert) geladen; läuft auf CUDA, bei gesperrtem Netzwerk getestet (2026-10-03)
- [x] STT mit echter Sprachaufnahme: im Live-Test funktioniert (2026-10-03)
- [x] Sprecherverifikation-Logik (`voice/speaker.py`, fail-closed, Cosine-Score), mit synthetischen Embeddings getestet
- [ ] Embedding-Modell wählen (lokal, z. B. ECAPA/Resemblyzer), Profil im Vault speichern und mit echter Stimme prüfen (neu 2026-10-03: Modellwahl/Download und Live-Test durch den Nutzer)
- [x] Ollama-Client (`llm/ollama.py`, nur Loopback, nur Text), mit lokalem Fake-Server getestet
- [x] Ollama 0.35.1 (Standalone-ZIP, SHA256 geprüft, ohne Auto-Updater, `tools/`) und qwen2.5:7b (`models/ollama`) installiert, Chat über Loopback getestet (2026-10-03)
- [ ] Ollama beim Start der Anwendung automatisch starten (OLLAMA_HOST=127.0.0.1, OLLAMA_MODELS) und Latenz optimieren
- [x] TTS-Logik (`voice/tts.py`: Satz-Streaming, Abbruch bei Barge-in), Engine austauschbar, getestet
- [x] Piper 1.8.0 (Home Assistant/OHF-Voice, GPL-3, privat ok) mit deutscher Stimme thorsten-high lokal in `models/piper`; `PiperEngine` in `voice/tts.py`; Synthese bei gesperrtem Netzwerk getestet (2026-10-03)
- [ ] Hörtest der Stimme und Audioausgabe an Lautsprecher anbinden (nur Nutzer hört, Gerätewahl)
- [x] Barge-in/Gesprächszustand (`voice/dialog.py`), mit Tests
- [x] Pipeline-Logik (`voice/pipeline.py`): STT, Notaus vor allem, Sprecher-Prüfung fail-closed, LLM nur Text, Satz-Sprachausgabe; Sprachbefehl-Notaus damit eingehängt (2026-10-03)
- [ ] Echtes LLM-Token-Streaming über Loopback (jetzt ein Block pro Antwort); Latenz ohne Audio gemessen: 0,4 s warm bei kurzer Antwort, längere Antworten und Mikrofonaufnahme noch offen
- [x] Audio-Modul `voice/audio.py` (sounddevice 0.5.6, MIT; Geräte nach Namensteil, Stille-Erkennung für Äußerungen, öffnet Mikrofon nur bei Aufruf, Audio nur im Speicher); Geräteliste gelesen, kein Stream geöffnet (2026-10-03)
- [x] `kushim talk` (`voice/talk.py`, Taste F9 oder `--wake`, `--mic`/`--out`) zusammengebaut. Kette ohne Mikrofon/Lautsprecher getestet: Piper-Sprache -> Whisper (CUDA) -> qwen2.5:7b -> Piper, Frage "Hauptstadt von Frankreich" richtig, 0,4 s warm (2,9 s erster Lauf); Notaus-Satz erkannt (2026-10-03). Nvidia cuBLAS/cuDNN (offizielle PyPI-Pakete) für die GPU nachinstalliert
- [x] Live-Test durch den Nutzer bestanden (2026-10-03, Systemstandard-Geräte, F9):  `kushim talk --mic "Arctis 5 Chat" --out "Arctis 5 Game"` (nur Nutzer; Gerätewahl)

## Phase 2: Oberfläche
- [x] Backend-API-Kern (`api/protocol.py`: Token, Default-Deny-Dispatch, neutrale Fehler), getestet
- [ ] Backend-Transport nur auf 127.0.0.1 (Freigabe erteilt 2026-10-03, ALLOWLIST-Eintrag nur für net/loopback.py)
- [ ] Tauri-UI mit animiertem Avatar
- [ ] Live-Transkript mit Feedback
- [x] Freigabe-Warteschlange (`safety/approvals.py`: nur ASK, einmalig, Hash-gebunden, Ablauf, Notaus), getestet
- [ ] Freigabe-Leiste und Claude-Vorschau in der UI (braucht UI-Toolchain)
- [x] Notaus-Kern (`safety/killswitch.py`): Marker-Datei per Verknüpfung `kushim NOTAUS.lnk`/`kushim kill`, Sprachbefehl-Erkennung ("Notaus", "stopp alles" ...), ohne Sprecherverifikation, Aufheben nur per `kushim resume`; `kushim start` beendet sich bei Notaus und startet bei aktivem Notaus nicht (2026-10-03)
- [x] Sprachbefehl-Notaus in der Pipeline (vor LLM, Dialog.halt); ActionGate.kill beim Anschluss des Gates noch als Aktion in `KillSwitch` registrieren
- [ ] Dashboard, Gedächtnis-Ansicht, Sicherheitsstatus in der UI

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

## Phase 2b: Start-Anwendung und Branding (Nutzerwunsch 2026-10-03)
- [x] Logo-Entwurf `assets/logo.svg` (Keil-K auf Tontafel, Anspielung auf Kushim, den frühesten namentlich bekannten Verwalter); nur lokal
- [x] Launcher-Kern `kushim.launcher` und `kushim start` (Ollama nur 127.0.0.1, übernimmt/beendet nichts Fremdes), getestet (2026-10-03)
- [ ] Desktop-Verknüpfung mit Logo für `kushim start` (braucht .ico), Backend/Notaus einbinden. Plan war: zuerst ein Launcher (Desktop-Verknüpfung mit Logo, startet Ollama nur auf 127.0.0.1 und das Backend, beendet beides sauber, Notaus-Taste), später abgelöst von der Tauri-App (Phase 2), die dieselbe Startlogik nutzt
- [x] `assets/kushim.ico` und `kushim.png` per `scripts/make_icon.py` (Pillow 12.3.0, offline, gleiche Geometrie wie das SVG) erzeugt; Desktop-Verknüpfung `kushim.lnk` angelegt (2026-10-03)

## Nutzerwünsche 2026-10-03 (Wake-Word-only, Stimme)
- [x] Nur Wake Word: vor dem Wake Word sieht nur der lokale Detektor das Mikrofon (keine STT, kein LLM, keine Speicherung); nur Wake Word gesagt -> kurze Quittung "Ja?", dann Zuhören mit 5 s Wartezeit; Quittung wird nicht als Befehl gehört (Mic.flush)
- [x] Mehrere Wake Words einstellbar: `[voice] wake_words = [...]` in der Konfiguration oder `kushim talk --wake-words a,b`; erlaubt sind vortrainierte Namen oder .onnx aus `models/wakewords/` (keine fremden Pfade)
- [ ] Sprecherverifikation erzwingen ("nur meine Stimme"): Embedding-Modell lokal (ONNX, offizielle Quelle prüfen), Einschreiben per `kushim voice enroll`, Stimmprofil nur im verschlüsselten Vault, `kushim talk` startet ohne Profil nicht (fail-closed), Notaus-Satz bleibt für jeden wirksam
- [ ] Flüssigere Stimme, möglichst mit der eigenen Stimme des Nutzers (Klon/Training lokal, nur eigene Aufnahmen mit Einwilligung): Optionen und Hardware (RTX 3070, 8 GB) klären, Entscheidung beim Nutzer
- [ ] Eigenes Wake Word "Hey Kushim" trainieren (siehe Phase 1)
