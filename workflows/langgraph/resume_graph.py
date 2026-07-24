"""LangGraph resume tailoring workflow.

Graph shape:

    START → load_context → draft → review → (revise → review)* → output → END

Nodes:
    load_context  Pulls master resume, tone profile, customization strategy,
                  and interview context for the target company / role.
    draft         Calls tools.generate.generate_resume to produce the resume.
                  Works in two modes — direct OpenAI call (if API key set) or
                  context-package fallback (returns instructions for an
                  AI client to complete the resume).
    review        Static checks on the draft: word count, bullet markers,
                  required section headers. Sets needs_revision + feedback.
    revise        On retry, re-invokes generate_resume with the previous
                  feedback appended to the JD so the LLM can correct. In
                  keyless mode this currently just re-runs the same call
                  (the feedback is folded into the context package text);
                  Phase D will swap this for true persona-driven revision.
    output        Assembles the final ResumeGraphState for return.

Conditional edge after review:
    needs_revision and revisions < max_revisions → revise → review
    otherwise                                      → output

The graph is testable end-to-end without an OpenAI key because every node
falls back to deterministic disk/text operations when no key is present.
"""

from __future__ import annotations

import re
from typing import TypedDict

from langgraph.graph import StateGraph, END

from lib.io import _load_master_context
from tools.fitment import get_customization_strategy
from tools.generate import generate_resume, _infer_role_type
from tools.interviews import get_interview_context
from tools.tone import get_tone_profile


MAX_REVISIONS = 1


class ResumeGraphState(TypedDict, total=False):
    """State threaded through the resume workflow."""
    # Inputs
    company: str
    role: str
    job_description: str
    output_filename: str
    max_revisions: int

    # Loaded context
    master_context: str
    tone_profile: str
    strategy: str
    interview_context: str

    # Draft + review loop
    draft: str
    review_feedback: list[str]
    needs_revision: bool
    revisions: int

    # Final output
    success: bool
    pdf_exported: bool
    final_content: str


# ──────────────────────────────────────────────────────────────────────────────
# Node implementations
# ──────────────────────────────────────────────────────────────────────────────

def _node_load_context(state: ResumeGraphState) -> dict:
    company = state["company"]
    role = state["role"]
    return {
        "master_context": _load_master_context(),
        "tone_profile": get_tone_profile(),
        "strategy": get_customization_strategy(_infer_role_type(role)),
        "interview_context": get_interview_context(company=company, role=role),
        "revisions": state.get("revisions", 0),
        "review_feedback": state.get("review_feedback", []),
    }


def _node_draft(state: ResumeGraphState) -> dict:
    content = generate_resume(
        company=state["company"],
        role=state["role"],
        job_description=state["job_description"],
        output_filename=state.get("output_filename", ""),
    )
    return {"draft": content}


def _node_review(state: ResumeGraphState) -> dict:
    """Static heuristic review.

    Two paths produce different draft shapes:
      - Direct LLM path returns a short confirmation summary "✓ Resume
        generated for ..." with embedded save and export paths. We accept
        these without revision.
      - Context-package fallback returns a long instruction block starting
        with header guidance. We accept these too (an AI client will complete
        them downstream); a single revision pass can be triggered for
        testing by raising max_revisions above zero in the input state.
    """
    draft = state.get("draft", "")
    feedback: list[str] = []

    if not draft.strip():
        feedback.append("Draft is empty.")
    # When the LLM path runs, errors are surfaced inline with leading markers.
    if draft.startswith("✗"):
        feedback.append("LLM call returned an error marker.")
    # The provenance gate runs inside tools.generate (this graph's draft node
    # delegates to it); an unsourced-claims verdict rides back in the
    # confirmation string (lib.provenance.format_provenance_line). Treat it
    # as a review failure so the revise loop gets one shot at a clean
    # regeneration. The pattern must not match the PASS line ("0 unsourced")
    # or the check-skipped line, so it anchors on the FAIL shape "⚠ N unsourced".
    if re.search(r"Provenance: ⚠ \d+ unsourced", draft):
        feedback.append(
            "Provenance gate found unsourced numeric claims — regenerate "
            "using only facts from the master resume."
        )

    revisions = state.get("revisions", 0)
    max_rev = state.get("max_revisions", MAX_REVISIONS)
    needs_revision = bool(feedback) and revisions < max_rev

    return {
        "review_feedback": feedback,
        "needs_revision": needs_revision,
    }


def _node_revise(state: ResumeGraphState) -> dict:
    """Re-draft with feedback folded into the JD.

    The revision count is incremented BEFORE re-running draft so the review
    node sees the new count and can exit the loop deterministically.
    """
    feedback_block = "\n\nPREVIOUS REVIEW FEEDBACK (address these):\n" + "\n".join(
        f"- {item}" for item in state.get("review_feedback", [])
    )
    augmented_jd = state["job_description"] + feedback_block
    content = generate_resume(
        company=state["company"],
        role=state["role"],
        job_description=augmented_jd,
        output_filename=state.get("output_filename", ""),
    )
    return {
        "draft": content,
        "revisions": state.get("revisions", 0) + 1,
    }


def _node_output(state: ResumeGraphState) -> dict:
    draft = state.get("draft", "")
    success = draft.startswith("✓")
    pdf_exported = "PDF exported" in draft or "PDF saved" in draft
    return {
        "final_content": draft,
        "success": success,
        "pdf_exported": pdf_exported,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Conditional edge
# ──────────────────────────────────────────────────────────────────────────────

def _route_after_review(state: ResumeGraphState) -> str:
    return "revise" if state.get("needs_revision") else "output"


# ──────────────────────────────────────────────────────────────────────────────
# Graph factory
# ──────────────────────────────────────────────────────────────────────────────

def build_resume_graph():
    """Build and compile the resume tailoring StateGraph.

    Returns the compiled graph (`Pregel`-style runnable). Call `.invoke(state)`
    to run synchronously or `.stream(state)` for per-node yields.
    """
    g = StateGraph(ResumeGraphState)

    g.add_node("load_context", _node_load_context)
    g.add_node("draft", _node_draft)
    g.add_node("review", _node_review)
    g.add_node("revise", _node_revise)
    g.add_node("output", _node_output)

    g.set_entry_point("load_context")
    g.add_edge("load_context", "draft")
    g.add_edge("draft", "review")
    g.add_conditional_edges("review", _route_after_review, {
        "revise": "revise",
        "output": "output",
    })
    g.add_edge("revise", "review")
    g.add_edge("output", END)

    return g.compile()
