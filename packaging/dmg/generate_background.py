"""Generate the macOS dmg installer background (desktop/src-tauri/dmg-background.tiff).

Run when the branding changes; the multi-resolution TIFF is committed so CI
doesn't need PIL:

    .venv/bin/python packaging/dmg/generate_background.py

The layout must stay in sync with desktop/src-tauri/dmg-settings.py:
window 660x400, icons at (165, 200) and (495, 200), icon size 128.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Brand palette (matches the dashboard SPA).
BG = (11, 17, 23)          # near-black navy
FG = (230, 237, 243)       # off-white
ACCENT = (0, 181, 200)     # jobContext teal
MUTED = (139, 148, 158)    # gray captions

W, H = 660, 400            # must match window_rect in dmg-settings.py
SCALE = 2                  # draw @2x, emit 1x + 2x in one TIFF


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    # Helvetica ships with macOS; index 1 is the bold face.
    return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size, index=1 if bold else 0)


def draw(scale: int) -> Image.Image:
    img = Image.new("RGB", (W * scale, H * scale), BG)
    d = ImageDraw.Draw(img)

    # Wordmark: "job" white + "Context" teal, centered near the top.
    f_brand = _font(30 * scale, bold=True)
    job_w = d.textlength("job", font=f_brand)
    ctx_w = d.textlength("Context", font=f_brand)
    x = (W * scale - (job_w + ctx_w)) / 2
    y = 42 * scale
    d.text((x, y), "job", font=f_brand, fill=FG)
    d.text((x + job_w, y), "Context", font=f_brand, fill=ACCENT)

    # Arrow between the two icon slots (icons sit at x=165 and x=495,
    # size 128 → edges at ~229 and ~431; arrow spans the gap at icon height).
    ay = 200 * scale
    x0, x1 = 258 * scale, 400 * scale
    lw = 5 * scale
    d.line([(x0, ay), (x1 - 14 * scale, ay)], fill=ACCENT, width=lw)
    d.polygon(
        [(x1, ay), (x1 - 22 * scale, ay - 13 * scale), (x1 - 22 * scale, ay + 13 * scale)],
        fill=ACCENT,
    )

    # Install hint under the icons (labels render at ~y=275).
    f_hint = _font(15 * scale)
    hint = "Drag jobContext to Applications to install"
    d.text(((W * scale - d.textlength(hint, font=f_hint)) / 2, 330 * scale), hint, font=f_hint, fill=MUTED)

    # Thin accent rule at the very bottom, echoing the dashboard header.
    d.rectangle([(0, (H - 3) * scale), (W * scale, H * scale)], fill=(0, 90, 100))
    return img


def main() -> None:
    out = Path(__file__).resolve().parents[2] / "desktop" / "src-tauri" / "dmg-background.tiff"
    with tempfile.TemporaryDirectory() as td:
        one = Path(td) / "bg.png"
        two = Path(td) / "bg@2x.png"
        draw(SCALE).resize((W, H), Image.LANCZOS).save(one)
        draw(SCALE).save(two)
        # Combine 1x + 2x into a single HiDPI-aware TIFF for Finder.
        subprocess.run(
            ["tiffutil", "-cathidpicheck", str(one), str(two), "-out", str(out)],
            check=True,
        )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
