"""Drawing + button shim for the GitHub Universe 2025 badge.

Everything hardware-specific is isolated in this one module on purpose.  The
badge ships Pimoroni's badgeware MicroPython firmware, whose exact drawing API
has moved between the e-ink Badger and the Tufty 2350 colour build, so the app
talks to the small surface defined here and this file adapts it to whatever
the firmware actually exposes.  If the badge's API differs from the guesses
below, this is the only file that needs editing.

Screen: 2.8" IPS, 320x240, full colour.
Buttons: UP, DOWN, A, B, C (no left/right — see keyboard.py for why that
shapes text entry the way it does).
"""

WIDTH = 320
HEIGHT = 240

# Colours as (r, g, b); the shim converts to whatever the firmware wants.
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
DIM = (140, 150, 165)
ACCENT = (60, 200, 210)
WARN = (240, 170, 60)
BAD = (235, 90, 90)
OK = (110, 210, 130)

# Rough character width at the default font, used for truncation and for
# centring without asking the firmware to measure.
CHAR_W = 8
LINE_H = 16

_display = None
_buttons = {}


def _import_firmware():
    """Return (display, buttons) from whichever firmware module is present."""
    try:  # Tufty / badgeware colour build
        import badgeware  # type: ignore

        return badgeware.display, {
            "UP": badgeware.button_up,
            "DOWN": badgeware.button_down,
            "A": badgeware.button_a,
            "B": badgeware.button_b,
            "C": badgeware.button_c,
        }
    except ImportError:
        pass
    try:  # PicoGraphics-style fallback
        from picographics import DISPLAY_TUFTY_2040, PicoGraphics  # type: ignore
        from pimoroni import Button  # type: ignore

        display = PicoGraphics(display=DISPLAY_TUFTY_2040)
        return display, {
            "UP": Button(22, invert=False),
            "DOWN": Button(6, invert=False),
            "A": Button(7, invert=False),
            "B": Button(8, invert=False),
            "C": Button(9, invert=False),
        }
    except ImportError:
        return None, {}


def init():
    global _display, _buttons
    _display, _buttons = _import_firmware()
    return _display is not None


def pressed(name):
    """True if button *name* is currently down. Unknown buttons read False so
    a firmware that lacks one degrades instead of crashing."""
    btn = _buttons.get(name)
    if btn is None:
        return False
    try:
        return bool(btn.read())
    except AttributeError:
        return bool(btn.value())


# ── drawing ────────────────────────────────────────────────────────────────────

def _pen(colour):
    if _display is None:
        return
    try:
        _display.set_pen(_display.create_pen(*colour))
    except AttributeError:
        _display.set_pen(colour)


def clear(colour=BLACK):
    if _display is None:
        return
    _pen(colour)
    _display.clear()


def text(value, x, y, colour=WHITE, scale=2):
    if _display is None:
        return
    _pen(colour)
    _display.text(str(value), int(x), int(y), WIDTH, scale)


def rect(x, y, w, h, colour):
    if _display is None:
        return
    _pen(colour)
    _display.rectangle(int(x), int(y), int(w), int(h))


def hline(y, colour=DIM):
    rect(0, y, WIDTH, 1, colour)


def flip():
    if _display is None:
        return
    _display.update()


def fit(value, chars):
    """Trim to *chars*, with a trailing dot when cut. The server already
    truncates payloads to display width; this catches locally-built strings."""
    value = str(value)
    if len(value) <= chars:
        return value
    return value[: chars - 1] + "."


def header(title, subtitle=""):
    rect(0, 0, WIDTH, 28, (18, 26, 40))
    text(fit(title, 26), 8, 6, ACCENT, 2)
    if subtitle:
        text(fit(subtitle, 34), 8, 32, DIM, 1)


def footer(hint):
    """One line of button legend along the bottom — the badge has no labels."""
    rect(0, HEIGHT - 18, WIDTH, 18, (18, 26, 40))
    text(fit(hint, 52), 6, HEIGHT - 14, DIM, 1)
