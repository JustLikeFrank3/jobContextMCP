"""Drawing + button shim for the GitHub Universe 2025 badge.

Everything hardware-specific is isolated in this one module on purpose: the
rest of the app talks to the small surface defined here.

Verified against the hardware with badge/probe.py (2026-10-02): the badge is
a "GitHub Badger with RP2350" running Pimoroni's badgeware firmware
(MicroPython 1.26).  What that means for this file:

  * There is no PicoGraphics.  ``badgeware.display`` is a bare ST7789 driver
    (update/backlight/command only); drawing goes through ``screen``, an
    Image you set a ``brush`` on and then ``draw(shapes.*)`` / ``text()``.
  * ``screen`` is 160x120 — the firmware doubles it onto the 320x240 panel.
    Every coordinate in this app is in that 160x120 space.
  * Fonts are proportional PixelFonts (.ppf) from /system/assets/fonts, so a
    fixed character width is meaningless: ``fit()`` measures in pixels.
  * The fonts are ASCII-only.  Anything else ("…", "✓", accented letters)
    renders as one fallback box, so ``_ascii()`` folds text before drawing.
  * Buttons are read from ``io.held`` (a set of BUTTON_* constants), which
    the firmware's ``run()`` loop refreshes every frame.
  * ``run()`` also pushes ``screen`` to the panel after every update(), so
    ``flip()`` does nothing; ``present()`` exists for frames drawn *outside*
    the loop (the splash and status screens shown before a blocking call).
"""

WIDTH = 160
HEIGHT = 120

# Colours as (r, g, b); converted to cached brushes on first use.
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
DIM = (140, 150, 165)
ACCENT = (60, 200, 210)
WARN = (240, 170, 60)
BAD = (235, 90, 90)
OK = (110, 210, 130)
PANEL = (18, 26, 40)
SELECT = (26, 40, 60)

# scale -> font.  1 is the small dense face for hints and secondary lines, 2
# is the badge menu's own face for primary text, 3 is a large display face.
_FONT_FILES = {
    1: "winds.ppf",
    2: "ark.ppf",
    3: "absolute.ppf",
}
_FONT_DIR = "/system/assets/fonts/"

HEADER_H = 14
FOOTER_H = 11

_fw = None  # the badgeware module, once init() has found it
_fonts = {}
_brushes = {}
_current_font = None


def init():
    global _fw
    try:
        import badgeware  # type: ignore
    except ImportError:
        return False
    _fw = badgeware
    for scale, name in _FONT_FILES.items():
        try:
            _fonts[scale] = badgeware.PixelFont.load(_FONT_DIR + name)
        except OSError:
            pass
    return True


def pressed(name):
    """True if button *name* is currently down. Unknown buttons read False so
    a firmware that lacks one degrades instead of crashing."""
    if _fw is None:
        return False
    const = getattr(_fw.io, "BUTTON_" + name, None)
    return const is not None and const in _fw.io.held


# ── text helpers ───────────────────────────────────────────────────────────────

_FOLD = {
    "…": "..", "—": "-", "–": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "✓": "ok", " ": " ",
    "à": "a", "á": "a", "â": "a", "ä": "a", "ã": "a", "å": "a",
    "ç": "c", "è": "e", "é": "e", "ê": "e", "ë": "e",
    "ì": "i", "í": "i", "î": "i", "ï": "i", "ñ": "n",
    "ò": "o", "ó": "o", "ô": "o", "ö": "o", "õ": "o", "ø": "o",
    "ù": "u", "ú": "u", "û": "u", "ü": "u", "ý": "y", "ß": "ss",
    "À": "A", "Á": "A", "Â": "A", "Ä": "A", "Å": "A", "Ç": "C",
    "È": "E", "É": "E", "Ê": "E", "Í": "I", "Ñ": "N",
    "Ó": "O", "Ö": "O", "Ø": "O", "Ú": "U", "Ü": "U",
}


def _ascii(value):
    """Fold *value* into what the ASCII-only pixel fonts can draw."""
    value = str(value)
    out = []
    for char in value:
        if " " <= char <= "~":
            out.append(char)
        else:
            out.append(_FOLD.get(char, "?"))
    return "".join(out)


def _use_font(scale):
    global _current_font
    font = _fonts.get(scale) or _fonts.get(2)
    if font is not None and font is not _current_font:
        _fw.screen.font = font
        _current_font = font


def text_width(value, scale=2):
    if _fw is None:
        return len(str(value)) * 5
    _use_font(scale)
    return int(_fw.screen.measure_text(_ascii(value))[0])


def line_height(scale=2):
    font = _fonts.get(scale)
    return font.height if font is not None else 11


def fit(value, width, scale=2):
    """Trim *value* to *width* pixels at *scale*, ending in '..' when cut.

    The server caps payload lengths, but the fonts are proportional, so only
    the badge can know what actually fits.
    """
    value = _ascii(value)
    if text_width(value, scale) <= width:
        return value
    while value and text_width(value + "..", scale) > width:
        value = value[:-1]
    return value.rstrip() + ".."


def wrap(value, width, scale=1, max_lines=4):
    """Greedy word wrap to *width* pixels; the last line is fit() if over."""
    words = _ascii(value).split()
    lines = []
    line = ""
    for i, word in enumerate(words):
        candidate = (line + " " + word) if line else word
        if text_width(candidate, scale) <= width:
            line = candidate
            continue
        if line:
            lines.append(line)
        if len(lines) == max_lines - 1:
            lines.append(fit(" ".join(words[i:]), width, scale))
            return lines
        line = fit(word, width, scale)
    if line:
        lines.append(line)
    return lines


def fit_tail(value, width, scale=2):
    """Like fit() but keeps the *end* — for the line being typed."""
    value = _ascii(value)
    while value and text_width(value, scale) > width:
        value = value[1:]
    return value


# ── drawing ────────────────────────────────────────────────────────────────────

def _brush(colour):
    brush = _brushes.get(colour)
    if brush is None:
        brush = _fw.brushes.color(*colour)
        _brushes[colour] = brush
    _fw.screen.brush = brush


def clear(colour=BLACK):
    if _fw is None:
        return
    _brush(colour)
    _fw.screen.clear()


def text(value, x, y, colour=WHITE, scale=2):
    if _fw is None:
        return
    _use_font(scale)
    _brush(colour)
    _fw.screen.text(_ascii(value), int(x), int(y))


def rect(x, y, w, h, colour):
    if _fw is None:
        return
    _brush(colour)
    _fw.screen.draw(_fw.shapes.rectangle(int(x), int(y), int(w), int(h)))


def hline(y, colour=DIM):
    rect(0, y, WIDTH, 1, colour)


def flip():
    """No-op: badgeware's run() pushes the frame after every update()."""


def present():
    """Push the current frame now — for screens drawn outside the frame loop."""
    if _fw is None:
        return
    _fw.display.update()


def qr_image(text, max_w, max_h):
    """Render *text* as a QR code into an offscreen Image, once.

    Returns (image, side_px) or None when the firmware has no qrcode module.
    Modules are as large as fit in max_w x max_h (at least 1px) with a
    2-module white quiet zone, drawn as horizontal runs so a dense code is a
    few hundred rectangles at render time and a single blit per frame after.
    """
    if _fw is None:
        return None
    try:
        import qrcode  # type: ignore
    except ImportError:
        return None
    code = qrcode.QRCode()
    code.set_text(text)
    n = code.get_size()[0]
    quiet = 2
    scale = max(1, min(max_w, max_h) // (n + 2 * quiet))
    side = (n + 2 * quiet) * scale
    image = _fw.Image(0, 0, side, side)
    image.brush = _fw.brushes.color(255, 255, 255)
    image.draw(_fw.shapes.rectangle(0, 0, side, side))
    image.brush = _fw.brushes.color(0, 0, 0)
    for y in range(n):
        x = 0
        while x < n:
            if not code.get_module(x, y):
                x += 1
                continue
            start = x
            while x < n and code.get_module(x, y):
                x += 1
            image.draw(_fw.shapes.rectangle(
                (start + quiet) * scale, (y + quiet) * scale, (x - start) * scale, scale))
    return image, side


def blit(image, x, y):
    if _fw is None:
        return
    _fw.screen.blit(image, int(x), int(y))


def header(title, subtitle=""):
    rect(0, 0, WIDTH, HEADER_H, PANEL)
    text(fit(title, WIDTH - 8, 2), 4, 1, ACCENT, 2)
    if subtitle:
        text(fit(subtitle, WIDTH - 8, 1), 4, HEADER_H + 1, DIM, 1)


def footer(hint):
    """One line of button legend along the bottom — the badge has no labels."""
    rect(0, HEIGHT - FOOTER_H, WIDTH, FOOTER_H, PANEL)
    text(fit(hint, WIDTH - 6, 1), 3, HEIGHT - FOOTER_H, DIM, 1)
