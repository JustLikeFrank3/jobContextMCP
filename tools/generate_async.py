"""Submit-and-poll document generation for short-timeout agents.

In-browser agents cap a WebMCP tool call at roughly 25 seconds (measured
2026-08-30: ChatGPT desktop aborts generation calls at 23–26s), while
resume/cover-letter generation legitimately holds a request open for
60–120s — the LLM call, the truth gate, and up to one correction pass. No
synchronous path fits that budget, so these tools split the call in two:

- ``submit_resume`` / ``submit_cover_letter`` enqueue the SAME control-plane
  work kind the synchronous path records (the dispatcher executes it with
  partition context taken from the row — lib/work.py) and return the work
  item id immediately.
- ``generation_status`` polls the durable row and, once the run succeeds,
  returns the same response text the synchronous tool returns — truth-gate
  attestation and control-plane audit line included.

The synchronous ``generate_resume`` / ``generate_cover_letter`` stay the
right call for clients without a tool timeout (Claude, Cursor, the CLI):
they answer in one round-trip instead of a poll loop.
"""
from __future__ import annotations

from lib import work
from tools import generate_work

_POLL_HINT = 'documents(action="generation_status", work_id={id})'


def _submit(kind: str, inputs: dict) -> str:
    item_id = work.enqueue(kind, inputs, origin="chat_async")
    return (
        f"⧗ Generation queued as work item #{item_id} ({kind}).\n"
        f"Poll {_POLL_HINT.format(id=item_id)} every ~15 seconds; once the run\n"
        "succeeds it returns the finished document with its truth-gate\n"
        "attestation. Typical runs take 60–120 seconds."
    )


def submit_resume(
    company: str,
    role: str,
    job_description: str,
    output_filename: str = "",
    template: str = "",
    style: str = "navy",
) -> str:
    """Queue background resume generation; returns a work item id immediately.

    Same generator, truth gate, and saved outputs as generate_resume — only
    the delivery differs: poll generation_status for the finished document.
    Use this instead of generate_resume when tool calls are cut off by a
    client-side timeout (in-browser agents allow ~25s; generation takes
    60–120s).
    """
    return _submit(generate_work.KIND_RESUME, {
        "company": company,
        "role": role,
        "job_description": job_description,
        "output_filename": output_filename,
        "template": template,
        "style": style,
    })


def submit_cover_letter(
    company: str,
    role: str,
    job_description: str,
    output_filename: str = "",
    export_pipeline: str = "html",
    role_title: str = "Full Stack Software Engineer",
    cl_template: str = "",
    cl_style: str = "navy",
) -> str:
    """Queue background cover-letter generation; returns a work item id immediately.

    Same generator, truth gate, and saved outputs as generate_cover_letter —
    only the delivery differs: poll generation_status for the finished
    document. Use this instead of generate_cover_letter when tool calls are
    cut off by a client-side timeout (in-browser agents allow ~25s;
    generation takes 60–120s).
    """
    return _submit(generate_work.KIND_COVER_LETTER, {
        "company": company,
        "role": role,
        "job_description": job_description,
        "output_filename": output_filename,
        "export_pipeline": export_pipeline,
        "role_title": role_title,
        "cl_template": cl_template,
        "cl_style": cl_style,
    })


def generation_status(work_id: int) -> str:
    """Poll a queued generation; returns the finished document once it succeeds.

    Read-only. Accepts the work item id that submit_resume /
    submit_cover_letter returned. While the run is queued or running, answers
    with its state; on success, returns the generator's full response —
    truth-gate attestation and control-plane audit line included — and on
    failure, the recorded error.
    """
    row = work.get_item(int(work_id))
    if not row:
        return f"✗ No work item #{work_id} found in this workspace."
    kind = str(row.get("kind") or "")
    if not kind.startswith("generate."):
        return (
            f"✗ Work item #{row['id']} is a {kind or 'non-generation'} task, "
            "not a document generation."
        )
    status = row.get("status")
    if status in ("queued", "running"):
        return (
            f"⧗ Work item #{row['id']} ({kind}) is {status} "
            f"(attempt {row.get('attempt', 0)}/{row.get('max_attempts', 1)}, "
            f"created {row.get('created_at')} UTC). Poll again in ~15 seconds."
        )
    if status == "succeeded":
        artifacts = row.get("artifacts") or {}
        result = str(artifacts.get("result") or "")
        if not result:
            return f"✗ Work item #{row['id']} succeeded but recorded no result."
        # Handled failures come back as ✗-prefixed strings with status
        # "succeeded" (the generator reported, not raised) — same rule as the
        # synchronous wrapper: never dress an error up as an attested success.
        if result.lstrip().startswith("✗"):
            return result
        return (
            f"{result}\n"
            f"  control plane: work item #{row['id']} ({kind}) — durable audit row"
        )
    if status == "cancelled":
        return f"✗ Work item #{row['id']} ({kind}) was cancelled."
    return (
        f"✗ Generation failed (work item #{row['id']}): "
        f"{row.get('error') or 'no error recorded'}"
    )
