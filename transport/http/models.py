"""Pydantic request/response models for the HTTP API.

Kept intentionally small — each model maps to one endpoint. Service-layer
result dataclasses are converted to these response models at the route
boundary so internal refactors do not change the public API shape.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


# Health

class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "jobContextMCP"
    version: str
    auth_enabled: bool


# Jobs

class JobEvaluateRequest(BaseModel):
    company: str = Field(..., min_length=1)
    role: str = Field(..., min_length=1)
    job_description: str = Field(..., min_length=1)
    source: str = ""
    persona: str | None = Field(
        default=None,
        description="Optional persona name to bias the fitment lens (e.g. 'faang_technical', 'executive_polish'). Defaults to no persona.",
    )


class JobEvaluateResponse(BaseModel):
    company: str
    role: str
    queued: bool
    evaluated: bool
    queue_status: str
    fitment_context: str
    notes: list[str] = Field(default_factory=list)


class JobIngestUrlRequest(BaseModel):
    url: str = Field(..., min_length=8)
    source: str = "share_sheet"
    persona: str | None = Field(
        default=None,
        description="Optional persona name to bias fitment evaluation.",
    )


class JobIngestUrlResponse(BaseModel):
    url: str
    company: str
    role: str
    queued: bool
    evaluated: bool
    queue_status: str
    fitment_context: str
    notes: list[str] = Field(default_factory=list)
    message: str = ""


class JobDecisionRequest(BaseModel):
    company: str = Field(..., min_length=1)
    role: str = Field(..., min_length=1)
    decision: Literal["add", "dismiss"]
    notes: str = ""
    fitment_score: str = ""


class JobDecisionResponse(BaseModel):
    result: str


# Resumes

class ResumeGenerateRequest(BaseModel):
    company: str = Field(..., min_length=1)
    role: str = Field(..., min_length=1)
    job_description: str = Field(..., min_length=1)
    output_filename: str = ""
    kind: Literal["resume", "cover_letter"] = "resume"
    export_pipeline: Literal["html", "latex"] = "html"
    persona: str | None = Field(
        default=None,
        description="Optional persona name. Defaults to 'default' if omitted.",
    )


class ResumeGenerateResponse(BaseModel):
    success: bool
    company: str
    role: str
    kind: str
    content: str
    pdf_exported: bool
    notes: list[str] = Field(default_factory=list)


# Stories (STAR) + Tone

class StorySearchRequest(BaseModel):
    tag: str = Field(..., min_length=1, description="STAR tag, e.g. 'ai_adoption', 'leadership'.")
    company: str = ""
    role_type: str = ""


class StorySearchResponse(BaseModel):
    tag: str
    results: str = Field(..., description="Formatted STAR context text from get_star_story_context.")


class ToneProfileResponse(BaseModel):
    profile: str


# SSE event envelope

class StreamEvent(BaseModel):
    """Serialized form of a services.ProgressEvent for SSE consumers."""
    stage: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
