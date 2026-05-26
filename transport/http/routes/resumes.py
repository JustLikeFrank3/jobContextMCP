"""Resume and cover letter generation endpoints.

Sync endpoint:
    POST /resumes/generate          returns full ResumeResult JSON

Streaming endpoint:
    POST /resumes/generate/stream   SSE per stage event, final result event

Use `kind: "resume"` (default) or `kind: "cover_letter"` in the request body
to choose the pipeline.
"""

from fastapi import APIRouter, Depends

from services import ResumeService
from transport.http.auth import require_api_key
from transport.http.models import ResumeGenerateRequest, ResumeGenerateResponse
from transport.http.sse import sse_response


router = APIRouter(
    prefix="/resumes",
    tags=["resumes"],
    dependencies=[Depends(require_api_key)],
)


@router.post("/generate", response_model=ResumeGenerateResponse)
async def generate(req: ResumeGenerateRequest) -> ResumeGenerateResponse:
    result = ResumeService.generate(
        company=req.company,
        role=req.role,
        job_description=req.job_description,
        output_filename=req.output_filename,
        kind=req.kind,
        persona=req.persona,
    )
    return ResumeGenerateResponse(
        success=result.success,
        company=result.company,
        role=result.role,
        kind=result.kind,
        content=result.content,
        pdf_exported=result.pdf_exported,
        notes=result.notes,
    )


@router.post("/generate/stream")
async def generate_stream(req: ResumeGenerateRequest):
    return sse_response(
        lambda cb: ResumeService.generate(
            company=req.company,
            role=req.role,
            job_description=req.job_description,
            output_filename=req.output_filename,
            kind=req.kind,
            persona=req.persona,
            on_progress=cb,
        ),
    )
