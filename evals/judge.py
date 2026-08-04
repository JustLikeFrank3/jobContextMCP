"""Layer 3 — adversarial LLM judge.

A separate model call receives the JD, a master-resume excerpt, and the
generated output, and returns structured per-dimension scores. The judge is
prompted to find weaknesses — hallucinations, weak bullets, missing
keywords, voice drift — not to be generous.

Calls go through ``lib.openai_calls.create_chat_completion`` like every
other LLM call in the system (rate spacing, retry semantics), against the
provider resolved by ``lib.config.get_llm_client``.
"""
from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass, field

from evals.rubrics import THRESHOLDS, RESUME_RUBRIC

# The judge scores the doc's five JSON dimensions (format_compliance stays a
# human/Layer-2 check — the judge sees plain text, not layout).
JUDGE_DIMENSIONS: tuple[str, ...] = (
    "keyword_coverage", "relevance", "accuracy", "impact_language", "ats_readiness",
)

JUDGE_SYSTEM = (
    "You are an adversarial resume evaluator. Your job is to find weaknesses, "
    "not to be kind. Look for hallucinations (claims not traceable to the "
    "master resume), weak bullets, missing keywords, and voice drift. "
    "Score honestly and critically."
)


def _build_rubric_block() -> str:
    threshold = THRESHOLDS["resume"]
    lines = [
        "SCORING RUBRIC:",
        *[f"- {dim}: {RESUME_RUBRIC[dim]}" for dim in JUDGE_DIMENSIONS],
        "",
        f"PASS CRITERION: A score is PASS only when the average of the five dimensions is >= {threshold.min_avg:.1f} and no dimension is below {threshold.min_dimension}.",
    ]
    return "\n".join(lines)


JUDGE_USER_TEMPLATE = """TODAY'S DATE: {today}. Dates on or before today are NOT future-dated; \
 do not flag employment dates as hallucinations merely because they are recent.

JOB DESCRIPTION:
{job_description}

MASTER RESUME EXCERPT:
{master_resume_excerpt}

GENERATED OUTPUT:
{generated_output}

{rubric_block}

Score the output on each dimension 1-5. The "hallucinations" list must contain \
ONLY claims from the output that cannot be traced to the master resume excerpt — \
if there are none, return an empty list []. Return ONLY a JSON object, no other text:
{{"keyword_coverage": N, "relevance": N, "accuracy": N, "impact_language": N,
 "ats_readiness": N, "rationale": "...", "hallucinations": ["..."],
 "verdict": "pass" or "fail"}}"""


@dataclass
class JudgeScore:
    scores: dict[str, int]
    rationale: str = ""
    hallucinations: list[str] = field(default_factory=list)
    verdict: str = "fail"
    raw: str = ""

    @property
    def mean(self) -> float:
        return sum(self.scores.values()) / len(self.scores) if self.scores else 0.0

    def to_dict(self) -> dict:
        return {
            **self.scores,
            "mean": round(self.mean, 2),
            "rationale": self.rationale,
            "hallucinations": self.hallucinations,
            "verdict": self.verdict,
        }


def build_judge_messages(
    job_description: str,
    master_resume_excerpt: str,
    generated_output: str,
    today: str = "",
) -> list[dict]:
    if not today:
        today = datetime.date.today().isoformat()
    return [
        {"role": "system", "content": JUDGE_SYSTEM},
        {"role": "user", "content": JUDGE_USER_TEMPLATE.format(
            today=today,
            job_description=job_description,
            master_resume_excerpt=master_resume_excerpt,
            generated_output=generated_output,
            rubric_block=_build_rubric_block(),
        )},
    ]


# Judges sometimes put a clean-bill NOTE into the hallucinations array
# ("No hallucinations detected...") — counting those as hallucinations
# inflated the rate to 60% on an entry with zero real findings.
_CLEAN_BILL = re.compile(r"(?i)\bno hallucinations?\b|^none\b\.?$")


def parse_judge_json(text: str) -> JudgeScore:
    """Parse the judge's response into a JudgeScore.

    Tolerates reasoning-model chatter: strips <think> blocks and code fences,
    then takes the outermost {...} span. Raises ValueError when no valid
    judge object can be recovered.
    """
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"```(?:json)?", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"no JSON object in judge response: {text[:120]!r}")
    try:
        obj = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"unparseable judge JSON: {e}") from e

    scores: dict[str, int] = {}
    for dim in JUDGE_DIMENSIONS:
        value = obj.get(dim)
        if not isinstance(value, (int, float)) or not 1 <= value <= 5:
            raise ValueError(f"judge score {dim}={value!r} not in 1–5")
        scores[dim] = int(value)
    verdict = str(obj.get("verdict", "")).lower()
    if verdict not in ("pass", "fail"):
        raise ValueError(f"judge verdict {obj.get('verdict')!r} not pass/fail")
    hallucinations = obj.get("hallucinations") or []
    if not isinstance(hallucinations, list):
        hallucinations = [str(hallucinations)]
    hallucinations = [str(h) for h in hallucinations if not _CLEAN_BILL.search(str(h))]
    from evals.rubrics import passes  # noqa: PLC0415

    verdict = "pass" if passes(scores, "resume")[0] else "fail"
    return JudgeScore(
        scores=scores,
        rationale=str(obj.get("rationale", "")),
        hallucinations=[str(h) for h in hallucinations],
        verdict=verdict,
        raw=text,
    )


def judge_output(
    job_description: str,
    master_resume_excerpt: str,
    generated_output: str,
    client=None,
    model: str = "",
    max_attempts: int = 2,
) -> JudgeScore:
    """Run one judge call and return the parsed score.

    Without an explicit *client*, resolves the configured provider via
    ``get_llm_client()`` and raises RuntimeError when none is ready (so
    callers surface a clear "configure a provider" message, not a crash).
    Retries once on unparseable output before giving up.
    """
    from lib.openai_calls import create_chat_completion  # noqa: PLC0415 — lazy: keeps import light for tests

    if client is None:
        from lib.config import get_llm_client  # noqa: PLC0415

        client, model = get_llm_client(task="eval_judge")
        if client is None:
            raise RuntimeError(
                "No LLM provider configured for the judge — set llm_provider "
                "in config.json (see lib.config.get_llm_client)."
            )
    messages = build_judge_messages(job_description, master_resume_excerpt, generated_output)
    last_error: Exception | None = None
    for _ in range(max_attempts):
        response = create_chat_completion(
            client, label="eval_judge", model=model,
            messages=messages, temperature=0.0,
        )
        content = response.choices[0].message.content or ""
        try:
            return parse_judge_json(content)
        except ValueError as e:
            last_error = e
    raise ValueError(f"judge returned unparseable output after {max_attempts} attempts: {last_error}")
