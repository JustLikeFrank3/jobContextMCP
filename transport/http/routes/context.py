"""STAR story retrieval and tone profile endpoints.

These wrap the existing tools.star and tools.tone single-step functions
directly — no service-layer orchestration needed because there is only
one step.
"""

from fastapi import APIRouter, Depends

from tools import star as _star
from tools import tone as _tone
from transport.http.auth import require_api_key
from transport.http.models import (
    StorySearchRequest,
    StorySearchResponse,
    ToneProfileResponse,
)


router = APIRouter(
    tags=["context"],
    dependencies=[Depends(require_api_key)],
)


@router.post("/stories/search", response_model=StorySearchResponse)
async def stories_search(req: StorySearchRequest) -> StorySearchResponse:
    result = _star.get_star_story_context(
        tag=req.tag, company=req.company, role_type=req.role_type,
    )
    return StorySearchResponse(tag=req.tag, results=result)


@router.get("/tone/profile", response_model=ToneProfileResponse)
async def tone_profile() -> ToneProfileResponse:
    return ToneProfileResponse(profile=_tone.get_tone_profile())
