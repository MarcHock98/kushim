"""Prüft die Farbpaare aus tokens.css gegen WCAG (Text 4,5:1, UI-Elemente 3:1). Ohne Abhängigkeiten.

Aufruf: python .claude/skills/kushim-ui-design/scripts/contrast.py [pfad/zu/tokens.css]
Exit 1, wenn ein Paar durchfällt. Neue Paare unten in PAIRS ergänzen.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DEFAULT = Path(__file__).resolve().parent.parent / "assets" / "tokens.css"

# (Vordergrund, Hintergrund, Mindestwert, Zweck)
PAIRS = [
    ("--text", "--bg-1", 4.5, "Fließtext auf Seite"),
    ("--text", "--bg-2", 4.5, "Fließtext auf Karte"),
    ("--text", "--bg-3", 4.5, "Fließtext auf erhöhter Karte"),
    ("--text-muted", "--bg-1", 4.5, "Hilfstext auf Seite"),
    ("--text-muted", "--bg-2", 4.5, "Hilfstext auf Karte"),
    ("--text-faint", "--bg-1", 3.0, "nur große/dekorative Schrift"),
    ("--amber", "--bg-1", 4.5, "Amber-Text/Icon auf Seite"),
    ("--amber-ink", "--amber", 4.5, "Text auf Amber-Knopf"),
    ("--cyan", "--bg-1", 4.5, "Cyan-Text/Icon auf Seite"),
    ("--cyan-ink", "--cyan", 4.5, "Text auf Cyan-Knopf"),
    ("--ok", "--bg-2", 4.5, "OK-Text auf Karte"),
    ("--warn", "--bg-2", 4.5, "Warn-Text auf Karte"),
    ("--alarm", "--bg-1", 4.5, "Alarm-Text auf Seite"),
    ("--alarm", "--alarm-bg", 4.5, "Alarm-Text auf Alarm-Fläche"),
    ("--alarm-ink", "--alarm", 4.5, "Text auf Notaus-Knopf"),
    ("--line-strong", "--bg-1", 3.0, "Rahmen von Eingabefeldern"),
    ("--amber", "--bg-1", 3.0, "Fokusring"),
]


def parse(css: str) -> dict[str, str]:
    return {k: v.lower() for k, v in re.findall(r"(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;", css)}


def lum(hex6: str) -> float:
    rgb = [int(hex6[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a: str, b: str) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT
    tokens = parse(path.read_text(encoding="utf-8"))
    bad = 0
    for fg, bg, need, why in PAIRS:
        if fg not in tokens or bg not in tokens:
            print(f"FEHLT   {fg} / {bg}")
            bad += 1
            continue
        r = ratio(tokens[fg], tokens[bg])
        ok = r >= need
        bad += not ok
        print(f"{'ok    ' if ok else 'FALLS '}  {r:5.2f}:1 (min {need})  {fg} auf {bg}  - {why}")
    print("Alles bestanden." if not bad else f"{bad} Paar(e) durchgefallen.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
