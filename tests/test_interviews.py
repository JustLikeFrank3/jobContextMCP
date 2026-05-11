"""
Tests for tools/interviews.py — v6 interview transcript / debrief logging.

Mirrors the canonical CRUD test pattern from tests/test_posts.py: each public
tool gets a class, fixture-isolated, with explicit JSON-on-disk verification.
"""

import json
from pathlib import Path

import pytest

import server as srv


def _interviews_path(isolated_root: Path) -> Path:
    return isolated_root / "data" / "interviews.json"


def _read_interviews(isolated_root: Path) -> list[dict]:
    p = _interviews_path(isolated_root)
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("interviews", [])


def _seed_interview(**overrides) -> str:
    """Convenience wrapper that calls log_interview with sane defaults."""
    payload = {
        "company": "Acme",
        "role": "Senior Software Engineer",
        "interview_date": "2026-05-05 14:00",
        "interview_type": "recruiter_screen",
        "interviewer": "Pat Recruiter",
        "interviewer_role": "Senior Technical Recruiter",
        "duration_minutes": 30,
        "self_rating": 8,
    }
    payload.update(overrides)
    return srv.log_interview(**payload)


# ──────────────────────────────────────────────────────────────────────────────
# log_interview
# ──────────────────────────────────────────────────────────────────────────────

class TestLogInterview:
    def test_creates_first_record_with_id_one(self, isolated_server):
        result = _seed_interview()
        assert "✓ Interview logged #1" in result
        records = _read_interviews(isolated_server)
        assert len(records) == 1
        r = records[0]
        assert r["id"] == 1
        assert r["company"] == "Acme"
        assert r["interview_type"] == "recruiter_screen"
        assert r["self_rating"] == 8
        assert r["interview_format"] == "video"  # default
        assert "timestamp" in r
        assert "last_updated" in r

    def test_assigns_incrementing_ids(self, isolated_server):
        _seed_interview()
        _seed_interview(interview_date="2026-05-12 14:00", interview_type="hiring_manager")
        records = _read_interviews(isolated_server)
        assert [r["id"] for r in records] == [1, 2]

    def test_rejects_invalid_interview_type(self, isolated_server):
        result = _seed_interview(interview_type="coffee_chat")
        assert result.startswith("✗ Invalid interview_type")
        assert _read_interviews(isolated_server) == []

    def test_rejects_invalid_format(self, isolated_server):
        result = _seed_interview(interview_format="telegram")
        assert result.startswith("✗ Invalid interview_format")
        assert _read_interviews(isolated_server) == []

    def test_clamps_self_rating_to_range(self, isolated_server):
        _seed_interview(self_rating=42)
        assert _read_interviews(isolated_server)[0]["self_rating"] == 10
        # second record, low end
        _seed_interview(interview_date="2026-05-06 14:00", self_rating=-3)
        assert _read_interviews(isolated_server)[1]["self_rating"] == 1

    def test_rejects_non_numeric_rating(self, isolated_server):
        result = _seed_interview(self_rating="great")
        assert result.startswith("✗ self_rating")
        assert _read_interviews(isolated_server) == []

    def test_normalizes_quote_strings_to_dicts(self, isolated_server):
        _seed_interview(verbatim_quotes=["Yeah, that's not gonna be enough"])
        q = _read_interviews(isolated_server)[0]["verbatim_quotes"]
        assert q == [{"speaker": "interviewer", "quote": "Yeah, that's not gonna be enough", "context": ""}]

    def test_accepts_quote_dicts(self, isolated_server):
        _seed_interview(verbatim_quotes=[
            {"speaker": "Pat", "quote": "Mission first", "context": "after culture question"},
        ])
        q = _read_interviews(isolated_server)[0]["verbatim_quotes"]
        assert q[0]["speaker"] == "Pat"
        assert q[0]["context"] == "after culture question"

    def test_drops_empty_quotes(self, isolated_server):
        _seed_interview(verbatim_quotes=[{"speaker": "x", "quote": ""}, "real one"])
        q = _read_interviews(isolated_server)[0]["verbatim_quotes"]
        assert len(q) == 1
        assert q[0]["quote"] == "real one"

    def test_lowercases_tags(self, isolated_server):
        _seed_interview(tags=["Mission", "Full-Stack", " warm "])
        tags = _read_interviews(isolated_server)[0]["tags"]
        assert tags == ["mission", "full-stack", "warm"]

    def test_upserts_on_company_plus_date(self, isolated_server):
        _seed_interview(what_landed=["mission framing landed"], tags=["initial"])
        result = _seed_interview(
            what_landed=["comp anchor accepted"],
            tags=["initial", "comp"],
            verbatim_quotes=["that's not enough for infrastructure"],
            comp_signals="$200k anchor inside $185-210k band",
        )
        assert "✓ Updated existing interview #1" in result
        records = _read_interviews(isolated_server)
        assert len(records) == 1
        r = records[0]
        # additive merge
        assert r["what_landed"] == ["mission framing landed", "comp anchor accepted"]
        assert r["tags"] == ["initial", "comp"]
        assert r["comp_signals"] == "$200k anchor inside $185-210k band"
        assert any("not enough for infrastructure" in q["quote"] for q in r["verbatim_quotes"])

    def test_upsert_dedupes_list_items(self, isolated_server):
        _seed_interview(what_landed=["mission framing landed"])
        _seed_interview(what_landed=["mission framing landed", "comp anchor"])
        landed = _read_interviews(isolated_server)[0]["what_landed"]
        assert landed == ["mission framing landed", "comp anchor"]

    def test_handles_none_list_args(self, isolated_server):
        # All optional list args default to None — must not crash
        srv.log_interview(
            company="Acme",
            role="SWE",
            interview_date="2026-01-01",
            interview_type="technical",
        )
        r = _read_interviews(isolated_server)[0]
        assert r["what_landed"] == []
        assert r["verbatim_quotes"] == []
        assert r["tags"] == []


# ──────────────────────────────────────────────────────────────────────────────
# get_interviews
# ──────────────────────────────────────────────────────────────────────────────

class TestGetInterviews:
    def test_empty_state_message(self, isolated_server):
        out = srv.get_interviews()
        assert "No interviews logged" in out

    def test_no_match_message(self, isolated_server):
        _seed_interview()
        out = srv.get_interviews(company="DoesNotExist")
        assert "No interviews match" in out

    def test_lists_all_with_count(self, isolated_server):
        _seed_interview()
        _seed_interview(
            company="Stripe",
            interview_date="2026-04-20 11:00",
            interview_type="hiring_manager",
            interviewer="Pat HM",
        )
        out = srv.get_interviews()
        assert "(2 found)" in out
        assert "Acme" in out
        assert "Stripe" in out

    def test_company_filter_partial_case_insensitive(self, isolated_server):
        _seed_interview()
        _seed_interview(company="Stripe", interview_date="2026-04-20 11:00", interview_type="hiring_manager")
        out = srv.get_interviews(company="acm")
        assert "Acme" in out
        assert "Stripe" not in out

    def test_interview_type_exact_match(self, isolated_server):
        _seed_interview()
        _seed_interview(
            interview_date="2026-05-12 14:00",
            interview_type="hiring_manager",
            interviewer="HM Person",
        )
        out = srv.get_interviews(interview_type="hiring_manager")
        assert "(1 found)" in out
        assert "HM Person" in out

    def test_since_filter(self, isolated_server):
        _seed_interview(interview_date="2026-01-01 09:00")
        _seed_interview(interview_date="2026-06-15 09:00")
        out = srv.get_interviews(since="2026-06-01")
        assert "(1 found)" in out
        assert "2026-06-15" in out

    def test_tag_filter(self, isolated_server):
        _seed_interview(tags=["mission", "warm"])
        _seed_interview(interview_date="2026-05-12 14:00", tags=["cold"])
        out = srv.get_interviews(tag="MISSION")
        assert "(1 found)" in out

    def test_compact_omits_quotes_by_default(self, isolated_server):
        _seed_interview(verbatim_quotes=["secret quote"])
        out = srv.get_interviews()
        assert "secret quote" not in out

    def test_include_full_renders_quotes_and_priorities(self, isolated_server):
        _seed_interview(
            verbatim_quotes=["secret quote"],
            surfaced_priorities=["unstated HM priority"],
            what_landed=["the mission framing"],
        )
        out = srv.get_interviews(include_full=True)
        assert "secret quote" in out
        assert "unstated HM priority" in out
        assert "the mission framing" in out

    def test_results_sorted_newest_first(self, isolated_server):
        _seed_interview(interview_date="2026-01-01 09:00", interviewer="Old")
        _seed_interview(interview_date="2026-06-15 09:00", interviewer="New")
        out = srv.get_interviews()
        new_pos = out.index("New")
        old_pos = out.index("Old")
        assert new_pos < old_pos


# ──────────────────────────────────────────────────────────────────────────────
# get_interview_context
# ──────────────────────────────────────────────────────────────────────────────

class TestGetInterviewContext:
    def test_empty_company_returns_empty_string(self, isolated_server):
        assert srv.get_interview_context("") == ""

    def test_no_records_returns_empty_string(self, isolated_server):
        assert srv.get_interview_context("Acme") == ""

    def test_no_matching_company_returns_empty_string(self, isolated_server):
        _seed_interview()
        assert srv.get_interview_context("Stripe") == ""

    def test_renders_block_for_matching_company(self, isolated_server):
        _seed_interview(
            verbatim_quotes=[{"speaker": "Pat", "quote": "not enough for infrastructure", "context": "comp"}],
            surfaced_priorities=["full-stack handoff was her idea"],
            what_landed=["mission resonance"],
            what_didnt=["comp anchor too low at first"],
            comp_signals="$200k inside $185-210k band",
            process_details="HM round next",
        )
        block = srv.get_interview_context("Acme")
        assert "PRIOR INTERVIEW CONTEXT (Acme)" in block
        assert "not enough for infrastructure" in block
        assert "full-stack handoff was her idea" in block
        assert "mission resonance" in block
        assert "comp anchor too low at first" in block
        assert "$200k" in block
        assert "HM round next" in block

    def test_role_filter_narrows_results(self, isolated_server):
        _seed_interview(role="Backend (Ordering)", interview_date="2026-05-05 14:00")
        _seed_interview(role="Production Planning Full-Stack", interview_date="2026-05-12 14:00")
        block = srv.get_interview_context("Acme", role="Production Planning")
        assert "2026-05-12" in block
        assert "2026-05-05" not in block

    def test_chronological_order_oldest_first(self, isolated_server):
        _seed_interview(interview_date="2026-06-15 09:00", interviewer="Newer")
        _seed_interview(interview_date="2026-01-01 09:00", interviewer="Older")
        block = srv.get_interview_context("Acme")
        assert block.index("Older") < block.index("Newer")
