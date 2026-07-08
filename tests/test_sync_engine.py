"""Bidirectional sync engine: journal triggers, export/apply, LWW, files.

Simulates two replicas ("desktop" and "cloud") as two isolated data dirs and
drives real writes through lib.db connections so the AFTER-triggers journal
them, then exchanges batches with export_changes/apply_changes.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import lib.config as cfg
import lib.db as db
from lib import sync


@pytest.fixture()
def replicas(tmp_path, monkeypatch):
    """Two isolated replica data dirs; yields a helper to run against either."""

    class Replica:
        def __init__(self, root: Path):
            self.root = root
            self._provisioned = False
            root.mkdir()

        def __enter__(self):
            self._patch = pytest.MonkeyPatch()
            self._patch.setattr(cfg, "DATA_FOLDER", str(self.root), raising=False)
            if not self._provisioned:
                from lib.user_provisioning import provision_user_data

                provision_user_data(self.root)
                self._provisioned = True
            return self

        def __exit__(self, *exc):
            self._patch.undo()

    return Replica(tmp_path / "desktop"), Replica(tmp_path / "cloud")


def _write_job(company="Acme", role="SWE", status="pending"):
    with db.get_connection() as con:
        con.execute(
            "INSERT INTO job_queue (company, role, jd, source, added_date, status) "
            "VALUES (?, ?, 'jd', 'test', date('now'), ?)",
            (company, role, status),
        )


def _update_job_status(company, role, status):
    with db.get_connection() as con:
        con.execute(
            "UPDATE job_queue SET status = ? WHERE company = ? AND role = ?",
            (status, company, role),
        )


def _log_interview(company="Acme", role="SWE", ts="2026-07-08T10:00:00"):
    with db.get_connection() as con:
        con.execute(
            "INSERT INTO interviews (timestamp, company, role, interview_date, interview_type) "
            "VALUES (?, ?, ?, date('now'), 'recruiter_screen')",
            (ts, company, role),
        )


def _export(since=0):
    with db.get_connection() as con:
        return sync.export_changes(con, since)


def _apply(changes):
    with db.get_connection() as con:
        return sync.apply_changes(con, changes)


def _rows(sql, args=()):
    with db.get_connection() as con:
        return [dict(r) for r in con.execute(sql, args).fetchall()]


def test_triggers_journal_local_writes(replicas):
    desktop, _ = replicas
    with desktop:
        _write_job()
        _log_interview()
        log = _rows("SELECT tbl, op, origin FROM sync_log ORDER BY id")
        assert {"tbl": "job_queue", "op": "upsert", "origin": "local"} in log
        assert {"tbl": "interviews", "op": "insert", "origin": "local"} in log


def test_row_roundtrip_desktop_to_cloud(replicas):
    desktop, cloud = replicas
    with desktop:
        _write_job()
        _log_interview(ts="2026-07-08T11:22:33")
        batch = _export()
        assert batch["changes"]
    with cloud:
        stats = _apply(batch["changes"])
        assert stats["applied"] == len(batch["changes"]), stats
        jobs = _rows("SELECT company, role, status FROM job_queue")
        assert jobs == [{"company": "Acme", "role": "SWE", "status": "pending"}]
        ivs = _rows("SELECT company, timestamp FROM interviews")
        assert ivs == [{"company": "Acme", "timestamp": "2026-07-08T11:22:33"}]


def test_apply_does_not_echo(replicas):
    """Applied rows journal as origin='remote' — they never re-export."""
    desktop, cloud = replicas
    with desktop:
        _write_job()
        batch = _export()
    with cloud:
        _apply(batch["changes"])
        assert _export()["changes"] == []  # nothing 'local' to send back


def test_append_tables_dedupe_on_replay(replicas):
    desktop, cloud = replicas
    with desktop:
        _log_interview()
        batch = _export()
    with cloud:
        assert _apply(batch["changes"])["applied"] == 1
        stats = _apply(batch["changes"])  # replay the same batch
        assert stats["applied"] == 0 and stats["skipped_dupe"] == 1
        assert len(_rows("SELECT id FROM interviews")) == 1


def test_lww_newer_local_wins(replicas):
    desktop, cloud = replicas
    with desktop:
        _write_job(status="pending")
        batch = _export()
    with cloud:
        _apply(batch["changes"])
        time.sleep(0.01)
        _update_job_status("Acme", "SWE", "applied")  # cloud edits later
        stale = dict(batch["changes"][0])
        stats = _apply([stale])  # replaying older desktop state must lose
        assert stats["skipped_lww"] == 1
        assert _rows("SELECT status FROM job_queue")[0]["status"] == "applied"


def test_upsert_conflict_newer_remote_wins(replicas):
    desktop, cloud = replicas
    with desktop:
        _write_job(status="pending")
        first = _export()
    with cloud:
        _apply(first["changes"])
    time.sleep(0.01)
    with desktop:
        _update_job_status("Acme", "SWE", "evaluated")
        second = _export(since=first["last_id"])
    with cloud:
        stats = _apply(second["changes"])
        assert stats["applied"] == 1
        assert _rows("SELECT status FROM job_queue")[0]["status"] == "evaluated"


def test_delete_tombstone_roundtrip(replicas):
    desktop, cloud = replicas
    with desktop:
        _write_job()
        batch = _export()
    with cloud:
        _apply(batch["changes"])
    with desktop:
        with db.get_connection() as con:
            con.execute("DELETE FROM job_queue WHERE company = 'Acme'")
        tomb = _export(since=batch["last_id"])
        assert tomb["changes"][0]["op"] == "delete"
    with cloud:
        _apply(tomb["changes"])
        assert _rows("SELECT id FROM job_queue") == []


def test_application_events_remap_parent_fk(replicas):
    desktop, cloud = replicas
    with desktop:
        with db.get_connection() as con:
            con.execute(
                "INSERT INTO applications (company, role, status) VALUES ('Acme', 'SWE', 'applied')"
            )
            app_id = con.execute("SELECT id FROM applications").fetchone()[0]
            con.execute(
                "INSERT INTO application_events (application_id, type, notes, date) "
                "VALUES (?, 'follow_up_sent', 'sent email', date('now'))",
                (app_id,),
            )
        batch = _export()
        ev = next(c for c in batch["changes"] if c["tbl"] == "application_events")
        assert ev["row"]["__parent_nk__"] == ["Acme", "SWE"]
        assert "application_id" not in ev["row"]
    with cloud:
        # Force a different parent rowid on the cloud replica first.
        with db.get_connection() as con:
            con.execute("INSERT INTO applications (company, role) VALUES ('Filler', 'X')")
        stats = _apply(batch["changes"])
        assert stats["applied"] >= 2, stats
        got = _rows(
            "SELECT ae.type, a.company FROM application_events ae JOIN applications a ON a.id = ae.application_id"
        )
        assert got == [{"type": "follow_up_sent", "company": "Acme"}]


def test_export_converts_vanished_upsert_to_delete(replicas):
    desktop, _ = replicas
    with desktop:
        _write_job()
        with db.get_connection() as con:
            con.execute("UPDATE sync_state SET applying = 1 WHERE id = 1")
            con.execute("DELETE FROM job_queue WHERE company = 'Acme'")  # unjournaled
            con.execute("UPDATE sync_state SET applying = 0 WHERE id = 1")
        batch = _export()
        assert batch["changes"][0]["op"] == "delete"


# ── file sync planning ─────────────────────────────────────────────────────────

def _m(sha, mtime=1.0):
    return {"size": 1, "mtime": mtime, "sha256": sha}


def test_plan_pull_push_and_conflict():
    baseline = {"a.md": _m("v1"), "b.md": _m("v1"), "c.md": _m("v1")}
    local = {"a.md": _m("v1"), "b.md": _m("v2-local"), "c.md": _m("v2-local"), "new-local.md": _m("x")}
    remote = {"a.md": _m("v2-remote"), "b.md": _m("v1"), "c.md": _m("v2-remote"), "new-remote.md": _m("y")}
    plan = sync.plan_file_sync(local, remote, baseline)
    assert plan["pull"] == ["a.md", "new-remote.md"]
    assert plan["push"] == ["b.md", "new-local.md"]
    assert plan["conflict"] == ["c.md"]


def test_plan_respects_deletions_via_baseline():
    baseline = {"gone-local.md": _m("v1"), "gone-remote.md": _m("v1")}
    local = {"gone-remote.md": _m("v1")}
    remote = {"gone-local.md": _m("v1")}
    plan = sync.plan_file_sync(local, remote, baseline)
    assert plan == {"pull": [], "push": [], "conflict": []}


def test_file_manifest_excludes_machine_local(tmp_path):
    (tmp_path / "db").mkdir()
    (tmp_path / "db" / "jobcontextmcp.db").write_bytes(b"x")
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "notes.md").write_text("hello")
    (tmp_path / "resume.bak").write_text("old")
    manifest = sync.file_manifest(tmp_path)
    assert list(manifest) == ["notes.md"]


def test_sync_url_normalization():
    from lib.sync_client import _normalize_url

    assert _normalize_url("app.jobcontext.ai") == "https://app.jobcontext.ai"
    assert _normalize_url("http://app.jobcontext.ai/") == "https://app.jobcontext.ai"
    assert _normalize_url("https://app.jobcontext.ai") == "https://app.jobcontext.ai"
    assert _normalize_url("http://127.0.0.1:8801") == "http://127.0.0.1:8801"
    assert _normalize_url("http://localhost:8801") == "http://localhost:8801"
    assert _normalize_url("  ") == ""
