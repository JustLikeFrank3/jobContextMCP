"""Entailment critic, Phase 1 — per-claim verdicts, report-only.

Why this exists: after three rounds of cheaper levers, every surviving
hallucination class is *compositional* — true facts under the wrong role or
period, one effort's timeframe annexing sibling work, roadmap language
inflated to delivered capability. The deterministic gate cannot see these
(every token is present in the sources) and prompt rules bounced off them
twice (NUMERIC INTEGRITY vs LiveVoxNative, ATTRIBUTION DISCIPLINE vs the
Level-5 Azure placement — measured 2026-08-19: the class was unchanged while
the judge quoted the master's own correction note back at us). Placement is
an *entailment* question: not "does the source contain X" but "does the
source entail this sentence, with this subject, in this role and period."

Phase discipline (pre-registered before the first reading):

- **Phase 1 (this module): report-only.** One critique per golden entry per
  suite run — calibration needs coverage, not repetition — stored beside the
  judge's findings in the results payload. Blocks nothing, revises nothing,
  alerts nothing.
- **Phase 2: calibrate against human labels.** The owner's triage of the
  08-12/08-14 flag classes (A = fabrication, B = misstated, C = judge
  over-reach) is the acceptance test. Only classes where the critic's
  precision proves out graduate.
- **Phase 3: enforce selectively.** Contradicted-with-quoted-evidence routes
  to the revise pass like a gate violation; unsupported stays advisory.

The critic will false-positive — a third of the human-triaged classes were
judge over-reach, and a critic with a whistle and bad judgment strips TRUE
claims from documents, which is worse than doing nothing. That is why the
whistle comes after the calibration, never before.

Runs on the eval-judge client (``task="eval_judge"``): the generation-side
default has no calibration table and ranked nothing in the fixtures pass.
Same model as the judge means Phase 1 measures the *framing* variable —
holistic scoring vs per-claim entailment — which is exactly the question.
"""
from __future__ import annotations

import json
import re

CRITIC_SYSTEM = (
    "You are a claim-level entailment checker for generated application "
    "documents. You do not score quality and you do not rewrite. For each "
    "claim in the document you decide whether the source of truth ENTAILS "
    "it — same fact, same subject, same role and time period, same scope."
)

CRITIC_USER_TEMPLATE = """SOURCE OF TRUTH (the only evidence that exists):
{master}

DOCUMENT UNDER REVIEW:
{document}

Split the document into individual claims (each bullet, header line, and
summary sentence). For each claim, decide:

- ENTAILED — the source states it, with the same subject, the same role and
  time period, and the same scope. Paraphrase is fine; a claim the source
  plausibly supports is ENTAILED. When in doubt, ENTAILED.
- UNSUPPORTED — a plausible addition the source does not state.
- CONTRADICTED — the source states otherwise. This includes: a true fact
  placed under a different role or period than the source attributes it to;
  a timeframe the source ties to different work; a correction or guardrail
  note in the source that the claim violates; groundwork or roadmap language
  inflated into a delivered capability; and a scope the source explicitly
  bounds differently.

Attribution is part of the claim: a true fact in the wrong place is
CONTRADICTED, not entailed.

Return ONLY a JSON object listing the non-entailed claims (an empty list if
everything is entailed) — no other text:
{{"findings": [{{"claim": "<the claim, quoted or tightly paraphrased>",
  "verdict": "unsupported" or "contradicted",
  "evidence": "<for contradicted: the verbatim source passage it conflicts with; for unsupported: NONE>"}}]}}"""


def build_critic_messages(master: str, document: str) -> list[dict]:
    return [
        {"role": "system", "content": CRITIC_SYSTEM},
        {"role": "user", "content": CRITIC_USER_TEMPLATE.format(
            master=master, document=document)},
    ]


_VALID_VERDICTS = ("unsupported", "contradicted")


def parse_critic_json(text: str) -> list[dict]:
    """Parse the critic's response into a findings list.

    Tolerates reasoning-model chatter the same way the judge parser does:
    strips <think> blocks and code fences, takes the outermost {...} span.
    Findings with verdicts outside the two non-entailed values are dropped
    (a model listing entailed claims is being chatty, not wrong). Raises
    ValueError when no valid object can be recovered.
    """
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"```(?:json)?", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"no JSON object in critic response: {text[:120]!r}")
    try:
        obj = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"unparseable critic JSON: {e}") from e
    raw = obj.get("findings")
    if not isinstance(raw, list):
        raise ValueError("critic response has no findings list")
    findings = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        verdict = str(item.get("verdict", "")).lower().strip()
        if verdict not in _VALID_VERDICTS:
            continue
        findings.append({
            "claim": str(item.get("claim", "")).strip(),
            "verdict": verdict,
            "evidence": str(item.get("evidence", "") or "").strip(),
        })
    return findings


def critique_document(
    master: str,
    document: str,
    client=None,
    model: str = "",
    max_attempts: int = 2,
) -> dict:
    """One report-only critique: {"model": ..., "findings": [...]}.

    Resolves the eval-judge client when none is given (see module docstring
    for why not the generation default). Retries once on unparseable output.
    Raises on total failure — the CALLER decides that a critic failure must
    not cost anything (report-only means the run's judge scores stand).
    """
    from lib.openai_calls import create_chat_completion  # noqa: PLC0415 — lazy: keeps import light for tests

    if client is None:
        from lib.config import get_llm_client  # noqa: PLC0415

        client, model = get_llm_client(task="eval_judge")
        if client is None:
            raise RuntimeError("no LLM provider configured for the critic")
    messages = build_critic_messages(master, document)
    last_error: Exception | None = None
    for _ in range(max_attempts):
        response = create_chat_completion(
            client, label="eval_critic", model=model,
            # Same headroom logic as the judge: on a reasoning model the
            # budget covers internal reasoning FIRST; a starved budget returns
            # empty on some documents and not others — an uncontrolled
            # variable inside one measurement.
            messages=messages, temperature=0.0, max_tokens=8000,
        )
        content = response.choices[0].message.content or ""
        try:
            return {"model": model, "findings": parse_critic_json(content)}
        except ValueError as e:
            last_error = e
    raise ValueError(f"critic returned unparseable output after {max_attempts} attempts: {last_error}")


# ── Phase 3: enforcement (generation-time) ──────────────────────────────────
# Calibration verdict (2026-08-21 maiden run): 11/11 contradicted findings
# correct, every one carrying verbatim source evidence, zero over-reach on
# the human-triaged C-class, plus one catch the judge missed across five
# passes. That earned the whistle — for CONTRADICTED findings only.
# Unsupported stays advisory forever unless its own calibration happens:
# "plausible addition" is exactly where the over-reach risk lives.

def enforcement_enabled() -> bool:
    """Kill switch: CRITIC_ENFORCE=0 disables generation-time enforcement.

    Default ON — Phase 3 is a deliberate behavior change, not an accident,
    but a one-env rollback must exist because the enforcement path adds an
    LLM call inside every generation and a miscalibrated critic strips TRUE
    claims from real application documents.
    """
    import os  # noqa: PLC0415

    return os.environ.get("CRITIC_ENFORCE", "").strip().lower() not in ("0", "false", "no")


def enforceable_findings(critic_result: "dict | None") -> list[dict]:
    """The findings allowed to drive a revision: contradicted WITH evidence.

    A contradiction without a quoted source passage gives the reviser nothing
    to correct against and is indistinguishable from over-reach — it stays
    advisory. 'NONE' is the prompt's explicit no-evidence marker.
    """
    if not critic_result:
        return []
    out = []
    for f in critic_result.get("findings") or []:
        evidence = (f.get("evidence") or "").strip()
        if f.get("verdict") == "contradicted" and evidence and evidence.upper() != "NONE":
            out.append(f)
    return out


def format_contradiction_feedback(findings: list[dict]) -> str:
    """Render enforceable findings as a correction-prompt section.

    Mirrors lib.provenance.format_violation_feedback's contract: same section
    shape, so the single correction pass can carry both kinds of violation in
    one message. The fix instruction is specific because the generic "remove
    the unsourced claim" is wrong here — these claims are TRUE facts in the
    wrong place, and the fix is moving them to where the quoted source puts
    them, restoring the source's timeframe, or downgrading delivered-language
    to what the source states.
    """
    if not findings:
        return ""
    blocks = []
    for f in findings:
        blocks.append(
            f"  - CLAIM: {f.get('claim')}\n"
            f"    SOURCE SAYS: “{f.get('evidence')}”"
        )
    return (
        "ENTAILMENT VIOLATIONS (each claim below contradicts the quoted source "
        "passage — every word may be true and the claim is still wrong because "
        "of WHERE or HOW it is stated. Fix each claim to match its quoted "
        "source exactly: move the bullet to the role/period the source "
        "attributes it to, restore a timeframe to the specific work the source "
        "ties it to, or restate delivered-capability language as what the "
        "source actually says. Do not delete true facts — relocate or restate "
        "them):\n" + "\n".join(blocks)
    )
