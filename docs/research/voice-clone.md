# Stimmklon (eigene Stimme, lokal)

Stand 2026-10-03. Hardware: RTX 3070 (8 GB VRAM). Quellen: GitHub-Repos der Projekte (Primär) plus Websuche (nur Orientierung).

| Modell | Deutsch | Lizenz | Anmerkung |
|---|---|---|---|
| Chatterbox Multilingual (Resemble AI, PyPI `chatterbox-tts`) | ja (23+ Sprachen laut Repo) | MIT | Zero-Shot-Klon aus kurzer Referenz; jede Ausgabe trägt ein unhörbares Perth-Wasserzeichen; Python 3.11 getestet (hier läuft 3.12, Kompatibilität offen); Torch/CUDA-Download nötig |
| XTTS-v2 (Coqui, gepflegter Fork `coqui-tts` von idiap, Code MPL-2.0) | ja | Modell unter CPML (nicht kommerziell, privat ok) | bewährt, ca. 4 GB VRAM; Torch muss separat installiert werden |
| F5-TTS | eingeschränkt | CC-BY-NC | Deutsch schwächer |
| Piper (Feintuning) | ja | MIT | kein Zero-Shot; Training auf eigenem Datensatz, aufwendiger |

Offen/zu prüfen vor dem Einsatz: Torch mit CUDA ist ein großer Download (über 2 GB, Nutzer fragen), Python-3.12-Kompatibilität, Offline-Betrieb nach dem Modell-Download (Netzwerk blockieren und testen), Qualität gegen die eigenen Aufnahmen (`kushim voice record`). Das Chatterbox-Wasserzeichen ist unkritisch für privaten Gebrauch, aber zu erwähnen.

Empfehlung: zuerst Chatterbox Multilingual (MIT, Deutsch ausdrücklich) mit den eigenen 10 Aufnahmen als Referenz testen; XTTS-v2 als Rückfalloption.

## Ergebnis 2026-10-04 (Umsetzung Chatterbox)
- Installiert in eigenem venv `tools/chatterbox` (git-ignoriert): torch 2.6.0+cu124 (download.pytorch.org, offiziell), `chatterbox-tts==0.1.7` (PyPI, MIT, Resemble AI, 26.03.2026). Modell: Hugging Face `ResembleAI/chatterbox`, genau 6 Dateien (ve.pt, t3_mtl23ls_v2.safetensors 2,1 GB, s3gen.pt 1,1 GB, conds.pt, zwei JSON), 3,0 GB.
- Deutsch (`language_id="de"`) unterstützt. Ausgabe 24 kHz, hier als 16-Bit-PCM-WAV geschrieben (Float32-WAV kann kushims Wiedergabe nicht).
- Offline: `HF_HUB_OFFLINE=1` plus Sperre jeder Nicht-Loopback-Verbindung im Prozess. Dabei fiel auf: `spacy_pkuseg` (Chinesisch) lädt bei jeder Initialisierung ein Modell von GitHub, die Sperre stoppte es; der Import wird im Worker verhindert, Deutsch ist unberührt. Das Paket meldet eine Warnung zum Cangjie-Mapping (nur Chinesisch).
- Messung RTX 3070: Laden 12 s, danach 2 bis 4 s pro Satz (Faktor 0,85 bis 1,14 zur Audiolänge). Ähnlichkeit (WeSpeaker) zur eigenen Stimme 0,57 bis 0,63, Piper 0,54: bei synthetischer Sprache wenig aussagekräftig, entscheidet das Gehör.
- Wasserzeichen: Chatterbox bettet ein unhörbares Perth-Wasserzeichen ein (privat unkritisch).
