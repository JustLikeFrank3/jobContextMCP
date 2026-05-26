"""WorkflowService: drives LangGraph workflows and emits ProgressEvents.

Currently supports:
    "resume_tailoring" — workflows.langgraph.resume_graph.build_resume_graph()

The service uses the compiled graph's `.stream(state, stream_mode="updates")`
to receive one update per node transition, emits a ProgressEvent with the
node name as the stage, and returns the final state dict after the stream
ends.

This is the Phase C wiring; the Phase A2 stub raised NotImplementedError.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from services.events import ProgressCallback, _emit
from workflows.langgraph import build_resume_graph


# Registry of available named workflows. Lazy-built so importing this module
# does not eagerly construct LangGraph state machines.
_GRAPH_BUILDERS: dict[str, Callable[[], Any]] = {
    "resume_tailoring": build_resume_graph,
}


class UnknownWorkflowError(KeyError):
    """Raised when WorkflowService.run is given a workflow name it does not know."""


class WorkflowService:
    """Drive a named LangGraph workflow with progress event emission."""

    @staticmethod
    def list_workflows() -> list[str]:
        """Return the names of all registered workflows."""
        return sorted(_GRAPH_BUILDERS.keys())

    @staticmethod
    def run(
        name: str,
        inputs: dict[str, Any],
        on_progress: Optional[ProgressCallback] = None,
    ) -> dict[str, Any]:
        """Run a named LangGraph workflow to completion.

        Stages emitted:
            "starting"  — about to invoke the graph, payload includes inputs.
            <node_name> — one event per node transition with the partial state
                          delta-key list in payload.
            "complete"  — graph finished, payload includes the final state keys.

        Args:
            name:        Workflow identifier (e.g. "resume_tailoring").
            inputs:      Initial state dict matching the workflow's State schema.
            on_progress: Optional progress callback.

        Returns:
            The final accumulated state dict.

        Raises:
            UnknownWorkflowError: If `name` is not in the registry.
        """
        if name not in _GRAPH_BUILDERS:
            available = ", ".join(WorkflowService.list_workflows()) or "(none)"
            raise UnknownWorkflowError(
                f"Unknown workflow {name!r}. Available: {available}"
            )

        _emit(on_progress, "starting", f"Starting workflow '{name}'",
              {"workflow": name, "inputs": _safe_summary(inputs)})

        graph = _GRAPH_BUILDERS[name]()

        # stream_mode="updates" yields {node_name: {state_delta}} per step.
        # We accumulate deltas into final_state and emit one event per node.
        final_state: dict[str, Any] = dict(inputs)
        for update in graph.stream(inputs, stream_mode="updates"):
            for node_name, delta in update.items():
                if delta:
                    final_state.update(delta)
                _emit(on_progress, node_name, f"Node '{node_name}' completed",
                      {"delta_keys": sorted(delta.keys()) if delta else []})

        _emit(on_progress, "complete", f"Workflow '{name}' finished",
              {"workflow": name, "result_keys": sorted(final_state.keys())})

        return final_state


def _safe_summary(inputs: dict[str, Any]) -> dict[str, Any]:
    """Truncate long string values in the inputs payload for event display."""
    out: dict[str, Any] = {}
    for k, v in inputs.items():
        if isinstance(v, str) and len(v) > 120:
            out[k] = v[:117] + "..."
        else:
            out[k] = v
    return out
