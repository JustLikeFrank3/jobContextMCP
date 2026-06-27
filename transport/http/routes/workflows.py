"""LangGraph workflow endpoints.

Sync:
    POST /workflows/{name}          run workflow, return final state JSON
    GET  /workflows                 list available workflow names

Streaming:
    POST /workflows/{name}/stream   SSE per node transition + final result
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from services import WorkflowService, UnknownWorkflowError
from transport.http.auth import require_api_key
from transport.http.sse import sse_response


router = APIRouter(
    prefix="/workflows",
    tags=["workflows"],
    dependencies=[Depends(require_api_key)],
)


@router.get("")
async def list_workflows() -> dict[str, list[str]]:
    return {"workflows": WorkflowService.list_workflows()}


@router.post("/{name}", responses={404: {"description": "Workflow not found"}})
async def run_workflow(name: str, inputs: dict[str, Any]) -> dict[str, Any]:
    try:
        return WorkflowService.run(name, inputs)
    except UnknownWorkflowError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{name}/stream", responses={404: {"description": "Workflow not found"}})
async def run_workflow_stream(name: str, inputs: dict[str, Any]):
    # Validate workflow name up-front so 404 surfaces immediately rather than
    # as an error event inside the SSE stream.
    if name not in WorkflowService.list_workflows():
        raise HTTPException(status_code=404, detail=f"Unknown workflow {name!r}")
    return sse_response(
        lambda cb: WorkflowService.run(name, inputs, on_progress=cb),
        result_to_payload=lambda r: {"keys": sorted(r.keys()), "success": r.get("success", False)},
    )
