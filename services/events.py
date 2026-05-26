"""
Progress event primitives for streaming multi-step service operations.

A ProgressEvent is a small named-stage marker emitted by a service method
between sub-steps. It carries a stage identifier (used as the SSE event name),
a human-readable message, and an optional structured payload.

Pattern:
    def some_orchestration(arg, on_progress: ProgressCallback | None = None):
        _emit(on_progress, "loading", "Loading master resume")
        ...
        _emit(on_progress, "saving", "Writing .txt", {"path": str(path)})
        ...
        return result

HTTP / SSE transport (Phase B) wraps the callback into an asyncio queue so
each event becomes a streamed message. CLI / test callers can pass
`events.append` to collect events synchronously, or pass `None` to ignore.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class ProgressEvent:
    """A single named stage in a multi-step service operation.

    Attributes:
        stage:   Stable machine-readable identifier (e.g. "generating",
                 "exporting_pdf"). Use this as the SSE event name.
        message: Human-readable description for logs and UI.
        payload: Optional structured data (paths, token counts, scores, etc.).
    """
    stage: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)


ProgressCallback = Callable[[ProgressEvent], None]


def _emit(
    on_progress: Optional[ProgressCallback],
    stage: str,
    message: str,
    payload: Optional[dict[str, Any]] = None,
) -> None:
    """Emit a ProgressEvent if a callback is provided. No-op otherwise."""
    if on_progress is None:
        return
    on_progress(ProgressEvent(stage=stage, message=message, payload=payload or {}))
