"""Zeichnet das kushima-Logo (Geometrie wie assets/logo.svg) und schreibt assets/kushima.ico + PNG.

Offline, nur Pillow. Aufruf: python scripts/make_icon.py (aus dem venv)
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
S = 1024                 # Zeichnung in 4-facher Auflösung (viewBox 256), danach verkleinern
K = S / 256

KEILE = [
    [(84, 52), (112, 52), (104, 118), (92, 118)],
    [(92, 118), (104, 118), (112, 204), (84, 204)],
    [(150, 58), (178, 66), (124, 124), (112, 112)],
    [(124, 132), (136, 120), (188, 196), (160, 204)],
]
MARKEN = [((196, 86), 255), ((214, 104), 178), ((196, 122), 115)]


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def gradient(c1, c2):
    g = Image.new("RGB", (S, S))
    px = g.load()
    for y in range(S):
        for x in range(S):
            px[x, y] = lerp(c1, c2, (x + y) / (2 * S))
    return g


def render() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([8 * K, 8 * K, 248 * K, 248 * K], 56 * K, fill=255)
    img.paste(gradient((27, 36, 51), (13, 17, 24)), (0, 0), mask)
    ImageDraw.Draw(img).rounded_rectangle([8 * K, 8 * K, 248 * K, 248 * K], 56 * K,
                                          outline=(44, 58, 82), width=round(3 * K))
    glow = gradient((255, 211, 122), (224, 138, 60))
    gm = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(gm)
    for poly in KEILE:
        d.polygon([(x * K, y * K) for x, y in poly], fill=255)
    img.paste(glow, (0, 0), gm)
    d = ImageDraw.Draw(img)
    for (cx, cy), a in MARKEN:
        r = 7 * K
        d.ellipse([cx * K - r, cy * K - r, cx * K + r, cy * K + r], fill=(111, 183, 255, a))
    return img


if __name__ == "__main__":
    big = render().resize((256, 256), Image.LANCZOS)
    out = ROOT / "assets"
    big.save(out / "kushima.png")
    big.save(out / "kushima.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("geschrieben:", out / "kushima.ico")
