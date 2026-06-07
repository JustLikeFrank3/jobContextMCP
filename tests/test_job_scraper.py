"""
Tests for tools/job_scraper.py

Uses pytest's monkeypatch to intercept httpx.get so no real network calls
are made.  The isolated_server fixture redirects all file paths to tmp_path.
"""

import json
from unittest.mock import MagicMock

import pytest

import server as srv


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_response(text: str = "", status_code: int = 200) -> MagicMock:
    mock = MagicMock()
    mock.text = text
    mock.status_code = status_code
    mock.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx
        mock.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=mock,
        )
    return mock


_SAMPLE_MARKDOWN = """\
# Senior Software Engineer, Payments at Stripe

Stripe | San Francisco, CA • Remote OK

## About the Role

We are looking for a Senior Software Engineer to join our Payments platform.
You will build distributed systems that handle billions of transactions per year.

## Requirements

- 5+ years of backend engineering experience
- Python, Go, or Java proficiency
- Experience with distributed systems

## Responsibilities

- Design and implement payment processing infrastructure
- Lead code reviews and mentor junior engineers
- Collaborate with product teams
"""

_SAMPLE_SERPAPI_RESPONSE = {
    "jobs_results": [
        {
            "title": "Staff Software Engineer",
            "company_name": "Stripe",
            "location": "San Francisco, CA",
            "via": "LinkedIn",
            "description": "Join Stripe's infrastructure team. 5+ years experience required.",
            "apply_options": [{"link": "https://stripe.com/jobs/123", "title": "Apply on Stripe"}],
        },
        {
            "title": "Senior Backend Engineer",
            "company_name": "Plaid",
            "location": "New York, NY",
            "via": "Greenhouse",
            "description": "Build financial data infrastructure at Plaid.",
            "apply_options": [],
        },
    ]
}


# ── scrape_job_url ─────────────────────────────────────────────────────────────

class TestScrapeJobUrl:
    def test_fetches_and_queues(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _mock_response(_SAMPLE_MARKDOWN))
        result = srv.scrape_job_url("https://stripe.com/jobs/123")
        assert "Scraped" in result
        assert "Stripe" in result or "stripe" in result.lower()

    def test_auto_queue_false_returns_preview(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _mock_response(_SAMPLE_MARKDOWN))
        result = srv.scrape_job_url("https://stripe.com/jobs/123", auto_queue=False)
        assert "Scraped:" in result
        assert "auto_queue=True" in result or "queue_job" in result
        # Should NOT have auto-queued
        data = json.loads(srv.JOB_QUEUE_FILE.read_text()) if srv.JOB_QUEUE_FILE.exists() else {"jobs": []}
        assert data.get("jobs", []) == []

    def test_auto_queue_true_adds_to_pipeline(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _mock_response(_SAMPLE_MARKDOWN))
        srv.scrape_job_url("https://stripe.com/jobs/123", auto_queue=True)
        data = json.loads(srv.JOB_QUEUE_FILE.read_text())
        assert len(data["jobs"]) == 1
        assert data["jobs"][0]["source"] == "https://stripe.com/jobs/123"

    def test_http_error_returns_friendly_message(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _mock_response(status_code=403))
        result = srv.scrape_job_url("https://boards.greenhouse.io/stripe/jobs/12345")
        assert "403" in result or "login" in result.lower()

    def test_linkedin_url_returns_blocked_message(self, isolated_server):
        # LinkedIn URLs bypass Jina entirely and return a user-friendly message.
        result = srv.scrape_job_url("https://www.linkedin.com/jobs/view/12345")
        assert "linkedin" in result.lower()
        assert "paste" in result.lower() or "dashboard" in result.lower()

    def test_empty_response_handled_gracefully(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _mock_response("   "))
        result = srv.scrape_job_url("https://example.com/jobs/1")
        assert "No content" in result or "login" in result.lower()

    def test_network_error_returns_friendly_message(self, isolated_server, monkeypatch):
        import httpx

        def _raise(*a, **kw):
            raise httpx.ConnectError("Connection refused")

        monkeypatch.setattr("httpx.get", _raise)
        result = srv.scrape_job_url("https://example.com/jobs/1")
        assert "Failed to fetch" in result


# ── search_jobs ────────────────────────────────────────────────────────────────

class TestSearchJobs:
    def test_no_api_key_returns_config_hint(self, isolated_server, monkeypatch):
        from lib import config as cfg
        monkeypatch.setattr(cfg, "SERPAPI_KEY", "")
        result = srv.search_jobs("Senior Engineer Python")
        assert "serpapi_key" in result
        assert "config.json" in result

    def test_returns_formatted_results(self, isolated_server, monkeypatch):
        from lib import config as cfg
        monkeypatch.setattr(cfg, "SERPAPI_KEY", "test-key")
        monkeypatch.setattr(
            "httpx.get",
            lambda *a, **kw: _mock_response(json.dumps(_SAMPLE_SERPAPI_RESPONSE)),
        )
        # Make the mock parse as JSON
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        mock.json.return_value = _SAMPLE_SERPAPI_RESPONSE
        monkeypatch.setattr("httpx.get", lambda *a, **kw: mock)

        result = srv.search_jobs("Senior Engineer Python")
        assert "Stripe" in result
        assert "Plaid" in result
        assert "Staff Software Engineer" in result

    def test_location_appears_in_header(self, isolated_server, monkeypatch):
        from lib import config as cfg
        monkeypatch.setattr(cfg, "SERPAPI_KEY", "test-key")
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        mock.json.return_value = _SAMPLE_SERPAPI_RESPONSE
        monkeypatch.setattr("httpx.get", lambda *a, **kw: mock)

        result = srv.search_jobs("Engineer", location="Seattle, WA")
        assert "Seattle, WA" in result

    def test_remote_location_folded_into_query(self, isolated_server, monkeypatch):
        from lib import config as cfg
        monkeypatch.setattr(cfg, "SERPAPI_KEY", "test-key")
        captured = {}
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        mock.json.return_value = _SAMPLE_SERPAPI_RESPONSE

        def _capture(*a, **kw):
            captured["params"] = kw.get("params", {})
            return mock

        monkeypatch.setattr("httpx.get", _capture)
        srv.search_jobs("Engineer", location="Remote")
        assert "remote" in captured["params"]["q"].lower()
        assert "location" not in captured["params"]

    def test_no_results_message(self, isolated_server, monkeypatch):
        from lib import config as cfg
        monkeypatch.setattr(cfg, "SERPAPI_KEY", "test-key")
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        mock.json.return_value = {"jobs_results": []}
        monkeypatch.setattr("httpx.get", lambda *a, **kw: mock)

        result = srv.search_jobs("Quantum Chef")
        assert "No results" in result

    def test_auto_queue_adds_to_pipeline(self, isolated_server, monkeypatch):
        from lib import config as cfg
        monkeypatch.setattr(cfg, "SERPAPI_KEY", "test-key")
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        mock.json.return_value = _SAMPLE_SERPAPI_RESPONSE
        monkeypatch.setattr("httpx.get", lambda *a, **kw: mock)

        srv.search_jobs("Engineer", auto_queue=True)
        data = json.loads(srv.JOB_QUEUE_FILE.read_text())
        companies = [j["company"] for j in data["jobs"]]
        assert "Stripe" in companies
        assert "Plaid" in companies

    def test_num_results_respected(self, isolated_server, monkeypatch):
        from lib import config as cfg
        monkeypatch.setattr(cfg, "SERPAPI_KEY", "test-key")
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        mock.json.return_value = _SAMPLE_SERPAPI_RESPONSE
        monkeypatch.setattr("httpx.get", lambda *a, **kw: mock)

        result = srv.search_jobs("Engineer", num_results=1)
        # Only the first result should appear
        assert "Stripe" in result
        assert "Plaid" not in result

    def test_serpapi_http_error(self, isolated_server, monkeypatch):
        from lib import config as cfg
        import httpx
        monkeypatch.setattr(cfg, "SERPAPI_KEY", "bad-key")

        def _raise(*a, **kw):
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            raise httpx.HTTPStatusError("401", request=MagicMock(), response=mock_resp)

        monkeypatch.setattr("httpx.get", _raise)
        result = srv.search_jobs("Engineer")
        assert "401" in result or "API key" in result


# ── sample payloads ────────────────────────────────────────────────────────────

_GREENHOUSE_RESPONSE = {
    "jobs": [
        {
            "id": 1001,
            "title": "Senior Software Engineer",
            "location": {"name": "San Francisco, CA"},
            "departments": [{"name": "Engineering"}],
            "absolute_url": "https://boards.greenhouse.io/stripe/jobs/1001",
            "updated_at": "2026-05-01T10:00:00Z",
            "content": "<p>We are hiring a <strong>Senior Engineer</strong> to work on payments.</p>",
        },
        {
            "id": 1002,
            "title": "Product Manager, Billing",
            "location": {"name": "Remote"},
            "departments": [{"name": "Product"}],
            "absolute_url": "https://boards.greenhouse.io/stripe/jobs/1002",
            "updated_at": "2026-04-15T10:00:00Z",
            "content": "<p>Lead our billing product strategy.</p>",
        },
    ]
}

_LEVER_RESPONSE = [
    {
        "id": "abc-001",
        "text": "Staff Backend Engineer",
        "categories": {
            "team": "Infrastructure",
            "location": "New York, NY",
            "commitment": "Full-time",
        },
        "hostedUrl": "https://jobs.lever.co/plaid/abc-001",
        "description": "<p>Join Plaid's infrastructure team.</p>",
        "descriptionBody": "<p>Requirements: 7+ years Python or Go.</p>",
    },
    {
        "id": "abc-002",
        "text": "Data Engineer",
        "categories": {
            "team": "Data",
            "location": "Remote",
            "commitment": "Full-time",
        },
        "hostedUrl": "https://jobs.lever.co/plaid/abc-002",
        "description": "<p>Build data pipelines at scale.</p>",
        "descriptionBody": "",
    },
]


def _json_mock(payload) -> MagicMock:
    """Return a mock httpx response that returns *payload* from .json()."""
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = payload
    return mock


def _status_error_mock(status_code: int) -> MagicMock:
    import httpx
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock = MagicMock()
    mock.raise_for_status.side_effect = httpx.HTTPStatusError(
        message=str(status_code), request=MagicMock(), response=mock_resp
    )
    return mock


# ── search_greenhouse_jobs ─────────────────────────────────────────────────────

class TestSearchGreenhouseJobs:
    def test_returns_all_roles(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _json_mock(_GREENHOUSE_RESPONSE))
        result = srv.search_greenhouse_jobs("stripe")
        assert "Senior Software Engineer" in result
        assert "Product Manager, Billing" in result
        assert "GREENHOUSE: Stripe" in result

    def test_query_filters_by_title(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _json_mock(_GREENHOUSE_RESPONSE))
        result = srv.search_greenhouse_jobs("stripe", query="engineer")
        assert "Senior Software Engineer" in result
        assert "Product Manager" not in result

    def test_query_no_match_returns_message(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _json_mock(_GREENHOUSE_RESPONSE))
        result = srv.search_greenhouse_jobs("stripe", query="quantum chef")
        assert "No Greenhouse roles matching" in result

    def test_404_returns_slug_hint(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _status_error_mock(404))
        result = srv.search_greenhouse_jobs("notacompany")
        assert "notacompany" in result
        assert "slug" in result.lower() or "greenhouse" in result.lower()

    def test_empty_board_returns_message(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _json_mock({"jobs": []}))
        result = srv.search_greenhouse_jobs("stripe")
        assert "No open roles" in result

    def test_auto_queue_adds_to_pipeline(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _json_mock(_GREENHOUSE_RESPONSE))
        srv.search_greenhouse_jobs("stripe", auto_queue=True)
        data = json.loads(srv.JOB_QUEUE_FILE.read_text())
        titles = [j["role"] for j in data["jobs"]]
        assert "Senior Software Engineer" in titles
        assert "Product Manager, Billing" in titles

    def test_auto_queue_source_is_greenhouse_url(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _json_mock(_GREENHOUSE_RESPONSE))
        srv.search_greenhouse_jobs("stripe", auto_queue=True)
        data = json.loads(srv.JOB_QUEUE_FILE.read_text())
        sources = [j["source"] for j in data["jobs"]]
        assert any("greenhouse.io" in s for s in sources)

    def test_html_stripped_from_jd(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _json_mock(_GREENHOUSE_RESPONSE))
        srv.search_greenhouse_jobs("stripe", auto_queue=True)
        data = json.loads(srv.JOB_QUEUE_FILE.read_text())
        jd = data["jobs"][0]["jd"]
        assert "<p>" not in jd
        assert "<strong>" not in jd

    def test_num_results_respected(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _json_mock(_GREENHOUSE_RESPONSE))
        result = srv.search_greenhouse_jobs("stripe", num_results=1)
        assert "Senior Software Engineer" in result
        assert "Product Manager" not in result

    def test_network_error_handled(self, isolated_server, monkeypatch):
        import httpx

        monkeypatch.setattr("httpx.get", lambda *a, **kw: (_ for _ in ()).throw(
            httpx.ConnectError("timeout")
        ))
        result = srv.search_greenhouse_jobs("stripe")
        assert "Failed" in result or "Greenhouse" in result


# ── search_lever_jobs ──────────────────────────────────────────────────────────

class TestSearchLeverJobs:
    def test_returns_all_roles(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _json_mock(_LEVER_RESPONSE))
        result = srv.search_lever_jobs("plaid")
        assert "Staff Backend Engineer" in result
        assert "Data Engineer" in result
        assert "LEVER: Plaid" in result

    def test_query_filters_by_title(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _json_mock(_LEVER_RESPONSE))
        result = srv.search_lever_jobs("plaid", query="backend")
        assert "Staff Backend Engineer" in result
        assert "Data Engineer" not in result

    def test_query_no_match_returns_message(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _json_mock(_LEVER_RESPONSE))
        result = srv.search_lever_jobs("plaid", query="quantum chef")
        assert "No Lever roles matching" in result

    def test_404_returns_slug_hint(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _status_error_mock(404))
        result = srv.search_lever_jobs("notacompany")
        assert "notacompany" in result
        assert "slug" in result.lower() or "lever" in result.lower()

    def test_empty_board_returns_message(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _json_mock([]))
        result = srv.search_lever_jobs("plaid")
        assert "No open roles" in result

    def test_auto_queue_adds_to_pipeline(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _json_mock(_LEVER_RESPONSE))
        srv.search_lever_jobs("plaid", auto_queue=True)
        data = json.loads(srv.JOB_QUEUE_FILE.read_text())
        titles = [j["role"] for j in data["jobs"]]
        assert "Staff Backend Engineer" in titles
        assert "Data Engineer" in titles

    def test_auto_queue_source_is_lever_url(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _json_mock(_LEVER_RESPONSE))
        srv.search_lever_jobs("plaid", auto_queue=True)
        data = json.loads(srv.JOB_QUEUE_FILE.read_text())
        sources = [j["source"] for j in data["jobs"]]
        assert any("lever.co" in s for s in sources)

    def test_html_stripped_from_jd(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _json_mock(_LEVER_RESPONSE))
        srv.search_lever_jobs("plaid", auto_queue=True)
        data = json.loads(srv.JOB_QUEUE_FILE.read_text())
        jd = data["jobs"][0]["jd"]
        assert "<p>" not in jd

    def test_commitment_and_team_shown(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _json_mock(_LEVER_RESPONSE))
        result = srv.search_lever_jobs("plaid")
        assert "Infrastructure" in result
        assert "Full-time" in result

    def test_num_results_respected(self, isolated_server, monkeypatch):
        monkeypatch.setattr("httpx.get", lambda *a, **kw: _json_mock(_LEVER_RESPONSE))
        result = srv.search_lever_jobs("plaid", num_results=1)
        assert "Staff Backend Engineer" in result
        assert "Data Engineer" not in result
