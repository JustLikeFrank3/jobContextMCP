"""On-screen keyboard for a badge with five buttons and no left/right.

A grid keyboard needs four-way movement; the badge has UP, DOWN, A, B, C.
So entry is a horizontal character strip: UP/DOWN slide the highlight along
it, A types the highlighted character.  Held UP/DOWN accelerates (see
inputs._Edges), which is what makes reaching 'W' bearable.

The strip is ordered to put the common cases first — letters, then digits,
then the handful of punctuation marks that appear in company names.
"""

try:
    from . import ui
except ImportError:
    import ui

CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .-&'"

# Strip geometry on the 160x120 screen: 16px cells, four characters either
# side of the highlight (9 x 16 = 144px).
_CELL = 16
_WINDOW = 4
_ENTRY_Y = 31
_STRIP_Y = 62


class OnScreenKeyboard:
    def __init__(self):
        self.index = 0

    def move(self, delta):
        # Wrap: scrolling off the end of the strip returns to the start, which
        # is much faster than reversing when the target is 'A' and you're on 'Z'.
        self.index = (self.index + delta) % len(CHARSET)

    def current(self):
        return CHARSET[self.index]

    def draw(self, text_so_far):
        """Render the entry line and the character strip."""
        # What has been typed so far; the tail stays visible as it grows.
        ui.rect(0, _ENTRY_Y, ui.WIDTH, 18, (12, 18, 30))
        if text_so_far:
            ui.text(ui.fit_tail(text_so_far + "_", ui.WIDTH - 8, 2), 4, _ENTRY_Y + 3, ui.WHITE, 2)
        else:
            ui.text("type a company", 4, _ENTRY_Y + 3, ui.DIM, 2)

        # The strip, highlight in the middle.
        centre_x = ui.WIDTH // 2
        ui.rect(centre_x - _CELL // 2, _STRIP_Y - 3, _CELL, 18, (30, 46, 70))
        for offset in range(-_WINDOW, _WINDOW + 1):
            char = CHARSET[(self.index + offset) % len(CHARSET)]
            glyph = "_" if char == " " else char
            x = centre_x + offset * _CELL - ui.text_width(glyph, 2) // 2
            colour = ui.ACCENT if offset == 0 else ui.DIM
            ui.text(glyph, x, _STRIP_Y, colour, 2)
