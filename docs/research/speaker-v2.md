# Sprecher-Prüfung v2 (längere Eingabe)

Stand 2026-10-04. Wunsch des Nutzers: Stimmerkennung neu gestalten mit längerer Spracheingabe; Einschreiben mit den
10 Klon-Absätzen; längere Äußerung = sicherer; zusätzlich längere Spracheingabe für Befehle.

## Entwurf
- **Einschreiben:** 10 Absätze (ca. 5 Min, 24 kHz -> 16 kHz) -> überlappende 3-s-Fenster -> Embeddings -> k-means zu bis zu
  6 Prototypen (statt einem Mittelwert). Bewertung einer Probe = Ähnlichkeit zum nächsten Prototyp.
- **Schwelle aus Daten:** Leave-one-recording-out (eigene zurückgehaltene Aufnahmen) gegen eine Kohorte fremder Stimmen
  (Rauschen plus 30 Sprecher des Piper-Mehrsprecher-Modells MLS, 236 Stimmen, `models/piper-cohort/`). Schwelle = Mitte
  zwischen schwächsten 10 % der eigenen Werte und oberen 5 % der Fremden, begrenzt auf 0,5 bis 0,9; die Trennung wird gemeldet.
- **Prüfung:** unter 0,8 s abgelehnt; bis 4 s ein Embedding (kürzer als 3 s wird durch Wiederholung auf 3 s aufgefüllt);
  länger: Fenster, Median >= Schwelle und mind. 60 % der Fenster. "Stark" = angenommen, mind. 1,5 s und Wert >= Schwelle +
  Abstand (höchstens Mitte zwischen Schwelle und 1,0). Änderungen (Wake Words) brauchen "stark"; eine kurze Bestätigung
  ("ja") darf ab 0,4 s kommen, aber nur direkt nach einer stark verifizierten Anfrage.
- **Längere Eingabe:** `end_silence_seconds` 1,2 s (früher 0,8) und `max_seconds` 60 s (früher 15) in `wakewords.toml`.

## Messungen (NUR künstliche Stimmen: "Ich" = Piper Thorsten, Fremde = 30 andere MLS-Sprecher, die nicht in der Kohorte waren)

| Variante | Satzlänge | "Ich" akzeptiert | Fremde akzeptiert |
|---|---|---|---|
| ohne Auffüllen, Schwelle 0,8 | kurz | 0 % | 31 % |
| ohne Auffüllen, Schwelle 0,8 | lang | 100 % | 72 % |
| mit Auffüllen, Schwelle 0,8 | kurz | 92 % | 62 % |
| **mit Auffüllen, Schwelle 0,9 (Endstand)** | kurz | 75 % (stark 8 %) | 2,8 % (stark 0 %) |
| **mit Auffüllen, Schwelle 0,9 (Endstand)** | lang | 100 % (stark 83 %) | 5,6 % (stark 0 %) |

Einzelbefund: Dieselbe Stimme erreicht auf 3-s-Fenstern 0,93 bis 0,96 (stabil), auf einem kurzen Satz ohne Auffüllen nur ca. 0,25.
Rauschen erreichte gegen Prototypen bis 0,77: Der Schutz davor ist das Spracherkennungs-Gate (leerer Text = keine Verarbeitung).
Verzerrte Kopien derselben Stimme sind KEINE Fremdstimmen (der Test mit ihnen war ungültig und wurde verworfen).

## Grenzen (ehrlich)
- Gemessen wurde nur mit künstlichen Stimmen. Das Embedding-Modell (WeSpeaker, englisch/VoxCeleb) trennt künstliche deutsche
  Stimmen nur schwach (Trennung ca. 0,01). Echte Menschen unterscheiden sich vermutlich stärker; das ist ungeprüft.
- Die Prüfung ist eine Hürde, keine Authentifizierung: Aufnahmen/Wiedergabe der echten Stimme oder gute Stimmklone können sie
  überwinden. Der ActionGate gilt weiter, Aktionen bleiben bestätigungspflichtig.
- Nur ein Test mit deiner Stimme und einer zweiten echten Person (`kushim voice test`) zeigt die wahren Quoten.
