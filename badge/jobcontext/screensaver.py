"""Contact-card screen saver: who you are on the left, Tetris on the right.

Shown by the app after a stretch with no button presses (contact.IDLE_SECONDS)
so a badge left on the jobcontext app works as a name tag. Any button wakes
it; the app swallows that press so it never also acts on the screen below.

The left panel alternates between the text card and a QR code of the same
details as a vCard, so scanning it adds you to someone's contacts. The right
panel is tetris.Game playing itself.

    +----------------------+---------+
    | Frank MacBride       | lines 12|
    | Senior SWE           | +-----+ |
    |                      | |     | |
    | you@example.com      | | ##  | |
    | in/handle            | |#### | |
    | gh/handle            | +-----+ |
    +----------------------+---------+

No contact.py means no screen saver: the app simply never idles into it.
"""

import time

try:
    from . import tetris, ui
except ImportError:
    import tetris
    import ui

_CELL = 4                    # px per Tetris cell: 10x20 well = 40x80
_WELL_X = ui.WIDTH - tetris.W * _CELL - 2
_WELL_Y = 24
_PANEL_W = _WELL_X - 4       # left panel width
_STEP_MS = 110               # Tetris animation tick
_PAGE_MS = 7000              # card <-> QR alternation
_PIECE_COLOURS = (
    (0, 0, 0),
    (60, 200, 210),   # I
    (240, 210, 70),   # O
    (175, 110, 230),  # T
    (110, 210, 130),  # S
    (235, 90, 90),    # Z
    (80, 130, 235),   # J
    (240, 160, 60),   # L
)

contact = None
_game = None
_last_step = 0
_started = 0
_qr = None          # (image, side) once rendered; False if unavailable


def load():
    """Import contact.py if present. Returns True when the saver is usable."""
    global contact
    try:
        from . import contact as c  # type: ignore
    except ImportError:
        try:
            import contact as c  # type: ignore
        except ImportError:
            c = None
    contact = c if c is not None and _field(c, "NAME") else None
    return contact is not None


def enabled():
    return contact is not None


def idle_ms():
    try:
        seconds = int(getattr(contact, "IDLE_SECONDS", 30))
    except (TypeError, ValueError):
        seconds = 30
    return max(5, seconds) * 1000


def _field(module, name):
    value = getattr(module, name, "") or ""
    return " ".join(str(value).split())


def vcard(c):
    """A minimal vCard 3.0 for *c* — only the fields that are filled in.

    Minimal on purpose: every byte grows the QR, and a dense code is hard to
    scan off a small screen.
    """
    name = _field(c, "NAME")
    parts = name.rsplit(" ", 1)
    family, given = (parts[1], parts[0]) if len(parts) == 2 else (name, "")
    lines = ["BEGIN:VCARD", "VERSION:3.0", "N:" + family + ";" + given, "FN:" + name]
    if _field(c, "TITLE"):
        lines.append("TITLE:" + _field(c, "TITLE"))
    if _field(c, "EMAIL"):
        lines.append("EMAIL:" + _field(c, "EMAIL"))
    if _field(c, "PHONE"):
        lines.append("TEL:" + _field(c, "PHONE"))
    if _field(c, "LINKEDIN"):
        lines.append("URL:https://linkedin.com/in/" + _field(c, "LINKEDIN"))
    if _field(c, "GITHUB"):
        lines.append("URL:https://github.com/" + _field(c, "GITHUB"))
    if _field(c, "WEBSITE"):
        lines.append("URL:https://" + _field(c, "WEBSITE"))
    lines.append("END:VCARD")
    return "\n".join(lines)


def start(now):
    """Begin (or resume) showing the saver at tick *now*."""
    global _game, _last_step, _started, _qr
    if _game is None:
        _game = tetris.Game()
    if _qr is None:
        # Render once: re-drawing a ~45x45 code module by module every frame
        # is far too slow on the badge, a cached image is one blit.
        _qr = ui.qr_image(vcard(contact), _PANEL_W, ui.HEIGHT - 14) or False
    _last_step = now
    _started = now


def draw(now):
    """Advance Tetris as time allows and draw one full frame."""
    global _last_step
    while time.ticks_diff(now, _last_step) >= _STEP_MS:
        _game.step()
        _last_step += _STEP_MS

    ui.clear(ui.BLACK)
    show_qr = _qr and (time.ticks_diff(now, _started) // _PAGE_MS) % 2 == 1
    if show_qr:
        _draw_qr()
    else:
        _draw_card()
    _draw_well()


def _draw_card():
    width = _PANEL_W - 4
    y = 4
    for line in ui.wrap(_field(contact, "NAME"), width, 2, 2):
        ui.text(line, 4, y, ui.ACCENT, 2)
        y += ui.line_height(2) + 1
    title = _field(contact, "TITLE")
    if title:
        for line in ui.wrap(title, width, 1, 2):
            ui.text(line, 4, y, ui.WHITE, 1)
            y += ui.line_height(1)
    y += 6
    for prefix, key in (("", "EMAIL"), ("", "PHONE"), ("in/", "LINKEDIN"),
                        ("gh/", "GITHUB"), ("", "WEBSITE")):
        value = _field(contact, key)
        if not value or y > ui.HEIGHT - ui.line_height(1):
            continue
        ui.text(ui.fit(prefix + value, width, 1), 4, y, ui.DIM, 1)
        y += ui.line_height(1)


def _draw_qr():
    image, side = _qr
    x = max(0, (_PANEL_W - side) // 2)
    ui.blit(image, x, 2)
    ui.text(ui.fit("scan to save my contact", _PANEL_W, 1), 4, ui.HEIGHT - 12, ui.DIM, 1)


def _draw_well():
    w = tetris.W * _CELL
    h = tetris.H * _CELL
    ui.text("lines " + str(_game.lines), _WELL_X, 6, ui.DIM, 1)
    ui.rect(_WELL_X - 1, _WELL_Y - 1, w + 2, h + 2, ui.DIM)
    ui.rect(_WELL_X, _WELL_Y, w, h, ui.PANEL)
    for x, y, colour in _game.cells():
        ui.rect(_WELL_X + x * _CELL, _WELL_Y + y * _CELL, _CELL - 1, _CELL - 1,
                _PIECE_COLOURS[colour])
