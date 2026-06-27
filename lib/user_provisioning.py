"""Provision a fresh per-user data directory on first login.

Called once per user when they first authenticate.  Subsequent calls are
no-ops (idempotent — guarded by data_dir.exists()).

Creates:
    <data_dir>/                 — user data root under DATA_FOLDER/users/{oid}/
    <data_dir>/jobcontextmcp.db — blank SQLite DB with the full app schema
    <data_dir>/workspace/       — workspace directory tree (empty, ready for blob sync)

The DDL here must be kept in sync with scripts/migrate_to_sqlite.py (_SCHEMA).
Uses IF NOT EXISTS throughout so re-running against an existing DB is safe.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

_log = logging.getLogger(__name__)

# ── Schema DDL ─────────────────────────────────────────────────────────────────
# Must stay in sync with scripts/migrate_to_sqlite.py.
# Uses IF NOT EXISTS so applying to an existing DB is idempotent.
_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS applications (
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
    comp         TEXT
);

CREATE TABLE IF NOT EXISTS application_events (
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
    raw_type       TEXT,
    notes          TEXT,
    date           TEXT
);

CREATE TABLE IF NOT EXISTS job_queue (
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
    decided_date    TEXT
);

CREATE TABLE IF NOT EXISTS people (
    id              INTEGER PRIMARY KEY,
    timestamp       TEXT,
    name            TEXT    NOT NULL,
    relationship    TEXT,
    company         TEXT,
    context         TEXT,
    tags            TEXT,
    contact_info    TEXT,
    outreach_status TEXT,
    notes           TEXT,
    last_updated    TEXT
);

CREATE TABLE IF NOT EXISTS interviews (
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
    what_landed           TEXT,
    what_didnt            TEXT,
    verbatim_quotes       TEXT,
    surfaced_priorities   TEXT,
    process_details       TEXT,
    comp_signals          TEXT,
    follow_up_commitments TEXT,
    tags                  TEXT,
    notes                 TEXT,
    last_updated          TEXT
);

CREATE TABLE IF NOT EXISTS rejections (
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

CREATE TABLE IF NOT EXISTS tone_samples (
    id         INTEGER PRIMARY KEY,
    timestamp  TEXT,
    source     TEXT,
    context    TEXT,
    text       TEXT    NOT NULL,
    word_count INTEGER
);

CREATE TABLE IF NOT EXISTS health_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  TEXT    NOT NULL,
    date       TEXT    NOT NULL,
    mood       TEXT,
    energy     INTEGER,
    productive INTEGER,
    notes      TEXT
);

CREATE TABLE IF NOT EXISTS linkedin_posts (
    id                  INTEGER PRIMARY KEY,
    timestamp           TEXT,
    posted_date         TEXT,
    source              TEXT,
    title               TEXT,
    url                 TEXT,
    hashtags            TEXT,
    context             TEXT,
    links               TEXT,
    metrics             TEXT,
    audience_highlights TEXT
);

CREATE TABLE IF NOT EXISTS stories (
    id        INTEGER PRIMARY KEY,
    timestamp TEXT,
    title     TEXT    NOT NULL,
    story     TEXT    NOT NULL,
    tags      TEXT,
    people    TEXT
);

CREATE TABLE IF NOT EXISTS star_stories (
    id             TEXT    PRIMARY KEY,
    title          TEXT    NOT NULL,
    tags           TEXT,
    situation      TEXT,
    task           TEXT,
    action         TEXT,
    result         TEXT,
    metric_bullets TEXT,
    framing_hints  TEXT,
    source         TEXT,
    notes          TEXT
);

CREATE TABLE IF NOT EXISTS linkedin_connections (
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
    facebook_match       TEXT
);

CREATE TABLE IF NOT EXISTS contact_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT,
    role        TEXT,
    source      TEXT,
    context     TEXT,
    date        TEXT,
    impressions INTEGER,
    reply       INTEGER,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS contact_crossref (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT    NOT NULL,
    normalized     TEXT,
    platforms      TEXT,
    platform_count INTEGER,
    signals        TEXT,
    action_hints   TEXT
);
"""

_STARTER_CONFIG: dict = {
    "contact": {
        "name":     "",
        "phone":    "",
        "city":     "",
        "email":    "",
        "linkedin": "",
        "github":   "",
    }
}

_WORKSPACE_SUBDIRS = [
    "workspace/01-Current-Optimized",
    "workspace/02-Cover-Letters",
    "workspace/03-Resume-PDFs",
    "workspace/04-Archived-Resumes",
    "workspace/05-Research",
    "workspace/06-Reference-Materials",
    "workspace/07-Job-Assessments",
    "workspace/08-Interview-Prep-Docs",
    "workspace/09-Cover-Letter-PDFs",
    "workspace/leetcode",
    "personas",
]

# Placeholder master resume written on first provision.
# The workspace setup flow (via chat) will overwrite this with the real content.
_PLACEHOLDER_RESUME = """\
NEW USER — RESUME NOT YET CONFIGURED
======================================

This is a placeholder. To set up your resume:
  1. Start a chat with the jobContextMCP assistant.
  2. Say: "Let's set up my workspace. Here is my resume:"
  3. Paste your resume text.

The assistant will guide you through the full workspace setup:
  - Master resume
  - Tone samples
  - Personal context & STAR stories
  - LinkedIn posts
  - Interview history

NAME:       [Your Full Name]
LOCATION:   [City, State]
EMAIL:      [your@email.com]
LINKEDIN:   [linkedin.com/in/yourprofile]

SUMMARY
-------
[Add your professional summary here]

EXPERIENCE
----------
[Add your work history here]

SKILLS
------
[Add your skills here]

EDUCATION
---------
[Add your education here]
"""


def provision_user_data(data_dir: Path) -> None:
    """Ensure the per-user data folder and all required seed files exist.

    File-level idempotent — creates any missing files/directories even when
    data_dir already exists.  Safe to call on every authenticated request;
    the hot path (everything present) is just a stat() on data_dir.
    Thread/process safe because mkdir(exist_ok=True) is atomic on POSIX.
    """
    import json as _json
    import shutil

    needs_full_log = not data_dir.exists()
    if needs_full_log:
        _log.info("Provisioning new user data dir: %s", data_dir)

    # Directory tree
    data_dir.mkdir(parents=True, exist_ok=True)
    for sub in _WORKSPACE_SUBDIRS:
        (data_dir / sub).mkdir(parents=True, exist_ok=True)

    # Starter config.json — empty contact block so get_contact_info() has a
    # real dict to read.  Never overwrites an existing config.json.
    config_path = data_dir / "config.json"
    if not config_path.exists():
        config_path.write_text(
            _json.dumps(_STARTER_CONFIG, indent=2), encoding="utf-8"
        )
        _log.info("Seeded starter config.json at %s", config_path)

    # Placeholder master resume — gives tools something to read on first login.
    # Overwritten when user completes workspace setup via chat.
    resume_file = data_dir / "workspace" / "01-Current-Optimized" / "Resume - MASTER SOURCE.txt"
    if not resume_file.exists():
        resume_file.write_text(_PLACEHOLDER_RESUME, encoding="utf-8")

    # Seed all *.example.json files from the global DATA_FOLDER root into the
    # user's data dir.  Strip the ".example" suffix so tools find the files by
    # their normal names (status.json, people.json, etc.).  This gives every new
    # user a valid empty-but-parseable JSON file for each data type, preventing
    # silent fallback to another user's data.
    global_data_dir = data_dir.parent.parent  # DATA_FOLDER/users/{oid} → DATA_FOLDER
    for example_file in sorted(global_data_dir.glob("*.example.json")):
        dest = data_dir / example_file.name.replace(".example.json", ".json")
        if not dest.exists():
            shutil.copy2(example_file, dest)
            _log.debug("Seeded %s → %s", example_file.name, dest)

    # Blank SQLite DB with full schema — executescript with IF NOT EXISTS is safe
    # to run against an existing DB (adds any missing tables, no data loss).
    (data_dir / "db").mkdir(parents=True, exist_ok=True)
    db_file = data_dir / "db" / "jobcontextmcp.db"
    con = sqlite3.connect(str(db_file))
    try:
        con.executescript(_SCHEMA_SQL)
        con.commit()
    finally:
        con.close()

    if needs_full_log:
        _log.info("User data provisioned at %s", data_dir)
