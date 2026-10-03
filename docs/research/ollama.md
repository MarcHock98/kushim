# Ollama

- Quelle: GitHub-Release ollama/ollama v0.35.1, `ollama-windows-amd64.zip` (1.471.094.402 Byte), SHA256 `dc50b9ca...e8e93` stimmt mit dem Release überein. Standalone statt Installer, damit kein Auto-Updater/Tray-App.
- Start: `OLLAMA_HOST=127.0.0.1:11434 OLLAMA_MODELS=<projekt>/models/ollama tools/ollama/ollama.exe serve`.
- Prüfung 2026-10-03: Port 11434 lauscht nur auf 127.0.0.1, keine ausgehenden Verbindungen im Leerlauf. Das einzige Netzwerk war der Modell-Pull (registry.ollama.com) mit Zustimmung des Nutzers.
- Modell: qwen2.5:7b (~4,7 GB), Antwort auf Deutsch, erster Aufruf ~34 s (Laden), siehe Latenz-Punkt in der Roadmap.
