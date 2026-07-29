"""Layer 1 eval case definitions.

Each case invokes one consolidated-tool action and asserts on the response
string. Cases follow the schema from the eval framework doc (id, tool,
action, inputs, expectations, tags); expectations are substring/length
checks because every tool returns a formatted string, never a dict.

Cases run in list order so read-after-write cases may rely on an earlier
write in the same run (``TC-005`` reads what ``TC-004`` wrote).

Tags:
    smoke            — run on every deploy; <95% pass blocks release
    read-only        — safe against any workspace, including production
    write            — mutates the workspace; run only in an isolated
                       test-user namespace, never against live data
    error-handling   — the *expected* outcome is a graceful error string
    semantic         — needs an embedding index + key to be meaningful
    network          — reaches the open web; excluded by default
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvalCase:
    """One Layer 1 test case."""

    id: str
    tool: str
    action: str
    inputs: dict = field(default_factory=dict)
    contains_all: tuple[str, ...] = ()
    contains_any: tuple[str, ...] = ()
    min_length: int = 1
    error_ok: bool = False  # a graceful error string is the expected outcome
    tags: tuple[str, ...] = ()
    notes: str = ""


# Company/name used by write cases so they are recognizable and scrubbable.
TEST_COMPANY = "TestCo"

CASES: tuple[EvalCase, ...] = (
    # ── doc cases TC-001 … TC-008 ────────────────────────────────────────────
    EvalCase(
        id="TC-001", tool="workspace", action="check",
        contains_all=("WORKSPACE STATUS",),
        tags=("smoke", "read-only"),
        notes="Live expectation: '✓ Master resume' and '✓ config.json' present.",
    ),
    EvalCase(
        id="TC-002", tool="materials", action="read_master_resume",
        min_length=10,
        tags=("smoke", "read-only"),
        notes="Live expectation: >500 chars and contains the candidate name.",
    ),
    EvalCase(
        id="TC-003", tool="materials", action="search",
        inputs={"query": "Python distributed systems"},
        contains_any=("Results for", "OpenAI API key", "reindex_materials"),
        tags=("semantic", "read-only"),
        notes="Without an index/key the graceful degradation message passes; "
              "live runs should return ≥1 relevant result.",
    ),
    EvalCase(
        id="TC-004", tool="interviews", action="log",
        inputs={
            "company": TEST_COMPANY, "role": "SWE",
            "interview_date": "2026-07-01", "interview_type": "recruiter_screen",
        },
        contains_all=(TEST_COMPANY,),
        tags=("write", "idempotency"),
    ),
    EvalCase(
        id="TC-005", tool="interviews", action="list",
        inputs={"company": TEST_COMPANY},
        contains_all=(TEST_COMPANY,),
        tags=("write", "read-after-write"),
        notes="Reads the debrief TC-004 wrote.",
    ),
    EvalCase(
        id="TC-006", tool="insights", action="rejection_log",
        inputs={"company": TEST_COMPANY, "role": "SWE", "stage": "phone screen"},
        contains_all=(TEST_COMPANY,),
        tags=("write",),
    ),
    EvalCase(
        id="TC-007", tool="insights", action="rejections",
        inputs={"include_pattern_analysis": True},
        min_length=5,
        tags=("analytics", "read-only"),
        notes="Funnel/pattern analysis must run without raising.",
    ),
    EvalCase(
        id="TC-008", tool="workspace", action="setup",
        inputs={"name": "Test User"},
        contains_all=("missing required parameter",),
        error_ok=True,
        tags=("error-handling",),
        notes="Missing email/phone/etc. must produce a readable error, not a crash.",
    ),
    # ── per-domain smoke coverage (all 11 tools) ─────────────────────────────
    EvalCase(
        id="TC-009", tool="applications", action="status",
        min_length=5, tags=("smoke", "read-only"),
    ),
    EvalCase(
        id="TC-010", tool="applications", action="get_queue",
        min_length=3, tags=("smoke", "read-only"),
    ),
    EvalCase(
        id="TC-011", tool="people", action="log",
        inputs={
            "name": "Eval Test Person", "relationship": "recruiter",
            "company": TEST_COMPANY, "context": "Layer 1 eval write case",
        },
        contains_all=("Eval Test Person",),
        tags=("write",),
    ),
    EvalCase(
        id="TC-012", tool="people", action="list",
        inputs={"company": TEST_COMPANY},
        contains_all=("Eval Test Person",),
        tags=("write", "read-after-write"),
        notes="Lookup by company returns the contact TC-011 wrote.",
    ),
    EvalCase(
        id="TC-013", tool="stories", action="tone_profile",
        min_length=3, tags=("smoke", "read-only"),
    ),
    EvalCase(
        id="TC-014", tool="wellbeing", action="log",
        min_length=3, tags=("smoke", "read-only"),
        notes="Must not error on empty history.",
    ),
    EvalCase(
        id="TC-015", tool="wellbeing", action="checkin",
        inputs={"mood": "good", "energy": 7, "notes": "Layer 1 eval write case"},
        min_length=3, tags=("write",),
    ),
    EvalCase(
        id="TC-016", tool="brand", action="posts",
        min_length=3, tags=("smoke", "read-only"),
    ),
    EvalCase(
        id="TC-017", tool="insights", action="daily_digest",
        contains_all=("PIPELINE",), tags=("smoke", "read-only"),
    ),
    EvalCase(
        id="TC-018", tool="documents", action="customization_strategy",
        inputs={"role_type": "ai_innovation"},
        min_length=20, tags=("smoke", "read-only"),
    ),
    EvalCase(
        id="TC-019", tool="documents", action="save_resume",
        inputs={
            "filename": "TestCo_SWE_eval.txt",
            "content": "EVAL TEST RESUME BODY — safe to delete.",
        },
        contains_all=("TestCo_SWE_eval",),
        tags=("write",),
    ),
    EvalCase(
        id="TC-020", tool="materials", action="read_resume",
        inputs={"filename": "TestCo_SWE_eval.txt"},
        contains_all=("EVAL TEST RESUME BODY",),
        tags=("write", "read-after-write"),
        notes="Reads the file TC-019 saved.",
    ),
    EvalCase(
        id="TC-021", tool="interviews", action="upcoming",
        min_length=3, tags=("smoke", "read-only"),
    ),
    EvalCase(
        id="TC-022", tool="job_search", action="web",
        inputs={"query": "software engineer AI", "location": "remote"},
        min_length=5, tags=("network", "read-only"),
        notes="Open-web search; excluded from default runs.",
    ),
)


def cases_by_tags(
    include: tuple[str, ...] | None = None,
    exclude: tuple[str, ...] = ("network",),
) -> list[EvalCase]:
    """Select cases: keep those matching any *include* tag (all when None),
    then drop those matching any *exclude* tag."""
    picked = [
        c for c in CASES
        if include is None or any(t in c.tags for t in include)
    ]
    return [c for c in picked if not any(t in c.tags for t in exclude)]
