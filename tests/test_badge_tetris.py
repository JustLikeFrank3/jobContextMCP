"""The screen saver's self-playing Tetris (badge/jobcontext/tetris.py).

Pure logic, MicroPython-safe, so it is tested here on the host directly.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "badge" / "jobcontext" / "tetris.py"


@pytest.fixture()
def tetris():
    spec = importlib.util.spec_from_file_location("badge_tetris", _SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_each_piece_has_its_distinct_rotations(tetris):
    # I O T S Z J L
    assert [len(r) for r in tetris.ROTATIONS] == [2, 1, 4, 2, 2, 4, 4]
    assert all(len(cells) == 4 for rots in tetris.ROTATIONS for cells in rots)


def test_full_rows_clear_and_the_stack_drops(tetris):
    board = [[0] * tetris.W for _ in range(tetris.H)]
    board[-1] = [1] * tetris.W
    board[-2] = [1] * (tetris.W - 1) + [0]
    after, cleared = tetris.clear_lines(board)
    assert cleared == 1
    assert after[-1] == [1] * (tetris.W - 1) + [0]
    assert len(after) == tetris.H


def test_ai_takes_the_line_clear_when_one_is_on_offer(tetris):
    board = [[0] * tetris.W for _ in range(tetris.H)]
    board[-1] = [1] * (tetris.W - 1) + [0]       # gap in the last column
    rot, x = tetris.best_move(board, 0)           # I piece
    cells = tetris.ROTATIONS[0][rot]
    assert {x + dx for dx, _ in cells} == {tetris.W - 1}  # vertical, into the gap


def test_game_plays_itself_and_clears_lines(tetris):
    game = tetris.Game(seed=3)
    for _ in range(6000):
        game.step()
        for x, y, colour in game.cells():
            assert 0 <= x < tetris.W and 0 <= y < tetris.H and 1 <= colour <= 7
    assert game.lines > 10


def test_topping_out_restarts_instead_of_stopping(tetris):
    game = tetris.Game(seed=5)
    game.board = [[1] * (tetris.W - 1) + [0] for _ in range(tetris.H)]  # nothing fits
    game._spawn()
    assert game.games == 2
    assert not any(any(row) for row in game.board)
