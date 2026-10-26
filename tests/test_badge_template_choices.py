"""Hermetic badge template contract tests: no auth server, network or real LLM.

Authentication/tenant routing stays covered by test_badge_api. These tests
exercise the request handler and actual executor with synthetic data only.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import socket

import pytest
from fastapi import HTTPException


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("Template contract tests must never contact a network")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


def _submit(monkeypatch, **fields):
    from transport.http.routes import badge

    queued = []
    monkeypatch.setattr(badge.work, "enqueue", lambda kind, inputs, **kw: queued.append((kind, inputs, kw)) or 41)
    out = asyncio.run(badge.badge_materials(badge.MaterialsRequest(job_id=7, **fields), object()))
    assert out == {"status": "queued", "work_id": 41}
    assert len(queued) == 1
    assert queued[0][0] == "badge_materials"
    assert queued[0][2] == {"origin": "badge"}
    return queued[0][1]


def test_legacy_request_payload_stays_unchanged(monkeypatch):
    assert _submit(monkeypatch) == {
        "job_id": 7, "material": "resume", "template": "", "style": "navy",
    }
    assert _submit(monkeypatch, material="both", template="sidebar", style="warm") == {
        "job_id": 7, "material": "both", "template": "sidebar", "style": "warm",
    }


def test_null_overrides_are_identical_to_old_requests(monkeypatch):
    assert _submit(monkeypatch, cl_template=None, cl_style=None) == {
        "job_id": 7, "material": "resume", "template": "", "style": "navy",
    }


def test_independent_choices_are_snapshotted_on_queued_work(monkeypatch):
    assert _submit(monkeypatch, material="both", template="executive", style="forest",
                   cl_template="portfolio", cl_style="classic") == {
        "job_id": 7, "material": "both", "template": "executive", "style": "forest",
        "cl_template": "portfolio", "cl_style": "classic",
    }


def test_explicit_legacy_cover_letter_choice_is_not_dropped(monkeypatch):
    inputs = _submit(monkeypatch, material="both", template="modern", cl_template="", cl_style="")
    assert inputs["cl_template"] == ""
    assert inputs["cl_style"] == ""


@pytest.mark.parametrize("extra", [
    {"cl_template": "not-a-template"}, {"cl_style": "not-a-style"},
    {"template": "not-a-template", "cl_template": "modern"},
    {"style": "not-a-style", "cl_style": "navy"},
])
def test_invalid_choice_is_rejected_before_enqueue(monkeypatch, extra):
    from transport.http.routes import badge

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Invalid selection must not create work")

    monkeypatch.setattr(badge.work, "enqueue", unexpected)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(badge.badge_materials(badge.MaterialsRequest(job_id=7, material="both", **extra), object()))
    assert exc.value.status_code == 422


@pytest.fixture()
def synthetic_job(isolated_server):
    import lib.config as cfg
    from lib.db import get_connection
    from lib.user_provisioning import provision_user_data

    provision_user_data(Path(cfg.DATA_FOLDER))
    with get_connection() as con:
        job_id = con.execute(
            "INSERT INTO job_queue (company, role, jd) VALUES (?, ?, ?)",
            ("Template Fixture", "Synthetic Engineer", "Synthetic role description"),
        ).lastrowid
    return job_id


def _run_executor(monkeypatch, job_id, **choices):
    from tools import generate
    from transport.http.routes import badge

    calls = {}

    def resume(company, role, jd, **kwargs):
        assert (company, role, jd) == ("Template Fixture", "Synthetic Engineer", "Synthetic role description")
        calls["resume"] = kwargs
        return "✓ Synthetic resume generated"

    def cover_letter(company, role, jd, **kwargs):
        assert (company, role, jd) == ("Template Fixture", "Synthetic Engineer", "Synthetic role description")
        calls["cover_letter"] = kwargs
        return "✓ Synthetic cover letter generated"

    monkeypatch.setattr(generate, "generate_resume", resume)
    monkeypatch.setattr(generate, "generate_cover_letter", cover_letter)
    result = badge._generate_materials({"job_id": job_id, "material": "both", **choices})
    return calls, result


def test_executor_consumes_distinct_choices(monkeypatch, synthetic_job):
    calls, result = _run_executor(monkeypatch, synthetic_job, template="executive", style="forest",
                                  cl_template="portfolio", cl_style="classic")
    assert calls == {
        "resume": {"template": "executive", "style": "forest"},
        "cover_letter": {"cl_template": "portfolio", "cl_style": "classic"},
    }
    assert result["resume"] and result["cover_letter"]


@pytest.mark.parametrize("choices,expected_template,expected_style", [
    ({}, "", "navy"),
    ({"template": "sidebar", "style": "warm"}, "sidebar", "warm"),
    ({"template": "sidebar", "style": "warm", "cl_template": None, "cl_style": None}, "sidebar", "warm"),
    ({"template": "sidebar", "style": "warm", "cl_template": "", "cl_style": ""}, "", "navy"),
    ({"template": "modern", "style": "forest", "cl_style": "slate"}, "modern", "slate"),
    ({"template": "modern", "style": "forest", "cl_template": "executive"}, "executive", "forest"),
])
def test_executor_preserves_legacy_and_partial_override_defaults(
    monkeypatch, synthetic_job, choices, expected_template, expected_style,
):
    calls, _ = _run_executor(monkeypatch, synthetic_job, **choices)
    assert calls["resume"] == {"template": choices.get("template", ""), "style": choices.get("style") or "navy"}
    assert calls["cover_letter"] == {"cl_template": expected_template, "cl_style": expected_style}
