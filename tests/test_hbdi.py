"""Tests for tools/hbdi.py — HBDI cognitive style profiler."""
import json
import pytest
from tests.conftest import isolated_server  # noqa: F401

# ── Shared test data ──────────────────────────────────────────────────────────

_Q1 = "First 20 minutes understanding the problem, then synthesize a one-line solution, then figure out infrastructure."
_Q2 = "Spend time understanding their frame of reference without compromising creative vision. No self-loathing."
_Q3 = "I'd use the hell out of an AI. Everything would get a fine-tooth comb pass. Pay it forward with documentation."
_Q4 = "Build both implementations. Push the senior dev's to prod, keep mine as backup to see if it's worth trying."

_SCORES_FRANK = dict(score_a=3, score_b=2, score_c=3, score_d=4)


# ── run_hbdi_assessment ───────────────────────────────────────────────────────

def test_run_hbdi_returns_profile_report(isolated_server):
    from tools.hbdi import run_hbdi_assessment
    result = run_hbdi_assessment(
        q1_no_spec_project=_Q1,
        q2_critical_feedback=_Q2,
        q3_tedious_finish=_Q3,
        q4_senior_disagreement=_Q4,
        **_SCORES_FRANK,
    )
    assert "HBDI COGNITIVE PROFILE" in result
    assert "D (Imaginative / Holistic): 4/4 — Primary" in result
    assert "Interview Framing Advice" in result


def test_run_hbdi_saves_to_personal_context(isolated_server):
    import lib.config as cfg
    from tools.hbdi import run_hbdi_assessment
    run_hbdi_assessment(
        q1_no_spec_project=_Q1,
        q2_critical_feedback=_Q2,
        q3_tedious_finish=_Q3,
        q4_senior_disagreement=_Q4,
        **_SCORES_FRANK,
    )
    data = json.loads(cfg.PERSONAL_CONTEXT_FILE.read_text())
    assert "hbdi_profile" in data
    profile = data["hbdi_profile"]
    assert profile["primary"] == "D"
    assert profile["scores"] == {"A": 3, "B": 2, "C": 3, "D": 4}


def test_run_hbdi_saves_responses(isolated_server):
    import lib.config as cfg
    from tools.hbdi import run_hbdi_assessment
    run_hbdi_assessment(
        q1_no_spec_project=_Q1,
        q2_critical_feedback=_Q2,
        q3_tedious_finish=_Q3,
        q4_senior_disagreement=_Q4,
        **_SCORES_FRANK,
    )
    data = json.loads(cfg.PERSONAL_CONTEXT_FILE.read_text())
    responses = data["hbdi_profile"]["responses"]
    assert responses["q1_no_spec_project"] == _Q1
    assert responses["q4_senior_disagreement"] == _Q4


def test_run_hbdi_preserves_existing_stories(isolated_server):
    import lib.config as cfg
    from tools.hbdi import run_hbdi_assessment
    # Seed an existing story
    cfg.PERSONAL_CONTEXT_FILE.write_text(
        json.dumps({"stories": [{"id": 1, "title": "Existing story", "story": "...", "tags": []}]})
    )
    run_hbdi_assessment(
        q1_no_spec_project=_Q1,
        q2_critical_feedback=_Q2,
        q3_tedious_finish=_Q3,
        q4_senior_disagreement=_Q4,
        **_SCORES_FRANK,
    )
    data = json.loads(cfg.PERSONAL_CONTEXT_FILE.read_text())
    assert len(data["stories"]) == 1
    assert data["stories"][0]["title"] == "Existing story"
    assert "hbdi_profile" in data


def test_run_hbdi_overwrites_previous_profile(isolated_server):
    import lib.config as cfg
    from tools.hbdi import run_hbdi_assessment
    run_hbdi_assessment(
        q1_no_spec_project="First attempt.",
        q2_critical_feedback=_Q2,
        q3_tedious_finish=_Q3,
        q4_senior_disagreement=_Q4,
        score_a=2, score_b=2, score_c=2, score_d=4,
    )
    run_hbdi_assessment(
        q1_no_spec_project="Updated answer.",
        q2_critical_feedback=_Q2,
        q3_tedious_finish=_Q3,
        q4_senior_disagreement=_Q4,
        **_SCORES_FRANK,
    )
    data = json.loads(cfg.PERSONAL_CONTEXT_FILE.read_text())
    assert data["hbdi_profile"]["responses"]["q1_no_spec_project"] == "Updated answer."


def test_run_hbdi_includes_notes(isolated_server):
    from tools.hbdi import run_hbdi_assessment
    result = run_hbdi_assessment(
        q1_no_spec_project=_Q1,
        q2_critical_feedback=_Q2,
        q3_tedious_finish=_Q3,
        q4_senior_disagreement=_Q4,
        notes="Self-assessment Feb 2026 with Nikki Ross conversation.",
        **_SCORES_FRANK,
    )
    assert "Nikki Ross" in result


def test_run_hbdi_confirms_save(isolated_server):
    from tools.hbdi import run_hbdi_assessment
    result = run_hbdi_assessment(
        q1_no_spec_project=_Q1,
        q2_critical_feedback=_Q2,
        q3_tedious_finish=_Q3,
        q4_senior_disagreement=_Q4,
        **_SCORES_FRANK,
    )
    assert "Profile saved" in result


def test_run_hbdi_rejects_invalid_score(isolated_server):
    from tools.hbdi import run_hbdi_assessment
    result = run_hbdi_assessment(
        q1_no_spec_project=_Q1,
        q2_critical_feedback=_Q2,
        q3_tedious_finish=_Q3,
        q4_senior_disagreement=_Q4,
        score_a=5, score_b=2, score_c=3, score_d=4,
    )
    assert "✗" in result
    assert "score_a" in result


def test_run_hbdi_rejects_zero_score(isolated_server):
    from tools.hbdi import run_hbdi_assessment
    result = run_hbdi_assessment(
        q1_no_spec_project=_Q1,
        q2_critical_feedback=_Q2,
        q3_tedious_finish=_Q3,
        q4_senior_disagreement=_Q4,
        score_a=3, score_b=0, score_c=3, score_d=4,
    )
    assert "✗" in result
    assert "score_b" in result


def test_run_hbdi_a_primary_gives_a_framing(isolated_server):
    from tools.hbdi import run_hbdi_assessment
    result = run_hbdi_assessment(
        q1_no_spec_project=_Q1,
        q2_critical_feedback=_Q2,
        q3_tedious_finish=_Q3,
        q4_senior_disagreement=_Q4,
        score_a=4, score_b=2, score_c=3, score_d=3,
    )
    assert "A (Analytical" in result
    assert "4/4 — Primary" in result


def test_run_hbdi_shows_strong_secondaries(isolated_server):
    from tools.hbdi import run_hbdi_assessment
    result = run_hbdi_assessment(
        q1_no_spec_project=_Q1,
        q2_critical_feedback=_Q2,
        q3_tedious_finish=_Q3,
        q4_senior_disagreement=_Q4,
        **_SCORES_FRANK,  # D=4, A=3, C=3, B=2
    )
    assert "Strong secondaries" in result
    assert "A" in result
    assert "C" in result


def test_run_hbdi_shows_present_not_dominant(isolated_server):
    from tools.hbdi import run_hbdi_assessment
    result = run_hbdi_assessment(
        q1_no_spec_project=_Q1,
        q2_critical_feedback=_Q2,
        q3_tedious_finish=_Q3,
        q4_senior_disagreement=_Q4,
        **_SCORES_FRANK,  # B=2 → present not dominant
    )
    assert "Present (not dominant)" in result


# ── get_hbdi_profile ──────────────────────────────────────────────────────────

def test_get_hbdi_profile_no_assessment(isolated_server):
    from tools.hbdi import get_hbdi_profile
    result = get_hbdi_profile()
    assert "No HBDI profile found" in result
    assert "run_hbdi_assessment" in result


def test_get_hbdi_profile_after_assessment(isolated_server):
    from tools.hbdi import run_hbdi_assessment, get_hbdi_profile
    run_hbdi_assessment(
        q1_no_spec_project=_Q1,
        q2_critical_feedback=_Q2,
        q3_tedious_finish=_Q3,
        q4_senior_disagreement=_Q4,
        **_SCORES_FRANK,
    )
    result = get_hbdi_profile()
    assert "HBDI COGNITIVE PROFILE" in result
    assert "Primary" in result
    assert "Assessed:" in result


def test_get_hbdi_profile_shows_responses(isolated_server):
    from tools.hbdi import run_hbdi_assessment, get_hbdi_profile
    run_hbdi_assessment(
        q1_no_spec_project=_Q1,
        q2_critical_feedback=_Q2,
        q3_tedious_finish=_Q3,
        q4_senior_disagreement=_Q4,
        **_SCORES_FRANK,
    )
    result = get_hbdi_profile()
    # Q1 response should appear in the report
    assert _Q1[:30] in result
