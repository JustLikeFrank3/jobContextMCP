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

# How many characters flank the highlight. Nine fits 320px comfortably at
# scale 2 with room for the cursor box.
_WINDOW = 9


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
        # What has been typed so far, with a block cursor.
        ui.rect(0, 60, ui.WIDTH, 34, (12, 18, 30))
        shown = text_so_far[-24:] if len(text_so_far) > 24 else text_so_far
        ui.text(shown or "type a company", 10, 68, ui.WHITE if shown else ui.DIM, 2)

        # The strip, highlight in the middle.
        centre_x = ui.WIDTH // 2
        ui.rect(centre_x - 14, 118, 28, 34, (30, 46, 70))
        for offset in range(-_WINDOW // 2, _WINDOW // 2 + 1):
            char = CHARSET[(self.index + offset) % len(CHARSET)]
            x = centre_x + offset * 28 - 5
            if x < 0 or x > ui.WIDTH - 10:
                continue
            colour = ui.ACCENT if offset == 0 else ui.DIM
            ui.text("_" if char == " " else char, x, 126, colour, 2)
