# Wake Word und Hotkey (Windows, Python 3.12)

Datum: 2026-10-03

- Frage: Wie läuft openWakeWord auf Windows mit Python 3.12?
  Fazit: `tflite-runtime` hat dort keine Wheels, daher nur ONNX-Pfad. Install mit
  `pip install --no-deps openwakeword` plus `onnxruntime numpy scipy scikit-learn tqdm`.
  Quellen: github.com/dscripka/openWakeWord, github.com/OpenVoiceOS/ovos-ww-plugin-openWakeWord (PR #36)
- Frage: Hotkey-Bibliothek für Push-to-Talk?
  Fazit: `pynput` (aktiv gepflegt, `GlobalHotKeys` und Press/Release-Listener). `keyboard` ist Alternative.
  Quelle: pynput.readthedocs.io
- Risiko: Ein globaler Tastatur-Listener sieht alle Tasten. Nur die konfigurierte Taste auswerten, nichts speichern oder loggen.
