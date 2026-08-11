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

import logging
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


# ── material generation ────────────────────────────────────────────────────────

_KIND = "badge_materials"
_VALID_MATERIALS = ("resume", "cover_letter", "both")


class MaterialsRequest(BaseModel):
    job_id: int
    material: str = "resume"


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

    with get_connection() as con:
        row = con.execute(
            "SELECT company, role, jd FROM job_queue WHERE id = ?", (job_id,)
        ).fetchone()
    if row is None:
        raise ValueError(f"job_queue row {job_id} not found")

    company, role, jd = row["company"], row["role"] or "Unknown role", row["jd"] or ""
    artifacts: dict[str, str] = {"company": company, "role": role}

    if material in ("resume", "both"):
        from tools.generate import generate_resume

        artifacts["resume"] = str(generate_resume(company, role, jd))
    if material in ("cover_letter", "both"):
        from tools.generate import generate_cover_letter

        artifacts["cover_letter"] = str(generate_cover_letter(company, role, jd))
    return artifacts


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
    work_id = work.enqueue(
        _KIND,
        {"job_id": request.job_id, "material": request.material},
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
        "detail": _clip(item.get("error") or "", _ROLE_CHARS) if item.get("status") == "failed" else "",
    }
