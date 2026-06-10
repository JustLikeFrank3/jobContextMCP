"""Job evaluation and decision endpoints.

Sync endpoints:
    POST /jobs/evaluate          queue + assess fitment, return full result
    POST /jobs/ingest-url        scrape URL + queue + assess fitment
    POST /jobs/decide            record add/dismiss decision

Streaming endpoints:
    POST /jobs/evaluate/stream   same as evaluate, but SSE per stage event
"""

from fastapi import APIRouter, Depends
from fastapi import HTTPException

import httpx

from services import JobAnalysisService
from transport.http.auth import require_api_key
from tools import job_scraper as _job_scraper
from tools.job_scraper import LinkedInBlockedError as _LinkedInBlockedError
from transport.http.models import (
    JobDecisionRequest,
    JobDecisionResponse,
    JobEvaluateRequest,
    JobEvaluateResponse,
    JobIngestUrlRequest,
    JobIngestUrlResponse,
)
from transport.http.sse import sse_response


router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
    dependencies=[Depends(require_api_key)],
)


@router.post("/evaluate")
async def evaluate(req: JobEvaluateRequest) -> JobEvaluateResponse:
    result = JobAnalysisService.evaluate(
        company=req.company,
        role=req.role,
        job_description=req.job_description,
        source=req.source,
        persona=req.persona,
    )
    return JobEvaluateResponse(
        company=result.company,
        role=result.role,
        queued=result.queued,
        evaluated=result.evaluated,
        queue_status=result.queue_status,
        fitment_context=result.fitment_context,
        notes=result.notes,
    )


@router.post(
    "/ingest-url",
    responses={
        400: {
            "description": "Invalid/unfetchable URL or unparseable job posting",
        }
    },
)
async def ingest_url(req: JobIngestUrlRequest) -> JobIngestUrlResponse:
    """Scrape a job URL, queue it, and run fitment evaluation in one call."""
    req = req.model_copy(update={"url": req.url.strip()})
    try:
        text = _job_scraper._fetch_jina(req.url)
    except _LinkedInBlockedError:
        # LinkedIn blocks Jina and usually requires login for full JD content.
        # Return 200 with a machine-readable status so iOS Shortcuts "Show
        # Result" displays a friendly message instead of crashing on a 4xx.
        return JobIngestUrlResponse(
            url=req.url,
            company="",
            role="",
            queued=False,
            evaluated=False,
            queue_status="linkedin_blocked",
            fitment_context="",
            message="⚠️ LinkedIn blocked — share the ATS URL instead (tap Apply first)",
            notes=[
                "LinkedIn blocks automated scraping (HTTP 451). "
                "On your phone: tap \u22ef in LinkedIn, choose \u2018Copy link\u2019 or select all text "
                "in the posting, then open the dashboard \u2192 Pipeline \u2192 \u2b50 Add Job and paste "
                "the job description there.",
            ],
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"HTTP {exc.response.status_code} fetching URL; page may require login.",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {exc}") from exc

    if not text.strip():
        raise HTTPException(
            status_code=400,
            detail="No content returned from URL; page may require login or block scraping.",
        )

    company, role, description = _job_scraper._parse_job_from_markdown(text, req.url)
    if not role:
        raise HTTPException(
            status_code=400,
            detail="Could not extract role from URL. Try manual queue/evaluate.",
        )

    result = JobAnalysisService.evaluate(
        company=company,
        role=role,
        job_description=description,
        source=req.source or req.url,
        persona=req.persona,
    )

    notes = list(result.notes)
    notes.append(f"Scraped from: {req.url}")

    return JobIngestUrlResponse(
        url=req.url,
        company=result.company,
        role=result.role,
        queued=result.queued,
        evaluated=result.evaluated,
        queue_status=result.queue_status,
        fitment_context=result.fitment_context,
        notes=notes,
        message=f"{result.role} @ {result.company} ({result.queue_status})",
    )


@router.post("/evaluate/stream")
async def evaluate_stream(req: JobEvaluateRequest):
    return sse_response(
        lambda cb: JobAnalysisService.evaluate(
            company=req.company,
            role=req.role,
            job_description=req.job_description,
            source=req.source,
            persona=req.persona,
            on_progress=cb,
        ),
    )


@router.post("/decide")
async def decide(req: JobDecisionRequest) -> JobDecisionResponse:
    result = JobAnalysisService.decide(
        company=req.company,
        role=req.role,
        decision=req.decision,
        notes=req.notes,
        fitment_score=req.fitment_score,
    )
    return JobDecisionResponse(result=result)
