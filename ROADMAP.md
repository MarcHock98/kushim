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
- [x] Mikrofon-Aufnahme (Streaming, 16 kHz) angebunden und mit echtem Mikrofon geprüft: Live-Test des Nutzers, `kushim talk` funktioniert, Gespräch "flüssiger" (2026-10-03/04)
- [x] Wake Words "hey kushim", "kushim", "kush", "hallo kush", "hi kushim", "kushi" ohne Training (2026-10-03): sherpa-onnx KWS, Modell geprüft; kein "hey jarvis" mehr als Standard (Wunsch des Nutzers). Messung auf synthetischer Stimme: 11 von 18 erkannt, 0 Fehlalarme in 10 Sätzen (siehe docs/research/wake-kws.md)
- [x] Wake-Word-Erkennung mit der echten Stimme: vom Nutzer als funktionierend gemeldet (2026-10-04). Feintuning von `threshold`/`boost` in `wakewords.toml` nur bei Bedarf
- [x] Speech-to-Text-Logik (faster-whisper, offline, `voice/stt.py`), mit Fake-Modell getestet
- [x] Whisper large-v3-turbo lokal (`models/`, git-ignoriert) geladen; läuft auf CUDA, bei gesperrtem Netzwerk getestet (2026-10-03)
- [x] STT mit echter Sprachaufnahme: im Live-Test funktioniert (2026-10-03)
- [x] Sprecherverifikation-Logik (`voice/speaker.py`, fail-closed, Cosine-Score), mit synthetischen Embeddings getestet
- [x] Embedding-Modell (WeSpeaker CAM++), Profil v2 im Vault, mit echter Stimme geprüft: `voice enroll` und `voice test` vom Nutzer durchgeführt, Schwelle vom Nutzer auf 0,79 gestellt (`kushim voice threshold`) (2026-10-04). Test mit zweiter Person: siehe offener Punkt unten
- [x] Ollama-Client (`llm/ollama.py`, nur Loopback, nur Text), mit lokalem Fake-Server getestet
- [x] Ollama 0.35.1 (Standalone-ZIP, SHA256 geprüft, ohne Auto-Updater, `tools/`) und qwen2.5:7b (`models/ollama`) installiert, Chat über Loopback getestet (2026-10-03)
- [x] Ollama beim Start der Anwendung automatisch starten (OLLAMA_HOST=127.0.0.1, OLLAMA_MODELS) und Latenz optimieren (2026-10-04: `kushim talk`/`start` starten Ollama über den Launcher, Modell bleibt 2 h warm und wird vorgeladen, `think: false`, Notaus beendet auch `llama-server`; Messung: erster Ton 0,7 bis 0,9 s mit qwen2.5:7b, 1,4 bis 2,0 s mit qwen3.5:9b)
- [x] TTS-Logik (`voice/tts.py`: Satz-Streaming, Abbruch bei Barge-in), Engine austauschbar, getestet
- [x] Piper 1.8.0 (Home Assistant/OHF-Voice, GPL-3, privat ok) mit deutscher Stimme thorsten-high lokal in `models/piper`; `PiperEngine` in `voice/tts.py`; Synthese bei gesperrtem Netzwerk getestet (2026-10-03)
- [x] Audioausgabe an Lautsprecher/Headset angebunden (Live-Test, `--out`); die eigene Stimme (Klon) ist ein eigener Punkt unten
- [x] Barge-in/Gesprächszustand (`voice/dialog.py`), mit Tests
- [x] Pipeline-Logik (`voice/pipeline.py`): STT, Notaus vor allem, Sprecher-Prüfung fail-closed, LLM nur Text, Satz-Sprachausgabe; Sprachbefehl-Notaus damit eingehängt (2026-10-03)
- [x] Echtes LLM-Token-Streaming über Loopback (`OllamaClient.chat_stream` + `chunk_stream` + `prefetch`: Satz für Satz, erster Satz 0,14 s warm; Abbruch beim Unterbrechen/Notaus behoben); Live-Test mit Mikrofon durch den Nutzer: flüssig (2026-10-04)
- [x] Audio-Modul `voice/audio.py` (sounddevice 0.5.6, MIT; Geräte nach Namensteil, Stille-Erkennung für Äußerungen, öffnet Mikrofon nur bei Aufruf, Audio nur im Speicher); Geräteliste gelesen, kein Stream geöffnet (2026-10-03)
- [x] `kushim talk` (`voice/talk.py`, Taste F9 oder `--wake`, `--mic`/`--out`) zusammengebaut. Kette ohne Mikrofon/Lautsprecher getestet: Piper-Sprache -> Whisper (CUDA) -> qwen2.5:7b -> Piper, Frage "Hauptstadt von Frankreich" richtig, 0,4 s warm (2,9 s erster Lauf); Notaus-Satz erkannt (2026-10-03). Nvidia cuBLAS/cuDNN (offizielle PyPI-Pakete) für die GPU nachinstalliert
- [x] Live-Test durch den Nutzer bestanden (2026-10-03, Systemstandard-Geräte, F9):  `kushim talk --mic "Arctis 5 Chat" --out "Arctis 5 Game"` (nur Nutzer; Gerätewahl)

## Phase 2: Oberfläche
- [x] Backend-API-Kern (`api/protocol.py`: Token, Default-Deny-Dispatch, neutrale Fehler), getestet
- [ ] Backend-Transport (WebSocket nur auf 127.0.0.1): **wartet auf Entscheidung des Nutzers**. Die Freigabe vom 2026-10-03 galt dem Loopback-Client (Ollama); ein Server braucht Importe, die `tests/test_no_egress.py` für `net/loopback.py` bisher sperrt. Lockerung nur mit ausdrücklichem Ja; Audit für `safety.kill`/`resume` kommt dabei mit
- [ ] Tauri-UI mit animiertem Avatar
- [ ] Live-Transkript mit Feedback
- [x] Freigabe-Warteschlange (`safety/approvals.py`: nur ASK, einmalig, Hash-gebunden, Ablauf, Notaus), getestet
- [ ] Freigabe-Leiste und Claude-Vorschau in der UI (braucht UI-Toolchain)
- [x] Notaus-Kern (`safety/killswitch.py`): Marker-Datei per Verknüpfung `kushim NOTAUS.lnk`/`kushim kill`, Sprachbefehl-Erkennung ("Notaus", "stopp alles" ...), ohne Sprecherverifikation, Aufheben nur per `kushim resume`; `kushim start` beendet sich bei Notaus und startet bei aktivem Notaus nicht (2026-10-03)
- [x] Sprachbefehl-Notaus in der Pipeline (vor LLM, Dialog.halt); ActionGate.kill beim Anschluss des Gates noch als Aktion in `KillSwitch` registrieren
- [ ] Dashboard, Gedächtnis-Ansicht, Sicherheitsstatus in der UI

## Phase 3: Tools (jeweils mit ActionSpec und Tests)
- [x] Tool-Verwaltung (2026-10-04, Nutzerwunsch "Tools über die UI aktivierbar"): `tools/registry.py` (alle Tools standardmäßig AUS, Einschalten nur bestätigt und nur wenn verfügbar, Ausschalten sofort, `ToolGate` um den `ActionGate`), `[tools] enabled` in `config.toml` (atomar), API-Typen `tools.list`/`tools.set` (`api/tools_api.py`), `kushim tools [enable|disable]`; Plan in `docs/tools-plan.md`; 20 Tests
- [ ] Werkzeuge-Bildschirm in der UI (Einstellungen > Werkzeuge: Schalter, Beschreibung, Chip "Sendet Daten nach außen", Bestätigung beim Einschalten) (braucht UI-Toolchain)
- [x] Recherche/Web, Logik (2026-10-04): `web/guard.py` (Prüfer: keine E-Mail/IBAN/Karte/Telefon/Schlüssel/Pfade/Personendaten), `web/sanitize.py` (HTML raus, Einschleus-Muster erkannt und verworfen, Zitat-Block "Daten, keine Anweisung"), `web/wikipedia.py` (feste URL-Grenze: nur https de.wikipedia.org/w/api.php, Parameter und Werte fest; Antwortform geprüft), `web/search.py` (Vorschau, Freigabe einmalig/hash-gebunden/Ablauf/Notaus, URL aus dem freigegebenen Text neu berechnet); mit Fake-Abrufer getestet (40 Tests). Gate verschärft: auch Nur-Lesen-Aktionen mit Außenwirkung brauchen verifizierten Sprecher
- [x] Recherche/Web, Netz-Modul `net/web.py` (2026-10-04, vom Nutzer freigegeben, **keine Downloads**): HTTPS-GET nur zu `de.wikipedia.org/w/api.php`, nur JSON, keine Weiterleitungen/Cookies/Kompression, 1 MB, 10 s, schreibt nie auf die Platte; ALLOWLIST-Eintrag und Sperr-Tests in `tests/test_no_egress.py`; `kushim search <frage> [--llm]` (Vorschau, Bestätigung, Quellen, Zusammenfassung); live gegen Wikipedia geprüft (qwen2.5:7b antwortet mit Quelle)
- [x] Quarantäne für Web-Inhalte (2026-10-04, Nutzerwunsch: Web-Inhalte dürfen das LLM nie etwas tun oder Tools nutzen lassen): `Untrusted`-Markierung (Web-Texte und die LLM-Antwort darauf lösen nie eine Suche/Aktion aus), werkzeugloser Antwortpfad `web/answer.py` (kennt weder Registry noch Gate noch Freigabe, Importe per Test gesperrt), Quellen nur in der Nutzer-Rolle, Terminal-Steuerzeichen entfernt; 13 Tests
- [x] Abbruch-Befehl (2026-10-04, Nutzerwunsch "wenn ich sage er soll einen Befehl abbrechen, soll er es können"): "abbrechen", "brich das ab", "vergiss es" u. ä. (kurze Sätze) beenden laufende Aufgaben (Claude-Abfrage samt Prozess, Recherche), lehnen offene Freigaben ab und stoppen Sprechen, **ohne etwas zu sperren** (der Notaus bleibt der große Schalter); geht auch WÄHREND eine Antwort läuft (`Pipeline.try_cancel`, STT mit Sperre) und ohne Sprecher-Prüfung (Abbrechen ist sicher); nach Abbruch **kein Ersatzweg** zu Wikipedia; `tasks.py` (`TaskRegistry`), API `tasks.list|cancel`, Strg+C im Terminal; 43 Tests
- [ ] Recherche/Web in der Pipeline: Absicht erkennen ("schau nach", "recherchiere"), Vorschau per UI/Sprache ("ja", nur verifizierte Stimme), Antwort mit Quellen, eingeschränkt auf aktives Tool (nach der Netz-Freigabe)
- ~~Claude als Rechercheur über die API (`claude.ask`, Schlüssel, Geldlimit)~~ ersetzt am 2026-10-04: Claude wird über die **Claude CLI** des angemeldeten Nutzers genutzt (kein API-Schlüssel), siehe nächster Punkt
- [ ] Claude über die Claude CLI steuern (Nutzerwunsch 2026-10-04; Plan `docs/claude-cli-plan.md`; nur in freigegebenen, in der UI einstellbaren Ordnern; Modus C; Tool `claude.code` standardmäßig aus):
  - [x] Recherche-Modus (2026-10-04, Nutzerwunsch "Claude primär für Recherche, Websuche als Ersatz"): `claude_cli/base.py` (CLI finden, Anmeldung lesen ohne Kontodaten, saubere Umgebung ohne API-Schlüssel/Umleiter), `claude_cli/ask.py` (Minimal-Modus: nur WebSearch/WebFetch, leerer Wegwerf-Ordner, `dontAsk`, kein Verlauf, 0,50 USD, 120 s, Prozessbaum-Abbruch), `research.py` (eine Freigabe mit beiden Zielen, Ersatzweg nur wenn die Vorschau ihn nannte, API-Konto durch Geldlimit 0 gestoppt, Antwort `Untrusted`), Tool `claude.research`, `kushim research|claude check|enable|disable`; 36 Tests mit gefälschtem Prozess. **Nicht live getestet** (kein echter Claude-Aufruf ohne dein Ja)
  - [ ] Recherche in die Sprach-Pipeline hängen ("recherchiere/schau nach" aus dem Gesagten, Vorschau per UI/Sprache, Antwort sprechen, Quellen in der UI)
  - [x] Teil 1 (2026-10-04): `claude_cli/folders.py` (Ordner-Freigabe `[claude] folders` als `name|pfad`: Git-Repo, nie Laufwerk/Home/System/AppData/.ssh/.claude/Vault, keine Junction), `dev.py` (Befehl: eigener Worktree `-w`, `acceptEdits`, `--permission-prompts none`, Rechteprofil in CLI-Schreibweise, nie `bypassPermissions`), `review.py` (Diff aus Git, nur lesende git-Befehle per Whitelist, geschützte Dateien rot, Stand des Nutzers unverändert?), `session.py` (ein Lauf zugleich, Zustand `run/claude-session.json`, Stopp/Notaus/`abbrechen`/Zeitgrenze, Status und Stopp aus einem zweiten Terminal), `control.py` (Vorschau, Freigabe, EgressGate, Prüfer), Tool `claude.code`, `kushim claude folders|add|remove|start|status|stop|result`; Sicherheitsfund unterwegs behoben: `is_protected` erkannte `.claude/` nicht. **Am echten Lauf in einem Wegwerf-Repo geprüft** (Worktree, Rückfrage, Fakten stimmen mit Git überein, Regelschreibweise korrigiert). Sicherheitslücke gefunden und mit Beweis geschlossen: Projekt-Einstellungen im Worktree hätten Selbst-Eskalation erlaubt, jetzt nur `--setting-sources user`
  - [x] Teil 2 (2026-10-04): `claude_cli/report.py` (festes Format Zusammenfassung/Rückfrage/Nächste Schritte, nur NEUE Verweigerungen, Angebote nur für harmlose Befehle, Übersicht aus Claude-Text plus Git-Fakten, gesprochene Kurzfassung), Fortsetzen per `--resume` (`kushim claude answer`, Erlaubnis nur für angebotene Muster)
  - [ ] Teil 3: API-Typen (`claude.folders.*`, `claude.status|stop|start|review|answer`) und Sprachbefehle ("nutze Claude um das Projekt weiterzuentwickeln", Status, Stopp, Antworten, Ergebnis; Start und Antwort nur stark verifiziert + Freigabe; `KillSwitch` um `sessions.stop` erweitern; Rückfragen und Übersicht sprechen)
  - [ ] Teil 4: UI-Bildschirm (Ordner, laufender Lauf, Rückfragen, Übersicht, Diff-Ansicht)
  - Entscheidungen des Nutzers: bis zur Antwort gelten die Standardwerte (Rechteprofil laut Plan, 2 USD und 45 min je Zug); welche Ordner freigegeben werden, trägt der Nutzer selbst ein (`kushim claude add`)
- [ ] Mail und Kalender (lokal)
- [ ] Timer, Erinnerungen und Notizen per Sprache (lokal, ohne Netz; Vorschlag 2026-10-04, schneller Gewinn; über `kushim-add-tool`, standardmäßig aus)
- [ ] PC-Steuerung (freigegebene Ordner, Papierkorb)
- [ ] Smart Home und Musik
- ~~Claude als Opt-in (Modus C)~~ aufgeteilt am 2026-10-04: Recherche über Claude ist umgesetzt (siehe oben), "Claude entwickelt das Projekt" steht als "Claude über die Claude CLI steuern" weiter oben

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
- [x] Desktop-Verknüpfungen mit Logo (`kushim`, `kushim sprechen`, `kushim NOTAUS`; nach einem Verlust am 2026-10-04 neu angelegt), Notaus eingebunden; Befehl `kushim` im Benutzer-PATH (`bin/kushim.cmd`, `scripts/add-path.ps1`, `-SkipPath`) und `kushim help`. Die Tauri-App löst den Launcher später ab (Phase 2)
- [x] `assets/kushim.ico` und `kushim.png` per `scripts/make_icon.py` (Pillow 12.3.0, offline, gleiche Geometrie wie das SVG) erzeugt; Desktop-Verknüpfung `kushim.lnk` angelegt (2026-10-03)

## Nutzerwünsche 2026-10-03 (Wake-Word-only, Stimme)
- [x] Nur Wake Word: vor dem Wake Word sieht nur der lokale Detektor das Mikrofon (keine STT, kein LLM, keine Speicherung); nur Wake Word gesagt -> kurze Quittung "Ja?", dann Zuhören mit 5 s Wartezeit; Quittung wird nicht als Befehl gehört (Mic.flush)
- [x] Mehrere Wake Words einstellbar: `[voice] wake_words = [...]` in der Konfiguration oder `kushim talk --wake-words a,b`; erlaubt sind vortrainierte Namen oder .onnx aus `models/wakewords/` (keine fremden Pfade)
- [x] Sprecherverifikation erzwungen (Code): sherpa-onnx 1.13.8 + WeSpeaker CAM++ (29 MB, `models/speaker`, Größe wie im Release), `kushim voice enroll|test|status|reset`, Profil nur im verschlüsselten Vault, Schwelle aus den Proben kalibriert (0,5 bis 0,75), `kushim talk` startet ohne Profil nicht, Notaus-Satz wirkt für jeden (2026-10-03)
- [x] Sprecher-Prüfung v2 (2026-10-04): Einschreiben aus den 10 Klon-Absätzen (`voice enroll`, dieselben Aufnahmen für den Klon), Mehr-Prototypen-Profil, Schwelle aus Daten (Leave-one-out gegen 30 Fremdstimmen), Fenster-Prüfung langer Äußerungen, "stark" für Änderungen, längere Spracheingabe (`end_silence_seconds` 1,2 / `max_seconds` 60). Gemessen nur mit künstlichen Stimmen, siehe docs/research/speaker-v2.md
- [x] Wake Word und Befehl in einem Zug (2026-10-04): "hey kushim, wie spät ist es?" wird direkt beantwortet, "Ja?" nur noch bei reinem Wake Word; Wake Word am Textanfang wird vor dem LLM entfernt; `command_wait_seconds` 1,5, `listen_seconds` 15 (Wunsch des Nutzers), `end_silence_seconds` 0,9; Modell bleibt 2 h warm
- [x] Mehrere Grafikkarten (2026-10-04): `kushim gpu`, `[gpu]` in `config.toml`; bei mehreren NVIDIA-Karten bekommt Whisper eine für sich, das Sprachmodell die übrigen; mit einer Karte alles wie bisher (nur mit erfundenen Kartenlisten und der einen Karte des Nutzers getestet)
- [x] Sprachmodell austauschbar (2026-10-04): `[llm] model`, `kushim llm set|test|back`, `install.ps1 -Llm`; `qwen3.5:9b` geladen und aktiv (Denkmodus aus, passt mit Whisper knapp in 8 GB; etwa 1 s langsamer als qwen2.5:7b), `qwen2.5:7b` bleibt installiert
- ~~(alt) Stimmprofil wirklich einschreiben und Schwelle mit der echten Stimme prüfen~~ erledigt, siehe Sprecher-Prüfung v2 und Phase 1 (2026-10-04)
- [ ] Flüssigere Stimme, möglichst mit der eigenen Stimme des Nutzers (Klon lokal, nur eigene Aufnahmen mit Einwilligung). **Stand 2026-10-04:** 10 Aufnahmen liegen vor (`voice-data/clone/`, etwa 2,4 Minuten, 24 kHz); der Klon ist noch nicht gebaut. **Der Nutzer hat Chatterbox Multilingual freigegeben, mit Auflage: beim Klonen dürfen keine Daten nach außen gehen** (Torch/CUDA und Modell einmalig aus offiziellen Quellen laden, danach alles Offline mit gesperrtem Netzwerk testen, Aufnahmen verlassen nie den PC). Zero-Shot, also kein Training nötig; XTTS-v2 als Rückfall (`docs/research/voice-clone.md`). Auf Wunsch des Nutzers erst nach dem Loop-Stopp
- ~~Eigenes Wake Word "Hey Kushim" trainieren~~ ersetzt durch freie Wörter ohne Training (siehe oben); Training bleibt nur eine Option, falls die Erkennung mit echter Stimme nicht reicht
- [x] Vorlesetext für Stimmprofil und Stimmklon: `docs/voice-recording-text.md` (5 Einschreibe-Sätze, 10 Absätze für den Klon, Aufnahmetipps) (2026-10-03)
- [x] Aufnahme-Werkzeug `kushim voice record [--mic NAME] [--redo]` (24 kHz mono, 10 Absätze aus dem Vorlesetext, Qualitätsprüfung auf zu leise/übersteuert/zu kurz, Ablage `voice-data/clone/`, git-ignoriert, nur lokal); getestet mit künstlichen Frames, nicht mit echtem Mikrofon (2026-10-03)
- [x] Wake Words per Sprache (Teil 1, 2026-10-03): `voice/wake_commands.py` (hinzufügen/entfernen/auflisten der vortrainierten Wörter; nur verifizierte Stimme, über ActionGate und ApprovalQueue mit Sprach-Bestätigung "ja", mindestens ein Wort bleibt, gilt ab nächstem Start), gespeichert im Vault (`voice/wakewords_store.py`), Vorrang: Kommandozeile > Vault > Konfiguration; 22 Tests, nicht live getestet
- [x] Wake Words per Sprache (Teil 2, 2026-10-03): freie Wörter lassen sich jetzt ohne Training per Sprachbefehl hinzufügen (engine kws) ("merke dir das Wake Word ..."): nur verifizierte Stimme, über ActionGate (umkehrbar, mit Bestätigung), Speicherung im Vault; neue Wörter brauchen ein trainiertes Modell oder Auswahl aus vortrainierten, Weg entschieden 2026-10-03: Auswahl vortrainierter Wörter plus lokales Training neuer Wörter (openWakeWord, synthetische Piper-Daten, im Hintergrund)
- [x] README mit 1:1-Anleitung (Voraussetzungen, Installation, Erster Start, Betrieb, Fehlerbehebung), `install.ps1` (ein Befehl, wiederholbar, -Check, Prüfsummen), `scripts/fetch_models.py`, `kushim doctor` (2026-10-03)
- ~~Umbenennung kushim -> kushim~~ überholt: die Umbenennung wurde zurückgenommen, der Name bleibt **kushim** (siehe nächste Zeile)
- ~~Projekt umbenennen~~ am 2026-10-03 umgesetzt und auf Wunsch des Nutzers wieder zurückgenommen; der Name bleibt **kushim**
- [x] Zentrale Wake-Word-Konfiguration (2026-10-03): eine Datei `wakewords.toml` (Vorlage `wakewords.example.toml`) für alle Wörter, Engines, Schwellen, `cooldown_seconds`, `listen_seconds`; Sprachbefehle schreiben dieselbe Datei; die alten Stellen (`[voice] wake_words` in config.toml, Vault-Speicherung) entfernt
- [x] Aufnahme/Einschreiben mit manueller Steuerung (2026-10-04): Enter startet, Enter beendet jeden Absatz, danach behalten oder neu aufnehmen (`r`), Tastenklick wird abgeschnitten, Höchstdauer 120 s; `--auto` für Ende per Stille
- [ ] Sprecher-Prüfung v2 mit echten Menschen prüfen: `voice enroll` (10 Absätze), dann `voice test` mit kurzen und langen Sätzen von dir UND einer zweiten Person; Zahlen zurückmelden, danach ggf. Schwelle nachstellen oder ein anderes Embedding-Modell prüfen (nur Nutzer)
- [x] Plan für das Setup in der Oberfläche (2026-10-04): `docs/ui-setup-plan.md` (erscheint beim ersten Start, wiederholbar, vier Schritte: Systemcheck+Vault/Schlüssel, Mikrofon/Lautsprecher+Stimme einschreiben, Wake Words, Sicherheit+Notaus; alles überspringbar, Überspringen ändert keine Sicherheitsregel; Anforderungen ans Backend und Tauri-Aufgaben)
- [x] Designer-Skill für die UI (2026-10-04): `.claude/skills/kushim-ui-design/` (Designsprache aus dem Logo, `tokens.css` mit Kontrastprüfung `scripts/contrast.py`, Avatar-Zustandsautomat, Bildschirme, Komponenten, Sicherheitsregeln der UI, Abnahme-Checkliste); `ui-builder` verweist darauf
- [x] Plan für den Modellwechsel in der Oberfläche (2026-10-04): `docs/ui-llm-plan.md` (Einstellungen > Sprachmodell, Probe vor dem Umschalten, Rückweg mit einem Klick, Laden nur mit Freigabe von registry.ollama.ai)
- [x] Modellwechsel, Backend Teil 1 (2026-10-04): `llm/manage.py` (Liste mit Größen oder offline aus den Manifesten, Probe mit Zeitmessung, Umschalten erst nach gelungener Probe, Rückweg über `run/llm-state.json`), API-Typen `llm.get|list|probe|set|rollback` (`api/llm_api.py`, Haken `on_change` für den Austausch zur Laufzeit), `kushim llm test|back` und Anzeige installierter Modelle; 14 Tests
- [ ] Modellwechsel, Backend Teil 2: Laden (`llm.pull`, nur mit Freigabe, Fortschritt, Abbruch/Notaus) und Entfernen (`llm.remove`, nie das aktive/letzte Modell) über die Ollama-Schnittstelle; Austausch zur Laufzeit zwischen zwei Antworten in der Pipeline
- [ ] Modellwechsel, Oberfläche: Bildschirm Einstellungen > Sprachmodell (nach der UI-Toolchain); Entscheidung offen: darf die UI Modelle laden? (siehe Plan)
- [x] Flüssiges Gespräch (2026-10-04, Nutzerwunsch): nach einer Antwort hört kushim `follow_up_seconds` (8 s) ohne Wake Word zu, "das war's"/Stille beendet es; Unterbrechen (`barge_in`): Dazwischensprechen stoppt Denken/Sprechen sofort und wird die nächste Frage (Antwort läuft im Hintergrund-Thread, Mikrofon bleibt offen); Fehler in `prefetch` behoben (hing bei Abbruch). Mit echter Kette und simuliertem Lautsprecher geprüft, nicht mit echtem Mikrofon. Ohne Echo-Unterdrückung kann kushim über Lautsprecher sich selbst hören: Kopfhörer empfohlen
- [x] Unterbrechen und Befehl direkt nach dem Wake Word repariert (2026-10-04, Nutzerberichte "konnte nicht unterbrechen", "Ja? statt Antwort"): Schwellen waren über dem echten Sprechpegel (Median 440; Pegel 1200 löste in 0 % der Sprach-Fenster aus). Neu `speech_level` 200, `barge_in_level` 250 / 240 ms (an den eigenen Aufnahmen gemessen: 100 % Auslösung nach im Median 0,5 s, 0 Fehlauslösungen in Ruhe), `kushim voice level [--apply]` misst das eigene Mikrofon, Vorlauf `preroll_seconds` (1 s vor dem Wake Word nur im Speicher), Hinweiszeile warum "Ja?" kam
- [ ] Flüssiges Gespräch live prüfen (nur Nutzer, Mikrofon): Befehl direkt nach dem Wake Word, Gespräch ohne Wake Word, Unterbrechen mit Kopfhörern und mit Lautsprechern; bei Abweichung `kushim voice level --apply`
- [ ] Optional: Echo-Unterdrückung für Lautsprecher-Betrieb, damit kushim sich dort nicht selbst unterbricht (heute: Kopfhörer empfohlen oder `barge_in_level` erhöhen)
- [x] UI-Setup, Backend-Teil 1 (2026-10-04): `setup/state.py` (`run/setup-state.json`, atomar, kaputt = offen), `setup/status.py` (Status der vier Schritte aus echten Fakten, eingeschränkter Modus), API-Typen `setup.status|skip|reopen|done`, `audio.devices`, `safety.status|kill|resume` (`api/setup_api.py`, transportunabhängig, `ApiError` mit festen Codes), `kushim setup`; 15 Tests mit Fakes
- [ ] UI-Setup, Backend-Teil 2: Abläufe aus `cli.py` (Einschreiben, Aufnahme-Sitzung) in wiederverwendbare Funktionen mit Fortschritts-Rückrufen; API-Typen `vault.*`, `voice.*`, `wake.*` (Wake-Word-Änderung über Bestätigung/ActionGate); Audit-Eintrag für `safety.kill`/`safety.resume` (beim Transport, wenn der Vault offen ist)
- [ ] UI-Setup, Oberfläche: Tauri-Assistent mit Pegel-/Trefferanzeige und Notaus-Knopf (braucht die Tauri/Node-Toolchain, vom Nutzer erlaubt, nur offizielle Quellen)
