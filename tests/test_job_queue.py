"""
Tests for job queue / evaluation pipeline tools.

Tools under test:
  queue_job, get_job_queue, evaluate_queued_job, decide_job
"""

import json

import pytest

import server as srv


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
