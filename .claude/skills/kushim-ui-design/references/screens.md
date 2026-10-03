# Bildschirme

Zwei Fenstermodi: **Overlay** (klein, transparent, per Hotkey, bleibt im Hintergrund unaufdringlich) und **Dashboard**
(Vollbild/Fenster). Gemeinsamer Kopf in beiden: Logo links, Zustandstext, **NOTAUS rechts oben**.

## Layout-Raster
- Dashboard: Seitenleiste 72 px (Icons mit Text-Tooltip + Beschriftung ab 1100 px), Inhalt max. 1200 px, 12 Spalten, Lücke
  `--s-5`. Unter 800 px: Seitenleiste wird untere Leiste.
- Overlay: 420 x 640, Avatar oben, darunter Transkript, unten Freigabe-Leiste (nur bei `asking`). Hotkey zeigt/versteckt.
- Karten: `--bg-2`, 1 px `--line`, `--r-md`, Innenabstand `--s-5`. Überschrift `--fs-lg`, Fließtext `--fs-md`, Hilfstext `--fs-sm` in `--text-muted`.

## 1. Overlay / Startbild
Avatar (160 px) + Textzeile des Zustands. Darunter das **Live-Transkript** (letzte 4 Äußerungen, "Du" rechts in Cyan-Rand,
kushim links in Bernstein-Rand). Je kushim-Antwort Daumen hoch/runter (44 px, Tooltip "Hilfreich"/"Nicht hilfreich",
`aria-pressed`). Zwischenergebnisse der Spracherkennung erscheinen gedämpft, finale Sätze normal. Kopieren per Klick.
Leer: "Noch nichts gesagt. Sag „hey kushim“ oder schreib unten."; Texteingabe unten (Enter sendet, Shift+Enter Zeilenumbruch).

## 2. Freigabe-Leiste (`asking`)
Erscheint **über** dem Transkript, schiebt nichts weg, nimmt den Fokus (Fokusfalle bis zur Entscheidung, Esc = Ablehnen).
- Titel: Aktion in einem Satz ("E-Mail an anna@example.org senden"). Risiko-Chip: Text + Icon ("Nicht umkehrbar",
  "Sendet nach außen", "Betrifft Dritte"), nie nur Farbe.
- **Exakte Vorschau** im Monospace-Kasten (voller Text, scrollbar, nichts gekürzt); bei Claude-Anfragen: "Dieser Text
  verlässt deinen Rechner:" + der Wortlaut.
- Zeile: "Läuft ab in 02:41" (Zähler), danach "Abgelaufen" und beide Knöpfe aus.
- Knöpfe: **Ablehnen** (Standardfokus, neutral umrandet) und **Erlauben** (Bernstein), gleich groß, nebeneinander,
  Abstand >= `--s-4`. Kein "Immer erlauben". Nach Klick: Ergebnis als Toast ("Gesendet" / "Abgelehnt").
- Bei Notaus oder Ablauf verschwindet die Leiste mit Grund, nichts wird ausgeführt.

## 3. Dashboard
Kacheln, nur mit echten Daten, sonst Leerzustand mit Erklärung ("Keine Recherche gestartet. Frag zum Beispiel …").
- **Heute:** Kalender/Mail-Zusammenfassung (lokal), Aufgabenstatus (offen/läuft/fertig/gescheitert, Text + Icon).
- **Ergebnisse:** Recherche mit Quellenliste (Titel, Domain, Zeitpunkt); Quellen sind Text, Link öffnet erst nach Klick im Systembrowser.
- **Aktivität:** letzte Aktionen mit Entscheidung des Gates (erlaubt/gefragt/verweigert) und Zeit.
- Ladezustand: Skelett in `--bg-3`, kein Spinner länger als 1 s ohne Text; Fehler mit Grund und "Erneut versuchen".

## 4. Gedächtnis
Durchsuchbare Liste (Suchfeld oben, `/` fokussiert), je Eintrag Text, Quelle, Datum. Bearbeiten inline, **Löschen mit
Rückgängig-Toast (10 s)**, endgültiges Löschen nur über "Papierkorb leeren" mit Bestätigung. Anzeige, wo der Vault liegt
und wann das letzte Backup war. Schlüssel und Rohdaten nie anzeigen. Leer: "Noch keine Erinnerungen."

## 5. Sicherheitsstatus
Ampelzeilen (Wort + Icon + Farbe): Modus A/C ("Lokal" / "Claude erlaubt"), Sprecher verifiziert (letzte Prüfung, Wert,
Schwelle, "stark"/"normal"), Notaus (bereit/aktiv), Vault (Ort, entsperrt), letztes Backup, Audit-Log (letzte 50
Einträge, filterbar, nur lesen), Geldlimit ("0 €, gesperrt"). Warnungen oben, sachlich ("Backup älter als 7 Tage").
Modus C wird dauerhaft in der Kopfzeile markiert, solange er aktiv ist.

## 6. Setup-Assistent
Folgt `docs/ui-setup-plan.md` (vier Schritte). Links Fortschrittsleiste (Schritt, Status Text + Icon), rechts Inhalt,
unten **Zurück / Überspringen / Weiter** (Überspringen immer erlaubt, mit Satz zur Folge). Pegelanzeige und Trefferanzeige
als Balken mit Zahl. Aufnahme-Absatz groß (`--fs-xl`, Zeilenhöhe 1,6), Start/Fertig als große Knöpfe, Leertaste/Enter
als Kürzel, Fortschritt "Absatz 3 von 10". Ergebnisse ehrlich mit Zahlen und Warnung bei geringer Trennung.
Schlüssel-Sicherung: Erklärung + Checkbox "Ich habe den Schlüssel gesichert", **Schlüssel wird nicht angezeigt**.

## 7. Notaus
Immer sichtbar: Pille oben rechts, `--alarm` Fläche, Text "NOTAUS", min. 44 x 44. Nach Auslösen: ganze Kopfzeile rot
getönt, Avatar `halted`, Banner "NOTAUS aktiv" mit Knopf "Aufheben" (öffnet kurze Bestätigung: "Alle Dienste dürfen wieder
starten."). Tastenkürzel (z. B. Strg+Umschalt+K) löst ihn auch aus, steht im Tooltip.

## 8. Einstellungen > Sprachmodell
Plan und Ablauf in `docs/ui-llm-plan.md`. Karte "Aktuelles Modell" (Name in `--font-mono`, Größe, Status mit Text, gemessene
Antwortzeit), darunter die Liste installierter Modelle (aktives mit Häkchen **und** "Aktiv", Knopf **Verwenden**), dann
"Modell hinzufügen" (Feld mit Prüfung, kleine Vorschlagsliste). **Verwenden** zeigt zuerst das Ergebnis der Probe (Zeit,
Hinweis), erst **Jetzt verwenden** schaltet um; "Zurück zu <vorher>" bleibt sichtbar. **Laden** öffnet die Freigabe-Leiste
mit Quelle (`registry.ollama.ai`), Ziel und freiem Speicher, Standardfokus auf Ablehnen; Fortschritt als Balken mit Zahl und
**Abbrechen**. Fremde Quellen (`hf.co/...`) brauchen eine zweite Bestätigung mit Warnung. Bei Notaus sind alle Knöpfe aus.

## Mikrotexte (Ton)
Deutsch, Du-Form, ruhig, sachlich, kurz. Kein "Oops", keine Ausrufezeichen, keine Emojis in der Oberfläche.
Fehler: **Was ist passiert + was jetzt.** ("Backend nicht erreicht. Starte kushim über die Verknüpfung.")
Verweigerung: "Das habe ich nicht getan, weil …" mit dem Regelgrund aus dem Backend.
Zahlen: Dezimalkomma, Einheit mit Leerzeichen ("0,79", "2,5 s").

## Zustände, die jeder Bildschirm haben muss
leer, lädt, Erfolg, Fehler, Backend offline, Notaus aktiv, eingeschränkter Modus, Stimme unbekannt (nur Hinweis, keine Daten).
