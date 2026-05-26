"""
WorkflowService: stub for the Phase C LangGraph resume workflow.

This module is intentionally minimal until Phase C lands. The placeholder
class establishes the import surface so transport and CLI code can be wired
up incrementally without circular-import churn later.

When Phase C is implemented this module will:
    - Import the StateGraph from workflows.langgraph.resume_graph
    - Expose `run_resume_workflow(company, role, jd, on_progress=None)` that
      drives the graph and emits a ProgressEvent at each node transition.
    - Expose `run_workflow_by_name(name, inputs, on_progress=None)` for the
      generic /workflows/{name} HTTP route.

See CHANGELOG.md "Issue #29" for the full specification.
"""

from typing import Any, Optional

from services.events import ProgressCallback, _emit


class WorkflowService:
    """Placeholder for the LangGraph workflow orchestrator (Phase C)."""

    @staticmethod
    def run(
        name: str,
        inputs: dict[str, Any],
        on_progress: Optional[ProgressCallback] = None,
    ) -> dict[str, Any]:
        """Run a named LangGraph workflow.

        Not yet implemented. Raises NotImplementedError. The signature is
        frozen so HTTP routes and tests can be scaffolded ahead of Phase C.

        Args:
            name:        Workflow identifier (e.g. "resume_tailoring").
            inputs:      Workflow input dict (company, role, jd, etc.).
            on_progress: Optional progress callback for node transitions.

        Returns:
            Workflow final state dict.

        Raises:
            NotImplementedError: Always, until Phase C lands.
        """
        _emit(on_progress, "not_implemented",
              f"Workflow '{name}' requested but LangGraph integration is pending (Phase C)",
              {"workflow": name})
        raise NotImplementedError(
            "WorkflowService is a Phase C stub. See CHANGELOG Issue #29."
        )
