"""Contact-card screen saver: who you are on the left, Tetris on the right.

Shown by the app after a stretch with no button presses (contact.IDLE_SECONDS)
so a badge left on the jobcontext app works as a name tag. Any button wakes
it; the app swallows that press so it never also acts on the screen below.

The left panel alternates between the text card and a QR code of the same
details (a MECARD — see qr_payload), so scanning it adds you to contacts. The right
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
_qr = None          # (modules, runs) once encoded; False if unavailable
_qr_scale = 2
_qr_full = False    # QR too dense for the side panel: it takes the screen
_MIN_MODULE_PX = 2  # 1px modules (2 physical px) proved unscannable
_shown_page = None  # page currently on screen; static pages draw once


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


def _mecard_escape(value):
    out = ""
    for ch in value:
        out += ("\\" + ch) if ch in ";:,\\" else ch
    return out


def qr_payload(c):
    """Contact details for the QR, as a MECARD — not a vCard.

    The first on-badge test used a full vCard 3.0: 261 bytes, a 65x65 code
    drawn at 1px per module, and phones could not scan it off the screen.
    MECARD carries the same contact without the vCard boilerplate, links drop
    their https://, and the title is left out (MECARD has no title field and
    it is on the text card anyway). A typical card is then ~150 bytes, a
    49x49 code at 2px per module: twice the size, and it scans. Both the iOS
    and Android cameras read MECARD.
    """
    parts = ["N:" + _mecard_escape(_field(c, "NAME"))]
    if _field(c, "EMAIL"):
        parts.append("EMAIL:" + _mecard_escape(_field(c, "EMAIL")))
    if _field(c, "PHONE"):
        parts.append("TEL:" + _mecard_escape(_field(c, "PHONE")))
    for prefix, key in (("linkedin.com/in/", "LINKEDIN"), ("github.com/", "GITHUB"), ("", "WEBSITE")):
        if _field(c, key):
            parts.append("URL:" + _mecard_escape(prefix + _field(c, key)))
    return "MECARD:" + ";".join(parts) + ";;"


def start(now):
    """Begin (or resume) showing the saver at tick *now*."""
    global _game, _last_step, _started, _qr, _shown_page
    if _game is None:
        _game = tetris.Game()
    if _qr is None:
        _qr = _render_qr()
    _last_step = now
    _started = now
    _shown_page = None  # whatever the app drew is underneath: redraw fully


def _render_qr():
    """Encode the QR once and pick where it goes.

    Beside Tetris if it fits at 2px per module; otherwise the QR page takes
    the whole screen, because a smaller code is a code nobody can scan.
    """
    global _qr_full, _qr_scale
    qr = ui.qr_code(qr_payload(contact))
    if not qr:
        return False
    side = qr[0] + 2 * ui.QR_QUIET
    _qr_scale = min(_PANEL_W, ui.HEIGHT) // side
    _qr_full = _qr_scale < _MIN_MODULE_PX
    if _qr_full:
        _qr_scale = max(1, min(ui.WIDTH, ui.HEIGHT) // side)
    return qr


def draw(now):
    """Advance Tetris as time allows and draw the frame.

    The card and the QR are static, so they are drawn only when the page
    changes; every other frame repaints just the Tetris well. A dense QR is
    hundreds of rectangles — fine once, wasteful at 30 fps.
    """
    global _last_step, _shown_page
    while time.ticks_diff(now, _last_step) >= _STEP_MS:
        _game.step()
        _last_step += _STEP_MS

    page = "qr" if _qr and (time.ticks_diff(now, _started) // _PAGE_MS) % 2 == 1 else "card"
    if page != _shown_page:
        _shown_page = page
        ui.clear(ui.BLACK)
        if page == "qr":
            _draw_qr()
        else:
            _draw_card()
    if page == "qr" and _qr_full:
        return
    _draw_well("scan me" if page == "qr" else "lines " + str(_game.lines))


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
    # White behind the whole panel, not just the code's own quiet zone: the
    # wider the light margin, the easier the scan.
    width = ui.WIDTH if _qr_full else _PANEL_W
    side = (_qr[0] + 2 * ui.QR_QUIET) * _qr_scale
    ui.rect(0, 0, width, ui.HEIGHT, ui.WHITE)
    ui.draw_qr(_qr, (width - side) // 2, (ui.HEIGHT - side) // 2, _qr_scale)


def _draw_well(label):
    w = tetris.W * _CELL
    h = tetris.H * _CELL
    ui.rect(_WELL_X - 1, 0, ui.WIDTH - _WELL_X + 1, _WELL_Y - 1, ui.BLACK)  # label area
    ui.text(label, _WELL_X, 6, ui.DIM, 1)
    ui.rect(_WELL_X - 1, _WELL_Y - 1, w + 2, h + 2, ui.DIM)
    ui.rect(_WELL_X, _WELL_Y, w, h, ui.PANEL)
    for x, y, colour in _game.cells():
        ui.rect(_WELL_X + x * _CELL, _WELL_Y + y * _CELL, _CELL - 1, _CELL - 1,
                _PIECE_COLOURS[colour])
