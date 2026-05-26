"""
JobAnalysisService: orchestrates the queue → evaluate → decide pipeline for
new job descriptions, plus standalone fitment assessment.

Wraps tools.job_queue and tools.fitment, emitting progress events around each
step so HTTP / SSE consumers can stream the analysis as it happens.

For single-step fitment assessment (no queue interaction), callers should
import tools.fitment.assess_job_fitment directly.
"""

from dataclasses import dataclass, field
from typing import Optional

from services.events import ProgressCallback, _emit
from tools import fitment as _fitment
from tools import job_queue as _job_queue


@dataclass
class AnalysisResult:
    """Structured result of a JobAnalysisService.evaluate call.

    Attributes:
        company:           Company name.
        role:              Role title.
        queued:            True if the job was newly queued or already present
                           in the queue and ready for evaluation.
        evaluated:         True if the fitment assessment was assembled.
        fitment_context:   The fitment context package text (master resume +
                           JD + interview context). Empty if evaluation skipped.
        queue_status:      Final status of the queue entry after this call.
        notes:             Non-fatal warnings collected during orchestration.
    """
    company: str
    role: str
    queued: bool
    evaluated: bool
    fitment_context: str
    queue_status: str
    notes: list[str] = field(default_factory=list)


class JobAnalysisService:
    """Orchestrates job description intake, fitment assessment, and decision."""

    @staticmethod
    def evaluate(
        company: str,
        role: str,
        job_description: str,
        source: str = "",
        on_progress: Optional[ProgressCallback] = None,
    ) -> AnalysisResult:
        """Queue a job and run fitment evaluation in one call.

        If the job is already queued, the existing entry is reused. If it has
        already been decided (added or dismissed), evaluation is skipped and
        the existing status is returned.

        Stages emitted:
            "queuing"     — about to call queue_job
            "queued"      — queue step finished, includes whether it was new
            "evaluating"  — about to call evaluate_queued_job
            "complete"    — full evaluation done, includes status

        Args:
            company:         Target company name.
            role:            Target role title.
            job_description: Full JD text.
            source:          Optional source label (e.g. "linkedin", "referral").
            on_progress:     Optional callback for streaming progress events.

        Returns:
            AnalysisResult with fitment_context populated when evaluation ran.
        """
        _emit(on_progress, "queuing", f"Queuing {company} — {role}",
              {"company": company, "role": role, "source": source})

        queue_result = _job_queue.queue_job(company, role, job_description, source)
        already_queued = queue_result.startswith("Already queued")

        _emit(on_progress, "queued",
              "Job already in queue" if already_queued else "Job added to queue",
              {"already_queued": already_queued})

        _emit(on_progress, "evaluating", "Running fitment assessment")

        fitment_result = _job_queue.evaluate_queued_job(company, role)

        # evaluate_queued_job returns the fitment context on success, or an
        # informational message when the job is already decided / not found.
        is_fitment_context = "FITMENT ASSESSMENT" in fitment_result
        is_already_decided = "already decided" in fitment_result

        notes = []
        if is_already_decided:
            notes.append("Job already decided — fitment context not regenerated")

        queue_status = "evaluated" if is_fitment_context else (
            "decided" if is_already_decided else "unknown"
        )

        _emit(on_progress, "complete",
              f"Evaluation finished (status: {queue_status})",
              {"queue_status": queue_status, "has_fitment": is_fitment_context})

        return AnalysisResult(
            company=company,
            role=role,
            queued=True,
            evaluated=is_fitment_context,
            fitment_context=fitment_result if is_fitment_context else "",
            queue_status=queue_status,
            notes=notes,
        )

    @staticmethod
    def assess(
        company: str,
        role: str,
        job_description: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> str:
        """Standalone fitment assessment (no queue interaction).

        Use when a caller just wants the fitment context for an ad-hoc JD that
        will not be tracked in the queue or pipeline.

        Args:
            company:         Target company name.
            role:            Target role title.
            job_description: Full JD text.
            on_progress:     Optional progress callback.

        Returns:
            The fitment context package text.
        """
        _emit(on_progress, "assessing", f"Assessing fitment for {role} @ {company}",
              {"company": company, "role": role})

        result = _fitment.assess_job_fitment(company, role, job_description)

        _emit(on_progress, "complete", "Fitment assessment finished")
        return result

    @staticmethod
    def decide(
        company: str,
        role: str,
        decision: str,
        notes: str = "",
        fitment_score: str = "",
        on_progress: Optional[ProgressCallback] = None,
    ) -> str:
        """Record the add/dismiss decision on an evaluated job.

        Thin orchestration wrapper around tools.job_queue.decide_job that emits
        progress events. Useful when an HTTP route wants to stream the
        full evaluate → decide flow.

        Args:
            company:       Company name.
            role:          Role title.
            decision:      "add" or "dismiss".
            notes:         Optional decision notes.
            fitment_score: Optional score string (e.g. "7/10").
            on_progress:   Optional progress callback.

        Returns:
            The result string from the underlying tool.
        """
        _emit(on_progress, "deciding", f"Recording decision '{decision}' for {company} — {role}",
              {"company": company, "role": role, "decision": decision})

        result = _job_queue.decide_job(company, role, decision, notes, fitment_score)

        _emit(on_progress, "complete", f"Decision recorded: {decision}")
        return result
