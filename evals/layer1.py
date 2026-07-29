"""Layer 1 runner — executes eval cases through the consolidated dispatch.

Cases go through ``tools.consolidated._run`` — the exact path MCP clients
hit — so parameter coercion, missing-parameter errors, and action routing
are all under test, not just the target functions.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from evals.cases import CASES, EvalCase, cases_by_tags

_TRACEBACK_MARKER = "Traceback (most recent call last)"


@dataclass
class CaseResult:
    case_id: str
    ok: bool
    latency_ms: float
    detail: str = ""          # first failed check, or "" on pass
    response_excerpt: str = ""
    response_length: int = 0
    tags: tuple[str, ...] = ()
    invocation: str = ""   # "tool.action(inputs)" for verbose reports
    checks: str = ""       # human-readable expectations for verbose reports


@dataclass
class Layer1Report:
    results: list[CaseResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return sum(r.ok for r in self.results) / len(self.results) if self.results else 0.0

    @property
    def failed(self) -> list[CaseResult]:
        return [r for r in self.results if not r.ok]

    def latency_percentile(self, pct: float) -> float:
        if not self.results:
            return 0.0
        ordered = sorted(r.latency_ms for r in self.results)
        idx = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
        return ordered[idx]

    def smoke_pass_rate(self) -> float:
        smoke = [r for r in self.results if "smoke" in r.tags]
        return sum(r.ok for r in smoke) / len(smoke) if smoke else 1.0

    def release_blocked(self, threshold: float = 0.95) -> bool:
        """Doc rule: <95% pass rate on smoke tests blocks release."""
        return self.smoke_pass_rate() < threshold

    def to_dict(self) -> dict:
        return {
            "pass_rate": round(self.pass_rate, 4),
            "smoke_pass_rate": round(self.smoke_pass_rate(), 4),
            "release_blocked": self.release_blocked(),
            "latency_ms_p50": round(self.latency_percentile(50), 1),
            "latency_ms_p95": round(self.latency_percentile(95), 1),
            "cases": [
                {
                    "id": r.case_id, "ok": r.ok,
                    "latency_ms": round(r.latency_ms, 1),
                    "detail": r.detail,
                    "response_length": r.response_length,
                }
                for r in self.results
            ],
        }

    def to_text(self, verbose: bool = False) -> str:
        lines = ["═══ LAYER 1 EVAL REPORT ═══", ""]
        for r in self.results:
            mark = "✓" if r.ok else "✗"
            line = f"{mark} {r.case_id}  {r.latency_ms:7.1f} ms  ({r.response_length} chars)"
            if r.detail:
                line += f"  — {r.detail}"
            lines.append(line)
            if verbose:
                lines += [
                    f"    call:     {r.invocation}",
                    f"    expected: {r.checks}",
                    f"    tags:     {', '.join(r.tags) or '—'}",
                    f"    response: {r.response_excerpt!r}",
                    "",
                ]
        lines += [
            "",
            f"Pass rate: {self.pass_rate:.0%}  ({sum(r.ok for r in self.results)}"
            f"/{len(self.results)})",
            f"Smoke pass rate: {self.smoke_pass_rate():.0%}"
            + ("  ⚠ BELOW 95% — RELEASE BLOCKED" if self.release_blocked() else ""),
            f"Latency p50/p95: {self.latency_percentile(50):.1f} / "
            f"{self.latency_percentile(95):.1f} ms",
        ]
        return "\n".join(lines)


def check_response(case: EvalCase, response: str) -> str:
    """Return "" when *response* satisfies *case*, else the failed check."""
    if not isinstance(response, str):
        return f"non-string response: {type(response).__name__}"
    if _TRACEBACK_MARKER in response:
        return "response contains a traceback"
    if len(response) < case.min_length:
        return f"response shorter than {case.min_length} chars"
    lowered = response.lower()
    for needle in case.contains_all:
        if needle.lower() not in lowered:
            return f"missing expected text {needle!r}"
    if case.contains_any and not any(n.lower() in lowered for n in case.contains_any):
        return f"none of the expected texts present: {case.contains_any}"
    return ""


def describe_checks(case: EvalCase) -> str:
    parts = [f"≥{case.min_length} chars", "no traceback"]
    if case.contains_all:
        parts.append("contains " + " AND ".join(repr(n) for n in case.contains_all))
    if case.contains_any:
        parts.append("contains " + " OR ".join(repr(n) for n in case.contains_any))
    if case.error_ok:
        parts.append("(graceful error IS the expected outcome)")
    return "; ".join(parts)


def run_case(case: EvalCase, dispatch=None) -> CaseResult:
    if dispatch is None:
        from tools.consolidated import _run as dispatch  # noqa: PLC0415 — lazy: importing tools loads server config
    started = time.perf_counter()
    try:
        response = dispatch(case.tool, case.action, dict(case.inputs))
        detail = check_response(case, response)
    except Exception as exc:  # an unhandled exception is always a failure
        response = f"{type(exc).__name__}: {exc}"
        detail = f"raised {type(exc).__name__} — tools must fail gracefully"
    latency_ms = (time.perf_counter() - started) * 1000
    return CaseResult(
        case_id=case.id,
        ok=detail == "",
        latency_ms=latency_ms,
        detail=detail,
        response_excerpt=str(response)[:200],
        response_length=len(str(response)),
        tags=case.tags,
        invocation=f"{case.tool}.{case.action}({case.inputs or ''})",
        checks=describe_checks(case),
    )


def run_cases(
    cases: list[EvalCase] | None = None,
    include_tags: tuple[str, ...] | None = None,
    exclude_tags: tuple[str, ...] = ("network",),
    dispatch=None,
) -> Layer1Report:
    """Run *cases* (default: the full registry filtered by tags) in order."""
    if cases is None:
        cases = cases_by_tags(include_tags, exclude_tags)
    report = Layer1Report()
    for case in cases:
        report.results.append(run_case(case, dispatch=dispatch))
    return report


__all__ = ["CASES", "CaseResult", "Layer1Report", "check_response", "run_case", "run_cases"]
