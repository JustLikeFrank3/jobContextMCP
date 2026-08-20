"""insights(action="evals_results") — the MCP pull path for eval outcomes.

Why this exists: an MCP client could TRIGGER a suite run through the HTTP
API but had no way to READ the outcome — the payload was reachable only via
the authenticated JSON route or the kiosk page, so "pull the results and
summarize" required the operator to paste JSON by hand (2026-08-18). The
action is read-only by contract.
"""
from __future__ import annotations

import json

from lib import config
from tools.consolidated import DOMAINS, insights

PAYLOAD = {
    "updated_at": "2026-08-18T16:25:17",
    "suite": {
        "judge_model": "claude-sonnet-5",
        "n_runs": 5,
        "started_at": "2026-08-18T15:06:26",
        "rows": [
            {"gd_id": "GD-01", "role": "AI Native Engineer", "mean": 3.52,
             "accuracy": 3.6, "cov_pct": 5.1, "flip_rate_pct": 0.0,
             "alerts": ["3 hallucination flags in 3/5 runs — immediate review"]},
            {"gd_id": "GD-09", "role": "Broken", "error": "generation failed"},
        ],
        "detail": {
            "GD-01": {"hallucination_flags": 3,
                      "hallucinations": ["renamed the project", "5+ years of X"]},
        },
    },
}


def _seed(payload) -> None:
    config.EVAL_RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.EVAL_RESULTS_FILE.write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_registered_as_read_only_insights_action():
    fn, desc = DOMAINS["insights"]["evals_results"]
    assert "read-only" in desc.lower()
    import inspect

    # Nothing writable in the signature — summarize and expose, never mutate.
    assert set(inspect.signature(fn).parameters) == {"raw"}


def test_synopsis_carries_scores_alerts_claims_and_flags(isolated_server):
    _seed(PAYLOAD)
    out = insights(action="evals_results")
    assert "claude-sonnet-5" in out
    assert "GD-01" in out and "3.52" in out
    assert "3 hallucination flags in 3/5 runs" in out          # alert verbatim
    assert "renamed the project" in out                        # claim quoted
    assert "errored: generation failed" in out                 # errors shown, not hidden
    # flags column carries the volume signal
    assert "· 3" in out


def test_flags_column_dashes_for_pre_count_payloads(isolated_server):
    old = json.loads(json.dumps(PAYLOAD))
    del old["suite"]["detail"]["GD-01"]["hallucination_flags"]
    _seed(old)
    line = next(l for l in insights(action="evals_results").splitlines()
                if l.strip().startswith("GD-01"))
    assert line.rstrip().endswith("—")  # a dash, never a fake zero


def test_raw_returns_the_json_payload(isolated_server):
    _seed(PAYLOAD)
    out = insights(action="evals_results", raw=True)
    assert json.loads(out)["suite"]["n_runs"] == 5


def test_empty_partition_degrades_to_a_sentence(isolated_server):
    if config.EVAL_RESULTS_FILE.exists():
        config.EVAL_RESULTS_FILE.unlink()
    out = insights(action="evals_results")
    assert "No stored eval run" in out


def test_critic_findings_render_in_the_synopsis(isolated_server):
    payload = json.loads(json.dumps(PAYLOAD))
    payload["suite"]["detail"]["GD-01"]["critic"] = {
        "model": "claude-sonnet-5",
        "findings": [
            {"claim": "Azure work under Level 5", "verdict": "contradicted",
             "evidence": "MADM was on-prem until 2025"},
            {"claim": "adept at workshops", "verdict": "unsupported", "evidence": "NONE"},
        ],
    }
    _seed(payload)
    out = insights(action="evals_results")
    assert "CRITIC FINDINGS (entailment, report-only)" in out
    assert "[contradicted]" in out and "MADM was on-prem until 2025" in out
    assert "[unsupported]" in out
    assert "NONE" not in out.split("CRITIC FINDINGS")[1]  # NONE evidence not rendered


def test_no_critic_section_for_pre_critic_payloads(isolated_server):
    _seed(PAYLOAD)
    assert "CRITIC FINDINGS" not in insights(action="evals_results")
