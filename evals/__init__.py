"""Three-layer eval framework for the jobContext MCP system.

Layer 1 (`evals.layer1`)  — functional tool evals: every case invokes a
    consolidated-tool action through the same dispatch the MCP surface uses
    and asserts the response is correct, graceful on bad input, and fast.
Layer 2 (`evals.rubrics`) — output-quality rubrics (resume / cover letter),
    scored 1–5 per dimension with passing thresholds.
Layer 3 (`evals.judge` / `evals.runner`) — LLM-as-judge over a golden
    dataset with N-run variance analysis (mean, CoV, hallucination rate,
    verdict flip rate) and version-stamped baseline tracking.

CLI: ``python -m evals layer1 | judge | suite`` (see ``python -m evals -h``).
Methodology doc: jobContext_Eval_Framework (July 2026).
"""
