"""Layer 2 — output-quality rubrics.

Each rubric scores an output 1–5 per dimension. Applied by a human reviewer
or by the Layer 3 judge; either way the scores land in the same schema and
the same passing thresholds apply.
"""
from __future__ import annotations

from dataclasses import dataclass

RESUME_RUBRIC: dict[str, str] = {
    "keyword_coverage": "Key technical terms from the JD appear verbatim or as "
                        "close synonyms (1: none … 5: >75% covered).",
    "relevance": "Bullets emphasize experience most relevant to the target "
                 "role; irrelevant content deprioritized (1: generic … 5: laser-focused).",
    "accuracy": "Every claim traceable to the master resume; no hallucinated "
                "titles, dates, or achievements (1: hallucinations … 5: fully grounded).",
    "impact_language": "Strong action verbs; quantified results where present "
                       "in source (1: passive … 5: all bullets punchy + quantified).",
    "ats_readiness": "No tables/graphics/headers that break parsing; keywords "
                     "in plain text (1: multiple issues … 5: clean).",
    "format_compliance": "Correct section order, length (1 page for IC roles), "
                         "consistent formatting (1: wrong format … 5: perfect).",
}

COVER_LETTER_RUBRIC: dict[str, str] = {
    "hook_quality": "Opening grabs attention; does not start with 'I am "
                    "applying' (1: boilerplate … 5: memorable).",
    "company_specificity": "Mentions a real company detail — product, mission, "
                           "recent news (1: none … 5: deeply researched).",
    "voice_match": "Tone matches saved tone samples: direct, confident, not "
                   "flowery (1: off-brand … 5: spot on).",
    "story_bridge": "≥1 concrete story connects experience to a role "
                    "requirement (1: none … 5: compelling).",
    "cta_close": "Clear, confident call to action — not 'thank you for your "
                 "consideration' (1: weak/generic … 5: memorable close).",
}


@dataclass(frozen=True)
class Threshold:
    min_avg: float
    min_dimension: int


THRESHOLDS: dict[str, Threshold] = {
    "resume": Threshold(min_avg=4.0, min_dimension=3),
    "cover_letter": Threshold(min_avg=3.8, min_dimension=3),
}

RUBRICS: dict[str, dict[str, str]] = {
    "resume": RESUME_RUBRIC,
    "cover_letter": COVER_LETTER_RUBRIC,
}


def validate_scores(scores: dict[str, int], output_type: str) -> None:
    """Raise ValueError on unknown dimensions or out-of-range scores."""
    rubric = RUBRICS[output_type]
    unknown = set(scores) - set(rubric)
    if unknown:
        raise ValueError(f"unknown dimension(s) for {output_type}: {sorted(unknown)}")
    bad = {d: s for d, s in scores.items() if not (isinstance(s, int) and 1 <= s <= 5)}
    if bad:
        raise ValueError(f"scores must be integers 1–5, got: {bad}")


def passes(scores: dict[str, int], output_type: str) -> tuple[bool, str]:
    """Apply the passing thresholds; returns (passed, reason)."""
    validate_scores(scores, output_type)
    if not scores:
        return False, "no dimensions scored"
    t = THRESHOLDS[output_type]
    avg = sum(scores.values()) / len(scores)
    low = [f"{d}={s}" for d, s in scores.items() if s < t.min_dimension]
    if low:
        return False, f"dimension(s) below {t.min_dimension}: {', '.join(sorted(low))}"
    if avg < t.min_avg:
        return False, f"average {avg:.2f} below threshold {t.min_avg}"
    return True, f"average {avg:.2f} ≥ {t.min_avg}, no dimension below {t.min_dimension}"
