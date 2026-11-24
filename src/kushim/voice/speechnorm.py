"""Deutsche Textnormalisierung für die Sprachausgabe (reine Funktion, nur Standardbibliothek).

Macht aus Zeichen, die eine Stimme falsch oder gar nicht liest, gesprochene Wörter: Uhrzeit („14:35 Uhr“ → „vierzehn Uhr
fünfunddreißig“), Datum, Zahlen, Prozent, Grad Celsius, Einheiten, Euro-Beträge und gängige Abkürzungen. Läuft im Speaker
direkt vor der Synthese, also NACH `safety.imitation.guard` (Channel/Brücke) und nach der Erkennung des Signalton-Zeichens
(`earcon.MARK`). Entfernt alle Steuer- und Formatzeichen (Unicode-Kategorie C), damit nichts davon die Stimme erreicht.

Herkunft: Die Regeln (Abkürzungen, Einheiten mit Einzahl/Mehrzahl/Genus, Ordinalzahlen nach Artikel, Datum, Uhrzeit, Euro,
Grad) folgen `german_text_rules.py` und `onnx-docker/tts_normalizer.py` aus dem Modell-Repo
„Kokoro-82M-ONNX-German-Martin“ (https://huggingface.co/Godelaune/Kokoro-82M-ONNX-German-Martin, Revision a1cba7fb…,
Lizenz Apache-2.0 laut Model Card; Lizenztext: docs/licenses/Apache-2.0.txt). Geändert gegenüber dem Original:
- Einheiten und Abkürzungen ohne IGNORECASE und nur mit festem Punkt („5 G-Netz“ wird nicht zu „Gramm“, „Z bald“ nicht zu
  „zum Beispiel“); eine Zahl am Satzende wird keine Ordinalzahl („Es sind 5.“ bleibt „fünf“);
- neu: Steuerzeichen, Prozent, Versionen, Zahlenbereiche, Tausenderpunkte, Dezimalzahlen, ISO-Datum, Monatsnamen statt
  „elften“, Zahlen in Wörtern bis in die Milliarden, typografische Anführungszeichen und Striche, Emoji;
- als eine Datei, ohne Modulzustand.
"""
from __future__ import annotations

import re
import unicodedata

__all__ = ["normalize", "number_to_words", "ordinal", "SPLIT_PROTECT", "MONTH_NAMES"]

_ONES = ("null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun", "zehn", "elf", "zwölf",
         "dreizehn", "vierzehn", "fünfzehn", "sechzehn", "siebzehn", "achtzehn", "neunzehn")
_TENS = {20: "zwanzig", 30: "dreißig", 40: "vierzig", 50: "fünfzig", 60: "sechzig", 70: "siebzig", 80: "achtzig", 90: "neunzig"}
MONTH_NAMES = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November",
               "Dezember")
_MONTHS_RE = "(?:" + "|".join(MONTH_NAMES) + ")"


def _under_thousand(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        ones, tens = n % 10, n - n % 10
        return _TENS[tens] if ones == 0 else ("ein" if ones == 1 else _ONES[ones]) + "und" + _TENS[tens]
    hundreds, rest = divmod(n, 100)
    head = ("ein" if hundreds == 1 else _ONES[hundreds]) + "hundert"
    return head if rest == 0 else head + _under_thousand(rest)


def _prefix(n: int) -> str:
    """Zahl als Vorsilbe („ein“ statt „eins“): einundzwanzigtausend, hunderteintausend."""
    w = number_to_words(n)
    return w[:-1] if w.endswith("eins") else w


def number_to_words(n: int) -> str:
    """Grundzahl in Worten (bis unter eine Billion; größere Zahlen Ziffer für Ziffer)."""
    if n < 0:
        return "minus " + number_to_words(-n)
    if n < 1000:
        return _under_thousand(n)
    if n < 1_000_000:
        th, rest = divmod(n, 1000)
        head = "eintausend" if th == 1 else _prefix(th) + "tausend"
        return head if rest == 0 else head + _under_thousand(rest)
    for size, one, many in ((1_000_000_000, "eine Milliarde", "Milliarden"), (1_000_000, "eine Million", "Millionen")):
        if size <= n < size * 1000:
            big, rest = divmod(n, size)
            lead = _prefix(big)
            head = one if big == 1 else (lead + "e" if lead.endswith("ein") else lead) + " " + many
            return head if rest == 0 else head + " " + number_to_words(rest)
    return " ".join(_ONES[int(d)] for d in str(n))


_ORD_SPECIAL = {1: "erster", 3: "dritter", 7: "siebter", 8: "achter"}


def ordinal(n: int, case: str = "nom") -> str:
    """Ordinalzahl: case "nom" (dritter), "weak" (dritte, nach der/die/das), "dat" (dritten, nach am/zum/den)."""
    if n in _ORD_SPECIAL:
        word = _ORD_SPECIAL[n]
    elif 0 < n < 20:
        word = number_to_words(n) + "ter"
    else:
        cardinal, rest = number_to_words(n), n % 100
        if 0 < rest < 20 and n > 100:          # hundertdritter, tausendzweiter
            word = cardinal[:-len(number_to_words(rest))] + ordinal(rest)
        else:
            word = cardinal + "ster"
    if case == "weak":
        return word[:-1]
    if case == "dat":
        return word[:-1] + "n"
    return word


# Artikel/Präpositionen vor einer Ordinalzahl oder einem Datum und der passende Fall
_DAT = {"am", "im", "zum", "vom", "dem", "den", "einen", "einem", "jeden", "jedem", "beim", "seit", "ab", "bis zum", "nach dem",
        "bis"}
_WEAK = {"der", "die", "das", "eine", "jede", "jeder"}
_PREFIX_RE = (r"(?:(?<![\wäöüß])(bis\s+zum|nach\s+dem|am|im|zum|vom|dem|den|der|die|das|eine|einen|einem|jede|jeden|jedem|"
              r"jeder|beim|seit|ab|bis)\s+)?")


def _case(prefix: str | None) -> str:
    p = " ".join((prefix or "").lower().split())
    return "dat" if p in _DAT else "weak" if p in _WEAK else "nom"


def _with_prefix(prefix: str | None, word: str) -> str:
    return f"{prefix} {word}" if prefix else word


# --- Tabellen -----------------------------------------------------------------------------------------------------------

# (Muster nach der Zahl, Einzahl, Mehrzahl, Genus) - längere zuerst; Groß-/Kleinschreibung zählt
UNITS = (
    (r"km/h", "Kilometer pro Stunde", "Kilometer pro Stunde", None),
    (r"kWh", "Kilowattstunde", "Kilowattstunden", "f"),
    (r"Wh", "Wattstunde", "Wattstunden", "f"),
    (r"mAh", "Milliamperestunde", "Milliamperestunden", "f"),
    (r"GHz", "Gigahertz", "Gigahertz", None),
    (r"MHz", "Megahertz", "Megahertz", None),
    (r"kHz", "Kilohertz", "Kilohertz", None),
    (r"Hz", "Hertz", "Hertz", None),
    (r"TB", "Terabyte", "Terabyte", None),
    (r"GB", "Gigabyte", "Gigabyte", None),
    (r"MB", "Megabyte", "Megabyte", None),
    (r"[kK]B", "Kilobyte", "Kilobyte", None),
    (r"Std\.", "Stunde", "Stunden", "f"),
    (r"Min\.", "Minute", "Minuten", "f"),
    (r"min", "Minute", "Minuten", "f"),
    (r"Sek\.", "Sekunde", "Sekunden", "f"),
    (r"ms", "Millisekunde", "Millisekunden", "f"),
    (r"Stck\.", "Stück", "Stück", "n"),
    (r"mA", "Milliampere", "Milliampere", None),
    (r"kW", "Kilowatt", "Kilowatt", None),
    (r"kg", "Kilogramm", "Kilogramm", None),
    (r"mg", "Milligramm", "Milligramm", None),
    (r"g", "Gramm", "Gramm", None),
    (r"km", "Kilometer", "Kilometer", None),
    (r"cm", "Zentimeter", "Zentimeter", None),
    (r"mm", "Millimeter", "Millimeter", None),
    (r"m²", "Quadratmeter", "Quadratmeter", None),
    (r"m³", "Kubikmeter", "Kubikmeter", None),
    (r"m", "Meter", "Meter", None),
    (r"ml", "Milliliter", "Milliliter", None),
    (r"ltr\.", "Liter", "Liter", None),
    (r"l", "Liter", "Liter", None),
    (r"h", "Stunde", "Stunden", "f"),
    (r"s", "Sekunde", "Sekunden", "f"),
    (r"W", "Watt", "Watt", None),
    (r"V", "Volt", "Volt", None),
    (r"A", "Ampere", "Ampere", None),
    (r"Tsd\.", "Tausend", "Tausend", None),
    (r"Mio\.", "Million", "Millionen", "f"),
    (r"Mrd\.", "Milliarde", "Milliarden", "f"),
    (r"(?:EUR|€)", "Euro", "Euro", None),
    (r"(?:USD|\$)", "Dollar", "Dollar", None),
)

# (Muster, Ersatz) - nur mit Punkt bzw. als ganzes Wort; Groß-/Kleinschreibung zählt (außer groß am Satzanfang)
ABBREVIATIONS = (
    (r"\b[zZ]\.\s?B\.", "zum Beispiel"),
    (r"\b[zZ]B\b", "zum Beispiel"),
    (r"\b[dD]\.\s?h\.", "das heißt"),
    (r"\b[uU]\.\s?a\.", "unter anderem"),
    (r"\b[zZ]\.\s?T\.", "zum Teil"),
    (r"\b[uU]\.\s?U\.", "unter Umständen"),
    (r"\b[oO]\.\s?Ä\.", "oder Ähnliches"),
    (r"\b[sS]\.\s?o\.", "siehe oben"),
    (r"\b[sS]\.\s?u\.", "siehe unten"),
    (r"\bv\.\s?Chr\.", "vor Christus"),
    (r"\bn\.\s?Chr\.", "nach Christus"),
    (r"\b[uU]sw\.", "und so weiter"),
    (r"\b[bB]zw\.", "beziehungsweise"),
    (r"\b[bB]zgl\.", "bezüglich"),
    (r"\b[cC]a\.", "zirka"),
    (r"\b[eE]tc\.", "et cetera"),
    (r"\b[gG]gf\.", "gegebenenfalls"),
    (r"\b[eE]vtl\.", "eventuell"),
    (r"\b[iI]nkl\.", "inklusive"),
    (r"\b[zZ]zgl\.", "zuzüglich"),
    (r"\b[vV]gl\.", "vergleiche"),
    (r"\b[bB]spw\.", "beispielsweise"),
    (r"\b[gG]gü\.", "gegenüber"),
    (r"\b[aA]llg\.", "allgemein"),
    (r"\bMwSt\.", "Mehrwertsteuer"),
    (r"\bLfd\.\s?Nr\.", "laufende Nummer"),
    (r"\bNr\.", "Nummer"),
    (r"\bDr\.", "Doktor"),
    (r"\bProf\.", "Professor"),
    (r"\bHr\.", "Herr"),
    (r"\bFr\.", "Frau"),
    (r"\bSt\.", "Sankt"),
    (r"\bStr\.", "Straße"),
    (r"\bTel\.", "Telefon"),
    (r"\bAbs\.", "Absatz"),
    (r"\bKap\.", "Kapitel"),
    (r"\bAbb\.", "Abbildung"),
    (r"\bJh\.", "Jahrhundert"),
    (r"\bS\.(?=\s?\d)", "Seite"),
    (r"\bHbf\b\.?", "Hauptbahnhof"),
    (r"\bGmbH\b", "G m b H"),
    (r"\bTsd\.", "Tausend"),
    (r"\bMio\.", "Millionen"),
    (r"\bMrd\.", "Milliarden"),
)

# Wörter (klein, ohne Punkt), nach deren Punkt die Satzteilung NICHT trennt (tts.split_sentences)
SPLIT_PROTECT = frozenset({
    "z", "b", "d", "h", "u", "a", "t", "o", "ä", "s", "v", "n", "chr", "usw", "bzw", "bzgl", "ca", "etc", "ggf", "evtl",
    "inkl", "zzgl", "vgl", "bspw", "ggü", "allg", "mwst", "lfd", "nr", "dr", "prof", "hr", "fr", "st", "str", "tel",
    "abs", "kap", "abb", "jh", "tsd", "mio", "mrd", "std", "min", "sek", "stck", "ltr", "hbf", "gem", "lt", "geb", "bd",
})

_QUOTES = {**dict.fromkeys(map(ord, "«»‹›„“”‚‘\""), None), ord("’"): "'"}
_DASH = "–—‒―"
_LABELS = {"kapitel", "nummer", "seite", "absatz", "gleis", "version", "punkt", "schritt", "teil", "folge", "staffel", "level",
           "stufe", "raum", "zimmer", "platz", "abschnitt", "zeile", "spalte", "tag", "woche", "runde", "minus", "plus", "mal"}
# Weibliche Endungen für „1 Datei“ → „eine Datei“ (Faustregel; sonst „ein“)
_FEMININE = re.compile(r"(?:e|ei|ung|heit|keit|schaft|ion|tät|ik|ur|enz|anz|in)$")
_WEEKDAYS = {"Mo": "Montag", "Di": "Dienstag", "Mi": "Mittwoch", "Do": "Donnerstag", "Fr": "Freitag", "Sa": "Samstag",
             "So": "Sonntag"}
_VERSION_WORDS = (r"Version|Versionen|Python|Node|Java|Kotlin|iOS|Android|macOS|Windows|Ubuntu|Debian|Firefox|Chrome|Release|"
                  r"Update|Build|Kernel|Claude Code|kushim|onnxruntime|CUDA|cuDNN")


# --- Teilschritte -------------------------------------------------------------------------------------------------------

def _strip_controls(text: str) -> str:
    """Steuer- und Formatzeichen (Unicode-Kategorie C) raus; Zeilenumbrüche und Tabs werden Leerzeichen."""
    text = unicodedata.normalize("NFC", text)
    out = []
    for ch in text:
        if unicodedata.category(ch)[0] == "C":
            if ch in "\t\n\r\x0b\x0c\x85  ":
                out.append(" ")
            continue
        out.append(ch)
    return "".join(out)


def _num(raw: str, one: str = "ein") -> str:
    """Zahl als Text, mit Dezimalkomma. Eine glatte 1 wird `one` („ein“, „eine“ oder „eins“)."""
    neg = raw.startswith(("-", "−"))
    raw = raw.lstrip("-−")
    if "," in raw:
        whole, frac = raw.split(",", 1)
        words = number_to_words(int(whole or "0")) + " komma " + " ".join(_ONES[int(d)] for d in frac if d.isdigit())
    else:
        n = int(raw)
        words = one if n == 1 else number_to_words(n)
    return ("minus " if neg else "") + words


def _is_one(raw: str) -> bool:
    return re.fullmatch(r"[-−]?0*1", raw) is not None


def _digits(raw: str) -> str:
    return " ".join(_ONES[int(d)] for d in raw if d.isdigit())


_NUM = r"[-−]?\d+(?:,\d+)?"
_BEFORE = r"(?<![\w.,:/])"           # Zahl beginnt nicht mitten in einem Wort, einer Version oder Uhrzeit
_AFTER_UNIT = r"(?![\wäöüßÄÖÜ²³])"


def _weekdays(t: str) -> str:
    """„Mo. bis Fr.“, „Mo.–Fr.“, „Sa./So.“ → „Montag bis Freitag“ (nur als Paar; ein einzelnes „Fr.“ bleibt „Frau“)."""
    days = "|".join(_WEEKDAYS)

    def pair(m: re.Match) -> str:
        sep = " und " if m.group(2).strip() in ("/", "und", "+") else " bis "
        return _WEEKDAYS[m.group(1)] + sep + _WEEKDAYS[m.group(3)]
    return re.sub(rf"\b({days})\.?(\s?(?:bis|und|[-–—/+])\s?)({days})\b\.?", pair, t)


def _phones(t: str) -> str:
    """Telefonnummern („+49 170 1234567“, „089/123456“, „0170-1234567“): „plus neunundvierzig“, dann Ziffer für Ziffer."""
    def phone(m: re.Match) -> str:
        head, rest = m.group(1), m.group(2)
        if sum(c.isdigit() for c in head + rest) < 6:
            return m.group(0)
        if head.startswith("+"):
            if rest[:1].isdigit():                    # „+491701234567“ ohne Trennung: alles einzeln
                return "plus " + _digits(head + rest)
            spoken = "plus " + number_to_words(int(head[1:]))
        else:
            spoken = _digits(head)
        groups = [g for g in re.split(r"[ /-]", rest) if g]
        return " ".join([spoken] + [_digits(g) for g in groups])
    return re.sub(r"(?<![\w.,+])(\+\d{1,3}|0\d{1,5})((?:[ /-]?\d{2,}){1,6})(?![\w.,]?\d)", phone, t)


def _spoken_version(raw: str) -> str:
    return " Punkt ".join(number_to_words(int(p)) for p in raw.split("."))


def _named_versions(t: str) -> str:
    """Versionen nach einem passenden Wort („Python 3.12“, „Version 1.0“, „v2.5“), VOR dem Datum: sonst wäre „3.12.“ ein Datum."""
    t = re.sub(rf"\b({_VERSION_WORDS})(\s+v?)(\d+(?:\.\d+)+)",
               lambda m: m.group(1) + m.group(2).replace("v", "") + _spoken_version(m.group(3)), t, flags=re.I)
    return re.sub(r"(?<![\w.])v(\d+(?:\.\d+)+)\b", lambda m: "Version " + _spoken_version(m.group(1)), t)


def _versions(t: str) -> str:
    """„2.1.321“ → „zwei Punkt eins Punkt dreihunderteinundzwanzig“ (nicht bei Tausenderpunkten wie „1.234.567“); nach dem Datum."""
    def version(m: re.Match) -> str:
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", m.group(1)):
            return m.group(1)
        return _spoken_version(m.group(1))
    return re.sub(r"(?<![\w.])(\d+(?:\.\d+){2,})(?![\w.]*\d)", version, t)


def _clock(h: int, mi: int) -> str:
    return ("ein" if h == 1 else number_to_words(h)) + " Uhr" + (f" {number_to_words(mi)}" if mi else "")


def _iso_dates(t: str) -> str:
    """„2026-11-24“ und Zeitstempel „2026-03-07T10:00“ (Sekunden und Zeitzone werden nicht vorgelesen)."""
    def iso(m: re.Match) -> str:
        prefix, y, mo, d = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            return m.group(0)
        out = _with_prefix(prefix, f"{ordinal(d, _case(prefix))} {MONTH_NAMES[mo - 1]} {number_to_words(y)}")
        if m.group(5) is not None:
            h, mi = int(m.group(5)), int(m.group(6))
            if h <= 24 and mi <= 59:
                out += ", " + _clock(h, mi)
        return out
    return re.sub(_PREFIX_RE + r"(?<![\w.-])(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?"
                  r"(?:Z|[+-]\d{2}:?\d{2})?)?(?![\w-])", iso, t, flags=re.I)


def _ranges(t: str) -> str:
    """„10–12“, „10-12“ → „10 bis 12“ (nur kurze Zahlen; vor den Minuszeichen und Einheiten)."""
    return re.sub(r"(?<![\w.,])(\d{1,4}(?:,\d+)?)\s?[-" + _DASH + r"]\s?(\d{1,4}(?:,\d+)?)(?![\w.]*\d)",
                  lambda m: f"{m.group(1)} bis {m.group(2)}", t)


def _dates(t: str) -> str:
    def numeric(m: re.Match) -> str:
        prefix, d, mo = m.group(1), int(m.group(2)), int(m.group(3))
        year = m.group(4) or m.group(5)
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            return m.group(0)
        out = _with_prefix(prefix, f"{ordinal(d, _case(prefix))} {MONTH_NAMES[mo - 1]}")
        if year:
            return out + f" {number_to_words(int(year))}"
        return out + ("." if not m.string[m.end():].strip() else "")      # Satzende-Punkt bleibt („der 24.11.“)
    t = re.sub(_PREFIX_RE + r"(?<![\w.])(\d{1,2})\.(\d{1,2})\.(?:(\d{2})(?![\d.])|\s?(\d{4}))?(?![\w.]*\d)", numeric, t,
               flags=re.I)

    def named(m: re.Match) -> str:
        prefix, d, month, y = m.group(1), int(m.group(2)), m.group(3), m.group(4)
        out = _with_prefix(prefix, f"{ordinal(d, _case(prefix))} {month}")
        return out + (f" {number_to_words(int(y))}" if y else "")
    return re.sub(_PREFIX_RE + r"(?<![\w.])(\d{1,2})\.\s?(" + _MONTHS_RE + r")(?:\s(\d{4}))?(?!\w)", named, t, flags=re.I)


def _times(t: str) -> str:
    def clock(m: re.Match) -> str:
        h, mi = int(m.group(1)), int(m.group(2))
        return m.group(0) if h > 24 or mi > 59 else _clock(h, mi)

    def duration(m: re.Match) -> str:
        parts = [(int(m.group(1)), "eine Stunde", "Stunden"), (int(m.group(2)), "eine Minute", "Minuten"),
                 (int(m.group(3)), "eine Sekunde", "Sekunden")]
        said = [one if n == 1 else f"{number_to_words(n)} {many}" for n, one, many in parts if n]
        return " ".join(said) if said else "null Sekunden"
    t = re.sub(r"(?<![\w.:,])(\d{1,2})[:.](\d{2})(?::\d{2})?\s?Uhr\b", clock, t)
    t = re.sub(r"(?<![\w.:,])(\d{1,3}):([0-5]\d):([0-5]\d)(?![\d:])", duration, t)       # Dauer „1:30:00“
    t = re.sub(r"(?<![\w.:,])(\d{1,2}):(\d{2})(?![\d:])", clock, t)
    t = re.sub(r"(?<![\w.,])1\s?Uhr\b", "ein Uhr", t)
    return re.sub(r"(?<![\w.,:])(\d{1,3}):(\d{1,3})(?![\d:])", r"\1 zu \2", t)      # Verhältnis, Spielstand „3:1“


_USD = r"(?:\$|USD|US-Dollar)"


def _dollars(t: str) -> str:
    """Dollar im englischen Format: „$1,299.99“, „$12,000“, „$ 3.50“, „1,299.99 USD“ (Komma = Tausender, Punkt = Cent)."""
    def amount(whole: str, cents: str | None) -> str:
        n = int(whole.replace(",", ""))
        c = int(cents) if cents else 0
        return ("ein" if n == 1 else number_to_words(n)) + " Dollar" + (f" {number_to_words(c)}" if c else "")
    t = re.sub(_USD + r"\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?(?![\d,.]?\d)",
               lambda m: amount(m.group(1), m.group(2)), t)
    return re.sub(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?\s?" + _USD + r"(?!\w)",
                  lambda m: amount(m.group(1), m.group(2)) if ("," in m.group(1) or m.group(2)) else m.group(0), t)


def _space_thousands(t: str) -> str:
    """Leerzeichen als Tausendertrenner: schmale (U+202F, U+2009) und geschützte (U+00A0) immer; ein normales Leerzeichen nur
    bei mindestens zwei Gruppen („1 234 567“) oder vor Dezimalkomma bzw. Währung („1 234,56 €“), sonst wären es zwei Zahlen."""
    t = re.sub(r"(?<![\d,.])(\d{1,3}(?:[   ]\d{3})+)(?!\d)", lambda m: re.sub(r"\D", "", m.group(1)), t)
    return re.sub(r"(?<![\d,.])(\d{1,3}(?: \d{3}){2,}|\d{1,3} \d{3}(?=,\d|\s?(?:€|EUR|Euro|\$|USD)))(?!\d)",
                  lambda m: m.group(1).replace(" ", ""), t)


def _thousands(t: str) -> str:
    """„1.234.567“ und „1.299,99“: Tausenderpunkte weg (ein Dezimalkomma danach ist erlaubt)."""
    return re.sub(r"(?<![\w.,])(\d{1,3}(?:\.\d{3})+)(?!\.?\d)", lambda m: m.group(1).replace(".", ""), t)


def _money(t: str) -> str:
    def euro(m: re.Match) -> str:
        whole, cents = m.group(1), m.group(2)
        c = int(cents.ljust(2, "0")[:2])
        return _num(whole) + " Euro" + (f" {number_to_words(c)}" if c else "")
    t = re.sub(_BEFORE + r"([-−]?\d+),-{1,2}\s?(?:EUR|€|Euro)(?!\w)", lambda m: _num(m.group(1)) + " Euro", t)      # „5,- €“
    t = re.sub(_BEFORE + r"([-−]?\d+),(\d{1,2})\s?(?:EUR|€|Euro)(?!\w)", euro, t)
    t = re.sub(r"€\s?(\d+),(\d{1,2})(?!\d)", euro, t)                                                           # „€ 1299,99“
    t = re.sub(r"€\s?(" + _NUM + r")(?![\d,])", lambda m: _num(m.group(1)) + " Euro", t)
    return re.sub(r"\$\s?(" + _NUM + r")(?![\d,])", lambda m: _num(m.group(1)) + " Dollar", t)


def _percent_degrees(t: str) -> str:
    t = re.sub(_BEFORE + "(" + _NUM + r")\s?%", lambda m: _num(m.group(1)) + " Prozent", t)
    t = re.sub(_BEFORE + "(" + _NUM + r")\s?°\s?C(?!\w)", lambda m: _num(m.group(1)) + " Grad Celsius", t)
    t = re.sub(_BEFORE + "(" + _NUM + r")\s?°\s?F(?!\w)", lambda m: _num(m.group(1)) + " Grad Fahrenheit", t)
    return re.sub(_BEFORE + "(" + _NUM + r")\s?°", lambda m: _num(m.group(1)) + " Grad", t)


def _units(t: str) -> str:
    for pattern, one, many, gender in UNITS:
        end = r"(?=[\s,;:!?)]|$)" if pattern.endswith(r"\.") else _AFTER_UNIT
        t = re.sub(_BEFORE + "(" + _NUM + r")\s?" + pattern + end,
                   lambda m, o=one, p=many, g=gender: (f"{_num(m.group(1), 'eine' if g == 'f' else 'ein')} "
                                                       f"{o if _is_one(m.group(1)) else p}"), t)
    return t


def _abbreviations(t: str) -> str:
    t = re.sub(r"\b([A-ZÄÖÜ][a-zäöüß]+)str\.", r"\1straße", t)              # „Hauptstr. 5“ → „Hauptstraße 5“
    for pattern, repl in ABBREVIATIONS:
        t = re.sub(pattern, repl, t)
    return t


def _numbers(t: str) -> str:
    # „am 3.“ am Satzende (nach dem Teilen von „am 3. Danach …“): Tag im Monat, also „am dritten.“
    t = re.sub(r"(?i)(?<![\wäöüß])(am|zum|vom|bis\s+zum)\s+(\d{1,2})\.\s*$",
               lambda m: f"{m.group(1)} {ordinal(int(m.group(2)), 'dat')}." if 1 <= int(m.group(2)) <= 31 else m.group(0), t)
    # Ordinalzahl „die 2. Schiene“, „am 3. Tag“: nur mitten im Satz (danach ein Wort)
    t = re.sub(_PREFIX_RE + r"(?<![\w.,])(\d{1,4})\.(?=\s+[\wäöüÄÖÜ])",
               lambda m: _with_prefix(m.group(1), ordinal(int(m.group(2)), _case(m.group(1)))), t, flags=re.I)
    # übrige Zahl mit Punkt („3.5“, „1.0“): Punkt sprechen
    t = re.sub(r"(?<![\w.,])(\d+)\.(\d+)(?![\w.]*\d)", lambda m: f"{m.group(1)} Punkt {m.group(2)}", t)

    def cardinal(m: re.Match) -> str:
        raw = m.group(0)
        digits = raw.lstrip("-−").split(",")[0]
        if len(digits) > 1 and digits.startswith("0") or len(digits) > 12:      # 007, Kennungen: Ziffer für Ziffer
            return _digits(raw)
        if _is_one(raw):
            before = re.search(r"([\wäöüÄÖÜß]+)\s*$", t[:m.start()])
            noun = re.match(r"\s+([A-ZÄÖÜ][\wäöüß]*)", t[m.end():])
            if noun and not (before and before.group(1).lower() in _LABELS):
                return "eine" if _FEMININE.search(noun.group(1)) else "ein"     # „eine Datei“, „ein Tag“ (Faustregel)
        return _num(raw, "eins")
    return re.sub(r"(?<![\w.,])(?:[-−](?=\d))?\d+(?:,\d+)?(?!\w)", cardinal, t)


def _symbols(t: str) -> str:
    """Übrige Bildzeichen (Emoji, Pfeile) liest die Stimme sonst auf Englisch oder gar nicht: raus; ein einzelnes ° wird Grad."""
    t = t.replace("°", " Grad ")
    return "".join(ch for ch in t if unicodedata.category(ch) not in ("So", "Sk"))


def normalize(text: str) -> str:
    """Text so umschreiben, dass die Stimme ihn richtig liest. Leerer Text bleibt leer.

    Achtung: Entfernt Zeichen (Anführungszeichen, Emoji, Symbole). Was danach wie eine Systemansage klingt, prüft der Speaker
    für Claudes Sätze noch einmal mit `safety.imitation` (die Normalisierung läuft NACH dem ersten Filter)."""
    if not text:
        return ""
    t = _strip_controls(text)
    t = t.translate(_QUOTES)
    t = _weekdays(t)
    t = _iso_dates(t)
    t = _phones(t)
    t = _dollars(t)
    t = _named_versions(t)
    t = _dates(t)
    t = _versions(t)
    t = _ranges(t)
    t = re.sub("[" + _DASH + "]", ",", t)                  # Gedankenstrich: kurze Pause (wie im Martin-Skript)
    t = t.replace("&", " und ").replace("…", "...")
    t = _times(t)
    t = _space_thousands(t)
    t = _thousands(t)
    t = _money(t)
    t = _percent_degrees(t)
    t = _units(t)
    t = _abbreviations(t)
    t = _numbers(t)
    t = _symbols(t)
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    t = re.sub(r",(\s*,)+", ",", t)
    t = re.sub(r"^[\s,]+", "", t)
    return " ".join(t.split())
