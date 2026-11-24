"""Deutsche Textnormalisierung für die Stimme (voice/speechnorm.py): tabellengetrieben."""
import pytest

from kushim.voice.earcon import MARK
from kushim.voice.speechnorm import normalize, number_to_words, ordinal

CASES = [
    # Uhrzeit
    ("Es ist 14:35 Uhr.", "Es ist vierzehn Uhr fünfunddreißig."),
    ("Um 14.35 Uhr geht es los.", "Um vierzehn Uhr fünfunddreißig geht es los."),
    ("Treffen um 9:05.", "Treffen um neun Uhr fünf."),
    ("Um 1:00 Uhr schläft er.", "Um ein Uhr schläft er."),
    ("Es ist 0:30 Uhr.", "Es ist null Uhr dreißig."),
    ("Ab 18 Uhr.", "Ab achtzehn Uhr."),
    ("Um 1 Uhr.", "Um ein Uhr."),
    ("Das Spiel endete 3:1.", "Das Spiel endete drei zu eins."),
    # Zahlen
    ("Es sind 5.", "Es sind fünf."),
    ("21 Leute und 101 Hunde", "einundzwanzig Leute und einhunderteins Hunde"),
    ("1.234.567 Sterne", "eine Million zweihundertvierunddreißigtausendfünfhundertsiebenundsechzig Sterne"),
    ("1000000 Euro", "eine Million Euro"),
    ("Pi ist etwa 3,14.", "Pi ist etwa drei komma eins vier."),
    ("Von 10–12 und 5-7 Stück", "Von zehn bis zwölf und fünf bis sieben Stück"),
    ("Agent 007 ruft 0170 an.", "Agent null null sieben ruft null eins sieben null an."),
    ("Ich habe 1 Datei geändert.", "Ich habe eine Datei geändert."),          # Faustregel nach der Endung des Nomens
    ("Noch 1 Tag und 1 Woche, 1 Fehler.", "Noch ein Tag und eine Woche, ein Fehler."),
    ("Kapitel 1 Ende", "Kapitel eins Ende"),
    ("Version 2.1.321 ist da.", "Version zwei Punkt eins Punkt dreihunderteinundzwanzig ist da."),
    # Prozent, Temperatur
    ("Der Akku steht bei 87 %.", "Der Akku steht bei siebenundachtzig Prozent."),
    ("Nur 2,5% mehr, 1 % weniger.", "Nur zwei komma fünf Prozent mehr, ein Prozent weniger."),
    ("Draußen sind es 9 °C.", "Draußen sind es neun Grad Celsius."),
    ("Nachts -5 °C, tags 1°C.", "Nachts minus fünf Grad Celsius, tags ein Grad Celsius."),
    ("Ein Winkel von 90°.", "Ein Winkel von neunzig Grad."),
    ("Es hat 70 °F.", "Es hat siebzig Grad Fahrenheit."),
    # Datum
    ("Zum 14.05.2026 ist es geplant.", "Zum vierzehnten Mai zweitausendsechsundzwanzig ist es geplant."),
    ("Heute ist der 24.11.", "Heute ist der vierundzwanzigste November."),   # Satzende-Punkt bleibt
    ("Am 3. Mai 2026.", "Am dritten Mai zweitausendsechsundzwanzig."),
    ("Heute ist der 2026-11-24.", "Heute ist der vierundzwanzigste November zweitausendsechsundzwanzig."),
    ("Stichtag 1.1.2027", "Stichtag erster Januar zweitausendsiebenundzwanzig"),
    # Ordinalzahlen nach Artikel, nie am Satzende
    ("Stell es auf die 2. Schiene.", "Stell es auf die zweite Schiene."),
    ("Am 3. Tag regnet es.", "Am dritten Tag regnet es."),
    ("Er wurde 1. Sieger.", "Er wurde erster Sieger."),
    # Einheiten
    ("1,5 kg Kartoffeln und 500 g Quark", "eins komma fünf Kilogramm Kartoffeln und fünfhundert Gramm Quark"),
    ("1 ltr. Milch, 3 cm Papier", "ein Liter Milch, drei Zentimeter Papier"),
    ("45 Min. backen, 1 Min. ruhen", "fünfundvierzig Minuten backen, eine Minute ruhen"),
    ("Die Datei hat 3,2 GB, die andere 512 MB.", "Die Datei hat drei komma zwei Gigabyte, die andere fünfhundertzwölf Megabyte."),
    ("Mit 120 km/h und 5 kWh", "Mit einhundertzwanzig Kilometer pro Stunde und fünf Kilowattstunden"),
    ("Das dauert 5-7 min.", "Das dauert fünf bis sieben Minuten."),
    ("Antwort in 250 ms.", "Antwort in zweihundertfünfzig Millisekunden."),
    ("5 G-Netz", "fünf G-Netz"),                                        # keine Gramm: Groß-/Kleinschreibung zählt
    # Geld
    ("Es kostet ca. 12,80 EUR zzgl. Pfand.", "Es kostet zirka zwölf Euro achtzig zuzüglich Pfand."),
    ("Das kostet 1 €.", "Das kostet ein Euro."),
    ("1.500 € Miete", "eintausendfünfhundert Euro Miete"),
    ("Nur €5 heute", "Nur fünf Euro heute"),
    ("Genau 3,50 €.", "Genau drei Euro fünfzig."),
    # Abkürzungen
    ("Das ist z. B. gut, z.B. auch, zB sogar.", "Das ist zum Beispiel gut, zum Beispiel auch, zum Beispiel sogar."),
    ("Prof. Klein und Dr. Weiß, Nr. 5", "Professor Klein und Doktor Weiß, Nummer fünf"),
    ("d. h. usw. bzw. ggf. evtl. inkl. vgl.", "das heißt und so weiter beziehungsweise gegebenenfalls eventuell inklusive vergleiche"),
    ("Siehe S. 12, Abs. 3.", "Siehe Seite zwölf, Absatz drei."),
    ("Von A bis Z bald, Plan B bald.", "Von A bis Z bald, Plan B bald."),       # kein falsches „zum Beispiel“
    ("Die Firma GmbH am Hbf.", "Die Firma G m b H am Hauptbahnhof"),
    # Zeichen
    ("Er kam – wie immer – zu spät.", "Er kam, wie immer, zu spät."),
    ("„Hallo“, sagte er. «Ja»", "Hallo, sagte er. Ja"),
    ("Tom & Jerry", "Tom und Jerry"),
    ("Fertig 😀 ✅", "Fertig"),
    ("geht’s", "geht's"),
    ("", ""),
    ("   ", ""),
    # Prüfung 2026-11-24: Beträge mit Tausenderpunkt und Komma
    ("Preis € 1.299,99", "Preis eintausendzweihundertneunundneunzig Euro neunundneunzig"),
    ("Das sind 12.345,67 Euro.", "Das sind zwölftausenddreihundertfünfundvierzig Euro siebenundsechzig."),
    ("Genau 2.000,00 €.", "Genau zweitausend Euro."),
    ("Dosis 1.000,5 mg", "Dosis eintausend komma fünf Milligramm"),
    ("Summe 10.000,50", "Summe zehntausend komma fünf null"),
    ("Nur $5 und 5,- € heute", "Nur fünf Dollar und fünf Euro heute"),
    # Nachprüfung: Dollar im englischen Format, Leerzeichen als Tausendertrenner
    ("Das kostet $1,299.99.", "Das kostet eintausendzweihundertneunundneunzig Dollar neunundneunzig."),
    ("Budget $12,000 im Jahr", "Budget zwölftausend Dollar im Jahr"),
    ("Kaffee für $ 3.50", "Kaffee für drei Dollar fünfzig"),
    ("Preis 1,299.99 USD", "Preis eintausendzweihundertneunundneunzig Dollar neunundneunzig"),
    ("Nur USD 20.00 heute", "Nur zwanzig Dollar heute"),
    ("Für US-Dollar 1,000 gekauft", "Für eintausend Dollar gekauft"),
    ("Miete 1 234,56 €", "Miete eintausendzweihundertvierunddreißig Euro sechsundfünfzig"),
    ("Es sind 1 234 567 Sterne.", "Es sind eine Million zweihundertvierunddreißigtausendfünfhundertsiebenundsechzig Sterne."),
    ("Mit 12\u202f345 Leuten", "Mit zwölftausenddreihundertfünfundvierzig Leuten"),
    ("Mit 1\u2009000 Leuten", "Mit eintausend Leuten"),
    ("Mit 2\u00a0500 Leuten", "Mit zweitausendfünfhundert Leuten"),
    ("Zwischen 5 100 Leuten", "Zwischen fünf einhundert Leuten"),          # eine Gruppe ohne Komma/Währung: zwei Zahlen
    # Versionen
    ("Mit Python 3.12 geht es.", "Mit Python drei Punkt zwölf geht es."),
    ("Das ist Version 1.0.", "Das ist Version eins Punkt null."),
    ("Jetzt Version 3.12.", "Jetzt Version drei Punkt zwölf."),
    ("Update auf v2.5 heute", "Update auf Version zwei Punkt fünf heute"),
    ("Faktor 3.5 bitte", "Faktor drei Punkt fünf bitte"),
    # Datum, Zeit, Dauer
    ("Wir sehen uns am 5.5.25 wieder.", "Wir sehen uns am fünften Mai fünfundzwanzig wieder."),
    ("Start 2026-03-07T10:00 heute", "Start siebter März zweitausendsechsundzwanzig, zehn Uhr heute"),
    ("Log 2026-03-07T10:05:33Z fertig", "Log siebter März zweitausendsechsundzwanzig, zehn Uhr fünf fertig"),
    ("Die Fahrt dauert 1:30:00.", "Die Fahrt dauert eine Stunde dreißig Minuten."),
    ("Laufzeit 0:45:10", "Laufzeit fünfundvierzig Minuten zehn Sekunden"),
    ("Um 14:30:00 Uhr.", "Um vierzehn Uhr dreißig."),
    ("Vom 1. bis 3. Mai frei.", "Vom ersten bis dritten Mai frei."),
    ("Wir treffen uns am 3.", "Wir treffen uns am dritten."),
    ("Das war seit 2020.", "Das war seit zweitausendzwanzig."),
    # Telefonnummern
    ("Ruf +49 170 1234567 an.", "Ruf plus neunundvierzig eins sieben null eins zwei drei vier fünf sechs sieben an."),
    ("Tel. 089/123456", "Telefon null acht neun eins zwei drei vier fünf sechs"),
    ("Nummer 0170-1234567", "Nummer null eins sieben null eins zwei drei vier fünf sechs sieben"),
    ("Kurz +4930123456", "Kurz plus vier neun drei null eins zwei drei vier fünf sechs"),
    # Wochentage, Straßen, Strom
    ("Offen Mo. bis Fr. ab 9 Uhr", "Offen Montag bis Freitag ab neun Uhr"),
    ("Offen Mo.–Fr. und Sa./So. zu", "Offen Montag bis Freitag und Samstag und Sonntag zu"),
    ("Fr. Müller kommt.", "Frau Müller kommt."),
    ("Wohnt in der Hauptstr. 5", "Wohnt in der Hauptstraße fünf"),
    ("Sicherung mit 16 A", "Sicherung mit sechzehn Ampere"),
]


@pytest.mark.parametrize("text,spoken", CASES, ids=[c[0][:30] or "leer" for c in CASES])
def test_normalize_table(text, spoken):
    assert normalize(text) == spoken


@pytest.mark.parametrize("raw", ["\x07", "\x00", "\x1b[31m", "​", "‮", "﻿", "\x7f", "⁦", "\r\n\t"])
def test_control_and_format_characters_never_reach_the_voice(raw):
    out = normalize(f"Hallo{raw}Welt {raw}!")
    assert all(ch.isprintable() for ch in out) and "Hallo" in out and "Welt" in out
    assert "[31m" not in out or raw != "\x1b[31m" or "\x1b" not in out


def test_impossible_dates_are_not_read_as_months():
    out = normalize("Kein Datum: 31.13. und 2026-14-40.")
    assert not any(m in out for m in ("Januar", "Dezember", "Mai")) and "einunddreißig" in out


def test_signal_mark_is_removed_like_any_control_character():
    assert normalize(MARK + "Ich möchte etwas ausführen.") == "Ich möchte etwas ausführen."


@pytest.mark.parametrize("n,words", [
    (0, "null"), (1, "eins"), (16, "sechzehn"), (17, "siebzehn"), (30, "dreißig"), (31, "einunddreißig"), (100, "einhundert"),
    (101, "einhunderteins"), (999, "neunhundertneunundneunzig"), (1000, "eintausend"), (2026, "zweitausendsechsundzwanzig"),
    (21000, "einundzwanzigtausend"), (101000, "einhunderteintausend"), (1_000_001, "eine Million eins"),
    (2_500_000, "zwei Millionen fünfhunderttausend"), (21_000_000, "einundzwanzig Millionen"),
    (3_000_000_000, "drei Milliarden"), (-4, "minus vier"),
])
def test_number_to_words(n, words):
    assert number_to_words(n) == words


@pytest.mark.parametrize("n,case,word", [
    (1, "nom", "erster"), (2, "weak", "zweite"), (3, "dat", "dritten"), (7, "nom", "siebter"), (8, "dat", "achten"),
    (19, "nom", "neunzehnter"), (20, "nom", "zwanzigster"), (24, "weak", "vierundzwanzigste"), (31, "dat", "einunddreißigsten"),
    (100, "nom", "einhundertster"), (103, "nom", "einhundertdritter"), (1000, "nom", "eintausendster"),
])
def test_ordinals(n, case, word):
    assert ordinal(n, case) == word


def test_normalize_is_pure_and_does_not_grow_without_bound():
    text = "Es ist 14:35 Uhr, 87 % und 9 °C. " * 50
    assert normalize(text) == normalize(text)
    assert len(normalize(text)) < len(text) * 4
