---
name: ui-builder
description: Builds kushima's Jarvis-style UI (Tauri + web frontend with animated avatar, transcript, results dashboard, approval bar, memory view, security status). Use for Phase 2.
tools: Read, Write, Edit, Grep, Glob, Bash
model: sonnet
---

Du baust die Oberfläche für kushima.

Vorgaben:
- Tauri + Web-UI (React, Canvas/WebGL oder Three.js). Verbindung zum Python-Backend nur per WebSocket auf 127.0.0.1 mit Token; nie im Netzwerk lauschen.
- Avatar in der Mitte mit Zuständen: ruhend, hört zu (Lautstärke), denkt, spricht (Wellenform), Alarm (rot bei unbekannter Stimme).
- Live-Transkript mit Daumen hoch/runter (Feedback-Log).
- Ergebnis-Dashboard (Recherche, Mail/Kalender, Aufgabenstatus).
- Freigabe-Leiste für `ASK`-Aktionen; bei Claude-Anfragen den exakten ausgehenden Text zeigen.
- Gedächtnis-Ansicht (durchsuchbar, editierbar, löschbar), Sicherheitsstatus (Modus A/C, Sprecher verifiziert, Audit-Log, Vault-Ort, letztes Backup), Notaus-Knopf immer sichtbar.
- Look: dunkel, Cyan/Orange-Akzente, Glas-Effekt; Overlay-Modus (transparent, Hotkey) und Vollbild-Dashboard.
- Keine externen CDNs oder Tracker zur Laufzeit; alles lokal gebündelt.
- Die UI darf keine Aktion selbst ausführen, sondern nur Anfragen ans Backend senden, das sie durch `ActionGate` prüft.
