#!/usr/bin/env python3
"""Regenerate badge/jobcontext/icon.png — the jobContext mark at 24x24.

    python3 badge/make_icon.py        (needs Pillow; runs on the Mac, not the badge)

Drawn from the geometry of docs/branding/logo/jobcontextmcp-mark-dark.svg
(dark disc, cyan ring, cyan C, white j) at 16x and downsampled, because the
repo's PNG exports have no disc and the white j vanishes on a light ground.
Strokes are thickened from the SVG's: at 24px the original 10-unit ring and
32-unit C are under a pixel and smear on the badge's screen.
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

INK, CYAN, WHITE = (10, 15, 28, 255), (0, 181, 200, 255), (255, 255, 255, 255)
OUT = Path(__file__).resolve().parent / "jobcontext" / "icon.png"


def render(size=24, ring_w=22, c_w=44, j_w=42, dot_r=26, k=16):
    w = size * k
    f = w / 320.0
    im = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    def disc(cx, cy, r, fill):
        d.ellipse([(cx - r) * f, (cy - r) * f, (cx + r) * f, (cy + r) * f], fill=fill)

    def stroke(points, width, fill):
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            d.line([(x0 * f, y0 * f), (x1 * f, y1 * f)], fill=fill, width=max(1, int(width * f)))
        for x, y in points:
            disc(x, y, width / 2, fill)  # round caps and joins

    disc(160, 160, 153, INK)
    d.ellipse([7 * f, 7 * f, 313 * f, 313 * f], outline=CYAN, width=int(ring_w * f))
    ox = -12  # the SVG's translate(-12 0)
    # C: "M234 118 A56 56 0 1 0 234 202" — large arc, centre to the left.
    r = 56
    cx = 234 - math.sqrt(r * r - 42 * 42)
    a0 = math.atan2(118 - 160, 234 - cx)
    sweep = 2 * math.pi - 2 * abs(a0)
    arc = [(cx + ox + r * math.cos(a0 - sweep * i / 90), 160 + r * math.sin(a0 - sweep * i / 90))
           for i in range(91)]
    stroke(arc, c_w, CYAN)
    # j: dot, stem, and the quadratic hook "Q100 230 74 230".
    disc(100 + ox, 112, dot_r, WHITE)
    hook = [(100 + ox, 142), (100 + ox, 205)]
    for i in range(1, 21):
        t = i / 20
        x = (1 - t) ** 2 * 100 + 2 * (1 - t) * t * 100 + t * t * 74
        y = (1 - t) ** 2 * 205 + 2 * (1 - t) * t * 230 + t * t * 230
        hook.append((x + ox, y))
    stroke(hook, j_w, WHITE)
    return im.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    render().save(OUT)
    print("wrote", OUT)
