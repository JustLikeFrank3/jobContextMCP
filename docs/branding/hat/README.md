# Hat / merch logo assets

Hat-ready exports of the jobContext "jC" mark for print-on-demand uploads
(CustomInk, etc.). All PNGs are 2000×2000 with a transparent background.

| File | Use on |
| --- | --- |
| `jobcontextmcp-hat-light-hats.png` / `.svg` | Light hats (white, khaki, grey) — navy `j` `#0F172A` + cyan `C` `#00B5C8` |
| `jobcontextmcp-hat-dark-hats.png` / `.svg` | Dark hats (black, navy, charcoal) — white `j` `#FFFFFF` + cyan `C` `#00B5C8` |
| `jobcontextmcp-hat-badge.png` / `.svg` | Any hat — full circular badge (dark disc, cyan ring, jC, `00100100` binary), extracted from the banner/app-icon art |
| `jobcontextmcp-hat-badge-knockout.png` / `.svg` | Dark hats — same badge without the disc fill, so the hat fabric is the background (fewer stitches/colors) |

The badge SVGs set the binary in JetBrains Mono Bold; the checked-in PNGs
were rendered with that font installed, so prefer the PNGs for uploads
unless you have the font locally.

Notes for embroidery:

- Two thread colors per variant; the cyan is `#00B5C8` (closest standard
  thread: a teal/turquoise — let the vendor color-match).
- Strokes are thick and rounded, so the mark holds up at typical front-panel
  embroidery sizes (2–2.5 in wide).
- Regenerate PNGs from the SVGs with
  `cairosvg <name>.svg -o <name>.png --output-width 2000 --output-height 2000`.
