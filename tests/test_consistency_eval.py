"""Tests for the assessment cross-run consistency eval (evals/consistency.py).

Everything here is offline and deterministic: assessments are stubbed,
the clustering/overlap math is exercised on hand-built gap lists shaped
like the BUG-3 finding (2026-08-28 WebMCP bug report) that motivated the
eval — one run of four uniquely surfacing the decision-relevant gap.
"""
from __future__ import annotations

import json

import pytest

from evals import consistency as cons
from evals.consistency import (
    ConsistencyReport,
    cluster_gaps,
    default_assess,
    extract_bullets,
    extract_gaps_section,
    mean_pairwise_overlap_pct,
    run_consistency,
)

_ASSESSMENT_TEMPLATE = """\
✓ Assessment complete for Senior Backend Engineer, Logistics Platform @ Harborline Technologies
  tokens: 100 in / 100 out
  (not saved — pass auto_save=True to persist)

## FITMENT SCORE
7/10 — solid platform fit.

## STRONG MATCHES
- Java and Spring Boot at scale.

## GAPS / RISKS
{gaps}

## KEY ANGLES TO EMPHASIZE
- Lead with the migration story.

## COMP ASSESSMENT
No compensation range was provided in the posting.

## RECOMMENDATION
Apply with caveats.
"""


def _assessment(gaps: list[str]) -> str:
    return _ASSESSMENT_TEMPLATE.format(gaps="\n".join(f"- {g}" for g in gaps))


# ── section + bullet extraction ───────────────────────────────────────────────

def test_extract_gaps_section_stops_at_next_header():
    section = extract_gaps_section(_assessment(["Gap one.", "Gap two."]))
    assert section is not None
    assert "Gap one." in section and "Gap two." in section
    assert "KEY ANGLES" not in section and "migration story" not in section


def test_extract_gaps_section_tolerates_spacing_and_case():
    for header in ("## GAPS / RISKS", "## Gaps/Risks", "##  GAPS  /  RISKS"):
        assert extract_gaps_section(f"{header}\n- the gap\n") == "\n- the gap\n"


def test_extract_gaps_section_at_end_of_document():
    assert extract_gaps_section("## GAPS / RISKS\n- last gap") == "\n- last gap"


def test_extract_gaps_section_absent_is_none():
    assert extract_gaps_section("## STRONG MATCHES\n- x\n") is None


def test_extract_bullets_markers_and_continuations():
    section = (
        "- dash gap\n"
        "* star gap\n"
        "• dot gap\n"
        "1. numbered gap\n"
        "2) parenthesis gap\n"
        "- wrapped gap\n"
        "  continues on the next line\n"
        "Prose between bullets is ignored.\n"
    )
    assert extract_bullets(section) == [
        "dash gap",
        "star gap",
        "dot gap",
        "numbered gap",
        "parenthesis gap",
        "wrapped gap continues on the next line",
    ]


def test_extract_bullets_empty_section():
    assert extract_bullets("None worth noting — the fit is clean.\n") == []


# ── clustering ────────────────────────────────────────────────────────────────

def test_cluster_merges_rewordings_and_separates_distinct_gaps():
    runs = [
        ["No formal ML model training or data science experience."],
        ["Lacks formal ML model training and data science background."],
        ["No Kafka experience at the required scale."],
    ]
    clusters = cluster_gaps(runs)
    assert len(clusters) == 2
    ml = next(c for c in clusters if "ML" in c.representative)
    assert ml.support == 2 and ml.runs == {0, 1}
    kafka = next(c for c in clusters if "Kafka" in c.representative)
    assert kafka.support == 1


def test_cluster_same_gap_twice_in_one_run_counts_one_run():
    clusters = cluster_gaps([["No Kafka experience.", "No Kafka experience at all."]])
    assert len(clusters) == 1 and clusters[0].support == 1


def test_overlap_pct_bug3_shape():
    # The BUG-3 anecdote: three runs agree on A/B/C, one run adds D.
    shared = [
        "No hands-on Kafka partitioning experience.",
        "No contractual SLA ownership in recent roles.",
        "Limited PostgreSQL query-planning depth.",
    ]
    unique = "No formal ML model training or data science experience."
    runs = [list(shared), list(shared), list(shared), [*shared, unique]]
    clusters = cluster_gaps(runs)
    assert len(clusters) == 4
    assert mean_pairwise_overlap_pct(clusters, 4) == pytest.approx(87.5)


def test_overlap_pct_identical_and_empty_runs():
    identical = cluster_gaps([["Gap alpha only."]] * 3)
    assert mean_pairwise_overlap_pct(identical, 3) == pytest.approx(100.0)
    # Two runs that both say "no gaps" agree perfectly.
    assert mean_pairwise_overlap_pct(cluster_gaps([[], []]), 2) == pytest.approx(100.0)


# ── report metrics + alerts ───────────────────────────────────────────────────

def _report_from_runs(runs: list[list[str]]) -> ConsistencyReport:
    report = ConsistencyReport(
        company="X", role="Y", jd_file="synthetic_jd.txt", n_requested=len(runs)
    )
    report.runs = runs
    report.clusters = cluster_gaps(runs)
    return report


def test_singleton_gap_raises_the_bug3_alert():
    shared = ["No hands-on Kafka partitioning experience."]
    unique = "No formal ML model training or data science experience."
    report = _report_from_runs([shared, shared, shared, [*shared, unique]])
    assert report.consensus_pct == pytest.approx(50.0)
    assert [c.representative for c in report.singletons] == [unique]
    assert any("only in run 4/4" in a and "ML model training" in a for a in report.alerts)
    # High shared overlap: the instability alert itself must not fire here.
    assert not any("unstable" in a for a in report.alerts)


def test_stable_runs_raise_no_alerts():
    report = _report_from_runs([["No SLA ownership in recent roles."]] * 3)
    assert report.overlap_pct == pytest.approx(100.0)
    assert report.consensus_pct == pytest.approx(100.0)
    assert report.alerts == []


def test_disjoint_runs_raise_instability_alert():
    report = _report_from_runs([
        ["No Kafka partitioning experience whatsoever."],
        ["Compensation expectations exceed the posted band."],
    ])
    assert report.overlap_pct == pytest.approx(0.0)
    assert any("unstable" in a for a in report.alerts)


def test_under_two_runs_is_not_measurable():
    report = _report_from_runs([["only one run completed"]])
    assert report.singletons == []
    assert report.alerts == ["fewer than 2 completed runs — agreement not measurable"]


def test_report_round_trips_to_dict_and_text():
    report = _report_from_runs([["No SLA ownership."], ["No SLA ownership at all."]])
    payload = report.to_dict()
    assert payload["n_ok"] == 2 and payload["gaps_per_run"] == [1, 1]
    assert payload["overlap_pct"] == 100.0 and payload["singleton_count"] == 0
    assert payload["clusters"][0]["support"] == "2/2"
    text = report.to_text()
    assert "mean pairwise overlap: 100%" in text and "2/2" in text


# ── run_consistency orchestration ─────────────────────────────────────────────

def test_run_consistency_end_to_end_with_stubbed_assessments():
    shared = ["No contractual SLA ownership.", "Limited PostgreSQL depth under load."]
    unique = "No formal ML model training or data science experience."
    outputs = iter([
        _assessment(shared),
        _assessment(shared),
        _assessment([*shared, unique]),
    ])
    report = run_consistency(n=3, assess_fn=lambda c, r, jd: next(outputs))
    assert report.n_ok == 3 and not report.errors
    assert report.jd_file == "synthetic_jd.txt"  # committed fixture resolved
    assert len(report.clusters) == 3
    assert len(report.singletons) == 1
    assert report.overlap_pct == pytest.approx((1 + 2 / 3 + 2 / 3) / 3 * 100)


def test_run_consistency_records_failed_runs_and_keeps_the_rest():
    calls = iter([
        RuntimeError("boom"),
        _assessment(["No SLA ownership."]),
        _assessment(["No SLA ownership."]),
    ])

    def assess(c, r, jd):
        item = next(calls)
        if isinstance(item, Exception):
            raise item
        return item

    report = run_consistency(n=3, assess_fn=assess)
    assert report.n_ok == 2
    assert report.errors == ["run 1: RuntimeError: boom"]
    assert report.alerts == []


def test_run_consistency_missing_gaps_section_fails_that_run():
    report = run_consistency(n=2, assess_fn=lambda c, r, jd: "✓ done\n## FITMENT SCORE\n8/10")
    assert report.n_ok == 0
    assert all("no GAPS / RISKS section" in e for e in report.errors)


def test_run_consistency_missing_jd_file_is_an_error_not_a_crash():
    report = run_consistency(n=2, jd_file="does-not-exist.txt", assess_fn=lambda *a: "")
    assert report.n_ok == 0
    assert report.errors == ["JD file not found: does-not-exist.txt"]


# ── default_assess ────────────────────────────────────────────────────────────

def test_default_assess_passes_auto_save_false_and_requires_success(monkeypatch):
    from tools import fitment

    seen: dict = {}

    def stub(company, role, job_description, persona="", auto_save=True):
        seen.update(auto_save=auto_save, kwargs_had_force=False)
        return _assessment(["No SLA ownership."])

    monkeypatch.setattr(fitment, "run_job_assessment", stub)
    output = default_assess("C", "R", "jd text")
    assert seen["auto_save"] is False
    assert "## GAPS / RISKS" in output


def test_default_assess_passes_force_when_the_guard_exists(monkeypatch):
    # The dedupe/reuse guard (fix/webmcp-bridge-bugs) adds a force param;
    # the eval must measure real regenerations once it lands.
    from tools import fitment

    seen: dict = {}

    def stub(company, role, job_description, persona="", auto_save=True, force=False):
        seen.update(auto_save=auto_save, force=force)
        return _assessment(["No SLA ownership."])

    monkeypatch.setattr(fitment, "run_job_assessment", stub)
    default_assess("C", "R", "jd text")
    assert seen == {"auto_save": False, "force": True}


def test_default_assess_rejects_fallback_and_error_outputs(monkeypatch):
    from tools import fitment

    for bad in ("═══ FITMENT ASSESSMENT ═══\ncontext pack", "✗ OpenAI API error: boom"):
        monkeypatch.setattr(fitment, "run_job_assessment", lambda *a, **k: bad)  # noqa: B023
        with pytest.raises(RuntimeError, match="assessment did not complete"):
            default_assess("C", "R", "jd")


# ── CLI ───────────────────────────────────────────────────────────────────────

def test_cli_consistency_writes_json_report(monkeypatch, tmp_path, capsys):
    from evals.__main__ import main

    monkeypatch.setattr(
        cons, "default_assess",
        lambda c, r, jd: _assessment(["No SLA ownership in recent roles."]),
    )
    out = tmp_path / "consistency.json"
    assert main(["consistency", "-n", "2", "--json", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["n_ok"] == 2 and payload["overlap_pct"] == 100.0
    assert payload["company"] == cons.DEFAULT_COMPANY
    assert "mean pairwise overlap: 100%" in capsys.readouterr().out
