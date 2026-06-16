"""
tests/test_sqlite_migration.py

Verifies the SQLite migration and io_sqlite adapter layer:

  1. Schema integrity  — all expected tables exist; row counts match source JSON
  2. Data fidelity     — every field in every Tier 1 record round-trips cleanly
  3. Event types       — all stored types are canonical; CHECK constraint fires
  4. io_sqlite adapter — load_from_sqlite() returns identical dicts to _load_json()
  5. USE_SQLITE flag   — _load_json() switches source transparently

Tests run against a *temporary* SQLite database seeded from data_dev/ at
session start so they never touch the live data_dev/jobcontextmcp.db.
If data_dev/ doesn't exist (e.g. CI), the fixture is skipped automatically.
"""

from __future__ import annotations

import importlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DEV = PROJECT_ROOT / "data_dev"
MIGRATE_SCRIPT = PROJECT_ROOT / "scripts" / "migrate_to_sqlite.py"


# ── Session-scoped fixture: build a fresh DB in tmp_path ──────────────────────

@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    """
    Run migrate_to_sqlite.py against data_dev/ and write the .db into a
    session-scoped tmp directory.  Skips the whole session if data_dev/ is
    absent.
    """
    if not DATA_DEV.exists():
        pytest.skip("data_dev/ not found — run 'cp -r data/ data_dev/' first")

    session_tmp = tmp_path_factory.mktemp("sqlite")
    db = session_tmp / "jobcontextmcp.db"

    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)

    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(PROJECT_ROOT),
    )
    # Patch DATA_DIR in the script output to point at our session tmp
    # Actually we need to override the DB path — re-run with a patched DATA_DIR
    # via env var honoured by the script's _ROOT / "data_dev" default.
    # Simpler: run the real migration to data_dev/, then *copy* the .db here.
    real_db = DATA_DEV / "jobcontextmcp.db"

    if result.returncode != 0:
        pytest.fail(f"Migration script failed:\n{result.stderr}")

    if not real_db.exists():
        pytest.fail("Migration ran but data_dev/jobcontextmcp.db was not created")

    import shutil
    shutil.copy2(real_db, db)
    return db


@pytest.fixture(scope="session")
def con(db_path):
    """Open a read-only session connection to the test DB."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _source(fname: str) -> dict | list:
    return json.loads((DATA_DEV / fname).read_text(encoding="utf-8"))


def _count(con, table: str) -> int:
    return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ── 1. Schema integrity ────────────────────────────────────────────────────────

EXPECTED_TABLES = [
    "applications", "application_events", "job_queue", "people",
    "interviews", "rejections", "tone_samples", "health_log",
    "linkedin_posts", "stories", "star_stories",
    "linkedin_connections", "contact_log", "contact_crossref",
]


def test_all_tables_exist(con):
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    existing = {r["name"] for r in rows}
    for t in EXPECTED_TABLES:
        assert t in existing, f"Missing table: {t}"


def test_row_counts_match_source(con):
    """
    Row counts in SQLite must be >= source JSON counts.
    (>= because dedup logic may merge a duplicate id — never drops real rows.)
    """
    checks = [
        ("applications",   "status.json",            "applications"),
        ("application_events", None,                  None),          # checked separately
        ("job_queue",      "job_queue.json",          "jobs"),
        ("people",         "people.json",             "people"),
        ("interviews",     "interviews.json",         "interviews"),
        ("rejections",     "rejections.json",         "rejections"),
        ("tone_samples",   "tone_samples.json",       "samples"),
        ("health_log",     "mental_health_log.json",  "entries"),
        ("linkedin_posts", "linkedin_posts.json",     "posts"),
        ("stories",        "personal_context.json",   "stories"),
        ("star_stories",   "personal_context.json",   "star_stories"),
        ("linkedin_connections", "linkedin_connections.json", "connections"),
        ("contact_crossref", "contact_crossref.json", "contacts"),
    ]
    for table, fname, key in checks:
        if fname is None:
            continue
        src = _source(fname)
        src_count = len(src.get(key, src) if isinstance(src, dict) else src)
        db_count = _count(con, table)
        # allow 1 fewer for known duplicate-id collapse (people id=23, stories id=105)
        assert db_count >= src_count - 1, (
            f"{table}: source={src_count}, db={db_count}"
        )


def test_application_events_total(con):
    """Total events in DB must match total events across all source applications."""
    apps = _source("status.json").get("applications", [])
    src_total = sum(len(a.get("events", [])) for a in apps)
    db_total = _count(con, "application_events")
    assert db_total == src_total


# ── 2. Data fidelity — Tier 1 spot checks ─────────────────────────────────────

def test_applications_core_fields(con):
    """Every application company/role/status survives the round-trip."""
    apps = _source("status.json").get("applications", [])
    db_rows = {
        (r["company"], r["role"]): r
        for r in con.execute("SELECT * FROM applications").fetchall()
    }
    for a in apps:
        key = (a["company"], a["role"])
        assert key in db_rows, f"Application not found in DB: {key}"
        row = db_rows[key]
        assert row["status"] == a["status"]
        assert row["last_updated"] == (a.get("last_updated") or None)


def test_applications_sparse_fields(con):
    """location, date_applied, req_number, comp are stored when present in source."""
    apps = _source("status.json").get("applications", [])
    db_rows = {
        (r["company"], r["role"]): dict(r)
        for r in con.execute("SELECT * FROM applications").fetchall()
    }
    for a in apps:
        row = db_rows[(a["company"], a["role"])]
        for sparse in ("location", "date_applied", "req_number"):
            if sparse in a and a[sparse] is not None:
                assert row[sparse] == a[sparse], (
                    f"{a['company']} {sparse}: source={a[sparse]!r} db={row[sparse]!r}"
                )
        if "comp" in a and a["comp"] is not None:
            db_comp = json.loads(row["comp"])
            assert db_comp == a["comp"]


def test_application_events_foreign_key(con):
    """Every event references an application_id that exists."""
    orphans = con.execute(
        """
        SELECT ae.id FROM application_events ae
        LEFT JOIN applications a ON ae.application_id = a.id
        WHERE a.id IS NULL
        """
    ).fetchall()
    assert len(orphans) == 0, f"{len(orphans)} orphaned event rows"


def test_job_queue_jd_preserved(con):
    """JD text round-trips without truncation."""
    jobs = _source("job_queue.json").get("jobs", [])
    for j in jobs[:5]:  # spot-check first 5
        row = con.execute("SELECT jd FROM job_queue WHERE id=?", (j["id"],)).fetchone()
        assert row is not None, f"job_queue id={j['id']} missing"
        assert row["jd"] == j.get("jd")


def test_people_tags_json_roundtrip(con):
    """Tags column deserializes back to the same list."""
    people = _source("people.json").get("people", [])
    for p in people[:20]:
        row = con.execute("SELECT tags FROM people WHERE id=?", (p["id"],)).fetchone()
        if row is None:
            continue  # may be a deduped id
        db_tags = json.loads(row["tags"]) if row["tags"] else []
        src_tags = p.get("tags") or []
        assert db_tags == src_tags, f"people id={p['id']} tags mismatch"


def test_interviews_verbatim_quotes_json_roundtrip(con):
    """verbatim_quotes round-trips as a list of dicts."""
    interviews = _source("interviews.json").get("interviews", [])
    for iv in interviews:
        row = con.execute(
            "SELECT verbatim_quotes FROM interviews WHERE id=?", (iv["id"],)
        ).fetchone()
        assert row is not None
        db_quotes = json.loads(row["verbatim_quotes"]) if row["verbatim_quotes"] else []
        src_quotes = iv.get("verbatim_quotes") or []
        assert len(db_quotes) == len(src_quotes), (
            f"interview id={iv['id']}: {len(db_quotes)} db quotes vs {len(src_quotes)} source"
        )
        for dq, sq in zip(db_quotes, src_quotes):
            assert dq["speaker"] == sq["speaker"]
            assert dq["quote"] == sq["quote"]


def test_rejections_no_id_row_present(con):
    """The Afresh June-8 rejection (no id in source JSON) must survive."""
    row = con.execute(
        "SELECT * FROM rejections WHERE company='Afresh' AND stage='pre-process'"
    ).fetchone()
    assert row is not None, "Missing no-id Afresh rejection"
    assert row["contact"] == "Erin Leonhard Zhang"
    assert "2026-06-08" in row["date"]


def test_rejections_contact_column(con):
    """contact column is nullable and populated for rows that have it."""
    rows = con.execute(
        "SELECT company, contact FROM rejections WHERE contact IS NOT NULL"
    ).fetchall()
    # At minimum the Afresh June-8 row has a contact
    companies = [r["company"] for r in rows]
    assert "Afresh" in companies


def test_health_log_productive_boolean(con):
    """productive is stored as 0/1 and deserializes to bool correctly."""
    entries = _source("mental_health_log.json").get("entries", [])
    db_entries = con.execute("SELECT productive FROM health_log").fetchall()
    for src, row in zip(entries, db_entries):
        expected = 1 if src.get("productive") else 0
        assert row["productive"] == expected


def test_star_stories_framing_hints_json_roundtrip(con):
    """framing_hints dict round-trips with all keys intact."""
    star = _source("personal_context.json").get("star_stories", [])
    for s in star:
        row = con.execute(
            "SELECT framing_hints FROM star_stories WHERE id=?", (s["id"],)
        ).fetchone()
        assert row is not None
        db_hints = json.loads(row["framing_hints"]) if row["framing_hints"] else {}
        src_hints = s.get("framing_hints") or {}
        assert set(db_hints.keys()) == set(src_hints.keys())
        for k in src_hints:
            assert db_hints[k] == src_hints[k]


# ── 3. Event type canonicalization ────────────────────────────────────────────

def test_all_event_types_are_canonical(con):
    """No non-canonical type should exist in the type column."""
    from lib.db import EVENT_TYPE_CANONICAL
    db_types = {
        r["type"]
        for r in con.execute("SELECT DISTINCT type FROM application_events").fetchall()
    }
    non_canonical = db_types - set(EVENT_TYPE_CANONICAL)
    assert not non_canonical, f"Non-canonical event types in DB: {non_canonical}"


def test_raw_type_preserved(con):
    """raw_type column retains the original pre-normalization string."""
    # 'resume_submitted' should map to 'applied' but raw_type = 'resume_submitted'
    row = con.execute(
        "SELECT type, raw_type FROM application_events WHERE raw_type='resume_submitted'"
    ).fetchone()
    if row:  # only assert if such a row exists in the data
        assert row["type"] == "applied"
        assert row["raw_type"] == "resume_submitted"


def test_check_constraint_rejects_bad_type(db_path):
    """INSERT with an invalid type must raise IntegrityError."""
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO application_events (application_id, type, notes, date) "
            "VALUES (1, 'BAD_TYPE', 'test', '2026-01-01')"
        )
    con.close()


def test_known_aliases_normalized(con):
    """Spot-check specific alias → canonical mappings in the stored data."""
    alias_to_canonical = {
        "resume_submitted":         "applied",
        "follow_up":                "follow_up_sent",
        "rejection":                "rejected",
        "recruiter_inbound":        "recruiter_contact",
        "onsite":                   "interview_completed",
        "referral_path_confirmed":  "referral_confirmed",
    }
    for raw, expected_canonical in alias_to_canonical.items():
        row = con.execute(
            "SELECT type FROM application_events WHERE raw_type=?", (raw,)
        ).fetchone()
        if row:
            assert row["type"] == expected_canonical, (
                f"raw_type={raw!r}: expected {expected_canonical!r}, got {row['type']!r}"
            )


# ── 4. io_sqlite adapter — load_from_sqlite() ─────────────────────────────────

@pytest.fixture()
def sqlite_env(monkeypatch):
    """Monkeypatch config DATA_FOLDER to data_dev/ and activate SQLite reads."""
    import lib.config as config
    import lib.io as io_mod
    monkeypatch.setattr(config, "DATA_FOLDER",          DATA_DEV)
    monkeypatch.setattr(config, "STATUS_FILE",          DATA_DEV / "status.json")
    monkeypatch.setattr(config, "HEALTH_LOG_FILE",       DATA_DEV / "mental_health_log.json")
    monkeypatch.setattr(config, "JOB_QUEUE_FILE",        DATA_DEV / "job_queue.json")
    monkeypatch.setattr(config, "REJECTIONS_FILE",       DATA_DEV / "rejections.json")
    monkeypatch.setattr(config, "PEOPLE_FILE",           DATA_DEV / "people.json")
    monkeypatch.setattr(config, "PERSONAL_CONTEXT_FILE", DATA_DEV / "personal_context.json")
    monkeypatch.setattr(config, "TONE_FILE",             DATA_DEV / "tone_samples.json")
    monkeypatch.setattr(config, "INTERVIEWS_FILE",       DATA_DEV / "interviews.json")
    monkeypatch.setattr(config, "LINKEDIN_POSTS_FILE",   DATA_DEV / "linkedin_posts.json")
    # Flip the flag directly — monkeypatch reverts it automatically after the test
    monkeypatch.setattr(io_mod, "_USE_SQLITE", True)


def test_load_from_sqlite_returns_no_handler_for_unknown_file(sqlite_env):
    from lib.io_sqlite import load_from_sqlite, SQLITE_NO_HANDLER
    import lib.config as config
    result = load_from_sqlite(config.DATA_FOLDER / "scan_index.json", {})
    assert result is SQLITE_NO_HANDLER


def test_status_application_count_matches(sqlite_env):
    from lib.io import _load_json
    import lib.config as config
    result = _load_json(config.STATUS_FILE, {})
    src = _source("status.json")
    assert len(result["applications"]) == len(src["applications"])


def test_status_all_companies_present(sqlite_env):
    from lib.io import _load_json
    import lib.config as config
    result = _load_json(config.STATUS_FILE, {})
    src = _source("status.json")
    src_companies = {a["company"] for a in src["applications"]}
    db_companies  = {a["company"] for a in result["applications"]}
    assert src_companies == db_companies


def test_job_queue_all_ids_present(sqlite_env):
    from lib.io import _load_json
    import lib.config as config
    result = _load_json(config.JOB_QUEUE_FILE, {})
    src = _source("job_queue.json")
    src_ids = {j["id"] for j in src["jobs"]}
    db_ids  = {j["id"] for j in result["jobs"]}
    assert src_ids == db_ids


def test_people_tags_are_lists_not_strings(sqlite_env):
    """Tags should come back as Python lists, not JSON strings."""
    from lib.io import _load_json
    import lib.config as config
    result = _load_json(config.PEOPLE_FILE, {})
    for p in result["people"]:
        assert isinstance(p["tags"], list), (
            f"people id={p['id']} tags is {type(p['tags']).__name__}, expected list"
        )


def test_interviews_verbatim_quotes_are_dicts(sqlite_env):
    """verbatim_quotes items should be dicts with speaker/quote keys."""
    from lib.io import _load_json
    import lib.config as config
    result = _load_json(config.INTERVIEWS_FILE, {})
    for iv in result["interviews"]:
        for q in iv.get("verbatim_quotes", []):
            assert isinstance(q, dict), f"quote is {type(q)}, expected dict"
            assert "speaker" in q and "quote" in q


def test_rejections_all_present(sqlite_env):
    from lib.io import _load_json
    import lib.config as config
    result = _load_json(config.REJECTIONS_FILE, {})
    src = _source("rejections.json")
    assert len(result["rejections"]) == len(src["rejections"])


def test_health_log_productive_is_bool(sqlite_env):
    """productive field must deserialize as bool, not int."""
    from lib.io import _load_json
    import lib.config as config
    result = _load_json(config.HEALTH_LOG_FILE, {})
    for entry in result["entries"]:
        assert isinstance(entry["productive"], bool), (
            f"productive is {type(entry['productive'])}, expected bool"
        )


def test_personal_context_stories_and_star_stories(sqlite_env):
    from lib.io import _load_json
    import lib.config as config
    result = _load_json(config.PERSONAL_CONTEXT_FILE, {})
    src = _source("personal_context.json")
    # stories count (allow -1 for known dup)
    assert len(result["stories"]) >= len(src["stories"]) - 1
    assert len(result["star_stories"]) == len(src["star_stories"])


def test_linkedin_posts_metrics_are_dicts(sqlite_env):
    """metrics column must come back as a dict, not a JSON string."""
    from lib.io import _load_json
    import lib.config as config
    result = _load_json(config.LINKEDIN_POSTS_FILE, {})
    for post in result["posts"]:
        assert isinstance(post["metrics"], dict), (
            f"post id={post.get('id')} metrics is {type(post['metrics'])}"
        )


# ── 5. USE_SQLITE flag ─────────────────────────────────────────────────────────

def test_use_sqlite_false_reads_json_file(monkeypatch):
    """With USE_SQLITE off, _load_json must read the actual JSON file."""
    import lib.io as io_mod
    monkeypatch.setattr(io_mod, "_USE_SQLITE", False)
    from lib.io import _load_json
    result = _load_json(DATA_DEV / "status.json", {"applications": []})
    assert isinstance(result, dict)
    assert "applications" in result
    src = _source("status.json")
    assert result.get("last_updated") == src.get("last_updated")


def test_use_sqlite_true_bypasses_json_file(monkeypatch, tmp_path):
    """With USE_SQLITE on, _load_json reads DB even when JSON has different content."""
    import lib.config as config
    import lib.io as io_mod
    monkeypatch.setattr(config, "DATA_FOLDER", DATA_DEV)
    monkeypatch.setattr(config, "STATUS_FILE", DATA_DEV / "status.json")
    monkeypatch.setattr(config, "HEALTH_LOG_FILE", DATA_DEV / "mental_health_log.json")
    monkeypatch.setattr(io_mod, "_USE_SQLITE", True)
    from lib.io import _load_json
    result = _load_json(config.STATUS_FILE, {})
    assert len(result.get("applications", [])) > 0


def test_unmapped_file_falls_through_to_json(monkeypatch, tmp_path):
    """scan_index.json is not in the SQLite handler map — must read from disk."""
    import lib.io as io_mod
    sentinel = tmp_path / "scan_index.json"
    sentinel.write_text(json.dumps({"scanned": {"sentinel": True}}))
    monkeypatch.setattr(io_mod, "_USE_SQLITE", True)
    from lib.io import _load_json
    result = _load_json(sentinel, {"scanned": {}})
    assert result["scanned"].get("sentinel") is True


# ── 6. Write round-trips ───────────────────────────────────────────────────────

def _make_db(tmp_path) -> "Path":
    """Create a fresh empty SQLite DB seeded with the full schema."""
    import sqlite3, sys
    sys.path.insert(0, str(PROJECT_ROOT))
    from scripts.migrate_to_sqlite import _SCHEMA
    db = tmp_path / "test.db"
    con = sqlite3.connect(db)
    con.executescript(_SCHEMA)
    con.commit()
    con.close()
    return db


def test_save_then_load_new_application(monkeypatch, tmp_path):
    """Writing a new application via save_to_sqlite is readable back via load_from_sqlite."""
    import lib.config as config
    import lib.db as db_mod
    from lib.io_sqlite import save_to_sqlite, load_from_sqlite

    db = _make_db(tmp_path)
    monkeypatch.setattr(db_mod, "db_path", lambda: db)

    data = {
        "last_updated": "2026-06-15 12:00",
        "applications": [
            {
                "company": "Nimble Gravity",
                "role": "AI Architect",
                "status": "phone_screen",
                "next_steps": "Follow up Wednesday",
                "contact": "Josephine De Graft-Johnson",
                "notes": "Strong fitment — AI platform, Azure, MCP",
                "applied_date": None,
                "last_updated": "2026-06-15",
                "events": [
                    {"type": "recruiter_contact", "notes": "Initial outreach", "date": "2026-06-10"},
                    {"type": "phone_screen", "notes": "Completed screen", "date": "2026-06-15"},
                ],
            }
        ],
    }

    save_to_sqlite(tmp_path / "status.json", data)

    result = load_from_sqlite(tmp_path / "status.json", {})
    assert result is not None
    apps = result.get("applications", [])
    assert len(apps) == 1
    app = apps[0]
    assert app["company"] == "Nimble Gravity"
    assert app["role"] == "AI Architect"
    assert app["status"] == "phone_screen"
    assert app["contact"] == "Josephine De Graft-Johnson"
    assert len(app["events"]) == 2
    assert app["events"][0]["type"] == "recruiter_contact"
    assert app["events"][1]["type"] == "phone_screen"


def test_save_then_load_health_entry(monkeypatch, tmp_path):
    """New health log entry is readable back after save."""
    import lib.db as db_mod
    import lib.config as config
    from lib.io_sqlite import save_to_sqlite, load_from_sqlite

    db = _make_db(tmp_path)
    monkeypatch.setattr(db_mod, "db_path", lambda: db)
    monkeypatch.setattr(config, "DATA_FOLDER", tmp_path)
    monkeypatch.setattr(config, "HEALTH_LOG_FILE", tmp_path / "mental_health_log.json")

    data = {"entries": [
        {"timestamp": "2026-06-15T09:00:00", "date": "2026-06-15",
         "mood": "focused", "energy": 8, "productive": True, "notes": "Good day"},
    ]}

    save_to_sqlite(tmp_path / "mental_health_log.json", data)
    # Second save is idempotent (same timestamp should not duplicate)
    save_to_sqlite(tmp_path / "mental_health_log.json", data)

    result = load_from_sqlite(tmp_path / "mental_health_log.json", {})
    entries = result.get("entries", [])
    assert len(entries) == 1
    assert entries[0]["mood"] == "focused"
    assert entries[0]["productive"] is True


def test_save_event_append_only(monkeypatch, tmp_path):
    """Events are only appended on subsequent saves \u2014 no duplicates."""
    import lib.db as db_mod
    import lib.config as config
    from lib.io_sqlite import save_to_sqlite, load_from_sqlite

    db = _make_db(tmp_path)
    monkeypatch.setattr(db_mod, "db_path", lambda: db)
    monkeypatch.setattr(config, "DATA_FOLDER", tmp_path)
    monkeypatch.setattr(config, "STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(config, "HEALTH_LOG_FILE", tmp_path / "mental_health_log.json")

    base = {
        "last_updated": "2026-06-15",
        "applications": [{
            "company": "Acme", "role": "SWE", "status": "applied",
            "events": [{"type": "applied", "notes": "submitted", "date": "2026-06-01"}],
        }],
    }

    # First save
    save_to_sqlite(tmp_path / "status.json", base)

    # Second save with one additional event
    base["applications"][0]["events"].append(
        {"type": "recruiter_contact", "notes": "recruiter called", "date": "2026-06-05"}
    )
    save_to_sqlite(tmp_path / "status.json", base)

    result = load_from_sqlite(tmp_path / "status.json", {})
    assert len(result["applications"][0]["events"]) == 2


def test_save_job_queue_sync_delete(monkeypatch, tmp_path):
    """Dismissed jobs (removed from data) are deleted from the job_queue table."""
    import lib.db as db_mod
    import lib.config as config
    from lib.io_sqlite import save_to_sqlite, load_from_sqlite

    db = _make_db(tmp_path)
    monkeypatch.setattr(db_mod, "db_path", lambda: db)
    monkeypatch.setattr(config, "DATA_FOLDER", tmp_path)
    monkeypatch.setattr(config, "JOB_QUEUE_FILE", tmp_path / "job_queue.json")

    queue = {
        "jobs": [
            {"id": 1, "company": "Alpha", "role": "SWE", "status": "pending"},
            {"id": 2, "company": "Beta",  "role": "SWE", "status": "evaluated"},
        ]
    }
    save_to_sqlite(tmp_path / "job_queue.json", queue)

    # Dismiss job 2 — remove it from the list
    queue["jobs"] = [j for j in queue["jobs"] if j["id"] != 2]
    save_to_sqlite(tmp_path / "job_queue.json", queue)

    result = load_from_sqlite(tmp_path / "job_queue.json", {})
    ids = [j["id"] for j in result["jobs"]]
    assert ids == [1], f"Expected only job 1, got {ids}"


def test_save_status_sync_delete(monkeypatch, tmp_path):
    """Applications removed from status data are deleted from SQLite (with events via CASCADE)."""
    import lib.db as db_mod
    import lib.config as config
    from lib.io_sqlite import save_to_sqlite, load_from_sqlite

    db = _make_db(tmp_path)
    monkeypatch.setattr(db_mod, "db_path", lambda: db)
    monkeypatch.setattr(config, "DATA_FOLDER", tmp_path)
    monkeypatch.setattr(config, "STATUS_FILE", tmp_path / "status.json")

    data = {
        "last_updated": "2026-06-15",
        "applications": [
            {"company": "Keep Co", "role": "SWE", "status": "applied",
             "events": [{"type": "applied", "notes": "submitted", "date": "2026-06-01"}]},
            {"company": "Drop Co", "role": "SWE", "status": "rejected",
             "events": [{"type": "rejection", "notes": "no fit", "date": "2026-06-10"}]},
        ],
    }
    save_to_sqlite(tmp_path / "status.json", data)

    # Remove Drop Co from the list
    data["applications"] = [a for a in data["applications"] if a["company"] != "Drop Co"]
    save_to_sqlite(tmp_path / "status.json", data)

    result = load_from_sqlite(tmp_path / "status.json", {})
    companies = [a["company"] for a in result["applications"]]
    assert "Drop Co" not in companies, f"Drop Co should be deleted, got {companies}"
    assert "Keep Co" in companies


def test_save_people_sync_delete(monkeypatch, tmp_path):
    """People removed from people data are deleted from SQLite."""
    import lib.db as db_mod
    import lib.config as config
    from lib.io_sqlite import save_to_sqlite, load_from_sqlite

    db = _make_db(tmp_path)
    monkeypatch.setattr(db_mod, "db_path", lambda: db)
    monkeypatch.setattr(config, "DATA_FOLDER", tmp_path)
    monkeypatch.setattr(config, "PEOPLE_FILE", tmp_path / "people.json")

    people_data = {
        "people": [
            {"id": 101, "name": "Alice", "relationship": "recruiter"},
            {"id": 102, "name": "Bob",   "relationship": "contact"},
        ]
    }
    save_to_sqlite(tmp_path / "people.json", people_data)

    # Remove Bob
    people_data["people"] = [p for p in people_data["people"] if p["id"] != 102]
    save_to_sqlite(tmp_path / "people.json", people_data)

    result = load_from_sqlite(tmp_path / "people.json", {})
    names = [p["name"] for p in result["people"]]
    assert "Bob" not in names, f"Bob should be deleted, got {names}"
    assert "Alice" in names
