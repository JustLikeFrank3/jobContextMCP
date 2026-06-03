"""Tests for the FastAPI HTTP transport.

Covers:
  - health endpoint (unauthenticated)
  - API key auth (missing / wrong / valid / disabled)
  - jobs/evaluate end-to-end against real services + tmp filesystem
  - resumes/generate end-to-end (keyless fallback path)
  - context endpoints (stories, tone)
  - SSE streaming envelope and stage ordering
"""

import json
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

import server as srv  # noqa: F401 — imported so isolated_server fixture works
from transport.http.app import create_app
from transport.http.config import reset_settings_cache


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-key"}


# ──────────────────────────────────────────────────────────────────────────────
# Health
# ──────────────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_open_when_auth_disabled(self, http_client_noauth):
        r = http_client_noauth.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["service"] == "jobContextMCP"
        assert body["auth_enabled"] is False

    def test_health_open_when_auth_enabled(self, http_client_authed):
        # Health must NOT require auth so load balancers can probe it.
        r = http_client_authed.get("/health")
        assert r.status_code == 200
        assert r.json()["auth_enabled"] is True


# ──────────────────────────────────────────────────────────────────────────────
# Authentication
# ──────────────────────────────────────────────────────────────────────────────

class TestAuth:
    def test_missing_authorization_rejected(self, http_client_authed):
        r = http_client_authed.post("/jobs/evaluate", json={
            "company": "X", "role": "Y", "job_description": "z",
        })
        assert r.status_code == 401
        assert "Missing credentials" in r.json()["detail"]

    def test_wrong_key_rejected(self, http_client_authed):
        r = http_client_authed.post(
            "/jobs/evaluate",
            headers={"Authorization": "Bearer wrong"},
            json={"company": "X", "role": "Y", "job_description": "z"},
        )
        assert r.status_code == 401
        assert "Invalid credentials" in r.json()["detail"]

    def test_valid_key_accepted(self, http_client_authed):
        r = http_client_authed.post(
            "/jobs/evaluate",
            headers=_auth_headers(),
            json={"company": "Stripe", "role": "Staff Engineer", "job_description": "JD"},
        )
        assert r.status_code == 200

    def test_bare_token_without_bearer_prefix_accepted(self, http_client_authed):
        r = http_client_authed.post(
            "/jobs/evaluate",
            headers={"Authorization": "test-key"},
            json={"company": "Stripe", "role": "Staff Engineer", "job_description": "JD"},
        )
        assert r.status_code == 200

    def test_auth_disabled_passes_through(self, http_client_noauth):
        r = http_client_noauth.post(
            "/jobs/evaluate",
            json={"company": "Stripe", "role": "Staff Engineer", "job_description": "JD"},
        )
        assert r.status_code == 200


# ──────────────────────────────────────────────────────────────────────────────
# /jobs/evaluate
# ──────────────────────────────────────────────────────────────────────────────

class TestJobsEvaluate:
    def test_evaluate_returns_full_result(self, http_client_noauth):
        r = http_client_noauth.post("/jobs/evaluate", json={
            "company": "Stripe",
            "role": "Staff Engineer",
            "job_description": "Build payments infrastructure.",
            "source": "linkedin",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["company"] == "Stripe"
        assert body["role"] == "Staff Engineer"
        assert body["queued"] is True
        assert body["evaluated"] is True
        assert body["queue_status"] == "evaluated"
        assert "Stripe" in body["fitment_context"]

    def test_evaluate_validates_required_fields(self, http_client_noauth):
        r = http_client_noauth.post("/jobs/evaluate", json={"company": ""})
        assert r.status_code == 422


# ──────────────────────────────────────────────────────────────────────────────
# /jobs/decide
# ──────────────────────────────────────────────────────────────────────────────

class TestJobsDecide:
    def test_decide_dismiss_after_evaluate(self, http_client_noauth):
        http_client_noauth.post("/jobs/evaluate", json={
            "company": "Stripe", "role": "Staff Engineer", "job_description": "JD",
        })
        r = http_client_noauth.post("/jobs/decide", json={
            "company": "Stripe", "role": "Staff Engineer",
            "decision": "dismiss", "notes": "not a fit",
        })
        assert r.status_code == 200
        assert "Dismissed" in r.json()["result"]

    def test_decide_rejects_invalid_decision(self, http_client_noauth):
        r = http_client_noauth.post("/jobs/decide", json={
            "company": "X", "role": "Y", "decision": "maybe",
        })
        assert r.status_code == 422


# ──────────────────────────────────────────────────────────────────────────────
# /resumes/generate
# ──────────────────────────────────────────────────────────────────────────────

class TestResumesGenerate:
    def test_generate_resume_keyless_fallback(self, http_client_noauth):
        r = http_client_noauth.post("/resumes/generate", json={
            "company": "Stripe",
            "role": "Staff Engineer",
            "job_description": "Build payments.",
            "kind": "resume",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["company"] == "Stripe"
        assert body["kind"] == "resume"
        assert isinstance(body["content"], str) and body["content"]

    def test_generate_cover_letter_kind(self, http_client_noauth):
        r = http_client_noauth.post("/resumes/generate", json={
            "company": "Stripe", "role": "Staff Engineer",
            "job_description": "JD", "kind": "cover_letter",
        })
        assert r.status_code == 200
        assert r.json()["kind"] == "cover_letter"

    def test_generate_rejects_invalid_kind(self, http_client_noauth):
        r = http_client_noauth.post("/resumes/generate", json={
            "company": "X", "role": "Y", "job_description": "z", "kind": "wat",
        })
        assert r.status_code == 422


# ──────────────────────────────────────────────────────────────────────────────
# /stories/search + /tone/profile
# ──────────────────────────────────────────────────────────────────────────────

class TestContextEndpoints:
    def test_stories_search_returns_text(self, http_client_noauth):
        r = http_client_noauth.post("/stories/search", json={"tag": "leadership"})
        assert r.status_code == 200
        body = r.json()
        assert body["tag"] == "leadership"
        assert isinstance(body["results"], str)

    def test_tone_profile_returns_text(self, http_client_noauth):
        r = http_client_noauth.get("/tone/profile")
        assert r.status_code == 200
        assert isinstance(r.json()["profile"], str)


# ──────────────────────────────────────────────────────────────────────────────
# Dashboard endpoints
# ──────────────────────────────────────────────────────────────────────────────

class TestDashboardEndpoints:
    def test_job_hunt_dashboard_page_renders(self, http_client_noauth):
        r = http_client_noauth.get("/dashboard/job-hunt")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Job Hunt Tracker" in r.text

    def test_job_hunt_dashboard_data_shape(self, http_client_noauth):
        r = http_client_noauth.get("/dashboard/job-hunt/data")
        assert r.status_code == 200
        body = r.json()
        assert "applications" in body
        assert "by_status" in body
        assert "total" in body

    def test_materials_dashboard_page_renders(self, http_client_noauth):
        r = http_client_noauth.get("/dashboard/materials")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Materials" in r.text

    def test_materials_dashboard_data_shape(self, http_client_noauth):
        r = http_client_noauth.get("/dashboard/materials/data")
        assert r.status_code == 200
        body = r.json()
        assert "folders" in body
        assert "optimized_resumes" in body
        assert "cover_letters" in body
        assert "tracked_applications" in body
        assert "gap" in body
        assert "untracked_resume_files" in body

    def test_home_dashboard_page_renders(self, http_client_noauth):
        r = http_client_noauth.get("/dashboard/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "jobContextMCP" in r.text

    def test_rejections_dashboard_page_renders(self, http_client_noauth):
        r = http_client_noauth.get("/dashboard/rejections")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Rejections" in r.text

    def test_rejections_dashboard_data_shape(self, http_client_noauth):
        r = http_client_noauth.get("/dashboard/rejections/data")
        assert r.status_code == 200
        body = r.json()
        assert "total" in body
        assert "by_stage" in body
        assert "by_company" in body
        assert "recent" in body

    def test_posts_dashboard_page_renders(self, http_client_noauth):
        r = http_client_noauth.get("/dashboard/posts")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Posts" in r.text

    def test_posts_dashboard_data_shape(self, http_client_noauth):
        r = http_client_noauth.get("/dashboard/posts/data")
        assert r.status_code == 200
        body = r.json()
        assert "total" in body
        assert "total_impressions" in body
        assert "total_reactions" in body
        assert "posts" in body

    def test_people_dashboard_page_renders(self, http_client_noauth):
        r = http_client_noauth.get("/dashboard/people")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Outreach" in r.text

    def test_people_dashboard_data_shape(self, http_client_noauth):
        r = http_client_noauth.get("/dashboard/people/data")
        assert r.status_code == 200
        body = r.json()
        assert "total" in body
        assert "by_status" in body
        assert "follow_up_queue" in body

    def test_health_dashboard_page_renders(self, http_client_noauth):
        r = http_client_noauth.get("/dashboard/health")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Wellbeing" in r.text

    def test_health_dashboard_data_shape(self, http_client_noauth):
        r = http_client_noauth.get("/dashboard/health/data")
        assert r.status_code == 200
        body = r.json()
        assert "total_entries" in body
        assert "recent" in body


# ──────────────────────────────────────────────────────────────────────────────
# SSE streaming
# ──────────────────────────────────────────────────────────────────────────────

def _parse_sse(text: str) -> list[dict]:
    """Parse the body of an SSE response into a list of {event, data} dicts."""
    events = []
    current: dict = {}
    for line in text.splitlines():
        if not line.strip():
            if current:
                events.append(current)
                current = {}
            continue
        if line.startswith("event:"):
            current["event"] = line[len("event:"):].strip()
        elif line.startswith("data:"):
            current["data"] = line[len("data:"):].strip()
    if current:
        events.append(current)
    return events


class TestSSEStreaming:
    def test_jobs_evaluate_stream_emits_named_stages(self, http_client_noauth):
        with http_client_noauth.stream("POST", "/jobs/evaluate/stream", json={
            "company": "Stripe",
            "role": "Staff Engineer",
            "job_description": "Build payments infrastructure.",
        }) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            body = r.read().decode("utf-8")

        events = _parse_sse(body)
        stages = [e["event"] for e in events]
        # Service emits: queuing, queued, evaluating, complete
        # SSE wrapper appends: result
        assert stages[0] == "queuing"
        assert "queued" in stages
        assert "evaluating" in stages
        assert "complete" in stages
        assert stages[-1] == "result"

        # Final "result" event payload mirrors AnalysisResult shape.
        result_event = events[-1]
        payload = json.loads(result_event["data"])
        assert payload["stage"] == "result"
        assert payload["payload"]["company"] == "Stripe"
        assert payload["payload"]["evaluated"] is True

    def test_resume_generate_stream_emits_stages(self, http_client_noauth):
        with http_client_noauth.stream("POST", "/resumes/generate/stream", json={
            "company": "Stripe",
            "role": "Staff Engineer",
            "job_description": "JD",
            "kind": "resume",
        }) as r:
            assert r.status_code == 200
            body = r.read().decode("utf-8")

        events = _parse_sse(body)
        stages = [e["event"] for e in events]
        assert stages[0] == "starting"
        assert "generating" in stages
        assert "complete" in stages
        assert stages[-1] == "result"


# ──────────────────────────────────────────────────────────────────────────────
# /workflows (LangGraph)
# ──────────────────────────────────────────────────────────────────────────────

class TestWorkflowEndpoints:
    def test_list_workflows(self, http_client_noauth):
        r = http_client_noauth.get("/workflows")
        assert r.status_code == 200
        assert "resume_tailoring" in r.json()["workflows"]

    def test_run_resume_tailoring_workflow_sync(self, http_client_noauth):
        r = http_client_noauth.post("/workflows/resume_tailoring", json={
            "company": "Stripe",
            "role": "Staff Engineer",
            "job_description": "Build payments infrastructure.",
        })
        assert r.status_code == 200
        body = r.json()
        assert "final_content" in body
        assert isinstance(body["final_content"], str) and body["final_content"]

    def test_run_unknown_workflow_returns_404(self, http_client_noauth):
        r = http_client_noauth.post("/workflows/nonexistent", json={})
        assert r.status_code == 404

    def test_run_workflow_stream_emits_node_events(self, http_client_noauth):
        with http_client_noauth.stream("POST", "/workflows/resume_tailoring/stream", json={
            "company": "Stripe",
            "role": "Staff Engineer",
            "job_description": "JD",
        }) as r:
            assert r.status_code == 200
            body = r.read().decode("utf-8")
        events = _parse_sse(body)
        stages = [e["event"] for e in events]
        assert stages[0] == "starting"
        assert "load_context" in stages
        assert "draft" in stages
        assert "review" in stages
        assert "output" in stages
        assert "complete" in stages
        assert stages[-1] == "result"

    def test_stream_unknown_workflow_returns_404(self, http_client_noauth):
        r = http_client_noauth.post("/workflows/nope/stream", json={})
        assert r.status_code == 404
