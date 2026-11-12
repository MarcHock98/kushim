"""Zeichnet das kushim-Logo im Stil „Jarvin Cockpit“ (Mini-Orb wie der Avatar) und schreibt alle Logo-Dateien.

Eine Geometrie, zwei Ausgaben: assets/logo.svg (Vektor) und per Pillow assets/kushim.png, assets/kushim.ico,
ui/public/kushim.png (Kopfzeile) sowie eine 1024er PNG als Quelle für `npx tauri icon` (Pfad als Argument).
Form: tiefschwarzer Grund mit Haarlinie, Skalenring aus Strichen, 24 Strahlen und ein Kern mit Keil-K in Cyan.
Offline, nur Pillow. Aufruf: python scripts/make_icon.py [pfad/zur/quelle-1024.png] (aus dem venv)
"""
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
S = 1024                 # Zeichnung in 4-facher Auflösung (viewBox 256), danach verkleinern
K = S / 256
C = 128                  # Mittelpunkt

VOID, SURFACE, LINE, LINE_STRONG, ARC = "#04090d", "#0a141b", "#1f3a47", "#3a6a80", "#3ee0ff"
TICKS = 48               # Skalenring: Striche von r 99 bis 109
RAYS = 24                # Strahlen ab r 66, Länge 10 bis 22 (feste Form wie im Avatar)
RAY_LEN = [10 + 12 * (0.35 + 0.65 * abs(math.sin(i * 2.3) * math.cos(i * 0.7))) for i in range(RAYS)]
G = 28                   # halbe Höhe des K


def _polar(r: float, i: int, n: int) -> tuple[float, float]:
    a = i / n * 2 * math.pi - math.pi / 2
    return C + math.cos(a) * r, C + math.sin(a) * r


def segments():
    """(Linien als ((x1, y1), (x2, y2), Breite, Farbe, Deckkraft)) in viewBox-Einheiten."""
    for i in range(TICKS):
        yield _polar(99, i, TICKS), _polar(109, i, TICKS), 4, LINE_STRONG, 1.0
    for i in range(RAYS):
        yield _polar(66, i, RAYS), _polar(66 + RAY_LEN[i], i, RAYS), 5, ARC, 0.85


K_PATHS = [[(C - 0.6 * G, C - G), (C - 0.6 * G, C + G)],
           [(C + 0.8 * G, C - G), (C - 0.6 * G, C + 0.05 * G), (C + 0.8 * G, C + G)]]


def svg() -> str:
    f = lambda v: f"{v:.1f}".rstrip("0").rstrip(".")                          # noqa: E731
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" role="img" aria-label="kushim">',
        "  <title>kushim</title>",
        "  <!-- Mini-Orb im Stil „Jarvin Cockpit“: Skalenring, Strahlen, Kern mit Keil-K (Kushim: Verwalter auf Tontafeln).",
        "       Erzeugt von scripts/make_icon.py, nicht von Hand ändern. -->",
        f'  <rect x="8" y="8" width="240" height="240" rx="48" fill="{VOID}" stroke="{LINE}" stroke-width="3"/>',
        f'  <circle cx="{C}" cy="{C}" r="114" fill="none" stroke="{LINE}" stroke-width="2"/>',
        '  <g stroke-linecap="round">',
    ]
    for (x1, y1), (x2, y2), w, col, op in segments():
        o = "" if op == 1.0 else f' stroke-opacity="{op}"'
        lines.append(f'    <line x1="{f(x1)}" y1="{f(y1)}" x2="{f(x2)}" y2="{f(y2)}" stroke="{col}" stroke-width="{w}"{o}/>')
    lines += [
        "  </g>",
        f'  <circle cx="{C}" cy="{C}" r="54" fill="{SURFACE}" stroke="{ARC}" stroke-width="3"/>',
        f'  <path d="{" ".join("M" + " L".join(f"{f(x)},{f(y)}" for x, y in p) for p in K_PATHS)}" fill="none" stroke="{ARC}" '
        'stroke-width="11" stroke-linecap="round" stroke-linejoin="round"/>',
        "</svg>",
        "",
    ]
    return "\r\n".join(lines)


def _rgb(hex6: str, alpha: float = 1.0) -> tuple[int, int, int, int]:
    return int(hex6[1:3], 16), int(hex6[3:5], 16), int(hex6[5:7], 16), round(255 * alpha)


def _line(d: ImageDraw.ImageDraw, pts, width: float, col) -> None:
    pts = [(x * K, y * K) for x, y in pts]
    w = round(width * K)
    d.line(pts, fill=col, width=w, joint="curve")
    for x, y in pts:                                                          # runde Enden
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=col)


def render() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8 * K, 8 * K, 248 * K, 248 * K], 48 * K, fill=_rgb(VOID), outline=_rgb(LINE), width=round(3 * K))
    d.ellipse([(C - 114) * K, (C - 114) * K, (C + 114) * K, (C + 114) * K], outline=_rgb(LINE), width=round(2 * K))
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))                           # Deckkraft der Strahlen auf eigener Ebene
    ld = ImageDraw.Draw(layer)
    for a, b, w, col, op in segments():
        _line(ld, [a, b], w, _rgb(col, op))
    img.alpha_composite(layer)
    d = ImageDraw.Draw(img)
    d.ellipse([(C - 54) * K, (C - 54) * K, (C + 54) * K, (C + 54) * K], fill=_rgb(SURFACE), outline=_rgb(ARC), width=round(3 * K))
    for p in K_PATHS:
        _line(d, p, 11, _rgb(ARC))
    return img


if __name__ == "__main__":
    (ROOT / "assets" / "logo.svg").write_bytes(svg().encode("utf-8"))
    full = render()
    big = full.resize((256, 256), Image.LANCZOS)
    big.save(ROOT / "assets" / "kushim.png")
    big.save(ROOT / "assets" / "kushim.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save(ROOT / "ui" / "public" / "kushim.png")
    if len(sys.argv) > 1:
        full.save(sys.argv[1])
    print("geschrieben: assets/logo.svg, assets/kushim.png, assets/kushim.ico, ui/public/kushim.png")
