"""Kiosk eval-detail page (/wallboard/evals).

The properties that matter: the route does not exist until the operator
configures the URL+PAT pair; payload text is treated as hostile markup (the
flagged claims are LLM output); the PAT never leaks into a response; and an
upstream failure renders a readable page, not a traceback.
"""
from __future__ import annotations

import types

import pytest
from fastapi.testclient import TestClient

from transport.http.routes import wallboard


@pytest.fixture()
def client(monkeypatch, tmp_path):
    import lib.config as cfg_mod
    from lib.user_provisioning import provision_user_data
    from transport.http.app import create_app
    from transport.http.config import reset_settings_cache

    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr(cfg_mod, "DATA_FOLDER", str(root), raising=False)
    provision_user_data(root)
    monkeypatch.delenv("API_KEY", raising=False)
    reset_settings_cache()
    wallboard._CACHE.clear()
    with TestClient(create_app()) as c:
        yield c
    reset_settings_cache()
    wallboard._CACHE.clear()


PAYLOAD = {
    "updated_at": "2026-08-12T08:11:00",
    "suite": {
        "judge_model": "claude-sonnet-5",
        "n_runs": 5,
        "rows": [
            {"gd_id": "GD-01", "role": "Platform Eng", "mean": 4.4, "accuracy": 4.2,
             "cov_pct": 3.1, "flip_rate_pct": 0.0, "alerts": []},
            {"gd_id": "GD-03", "role": "SRE", "mean": 3.6, "accuracy": 3.0,
             "cov_pct": 22.5, "flip_rate_pct": 40.0,
             "alerts": ["mean 3.6 below 4.0", "CoV 22.5% above 20%"]},
            {"gd_id": "GD-05", "role": "Backend", "error": "generation failed",
             "provenance_agreement": {}},
        ],
        "detail": {
            "GD-03": {"hallucinations": ["931 passing tests", "<script>alert(1)</script>"]},
        },
    },
}

WORK = {
    "tokens_by_kind": [
        {"kind": "run_evals", "llm_calls": 76, "tokens_prompt": 430000, "tokens_completion": 52000},
    ],
    "quota": {"tokens_used_today": 482000, "daily_token_quota": 0, "remaining": None,
              "exceeded": False},
}


def _configure(monkeypatch, responses: "dict[str, dict] | None" = None,
               fail: "Exception | None" = None) -> "list[str]":
    monkeypatch.setenv("WALLBOARD_EVALS_URL", "https://cloud.example")
    monkeypatch.setenv("WALLBOARD_EVALS_PAT", "jc_pat_SECRETSECRET")
    calls: list[str] = []

    def fake_get(url, headers=None, timeout=None, follow_redirects=None):
        calls.append(url)
        assert headers["Authorization"] == "Bearer jc_pat_SECRETSECRET"
        if fail is not None:
            raise fail
        body = (responses or {}).get(url.replace("https://cloud.example", ""), {})
        return types.SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: body)

    import httpx
    monkeypatch.setattr(httpx, "get", fake_get)
    return calls


def test_unconfigured_is_404(client, monkeypatch):
    """No env pair = the route does not exist. This is what keeps the public
    prefix safe on cloud and desktop deployments."""
    monkeypatch.delenv("WALLBOARD_EVALS_URL", raising=False)
    monkeypatch.delenv("WALLBOARD_EVALS_PAT", raising=False)
    assert client.get("/wallboard/evals").status_code == 404


def test_renders_alerts_claims_and_errored_entries(client, monkeypatch):
    _configure(monkeypatch, {"/api/evals/results": PAYLOAD, "/api/work/stats": WORK})
    resp = client.get("/wallboard/evals")
    assert resp.status_code == 200
    body = resp.text
    assert "claude-sonnet-5" in body
    assert "CoV 22.5% above 20%" in body          # the alert string, in words
    assert "931 passing tests" in body            # the flagged claim, quoted
    assert "generation failed" in body            # an errored entry is shown, not hidden
    assert "run_evals" in body and "430000" in body  # work stats table


def test_claim_text_is_escaped_not_executed(client, monkeypatch):
    """Flagged claims are LLM output rendered into HTML — hostile by default."""
    _configure(monkeypatch, {"/api/evals/results": PAYLOAD, "/api/work/stats": WORK})
    body = client.get("/wallboard/evals").text
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body


def test_pat_never_appears_in_any_response(client, monkeypatch):
    _configure(monkeypatch, {"/api/evals/results": PAYLOAD, "/api/work/stats": WORK})
    assert "SECRETSECRET" not in client.get("/wallboard/evals").text

    wallboard._CACHE.clear()
    _configure(monkeypatch, fail=RuntimeError("boom with context"))
    assert "SECRETSECRET" not in client.get("/wallboard/evals").text


def test_upstream_failure_renders_a_page_not_a_traceback(client, monkeypatch):
    _configure(monkeypatch, fail=RuntimeError("connect timeout"))
    resp = client.get("/wallboard/evals")
    assert resp.status_code == 502
    assert "Couldn't fetch" in resp.text
    assert "Traceback" not in resp.text


def test_work_stats_failure_still_renders_evals(client, monkeypatch):
    """The eval detail is the page's point; work stats are garnish."""
    calls = _configure(monkeypatch, {"/api/evals/results": PAYLOAD})

    import httpx
    real = httpx.get

    def flaky(url, **kw):
        if url.endswith("/api/work/stats"):
            raise RuntimeError("stats down")
        return real(url, **kw)

    monkeypatch.setattr(httpx, "get", flaky)
    resp = client.get("/wallboard/evals")
    assert resp.status_code == 200
    assert "931 passing tests" in resp.text
    assert "tokens by kind" not in resp.text
    assert calls is not None  # fixture plumbing


def test_fetches_are_cached(client, monkeypatch):
    calls = _configure(monkeypatch, {"/api/evals/results": PAYLOAD, "/api/work/stats": WORK})
    client.get("/wallboard/evals")
    client.get("/wallboard/evals")
    # 2 endpoints, 2 page loads, but each endpoint fetched once within the TTL.
    assert len(calls) == 2


def test_back_link_uses_the_request_host(client, monkeypatch):
    """The kiosk browser has no back button; the page carries its own escape
    hatch, pointed at the Grafana on the SAME host the page was reached by —
    no configured IP to drift."""
    _configure(monkeypatch, {"/api/evals/results": PAYLOAD, "/api/work/stats": WORK})
    body = client.get("/wallboard/evals").text
    assert "href='http://testserver:3000/d/kiosk-evals?kiosk'" in body
    assert "back to the board" in body

    wallboard._CACHE.clear()
    _configure(monkeypatch, fail=RuntimeError("down"))
    assert "back to the board" in client.get("/wallboard/evals").text  # error page too


def test_critic_findings_render_and_escape(client, monkeypatch):
    payload = dict(PAYLOAD)
    payload["suite"] = dict(PAYLOAD["suite"])
    payload["suite"]["detail"] = {
        "GD-03": {
            "hallucinations": ["931 passing tests"],
            "critic": {"model": "m", "findings": [
                {"claim": "<b>bold claim</b>", "verdict": "contradicted",
                 "evidence": "the <i>source</i> passage"},
            ]},
        },
    }
    _configure(monkeypatch, {"/api/evals/results": payload, "/api/work/stats": WORK})
    body = client.get("/wallboard/evals").text
    assert "Critic findings (entailment, report-only)" in body
    assert "&lt;b&gt;bold claim&lt;/b&gt;" in body      # escaped, not executed
    assert "the &lt;i&gt;source&lt;/i&gt; passage" in body
