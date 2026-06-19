#!/usr/bin/env python3
"""
Import `data/job_queue.json` into SQLite `job_queue` table if the table is empty.
This is safe to run on startup; it's idempotent (will not duplicate rows)
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import config
from lib.db import get_connection, db_path

JOB_FILE = config.JOB_QUEUE_FILE
DB = db_path()


def main() -> int:
    if not JOB_FILE.exists():
        print(f"No {JOB_FILE} found — nothing to import.")
        return 0
    if not DB.exists():
        print(f"DB {DB} not found — cannot import.")
        return 1

    data = json.loads(JOB_FILE.read_text(encoding="utf-8"))
    jobs = data.get("jobs", [])
    if not jobs:
        print("No jobs in JSON — nothing to import.")
        return 0

    with get_connection() as con:
        cur = con.execute("SELECT COUNT(*) FROM job_queue")
        count = cur.fetchone()[0]
        if count > 0:
            print(f"job_queue already has {count} rows — skipping import.")
            return 0

        cur = con.cursor()
        cur.executemany(
            """
            INSERT OR REPLACE INTO job_queue
                (id, company, role, jd, source, added_date, status,
                 fitment_score, fitment_context, decision_notes, decided_date)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    r.get("id"), r.get("company", ""), r.get("role", ""),
                    r.get("jd"), r.get("source"), r.get("added_date"),
                    r.get("status", "pending"), r.get("fitment_score"),
                    r.get("fitment_context"), r.get("decision_notes"),
                    r.get("decided_date"),
                )
                for r in jobs
            ],
        )
        con.commit()
        print(f"Imported {len(jobs)} jobs into DB.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
