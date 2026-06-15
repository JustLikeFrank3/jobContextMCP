"""
lib/io_sqlite.py — SQLite-backed drop-in readers for _load_json().

Each handler returns the EXACT same dict shape the original JSON file returned,
so every existing tool works unmodified when USE_SQLITE=1 is set.

Write path is intentionally out of scope for the prototype: _save_json still
writes to JSON, and the migration script (scripts/migrate_to_sqlite.py) is
idempotent so a re-run after any write keeps the DB in sync.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lib.db import get_connection


# ── JSON column helper ─────────────────────────────────────────────────────────

def _j(col: str | None) -> Any:
    """Deserialize a stored JSON column value; pass through non-strings as-is."""
    if col is None:
        return None
    if isinstance(col, str):
        try:
            return json.loads(col)
        except (TypeError, ValueError):
            return col
    return col


# ── Per-file handlers ──────────────────────────────────────────────────────────

def _load_status(con) -> dict:
    app_rows = con.execute("SELECT * FROM applications ORDER BY id").fetchall()

    # Fetch every event in one pass, group by application_id
    ev_rows = con.execute(
        "SELECT application_id, type, notes, date FROM application_events ORDER BY id"
    ).fetchall()
    events_by_id: dict[int, list] = {}
    for ev in ev_rows:
        events_by_id.setdefault(ev["application_id"], []).append(
            {"type": ev["type"], "notes": ev["notes"], "date": ev["date"]}
        )

    apps = []
    for r in app_rows:
        app: dict = {
            "company":      r["company"],
            "role":         r["role"],
            "status":       r["status"],
            "next_steps":   r["next_steps"],
            "contact":      r["contact"],
            "notes":        r["notes"],
            "applied_date": r["applied_date"],
            "last_updated": r["last_updated"],
            "events":       events_by_id.get(r["id"], []),
        }
        # Sparse fields — only include when present so callers see the same
        # shape as the original JSON (no surprise None keys on most records)
        for sparse_key in ("location", "date_applied", "req_number"):
            val = r[sparse_key]
            if val is not None:
                app[sparse_key] = val
        comp = _j(r["comp"])
        if comp is not None:
            app["comp"] = comp
        apps.append(app)

    last_updated = max(
        (a["last_updated"] for a in apps if a["last_updated"]),
        default=None,
    )
    return {"last_updated": last_updated, "applications": apps}


def _load_job_queue(con) -> dict:
    rows = con.execute("SELECT * FROM job_queue ORDER BY id").fetchall()
    return {
        "jobs": [
            {
                "id":             r["id"],
                "company":        r["company"],
                "role":           r["role"],
                "jd":             r["jd"],
                "source":         r["source"],
                "added_date":     r["added_date"],
                "status":         r["status"],
                "fitment_score":  r["fitment_score"],
                "decision_notes": r["decision_notes"],
                "decided_date":   r["decided_date"],
            }
            for r in rows
        ]
    }


def _load_people(con) -> dict:
    rows = con.execute("SELECT * FROM people ORDER BY id").fetchall()
    return {
        "people": [
            {
                "id":             r["id"],
                "timestamp":      r["timestamp"],
                "name":           r["name"],
                "relationship":   r["relationship"],
                "company":        r["company"],
                "context":        r["context"],
                "tags":           _j(r["tags"]) or [],
                "contact_info":   r["contact_info"],
                "outreach_status": r["outreach_status"],
                "notes":          r["notes"],
                "last_updated":   r["last_updated"],
            }
            for r in rows
        ]
    }


def _load_interviews(con) -> dict:
    rows = con.execute("SELECT * FROM interviews ORDER BY id").fetchall()
    return {
        "interviews": [
            {
                "id":                    r["id"],
                "timestamp":             r["timestamp"],
                "company":               r["company"],
                "role":                  r["role"],
                "interview_date":        r["interview_date"],
                "interview_type":        r["interview_type"],
                "interview_format":      r["interview_format"],
                "interviewer":           r["interviewer"],
                "interviewer_role":      r["interviewer_role"],
                "duration_minutes":      r["duration_minutes"],
                "self_rating":           r["self_rating"],
                "what_landed":           _j(r["what_landed"]) or [],
                "what_didnt":            _j(r["what_didnt"]) or [],
                "verbatim_quotes":       _j(r["verbatim_quotes"]) or [],
                "surfaced_priorities":   _j(r["surfaced_priorities"]) or [],
                "process_details":       r["process_details"],
                "comp_signals":          r["comp_signals"],
                "follow_up_commitments": _j(r["follow_up_commitments"]) or [],
                "tags":                  _j(r["tags"]) or [],
                "notes":                 r["notes"],
                "last_updated":          r["last_updated"],
            }
            for r in rows
        ]
    }


def _load_rejections(con) -> dict:
    rows = con.execute("SELECT * FROM rejections ORDER BY id").fetchall()
    return {
        "rejections": [
            {
                "id":       r["id"],
                "company":  r["company"],
                "role":     r["role"],
                "stage":    r["stage"],
                "reason":   r["reason"],
                "notes":    r["notes"],
                "date":     r["date"],
                "logged_at": r["logged_at"],
                "contact":  r["contact"],
            }
            for r in rows
        ]
    }


def _load_tone(con) -> dict:
    rows = con.execute("SELECT * FROM tone_samples ORDER BY id").fetchall()
    return {
        "samples": [
            {
                "id":         r["id"],
                "timestamp":  r["timestamp"],
                "source":     r["source"],
                "context":    r["context"],
                "text":       r["text"],
                "word_count": r["word_count"],
            }
            for r in rows
        ]
    }


def _load_health_log(con) -> dict:
    rows = con.execute("SELECT * FROM health_log ORDER BY id").fetchall()
    return {
        "entries": [
            {
                "timestamp":  r["timestamp"],
                "date":       r["date"],
                "mood":       r["mood"],
                "energy":     r["energy"],
                "productive": bool(r["productive"]),
                "notes":      r["notes"],
            }
            for r in rows
        ]
    }


def _load_linkedin_posts(con) -> dict:
    rows = con.execute("SELECT * FROM linkedin_posts ORDER BY id").fetchall()
    return {
        "posts": [
            {
                "id":                  r["id"],
                "timestamp":           r["timestamp"],
                "posted_date":         r["posted_date"],
                "source":              r["source"],
                "title":               r["title"],
                "url":                 r["url"],
                "hashtags":            _j(r["hashtags"]) or [],
                "context":             r["context"],
                "links":               _j(r["links"]) or [],
                "metrics":             _j(r["metrics"]) or {},
                "audience_highlights": _j(r["audience_highlights"]) or {},
            }
            for r in rows
        ]
    }


def _load_personal_context(con) -> dict:
    story_rows = con.execute("SELECT * FROM stories ORDER BY id").fetchall()
    stories = [
        {
            "id":        r["id"],
            "timestamp": r["timestamp"],
            "title":     r["title"],
            "story":     r["story"],
            "tags":      _j(r["tags"]) or [],
            "people":    _j(r["people"]) or [],
        }
        for r in story_rows
    ]

    star_rows = con.execute("SELECT * FROM star_stories ORDER BY id").fetchall()
    star_stories = [
        {
            "id":             r["id"],
            "title":          r["title"],
            "tags":           _j(r["tags"]) or [],
            "situation":      r["situation"],
            "task":           r["task"],
            "action":         r["action"],
            "result":         r["result"],
            "metric_bullets": _j(r["metric_bullets"]) or [],
            "framing_hints":  _j(r["framing_hints"]) or {},
            "source":         r["source"],
            "notes":          r["notes"],
        }
        for r in star_rows
    ]

    # hbdi_profile is a singleton config blob, not a list — not yet in SQLite.
    # Returning {} is safe: tools call data.get("hbdi_profile", {}) and handle it.
    return {
        "stories":      stories,
        "star_stories": star_stories,
        "hbdi_profile": {},
    }


# ── Dispatch table ─────────────────────────────────────────────────────────────

_HANDLERS: dict[str, Any] = {
    "status.json":            _load_status,
    "job_queue.json":         _load_job_queue,
    "people.json":            _load_people,
    "interviews.json":        _load_interviews,
    "rejections.json":        _load_rejections,
    "tone_samples.json":      _load_tone,
    "mental_health_log.json": _load_health_log,
    "linkedin_posts.json":    _load_linkedin_posts,
    "personal_context.json":  _load_personal_context,
}

# Sentinel used by io.py to detect "no handler found" vs a valid None result
SQLITE_NO_HANDLER = object()


def load_from_sqlite(path: Path, default: Any) -> Any:
    """
    Return the same dict shape _load_json(path, default) would, sourced from SQLite.

    Returns SQLITE_NO_HANDLER (not default) when the path is unmapped, so the
    caller can fall through to the normal JSON read for unknown files.
    """
    handler = _HANDLERS.get(path.name)
    if handler is None:
        return SQLITE_NO_HANDLER

    try:
        with get_connection() as con:
            return handler(con)
    except Exception:
        # DB missing or corrupt — fall back gracefully
        return default
