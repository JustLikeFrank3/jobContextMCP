"""Tests for the LangGraph resume tailoring workflow.

Covers:
  - Graph structure: build_resume_graph returns a compiled runnable.
  - End-to-end invoke against the keyless fallback path (no OpenAI required).
  - Streaming emits one event per node, in topological order.
  - Conditional revision loop: empty-draft path triggers revise then exits
    after max_revisions.
  - WorkflowService.run wiring emits starting + per-node + complete events.
"""

import pytest

from services import WorkflowService, ProgressEvent
from workflows.langgraph import build_resume_graph

_FAKE_RESUME = "✓ Resume generated for Test Co — Staff Engineer\n\nSummary: ..."


def _capture():
    events: list[ProgressEvent] = []
    return events, events.append


class TestResumeGraph:
    def test_graph_builds(self):
        g = build_resume_graph()
        assert g is not None
        # Compiled graph exposes invoke / stream.
        assert hasattr(g, "invoke")
        assert hasattr(g, "stream")

    def test_invoke_produces_final_state(self, isolated_server):
        g = build_resume_graph()
        state = g.invoke({
            "company": "Stripe",
            "role": "Staff Engineer",
            "job_description": "Build payments infrastructure.",
        })
        # Required keys populated by load_context.
        assert "master_context" in state
        assert "tone_profile" in state
        assert "strategy" in state
        assert "interview_context" in state
        # Draft + output ran.
        assert "draft" in state
        assert "final_content" in state
        assert isinstance(state["final_content"], str) and state["final_content"]

    def test_stream_emits_each_node_in_order(self, isolated_server):
        g = build_resume_graph()
        node_names = []
        for update in g.stream(
            {
                "company": "Stripe",
                "role": "Staff Engineer",
                "job_description": "Build payments infrastructure.",
            },
            stream_mode="updates",
        ):
            node_names.extend(update.keys())
        # Expected base path: load_context → draft → review → output.
        # Revision loop is not triggered for a non-empty draft.
        assert node_names[0] == "load_context"
        assert "draft" in node_names
        assert "review" in node_names
        assert node_names[-1] == "output"


class TestRevisionLoop:
    def test_revise_path_runs_when_draft_starts_with_error_marker(
        self, isolated_server, monkeypatch
    ):
        """Force the review node to fail by stubbing the draft node to emit an
        error-marker string. The conditional edge should route to revise once,
        then exit after max_revisions."""
        from workflows.langgraph import resume_graph as rg

        call_count = {"n": 0}

        def fake_generate_resume(**_kwargs):
            call_count["n"] += 1
            # First call: error marker → review fails → revise.
            # Second call (from revise): clean output → review passes → output.
            return "✗ OpenAI API error: simulated" if call_count["n"] == 1 else "✓ Resume generated for Test"

        monkeypatch.setattr(rg, "generate_resume", fake_generate_resume)

        g = build_resume_graph()
        state = g.invoke({
            "company": "X",
            "role": "Y",
            "job_description": "JD",
            "max_revisions": 1,
        })
        assert state["revisions"] == 1
        assert state["success"] is True
        assert call_count["n"] == 2

    def test_no_revision_when_max_revisions_zero(
        self, isolated_server, monkeypatch
    ):
        from workflows.langgraph import resume_graph as rg

        monkeypatch.setattr(
            rg, "generate_resume",
            lambda **_k: "✗ error",
        )
        g = build_resume_graph()
        state = g.invoke({
            "company": "X",
            "role": "Y",
            "job_description": "JD",
            "max_revisions": 0,
        })
        # No revision attempted even though review found a problem.
        assert state.get("revisions", 0) == 0
        assert state["final_content"].startswith("✗")


class TestWorkflowServiceRun:
    def test_emits_starting_node_and_complete_events(self, isolated_server):
        events, cb = _capture()
        result = WorkflowService.run(
            "resume_tailoring",
            {
                "company": "Stripe",
                "role": "Staff Engineer",
                "job_description": "Build payments infrastructure.",
            },
            on_progress=cb,
        )
        stages = [e.stage for e in events]
        assert stages[0] == "starting"
        assert "load_context" in stages
        assert "draft" in stages
        assert "review" in stages
        assert "output" in stages
        assert stages[-1] == "complete"
        assert "final_content" in result
        assert result.get("final_content")

    def test_starting_event_truncates_long_jd(self, isolated_server):
        events, cb = _capture()
        long_jd = "x" * 500
        WorkflowService.run(
            "resume_tailoring",
            {"company": "X", "role": "Y", "job_description": long_jd},
            on_progress=cb,
        )
        starting = events[0]
        assert starting.stage == "starting"
        truncated = starting.payload["inputs"]["job_description"]
        assert truncated.endswith("...")
        assert len(truncated) <= 120
