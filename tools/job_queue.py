"""
Job queue / evaluation pipeline — v1

A pre-pipeline inbox for evaluating job descriptions before committing to an
application. Workflow:

  1. queue_job          — drop a JD into the inbox (status: pending)
  2. evaluate_queued_job — run fitment analysis (status: evaluated)
  3. decide_job         — add (creates "interested" application) or dismiss

Dismissals are soft-deleted; all records remain queryable via get_job_queue.
"""

import re

from lib import config
from lib.io import _load_json, _save_json, _now
from tools.job_hunt import update_application
from tools.fitment import run_job_assessment


_VALID_STATUSES = {"pending", "evaluated", "added", "dismissed"}

_FITMENT_SCORE_RE = re.compile(r"##\s*FITMENT\s*SCORE\s*\n\s*(\d{1,2}/10)", re.IGNORECASE)



def _extract_fitment_score(text: str) -> str | None:
    m = _FITMENT_SCORE_RE.search(text or "")
    return m.group(1).strip() if m else None


def _extract_assessment_content(full_response: str) -> str:
    """Extract just the assessment content, stripping metadata prefix."""
    marker = "## FITMENT SCORE"
    if marker in full_response:
        idx = full_response.find(marker)
        return full_response[idx:].strip()
    return full_response


def _next_id(jobs: list[dict]) -> int:
    if not jobs:
        return 1
    return max(j.get("id", 0) for j in jobs) + 1


def _find_job(jobs: list[dict], company: str, role: str) -> dict | None:
    company_l = company.lower()
    role_l = role.lower()
    return next(
        (j for j in jobs if j["company"].lower() == company_l and j["role"].lower() == role_l),
        None,
    )


def queue_job(company: str, role: str, jd: str, source: str = "") -> str:
    """Add a job description to the evaluation queue for later fitment review. Status starts as 'pending'. Run evaluate_queued_job next."""
    data = _load_json(config.JOB_QUEUE_FILE, {"jobs": []})
    jobs: list = data.setdefault("jobs", [])

    existing = _find_job(jobs, company, role)
    if existing:
        return (
            f"Already queued: {company} — {role} (status: {existing['status']}). "
            "Use evaluate_queued_job to assess it."
        )

    jobs.append({
        "id": _next_id(jobs),
        "company": company,
        "role": role,
        "jd": jd,
        "source": source,
        "added_date": _now(),
        "status": "pending",
        "fitment_context": None,
        "fitment_score": None,
        "decision_notes": None,
        "decided_date": None,
    })
    _save_json(config.JOB_QUEUE_FILE, data)
    return f"Queued: {company} — {role}. Run evaluate_queued_job to assess fitment before deciding."


def get_job_queue(status: str = "") -> str:
    """Return all jobs in the evaluation queue. Optionally filter by status: pending, evaluated, added, dismissed."""
    data = _load_json(config.JOB_QUEUE_FILE, {"jobs": []})
    jobs: list = data.get("jobs", [])

    if status:
        jobs = [j for j in jobs if j.get("status") == status]

    if not jobs:
        label = f" with status '{status}'" if status else ""
        return f"No jobs in queue{label}."

    lines = ["═══ JOB QUEUE ═══", ""]
    for j in jobs:
        lines.append(f"■ [{j['status'].upper()}] {j['company']} — {j['role']}")
        lines.append(f"  ID:       {j['id']}")
        lines.append(f"  Added:    {j.get('added_date', '—')}")
        if j.get("source"):
            lines.append(f"  Source:   {j['source']}")
        if j.get("fitment_score"):
            lines.append(f"  Fitment:  {j['fitment_score']}")
        if j.get("decision_notes"):
            lines.append(f"  Notes:    {j['decision_notes']}")
        if j.get("decided_date"):
            lines.append(f"  Decided:  {j['decided_date']}")
        lines.append("")

    return "\n".join(lines)


def evaluate_queued_job(company: str, role: str, persona: str = "") -> str:
    """Run fitment analysis on a queued job. Loads the stored JD and assembles a full fitment context package for review. Sets status to 'evaluated' so decide_job can proceed. After reviewing this output, call decide_job with 'add' or 'dismiss'.

    Optional `persona` (e.g. 'faang_technical', 'executive_polish') prepends a
    persona lens to the context pack so the consuming agent applies role-specific
    weighting.
    """
    data = _load_json(config.JOB_QUEUE_FILE, {"jobs": []})
    jobs: list = data.get("jobs", [])

    job = _find_job(jobs, company, role)
    if job is None:
        return f"No queued job found for {company} — {role}. Use queue_job to add it first."

    if job["status"] in ("added", "dismissed"):
        return (
            f"{company} — {role} is already decided (status: {job['status']}). "
            "No re-evaluation needed."
        )

    # Run full LLM assessment
    assessment_response = run_job_assessment(
        company=company,
        role=role,
        job_description=job.get("jd", ""),
        persona=persona,
        auto_save=True,
    )

    # Check for error responses
    if assessment_response.startswith("✗"):
        return assessment_response

    # Extract structured assessment content
    assessment_content = _extract_assessment_content(assessment_response)
    
    # Validate extraction worked
    if not assessment_content or assessment_content.startswith("✗"):
        return f"Assessment extraction failed. Response:\n{assessment_response[:300]}"

    # Persist assessment data to job queue
    job["status"] = "evaluated"
    job["fitment_context"] = assessment_content
    parsed_score = _extract_fitment_score(assessment_content)
    if parsed_score:
        job["fitment_score"] = parsed_score
    _save_json(config.JOB_QUEUE_FILE, data)

    return assessment_response



def decide_job(
    company: str,
    role: str,
    decision: str,
    notes: str = "",
    fitment_score: str = "",
) -> str:
    """Record your add/dismiss decision on an evaluated job.

    decision must be 'add' or 'dismiss'.
    - 'add'     creates an application at status 'interested' in the pipeline.
    - 'dismiss' soft-deletes the queue entry (still queryable).

    Requires evaluate_queued_job to have been run first (gate enforced).
    Optionally pass fitment_score (e.g. '7/10') to record the analysis result.
    """
    decision = decision.strip().lower()
    if decision not in ("add", "dismiss"):
        return "Invalid decision. Use 'add' or 'dismiss'."

    data = _load_json(config.JOB_QUEUE_FILE, {"jobs": []})
    jobs: list = data.get("jobs", [])

    job = _find_job(jobs, company, role)
    if job is None:
        return f"No queued job found for {company} — {role}."

    if job["status"] == "pending":
        return (
            f"{company} — {role} has not been evaluated yet. "
            "Run evaluate_queued_job first."
        )

    if job["status"] == "added":
        return f"{company} — {role} was already added to the pipeline."

    if job["status"] == "dismissed":
        return f"{company} — {role} was already dismissed."

    # Commit decision
    job["decision_notes"] = notes or None
    job["fitment_score"] = fitment_score or job.get("fitment_score")
    job["decided_date"] = _now()

    if decision == "add":
        job["status"] = "added"
        _save_json(config.JOB_QUEUE_FILE, data)
        update_result = update_application(
            company=company,
            role=role,
            status="interested",
            notes=f"Added from job queue.{(' ' + notes) if notes else ''}",
        )
        return f"Added {company} — {role} to pipeline as 'interested'.\n{update_result}"

    # dismiss
    job["status"] = "dismissed"
    _save_json(config.JOB_QUEUE_FILE, data)
    return f"Dismissed: {company} — {role}.{(' Reason: ' + notes) if notes else ''}"


def register(mcp) -> None:
    mcp.tool()(queue_job)
    mcp.tool()(get_job_queue)
    mcp.tool()(evaluate_queued_job)
    mcp.tool()(decide_job)
