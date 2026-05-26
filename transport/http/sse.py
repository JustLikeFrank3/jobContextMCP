"""Adapter for streaming a sync service callback as SSE events.

Services use a sync `on_progress(ProgressEvent)` callback pattern (see
services/events.py) so CLI and test consumers can drive them with zero
async overhead. For HTTP SSE we need to bridge sync emissions into an
async generator. This module runs the service call in a worker thread,
pushes events into an asyncio.Queue, and yields them to the response.

Usage:

    @router.post("/jobs/evaluate/stream")
    async def stream(req: JobEvaluateRequest):
        return sse_response(
            lambda cb: JobAnalysisService.evaluate(
                req.company, req.role, req.job_description,
                source=req.source, on_progress=cb,
            ),
            result_to_payload=lambda r: r.__dict__,
        )

The final service return value is emitted as a synthetic "result" event so
clients can consume the structured output without a second HTTP call.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, Awaitable, Callable, Optional

from sse_starlette.sse import EventSourceResponse

from services.events import ProgressEvent


_logger = logging.getLogger(__name__)

# Sentinel placed on the queue to signal the worker is done.
_DONE = object()


ServiceCallable = Callable[[Callable[[ProgressEvent], None]], Any]
ResultSerializer = Optional[Callable[[Any], dict[str, Any]]]


def sse_response(
    service_call: ServiceCallable,
    result_to_payload: ResultSerializer = None,
) -> EventSourceResponse:
    """Wrap a sync service invocation in an SSE stream.

    Args:
        service_call:      A callable that takes a single arg (a sync
                           progress callback) and runs a service method,
                           returning the structured result.
        result_to_payload: Optional function to convert the service return
                           value into a dict for the final "result" event.
                           Defaults to ``vars()`` for dataclass-like objects,
                           ``{"value": str(result)}`` for primitives.

    Returns:
        EventSourceResponse that streams `data: {...}\\n\\n` lines, one per
        emitted ProgressEvent plus a terminal "result" event. Each line
        includes an `event:` field set to the stage name.
    """
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def push(event: ProgressEvent) -> None:
        # Called from the worker thread; schedule the put on the event loop.
        asyncio.run_coroutine_threadsafe(queue.put(event), loop)

    def runner() -> None:
        try:
            result = service_call(push)
        except Exception as exc:  # noqa: BLE001 — surface any error to client
            _logger.exception("service_call failed in SSE worker")
            asyncio.run_coroutine_threadsafe(
                queue.put(_error_event(exc)), loop
            )
        else:
            payload = _serialize_result(result, result_to_payload)
            asyncio.run_coroutine_threadsafe(
                queue.put(ProgressEvent(stage="result", message="Service complete", payload=payload)),
                loop,
            )
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(_DONE), loop)

    threading.Thread(target=runner, daemon=True).start()

    async def event_iter():
        while True:
            item = await queue.get()
            if item is _DONE:
                return
            assert isinstance(item, ProgressEvent)
            yield {
                "event": item.stage,
                "data": json.dumps({
                    "stage": item.stage,
                    "message": item.message,
                    "payload": item.payload,
                }),
            }

    return EventSourceResponse(event_iter())


def _serialize_result(result: Any, custom: ResultSerializer) -> dict[str, Any]:
    if custom is not None:
        return custom(result)
    if hasattr(result, "__dict__"):
        return dict(vars(result))
    if isinstance(result, dict):
        return result
    return {"value": str(result)}


def _error_event(exc: BaseException) -> ProgressEvent:
    return ProgressEvent(
        stage="error",
        message=f"{type(exc).__name__}: {exc}",
        payload={"error_type": type(exc).__name__},
    )
