"""
LangGraph-powered multi-stage resume generation pipeline — v2.0

generate_resume_agent(company, role, job_description) → str

Why this is better than a single LLM call
─────────────────────────────────────────
The existing generate_resume() fires one big prompt and hopes the model
holds all the context (JD analysis, experience selection, format spec,
tone, and actual writing) in a single pass. That works reasonably well,
but the model frequently optimizes for the wrong things — it pattern-matches
to what a "resume" looks like rather than what THIS role needs.

LangGraph breaks that into explicit reasoning stages:
  1. load_context — loads tone profile and STAR stories from disk (no LLM)
  2. retrieve   — RAG search: finds the most JD-relevant resume chunks (no LLM)
  3. draft      — writes the resume with retrieved context already in-scope
  4. review     — separate call checks format compliance and content quality
  5. revise     — targeted fixes if the reviewer found issues (up to 2 passes)
  6. finalize   — passthrough node that surfaces the approved draft

Token efficiency
─────────────────────────────────────────
The original design loaded the full enriched master context (~20k tokens) plus
personal_context stories (~15k tokens) into every LLM prompt, blowing past the
30k TPM limit in both assess and draft nodes.

The RAG approach: embed the JD, cosine-search the pre-built index, and pull
only the top-N relevant chunks (~1,600 tokens). Draft gets ~6,500 total input
tokens instead of 49k. No LLM call needed to decide what's relevant.

LangGraph concepts illustrated here
─────────────────────────────────────────
  StateGraph   — the graph itself, parameterized by your state type
  TypedDict    — the state: a typed bag of data flowing through every node
  Node         — a plain Python function: (state) -> dict
                 return ONLY the fields you changed; LangGraph merges them
  Edge         — direct connection between nodes (add_edge)
  Conditional  — a Python function returning the next node's name by
  edge           string; this is how branching works — no LLM decides
  compile()    — seals the graph into a runnable CompiledGraph
  invoke()     — runs the graph from the entry point, returns final state

Graph structure:

    START → load_context → retrieve → draft → review ──→ finalize → END
                                                   │           ↑
                                                   └──→ revise ┘   (if issues found, max 2x)
"""

from __future__ import annotations

import textwrap
from typing import TypedDict

from langgraph.graph import StateGraph, END

from lib import config
from lib.io import _load_master_context, _read
from tools.tone import get_tone_profile
from tools.star import get_star_story_context
from tools.generate import _infer_role_type, _RESUME_FORMAT_SPEC, _RESUME_SYSTEM


# ── STATE ──────────────────────────────────────────────────────────────────────
# The state is the central data structure of a LangGraph pipeline.
# Every node receives a copy of the full state and returns a dict with
# ONLY the fields it updated. LangGraph merges those updates in.
# Think of it as the shared whiteboard all nodes read from and write to.

class ResumeAgentState(TypedDict):
    company: str
    role: str
    job_description: str
    retrieved_context: str      # set by retrieve_node: RAG hits relevant to this JD
    tone_profile: str           # set by load_context_node
    star_stories: str           # set by load_context_node: relevant STAR stories
    draft: str                  # set by draft_node, updated by revise_node
    review_notes: str           # set by review_node: issues or "APPROVED"
    revision_count: int         # incremented by revise_node, guards the loop
    approved: bool              # set True by review_node when draft is clean


# ── NODES ──────────────────────────────────────────────────────────────────────
# Each node is just a Python function: (state: dict) -> dict
# You return a partial dict — only the keys you want to update.
# LangGraph merges your return value into the running state.

def load_context_node(state: ResumeAgentState) -> dict:
    """Load tone profile and STAR stories from disk. No LLM call.

    Keeps I/O out of the downstream nodes. retrieve_node handles the
    RAG search separately so its token cost is visible and isolated.
    """
    role_type = _infer_role_type(state["role"])
    star_1 = get_star_story_context("cloud_migration", state["company"], role_type)
    star_2 = get_star_story_context("ai_innovation", state["company"], role_type)
    return {
        "tone_profile": get_tone_profile(),
        "star_stories": (star_1 + "\n\n" + star_2).strip(),
        "retrieved_context": "",
        "revision_count": 0,
        "approved": False,
        "draft": "",
        "review_notes": "",
    }


def retrieve_node(state: ResumeAgentState) -> dict:
    """Retrieve the most JD-relevant resume chunks from the pre-built RAG index.

    This replaces the assess_node LLM call with a simple embedding lookup —
    cosine similarity decides what's relevant, not another GPT round-trip.

    Two queries are run and deduplicated:
      1. The JD text (truncated) — pulls the resume sections that best match
         the role's requirements.
      2. An AI/agent-focused query — specifically surfaces jobContextMCP's
         RAG pipeline, MCP architecture, and LLM production work, which
         cosine similarity may underweight if the JD uses different vocabulary.

    Token cost: one embedding call (~$0.00003) instead of an LLM call.
    """
    from rag import search, format_results

    # Query 1: JD-driven — surfaces what the role actually asks for
    jd_query = state["job_description"][:800]
    hits_jd = search(jd_query, n_results=5)

    # Query 2: AI/agent-focused — ensures jobContextMCP content is represented
    ai_query = (
        "RAG pipeline LLM production agentic AI MCP agent architecture "
        "memory context management embeddings retrieval OpenAI"
    )
    hits_ai = search(ai_query, n_results=4)

    # Deduplicate by chunk text, JD hits take priority (inserted first)
    seen: dict[str, dict] = {}
    for hit in hits_jd + hits_ai:
        if hit["text"] not in seen:
            seen[hit["text"]] = hit

    return {"retrieved_context": format_results(list(seen.values()), "RETRIEVED EXPERIENCE")}


def draft_node(state: ResumeAgentState) -> dict:
    """Write the resume using the master resume as ground truth.

    retrieved_context tells the model which sections are most relevant to
    this JD (emphasis guidance). The master resume is the strict source of
    truth for all facts, dates, metrics, and company names — the model must
    not invent anything not present there.
    """
    prompt = "\n\n".join(filter(None, [
        f"TARGET COMPANY: {state['company']}",
        f"TARGET ROLE: {state['role']}",
        f"JOB DESCRIPTION:\n{state['job_description']}",
        f"RETRIEVED EXPERIENCE (RAG hits — use to decide what to emphasize, NOT as the source of facts):\n{state['retrieved_context']}",
        f"MASTER RESUME (strict source of truth — use ONLY facts, dates, metrics, and names from here; do not invent anything):\n{_read(config.MASTER_RESUME)}",
        f"STAR STORIES (draw specific metrics and quotes from these):\n{state['star_stories']}" if state.get("star_stories") else "",
        f"TONE PROFILE (write in this voice):\n{state['tone_profile']}",
        _RESUME_FORMAT_SPEC,
        "Now write the resume. Output the raw .txt content only — no preamble, no commentary.",
    ]))

    response = _get_client().chat.completions.create(
        model=_model(),
        messages=[
            {"role": "system", "content": _RESUME_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
        max_tokens=2000,
    )

    return {"draft": (response.choices[0].message.content or "").strip()}


def review_node(state: ResumeAgentState) -> dict:
    """Check the draft for format violations and content weaknesses.

    Returns "APPROVED" if acceptable, or a list of specific actionable issues.
    The conditional edge after this node routes to 'finalize' or 'revise'
    based purely on whether review_notes == "APPROVED" — no LLM routing.
    """
    prompt = textwrap.dedent(f"""\
        You are a strict resume format and content reviewer. Check this draft.

        FORMAT CHECKS (auto-fail on any violation):
        1. Starts with <NAME> tag and candidate name on its own line?
        2. All section headers ALL CAPS?
        3. Bullets use • (U+2022), not - or *?
        4. Job headers: "Title | Company, Location | Month YYYY - Month YYYY"?
        5. Project headers: "Name | Tech Stack | Year"?
        6. Total length roughly 750-900 words?

        CONTENT CHECKS:
        7. Most relevant projects to this role included?
        8. Every bullet has at least one specific metric OR a named artifact/technology/outcome? (Do NOT flag missing metrics if the source material has none — qualitative specificity is acceptable.)
        9. Free of em dashes, "I'm excited", AI-sounding openers?
        10. Addresses the core requirements of the target role?

        TARGET ROLE: {state['role']} at {state['company']}

        DRAFT:
        {state['draft']}

        If the draft is acceptable, respond with exactly: APPROVED
        If there are issues, list them one per line. Be specific and actionable.
        Do NOT rewrite anything — only describe what needs to change.
    """)

    response = _get_client().chat.completions.create(
        model=_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=400,
    )

    feedback = (response.choices[0].message.content or "").strip()
    approved = feedback.strip().upper() == "APPROVED"

    return {
        "review_notes": feedback,
        "approved": approved,
    }


def revise_node(state: ResumeAgentState) -> dict:
    """Apply reviewer feedback to the draft. Increments revision_count.

    This node only runs when review_node found issues AND revision_count < 2.
    The conditional edge handles that logic — this node just executes the fix.
    """
    prompt = textwrap.dedent(f"""\
        You are revising a resume draft based on specific reviewer feedback.
        Apply ONLY the changes described in the feedback. Do not make unrelated changes.
        Output the complete revised resume in .txt format — no preamble, no commentary.

        MASTER RESUME (strict source of truth — do NOT invent any metric, percentage, number, date, or named artifact not present in the current draft or this source. If a bullet needs strengthening, use named technologies, concrete actions, or qualitative outcomes instead of fabricated numbers):
        {_read(config.MASTER_RESUME)}

        REVIEWER FEEDBACK:
        {state['review_notes']}

        CURRENT DRAFT:
        {state['draft']}

        FORMAT SPEC (keep compliant):
        {_RESUME_FORMAT_SPEC}
    """)

    response = _get_client().chat.completions.create(
        model=_model(),
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a resume editor. Your single most important rule: "
                    "DO NOT invent any number, percentage, count, or metric that is not "
                    "explicitly present in the MASTER RESUME provided in the user message. "
                    "If the reviewer asked for a metric and none exists in the source, "
                    "use a named technology, concrete action, or qualitative outcome instead. "
                    "Fabricating metrics is a disqualifying error."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=2000,
    )

    return {
        "draft": (response.choices[0].message.content or "").strip(),
        "revision_count": state["revision_count"] + 1,
    }


# ── ROUTING ────────────────────────────────────────────────────────────────────
# This is the conditional edge function. It's a plain Python function that
# receives the current state and returns the NAME of the next node as a string.
# No LLM involved — deterministic routing based on state values.

def route_after_review(state: ResumeAgentState) -> str:
    """Route to 'revise' if issues were found and we haven't hit the limit.
    Route to 'finalize' if approved or we've already revised twice.
    """
    if state["approved"] or state["revision_count"] >= 2:
        return "finalize"
    return "revise"


# ── GRAPH ASSEMBLY ─────────────────────────────────────────────────────────────

def _build_graph():
    """Assemble and compile the resume generation graph.

    You build LangGraph graphs by:
      1. Creating a StateGraph(StateType)
      2. Adding nodes with add_node(name, function)
      3. Adding edges with add_edge(from, to)
      4. Adding conditional edges with add_conditional_edges(from, router_fn, mapping)
      5. Setting the entry point with set_entry_point(node_name)
      6. Calling compile() to get the runnable app
    """
    graph = StateGraph(ResumeAgentState)

    # Register nodes — name + function
    graph.add_node("load_context", load_context_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("draft", draft_node)
    graph.add_node("review", review_node)
    graph.add_node("revise", revise_node)
    graph.add_node("finalize", lambda state: {})  # passthrough — draft is already final

    # Set the entry point
    graph.set_entry_point("load_context")

    # Direct edges — always run the next node
    graph.add_edge("load_context", "retrieve")
    graph.add_edge("retrieve", "draft")
    graph.add_edge("draft", "review")

    # Conditional edge after review:
    #   route_after_review(state) returns "revise" or "finalize"
    #   the mapping dict translates that string to the actual node name
    graph.add_conditional_edges(
        "review",
        route_after_review,
        {
            "revise": "revise",
            "finalize": "finalize",
        },
    )

    # Revise loops back to review for a second pass
    graph.add_edge("revise", "review")
    graph.add_edge("finalize", END)

    return graph.compile()


# ── PUBLIC API ─────────────────────────────────────────────────────────────────

def generate_resume_agent(company: str, role: str, job_description: str) -> str:
    """Generate a targeted resume using a multi-stage LangGraph pipeline.

    Runs a 4-node stateful graph:
      assess → draft → review → [revise →] finalize

    Produces higher-quality output than a single LLM call because each stage
    has a narrow mandate: analyze, write, critique, fix. State flows explicitly
    between stages so no context is lost and each node's job is clear.

    Falls back to generate_resume() context-packing if OpenAI is not configured.
    """
    if not _get_client():
        from tools.generate import generate_resume
        return generate_resume(company, role, job_description)

    app = _build_graph()

    initial_state: ResumeAgentState = {
        "company": company,
        "role": role,
        "job_description": job_description,
        "retrieved_context": "",
        "tone_profile": "",
        "star_stories": "",
        "draft": "",
        "review_notes": "",
        "revision_count": 0,
        "approved": False,
    }

    final_state = app.invoke(initial_state)

    revisions = final_state["revision_count"]
    review = final_state["review_notes"]
    review_summary = review[:80] + "..." if len(review) > 80 else review

    header = "\n".join([
        f"LangGraph pipeline complete — {revisions} revision(s)",
        f"  load_context → retrieve (RAG) → draft → {'revise → ' * revisions}finalize",
        f"  Final review: {review_summary}",
        "",
    ])

    return header + final_state["draft"]


# ── HELPERS ────────────────────────────────────────────────────────────────────

def _personal_context_index() -> str:
    """Return a compact title+tags-only index of personal stories.

    The full personal_context blob (~6k tokens for 44 stories) is too large
    to include in the assess_node prompt given the 30k TPM limit. This index
    gives the strategist enough signal to decide what to surface or suppress
    without the full story text. draft_node gets the full content.
    """
    from lib.io import _load_json
    data = _load_json(config.PERSONAL_CONTEXT_FILE, {"stories": []})
    stories = data.get("stories", [])
    if not stories:
        return ""
    lines = [f"PERSONAL CONTEXT INDEX ({len(stories)} stories — titles and tags for strategy only):"]
    for s in stories:
        tags_str = ", ".join(s.get("tags", []))
        lines.append(f"  #{s.get('id', '?')} {s.get('title', '')[:80]} [{tags_str}]")
    return "\n".join(lines)


def _get_client():
    """Return configured OpenAI client using whichever provider is set (openai or ollama)."""
    try:
        from lib.config import get_llm_client
        client, _ = get_llm_client()
        return client
    except Exception:
        return None


def _model() -> str:
    try:
        from lib.config import get_llm_client
        _, model = get_llm_client()
        return model
    except Exception:
        return config._cfg.get("openai_model", "gpt-4o-mini")


def register(mcp) -> None:
    mcp.tool()(generate_resume_agent)
