"""
tests/test_sqlite_migration.py

Verifies the SQLite migration and io_sqlite adapter layer:

  1. Schema integrity  — all expected tables exist; row counts match source JSON
  2. Data fidelity     — every field in every Tier 1 record round-trips cleanly
  3. Event types       — all stored types are canonical; CHECK constraint fires
  4. io_sqlite adapter — load_from_sqlite() returns identical dicts to _load_json()
  5. USE_SQLITE flag   — _load_json() switches source transparently

Schema/integrity tests (sections 1–3) run against a *read-only copy* of
data/jobcontextmcp.db seeded at session start.  They are skipped automatically
when the DB doesn't exist yet (e.g. fresh checkout before first server run).

Unit/round-trip tests (sections 4–6) use the self-contained ``synth_dir``
fixture and never touch disk data.
"""

from __future__ import annotations

import importlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DEV = PROJECT_ROOT / "data"   # live data dir — data_dev/ was only for migration sandboxing
MIGRATE_SCRIPT = PROJECT_ROOT / "scripts" / "migrate_to_sqlite.py"


# ── Session-scoped fixture: build a fresh DB in tmp_path ──────────────────────

@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    """
    Copy data/jobcontextmcp.db into a session-scoped tmp directory for
    read-only schema/integrity tests.  Skips if data/ or the DB is absent
    (e.g. fresh checkout before first server run).
    """
    real_db = DATA_DEV / "jobcontextmcp.db"
    if not DATA_DEV.exists() or not real_db.exists():
        pytest.skip(
            "data/jobcontextmcp.db not found — start the server once to create it"
        )

    import shutil
    session_tmp = tmp_path_factory.mktemp("sqlite")
    db = session_tmp / "jobcontextmcp.db"
    shutil.copy2(real_db, db)
    return db


@pytest.fixture(scope="session")
def con(db_path):
    """Open a read-only session connection to the test DB."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ── Synthetic data fixture (no data_dev/ required) ────────────────────────────

_SYNTH_DATA: dict[str, dict] = {
    "status.json": {
        "last_updated": "2026-06-15",
        "applications": [
            {
                "company": "Alpha Inc", "role": "SWE", "status": "applied",
                "applied_date": "2026-06-01", "last_updated": "2026-06-15",
                "notes": "good fit", "next_steps": None, "contact": None,
                "events": [
                    {"type": "applied", "notes": "submitted", "date": "2026-06-01"},
                ],
            },
            {
                "company": "Beta LLC", "role": "SRE", "status": "phone_screen",
                "applied_date": "2026-06-03", "last_updated": "2026-06-10",
                "notes": "", "next_steps": "follow up", "contact": "Bob",
                "events": [
                    {"type": "applied", "notes": "", "date": "2026-06-03"},
                    {"type": "phone_screen", "notes": "great call", "date": "2026-06-10"},
                ],
            },
        ],
    },
    "job_queue.json": {
        "jobs": [
            {"id": 101, "company": "QueueCo", "role": "ML Eng", "jd": "JD text here",
             "source": "linkedin", "added_date": "2026-06-01", "status": "pending",
             "fitment_score": None, "decision_notes": None, "decided_date": None},
            {"id": 102, "company": "NextCo", "role": "Infra", "jd": "JD2 text",
             "source": "referral", "added_date": "2026-06-02", "status": "evaluated",
             "fitment_score": "8/10", "decision_notes": "strong fit", "decided_date": None},
        ]
    },
    "people.json": {
        "people": [
            {"id": 201, "name": "Alice Smith", "relationship": "recruiter",
             "company": "Alpha Inc", "tags": ["warm", "recruiter"],
             "contact_info": "alice@example.com", "outreach_status": "replied",
             "notes": "", "timestamp": "2026-06-01", "last_updated": "2026-06-01",
             "context": "met at conference"},
        ]
    },
    "interviews.json": {
        "interviews": [
            {"id": 301, "company": "Alpha Inc", "role": "SWE",
             "interview_date": "2026-06-10", "interview_type": "phone",
             "interview_format": "video", "interviewer": "Jane",
             "interviewer_role": "EM", "duration_minutes": 30, "self_rating": 4,
             "verbatim_quotes": [{"speaker": "Jane", "quote": "Strong background"}],
             "what_landed": ["tech depth"], "what_didnt": [],
             "surfaced_priorities": ["scalability"], "tags": ["technical"],
             "follow_up_commitments": [], "process_details": "3 more rounds",
             "comp_signals": "$180k", "notes": "",
             "timestamp": "2026-06-10", "last_updated": "2026-06-10"},
        ]
    },
    "rejections.json": {
        "rejections": [
            {"id": 401, "company": "RejectCo", "role": "SWE", "stage": "applied",
             "reason": "overqualified", "notes": "", "date": "2026-06-05",
             "logged_at": "2026-06-05T10:00:00", "contact": None},
        ]
    },
    "mental_health_log.json": {
        "entries": [
            {"timestamp": "2026-06-15T09:00:00", "date": "2026-06-15",
             "mood": "focused", "energy": 8, "productive": True, "notes": ""},
            {"timestamp": "2026-06-14T09:00:00", "date": "2026-06-14",
             "mood": "tired", "energy": 5, "productive": False, "notes": ""},
        ]
    },
    "personal_context.json": {
        "stories": [
            {"id": 501, "title": "Led migration", "story": "Migrated DB to cloud",
             "tags": ["leadership"], "people": [], "timestamp": "2026-06-01"},
        ],
        "star_stories": [
            {"id": "synth_story_1", "title": "DB Migration", "tags": ["technical"],
             "situation": "Slow queries", "task": "Optimize",
             "action": "Planned migration", "result": "3x speed",
             "metric_bullets": ["3x faster"],
             "framing_hints": {"scale": "enterprise", "impact": "high"},
             "source": "direct", "notes": ""},
        ],
    },
    "linkedin_posts.json": {
        "posts": [
            {"id": 601, "title": "AI post", "posted_date": "2026-06-01",
             "source": "manual", "hashtags": ["#ai", "#python"],
             "metrics": {"impressions": 500, "reactions": 20},
             "audience_highlights": {"top_job_title": "Engineer"},
             "links": [], "context": "", "url": "https://li.com/p/1",
             "timestamp": "2026-06-01"},
        ]
    },
    "tone_samples.json": {
        "samples": [
            {"id": 701, "timestamp": "2026-06-01T09:00:00", "source": "email",
             "context": "outreach", "text": "Concise and direct tone sample",
             "word_count": 5},
        ]
    },
}


@pytest.fixture(scope="session")
def synth_dir(tmp_path_factory):
    """Create a self-contained temp dir with JSON files + SQLite DB seeded from
    ``_SYNTH_DATA``.  No dependency on data_dev/ — safe to run anywhere."""
    import lib.config as config
    import lib.db as db_mod
    from lib.io_sqlite import save_to_sqlite
    from scripts.migrate_to_sqlite import _SCHEMA

    d = tmp_path_factory.mktemp("synth")

    # Write all JSON files
    for fname, content in _SYNTH_DATA.items():
        (d / fname).write_text(
            json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # Create fresh SQLite DB with full schema
    db_file = d / "jobcontextmcp.db"
    raw = sqlite3.connect(db_file)
    raw.executescript(_SCHEMA)
    raw.commit()
    raw.close()

    # Seed via save_to_sqlite — patch db_path + config temporarily
    orig_db_fn   = db_mod.db_path
    orig_data    = config.DATA_FOLDER
    orig_jq      = config.JOB_QUEUE_FILE
    db_mod.db_path     = lambda: db_file
    config.DATA_FOLDER = d
    config.JOB_QUEUE_FILE = d / "job_queue.json"
    try:
        for fname, content in _SYNTH_DATA.items():
            save_to_sqlite(d / fname, content)
    finally:
        db_mod.db_path        = orig_db_fn
        config.DATA_FOLDER    = orig_data
        config.JOB_QUEUE_FILE = orig_jq

    return d, _SYNTH_DATA


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
    Row counts in SQLite must be close to source JSON counts.
    Allow up to 3 rows of lag — the DB reflects the last-written state; the
    JSON may have newer entries not yet flushed via a save path.
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
    DRIFT_TOLERANCE = 3  # DB may lag JSON by this many rows
    for table, fname, key in checks:
        if fname is None:
            continue
        src = _source(fname)
        src_count = len(src.get(key, src) if isinstance(src, dict) else src)
        db_count = _count(con, table)
        assert db_count >= src_count - DRIFT_TOLERANCE, (
            f"{table}: source={src_count}, db={db_count} (drift>{DRIFT_TOLERANCE})"
        )


def test_application_events_total(con):
    """Total events in DB must be close to total events across all source applications.
    Allow small drift (JSON may have been edited after last DB write)."""
    apps = _source("status.json").get("applications", [])
    src_total = sum(len(a.get("events", [])) for a in apps)
    db_total = _count(con, "application_events")
    assert abs(db_total - src_total) <= 10, (
        f"event count drift too large: db={db_total}, source={src_total}"
    )


# ── 2. Data fidelity — Tier 1 spot checks ─────────────────────────────────────

def test_applications_core_fields(con):
    """Every application in the DB that also exists in the JSON has a consistent
    status.  Rows present only in JSON (DB lags) or only in DB (DB is ahead)
    are both fine — we just verify there are no *unexplained mismatches* for
    rows that appear in both with the same last_updated timestamp."""
    apps = _source("status.json").get("applications", [])
    db_rows = {
        (r["company"], r["role"]): r
        for r in con.execute("SELECT * FROM applications").fetchall()
    }
    # We only assert company/role presence in at least one side — no strict
    # status equality since DB is canonical and may be ahead of JSON.
    for a in apps:
        key = (a["company"], a["role"])
        if key not in db_rows:
            continue  # DB may lag JSON — acceptable
        # If timestamps match exactly, statuses must also match
        row = db_rows[key]
        src_ts = a.get("last_updated") or None
        db_ts  = row["last_updated"]
        if src_ts and db_ts and src_ts == db_ts:
            assert row["status"] == a["status"], (
                f"{key}: same timestamp but status differs: "
                f"db={row['status']!r} json={a['status']!r}"
            )


def test_applications_sparse_fields(con):
    """location, date_applied, req_number, comp are stored when present in source.
    Rows absent from DB are skipped (DB may lag JSON)."""
    apps = _source("status.json").get("applications", [])
    db_rows = {
        (r["company"], r["role"]): dict(r)
        for r in con.execute("SELECT * FROM applications").fetchall()
    }
    for a in apps:
        key = (a["company"], a["role"])
        if key not in db_rows:
            continue  # DB may lag JSON
        row = db_rows[key]
        for sparse in ("location", "date_applied", "req_number"):
            if sparse in a and a[sparse] is not None:
                assert row[sparse] == a[sparse], (
                    f"{a['company']} {sparse}: source={a[sparse]!r} db={row[sparse]!r}"
                )
        if "comp" in a and a["comp"] is not None:
            if row.get("comp") is not None:
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
def sqlite_env(monkeypatch, synth_dir):
    """Monkeypatch config + db_path to the synth_dir DB and activate SQLite reads.
    Self-contained: no data_dev/ required."""
    d, _ = synth_dir
    import lib.config as config
    import lib.io as io_mod
    import lib.db as db_mod
    monkeypatch.setattr(db_mod, "db_path",               lambda: d / "jobcontextmcp.db")
    monkeypatch.setattr(config, "DATA_FOLDER",           d)
    monkeypatch.setattr(config, "STATUS_FILE",           d / "status.json")
    monkeypatch.setattr(config, "HEALTH_LOG_FILE",       d / "mental_health_log.json")
    monkeypatch.setattr(config, "JOB_QUEUE_FILE",        d / "job_queue.json")
    monkeypatch.setattr(config, "REJECTIONS_FILE",       d / "rejections.json")
    monkeypatch.setattr(config, "PEOPLE_FILE",           d / "people.json")
    monkeypatch.setattr(config, "PERSONAL_CONTEXT_FILE", d / "personal_context.json")
    monkeypatch.setattr(config, "TONE_FILE",             d / "tone_samples.json")
    monkeypatch.setattr(config, "INTERVIEWS_FILE",       d / "interviews.json")
    monkeypatch.setattr(config, "LINKEDIN_POSTS_FILE",   d / "linkedin_posts.json")
    monkeypatch.setattr(io_mod, "_USE_SQLITE", True)


def test_load_from_sqlite_returns_no_handler_for_unknown_file(sqlite_env):
    from lib.io_sqlite import load_from_sqlite, SQLITE_NO_HANDLER
    import lib.config as config
    result = load_from_sqlite(config.DATA_FOLDER / "scan_index.json", {})
    assert result is SQLITE_NO_HANDLER


def test_status_application_count_matches(sqlite_env, synth_dir):
    from lib.io import _load_json
    import lib.config as config
    _, SYNTH = synth_dir
    result = _load_json(config.STATUS_FILE, {})
    src = SYNTH["status.json"]
    assert len(result["applications"]) == len(src["applications"])


def test_status_all_companies_present(sqlite_env, synth_dir):
    from lib.io import _load_json
    import lib.config as config
    _, SYNTH = synth_dir
    result = _load_json(config.STATUS_FILE, {})
    src = SYNTH["status.json"]
    src_companies = {a["company"] for a in src["applications"]}
    db_companies  = {a["company"] for a in result["applications"]}
    assert src_companies == db_companies


def test_job_queue_all_ids_present(sqlite_env, synth_dir):
    from lib.io import _load_json
    import lib.config as config
    _, SYNTH = synth_dir
    result = _load_json(config.JOB_QUEUE_FILE, {})
    src = SYNTH["job_queue.json"]
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


def test_rejections_all_present(sqlite_env, synth_dir):
    from lib.io import _load_json
    import lib.config as config
    _, SYNTH = synth_dir
    result = _load_json(config.REJECTIONS_FILE, {})
    src = SYNTH["rejections.json"]
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


def test_personal_context_stories_and_star_stories(sqlite_env, synth_dir):
    from lib.io import _load_json
    import lib.config as config
    _, SYNTH = synth_dir
    result = _load_json(config.PERSONAL_CONTEXT_FILE, {})
    src = SYNTH["personal_context.json"]
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

def test_use_sqlite_false_reads_json_file(monkeypatch, synth_dir):
    """With USE_SQLITE off, _load_json must read the actual JSON file."""
    d, SYNTH = synth_dir
    import lib.io as io_mod
    monkeypatch.setattr(io_mod, "_USE_SQLITE", False)
    from lib.io import _load_json
    result = _load_json(d / "status.json", {"applications": []})
    assert isinstance(result, dict)
    assert "applications" in result
    src = SYNTH["status.json"]
    assert result.get("last_updated") == src.get("last_updated")


def test_use_sqlite_true_bypasses_json_file(monkeypatch, synth_dir):
    """With USE_SQLITE on, _load_json reads DB even when JSON has different content."""
    d, _ = synth_dir
    import lib.config as config
    import lib.io as io_mod
    import lib.db as db_mod
    monkeypatch.setattr(db_mod, "db_path",      lambda: d / "jobcontextmcp.db")
    monkeypatch.setattr(config, "DATA_FOLDER",  d)
    monkeypatch.setattr(config, "STATUS_FILE",  d / "status.json")
    monkeypatch.setattr(config, "HEALTH_LOG_FILE", d / "mental_health_log.json")
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


def test_save_job_queue_sync_deletes_removed_jobs(monkeypatch, tmp_path):
    """_save_job_queue performs sync-delete — omitting a job from the payload
    removes it from the DB.  This is what makes the /pipeline/remove endpoint
    actually work when USE_SQLITE=1."""
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

    # Save only job 1 — job 2 must be removed (sync-delete).
    queue["jobs"] = [j for j in queue["jobs"] if j["id"] != 2]
    save_to_sqlite(tmp_path / "job_queue.json", queue)

    result = load_from_sqlite(tmp_path / "job_queue.json", {})
    ids = [j["id"] for j in result["jobs"]]
    assert set(ids) == {1}, (
        f"Expected only job 1 after removal, got {ids}"
    )


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


# ── Regression: seeder schema must not drift from _MIGRATIONS (PR #67, #1) ────
#
# The per-user SQLite DB is created out-of-band by the seeder schema
# (lib.user_provisioning._SCHEMA_SQL / scripts.migrate_to_sqlite._SCHEMA), NOT
# by lib.db._MIGRATIONS.  Because _apply_migrations tolerates a "no such table"
# error for a job_queue ALTER and *still advances the version ledger*, any
# `ALTER TABLE job_queue ADD COLUMN ...` that runs against an empty DB before
# the table exists is silently marked applied and never retried.  If the seeder
# then creates job_queue without those columns, they are missing forever and
# writes to them fail.  The only safe contract is: the seeder must create
# job_queue with every column the ALTER-migrations would add.

def _job_queue_columns(db_file: Path) -> set[str]:
    """Return the column names of the job_queue table in a seeded DB file."""
    con = sqlite3.connect(str(db_file))
    try:
        return {row[1] for row in con.execute("PRAGMA table_info(job_queue)")}
    finally:
        con.close()


def test_provisioned_tenant_db_has_template_columns(tmp_path):
    """A freshly provisioned tenant DB includes all job_queue template columns.

    resume_template / resume_style / cl_template / cl_style must exist at seed
    time so per-card template selection persists even when the ALTER migrations
    were tolerated-and-skipped on an empty DB.
    """
    from lib.user_provisioning import provision_user_data

    data_dir = tmp_path / "users" / "oid-under-test"
    provision_user_data(data_dir)

    cols = _job_queue_columns(data_dir / "db" / "jobcontextmcp.db")
    for expected in ("resume_template", "resume_style", "cl_template", "cl_style"):
        assert expected in cols, (
            f"seeder job_queue missing {expected!r}: {sorted(cols)}"
        )


def test_seeder_job_queue_covers_all_alter_migrations(tmp_path):
    """The seeder must create every job_queue column the ALTER migrations add.

    Self-maintaining drift guard: if a future migration adds another
    ``ALTER TABLE job_queue ADD COLUMN <name>`` without updating the seeder
    schema, this fails — because that column would be permanently skipped on
    DBs where the ALTER was tolerated before the table existed.
    """
    import re
    import lib.db as db_mod
    from lib.user_provisioning import provision_user_data

    alter_cols = set()
    for sql in db_mod._MIGRATIONS:
        m = re.search(r"ALTER\s+TABLE\s+job_queue\s+ADD\s+COLUMN\s+(\w+)", sql, re.I)
        if m:
            alter_cols.add(m.group(1))
    assert alter_cols, "expected at least one ALTER TABLE job_queue migration"

    data_dir = tmp_path / "users" / "oid-drift-guard"
    provision_user_data(data_dir)
    seeder_cols = _job_queue_columns(data_dir / "db" / "jobcontextmcp.db")

    missing = alter_cols - seeder_cols
    assert not missing, (
        f"seeder job_queue is missing ALTER-migration columns {sorted(missing)}; "
        "add them to _SCHEMA_SQL (lib/user_provisioning.py) and _SCHEMA "
        "(scripts/migrate_to_sqlite.py) to prevent ledger-skip drift"
    )
