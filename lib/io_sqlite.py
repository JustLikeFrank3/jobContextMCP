"""
lib/io_sqlite.py — SQLite-backed drop-in readers and writers for _load_json() / _save_json().

Each load handler returns the EXACT same dict shape the original JSON file
returned, so every existing tool works unmodified when USE_SQLITE=1 is set.

Each save handler accepts the same dict _save_json() would write to disk and
upserts it into the appropriate SQLite table(s).

Write strategy: DUAL-WRITE — _save_json() updates SQLite AND the JSON file.
This keeps the JSON files as a human-readable audit trail and ensures unmapped
files (scan_index.json, github_metrics.json, etc.) and singleton blobs like
hbdi_profile are never silently lost. Phase 2 will drop the JSON write path.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from lib.db import get_connection
from lib import config


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
                "id":               r["id"],
                "company":          r["company"],
                "role":             r["role"],
                "jd":               r["jd"],
                "source":           r["source"],
                "added_date":       r["added_date"],
                "status":           r["status"],
                "fitment_score":    r["fitment_score"],
                "fitment_context":  r["fitment_context"],
                "decision_notes":   r["decision_notes"],
                "decided_date":     r["decided_date"],
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


# ── Save helpers ───────────────────────────────────────────────────────────────

def _js(val: Any) -> str | None:
    """Serialize val to compact JSON string for storage; strings and None pass through."""
    if val is None or isinstance(val, str):
        return val
    return json.dumps(val, ensure_ascii=False, separators=(",", ":"))


# ── Per-file save handlers ─────────────────────────────────────────────────────

def _save_status(con, data: dict) -> None:
    from lib.db import normalize_event_type
    for app in data.get("applications", []):
        company = app.get("company", "")
        role    = app.get("role", "")
        row = con.execute(
            "SELECT id FROM applications WHERE company=? AND role=?", (company, role)
        ).fetchone()
        if row:
            app_id = row["id"]
            con.execute(
                """
                UPDATE applications SET
                    status=?, next_steps=?, contact=?, notes=?,
                    applied_date=?, last_updated=?,
                    location=?, date_applied=?, req_number=?, comp=?
                WHERE id=?
                """,
                (
                    app.get("status"), app.get("next_steps"), app.get("contact"),
                    app.get("notes"), app.get("applied_date"), app.get("last_updated") or None,
                    app.get("location"), app.get("date_applied"), app.get("req_number"),
                    _js(app.get("comp")), app_id,
                ),
            )
        else:
            con.execute(
                """
                INSERT INTO applications
                    (company, role, status, next_steps, contact, notes,
                     applied_date, last_updated, location, date_applied, req_number, comp)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    company, role,
                    app.get("status", "pre-application"),
                    app.get("next_steps"), app.get("contact"), app.get("notes"),
                    app.get("applied_date"), app.get("last_updated") or None,
                    app.get("location"), app.get("date_applied"),
                    app.get("req_number"), _js(app.get("comp")),
                ),
            )
            app_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Events are append-only — insert only those beyond the existing count
        existing = con.execute(
            "SELECT COUNT(*) FROM application_events WHERE application_id=?", (app_id,)
        ).fetchone()[0]
        for ev in (app.get("events") or [])[existing:]:
            raw = ev.get("type", "note")
            con.execute(
                "INSERT INTO application_events"
                "  (application_id, type, raw_type, notes, date) VALUES (?,?,?,?,?)",
                (app_id, normalize_event_type(raw), raw, ev.get("notes"), ev.get("date")),
            )

    # Sync-delete: remove applications (and their events via CASCADE) that are
    # no longer in the incoming dataset.  Guard against accidental full wipe.
    seen_pairs = [(a.get("company", ""), a.get("role", "")) for a in data.get("applications", [])]
    if seen_pairs:
        existing_rows = con.execute(
            "SELECT id, company, role FROM applications"
        ).fetchall()
        pair_set = {(c, r) for c, r in seen_pairs}
        stale_ids = [
            r["id"] for r in existing_rows
            if (r["company"], r["role"]) not in pair_set
        ]
        for stale_id in stale_ids:
            con.execute("DELETE FROM applications WHERE id=?", (stale_id,))


def _save_job_queue(con, data: dict) -> None:
    jobs = data.get("jobs", [])
    incoming_ids: list = [j.get("id") for j in jobs if j.get("id") is not None]
    # Upsert incoming jobs inside the DB transaction.
    for j in jobs:
        con.execute(
            """
            INSERT INTO job_queue
                (id, company, role, jd, source, added_date, status,
                 fitment_score, fitment_context, decision_notes, decided_date)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                company=excluded.company, role=excluded.role, jd=excluded.jd,
                source=excluded.source, added_date=excluded.added_date,
                status=excluded.status, fitment_score=excluded.fitment_score,
                fitment_context=excluded.fitment_context,
                decision_notes=excluded.decision_notes, decided_date=excluded.decided_date
            """,
            (
                j.get("id"), j.get("company", ""), j.get("role", ""),
                j.get("jd"), j.get("source"), j.get("added_date"),
                j.get("status", "pending"), j.get("fitment_score"),
                j.get("fitment_context"), j.get("decision_notes"), j.get("decided_date"),
            ),
        )
    # Sync-delete: remove jobs no longer in the incoming dataset so that
    # explicit removals (pipeline_remove endpoint) are reflected in SQLite.
    if incoming_ids:
        placeholders = ",".join("?" * len(incoming_ids))
        con.execute(
            f"DELETE FROM job_queue WHERE id NOT IN ({placeholders})",
            incoming_ids,
        )
    elif jobs == []:
        # All jobs removed — clear the table entirely.
        con.execute("DELETE FROM job_queue")

    # After committing the DB changes, export the canonical job_queue to JSON
    # as an atomic replica for human inspection and safe backups. This keeps
    # the DB as the single source of truth while preserving the dual-write
    # audit trail the project currently expects.
    # Build the jobs list from the DB to ensure consistent shape.
    rows = con.execute("SELECT * FROM job_queue ORDER BY id").fetchall()
    out = {
        "jobs": [
            {
                "id":               r["id"],
                "company":          r["company"],
                "role":             r["role"],
                "jd":               r["jd"],
                "source":           r["source"],
                "added_date":       r["added_date"],
                "status":           r["status"],
                "fitment_score":    r["fitment_score"],
                "fitment_context":  r["fitment_context"],
                "decision_notes":   r["decision_notes"],
                "decided_date":     r["decided_date"],
            }
            for r in rows
        ]
    }

    # Atomic write to the configured JOB_QUEUE_FILE
    job_file: Path = config.JOB_QUEUE_FILE
    try:
        job_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix="job_queue.", dir=str(job_file.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(out, fh, ensure_ascii=False, indent=2)
                fh.flush(); os.fsync(fh.fileno())
            os.replace(tmp_path, str(job_file))
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
    except Exception:
        # JSON replica write failure should not break the DB commit path.
        # Surface a log-worthy warning for operators.
        try:
            import logging

            logging.exception("Failed to write job_queue JSON replica")
        except Exception:
            pass


def _save_people(con, data: dict) -> None:
    people = data.get("people", [])
    incoming_ids: list = [p.get("id") for p in people if p.get("id") is not None]
    for p in people:
        con.execute(
            """
            INSERT INTO people
                (id, timestamp, name, relationship, company, context,
                 tags, contact_info, outreach_status, notes, last_updated)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                timestamp=excluded.timestamp, name=excluded.name,
                relationship=excluded.relationship, company=excluded.company,
                context=excluded.context, tags=excluded.tags,
                contact_info=excluded.contact_info,
                outreach_status=excluded.outreach_status,
                notes=excluded.notes, last_updated=excluded.last_updated
            """,
            (
                p.get("id"), p.get("timestamp"), p.get("name", ""),
                p.get("relationship"), p.get("company"), p.get("context"),
                _js(p.get("tags")), p.get("contact_info"),
                p.get("outreach_status"), p.get("notes"), p.get("last_updated"),
            ),
        )
    # Sync-delete: remove people no longer in the incoming dataset.
    if incoming_ids:
        placeholders = ",".join("?" * len(incoming_ids))
        con.execute(
            f"DELETE FROM people WHERE id NOT IN ({placeholders})",
            incoming_ids,
        )


def _save_interviews(con, data: dict) -> None:
    for iv in data.get("interviews", []):
        con.execute(
            """
            INSERT INTO interviews
                (id, timestamp, company, role, interview_date, interview_type,
                 interview_format, interviewer, interviewer_role, duration_minutes,
                 self_rating, what_landed, what_didnt, verbatim_quotes,
                 surfaced_priorities, process_details, comp_signals,
                 follow_up_commitments, tags, notes, last_updated)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                timestamp=excluded.timestamp, company=excluded.company,
                role=excluded.role, interview_date=excluded.interview_date,
                interview_type=excluded.interview_type,
                interview_format=excluded.interview_format,
                interviewer=excluded.interviewer,
                interviewer_role=excluded.interviewer_role,
                duration_minutes=excluded.duration_minutes,
                self_rating=excluded.self_rating,
                what_landed=excluded.what_landed, what_didnt=excluded.what_didnt,
                verbatim_quotes=excluded.verbatim_quotes,
                surfaced_priorities=excluded.surfaced_priorities,
                process_details=excluded.process_details,
                comp_signals=excluded.comp_signals,
                follow_up_commitments=excluded.follow_up_commitments,
                tags=excluded.tags, notes=excluded.notes,
                last_updated=excluded.last_updated
            """,
            (
                iv.get("id"), iv.get("timestamp"),
                iv.get("company", ""), iv.get("role", ""),
                iv.get("interview_date"), iv.get("interview_type"),
                iv.get("interview_format"), iv.get("interviewer"),
                iv.get("interviewer_role"), iv.get("duration_minutes"),
                iv.get("self_rating"),
                _js(iv.get("what_landed")), _js(iv.get("what_didnt")),
                _js(iv.get("verbatim_quotes")), _js(iv.get("surfaced_priorities")),
                iv.get("process_details"), iv.get("comp_signals"),
                _js(iv.get("follow_up_commitments")), _js(iv.get("tags")),
                iv.get("notes"), iv.get("last_updated"),
            ),
        )


def _save_rejections(con, data: dict) -> None:
    for r in data.get("rejections", []):
        con.execute(
            """
            INSERT INTO rejections
                (id, company, role, stage, reason, notes, date, logged_at, contact)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                company=excluded.company, role=excluded.role,
                stage=excluded.stage, reason=excluded.reason,
                notes=excluded.notes, date=excluded.date,
                logged_at=excluded.logged_at, contact=excluded.contact
            """,
            (
                r.get("id"), r.get("company", ""), r.get("role", ""),
                r.get("stage"), r.get("reason"), r.get("notes"),
                r.get("date"), r.get("logged_at"), r.get("contact"),
            ),
        )


def _save_tone(con, data: dict) -> None:
    for s in data.get("samples", []):
        con.execute(
            """
            INSERT INTO tone_samples
                (id, timestamp, source, context, text, word_count)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                timestamp=excluded.timestamp, source=excluded.source,
                context=excluded.context, text=excluded.text,
                word_count=excluded.word_count
            """,
            (
                s.get("id"), s.get("timestamp"), s.get("source"),
                s.get("context"), s.get("text", ""), s.get("word_count"),
            ),
        )


def _save_health_log(con, data: dict) -> None:
    # health_log uses AUTOINCREMENT — insert new entries only (idempotent by timestamp)
    for e in data.get("entries", []):
        ts = e.get("timestamp", "")
        exists = con.execute(
            "SELECT 1 FROM health_log WHERE timestamp=?", (ts,)
        ).fetchone()
        if not exists:
            con.execute(
                "INSERT INTO health_log"
                "  (timestamp, date, mood, energy, productive, notes)"
                "  VALUES (?,?,?,?,?,?)",
                (
                    ts, e.get("date", ""), e.get("mood"),
                    e.get("energy"), 1 if e.get("productive") else 0, e.get("notes"),
                ),
            )


def _save_linkedin_posts(con, data: dict) -> None:
    for p in data.get("posts", []):
        con.execute(
            """
            INSERT INTO linkedin_posts
                (id, timestamp, posted_date, source, title, url,
                 hashtags, context, links, metrics, audience_highlights)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                timestamp=excluded.timestamp, posted_date=excluded.posted_date,
                source=excluded.source, title=excluded.title, url=excluded.url,
                hashtags=excluded.hashtags, context=excluded.context,
                links=excluded.links, metrics=excluded.metrics,
                audience_highlights=excluded.audience_highlights
            """,
            (
                p.get("id"), p.get("timestamp"), p.get("posted_date"),
                p.get("source"), p.get("title"), p.get("url"),
                _js(p.get("hashtags")), p.get("context"),
                _js(p.get("links")), _js(p.get("metrics")),
                _js(p.get("audience_highlights")),
            ),
        )


def _save_personal_context(con, data: dict) -> None:
    for s in data.get("stories", []):
        con.execute(
            """
            INSERT INTO stories (id, timestamp, title, story, tags, people)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                timestamp=excluded.timestamp, title=excluded.title,
                story=excluded.story, tags=excluded.tags, people=excluded.people
            """,
            (
                s.get("id"), s.get("timestamp"),
                s.get("title", ""), s.get("story", ""),
                _js(s.get("tags")), _js(s.get("people")),
            ),
        )
    for s in data.get("star_stories", []):
        con.execute(
            """
            INSERT INTO star_stories
                (id, title, tags, situation, task, action, result,
                 metric_bullets, framing_hints, source, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title, tags=excluded.tags,
                situation=excluded.situation, task=excluded.task,
                action=excluded.action, result=excluded.result,
                metric_bullets=excluded.metric_bullets,
                framing_hints=excluded.framing_hints,
                source=excluded.source, notes=excluded.notes
            """,
            (
                s.get("id"), s.get("title", ""), _js(s.get("tags")),
                s.get("situation"), s.get("task"), s.get("action"),
                s.get("result"), _js(s.get("metric_bullets")),
                _js(s.get("framing_hints")), s.get("source"), s.get("notes"),
            ),
        )
    # hbdi_profile is a singleton config blob — not stored in SQLite.
    # The JSON write path in _save_json handles it via dual-write.


# ── Save dispatch table ────────────────────────────────────────────────────────

_SAVE_HANDLERS: dict[str, Any] = {
    "status.json":            _save_status,
    "job_queue.json":         _save_job_queue,
    "people.json":            _save_people,
    "interviews.json":        _save_interviews,
    "rejections.json":        _save_rejections,
    "tone_samples.json":      _save_tone,
    "mental_health_log.json": _save_health_log,
    "linkedin_posts.json":    _save_linkedin_posts,
    "personal_context.json":  _save_personal_context,
}


def save_to_sqlite(path: Path, data: Any) -> None:
    """
    Upsert data into the appropriate SQLite table(s) for the given file path.

    No-op for unmapped files (caller should still write JSON for those).
    Raises on SQLite errors — silent data loss is worse than a visible failure.
    """
    handler = _SAVE_HANDLERS.get(path.name)
    if handler is None:
        return
    with get_connection() as con:
        handler(con, data)
