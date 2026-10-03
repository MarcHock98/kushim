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
