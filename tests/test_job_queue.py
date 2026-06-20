"""
Tests for job queue / evaluation pipeline tools.

Tools under test:
  queue_job, get_job_queue, evaluate_queued_job, decide_job

Section 1 (TestQueueJob … TestDecideJob) — JSON-path behaviour, isolated_server.
Section 2 (TestJobQueueSQLite) — SQLite write/read round-trips with a real DB,
  verifying that queue_job/decide_job write to both the DB and the JSON replica
  and that explicit deletes (decide_job) remove from the DB but omitting a job
  from a payload does NOT (upsert-only, no sync-delete).
"""

import json
import sqlite3

import pytest

import server as srv


# ── Helpers ────────────────────────────────────────────────────────────────────

def _seed_db(data_dir):
    """Create a fresh SQLite DB with the full schema under data_dir."""
    from scripts.migrate_to_sqlite import _SCHEMA
    db = data_dir / "jobcontextmcp.db"
    con = sqlite3.connect(db)
    con.executescript(_SCHEMA)
    con.commit()
    con.close()
    return db


class TestQueueJob:
    def test_adds_pending_entry(self, isolated_server):
        result = srv.queue_job("Stripe", "Staff Engineer", "We need a staff engineer...")
        assert "Queued" in result
        assert "Stripe" in result

        data = json.loads(srv.JOB_QUEUE_FILE.read_text())
        jobs = data["jobs"]
        assert len(jobs) == 1
        assert jobs[0]["company"] == "Stripe"
        assert jobs[0]["role"] == "Staff Engineer"
        assert jobs[0]["status"] == "pending"
        assert jobs[0]["jd"] == "We need a staff engineer..."

    def test_optional_source_stored(self, isolated_server):
        srv.queue_job("Stripe", "Staff Engineer", "JD text", source="LinkedIn")
        data = json.loads(srv.JOB_QUEUE_FILE.read_text())
        assert data["jobs"][0]["source"] == "LinkedIn"

    def test_duplicate_returns_already_queued_message(self, isolated_server):
        srv.queue_job("Stripe", "Staff Engineer", "JD text")
        result = srv.queue_job("Stripe", "Staff Engineer", "different JD")
        assert "Already queued" in result

    def test_ids_auto_increment(self, isolated_server):
        srv.queue_job("Stripe", "Staff Engineer", "JD A")
        srv.queue_job("Acme", "Backend Engineer", "JD B")
        data = json.loads(srv.JOB_QUEUE_FILE.read_text())
        ids = [j["id"] for j in data["jobs"]]
        assert ids == [1, 2]


class TestGetJobQueue:
    def test_empty_queue(self, isolated_server):
        result = srv.get_job_queue()
        assert "No jobs in queue" in result

    def test_returns_queued_job(self, isolated_server):
        srv.queue_job("Stripe", "Staff Engineer", "JD text")
        result = srv.get_job_queue()
        assert "Stripe" in result
        assert "PENDING" in result

    def test_filters_by_status(self, isolated_server):
        srv.queue_job("Stripe", "Staff Engineer", "JD A")
        srv.queue_job("Acme", "Backend Engineer", "JD B")
        # Manually promote one to evaluated
        data = json.loads(srv.JOB_QUEUE_FILE.read_text())
        data["jobs"][1]["status"] = "evaluated"
        srv.JOB_QUEUE_FILE.write_text(json.dumps(data))

        result = srv.get_job_queue(status="pending")
        assert "Stripe" in result
        assert "Acme" not in result

    def test_no_match_for_status_filter(self, isolated_server):
        srv.queue_job("Stripe", "Staff Engineer", "JD text")
        result = srv.get_job_queue(status="dismissed")
        assert "No jobs in queue" in result


class TestEvaluateQueuedJob:
    def test_sets_status_to_evaluated(self, isolated_server):
        srv.queue_job("Stripe", "Staff Engineer", "Engineer at Stripe.")
        srv.evaluate_queued_job("Stripe", "Staff Engineer")

        data = json.loads(srv.JOB_QUEUE_FILE.read_text())
        assert data["jobs"][0]["status"] == "evaluated"

    def test_returns_fitment_context(self, isolated_server):
        srv.queue_job("Stripe", "Staff Engineer", "Engineer at Stripe.")
        result = srv.evaluate_queued_job("Stripe", "Staff Engineer")
        assert "Stripe" in result
        assert "Staff Engineer" in result

    def test_missing_job_returns_error(self, isolated_server):
        result = srv.evaluate_queued_job("NoSuchCo", "Ghost Role")
        assert "No queued job found" in result

    def test_already_decided_returns_message(self, isolated_server):
        srv.queue_job("Stripe", "Staff Engineer", "JD text")
        data = json.loads(srv.JOB_QUEUE_FILE.read_text())
        data["jobs"][0]["status"] = "added"
        srv.JOB_QUEUE_FILE.write_text(json.dumps(data))

        result = srv.evaluate_queued_job("Stripe", "Staff Engineer")
        assert "already decided" in result


class TestDecideJob:
    def _make_evaluated_job(self, company="Stripe", role="Staff Engineer"):
        srv.queue_job(company, role, "JD text")
        srv.evaluate_queued_job(company, role)

    def test_add_creates_application_as_interested(self, isolated_server):
        self._make_evaluated_job()
        result = srv.decide_job("Stripe", "Staff Engineer", "add")
        assert "interested" in result.lower()

        pipeline = json.loads(srv.STATUS_FILE.read_text())
        apps = pipeline["applications"]
        assert any(
            a["company"] == "Stripe" and a["status"] == "interested"
            for a in apps
        )

    def test_add_removes_job_from_queue(self, isolated_server):
        self._make_evaluated_job()
        srv.decide_job("Stripe", "Staff Engineer", "add")

        data = json.loads(srv.JOB_QUEUE_FILE.read_text())
        assert data["jobs"] == []

    def test_dismiss_removes_job_from_queue(self, isolated_server):
        self._make_evaluated_job()
        srv.decide_job("Stripe", "Staff Engineer", "dismiss", notes="Comp too low")

        data = json.loads(srv.JOB_QUEUE_FILE.read_text())
        assert data["jobs"] == []

    def test_dismiss_does_not_touch_status_file(self, isolated_server):
        self._make_evaluated_job()
        srv.decide_job("Stripe", "Staff Engineer", "dismiss")

        pipeline = json.loads(srv.STATUS_FILE.read_text())
        assert pipeline["applications"] == []

    def test_gate_blocks_pending_job(self, isolated_server):
        srv.queue_job("Stripe", "Staff Engineer", "JD text")
        result = srv.decide_job("Stripe", "Staff Engineer", "add")
        assert "not been evaluated" in result

        # Confirm no application was created
        pipeline = json.loads(srv.STATUS_FILE.read_text())
        assert pipeline["applications"] == []

    def test_invalid_decision_returns_error(self, isolated_server):
        self._make_evaluated_job()
        result = srv.decide_job("Stripe", "Staff Engineer", "maybe")
        assert "Invalid decision" in result

    def test_fitment_score_stored_in_pipeline(self, isolated_server):
        self._make_evaluated_job()
        srv.decide_job("Stripe", "Staff Engineer", "add", fitment_score="8/10")

        # Job is removed from queue; score should be on the pipeline app
        data = json.loads(srv.JOB_QUEUE_FILE.read_text())
        assert data["jobs"] == []

    def test_double_add_returns_not_found(self, isolated_server):
        self._make_evaluated_job()
        srv.decide_job("Stripe", "Staff Engineer", "add")
        result = srv.decide_job("Stripe", "Staff Engineer", "add")
        assert "No queued job found" in result

    def test_missing_job_returns_error(self, isolated_server):
        result = srv.decide_job("Ghost", "No Role", "add")
        assert "No queued job found" in result


# ── Section 2: SQLite write/read round-trips ───────────────────────────────────

class TestJobQueueSQLite:
    """
    Verifies that queue_job / decide_job write to both SQLite and the JSON
    replica, that load_from_sqlite reads back what was written, and that
    sync-delete (omitting a job from a save payload removes it from the DB)
    works correctly — this is what makes the pipeline /remove endpoint work.
    """

    @pytest.fixture()
    def sqlite_server(self, isolated_server, monkeypatch):
        """isolated_server + a fresh DB + SQLite writes enabled."""
        import lib.db as db_mod
        import lib.io as io_mod

        data_dir = isolated_server / "data"
        db = _seed_db(data_dir)

        monkeypatch.setattr(db_mod, "db_path", lambda: db)
        monkeypatch.setattr(io_mod, "_USE_SQLITE", True)
        return isolated_server

    # ── queue_job writes to DB ─────────────────────────────────────────────

    def test_queue_job_writes_to_db(self, sqlite_server, monkeypatch):
        """queue_job stores the job in the SQLite job_queue table."""
        import lib.db as db_mod
        from lib.io_sqlite import load_from_sqlite

        srv.queue_job("Acme", "ML Engineer", "We build AI things.")

        result = load_from_sqlite(srv.JOB_QUEUE_FILE, {})
        jobs = result.get("jobs", [])
        assert len(jobs) == 1
        assert jobs[0]["company"] == "Acme"
        assert jobs[0]["role"] == "ML Engineer"
        assert jobs[0]["status"] == "pending"

    def test_queue_job_writes_json_replica(self, sqlite_server):
        """queue_job atomically updates the JSON replica alongside the DB write."""
        srv.queue_job("Acme", "ML Engineer", "JD text")

        data = json.loads(srv.JOB_QUEUE_FILE.read_text())
        jobs = data.get("jobs", [])
        assert len(jobs) == 1
        assert jobs[0]["company"] == "Acme"

    def test_db_and_json_replica_are_consistent(self, sqlite_server):
        """DB and JSON replica contain identical job sets after a write."""
        from lib.io_sqlite import load_from_sqlite

        srv.queue_job("Alpha", "SWE I",  "JD A")
        srv.queue_job("Beta",  "SWE II", "JD B")

        db_jobs   = load_from_sqlite(srv.JOB_QUEUE_FILE, {}).get("jobs", [])
        json_jobs = json.loads(srv.JOB_QUEUE_FILE.read_text()).get("jobs", [])

        db_ids   = {j["id"] for j in db_jobs}
        json_ids = {j["id"] for j in json_jobs}
        assert db_ids == json_ids
        assert {j["company"] for j in db_jobs} == {"Alpha", "Beta"}

    # ── upsert-only: omitting a job must NOT delete it ─────────────────────

    def test_save_subset_removes_omitted_jobs(self, sqlite_server):
        """Saving a subset of jobs removes the omitted ones — this is the sync-delete
        behaviour that makes the pipeline /remove endpoint actually work in SQLite mode."""
        from lib.io_sqlite import save_to_sqlite, load_from_sqlite

        save_to_sqlite(srv.JOB_QUEUE_FILE, {
            "jobs": [
                {"id": 10, "company": "Keep", "role": "SWE", "status": "pending"},
                {"id": 11, "company": "Remove", "role": "SWE", "status": "evaluated"},
            ]
        })
        # Save only job 10 — job 11 must be removed (sync-delete)
        save_to_sqlite(srv.JOB_QUEUE_FILE, {
            "jobs": [{"id": 10, "company": "Keep", "role": "SWE", "status": "pending"}]
        })

        result = load_from_sqlite(srv.JOB_QUEUE_FILE, {})
        ids = {j["id"] for j in result["jobs"]}
        assert ids == {10}, f"Expected only job 10 after removal, got {ids}"

    # ── decide_job: explicit deletes hit the DB ────────────────────────────

    def test_decide_add_removes_from_db(self, sqlite_server):
        """decide_job('add') explicitly deletes the job from the DB."""
        from lib.io_sqlite import load_from_sqlite

        srv.queue_job("Stripe", "Staff Engineer", "JD text")
        srv.evaluate_queued_job("Stripe", "Staff Engineer")
        srv.decide_job("Stripe", "Staff Engineer", "add")

        result = load_from_sqlite(srv.JOB_QUEUE_FILE, {})
        companies = [j["company"] for j in result.get("jobs", [])]
        assert "Stripe" not in companies

    def test_decide_dismiss_removes_from_db(self, sqlite_server):
        """decide_job('dismiss') explicitly deletes the job from the DB."""
        from lib.io_sqlite import load_from_sqlite

        srv.queue_job("Stripe", "Staff Engineer", "JD text")
        srv.evaluate_queued_job("Stripe", "Staff Engineer")
        srv.decide_job("Stripe", "Staff Engineer", "dismiss")

        result = load_from_sqlite(srv.JOB_QUEUE_FILE, {})
        companies = [j["company"] for j in result.get("jobs", [])]
        assert "Stripe" not in companies

    def test_decide_only_removes_decided_job(self, sqlite_server):
        """decide_job must only remove the target job, leaving others intact."""
        from lib.io_sqlite import load_from_sqlite

        srv.queue_job("Keep Co",  "SWE", "JD A")
        srv.queue_job("Drop Co",  "SWE", "JD B")
        srv.evaluate_queued_job("Drop Co", "SWE")
        srv.decide_job("Drop Co", "SWE", "dismiss")

        result = load_from_sqlite(srv.JOB_QUEUE_FILE, {})
        companies = [j["company"] for j in result.get("jobs", [])]
        assert "Keep Co" in companies
        assert "Drop Co" not in companies

    # ── evaluate_queued_job updates status in DB ───────────────────────────

    def test_evaluate_updates_status_in_db(self, sqlite_server):
        """evaluate_queued_job flips status to 'evaluated' in the DB."""
        from lib.io_sqlite import load_from_sqlite

        srv.queue_job("Nimble", "AI Architect", "JD text")
        srv.evaluate_queued_job("Nimble", "AI Architect")

        result = load_from_sqlite(srv.JOB_QUEUE_FILE, {})
        job = next(j for j in result["jobs"] if j["company"] == "Nimble")
        assert job["status"] == "evaluated"


class TestJobQueueTenantIsolation:
    """Regression tests for the JSON replica path isolation bug.

    Before the fix, _save_job_queue always wrote the JSON replica to the
    global config.JOB_QUEUE_FILE regardless of which tenant's session
    triggered the save. This means tenant A's save would overwrite tenant B's
    file (and the global file) with A's data.
    """

    @pytest.fixture()
    def tenant_env(self, tmp_path, monkeypatch):
        """Patch DB, config paths, and activate a per-user data folder override."""
        import lib.db as db_mod
        import lib.config as cfg
        import lib.user_context as uctx

        # Global data folder (owner / default)
        global_data = tmp_path / "data"
        global_data.mkdir()

        # Tenant's isolated data folder (what UserDataContextMiddleware sets)
        tenant_data = tmp_path / "data" / "users" / "tenant-oid-123"
        (tenant_data / "db").mkdir(parents=True)

        # Build DB under tenant's db/ subdir (where get_connection resolves it
        # when the data-folder override is active)
        from scripts.migrate_to_sqlite import _SCHEMA
        tenant_db = tenant_data / "db" / "jobcontextmcp.db"
        con = sqlite3.connect(tenant_db)
        con.executescript(_SCHEMA)
        con.commit()
        con.close()

        monkeypatch.setattr(cfg, "DATA_FOLDER", global_data)
        monkeypatch.setattr(cfg, "JOB_QUEUE_FILE", global_data / "job_queue.json")

        # Activate the tenant override (simulates UserDataContextMiddleware)
        token = uctx.set_data_folder(tenant_data)
        yield global_data, tenant_data
        uctx.reset_data_folder(token)

    def test_json_replica_goes_to_tenant_folder(self, tenant_env):
        """JSON replica must be written to the tenant's folder, not the global path."""
        from lib.io_sqlite import save_to_sqlite
        import lib.config as cfg

        global_data, tenant_data = tenant_env

        save_to_sqlite(cfg.JOB_QUEUE_FILE, {
            "jobs": [{"id": 1, "company": "TenantCo", "role": "SWE", "status": "pending"}]
        })

        tenant_replica = tenant_data / "job_queue.json"
        global_replica = global_data / "job_queue.json"

        assert tenant_replica.exists(), "JSON replica must exist in the tenant's data folder"
        assert not global_replica.exists(), "JSON replica must NOT be written to the global path"

        data = json.loads(tenant_replica.read_text())
        assert data["jobs"][0]["company"] == "TenantCo"

    def test_global_path_unaffected_by_tenant_save(self, tenant_env, tmp_path):
        """A pre-existing global job_queue.json is not overwritten by a tenant save."""
        from lib.io_sqlite import save_to_sqlite
        import lib.config as cfg

        global_data, tenant_data = tenant_env

        # Seed an owner job in the global file
        owner_data = {"jobs": [{"id": 99, "company": "OwnerCo", "role": "CTO", "status": "pending"}]}
        (global_data / "job_queue.json").write_text(json.dumps(owner_data))

        # Tenant saves their own job
        save_to_sqlite(cfg.JOB_QUEUE_FILE, {
            "jobs": [{"id": 1, "company": "TenantCo", "role": "SWE", "status": "pending"}]
        })

        # Global file must be unchanged
        global_content = json.loads((global_data / "job_queue.json").read_text())
        assert global_content["jobs"][0]["company"] == "OwnerCo", (
            "Tenant save must not overwrite the global job_queue.json"
        )
