# TTS: Kokoro-82M deutsch, Stimme „Martin“ (ONNX)

Stand 2026-11-24. Entscheidung des Nutzers nach einem Hörvergleich: Kokoro „Martin“ ersetzt Piper (thorsten-high). Nur die
eingebaute Stimme, kein Klonen. Grundlage sind zwei Evaluationen (`tools/tts-eval/ERGEBNIS.md`, `tools/tts-eval2/ERGEBNIS.md`,
beide git-ignoriert); dieses Dokument fasst sie zusammen.

## Was kushim benutzt

- Modell: `Godelaune/Kokoro-82M-ONNX-German-Martin` (früher `huggingFresse/...`, HF leitet weiter), Revision
  `a1cba7fbf0e72fbae38f0a3a48ce0dc8e6077804`, Dateien `kokoro-martin.onnx` (325 512 630 B, SHA-256 `c302f1d8…49276b`) und
  `voices-martin.npz` (522 506 B, `5b9c8553…105acd`), Ablage `models/kokoro/` (git-ignoriert). Lizenz Apache-2.0 (Model Card;
  Basis kikiri-tts/kikiri-german-martin, Architektur hexgrad/Kokoro-82M). `scripts/fetch_models.py` lädt und prüft sie, oder
  übernimmt sie geprüft aus `tools/tts-eval2/dl/kokoro-martin-hf`.
- Laufzeit: eigener Prozess `scripts/kokoro_worker.py` im eigenen venv `tools/kokoro/venv` (Python 3.12): onnxruntime-gpu
  1.32.0 mit CUDA 13/cuDNN aus pip-Wheels, kokoro-onnx 0.5.0, phonemizer-fork 3.3.2, espeakng-loader 0.2.4 (bringt espeak-ng als
  DLL mit, keine Systeminstallation). Pakete mit Hashes: `scripts/kokoro-requirements.txt`. kushims `.venv` behält das
  CPU-onnxruntime (faster-whisper braucht es) und hat kein Piper mehr in `pyproject.toml`.
- Lizenzen: Modell und Normalisierungsregeln Apache-2.0, kokoro-onnx MIT, onnxruntime MIT, phonemizer-fork GPL-3.0,
  espeak-ng GPL-3.0, CUDA-Wheels NVIDIA-Lizenz. Bei rein privater Nutzung unkritisch; vor einer Weitergabe neu prüfen (GPL).
- Sprechtempo 1,125 wie im Skript des Modell-Repos.

## Aufbau in kushim

- `voice/ttsworker.py` (Client): startet den Worker über stdin/stdout (Rahmen: 4 Byte Länge + JSON-Kopf + WAV-Bytes; Kopf
  höchstens 64 KiB, Nutzdaten höchstens 16 MiB), kein Socket. Umgebung nur nach Liste (keine Tokens), kein Fenster
  (`hidden()`). Watchdog je Satz, Neustart nach Absturz mit Pause (höchstens 3 in 10 Minuten), Notaus beendet den Worker per
  `kill_tree` (`KillSwitch`-Aktion), Beenden schickt `quit` und dann `kill_tree`. Zustand für die Oberfläche in
  `run/voice-state.json`, Feld `tts`: loading | ready | cpu | failed | off.
- CPU-Rückfall: Scheitert CUDA (Laden, GPU voll, CUDA-Fehler, Absturz oder Hänger auf der GPU), startet der Worker mit dem
  CPU-Provider neu. Erst wenn auch das scheitert: Text plus Hinweiston (`earcon.hint_wav`), nie Stille.
- `scripts/kokoro_worker.py`: sperrt als Erstes das Netz im Prozess (Socket-Erzeugung, Verbindungen, Namensauflösung,
  `socketpair`, auch Loopback) und setzt Offline-Variablen; erst danach werden onnxruntime und kokoro-onnx geladen. Schreibt nur
  Protokollrahmen nach stdout, alles andere nach stderr (`run/tts-worker.log`), nie den Text.
- `voice/tts.py`: Satzteilung mit Schutz für Abkürzungen, Datum und Ordinalzahlen; erster Satz über 60 Zeichen wird am Komma
  geteilt; Satz n+1 wird gerechnet, während Satz n läuft; Satz-Cache nur für feste Sätze aus dem Code („Ja?“, „Moment.“,
  Bestätigungen).
- `voice/speechnorm.py`: deutsche Normalisierung (Uhrzeit, Datum, Zahlen, Prozent, °C, Einheiten, Euro, Abkürzungen),
  abgeleitet von `german_text_rules.py`/`tts_normalizer.py` aus dem Modell-Repo (Apache-2.0, Lizenztext
  `docs/licenses/Apache-2.0.txt`) und erweitert. Läuft nach `imitation.guard` und entfernt Steuerzeichen.
- Start: zuerst Whisper, dann der Worker (auf derselben Karte wie Whisper; ohne Karte auf dem Prozessor).
- Nachträge aus der Prüfung (2026-11-24):
  - Die Normalisierung entfernt Anführungszeichen, Emoji und Symbole und läuft nach `imitation.guard`. Deshalb prüft der
    Speaker jeden Satz von Claude danach noch einmal mit `imitation.imitates_system` (auch über zwei Sätze); Treffer werden zu
    `imitation.NEUTRAL`. kushims eigene Ansagen kennzeichnet `earcon.mark` je Satz: `MARK` (erster Satz, mit Signalton) bzw.
    `OWN` (Folgesätze), jeder mit `END`; `split_sentences` leitet nichts ab. Freigabe-Ansagen und Texte von Claude laufen als
    getrennte Stücke (Listen), auch beim Nachreichen. Keines der Zeichen kann Claude senden. Die zweite Prüfung läuft über ein
    gleitendes Fenster (160 Zeichen) aller fremden Sätze eines `say` und über verschärfte Fassungen (Trennzeichen in Wörtern
    entfernt, Nachbarwörter zusammengezogen); `safety/` bleibt unverändert. Seit der dritten Prüfung faltet
    `voice/imitation_fold.py` den Text zusätzlich (NFKD, ohne kombinierende Zeichen, Doppelgänger-Buchstaben), zieht 2–4
    Wortteile über sprechbare Lücken zusammen und sucht Kernwörter (Notaus samt „Nohtaus“/„Notausschalter“, aber nicht
    „Notausgang“; Freigabe … erteilt; Terminal … bestätig; „erlauben?“). Bekannte Falsch-Positive: „Not, aus der man lernt“. In gesprochenen Freigabe-Ansagen entschärft
    `speakable.announce` eingebaute Befehle, Dateinamen, Suchbegriffe usw. (keine eigenen Sätze, Nachahmungen ausgeblendet).
  - Kokoro schafft höchstens 510 Phoneme (darüber IndexError bzw. stilles Abschneiden). Der Speaker teilt jeden Abschnitt auf
    höchstens 250 Zeichen (Komma, Doppelpunkt, Strich, „und“/„oder“, Wortgrenze), der Worker halbiert zusätzlich ab 480
    Phonemen. Der Client schneidet nie ab.
  - Der Worker bekommt einen eigenen Temp-Ordner (`run/tts-tmp`; phonemizer legt dort Kopien von `espeak-ng.dll` ab, der
    Worker räumt beim Start nur dort auf), schaltet die onnxruntime-Telemetrie per `disable_telemetry_events()` ab und startet
    bei aktivem Notaus (Marker-Datei) nicht und nicht neu.

## Messung in kushim (2026-11-24, RTX 3070, Whisper large-v3-turbo float16 geladen, kushim lief nicht)

| | GPU (CUDA) | CPU |
|---|---|---|
| Laden bis bereit (inkl. Aufwärmen) | 1,6 s | 1,2 s |
| erster Ton, ganzer Satz (Median, 5 Sätze) | 0,22 s | 0,56 s |
| erster Ton mit Komma-Teilung (wie kushim) | 0,11 s | 0,30 s |
| Speaker bis zum ersten Abspielen | 0,11 s | 0,27 s |
| Echtzeitfaktor (Median) | 0,06 | 0,15 |
| GPU-Speicher | +0,7 GB nach Laden, Spitze +0,9 GB (3,3 → 4,2 GB) | 0 |

Arena des CUDA-Providers: `kSameAsRequested`, Obergrenze 2 GB. Zahlen-Satz („Es ist 14:35 Uhr, … 9 °C, … 87 %“) wird zu „vierzehn
Uhr fünfunddreißig … neun Grad Celsius … siebenundachtzig Prozent“ (GPU 0,45 s für 6,3 s Audio).

## Evaluation 1 (2026-11-23): Piper, Chatterbox, Qwen3-TTS

| | Piper thorsten-high | Chatterbox Multilingual V3 | Qwen3-TTS 0.6B |
|---|---|---|---|
| Median erster Ton | 0,32 s (CPU) | 2,52 s (GPU fp32, kein Streaming) | 10,2 s |
| Echtzeitfaktor | 0,09 | 0,69 | 1,89 |
| GPU-Spitze mit Whisper | 3,8 GB | 7,4 GB | 6,4 GB |
| Ziffern („14:35“, „9 °C“) | holprig | falsche Zahlen | „°C“ falsch |

Ergebnis damals: Piper als einzige Stimme im Latenzziel; Chatterbox nur als Zusatzmodus denkbar; Qwen zu langsam und ohne
deutsche Stimme. Erkenntnis für jede Stimme: kushim braucht eine Textnormalisierung.

## Evaluation 2 (2026-11-23): Kokoro, Chatterbox-Streaming, ZONOS3-Mini, Phonon

| Kandidat | erster Ton (Median) | Preis |
|---|---|---|
| Kokoro Martin ONNX, GPU | 0,21 s | +1,2 GB VRAM (ohne Obergrenze), venv 2 GB |
| Kokoro Martin ONNX, CPU | 0,51 s (lange Sätze 0,63–0,67 s) | kein VRAM, venv 0,2 GB |
| Kokoro Thorsten (PyTorch), GPU / CPU | 0,09 s / 0,43 s | torch-venv 5 GB |
| ZONOS3-Mini, `start_immediately` | lückenlos ab 0,37 s (f32) / 0,46 s (bf16) | 7,2–7,8 GB VRAM mit Whisper, 15 GB Platte |
| Chatterbox-Streaming (Chunk 25) | 0,89–1,0 s | S3Gen kostet je Stück ~0,55 s |
| Piper (Referenz) | 0,33 s | – |

- Whisper-Wortfehlerrate bei Kokoro Martin 0 % (5 Sätze). Die Normalisierung des Modell-Repos liest Uhrzeit und °C richtig.
- Hinweis aus der Messung: Bei der Ja/Nein-Frage („Soll ich die Änderung übernehmen?“) **fällt** die Melodie am Ende (−6,5
  Halbtöne), bei Piper stieg sie. Der Nutzer hat nach dem Hören trotzdem Kokoro Martin gewählt.
- Phonon-40m-de und Pocket TTS sind gated (Konto, Token) und wurden nicht gemessen; Phonon ist nur nichtkommerziell lizenziert.

## Früher: Piper (2026-10-03 bis 2026-11-24)

`piper-tts` 1.8.0 (GPL-3.0-or-later), Stimme `rhasspy/piper-voices` `de/de_DE/thorsten/high`. Aus Code und `pyproject.toml`
entfernt; `models/piper/` und das Paket in `.venv` bleiben liegen, bis der Nutzer sie selbst entfernt. Die Testaudios für die
Wake-Word-Erkennung (`tests/data/kws/`) wurden vorher einmal mit Piper erzeugt.
