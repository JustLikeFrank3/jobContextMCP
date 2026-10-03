"""Conference-badge API — the cloud side of the GitHub Universe badge app.

  GET  /api/badge/ping            — connectivity + identity check (firmware setup)
  GET  /api/badge/search?q=       — company/role search over the pipeline
  POST /api/badge/materials       — enqueue a resume / cover letter generation
  GET  /api/badge/work/{id}       — poll that job

Design constraints come from the hardware (Pimoroni Tufty 2350: RP2350B,
320x240, MicroPython).  Two of them shape every response here:

  * Payloads stay small and pre-truncated.  The badge renders ~34 characters
    per line and parses JSON with `json.loads` into 520KB of SRAM, so strings
    are cut to display width on the server rather than shipping a paragraph
    the firmware would throw away.
  * Nothing long-running answers inline.  Generating a resume is a multi-second
    LLM call; a battery-powered device on conference WiFi cannot hold that
    socket open.  Generation goes through the control plane (lib/work.py) and
    the badge polls a work id — which is also the P1 in docs/control-plane.md.

Auth is `require_badge_client`, the one dependency that accepts a badge-scoped
key.  Scope itself is enforced upstream in the partition middleware; see
lib/api_keys.py for why a badge token is treated as semi-public.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import hashlib
import json
import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from lib import work
from transport.http.auth import require_badge_client
from transport.http.security import User

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/badge", tags=["badge"])

# Display widths, in characters, at the badge's default font. Truncating here
# keeps the firmware free of layout math and the payload small.
_COMPANY_CHARS = 28
_ROLE_CHARS = 34
# The badge word-wraps failure text over a few lines, so this can be longer
# than a list row.
_DETAIL_CHARS = 80
_MAX_RESULTS = 12


def _clip(value: object, width: int) -> str:
    """Trim to *width* display characters, with an ellipsis when cut."""
    text = " ".join(str(value or "").split())
    if len(text) <= width:
        return text
    return text[: width - 1].rstrip() + "…"


# ── search ─────────────────────────────────────────────────────────────────────

@router.get("/ping")
async def badge_ping(user: Annotated[User, Depends(require_badge_client)]) -> dict:
    """Cheapest possible round trip — the firmware's WiFi/token smoke test."""
    return {"ok": True, "scope": user.scope}


@router.get("/search")
async def badge_search(
    user: Annotated[User, Depends(require_badge_client)],  # noqa: ARG001
    q: str = "",
    limit: int = 6,
) -> dict:
    """Search the caller's pipeline by company or role.

    Falls back to the employer directory for companies that are known but not
    yet queued, so typing a company you just met at a booth still lands
    something instead of an empty screen.
    """
    from lib.db import get_connection

    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="Type something to search for.")
    limit = max(1, min(limit, _MAX_RESULTS))
    like = f"%{query}%"

    results: list[dict] = []
    seen: set[str] = set()
    with get_connection() as con:
        rows = con.execute(
            "SELECT id, company, role, status, fitment_score FROM job_queue "
            "WHERE company LIKE ? OR role LIKE ? "
            "ORDER BY id DESC LIMIT ?",
            (like, like, limit),
        ).fetchall()
        for r in rows:
            seen.add((r["company"] or "").lower())
            results.append(
                {
                    "job_id": r["id"],
                    "company": _clip(r["company"], _COMPANY_CHARS),
                    "role": _clip(r["role"], _ROLE_CHARS),
                    "status": _clip(r["status"] or "pending", 12),
                    # fitment_score is free text ("7/10", "7.5/10 — strong");
                    # the badge only has room for the leading token.
                    "score": _clip((r["fitment_score"] or "").split()[0] if r["fitment_score"] else "", 8),
                }
            )

        if len(results) < limit:
            try:
                extra = con.execute(
                    "SELECT canonical_name, city, state FROM employer_directory "
                    "WHERE canonical_name LIKE ? ORDER BY canonical_name LIMIT ?",
                    (like, limit - len(results)),
                ).fetchall()
            except Exception:  # noqa: BLE001 — directory is optional, search is not
                extra = []
            for r in extra:
                if (r["canonical_name"] or "").lower() in seen:
                    continue
                where = ", ".join(x for x in (r["city"], r["state"]) if x)
                results.append(
                    {
                        "job_id": 0,  # not queued — no material generation target
                        "company": _clip(r["canonical_name"], _COMPANY_CHARS),
                        "role": _clip(where or "known employer", _ROLE_CHARS),
                        "status": "directory",
                        "score": "",
                    }
                )

    return {"query": _clip(query, _ROLE_CHARS), "count": len(results), "results": results}


# ── job search (new openings, not the pipeline) ────────────────────────────────
#
# /search above only looks inside the caller's job_queue. These find openings
# that aren't there yet — Google Jobs through the server's SerpAPI key — and
# queue one so the materials flow can run against it.
#
# Every uncached search is a paid call on a key shared by all tenants, so a
# repeat query within the hour reuses the stored results and each tenant gets
# a daily cap. Results live in job_discovery's job_search_results table (same
# expiry, same lookup), which is what lets queue_result add one by number with
# its full description — never a title-only stub.

_JOB_SEARCHES_PER_DAY = 25
_MAX_QUERY_CHARS = 120


class JobQueueRequest(BaseModel):
    search_id: str
    number: int


def _web_job(job: dict) -> "dict | None":
    """Normalise one Google Jobs result to job_discovery's stored shape."""
    company = " ".join(str(job.get("company_name") or "").split())
    role = " ".join(str(job.get("title") or "").split())
    if not company or not role:
        return None
    source = next((o["link"] for o in job.get("apply_options") or [] if o.get("link")), "")
    return {
        "company": company[:120],
        "role": role[:240],
        "location": " ".join(str(job.get("location") or "").split())[:240],
        "source": source or str(job.get("via") or ""),
        "jd": str(job.get("description") or ""),
        "provider": "web",
    }


def _search_id(query: str) -> str:
    return "badge-web-" + hashlib.sha256(query.casefold().encode()).hexdigest()[:20]


def _use_search_quota(con) -> bool:
    """Count one paid search against today's cap; False once it is spent."""
    con.execute(
        "CREATE TABLE IF NOT EXISTS badge_usage (day TEXT PRIMARY KEY, web_searches INTEGER NOT NULL)"
    )
    day = _dt.date.today().isoformat()
    row = con.execute("SELECT web_searches FROM badge_usage WHERE day = ?", (day,)).fetchone()
    used = row["web_searches"] if row else 0
    if used >= _JOB_SEARCHES_PER_DAY:
        return False
    con.execute(
        "INSERT INTO badge_usage (day, web_searches) VALUES (?, 1) "
        "ON CONFLICT(day) DO UPDATE SET web_searches = web_searches + 1",
        (day,),
    )
    return True


def _job_rows(search_id: str, jobs: list[dict], limit: int) -> dict:
    return {
        "search_id": search_id,
        "count": min(len(jobs), limit),
        "results": [
            {
                "number": n,
                "company": _clip(j["company"], _COMPANY_CHARS),
                "role": _clip(j["role"], _ROLE_CHARS),
                "location": _clip(j["location"], _ROLE_CHARS),
            }
            for n, j in enumerate(jobs[:limit], 1)
        ],
    }


@router.get("/jobs")
async def badge_jobs(
    user: Annotated[User, Depends(require_badge_client)],  # noqa: ARG001
    q: str = "",
    limit: int = 6,
) -> dict:
    """Find open roles on the web for *q* (a company, a role, or both)."""
    from tools.job_discovery import TTL, _db
    from tools.job_scraper import JobSearchError, _serpapi_jobs

    query = " ".join(q.split())
    if not query or len(query) > _MAX_QUERY_CHARS:
        raise HTTPException(status_code=422, detail="Type a company or role to search for.")
    limit = max(1, min(limit, _MAX_RESULTS))
    search_id = _search_id(query)

    with _db() as con:
        row = con.execute(
            "SELECT results FROM job_search_results WHERE id = ? AND expires >= ?",
            (search_id, time.time()),
        ).fetchone()
        if row is not None:
            return _job_rows(search_id, json.loads(row["results"]), limit)
        if not _use_search_quota(con):
            raise HTTPException(
                status_code=429,
                detail=f"Daily job search limit ({_JOB_SEARCHES_PER_DAY}) reached - try tomorrow.",
            )

    # The HTTP call needs no partition, so a worker thread is safe here; the
    # result is stored back on this request's own context below.
    try:
        raw = await asyncio.to_thread(_serpapi_jobs, query)
    except JobSearchError as exc:
        _log.warning("badge job search failed: %s", exc)
        if "serpapi_key not set" in str(exc):
            raise HTTPException(status_code=503, detail="Job search isn't set up on this server.") from exc
        raise HTTPException(status_code=502, detail="Job search failed - try again.") from exc

    jobs = [j for j in (_web_job(r) for r in raw) if j is not None]
    with _db() as con:
        con.execute("DELETE FROM job_search_results WHERE expires < ?", (time.time(),))
        con.execute(
            "INSERT OR REPLACE INTO job_search_results VALUES (?, ?, ?)",
            (search_id, time.time() + TTL, json.dumps(jobs)),
        )
    return _job_rows(search_id, jobs, limit)


@router.post("/jobs/queue")
async def badge_queue_job(
    request: JobQueueRequest,
    user: Annotated[User, Depends(require_badge_client)],  # noqa: ARG001
) -> dict:
    """Add one search result to the pipeline and return its job id.

    Idempotent: picking a posting that is already queued returns the existing
    row, so a double press can't create two jobs.
    """
    from lib.db import get_connection
    from tools.job_discovery import lookup_result, queue_result

    try:
        job = lookup_result(request.search_id, request.number)
        message = queue_result(request.search_id, request.number)
    except ValueError as exc:
        raise HTTPException(status_code=410, detail="Those results expired - search again.") from exc

    with get_connection() as con:
        row = next(
            (
                r
                for r in con.execute("SELECT id, company, role FROM job_queue ORDER BY id DESC")
                if (r["company"] or "").casefold() == job["company"].casefold()
                and (r["role"] or "").casefold() == job["role"].casefold()
            ),
            None,
        )
    if row is None:
        raise HTTPException(status_code=500, detail="Queued, but the job could not be found.")
    return {
        "job_id": row["id"],
        "company": _clip(job["company"], _COMPANY_CHARS),
        "role": _clip(job["role"], _ROLE_CHARS),
        "status": "already queued" if message.startswith("Already") else "queued",
    }


# ── material generation ────────────────────────────────────────────────────────

_KIND = "badge_materials"
_VALID_MATERIALS = ("resume", "cover_letter", "both")


class MaterialsRequest(BaseModel):
    job_id: int
    material: str = "resume"
    # Visual layout + colour theme for the PDF. Empty template is the legacy
    # layout, which ignores style. Firmware that predates the picker sends
    # neither and gets exactly what it always got.
    template: str = ""
    style: str = "navy"


def _generate_materials(inputs: dict) -> dict:
    """Work executor (kind=badge_materials): look up the job, generate, report paths.

    Runs under the dispatcher with partition context taken from the work row,
    never from the request that queued it — the badge is long gone by the time
    this runs.

    The generators called below are themselves @tracked (control-plane P1), so
    each document gets its own row stamped with prompt_version and model. This
    row is the badge's *async* handle — the thing it polls — and exists because
    P1's generation rows run inline via run_now for interactive callers, which
    a polling battery-powered device cannot use. Same relationship capture_url
    has with the assessment row it nests.
    """
    from lib.db import get_connection

    job_id = int(inputs["job_id"])
    material = inputs.get("material", "resume")
    template = inputs.get("template", "")
    style = inputs.get("style") or "navy"

    with get_connection() as con:
        row = con.execute(
            "SELECT company, role, jd FROM job_queue WHERE id = ?", (job_id,)
        ).fetchone()
    if row is None:
        raise ValueError(f"job_queue row {job_id} not found")

    company, role, jd = row["company"], row["role"] or "Unknown role", row["jd"] or ""
    artifacts: dict = {"company": company, "role": role}
    errors: dict[str, str] = {}

    from tools import generate

    wanted = [m for m in ("resume", "cover_letter") if material in (m, "both")]
    for name in wanted:
        if name == "resume":
            result = str(generate.generate_resume(company, role, jd, template=template, style=style))
        else:
            result = str(
                generate.generate_cover_letter(company, role, jd, cl_template=template, cl_style=style)
            )
        failure = _generation_failure(result)
        if failure:
            errors[name] = failure
        else:
            artifacts[name] = result

    if len(errors) == len(wanted):
        # Nothing was written. Fail the row so the badge's poll says so instead
        # of listing a document that does not exist.
        raise RuntimeError("; ".join(errors.values()))
    if errors:
        artifacts["errors"] = errors
    return artifacts


def _generation_failure(result: str) -> str:
    """Return a short reason if *result* is not a generated document, else "".

    The generators never raise on failure — they *report* it in their return
    text, because their usual caller is an MCP client that reads that text.
    With no LLM configured they return a "CONTEXT PACKAGE" for the client to
    write from; on an API error a "✗ …" line followed by that same package.
    Either is a successful call that produced no file, and storing it as the
    artifact made every one of them look like a finished document.
    """
    head = result.lstrip()
    if head.startswith("✓"):
        return ""
    if "CONTEXT PACKAGE" in head[:200]:
        return "no LLM configured on the server"
    first = head.splitlines()[0] if head else "empty result"
    return first.lstrip("✗ ").strip() or "generation failed"


work.register_kind(_KIND, _generate_materials)


@router.post("/materials")
async def badge_materials(
    request: MaterialsRequest,
    user: Annotated[User, Depends(require_badge_client)],  # noqa: ARG001
) -> dict:
    """Enqueue generation and return the work id immediately.

    The badge shows a spinner against this id; the dispatcher does the work.
    """
    if request.material not in _VALID_MATERIALS:
        raise HTTPException(
            status_code=422,
            detail=f"material must be one of {', '.join(_VALID_MATERIALS)}.",
        )
    if request.job_id <= 0:
        raise HTTPException(
            status_code=422,
            detail="That result isn't a queued job yet — capture it first.",
        )
    from lib.template_loader import template_style_error

    # Same gate the generators and export use, for both document kinds (a
    # "both" request applies one choice to each), checked here so a bad value
    # is a 422 now rather than a failed work row a minute later.
    for is_cl in (False, True):
        err = template_style_error(request.template, request.style, cover_letter=is_cl)
        if err:
            raise HTTPException(status_code=422, detail=err)
    work_id = work.enqueue(
        _KIND,
        {
            "job_id": request.job_id,
            "material": request.material,
            "template": request.template,
            "style": request.style,
        },
        origin="badge",
    )
    return {"status": "queued", "work_id": work_id}


@router.get("/work/{item_id}")
async def badge_work(
    item_id: int,
    user: Annotated[User, Depends(require_badge_client)],  # noqa: ARG001
) -> dict:
    """Compact poll target: just enough for the badge to draw a status line.

    Deliberately not a thin proxy to /api/work — that returns inputs, timings
    and full tracebacks, which is both wasted bytes on a 320x240 screen and
    more than a semi-public credential should be able to read back.
    """
    item = work.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="No such work item.")

    artifacts = item.get("artifacts") or {}
    if isinstance(artifacts, dict):
        done = [k for k in ("resume", "cover_letter") if artifacts.get(k)]
    else:
        done = []
    return {
        "work_id": item_id,
        "status": item.get("status", ""),
        "made": done,
        # One short line, never a traceback.
        "detail": _failure_line(item.get("error")) if item.get("status") == "failed" else "",
    }


def _failure_line(error: "str | None") -> str:
    """The exception message only. The row's error is "<message>\n<traceback>",
    and _clip() collapses whitespace, so clipping the whole thing would run a
    short message straight into "Traceback (most recent…"."""
    first = (error or "").strip().splitlines()
    return _clip(first[0] if first else "", _DETAIL_CHARS)
