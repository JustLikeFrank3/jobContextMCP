"""
Tests for the services/ orchestration layer.

Services are thin wrappers around tools/ that emit ProgressEvents around
multi-step pipelines. These tests verify:
  - orchestration calls underlying tools correctly
  - progress events fire in the expected order with correct stages
  - structured result dataclasses are populated as documented
  - the WorkflowService stub raises NotImplementedError but emits an event

The `isolated_server` fixture is used because services call real tool
functions which read/write JSON files under config paths.
"""

import pytest

from services import (
    JobAnalysisService,
    AnalysisResult,
    ProgressEvent,
    ResumeService,
    ResumeResult,
    WorkflowService,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _capture():
    """Return (events_list, callback) for capturing emitted ProgressEvents."""
    events: list[ProgressEvent] = []
    return events, events.append


# ──────────────────────────────────────────────────────────────────────────────
# ProgressEvent contract
# ──────────────────────────────────────────────────────────────────────────────

class TestProgressEvent:
    def test_event_carries_stage_message_and_payload(self):
        e = ProgressEvent(stage="x", message="m", payload={"k": 1})
        assert e.stage == "x"
        assert e.message == "m"
        assert e.payload == {"k": 1}

    def test_payload_defaults_to_empty_dict(self):
        e = ProgressEvent(stage="x", message="m")
        assert e.payload == {}

    def test_event_is_frozen(self):
        e = ProgressEvent(stage="x", message="m")
        with pytest.raises((AttributeError, Exception)):
            e.stage = "y"  # type: ignore[misc]


# ──────────────────────────────────────────────────────────────────────────────
# ResumeService — runs against the real generate tool which falls back to a
# context package when no OpenAI key is configured. Tests verify orchestration
# and event emission, not LLM output content.
# ──────────────────────────────────────────────────────────────────────────────

class TestResumeService:
    def test_generate_resume_emits_start_and_complete_events(self, isolated_server):
        events, cb = _capture()
        result = ResumeService.generate(
            company="Stripe",
            role="Staff Engineer",
            job_description="Build payments infrastructure.",
            kind="resume",
            on_progress=cb,
        )
        stages = [e.stage for e in events]
        assert stages[0] == "starting"
        assert "generating" in stages
        assert stages[-1] == "complete"
        assert isinstance(result, ResumeResult)
        assert result.company == "Stripe"
        assert result.role == "Staff Engineer"
        assert result.kind == "resume"
        assert isinstance(result.content, str) and result.content

    def test_generate_cover_letter_uses_cover_letter_kind(self, isolated_server):
        events, cb = _capture()
        result = ResumeService.generate(
            company="Stripe",
            role="Staff Engineer",
            job_description="Build payments infrastructure.",
            kind="cover_letter",
            on_progress=cb,
        )
        assert result.kind == "cover_letter"
        # starting event payload includes kind
        assert events[0].payload.get("kind") == "cover_letter"

    def test_generate_rejects_invalid_kind(self, isolated_server):
        with pytest.raises(ValueError, match="kind must be"):
            ResumeService.generate(
                company="X", role="Y", job_description="z", kind="invalid",
            )

    def test_generate_works_without_progress_callback(self, isolated_server):
        # No callback should not raise.
        result = ResumeService.generate(
            company="Stripe",
            role="Staff Engineer",
            job_description="JD text",
            kind="resume",
            on_progress=None,
        )
        assert isinstance(result, ResumeResult)

    def test_starting_event_payload_includes_company_and_role(self, isolated_server):
        events, cb = _capture()
        ResumeService.generate(
            company="Stripe", role="Staff Engineer", job_description="JD",
            kind="resume", on_progress=cb,
        )
        starting = events[0]
        assert starting.stage == "starting"
        assert starting.payload["company"] == "Stripe"
        assert starting.payload["role"] == "Staff Engineer"


# ──────────────────────────────────────────────────────────────────────────────
# JobAnalysisService
# ──────────────────────────────────────────────────────────────────────────────

class TestJobAnalysisService:
    def test_evaluate_queues_and_assesses_new_job(self, isolated_server):
        events, cb = _capture()
        result = JobAnalysisService.evaluate(
            company="Stripe",
            role="Staff Engineer",
            job_description="Build payments infrastructure.",
            source="linkedin",
            on_progress=cb,
        )
        stages = [e.stage for e in events]
        assert stages == ["queuing", "queued", "evaluating", "complete"]
        assert isinstance(result, AnalysisResult)
        assert result.queued is True
        assert result.evaluated is True
        assert result.queue_status == "evaluated"
        assert "Stripe" in result.fitment_context
        # queued event reports new entry
        queued_event = next(e for e in events if e.stage == "queued")
        assert queued_event.payload["already_queued"] is False

    def test_evaluate_reuses_existing_queue_entry(self, isolated_server):
        # First call queues + evaluates → status becomes "evaluated"
        JobAnalysisService.evaluate(
            company="Stripe", role="Staff Engineer", job_description="JD",
        )
        # Second call sees it as already queued
        events, cb = _capture()
        result = JobAnalysisService.evaluate(
            company="Stripe", role="Staff Engineer", job_description="JD",
            on_progress=cb,
        )
        queued_event = next(e for e in events if e.stage == "queued")
        assert queued_event.payload["already_queued"] is True
        # Re-evaluation still produces fitment context (status remains "evaluated")
        assert result.evaluated is True

    def test_evaluate_skips_when_already_decided(self, isolated_server):
        import server as srv
        import json
        srv.queue_job("Stripe", "Staff Engineer", "JD")
        # Force-decide the entry
        data = json.loads(srv.JOB_QUEUE_FILE.read_text())
        data["jobs"][0]["status"] = "added"
        srv.JOB_QUEUE_FILE.write_text(json.dumps(data))

        result = JobAnalysisService.evaluate(
            company="Stripe", role="Staff Engineer", job_description="JD",
        )
        assert result.evaluated is False
        assert result.queue_status == "decided"
        assert any("already decided" in n for n in result.notes)

    def test_assess_runs_standalone_fitment(self, isolated_server):
        events, cb = _capture()
        result = JobAnalysisService.assess(
            company="Stripe", role="Staff Engineer", job_description="JD",
            on_progress=cb,
        )
        stages = [e.stage for e in events]
        assert stages == ["assessing", "complete"]
        assert "Stripe" in result

    def test_decide_emits_events_and_records_decision(self, isolated_server):
        JobAnalysisService.evaluate(
            company="Stripe", role="Staff Engineer", job_description="JD",
        )
        events, cb = _capture()
        result = JobAnalysisService.decide(
            company="Stripe", role="Staff Engineer", decision="dismiss",
            notes="not a fit", on_progress=cb,
        )
        stages = [e.stage for e in events]
        assert stages == ["deciding", "complete"]
        assert "Dismissed" in result


# ──────────────────────────────────────────────────────────────────────────────
# WorkflowService (Phase C — now wired to LangGraph)
# ──────────────────────────────────────────────────────────────────────────────

class TestWorkflowService:
    def test_list_workflows_contains_resume_tailoring(self):
        assert "resume_tailoring" in WorkflowService.list_workflows()

    def test_unknown_workflow_raises(self):
        from services import UnknownWorkflowError
        with pytest.raises(UnknownWorkflowError, match="Unknown workflow"):
            WorkflowService.run("nonexistent", {})

    def test_unknown_workflow_does_not_emit_node_events(self):
        from services import UnknownWorkflowError
        events, cb = _capture()
        with pytest.raises(UnknownWorkflowError):
            WorkflowService.run("nope", {}, on_progress=cb)
        # No starting/node/complete events for an unknown workflow.
        assert events == []
