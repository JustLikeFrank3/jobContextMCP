"""Drawing + input shim for the GitHub Universe 2026 badge.

Everything that touches the firmware is isolated in this one module. The 2026
runtime supplies its API as builtins — `badge`, `screen`, `color`, `shape`,
`rect`, `image`, `font` and the `BUTTON_*` constants — so nothing here is
imported; the names simply exist on the device (and are faked in the tests).

Screen: 320x240, requested with `badge.mode(HIRES | VSYNC)`; the runtime's
default is a 160x120 logical surface, which is too small for a results list.

Controls: eight capacitive pads — a d-pad plus SELECT, BACK, MENU and HOME.
The app uses logical action names ("UP", "SELECT", ...) and never physical
positions: the firmware remaps the pads when the badge hangs upside down.
HOME is reserved by the firmware for returning to the launcher.

Text is laid out with the firmware's own measurement: `text(..., width=)`
draws into a rect with `overflow=image.ELLIPSES`, so wrapping and truncation
are the firmware's rather than estimated from a guessed character width. The
rect must be at least one full line tall — any shorter and no line "fits",
so nothing gets an ellipsis and the glyphs are simply cut off at the bottom.
Line heights are measured from the font at startup for that reason.
"""

WIDTH = 320
HEIGHT = 240

# Colours as (r, g, b); converted to firmware colours on first use.
BLACK = (13, 17, 23)
WHITE = (240, 246, 252)
DIM = (139, 148, 158)
ACCENT = (88, 166, 255)
WARN = (240, 170, 60)
BAD = (248, 81, 73)
OK = (63, 185, 80)
PANEL = (22, 27, 34)
HIGHLIGHT = (31, 58, 95)

# Pixel ROM fonts: always present, crisp at integer scale. `nope` is the
# "clear, readable" face; measured in the Badgeware simulator its line box is
# 13px at size 1, 26px at size 2 and ~8px per character at size 1.
FONT_NAME = "nope"
_FALLBACK_LINE_H = 13

_buttons = {}
_colours = {}
_line_h = {}
_font = None


def init():
    """Switch to full resolution and resolve button constants.

    Returns False when the firmware globals are missing, which only happens
    off-device.
    """
    global _font
    try:
        badge.mode(HIRES | VSYNC)
        _font = getattr(font, FONT_NAME)
        _buttons.update({
            "UP": BUTTON_UP,
            "DOWN": BUTTON_DOWN,
            "LEFT": BUTTON_LEFT,
            "RIGHT": BUTTON_RIGHT,
            "SELECT": BUTTON_SELECT,
            "BACK": BUTTON_BACK,
            "MENU": BUTTON_MENU,
        })
    except NameError:
        return False
    return True


# ── input ──────────────────────────────────────────────────────────────────────

def pressed(action):
    """True on the frame *action* went down. The firmware does the edge
    detection, so a held pad reports once, not every frame."""
    button = _buttons.get(action)
    return button is not None and bool(badge.pressed(button))


def held(action):
    button = _buttons.get(action)
    return button is not None and bool(badge.held(button))


def ticks():
    """Milliseconds since boot."""
    return badge.ticks


# ── drawing ────────────────────────────────────────────────────────────────────

def _pen(colour):
    pen = _colours.get(colour)
    if pen is None:
        pen = color.rgb(*colour)
        _colours[colour] = pen
    screen.pen = pen


def line_height(size=2):
    """Height of one line of text at *size*, measured from the font once."""
    height = _line_h.get(size)
    if height is None:
        screen.font = _font
        try:
            height = int(screen.measure_text("Ag", size)[1]) or _FALLBACK_LINE_H * size
        except (AttributeError, TypeError, ValueError):
            height = _FALLBACK_LINE_H * size
        _line_h[size] = height
    return height


def clear(colour=BLACK):
    _pen(colour)
    screen.clear()


def text(value, x, y, colour=WHITE, size=2, width=None, lines=1):
    """Draw text at (x, y). With *width*, it is laid out in a box that many
    pixels wide and *lines* lines tall — wrapped by the firmware, with a
    trailing ellipsis on the last line when it does not all fit."""
    screen.font = _font
    _pen(colour)
    value = str(value)
    if width is None:
        screen.text(value, int(x), int(y), size)
    else:
        bounds = rect(int(x), int(y), int(width), line_height(size) * lines)
        screen.text(value, bounds, size, overflow=image.ELLIPSES)


def centred(value, y, colour=WHITE, size=2, x=0, span=WIDTH):
    """Centre *value* horizontally within [x, x + span), stepping the size
    down when it would not fit — status lines carry user-typed text."""
    screen.font = _font
    value = str(value)
    width = screen.measure_text(value, size)[0]
    while size > 1 and width > span:
        size -= 1
        width = screen.measure_text(value, size)[0]
    if width > span:
        text(value, x, y, colour, size, width=span)
    else:
        text(value, x + (span - width) / 2, y, colour, size)


def box(x, y, w, h, colour, radius=0):
    _pen(colour)
    if radius:
        screen.shape(shape.rounded_rectangle(int(x), int(y), int(w), int(h), radius))
    else:
        screen.shape(shape.rectangle(int(x), int(y), int(w), int(h)))


HEADER_H = 30
FOOTER_H = 16


def header(title, subtitle=""):
    box(0, 0, WIDTH, HEADER_H, PANEL)
    text(title, 8, 2, ACCENT, 2, width=WIDTH - 16)
    if subtitle:
        text(subtitle, 8, HEADER_H + 2, DIM, 1, width=WIDTH - 16)


def footer(hint):
    """One line of control legend along the bottom — the pads have no labels
    printed next to the screen."""
    box(0, HEIGHT - FOOTER_H, WIDTH, FOOTER_H, PANEL)
    text(hint, 6, HEIGHT - FOOTER_H + 2, DIM, 1, width=WIDTH - 12)
