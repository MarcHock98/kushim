# Plan: Lernen (Bandit für Antwortstile, Reflexionsschleife, Nutzerprofil)

Stand 2026-10-04. Noch nichts davon ist gebaut. Dieser Plan legt fest, was gebaut wird und welche Entscheidungen beim Nutzer liegen.
Bis zur Antwort gelten die **Standardwerte** unten (vorsichtigste Variante).

## Grundsätze (nicht verhandelbar)
1. **Lernen ändert nur Stil, nie Rechte oder Regeln.** Kein Lernschritt darf `ActionGate`, `rules.py`, Notaus, Egress-Regeln, Werkzeug-Schalter
   oder den festen Sicherheitsteil des Systemprompts berühren. Arme des Bandits sind reine Bezeichner (siehe `learning/bandit.py`).
2. **Sicherheitsverstoß ist immer -1**, Schmeichelei und Abhängigkeit ziehen ab, Lob gleicht das nie aus (`bandit.reward`).
3. **Nichts Persönliches ohne Klick des Nutzers.** Vorschläge sind Vorschläge; gespeichert wird erst nach "Übernehmen".
4. **Lokal.** Auswertung und Reflexion nur mit dem lokalen Modell (Modus A), nie über Claude oder das Netz.
5. **Löschbar.** Alles Gelernte ist in der Gedächtnis-Ansicht sichtbar, änderbar und löschbar (Rückgängig-Frist).

## Teil A: Bandit für Antwortstile
- **Arme:** Stil-Sätze, die an den festen Systemprompt ANGEHÄNGT werden (z. B. "kurz", "ausführlicher", "direkt", "freundlicher"). Der feste Teil
  mit Regeln und Schutzsätzen bleibt unverändert davor. Jeder Stil wird vorab mit `kushim behavior` geprüft (neuer Schalter `--style`); fällt er durch,
  wird er nie angeboten.
- **Reward:** Daumen (+1/-1, `feedback.add`) über `bandit.reward`; Strafen für Schmeichelei und Abhängigkeit aus einfachen Detektoren auf der Antwort
  (Zustimmung am Satzanfang, Dauerversprechen, "nur ich verstehe dich" und ähnlich; dieselben Muster wie im Verhaltens-Check). Verstoß = -1.
- **Speicher:** Zähler und Mittelwerte je Stil als Profil-Eintrag im Vault (`style_bandit`), keine Gesprächstexte.
- **Anwendung:** **Nur Vorschlag** (Standard): Die UI zeigt "Du bewertest kürzere Antworten besser. Stil "kurz" verwenden?" mit Übernehmen/Ablehnen.
  Der gewählte Stil gilt, bis der Nutzer ihn ändert. Kein stilles Umschalten, keine Zufallsstile pro Antwort.
- **Schutz vor Belohnungs-Tricks:** Mindestens 20 Bewertungen je Stil, bevor ein Vorschlag erscheint; Vorschlag nie, wenn der Gewinner mehr Strafen
  als der Durchschnitt hat; Wechsel höchstens einmal pro Tag.

## Teil B: Reflexionsschleife und Nutzerprofil
- **Auslöser:** Auf Befehl (`kushim reflect` oder Knopf im Gedächtnis-Bereich). Nicht nachts im Hintergrund, weil das die Grafikkarte belegt, die Whisper
  und das Sprachmodell brauchen.
- **Eingabe:** nur bewertete Episoden und vorhandene Erinnerungen der letzten 30 Tage, nie Roh-Audio, nie Web-Inhalte, nie Notizen.
- **Ausgabe:** höchstens 5 **Profil-Vorschläge** ("Du magst kurze Antworten", "Du fragst oft nach dem Wetter in Bielefeld"), je mit Begründung ("aus 4
  bewerteten Antworten"). Die Vorschläge laufen durch den Prüfer aus `web/guard.py` (keine E-Mail, IBAN, Telefonnummer, Schlüssel, Pfade).
- **Sensible Bereiche** (Gesundheit, Finanzen, Religion, Politik, Sexualität, Dritte mit Namen): werden **nie vorgeschlagen** (Standard).
- **Übernehmen:** in der Gedächtnis-Ansicht je Vorschlag Übernehmen / Bearbeiten / Ablehnen; erst dann `add_fact(source="reflexion", ...)`. Abgelehnte
  Vorschläge werden nicht erneut vorgeschlagen (Hash merken).
- **Nutzen:** Die übernommenen Erinnerungen dürfen in den Systemprompt als kurzer Abschnitt "Was du über den Nutzer weißt" (höchstens 10 Zeilen, als
  Daten markiert, nie als Anweisung).

## Tests
- Reward-Unveränderlichkeit (Verstoß schlägt Lob), Arme ohne Rechte-Bezug, Stile nur nach bestandenem `behavior`.
- Vorschläge ohne PII und ohne sensible Bereiche (Beispiele als Testfälle), nichts ohne Klick gespeichert, abgelehnte nicht erneut.
- Threading: Vault nur über `SharedStore`.

## Entscheidungen des Nutzers (Standard bis zur Antwort in Klammern)
1. Stile nur als **Vorschlag** mit Übernehmen (Standard) oder dürfen sie sich nach genug Bewertungen automatisch ändern?
2. Welche Stile soll es geben? (kurz, ausführlich, direkt, freundlich)
3. Reflexion **nur auf Befehl** (Standard) oder zusätzlich automatisch zu einer festen Uhrzeit, wenn der Rechner im Leerlauf ist?
4. Sensible Bereiche vom Vorschlagen **ausschließen** (Standard) oder zulassen?
5. Wie lange sollen bewertete Episoden (Frage und Antwort) im Vault bleiben? (90 Tage, danach automatisch gelöscht; jederzeit manuell löschbar)
6. Darf das Nutzerprofil (übernommene Erinnerungen) in den Systemprompt? (ja, höchstens 10 Zeilen, als Daten markiert)
