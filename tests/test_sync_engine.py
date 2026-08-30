"""Bidirectional sync engine: journal triggers, export/apply, LWW, files.

Simulates two replicas ("desktop" and "cloud") as two isolated data dirs and
drives real writes through lib.db connections so the AFTER-triggers journal
them, then exchanges batches with export_changes/apply_changes.
"""
from __future__ import annotations

import json
import os
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
        assert {"tbl": "interviews", "op": "upsert", "origin": "local"} in log


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
        with db.get_connection() as con:
            con.execute(
                "INSERT INTO rejections (company, role, stage, logged_at) "
                "VALUES ('Acme', 'SWE', 'screen', '2026-07-08T12:00:00')"
            )
        batch = _export()
    with cloud:
        assert _apply(batch["changes"])["applied"] == 1
        stats = _apply(batch["changes"])  # replay the same batch
        assert stats["applied"] == 0 and stats["skipped_dupe"] == 1
        assert len(_rows("SELECT id FROM rejections")) == 1


def test_interview_enrichment_syncs(replicas):
    """Debriefs UPDATE existing interview rows — they must journal and
    LWW-replace on the peer (the Cox comp-signals field bug)."""
    desktop, cloud = replicas
    with desktop:
        _log_interview(company="Cox", ts="2026-07-08T09:00:00")
        first = _export()
    with cloud:
        _apply(first["changes"])
    time.sleep(0.01)
    with desktop:
        with db.get_connection() as con:
            con.execute(
                "UPDATE interviews SET comp_signals = '135K base, 10% bonus' WHERE company = 'Cox'"
            )
        second = _export(since=first["last_id"])
        assert second["changes"], "interview UPDATE must journal"
    with cloud:
        stats = _apply(second["changes"])
        assert stats["applied"] == 1, stats
        assert _rows("SELECT comp_signals FROM interviews WHERE company='Cox'") == [
            {"comp_signals": "135K base, 10% bonus"}
        ]


def test_backfill_journals_pretrigger_rows(replicas):
    """Rows written before the sync schema existed must export after backfill
    and survive LWW against older peer entries."""
    desktop, _ = replicas
    with desktop:
        with db.get_connection() as con:
            # Simulate pre-sync-era data: silence triggers, wipe the journal
            # and the backfill guard, then write.
            con.execute("UPDATE sync_state SET applying = 1 WHERE id = 1")
            con.execute(
                "INSERT INTO interviews (timestamp, company, role, interview_date, interview_type) "
                "VALUES ('2026-07-01T09:00:00', 'PreSync Co', 'SWE', '2026-07-01', 'recruiter_screen')"
            )
            con.execute("UPDATE sync_state SET applying = 0 WHERE id = 1")
            con.execute("DELETE FROM sync_meta WHERE key LIKE 'journal_backfill:%'")
            con.commit()
        # Next connection re-runs ensure_sync_schema → backfill.
        batch = _export()
        assert any(
            c["tbl"] == "interviews" and c["row"] and c["row"].get("company") == "PreSync Co"
            for c in batch["changes"]
        ), batch


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


# ── personal context + tone samples ────────────────────────────────────────────
#
# These tables are mapped in lib/io_sqlite.py but were missing from TABLE_SPECS,
# so they never row-synced. They can't travel by file sync either: the desktop
# runs SQLITE_ONLY=1 (never writes the JSON) and nothing imports a received
# JSON back into SQLite. Net effect was silent staleness in both directions.

def _log_story(title="Migration weekend", ts="2026-07-08T09:00:00.123456"):
    with db.get_connection() as con:
        con.execute(
            "INSERT INTO stories (timestamp, title, story, tags, people) "
            "VALUES (?, ?, 'We cut over 400 services in one weekend.', '[\"cloud\"]', '[]')",
            (ts, title),
        )


def _log_tone(source="cover_letter_acme", ts="2026-07-08T10:00:00.654321"):
    with db.get_connection() as con:
        con.execute(
            "INSERT INTO tone_samples (timestamp, source, context, text, word_count) "
            "VALUES (?, ?, 'ctx', 'I write like this, plainly.', 5)",
            (ts, source),
        )


def test_personal_story_roundtrip_desktop_to_cloud(replicas):
    desktop, cloud = replicas
    with desktop:
        _log_story()
        batch = _export()
        assert any(c["tbl"] == "stories" for c in batch["changes"]), batch
    with cloud:
        stats = _apply(batch["changes"])
        assert stats["applied"] >= 1, stats
        assert _rows("SELECT title FROM stories") == [{"title": "Migration weekend"}]


def test_personal_story_edit_syncs(replicas):
    """update_personal_story rewrites the row in place — the edit must travel."""
    desktop, cloud = replicas
    with desktop:
        _log_story()
        first = _export()
    with cloud:
        _apply(first["changes"])
    time.sleep(0.01)
    with desktop:
        with db.get_connection() as con:
            con.execute("UPDATE stories SET story = 'Corrected: 420 services.'")
        second = _export(since=first["last_id"])
        assert second["changes"], "story UPDATE must journal"
    with cloud:
        assert _apply(second["changes"])["applied"] == 1
        assert _rows("SELECT story FROM stories") == [
            {"story": "Corrected: 420 services."}
        ]


def test_personal_story_delete_propagates(replicas):
    """delete_personal_story drops the entry from the payload; the save handler
    must prune the row so the delete journals and reaches the peer (otherwise
    the ghost row is re-pushed forever)."""
    monkey = pytest.MonkeyPatch()
    monkey.setattr("lib.io._USE_SQLITE", True)
    monkey.setattr("lib.io._SQLITE_ONLY", True)
    desktop, cloud = replicas
    try:
        with desktop:
            monkey.setattr(cfg, "PERSONAL_CONTEXT_FILE", desktop.root / "personal_context.json")
            from tools.context import delete_personal_story, log_personal_story

            log_personal_story("Keep me.", ["a"], title="Keeper")
            log_personal_story("Logged by mistake.", ["b"], title="Oops")
            first = _export()
        with cloud:
            _apply(first["changes"])
            assert len(_rows("SELECT id FROM stories")) == 2
        time.sleep(0.01)
        with desktop:
            oops = next(
                r["id"] for r in _rows("SELECT id, title FROM stories") if r["title"] == "Oops"
            )
            delete_personal_story(oops)
            assert [r["title"] for r in _rows("SELECT title FROM stories")] == ["Keeper"]
            second = _export(since=first["last_id"])
            assert any(c["op"] == "delete" for c in second["changes"]), second
        with cloud:
            _apply(second["changes"])
            assert [r["title"] for r in _rows("SELECT title FROM stories")] == ["Keeper"]
    finally:
        monkey.undo()


def test_backfill_is_per_table_so_a_newly_specced_table_still_lands(replicas):
    """The upgrade path for stories/star_stories/tone_samples.

    Every existing install had already recorded "backfill done" under the old
    single global key. With a per-table guard, a table registered in
    TABLE_SPECS later still backfills on its first ensure — otherwise the whole
    pre-existing story library stays invisible to export.
    """
    desktop, _ = replicas
    with desktop:
        with db.get_connection() as con:
            # A story from before these tables were specced: no trigger, no
            # journal entry — but every OTHER table is already marked done.
            con.execute("UPDATE sync_state SET applying = 1 WHERE id = 1")
            con.execute(
                "INSERT INTO stories (timestamp, title, story) "
                "VALUES ('2026-07-01T09:00:00', 'Legacy story', 'Predates the spec.')"
            )
            con.execute("UPDATE sync_state SET applying = 0 WHERE id = 1")
            con.execute("DELETE FROM sync_log")
            con.execute("DELETE FROM sync_meta WHERE key = 'journal_backfill:stories'")
            con.commit()
        # Next connection re-runs ensure_sync_schema → backfills stories only.
        batch = _export()
        assert any(
            c["tbl"] == "stories" and (c["row"] or {}).get("title") == "Legacy story"
            for c in batch["changes"]
        ), batch


def test_star_story_roundtrip_keeps_its_slug_id(replicas):
    """star_stories.id is a hand-authored TEXT slug — stable across replicas,
    so it is the natural key and must survive the trip (unlike the integer
    rowids everywhere else, which are machine-local)."""
    desktop, cloud = replicas
    with desktop:
        with db.get_connection() as con:
            con.execute(
                "INSERT INTO star_stories (id, title, tags, situation, result) "
                "VALUES ('star_001', 'Prod outage', '[\"incident\"]', 'DB at 100%', 'Inside SLA')"
            )
        batch = _export()
    with cloud:
        assert _apply(batch["changes"])["applied"] >= 1
        assert _rows("SELECT id, title FROM star_stories") == [
            {"id": "star_001", "title": "Prod outage"}
        ]


def test_tone_sample_roundtrip_desktop_to_cloud(replicas):
    desktop, cloud = replicas
    with desktop:
        _log_tone()
        batch = _export()
        assert any(c["tbl"] == "tone_samples" for c in batch["changes"]), batch
    with cloud:
        assert _apply(batch["changes"])["applied"] >= 1
        assert _rows("SELECT source FROM tone_samples") == [
            {"source": "cover_letter_acme"}
        ]


def test_tone_samples_dedupe_on_replay(replicas):
    """Samples are immutable once logged — a replayed batch must not duplicate."""
    desktop, cloud = replicas
    with desktop:
        _log_tone()
        batch = _export()
    with cloud:
        assert _apply(batch["changes"])["applied"] == 1
        stats = _apply(batch["changes"])
        assert stats["applied"] == 0 and stats["skipped_dupe"] == 1, stats
        assert len(_rows("SELECT id FROM tone_samples")) == 1


def test_desktop_tool_writes_reach_the_peer(replicas, monkeypatch):
    """End-to-end through the real tool write path in desktop mode.

    Desktop is SQLITE_ONLY: log_personal_story/log_tone_sample write SQLite and
    no JSON at all, so the JSON file is not just stale — it is absent. This is
    why file sync could never have carried this data.
    """
    monkeypatch.setattr("lib.io._USE_SQLITE", True)
    monkeypatch.setattr("lib.io._SQLITE_ONLY", True)
    desktop, cloud = replicas

    with desktop:
        monkeypatch.setattr(cfg, "PERSONAL_CONTEXT_FILE", desktop.root / "personal_context.json")
        monkeypatch.setattr(cfg, "TONE_FILE", desktop.root / "tone_samples.json")
        from tools.context import log_personal_story
        from tools.tone import log_tone_sample

        log_personal_story("I led the cutover.", ["leadership"], title="Cutover")
        log_tone_sample("Plain, direct, no filler.", "outreach_note")
        # The JSON files the file-sync leg would have carried are never written.
        assert not cfg.PERSONAL_CONTEXT_FILE.exists()
        assert not cfg.TONE_FILE.exists()
        batch = _export()

    with cloud:
        _apply(batch["changes"])
        assert _rows("SELECT title FROM stories") == [{"title": "Cutover"}]
        assert _rows("SELECT source FROM tone_samples") == [{"source": "outreach_note"}]


def test_hbdi_profile_roundtrip(replicas, monkeypatch):
    """The HBDI profile is a singleton blob inside personal_context.json.

    It had no SQLite home at all, so on desktop (SQLITE_ONLY) an assessment was
    written nowhere: run_hbdi_assessment reported success and get_hbdi_profile
    then answered "No HBDI profile found."
    """
    monkeypatch.setattr("lib.io._USE_SQLITE", True)
    monkeypatch.setattr("lib.io._SQLITE_ONLY", True)
    desktop, cloud = replicas

    with desktop:
        monkeypatch.setattr(cfg, "PERSONAL_CONTEXT_FILE", desktop.root / "personal_context.json")
        from lib.io import _load_json, _save_json

        data = _load_json(cfg.PERSONAL_CONTEXT_FILE, {"stories": []})
        data["hbdi_profile"] = {"primary": "D", "scores": {"A": 3, "B": 2, "C": 2, "D": 4}}
        _save_json(cfg.PERSONAL_CONTEXT_FILE, data)
        # Survives the write → read cycle locally...
        assert _load_json(cfg.PERSONAL_CONTEXT_FILE, {})["hbdi_profile"]["primary"] == "D"
        batch = _export()

    with cloud:
        monkeypatch.setattr(cfg, "PERSONAL_CONTEXT_FILE", cloud.root / "personal_context.json")
        from lib.io import _load_json as _load

        _apply(batch["changes"])
        # ...and reaches the peer.
        assert _load(cfg.PERSONAL_CONTEXT_FILE, {}).get("hbdi_profile", {}).get("primary") == "D"


def test_tone_sample_ids_never_collide_with_pulled_rows():
    """New sample ids come from max()+1, not the sample count.

    A pulled sample lands on a locally assigned rowid, so count and highest id
    diverge — and _save_tone upserts ON CONFLICT(id), which would then
    overwrite an existing sample instead of appending.
    """
    from lib.helpers import _build_tone_sample_entry

    existing = [{"id": 7}, {"id": 9}]  # ids from a peer; only two rows
    assert _build_tone_sample_entry(existing, "text", "src", "")["id"] == 10
    assert _build_tone_sample_entry([], "text", "src", "")["id"] == 1


def test_every_sqlite_mapped_table_row_syncs():
    """Self-maintaining drift guard.

    A table that lib/io_sqlite.py reads or writes holds the SQLite copy of a
    mapped JSON file. If it is missing from TABLE_SPECS it never row-syncs —
    and it cannot fall back to file sync either, because SQLITE_ONLY means the
    JSON is never written and nothing imports a received JSON back into
    SQLite. That was exactly the personal_context/tone_samples hole.
    """
    import re
    from pathlib import Path as _Path

    src = _Path(sync.__file__).with_name("io_sqlite.py").read_text(encoding="utf-8")
    referenced = {
        m.group(1)
        for m in re.finditer(
            r"(?:INSERT\s+INTO|(?:SELECT\s.*?\s)?FROM|UPDATE(?!\s+SET))"
            r"\s+([A-Za-z_][A-Za-z0-9_]*)",
            src,
        )
    }
    # Non-table matches from Python source (imports, f-string placeholders).
    referenced -= {"lib", "typing", "pathlib", "table", "__future__"}
    spec_names = {s.name for s in sync.TABLE_SPECS}

    missing = sorted(referenced - spec_names)
    assert not missing, (
        f"io_sqlite touches {missing} but they are absent from TABLE_SPECS — "
        "those tables would silently never sync; add a TableSpec with a "
        "replica-stable natural key"
    )


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


def test_file_manifest_keys_are_posix(tmp_path):
    """Manifest keys are the sync wire format — POSIX-separated on every OS,
    or a Windows peer forks each key and re-transfers the whole workspace."""
    nested = tmp_path / "07-Job-Assessments" / "run_job_assessment"
    nested.mkdir(parents=True)
    (nested / "note.md").write_text("x")
    manifest = sync.file_manifest(tmp_path)
    assert list(manifest) == ["07-Job-Assessments/run_job_assessment/note.md"]


def test_pull_file_rejects_backslash_rel_on_windows(tmp_path, monkeypatch):
    """A rel with a literal backslash (legal filename on macOS/Linux) must be
    skipped on Windows, not reinterpreted as a path separator."""
    from lib import sync_client

    monkeypatch.setattr(sync_client, "_IS_WINDOWS", True)
    with pytest.raises(ValueError, match="not representable"):
        sync_client._pull_file(None, tmp_path, r"weird\name.md")


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


# ── file sync execution: skip-and-report ──────────────────────────────────────

class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeHttp:
    """Stands in for the httpx client run_sync opens against the cloud."""

    def __init__(
        self,
        remote_files: dict[str, bytes],
        fail_put_rel: str = "",
        cloud_contact: dict | None = None,
        contact_404: bool = False,
        tombstones: dict | None = None,
    ):
        self.remote_files = remote_files
        self.fail_put_rel = fail_put_rel
        self.cloud_contact = dict(cloud_contact or {})
        self.contact_404 = contact_404
        # None → the manifest response has no "tombstones" key at all,
        # exactly like a cloud predating file tombstones.
        self.tombstones = tombstones
        self.contact_posts: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, path, json=None):
        import base64
        import hashlib

        if path == "/api/sync/changes":
            return _FakeResp({"changes": [], "last_id": 0})
        if path == "/api/sync/apply":
            return _FakeResp({"applied": len(json["changes"])})
        if path == "/api/sync/contact":
            if self.contact_404:
                return _FakeResp({"detail": "Not Found"}, status_code=404)
            posted = dict(json.get("contact") or {})
            self.contact_posts.append(posted)
            from lib.sync import merge_contact

            self.cloud_contact, filled = merge_contact(self.cloud_contact, posted)
            return _FakeResp({"contact": self.cloud_contact, "filled": filled})
        if path == "/api/sync/files/manifest":
            manifest = {
                rel: {"size": len(data), "mtime": 1.0, "sha256": hashlib.sha256(data).hexdigest()}
                for rel, data in self.remote_files.items()
            }
            payload = {"manifest": manifest}
            if self.tombstones is not None:
                payload["tombstones"] = self.tombstones
            return _FakeResp(payload)
        if path == "/api/sync/files/get":
            data = self.remote_files[json["rel"]]
            return _FakeResp({
                "rel": json["rel"],
                "mtime": 1.0,
                "content_b64": base64.b64encode(data).decode("ascii"),
            })
        if path == "/api/sync/files/put":
            if json["rel"] == self.fail_put_rel:
                raise RuntimeError("upload rejected")
            return _FakeResp({"status": "stored", "rel": json["rel"]})
        raise AssertionError(f"unexpected POST {path}")


def _wire_fake_sync(monkeypatch, root, http):
    from lib import sync_client

    monkeypatch.setattr(
        sync_client, "sync_settings",
        lambda: {"url": "https://cloud.test", "pat": "pat", "auto": True},
    )
    monkeypatch.setattr(sync_client, "_client", lambda url, pat: http)
    monkeypatch.setattr(sync_client, "_local_root", lambda: root)
    return sync_client


def _stored_baseline():
    rows = _rows("SELECT value FROM sync_meta WHERE key = 'file_sync_baseline'")
    return json.loads(rows[0]["value"]) if rows else {}


def test_run_sync_skips_unwritable_pull_and_reports(replicas, monkeypatch):
    desktop, _ = replicas
    with desktop:
        http = _FakeHttp({"good.md": b"good", "bad | name.md": b"bad"})
        sync_client = _wire_fake_sync(monkeypatch, desktop.root, http)

        real_pull = sync_client._pull_file

        def pull(http_, root_, rel, conflict=False):
            if "|" in rel:  # deterministic stand-in for the Windows EINVAL
                raise OSError(22, "Invalid argument", rel)
            return real_pull(http_, root_, rel, conflict)

        monkeypatch.setattr(sync_client, "_pull_file", pull)
        summary = sync_client.run_sync()

        assert summary["status"] == "ok", summary
        assert (desktop.root / "good.md").read_bytes() == b"good"
        assert summary["files"]["skipped"] == 1
        [err] = summary["files"]["errors"]
        assert err["op"] == "pull"
        assert err["rel"] == "bad | name.md"
        assert "Invalid argument" in err["error"]
        # Skipped pull stays out of the baseline so the next pass retries it.
        baseline = _stored_baseline()
        assert "good.md" in baseline
        assert "bad | name.md" not in baseline


def test_run_sync_failed_push_keeps_rel_out_of_baseline(replicas, monkeypatch):
    desktop, _ = replicas
    with desktop:
        (desktop.root / "note.md").write_text("local work", encoding="utf-8")
        http = _FakeHttp({}, fail_put_rel="note.md")
        sync_client = _wire_fake_sync(monkeypatch, desktop.root, http)

        summary = sync_client.run_sync()

        assert summary["status"] == "ok", summary
        assert summary["files"]["skipped"] == 1
        assert summary["files"]["errors"][0]["op"] == "push"
        # note.md never reached the cloud: it must not enter the baseline,
        # otherwise the next pass would misread the cloud copy as an update.
        baseline = _stored_baseline()
        assert "note.md" not in baseline
        plan = sync.plan_file_sync(sync.file_manifest(desktop.root), {}, baseline)
        assert "note.md" in plan["push"]


# ── contact block exchange ─────────────────────────────────────────────────────

def test_merge_contact_fill_empty_only():
    base = {"name": "Frank", "email": "", "phone": "  ", "github": "gh"}
    incoming = {"name": "Other", "email": "f@x.com", "phone": "555", "city": "Atlanta"}
    merged, filled = sync.merge_contact(base, incoming)
    assert merged == {
        "name": "Frank",       # non-empty never overwritten
        "email": "f@x.com",    # empty filled
        "phone": "555",        # whitespace-only counts as empty
        "github": "gh",        # keys missing from incoming survive
        "city": "Atlanta",     # union of keys
    }
    assert filled == 3
    assert sync.merge_contact({"name": "A"}, {"name": ""}) == ({"name": "A"}, 0)


def _write_desktop_config(root, contact, monkeypatch):
    config_path = root / "config.json"
    config_path.write_text(
        json.dumps({"contact": contact, "cloud_sync_pat": "keep-me"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("JOBCONTEXT_CONFIG", str(config_path))
    return config_path


def test_run_sync_contact_pull_fills_local_config(replicas, monkeypatch):
    desktop, _ = replicas
    with desktop:
        config_path = _write_desktop_config(
            desktop.root, {"name": "", "email": ""}, monkeypatch
        )
        monkeypatch.setattr(cfg, "_cfg", dict(cfg._cfg))  # runtime refresh, no leak
        http = _FakeHttp({}, cloud_contact={"name": "Frank MacBride", "email": "f@x.com"})
        sync_client = _wire_fake_sync(monkeypatch, desktop.root, http)

        summary = sync_client.run_sync()

        assert summary["contact"] == {"status": "ok", "filled_local": 2, "filled_cloud": 0}
        saved = json.loads(config_path.read_text(encoding="utf-8"))
        assert saved["contact"] == {"name": "Frank MacBride", "email": "f@x.com"}
        assert saved["cloud_sync_pat"] == "keep-me"  # machine-local keys survive
        assert cfg._cfg["contact"]["name"] == "Frank MacBride"  # live without restart


def test_run_sync_contact_pushes_local_fields(replicas, monkeypatch):
    desktop, _ = replicas
    with desktop:
        _write_desktop_config(desktop.root, {"name": "Frank", "email": ""}, monkeypatch)
        http = _FakeHttp({}, cloud_contact={"name": "", "email": "f@x.com"})
        sync_client = _wire_fake_sync(monkeypatch, desktop.root, http)

        summary = sync_client.run_sync()

        assert http.contact_posts == [{"name": "Frank", "email": ""}]
        assert http.cloud_contact["name"] == "Frank"
        assert summary["contact"] == {"status": "ok", "filled_local": 1, "filled_cloud": 1}


def test_run_sync_contact_404_is_nonfatal(replicas, monkeypatch):
    """An older cloud without the endpoint must not break the pass."""
    desktop, _ = replicas
    with desktop:
        _write_desktop_config(desktop.root, {"name": ""}, monkeypatch)
        http = _FakeHttp({"doc.md": b"hello"}, contact_404=True)
        sync_client = _wire_fake_sync(monkeypatch, desktop.root, http)

        summary = sync_client.run_sync()

        assert summary["status"] == "ok", summary
        assert summary["contact"] == {"status": "unsupported"}
        assert (desktop.root / "doc.md").read_bytes() == b"hello"  # files still sync


def test_sync_contact_endpoint_merges_and_persists(tmp_path, monkeypatch):
    import asyncio

    from transport.http.routes import sync as sync_routes

    monkeypatch.setattr(sync_routes, "_user_root", lambda: tmp_path)
    (tmp_path / "config.json").write_text(
        json.dumps({"contact": {"name": "", "email": "cloud@x.com"}, "openai_api_key": "sk-keep"}),
        encoding="utf-8",
    )

    out = asyncio.run(
        sync_routes.sync_contact(
            sync_routes.ContactExchange(contact={"name": "Frank", "email": "peer@x.com"}),
            user=None,
        )
    )

    assert out["filled"] == 1
    assert out["contact"] == {"name": "Frank", "email": "cloud@x.com"}
    saved = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert saved["contact"] == {"name": "Frank", "email": "cloud@x.com"}
    assert saved["openai_api_key"] == "sk-keep"  # other keys preserved


def test_sync_contact_endpoint_tolerates_missing_config(tmp_path, monkeypatch):
    import asyncio

    from transport.http.routes import sync as sync_routes

    monkeypatch.setattr(sync_routes, "_user_root", lambda: tmp_path)

    out = asyncio.run(
        sync_routes.sync_contact(
            sync_routes.ContactExchange(contact={"name": "Frank"}), user=None
        )
    )

    assert out == {"contact": {"name": "Frank"}, "filled": 1}
    saved = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert saved["contact"] == {"name": "Frank"}


def _write_employer(name, street="", manual=0):
    with db.get_connection() as con:
        con.execute(
            "INSERT INTO employer_directory (canonical_name, street, city, state, zip,"
            " manual_override, created_at, updated_at)"
            " VALUES (?, ?, 'Atlanta', 'GA', '30303', ?, datetime('now'), datetime('now'))"
            " ON CONFLICT(canonical_name) DO UPDATE SET street=excluded.street,"
            " manual_override=excluded.manual_override, updated_at=excluded.updated_at",
            (name, street, manual),
        )


def _backdate_journal(tbl):
    with db.get_connection() as con:
        con.execute("UPDATE sync_log SET ts = '2020-01-01T00:00:00' WHERE tbl = ?", (tbl,))


def test_manual_override_survives_newer_auto_row(replicas):
    """A peer's failed auto-enrichment (empty row, fresh ts) must never clobber
    a manually corrected address — the lock holds across sync, not just within
    the enrichment pipeline."""
    desktop, cloud = replicas
    with cloud:
        _write_employer("Acme", street="1 Real St", manual=1)
        _backdate_journal("employer_directory")  # make the manual row LWW-losable
    with desktop:
        _write_employer("Acme", street="", manual=0)  # fresh ts: would win LWW
        batch = _export()
    with cloud:
        stats = _apply(batch["changes"])
        rows = _rows(
            "SELECT street, manual_override FROM employer_directory WHERE canonical_name='Acme'"
        )
        assert rows == [{"street": "1 Real St", "manual_override": 1}]
        assert stats["skipped_guard"] >= 1


def test_manual_override_propagates_over_auto_row(replicas):
    """The guard is one-way: an incoming manual correction still replaces a
    peer's auto row via normal LWW."""
    desktop, cloud = replicas
    with desktop:
        _write_employer("Acme", street="", manual=0)
        _backdate_journal("employer_directory")
    with cloud:
        _write_employer("Acme", street="75 5th St NW", manual=1)
        batch = _export()
    with desktop:
        stats = _apply(batch["changes"])
        rows = _rows(
            "SELECT street, manual_override FROM employer_directory WHERE canonical_name='Acme'"
        )
        assert rows == [{"street": "75 5th St NW", "manual_override": 1}]
        assert stats["applied"] >= 1


def _set_apply_flag(applying, since):
    with db.get_connection() as con:
        con.execute(
            "UPDATE sync_state SET applying = ?, applying_since = ? WHERE id = 1",
            (applying, since),
        )


def _flag():
    with db.get_connection() as con:
        return con.execute("SELECT applying FROM sync_state WHERE id = 1").fetchone()[0]


def test_stale_apply_lease_is_released_and_journaling_resumes(replicas):
    """A crash mid-apply (SIGKILL skips the finally) leaves `applying` set, and
    every journal trigger is gated on it — so the partition silently stops
    publishing ANY local write. The lease must expire and journaling resume."""
    desktop, _ = replicas
    with desktop:
        _write_job(company="Before")
        stale = "2020-01-01T00:00:00.000Z"
        _set_apply_flag(1, stale)
        # Opening a connection runs ensure_sync_schema, which reaps the lease.
        assert _flag() == 0
        _write_job(company="After")
        journaled = _rows(
            "SELECT nk FROM sync_log WHERE tbl = 'job_queue' AND origin = 'local'"
        )
        assert any("After" in r["nk"] for r in journaled), journaled
        assert _rows("SELECT value FROM sync_meta WHERE key='last_stale_apply_release'")


def test_live_apply_lease_is_not_stolen(replicas):
    """A genuinely in-flight apply keeps the flag — clearing it would let the
    applying peer's writes journal as local and echo back."""
    desktop, _ = replicas
    with desktop:
        _write_job()
        _set_apply_flag(1, sync._now_ts())
        assert _flag() == 1
        _write_job(company="DuringApply")
        assert not any(
            "DuringApply" in r["nk"]
            for r in _rows("SELECT nk FROM sync_log WHERE origin = 'local'")
        )
        _set_apply_flag(0, "")


def test_apply_changes_stamps_and_clears_the_lease(replicas):
    desktop, cloud = replicas
    with desktop:
        _write_job(company="Leased")
        batch = _export()
    with cloud:
        _apply(batch["changes"])
        row = _rows("SELECT applying, applying_since FROM sync_state WHERE id = 1")
        assert row == [{"applying": 0, "applying_since": ""}]


# ── file deletion tombstones ───────────────────────────────────────────────────
#
# File sync has no delete leg of its own: manifests only describe what exists,
# and the baseline forgets a deletion after one pass — so a deleted file was
# re-pulled from (or re-pushed by) the peer forever. Deletions now journal a
# file_tombstones row and both sides reconcile it against their tree.

_ORPHAN = "workspace/01-Current-Optimized/Orphan_Resume.txt"


def _touch(root, rel, content=b"doc", mtime=None):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def test_delete_synced_file_removes_and_journals(replicas):
    desktop, _ = replicas
    with desktop:
        target = _touch(desktop.root, _ORPHAN)
        with db.get_connection() as con:
            info = sync.delete_synced_file(con, desktop.root, target)
        assert info == {"deleted": True, "rel": _ORPHAN}
        assert not target.exists()
        log = _rows("SELECT tbl, op, origin FROM sync_log WHERE tbl='file_tombstones'")
        assert {"tbl": "file_tombstones", "op": "upsert", "origin": "local"} in log


def test_file_delete_roundtrip_converges_on_absence(replicas):
    """Delete on desktop → tombstone row travels → cloud reconcile removes the
    cloud copy and stops advertising it."""
    desktop, cloud = replicas
    old = time.time() - 3600
    with cloud:
        cloud_copy = _touch(cloud.root, _ORPHAN, mtime=old)
    with desktop:
        target = _touch(desktop.root, _ORPHAN, mtime=old)
        with db.get_connection() as con:
            sync.delete_synced_file(con, desktop.root, target)
        batch = _export()
        assert any(c["tbl"] == "file_tombstones" for c in batch["changes"]), batch
    with cloud:
        _apply(batch["changes"])
        with db.get_connection() as con:
            assert _ORPHAN in sync.list_file_tombstones(con)
            stats = sync.apply_file_tombstones(con, cloud.root)
        assert stats["removed"] == [_ORPHAN]
        assert not cloud_copy.exists()
        assert _ORPHAN not in sync.file_manifest(cloud.root)


def test_recreated_file_clears_the_tombstone(replicas):
    """A file regenerated after its deletion must win: reconcile clears the
    tombstone (journaled, so the clearing reaches the peer) instead of
    deleting the new document."""
    desktop, _ = replicas
    with desktop:
        target = _touch(desktop.root, _ORPHAN)
        with db.get_connection() as con:
            sync.delete_synced_file(con, desktop.root, target)
        first = _export()
        time.sleep(0.02)
        recreated = _touch(desktop.root, _ORPHAN, content=b"regenerated")
        with db.get_connection() as con:
            stats = sync.apply_file_tombstones(con, desktop.root)
        assert stats["cleared"] == [_ORPHAN]
        assert recreated.read_bytes() == b"regenerated"
        with db.get_connection() as con:
            assert sync.list_file_tombstones(con) == {}
        second = _export(since=first["last_id"])
        assert any(
            c["tbl"] == "file_tombstones" and c["op"] == "delete" for c in second["changes"]
        ), second


def test_peer_tombstones_delete_stale_files_without_becoming_rows(replicas):
    """The manifest's tombstone list is a file-level safety net (for rows a
    replica missed on an old build): stale copies go, files newer than the
    deletion stay, and no local row is ever written from it."""
    desktop, _ = replicas
    with desktop:
        stale = _touch(desktop.root, "notes.md", mtime=time.time() - 3600)
        fresh = _touch(desktop.root, "fresh.md")
        peer = {
            "notes.md": {"sha256": "", "deleted_at": sync._now_ts()},
            "fresh.md": {"sha256": "", "deleted_at": "2020-01-01T00:00:00.000000Z"},
        }
        with db.get_connection() as con:
            stats = sync.apply_file_tombstones(con, desktop.root, peer)
        assert stats["removed"] == ["notes.md"]
        assert not stale.exists() and fresh.exists()
        with db.get_connection() as con:
            assert sync.list_file_tombstones(con) == {}


def test_tombstone_rels_cannot_escape_the_root(replicas):
    """rels arrive from the peer via row sync and feed an unlink — traversal,
    absolute, drive-qualified, and backslash forms must never resolve."""
    desktop, _ = replicas
    outside = desktop.root.parent / "victim.txt"
    outside.write_text("keep me", encoding="utf-8")
    evil_ts = sync._now_ts()
    evil = {
        "../victim.txt": {"sha256": "", "deleted_at": evil_ts},
        "a/../../victim.txt": {"sha256": "", "deleted_at": evil_ts},
        "/etc/passwd": {"sha256": "", "deleted_at": evil_ts},
        "C:/victim.txt": {"sha256": "", "deleted_at": evil_ts},
        "": {"sha256": "", "deleted_at": evil_ts},
    }
    with desktop:
        with db.get_connection() as con:
            stats = sync.apply_file_tombstones(con, desktop.root, evil)
        assert stats["removed"] == []
        assert outside.exists()


def test_retention_prunes_ancient_tombstones(replicas):
    desktop, _ = replicas
    with desktop:
        with db.get_connection() as con:
            con.execute(
                "INSERT INTO file_tombstones (rel, sha256, deleted_at) "
                "VALUES ('long-gone.md', '', '2020-01-01T00:00:00.000000Z')"
            )
        with db.get_connection() as con:
            stats = sync.apply_file_tombstones(con, desktop.root)
        assert stats["pruned"] == 1
        with db.get_connection() as con:
            assert sync.list_file_tombstones(con) == {}


def test_strip_tombstoned_entries_blocks_stale_but_not_recreated():
    tomb = {"gone.md": {"sha256": "", "deleted_at": sync._now_ts()}}
    stale = {"size": 1, "mtime": time.time() - 3600, "sha256": "x"}
    recreated = {"size": 1, "mtime": time.time() + 3600, "sha256": "y"}
    assert sync.strip_tombstoned_entries(
        {"gone.md": stale, "keep.md": stale}, tomb
    ) == {"keep.md": stale}
    assert "gone.md" in sync.strip_tombstoned_entries({"gone.md": recreated}, tomb)


def test_run_sync_applies_cloud_tombstones_from_manifest(replicas, monkeypatch):
    """A tombstone arriving only in the manifest response (row missed while on
    an old build) still deletes the stale local copy — and the file must not
    be pushed back afterwards."""
    desktop, _ = replicas
    with desktop:
        stale = _touch(desktop.root, "orphan.md", mtime=time.time() - 3600)
        http = _FakeHttp(
            {}, tombstones={"orphan.md": {"sha256": "", "deleted_at": sync._now_ts()}}
        )
        sync_client = _wire_fake_sync(monkeypatch, desktop.root, http)

        summary = sync_client.run_sync()

        assert summary["status"] == "ok", summary
        assert not stale.exists()
        assert summary["files"]["tombstones"] == {"removed": 1, "cleared": 0, "pruned": 0}
        # Deleted before the local manifest is built, so it can't push back.
        assert "orphan.md" not in _stored_baseline()


def test_run_sync_never_repulls_a_copy_its_tombstone_supersedes(replicas, monkeypatch):
    """Old-cloud scenario: the cloud can't reconcile server-side and keeps
    advertising the deleted file. The deleting side must not pull it back —
    this was the original resurrection loop (baseline forgets after one pass)."""
    desktop, _ = replicas
    with desktop:
        target = _touch(desktop.root, "orphan.md", mtime=time.time() - 3600)
        with db.get_connection() as con:
            sync.delete_synced_file(con, desktop.root, target)
        # The fake cloud still has the copy (manifest mtime=1.0 → ancient) and
        # sends no "tombstones" key at all, like a build predating them.
        http = _FakeHttp({"orphan.md": b"doc"})
        sync_client = _wire_fake_sync(monkeypatch, desktop.root, http)

        summary = sync_client.run_sync()

        assert summary["status"] == "ok", summary
        assert summary["files"]["pull"] == 0
        assert not (desktop.root / "orphan.md").exists()


def test_files_manifest_endpoint_reconciles_and_reports_tombstones(replicas, monkeypatch):
    """The cloud reconciles inside /files/manifest — the client pushes rows
    before requesting it, so a deletion leaves the manifest in the same pass."""
    import asyncio

    from transport.http.routes import sync as sync_routes

    desktop, _ = replicas
    with desktop:
        monkeypatch.setattr(sync_routes, "_user_root", lambda: desktop.root)
        stale = _touch(desktop.root, "doc.md", mtime=time.time() - 3600)
        with db.get_connection() as con:
            con.execute(
                "INSERT INTO file_tombstones (rel, sha256, deleted_at) VALUES (?, ?, ?)",
                ("doc.md", "", sync._now_ts()),
            )

        out = asyncio.run(sync_routes.sync_files_manifest(user=None))

        assert not stale.exists()
        assert "doc.md" not in out["manifest"]
        assert "doc.md" in out["tombstones"]


def test_files_put_endpoint_refuses_stale_content_but_accepts_recreation(replicas, monkeypatch):
    """The guard against old-build peers re-pushing a deleted file: content
    older than the tombstone is refused (success-shaped, so their
    skip-and-report loop stays quiet); newer content is a deliberate
    recreation — stored, and the tombstone clears."""
    import asyncio
    import base64 as b64

    from transport.http.routes import sync as sync_routes

    desktop, _ = replicas
    with desktop:
        monkeypatch.setattr(sync_routes, "_user_root", lambda: desktop.root)
        with db.get_connection() as con:
            con.execute(
                "INSERT INTO file_tombstones (rel, sha256, deleted_at) VALUES (?, ?, ?)",
                ("doc.md", "", sync._now_ts()),
            )

        out = asyncio.run(sync_routes.sync_files_put(
            sync_routes.FilePut(
                rel="doc.md",
                content_b64=b64.b64encode(b"stale copy").decode("ascii"),
                mtime=time.time() - 3600,
            ),
            user=None,
        ))
        assert out["status"] == "tombstoned"
        assert not (desktop.root / "doc.md").exists()

        out = asyncio.run(sync_routes.sync_files_put(
            sync_routes.FilePut(
                rel="doc.md",
                content_b64=b64.b64encode(b"recreated").decode("ascii"),
                mtime=time.time() + 60,
            ),
            user=None,
        ))
        assert out["status"] == "stored"
        assert (desktop.root / "doc.md").read_bytes() == b"recreated"
        with db.get_connection() as con:
            assert sync.list_file_tombstones(con) == {}
