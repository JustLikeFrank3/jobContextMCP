"""
One-time schema migration: add `fitment_context TEXT` column to job_queue.

Safe to run multiple times — silently no-ops if the column already exists.

Usage:
    python scripts/add_fitment_context_column.py [--db PATH]

Defaults to the path resolved by lib.config (i.e. whatever DB the server uses).
"""

import argparse
import sqlite3
import sys
from pathlib import Path

# Allow running from repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.db import db_path as _default_db_path  # noqa: E402  (after sys.path tweak)


def _db_path(override: str | None) -> Path:
    if override:
        return Path(override)
    p = _default_db_path()
    if not p or not p.exists():
        raise FileNotFoundError(
            f"DB not found at '{p}'. Pass --db to specify the path explicitly."
        )
    return p


def run(db: Path) -> None:
    print(f"Migrating: {db}")
    con = sqlite3.connect(str(db))
    try:
        # Check current columns
        cols = {row[1] for row in con.execute("PRAGMA table_info(job_queue)")}
        if "fitment_context" in cols:
            print("  ✓ fitment_context column already exists — nothing to do.")
            return

        con.execute("ALTER TABLE job_queue ADD COLUMN fitment_context TEXT")
        con.commit()
        print("  ✓ Added fitment_context TEXT column to job_queue.")

        # Also fix fitment_score affinity if it was declared REAL (SQLite DDL
        # can't ALTER column type, but storing '9/10' strings in a REAL column
        # works fine at runtime due to SQLite's flexible typing — no action needed).

    finally:
        con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add fitment_context column to job_queue.")
    parser.add_argument("--db", help="Path to the SQLite DB file.", default=None)
    args = parser.parse_args()

    try:
        db_path = _db_path(args.db)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    run(db_path)
