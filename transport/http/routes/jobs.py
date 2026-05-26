"""Job evaluation and decision endpoints.

Sync endpoints:
    POST /jobs/evaluate          queue + assess fitment, return full result
    POST /jobs/decide            record add/dismiss decision

Streaming endpoints:
    POST /jobs/evaluate/stream   same as evaluate, but SSE per stage event
"""

from fastapi import APIRouter, Depends

from services import JobAnalysisService
from transport.http.auth import require_api_key
from transport.http.models import (
    JobDecisionRequest,
    JobDecisionResponse,
    JobEvaluateRequest,
    JobEvaluateResponse,
)
from transport.http.sse import sse_response


router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
    dependencies=[Depends(require_api_key)],
)


@router.post("/evaluate", response_model=JobEvaluateResponse)
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


@router.post("/decide", response_model=JobDecisionResponse)
async def decide(req: JobDecisionRequest) -> JobDecisionResponse:
    result = JobAnalysisService.decide(
        company=req.company,
        role=req.role,
        decision=req.decision,
        notes=req.notes,
        fitment_score=req.fitment_score,
    )
    return JobDecisionResponse(result=result)
