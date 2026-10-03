"""Self-playing Tetris for the screen saver.

Pure game logic — no hardware, no drawing — so it runs (and is tested) on the
host as well as the badge. screensaver.py owns the pixels.

The player is the classic one-piece-lookahead heuristic: when a piece spawns,
try every rotation at every column, drop it, and score the resulting board on
lines cleared, aggregate height, holes and bumpiness (weights from Yiyuan
Lee's well-known tuning). The chosen move is then *animated* — rotate, slide,
fall one row per step — so it looks played rather than teleported. When the
stack tops out the board resets; a screen saver never shows "game over".

MicroPython-safe: no dataclasses, no typing, only random.randint.
"""

import random

W = 10
H = 20

_SHAPES = (
    ((0, 1), (1, 1), (2, 1), (3, 1)),  # I
    ((0, 0), (1, 0), (0, 1), (1, 1)),  # O
    ((1, 0), (0, 1), (1, 1), (2, 1)),  # T
    ((1, 0), (2, 0), (0, 1), (1, 1)),  # S
    ((0, 0), (1, 0), (1, 1), (2, 1)),  # Z
    ((0, 0), (0, 1), (1, 1), (2, 1)),  # J
    ((2, 0), (0, 1), (1, 1), (2, 1)),  # L
)

_W_LINES = 0.760666
_W_HEIGHT = -0.510066
_W_HOLES = -0.35663
_W_BUMPY = -0.184483


def _rotations(cells):
    """Distinct rotations of *cells*, each normalised to a (0, 0) origin."""
    out = []
    cur = list(cells)
    for _ in range(4):
        min_x = min(x for x, _y in cur)
        min_y = min(y for _x, y in cur)
        norm = tuple(sorted((x - min_x, y - min_y) for x, y in cur))
        if norm not in out:
            out.append(norm)
        cur = [(-y, x) for x, y in cur]
    return out


ROTATIONS = [_rotations(s) for s in _SHAPES]
KINDS = len(ROTATIONS)


def fits(board, kind, rot, x, y):
    for dx, dy in ROTATIONS[kind][rot]:
        cx, cy = x + dx, y + dy
        if cx < 0 or cx >= W or cy >= H:
            return False
        if cy >= 0 and board[cy][cx]:
            return False
    return True


def _drop_y(board, kind, rot, x):
    """Lowest y the piece reaches falling straight down from the top, or None."""
    if not fits(board, kind, rot, x, 0):
        return None
    y = 0
    while fits(board, kind, rot, x, y + 1):
        y += 1
    return y


def _place(board, kind, rot, x, y):
    """A copy of *board* with the piece locked in (colour = kind + 1)."""
    new = [row[:] for row in board]
    for dx, dy in ROTATIONS[kind][rot]:
        if 0 <= y + dy < H:
            new[y + dy][x + dx] = kind + 1
    return new


def clear_lines(board):
    """Return (board without full rows, number of rows cleared)."""
    kept = [row for row in board if not all(row)]
    cleared = H - len(kept)
    return [[0] * W for _ in range(cleared)] + kept, cleared


def score(board, cleared):
    heights = []
    holes = 0
    for x in range(W):
        top = H
        for y in range(H):
            if board[y][x]:
                top = y
                break
        heights.append(H - top)
        for y in range(top + 1, H):
            if not board[y][x]:
                holes += 1
    bumpy = 0
    for i in range(W - 1):
        bumpy += abs(heights[i] - heights[i + 1])
    return (_W_LINES * cleared + _W_HEIGHT * sum(heights)
            + _W_HOLES * holes + _W_BUMPY * bumpy)


def best_move(board, kind):
    """(rot, x) of the best placement for *kind*, or None if nothing fits."""
    best = None
    best_score = 0
    for rot in range(len(ROTATIONS[kind])):
        for x in range(-1, W):
            y = _drop_y(board, kind, rot, x)
            if y is None:
                continue
            after, cleared = clear_lines(_place(board, kind, rot, x, y))
            s = score(after, cleared)
            if best is None or s > best_score:
                best, best_score = (rot, x), s
    return best


class Game:
    """One endless self-playing game. Call step() on a timer; read cells()."""

    def __init__(self, seed=None):
        if seed is not None:
            random.seed(seed)
        self.games = 0
        self.reset()

    def reset(self):
        self.board = [[0] * W for _ in range(H)]
        self.lines = 0
        self.games += 1
        self._spawn()

    def _spawn(self):
        self.kind = random.randint(0, KINDS - 1)
        self.rot = 0
        self.x = (W - 3) // 2
        self.y = 0
        move = best_move(self.board, self.kind)
        if move is None or not fits(self.board, self.kind, self.rot, self.x, self.y):
            self.reset()  # topped out: start over rather than stop
            return
        self.target = move

    def step(self):
        """Advance one animation tick: rotate, then slide, then fall."""
        t_rot, t_x = self.target
        if self.rot != t_rot and fits(self.board, self.kind, t_rot, self.x, self.y):
            self.rot = t_rot
            return
        if self.x != t_x:
            nx = self.x + (1 if t_x > self.x else -1)
            if fits(self.board, self.kind, self.rot, nx, self.y):
                self.x = nx
                return
        if fits(self.board, self.kind, self.rot, self.x, self.y + 1):
            self.y += 1
            return
        self.board, cleared = clear_lines(_place(self.board, self.kind, self.rot, self.x, self.y))
        self.lines += cleared
        self._spawn()

    def cells(self):
        """(x, y, colour) for every filled cell, the falling piece included."""
        out = []
        for y in range(H):
            row = self.board[y]
            for x in range(W):
                if row[x]:
                    out.append((x, y, row[x]))
        for dx, dy in ROTATIONS[self.kind][self.rot]:
            if self.y + dy >= 0:
                out.append((self.x + dx, self.y + dy, self.kind + 1))
        return out
