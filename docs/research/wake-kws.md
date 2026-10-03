# Freie Wake Words ohne Training (KWS)

Stand 2026-10-03. Wunsch des Nutzers: eigene Wake Words "hey kushim", "kushim", "kush", "hallo kush", "hi kushim",
"kushi" (kein "hey jarvis"), zentral konfigurierbar.

- Weg: sherpa-onnx `KeywordSpotter` (offenes Vokabular, kein Training). Modell
  `sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01` (englisch, 17,6 MB) aus dem Release `kws-models` von
  k2-fsa/sherpa-onnx, SHA-256 `f170013b...561a` laut `checksum.txt` des Releases geprueft. Ablage `models/kws/`
  (nicht im Git). Woerter werden per BPE (sentencepiece 0.2.1) in Tokens zerlegt, Schwelle (`#`) und boost (`:`) je Wort.
- Alternative (verworfen): eigene openWakeWord-Modelle trainieren. Auf Windows sehr aufwendig (Linux-Trainingspipeline,
  viele GB Hintergrunddaten), pro Wort ein eigenes Modell.

## Messung (nur synthetische Piper-Stimme, 18 Aufrufe = 6 Woerter x 3 Varianten, 10 Negativsaetze, Blockweise wie am Mikrofon)

| Schwelle | boost | erkannt | Fehlalarme |
|---|---|---|---|
| 0.25 | 1.5 | 7 von 18 | 0 in 10 Saetzen |
| 0.15 | 2.0 | 11 von 18 | 0 in 10 Saetzen |
| 0.10 | 3.0 | 12 von 18 | 1 in 10 Saetzen |

Gewaehlt: Schwelle 0.15, boost 2.0 (Standard).

## Grenzen
- Das Modell ist englisch; "kushim" wird ueber englische BPE-Teile abgebildet. Mit echter Stimme kann es besser oder schlechter sein.
- Woerter mit gleichem Anfang (kush, kushi, kushim) sind nicht sicher zu unterscheiden; jeder Treffer loest aus, der gemeldete Name kann der kuerzere sein.
- Sehr kurze Woerter ("kush", "kushi") loesten in einem ersten Test bei "Kusch"/"Kuschelbaer" aus.
- Eine Fehlausloesung oeffnet nur das Zuhoeren; Befehle brauchen weiter die verifizierte Stimme.
- Nur ein Test mit echter Stimme (`kushim talk`) zeigt die wahre Trefferquote.
