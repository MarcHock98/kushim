---
name: kushim-next-phase
description: Use to continue kushima development: reads ROADMAP.md, picks the next unfinished item, plans and implements it with tests and safety review.
---

# Nächsten Roadmap-Schritt bearbeiten

1. `ROADMAP.md` lesen, das erste offene Element (`[ ]`) der frühesten Phase wählen.
2. Kurz planen: Ziel, betroffene Dateien, Sicherheitsrisiken. Bei einer echten Nutzerentscheidung (Hardware, Dienst, Kosten, Daten nach außen) nachfragen, sonst weitermachen.
3. Umsetzen im Stil des vorhandenen Codes. Neue Fähigkeiten über `kushim-add-tool`.
4. Tests schreiben und ausführen (`.venv\Scripts\python -m pytest -q`).
5. `kushim-safety-review` ausführen.
6. Element in `ROADMAP.md` abhaken, nur wenn getestet und geprüft.
7. Committen auf Nutzerwunsch; nie ungefragt pushen.

Leitplanken: lokal zuerst (Modus A), Claude nur Opt-in (Modus C), Gedächtnis nie nach außen, Vault-Ort nur über `memory.location`.
