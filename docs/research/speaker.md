# Sprecherverifikation

- Paket: PyPI `sherpa-onnx` 1.13.8 (k2-fsa, Apache-2.0), offline.
- Modell: `wespeaker_en_voxceleb_CAM++_LM.onnx` aus dem GitHub-Release `k2-fsa/sherpa-onnx` (`speaker-recongition-models`), 29.292.687 Byte (stimmt mit dem Release überein; das Release liefert keinen Hash). Ablage `models/speaker`. Leak-Test: Laden bei blockiertem Netzwerk ohne Zugriff.
- Messung 2026-10-03 mit synthetischer Piper-Stimme: gleiche Stimme, verschiedene Sätze 0,19 bis 0,98 (Mittel 0,51); weißes Rauschen gegen Stimme 0,43; verändertes Tempo 0,43 bis 0,52. Fazit: mit TTS nicht kalibrierbar. Echte Stimmen sind stabiler, die Schwelle wird deshalb beim Einschreiben aus den Proben bestimmt (80 % der mittleren Ähnlichkeit, begrenzt auf 0,5 bis 0,75, Untergrenze oberhalb des Rauschens). Mit `kushim voice test` kann der Nutzer die Werte prüfen.
- Profil: nur der gemittelte Vektor, im verschlüsselten Vault (`profile`-Tabelle), keine Aufnahme.
