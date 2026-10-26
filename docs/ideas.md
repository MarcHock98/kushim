# Feature-Ideen (nur Vorschläge, nichts davon ist beschlossen)

Gesammelt vom Ideen-Loop (`/loop`, ein Themenfeld pro Durchlauf). Die Roadmap ändert nur der Nutzer. Regeln für jede
Idee: kein Schaden, keine Manipulation, keine Abhängigkeit; lokal zuerst (Modus A); alles mit Außenwirkung über
`ActionGate` und Freigabe; Werkzeuge standardmäßig aus (`kushim-add-tool`).

Skala: Aufwand S (Tage) / M (eine Woche) / L (länger). Egress = geht etwas ins Netz.

## Themenfeld 1: Alltag und Haushalt (2026-10-04)
Quelle für den Stand der Technik: lokale Sprachassistenten (Whisper + Piper + lokales LLM, z. B. Home Assistant Assist)
decken Gerätesteuerung und Routinen ohne Cloud ab; kushim hat bisher Timer, Notizen und Recherche, aber keine Listen,
Routinen oder Ruhemodus.

### 1. Listen per Sprache (Einkauf, To-do)
- **Nutzen:** "Setz Milch auf die Einkaufsliste", "Was steht auf der Liste?", "Streich Milch". Ergänzt Notizen um
  abhakbare Einträge.
- **Aufwand:** S. **Risiko:** niedrig (nur lokale Daten). **Egress:** nein. **Modus:** A.
- **Abhängigkeiten:** Vault (`kind=list`), Muster von `voice/note_commands.py`, Löschen nur nach Rückfrage.
- **Phase:** 3 (neben Timer und Notizen), Werkzeug `lists.local`.

### 2. Tagesübersicht auf Zuruf
- **Nutzen:** "Was steht heute an?" fasst laufende Timer, Erinnerungen, letzte Notizen und (später) Kalender
  zusammen, kurz gesprochen. Nur auf Anfrage, nie ungefragt.
- **Aufwand:** M. **Risiko:** niedrig. **Egress:** nein (Wetter nur optional und nur mit eigener Freigabe).
- **Modus:** A. **Abhängigkeiten:** `timers.py`, Notizen, später "Mail und Kalender (lokal)".
- **Phase:** 3, nach Kalender.

### 3. Szenen und Routinen ("Guten Abend")
- **Nutzen:** Ein Satz löst eine feste, vom Nutzer angelegte Folge aus (Licht dimmen, Musik, Timer). Die Folge ist
  eine Liste fester Aktionen, kein freies LLM-Handeln.
- **Aufwand:** M. **Risiko:** mittel: jede Aktion läuft einzeln durch `ActionGate`, Szene wird beim Anlegen angezeigt
  und bestätigt, Notaus bricht sie ab, keine Szene darf Aktionen mit Geld oder Löschen enthalten.
- **Egress:** nein (lokales Smart Home). **Modus:** A. **Abhängigkeiten:** Smart-Home-Tool, `TaskRegistry`.
- **Phase:** 3, nach "Smart Home und Musik".

### 4. Sanfte wiederkehrende Erinnerungen (Wasser, Pause, Medikamente)
- **Nutzen:** Täglich oder wochentags zu festen Zeiten, vom Nutzer eingerichtet; eine Ansage, kein Nachhaken, keine
  Streaks, kein Druck. Verpasst heißt nur "verpasst", ohne Vorwurf.
- **Aufwand:** S. **Risiko:** niedrig, aber heikel bei Gesundheit: kein medizinischer Rat, Text kommt vom Nutzer,
  Hinweis "ersetzt keinen Medikationsplan". **Egress:** nein. **Modus:** A.
- **Abhängigkeiten:** Erweiterung von `timers.py` um Wiederholung (heute höchstens 7 Tage).
- **Phase:** 3, direkt an `timer.local`.

### 5. Ruhemodus ("nicht stören")
- **Nutzen:** Solange aktiv, spricht kushim nichts von sich aus (Timer-Ansagen werden als Text gesammelt und danach
  einmal genannt), reagiert aber weiter auf Wake Word und Notaus. Ende per Sprache oder Uhrzeit.
- **Aufwand:** S. **Risiko:** niedrig; Notaus und Wake Word bleiben unverändert, Ansagen gehen nicht verloren.
- **Egress:** nein. **Modus:** A. **Abhängigkeiten:** Ansage-Weg in `voice/talk.py`, `timers.py`.
- **Phase:** 2b/3 (Sprach-Pipeline), vor mehr Ansagen von Claude-Läufen.

Quellen: [Local Voice Assistants in 2026](https://emersonsmart.com/blogs/news/local-voice-assistants-in-2026-complete-privacy-without-internet),
[Build a Fully Local Voice Assistant for Your Smart Home](https://www.promptquorum.com/smart-home/local-voice-assistant-smart-home)

## Als Nächstes dran (Reihenfolge der Themenfelder)
2 Produktivität · 3 Barrierefreiheit · 4 Sicherheit und Datenschutz · 5 Gedächtnis und Lernen · 6 Entwicklung mit Claude ·
7 Smart Home und Musik · 8 Wohlbefinden ohne Abhängigkeit
