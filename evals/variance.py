"""Layer 3 — variance analysis across N judge runs.

LLM outputs are non-deterministic; the same input can produce different
quality on different runs. These metrics quantify that risk per the doc:

    Mean score          — mean below the resume rubric threshold → flag for review
    CoV (%)             — std dev / mean × 100; > 20% → output unstable
    Hallucination rate  — % of runs flagging ≥1 hallucination; target 0%
    Verdict flip rate   — % of runs where the verdict flips; > 20% → add
                          temperature constraints
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from evals.judge import JUDGE_DIMENSIONS, JudgeScore
from evals.rubrics import THRESHOLDS

# Sourced from the resume rubric so the wallboard alert and the code-derived
# verdict cannot drift apart: 3.8 here once left a 3.8-4.0 band that failed
# the rubric with no alert firing.
MEAN_ALERT = THRESHOLDS["resume"].min_avg
COV_ALERT_PCT = 20.0
FLIP_ALERT_PCT = 20.0


def cov_percent(values: list[float]) -> float:
    """Coefficient of variation: sample std dev / mean × 100 (0 for n<2)."""
    if len(values) < 2:
        return 0.0
    mean = statistics.mean(values)
    if mean == 0:
        return 0.0
    return statistics.stdev(values) / mean * 100


def verdict_flip_rate(verdicts: list[str]) -> float:
    """% of runs disagreeing with the majority verdict (0 when unanimous)."""
    if not verdicts:
        return 0.0
    majority = max(set(verdicts), key=verdicts.count)
    return sum(v != majority for v in verdicts) / len(verdicts) * 100


@dataclass
class RunAggregate:
    """Variance metrics for one golden entry across N runs."""

    n_runs: int
    per_dimension: dict[str, dict[str, float]]  # dim → {mean, stdev, cov_pct}
    mean_score: float
    cov_pct: float
    hallucination_rate_pct: float
    flip_rate_pct: float
    verdicts: list[str] = field(default_factory=list)
    hallucinations: list[str] = field(default_factory=list)  # unique claims across runs

    @property
    def alerts(self) -> list[str]:
        found = []
        if self.mean_score < MEAN_ALERT:
            found.append(f"mean {self.mean_score:.2f} < {MEAN_ALERT} — flag for review")
        if self.cov_pct > COV_ALERT_PCT:
            found.append(f"CoV {self.cov_pct:.1f}% > {COV_ALERT_PCT}% — output unstable")
        if self.hallucination_rate_pct > 0:
            found.append(
                f"hallucination rate {self.hallucination_rate_pct:.0f}% — immediate review"
            )
        if self.flip_rate_pct > FLIP_ALERT_PCT:
            found.append(f"verdict flip rate {self.flip_rate_pct:.0f}% — non-deterministic")
        return found

    def to_dict(self) -> dict:
        return {
            "n_runs": self.n_runs,
            "mean_score": round(self.mean_score, 2),
            "cov_pct": round(self.cov_pct, 1),
            "hallucination_rate_pct": round(self.hallucination_rate_pct, 1),
            "verdict_flip_rate_pct": round(self.flip_rate_pct, 1),
            "per_dimension": {
                d: {k: round(v, 2) for k, v in m.items()}
                for d, m in self.per_dimension.items()
            },
            "verdicts": self.verdicts,
            "hallucinations": self.hallucinations,
            "alerts": self.alerts,
        }


def aggregate_runs(runs: list[JudgeScore]) -> RunAggregate:
    """Aggregate N judge scores for the same input into variance metrics."""
    if not runs:
        raise ValueError("aggregate_runs needs at least one judge score")
    per_dimension: dict[str, dict[str, float]] = {}
    for dim in JUDGE_DIMENSIONS:
        values = [float(r.scores[dim]) for r in runs]
        per_dimension[dim] = {
            "mean": statistics.mean(values),
            "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
            "cov_pct": cov_percent(values),
        }
    means = [r.mean for r in runs]
    verdicts = [r.verdict for r in runs]
    return RunAggregate(
        n_runs=len(runs),
        per_dimension=per_dimension,
        mean_score=statistics.mean(means),
        cov_pct=cov_percent(means),
        hallucination_rate_pct=sum(bool(r.hallucinations) for r in runs) / len(runs) * 100,
        flip_rate_pct=verdict_flip_rate(verdicts),
        verdicts=verdicts,
        hallucinations=sorted({h for r in runs for h in r.hallucinations}),
    )


def keyword_delta(current: RunAggregate, baseline: RunAggregate) -> float:
    """Mean keyword-coverage score vs. baseline; < −0.5 → prompt regression."""
    return (
        current.per_dimension["keyword_coverage"]["mean"]
        - baseline.per_dimension["keyword_coverage"]["mean"]
    )
