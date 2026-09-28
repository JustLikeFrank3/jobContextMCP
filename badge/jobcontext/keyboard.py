"""On-screen grid keyboard for the badge's d-pad.

The 2025 badge had UP, DOWN, A, B and C — no left/right — so entry there was
a one-dimensional character strip. The 2026 badge has a full capacitive d-pad,
so this is an ordinary grid: move the cursor in two dimensions, SELECT types.

Rows are ordered for company names: letters first, then the punctuation that
actually appears in them, then digits, then the action keys. Movement wraps
on both axes, because from 'A' the fastest way to 'J' is one step left.
"""

try:
    from . import ui
except ImportError:
    import ui

SPACE = "SPACE"
DELETE = "DEL"
SEARCH = "GO"

ROWS = (
    tuple("ABCDEFGHIJ"),
    tuple("KLMNOPQRST"),
    tuple("UVWXYZ.-&'"),
    tuple("0123456789"),
    (SPACE, DELETE, SEARCH),
)

_LABELS = {SPACE: "space", DELETE: "del", SEARCH: "search"}

# Laid out from measured metrics: a size-2 glyph line is 26px, so 30px rows
# fit five rows between the 30px header + entry line and the 16px footer.
_ENTRY_Y = 34
_TOP = 68
_CELL_H = 30
_LEFT = 10
_GRID_W = ui.WIDTH - 2 * _LEFT


class OnScreenKeyboard:
    def __init__(self):
        self.row = 0
        self.col = 0

    def move(self, d_row, d_col):
        if d_row:
            old = len(ROWS[self.row])
            self.row = (self.row + d_row) % len(ROWS)
            new = len(ROWS[self.row])
            # Rows differ in length (the action row has three wide keys), so
            # keep the cursor at the same horizontal *position*, not index.
            self.col = min(new - 1, int((self.col + 0.5) * new / old))
        if d_col:
            self.col = (self.col + d_col) % len(ROWS[self.row])

    def current(self):
        return ROWS[self.row][self.col]

    def draw(self, text_so_far):
        # The entry line, newest characters kept visible.
        ui.box(_LEFT, _ENTRY_Y - 2, _GRID_W, ui.line_height(2) + 4, ui.PANEL, 4)
        if text_so_far:
            # Keep the end of the query (where typing happens) in view: at
            # size 2 a character is 16px, so 16 of them plus the cursor fit
            # the 284px line. Any more and the firmware ellipsizes the tail.
            ui.text(text_so_far[-16:] + "_", _LEFT + 8, _ENTRY_Y, ui.WHITE, 2, width=_GRID_W - 16)
        else:
            ui.text("type a company", _LEFT + 8, _ENTRY_Y, ui.DIM, 2, width=_GRID_W - 16)

        for r, keys in enumerate(ROWS):
            cell_w = _GRID_W / len(keys)
            y = _TOP + r * _CELL_H
            for c, key in enumerate(keys):
                x = _LEFT + c * cell_w
                chosen = r == self.row and c == self.col
                if chosen:
                    ui.box(x + 1, y, cell_w - 2, _CELL_H - 2, ui.HIGHLIGHT, 4)
                label = _LABELS.get(key, key)
                size = 1 if len(label) > 1 else 2
                ui.centred(
                    label,
                    y + (_CELL_H - ui.line_height(size)) / 2 - 1,
                    ui.ACCENT if chosen else ui.WHITE,
                    size,
                    x=x,
                    span=cell_w,
                )
