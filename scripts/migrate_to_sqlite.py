#!/usr/bin/env python3
"""
Migrate jobContextMCP JSON data files → SQLite.

Source : data_dev/   (safe working copy, never written by production server)
Target : data_dev/jobcontextmcp.db

Idempotent: deletes and fully recreates the .db on every run.
Run from project root:

    python scripts/migrate_to_sqlite.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

# Ensure project root is on sys.path when the script is run directly
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lib.db import normalize_event_type

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data_dev"
DB_PATH = DATA_DIR / "jobcontextmcp.db"

# ── DDL ───────────────────────────────────────────────────────────────────────
_SCHEMA = """
-- ── Tier 1 — Core relational ─────────────────────────────────────────────────

CREATE TABLE applications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    company      TEXT    NOT NULL,
    role         TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'pre-application',
    next_steps   TEXT,
    contact      TEXT,
    notes        TEXT,
    applied_date TEXT,
    last_updated TEXT,
    location     TEXT,
    date_applied TEXT,
    req_number   TEXT,
    comp         TEXT     -- JSON object
);

CREATE TABLE application_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    type           TEXT    NOT NULL
                           CHECK (type IN (
                               'applied','contact_update','follow_up_sent',
                               'hiring_manager_contact','interview_completed',
                               'interview_scheduled','note','outreach_sent',
                               'phone_screen','recruiter_contact',
                               'referral_confirmed','referral_identified',
                               'referral_submitted','rejected',
                               'reply_received','reply_sent'
                           )),
    raw_type       TEXT,    -- original value before normalization
    notes          TEXT,
    date           TEXT
);

CREATE TABLE job_queue (
    id              INTEGER PRIMARY KEY,
    company         TEXT    NOT NULL,
    role            TEXT    NOT NULL,
    jd              TEXT,
    source          TEXT,
    added_date      TEXT,
    status          TEXT    DEFAULT 'pending',
    fitment_score   TEXT,
    fitment_context TEXT,
    decision_notes  TEXT,
    decided_date    TEXT,
    resume_template TEXT,
    resume_style    TEXT,
    cl_template     TEXT,
    cl_style        TEXT
);

CREATE TABLE people (
    id              INTEGER PRIMARY KEY,
    timestamp       TEXT,
    name            TEXT    NOT NULL,
    relationship    TEXT,
    company         TEXT,
    context         TEXT,
    tags            TEXT,    -- JSON array
    contact_info    TEXT,
    outreach_status TEXT,
    notes           TEXT,
    last_updated    TEXT
);

CREATE TABLE interviews (
    id                    INTEGER PRIMARY KEY,
    timestamp             TEXT,
    company               TEXT    NOT NULL,
    role                  TEXT    NOT NULL,
    interview_date        TEXT,
    interview_type        TEXT,
    interview_format      TEXT,
    interviewer           TEXT,
    interviewer_role      TEXT,
    duration_minutes      INTEGER,
    self_rating           INTEGER,
    what_landed           TEXT,    -- JSON array
    what_didnt            TEXT,    -- JSON array
    verbatim_quotes       TEXT,    -- JSON array of objects
    surfaced_priorities   TEXT,    -- JSON array
    process_details       TEXT,
    comp_signals          TEXT,
    follow_up_commitments TEXT,    -- JSON array
    tags                  TEXT,    -- JSON array
    notes                 TEXT,
    last_updated          TEXT
);

CREATE TABLE rejections (
    id        INTEGER PRIMARY KEY,
    company   TEXT    NOT NULL,
    role      TEXT    NOT NULL,
    stage     TEXT,
    reason    TEXT,
    notes     TEXT,
    date      TEXT,
    logged_at TEXT,
    contact   TEXT
);

-- ── Tier 2 — Supporting ───────────────────────────────────────────────────────

CREATE TABLE tone_samples (
    id         INTEGER PRIMARY KEY,
    timestamp  TEXT,
    source     TEXT,
    context    TEXT,
    text       TEXT    NOT NULL,
    word_count INTEGER
);

CREATE TABLE health_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  TEXT    NOT NULL,
    date       TEXT    NOT NULL,
    mood       TEXT,
    energy     INTEGER,
    productive INTEGER,    -- 0 / 1
    notes      TEXT
);

CREATE TABLE linkedin_posts (
    id                  INTEGER PRIMARY KEY,
    timestamp           TEXT,
    posted_date         TEXT,
    source              TEXT,
    title               TEXT,
    url                 TEXT,
    hashtags            TEXT,    -- JSON array
    context             TEXT,
    links               TEXT,    -- JSON array
    metrics             TEXT,    -- JSON object
    audience_highlights TEXT     -- JSON object
);

CREATE TABLE stories (
    id        INTEGER PRIMARY KEY,
    timestamp TEXT,
    title     TEXT    NOT NULL,
    story     TEXT    NOT NULL,
    tags      TEXT,    -- JSON array
    people    TEXT     -- JSON array
);

CREATE TABLE star_stories (
    id             TEXT    PRIMARY KEY,    -- e.g. 'msal_documentation_enablement'
    title          TEXT    NOT NULL,
    tags           TEXT,    -- JSON array
    situation      TEXT,
    task           TEXT,
    action         TEXT,
    result         TEXT,
    metric_bullets TEXT,    -- JSON array
    framing_hints  TEXT,    -- JSON object
    source         TEXT,
    notes          TEXT
);

-- ── Tier 3 — Reference / lookup ───────────────────────────────────────────────

CREATE TABLE linkedin_connections (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name           TEXT,
    last_name            TEXT,
    full_name            TEXT,
    full_name_normalized TEXT,
    linkedin_url         TEXT,
    email                TEXT,
    company              TEXT,
    position             TEXT,
    connected_on         TEXT,
    facebook_match       TEXT     -- JSON object
);

CREATE TABLE contact_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT,
    role        TEXT,
    source      TEXT,
    context     TEXT,
    date        TEXT,
    impressions INTEGER,
    reply       INTEGER,    -- 0 / 1
    notes       TEXT
);

CREATE TABLE contact_crossref (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT    NOT NULL,
    normalized     TEXT,
    platforms      TEXT,    -- JSON object
    platform_count INTEGER,
    signals        TEXT,    -- JSON array
    action_hints   TEXT     -- JSON array
);

CREATE TABLE user_api_keys (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash     TEXT    NOT NULL UNIQUE,  -- SHA-256 hex of the plaintext token
    oid          TEXT    NOT NULL,         -- Entra OID of the owning user
    label        TEXT,                     -- human-readable name for the key
    created_at   TEXT    NOT NULL,
    last_used_at TEXT
);
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _j(val) -> str | None:
    """Serialize val to compact JSON string; pass strings through; None stays None."""
    if val is None:
        return None
    if isinstance(val, str):
        return val
    return json.dumps(val, ensure_ascii=False, separators=(",", ":"))


def _assign_missing_ids(rows: list[dict]) -> list[dict]:
    """
    Assign synthetic integer ids to any rows where 'id' is absent or None.
    Uses max(existing ids) + 1 to avoid collisions with explicit ids.
    """
    max_id = max((r.get("id") or 0 for r in rows), default=0)
    counter = max_id + 1
    result = []
    for r in rows:
        if r.get("id") is None:
            r = {**r, "id": counter}
            counter += 1
        result.append(r)
    return result


def _warn_dupes(label: str, rows: list[dict]) -> None:
    """Print a warning if any id appears more than once in the source data."""
    from collections import Counter
    counts = Counter(r.get("id") for r in rows)
    dupes = {k: v for k, v in counts.items() if v > 1 and k is not None}
    if dupes:
        print(f"  ⚠  {label}: duplicate ids in source JSON (last row wins): {dupes}")


def _read(fname: str) -> dict | list:
    path = DATA_DIR / fname
    if not path.exists():
        raise FileNotFoundError(f"Missing source file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# ── Per-table migration functions ─────────────────────────────────────────────

def _applications(cur: sqlite3.Cursor) -> tuple[int, int]:
    data = _read("status.json")
    apps = data.get("applications", [])
    n_apps = n_events = 0
    for app in apps:
        cur.execute(
            """
            INSERT INTO applications
                (company, role, status, next_steps, contact, notes, applied_date, last_updated,
                 location, date_applied, req_number, comp)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                app.get("company", ""),
                app.get("role", ""),
                app.get("status", "pre-application"),
                app.get("next_steps"),
                app.get("contact"),
                app.get("notes"),
                app.get("applied_date"),
                app.get("last_updated") or None,
                app.get("location"),
                app.get("date_applied"),
                app.get("req_number"),
                _j(app.get("comp")),
            ),
        )
        app_id = cur.lastrowid
        for ev in app.get("events", []):
            raw_type = ev.get("type", "note")
            cur.execute(
                "INSERT INTO application_events (application_id, type, raw_type, notes, date) VALUES (?,?,?,?,?)",
                (app_id, normalize_event_type(raw_type), raw_type, ev.get("notes"), ev.get("date")),
            )
            n_events += 1
        n_apps += 1
    return n_apps, n_events


def _job_queue(cur: sqlite3.Cursor) -> int:
    rows = _read("job_queue.json").get("jobs", [])
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
                r.get("fitment_context"), r.get("decision_notes"), r.get("decided_date"),
            )
            for r in rows
        ],
    )
    return len(rows)


def _people(cur: sqlite3.Cursor) -> int:
    rows = _read("people.json").get("people", [])
    _warn_dupes("people", rows)
    cur.executemany(
        """
        INSERT OR REPLACE INTO people
            (id, timestamp, name, relationship, company, context,
             tags, contact_info, outreach_status, notes, last_updated)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                p["id"], p.get("timestamp"), p.get("name", ""),
                p.get("relationship"), p.get("company"), p.get("context"),
                _j(p.get("tags")), p.get("contact_info"),
                p.get("outreach_status"), p.get("notes"), p.get("last_updated"),
            )
            for p in rows
        ],
    )
    return len(rows)


def _interviews(cur: sqlite3.Cursor) -> int:
    rows = _read("interviews.json").get("interviews", [])
    cur.executemany(
        """
        INSERT OR REPLACE INTO interviews
            (id, timestamp, company, role, interview_date, interview_type,
             interview_format, interviewer, interviewer_role, duration_minutes,
             self_rating, what_landed, what_didnt, verbatim_quotes,
             surfaced_priorities, process_details, comp_signals,
             follow_up_commitments, tags, notes, last_updated)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                r.get("id"), r.get("timestamp"), r.get("company", ""), r.get("role", ""),
                r.get("interview_date"), r.get("interview_type"), r.get("interview_format"),
                r.get("interviewer"), r.get("interviewer_role"), r.get("duration_minutes"),
                r.get("self_rating"), _j(r.get("what_landed")), _j(r.get("what_didnt")),
                _j(r.get("verbatim_quotes")), _j(r.get("surfaced_priorities")),
                r.get("process_details"), r.get("comp_signals"),
                _j(r.get("follow_up_commitments")), _j(r.get("tags")),
                r.get("notes"), r.get("last_updated"),
            )
            for r in rows
        ],
    )
    return len(rows)


def _rejections(cur: sqlite3.Cursor) -> int:
    rows = _read("rejections.json").get("rejections", [])
    _warn_dupes("rejections", rows)
    rows = _assign_missing_ids(rows)
    cur.executemany(
        """
        INSERT OR REPLACE INTO rejections
            (id, company, role, stage, reason, notes, date, logged_at, contact)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                r.get("id"), r.get("company", ""), r.get("role", ""),
                r.get("stage"), r.get("reason"), r.get("notes"),
                r.get("date"), r.get("logged_at"), r.get("contact"),
            )
            for r in rows
        ],
    )
    return len(rows)


def _tone_samples(cur: sqlite3.Cursor) -> int:
    rows = _read("tone_samples.json").get("samples", [])
    cur.executemany(
        """
        INSERT OR REPLACE INTO tone_samples
            (id, timestamp, source, context, text, word_count)
        VALUES (?,?,?,?,?,?)
        """,
        [
            (
                r.get("id"), r.get("timestamp"), r.get("source"),
                r.get("context"), r.get("text", ""), r.get("word_count"),
            )
            for r in rows
        ],
    )
    return len(rows)


def _health_log(cur: sqlite3.Cursor) -> int:
    rows = _read("mental_health_log.json").get("entries", [])
    cur.executemany(
        """
        INSERT INTO health_log
            (timestamp, date, mood, energy, productive, notes)
        VALUES (?,?,?,?,?,?)
        """,
        [
            (
                r.get("timestamp", ""), r.get("date", ""), r.get("mood"),
                r.get("energy"), 1 if r.get("productive") else 0, r.get("notes"),
            )
            for r in rows
        ],
    )
    return len(rows)


def _linkedin_posts(cur: sqlite3.Cursor) -> int:
    rows = _read("linkedin_posts.json").get("posts", [])
    _warn_dupes("linkedin_posts", rows)
    rows = _assign_missing_ids(rows)
    cur.executemany(
        """
        INSERT OR REPLACE INTO linkedin_posts
            (id, timestamp, posted_date, source, title, url,
             hashtags, context, links, metrics, audience_highlights)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                r.get("id"), r.get("timestamp"), r.get("posted_date"),
                r.get("source"), r.get("title"), r.get("url"),
                _j(r.get("hashtags")), r.get("context"),
                _j(r.get("links")), _j(r.get("metrics")),
                _j(r.get("audience_highlights")),
            )
            for r in rows
        ],
    )
    return len(rows)


def _personal_context(cur: sqlite3.Cursor) -> tuple[int, int]:
    data = _read("personal_context.json")

    stories = data.get("stories", [])
    _warn_dupes("stories", stories)
    cur.executemany(
        """
        INSERT OR REPLACE INTO stories
            (id, timestamp, title, story, tags, people)
        VALUES (?,?,?,?,?,?)
        """,
        [
            (
                r.get("id"), r.get("timestamp"), r.get("title", ""),
                r.get("story", ""), _j(r.get("tags")), _j(r.get("people")),
            )
            for r in stories
        ],
    )

    star = data.get("star_stories", [])
    cur.executemany(
        """
        INSERT OR REPLACE INTO star_stories
            (id, title, tags, situation, task, action, result,
             metric_bullets, framing_hints, source, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                r.get("id"), r.get("title", ""), _j(r.get("tags")),
                r.get("situation"), r.get("task"), r.get("action"),
                r.get("result"), _j(r.get("metric_bullets")),
                _j(r.get("framing_hints")), r.get("source"), r.get("notes"),
            )
            for r in star
        ],
    )

    return len(stories), len(star)


def _linkedin_connections(cur: sqlite3.Cursor) -> int:
    rows = _read("linkedin_connections.json").get("connections", [])
    cur.executemany(
        """
        INSERT INTO linkedin_connections
            (first_name, last_name, full_name, full_name_normalized,
             linkedin_url, email, company, position, connected_on, facebook_match)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                r.get("first_name"), r.get("last_name"), r.get("full_name"),
                r.get("full_name_normalized"), r.get("linkedin_url"),
                r.get("email"), r.get("company"), r.get("position"),
                r.get("connected_on"), _j(r.get("facebook_match")),
            )
            for r in rows
        ],
    )
    return len(rows)


def _contact_log(cur: sqlite3.Cursor) -> int:
    raw = _read("contact_log.json")
    rows = raw if isinstance(raw, list) else raw.get("contacts", [])
    cur.executemany(
        """
        INSERT INTO contact_log
            (name, role, source, context, date, impressions, reply, notes)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        [
            (
                r.get("name"), r.get("role"), r.get("source"), r.get("context"),
                r.get("date"), r.get("impressions"),
                1 if r.get("reply") else 0, r.get("notes"),
            )
            for r in rows
        ],
    )
    return len(rows)


def _contact_crossref(cur: sqlite3.Cursor) -> int:
    rows = _read("contact_crossref.json").get("contacts", [])
    cur.executemany(
        """
        INSERT INTO contact_crossref
            (canonical_name, normalized, platforms, platform_count, signals, action_hints)
        VALUES (?,?,?,?,?,?)
        """,
        [
            (
                r.get("canonical_name", ""), r.get("normalized"),
                _j(r.get("platforms")), r.get("platform_count"),
                _j(r.get("signals")), _j(r.get("action_hints")),
            )
            for r in rows
        ],
    )
    return len(rows)


# ── Main ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print(f"\n🗄  SQLite migration")
    print(f"   Source : {DATA_DIR}")
    print(f"   Target : {DB_PATH}\n")

    if DB_PATH.exists():
        DB_PATH.unlink()
        print("   Removed existing database.")

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(_SCHEMA)
    con.commit()
    print("   Schema applied.\n")

    totals: dict[str, int] = {}

    with con:
        cur = con.cursor()

        n_apps, n_ev = _applications(cur)
        totals["applications"] = n_apps
        totals["application_events"] = n_ev
        print(f"  ✓  applications         {n_apps:>5}  ({n_ev} events)")

        n = _job_queue(cur)
        totals["job_queue"] = n
        print(f"  ✓  job_queue            {n:>5}")

        n = _people(cur)
        totals["people"] = n
        print(f"  ✓  people               {n:>5}")

        n = _interviews(cur)
        totals["interviews"] = n
        print(f"  ✓  interviews           {n:>5}")

        n = _rejections(cur)
        totals["rejections"] = n
        print(f"  ✓  rejections           {n:>5}")

        n = _tone_samples(cur)
        totals["tone_samples"] = n
        print(f"  ✓  tone_samples         {n:>5}")

        n = _health_log(cur)
        totals["health_log"] = n
        print(f"  ✓  health_log           {n:>5}")

        n = _linkedin_posts(cur)
        totals["linkedin_posts"] = n
        print(f"  ✓  linkedin_posts       {n:>5}")

        n_st, n_ss = _personal_context(cur)
        totals["stories"] = n_st
        totals["star_stories"] = n_ss
        print(f"  ✓  stories              {n_st:>5}  ({n_ss} star_stories)")

        n = _linkedin_connections(cur)
        totals["linkedin_connections"] = n
        print(f"  ✓  linkedin_connections {n:>5}")

        n = _contact_log(cur)
        totals["contact_log"] = n
        print(f"  ✓  contact_log          {n:>5}")

        n = _contact_crossref(cur)
        totals["contact_crossref"] = n
        print(f"  ✓  contact_crossref     {n:>5}")

    size_kb = DB_PATH.stat().st_size // 1024
    total_rows = sum(totals.values())
    con.close()
    print(f"\n✅  Done — {total_rows} rows, {size_kb} KB  →  {DB_PATH.name}\n")


if __name__ == "__main__":
    run()
