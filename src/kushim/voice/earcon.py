"""Signalton vor kushims eigenen Systemansagen (Freigabe-Anfragen, Notaus), Safety-Audit 2026-11-23.

Claude spricht mit kushims Stimme und in der ersten Person. Damit eine Ansage wie „Ich möchte den Befehl … ausführen. Bitte im
Terminal bestätigen.“ oder „Der Notaus ist aktiv …“ von kushim selbst erkennbar bleibt, kommt davor ein kurzer Zweiklang.
Er wird hier aus Sinuswellen erzeugt (keine Datei, kein Download) und über die normale Ausgabe gespielt.

Kennzeichen ist das Steuerzeichen MARK am Anfang eines Satzes. Texte von Claude (`sprich`) können es nie enthalten: Channel
und Brücke entfernen alle nicht druckbaren Zeichen (`clean_text`). Nur fester Text in kushims eigenem Code setzt es (`mark`).
"""
from __future__ import annotations

import io
import math
import struct
import wave

MARK = "\x07"                   # BEL: nicht druckbar, wird aus jedem fremden Text entfernt
# Folgesätze einer markierten Ansage („… ausführen. Bitte im Terminal bestätigen.“): ebenfalls kushims eigener Text, aber
# ohne zweiten Signalton. Jeden eigenen Satz setzt `mark` einzeln in MARK bzw. OWN ... END; nichts wird beim Teilen
# abgeleitet. So kann ein angehängter Text von Claude nie als „eigener Satz“ gelten, auch nicht, wenn jemand Stücke
# aneinanderhängt. Alle drei Zeichen sind nicht druckbar, also aus Claudes Text immer entfernt. Der Speaker prüft nur Sätze
# OHNE MARK/OWN nach der Normalisierung noch einmal auf nachgeahmte Systemansagen.
OWN = "\x0e"                    # SO: nicht druckbar, Anfang eines eigenen Folgesatzes
END = "\x0f"                    # SI: nicht druckbar, Ende eines eigenen Satzes
MARKS = MARK + OWN + END
RATE = 22050
TONES = ((660.0, 0.12), (990.0, 0.18))      # zwei Töne aufwärts, zusammen 0,3 s
# Hinweiston, wenn die Stimme ausfällt (Text statt Sprache): zwei tiefe Töne abwärts, klar anders als der Zweiklang oben
HINT_TONES = ((523.0, 0.14), (0.0, 0.06), (392.0, 0.22))
VOLUME = 0.25


def mark(text: str) -> str:
    """Fester kushim-Text mit Signalton davor: jeder Satz einzeln gekennzeichnet (erster MARK, weitere OWN, jeder mit END).
    Nur für Text aus kushims Code (bzw. dafür entschärfte Teile, siehe `channel.speakable.announce`)."""
    from .tts import split_sentences
    parts = [plain(p) for p in split_sentences(plain(text))] or [plain(text)]
    return " ".join((MARK if i == 0 else OWN) + p + END for i, p in enumerate(parts) if p)


def plain(text: str) -> str:
    """Text ohne Kennzeichen (für Anzeige, Verlauf und Protokoll)."""
    return text.translate({ord(c): None for c in MARKS})


def chime_wav(rate: int = RATE) -> bytes:
    """Zweiklang als 16-bit-Mono-WAV (mit kurzem Ein- und Ausblenden, damit es nicht knackt)."""
    return _tones_wav(TONES, rate)


def hint_wav(rate: int = RATE) -> bytes:
    """Hinweiston: Die Stimme ist gerade nicht verfügbar, die Antwort steht als Text da (nie still bleiben)."""
    return _tones_wav(HINT_TONES, rate)


def _tones_wav(tones, rate: int) -> bytes:
    samples: list[int] = []
    for freq, seconds in tones:
        n = int(rate * seconds)
        fade = max(1, int(rate * 0.01))
        for i in range(n):
            env = min(1.0, i / fade, (n - 1 - i) / fade)
            samples.append(int(32767 * VOLUME * env * math.sin(2 * math.pi * freq * i / rate)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return buf.getvalue()
