"""
lib/db.py — SQLite connection helper for jobContextMCP.

Usage
-----
    from lib.db import get_connection

    with get_connection() as con:
        row = con.execute("SELECT * FROM applications WHERE id = ?", (1,)).fetchone()
        print(dict(row))

The context manager commits on clean exit and rolls back on any exception.
All rows are returned as sqlite3.Row objects (subscriptable by name).
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Generator
import sqlite3

import lib.config as _cfg


def db_path() -> Path:
    """Return the path to the SQLite database, derived from config DATA_FOLDER."""
    return Path(str(_cfg.DATA_FOLDER)) / "jobcontextmcp.db"


@contextmanager
def get_connection(path: Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    """
    Yield an open sqlite3 Connection with WAL mode and foreign keys enabled.

    Commits on clean exit, rolls back on exception.

    Parameters
    ----------
    path : override the default db_path() — useful for tests pointing at data_dev/.
    """
    resolved = path or db_path()
    con = sqlite3.connect(resolved)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
