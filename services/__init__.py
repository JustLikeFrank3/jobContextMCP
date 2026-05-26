"""
Orchestration services for jobContextMCP.

The tool modules in `tools/` are already focused, plain-Python modules and
serve as the unit-level API surface. They are the right entry point for any
single-tool operation (CLI dispatch, MCP tool calls, direct imports from
FastAPI routes for simple endpoints).

This `services/` package adds a thin orchestration layer for MULTI-STEP
workflows that compose several tools and emit progress events along the way.
The primary consumer is the FastAPI / SSE transport in `transport/http/`,
where each named stage becomes a streamable event for browser / iPad clients.

Services are synchronous and take an optional `on_progress` callback. HTTP
routes wrap them in a threadpool + asyncio queue to stream events; CLI and
test callers can pass a list-appender or ignore events entirely.

Public exports:
    - ProgressEvent          : single named-stage event with optional payload
    - ResumeResult           : output of ResumeService.generate
    - AnalysisResult         : output of JobAnalysisService.evaluate
    - ResumeService          : multi-step resume + cover letter generation
    - JobAnalysisService     : queue + assess + decision orchestration
    - WorkflowService        : stub for LangGraph workflow (Phase C)
"""

from services.events import ProgressEvent, ProgressCallback, _emit
from services.resume_service import ResumeService, ResumeResult
from services.job_analysis_service import JobAnalysisService, AnalysisResult
from services.workflow_service import WorkflowService

__all__ = [
    "ProgressEvent",
    "ProgressCallback",
    "ResumeService",
    "ResumeResult",
    "JobAnalysisService",
    "AnalysisResult",
    "WorkflowService",
]
