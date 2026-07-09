"""Mobile companion API: Career Inbox events, push tokens, share-sheet capture.

Philosophy (docs/mobile/ROADMAP.md): desktop creates knowledge, mobile
captures reality, cloud synchronizes. This router is the cloud side of the
capture loop:

  GET  /api/events         — the Career Inbox: a typed, chronological feed of
                             everything that changed, derived from the sync
                             journal (which already records every write on
                             every device) + live row snapshots.
  POST /api/push/register  — store an Expo push token for this user.
  POST /api/capture        — share-sheet entry point: import a job URL,
                             queue it, kick an assessment in the background,
                             push "Assessment complete: N/10" when it lands.

Auth: same PAT/Entra dependency as the rest of the API; on the hosted
product the middleware resolves the caller's partition.
"""
from __future__ import annotations

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from lib import work
from transport.http.auth import require_authenticated_user
from transport.http.security import User

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["mobile"])


# ── Career Inbox ───────────────────────────────────────────────────────────────

def _event_for(entry: dict, row: "dict | None") -> "dict | None":
    """Humanize one journal entry into an inbox event (None = not inbox-worthy)."""
    tbl, op, ts = entry["tbl"], entry["op"], entry["ts"]
    nk = json.loads(entry["nk"])
    base = {"id": entry["id"], "ts": ts}

    if tbl == "job_queue":
        company, role = (nk + ["", ""])[:2]
        if op == "delete":
            return None
        score = (row or {}).get("fitment_score")
        status = ((row or {}).get("status") or "").lower()
        if status in ("evaluated", "added") and score:
            return {**base, "type": "assessment_done", "title": f"Assessment complete: {score}",
                    "subtitle": f"{company} — {role}", "company": company, "role": role}
        return {**base, "type": "job_imported", "title": f"Job imported: {company}",
                "subtitle": role, "company": company, "role": role}
    if tbl == "interviews":
        company, role = (nk + ["", "", ""])[1:3] if len(nk) >= 3 else ("", "")
        itype = ((row or {}).get("interview_type") or "interview").replace("_", " ")
        return {**base, "type": "interview_logged", "title": f"Interview logged: {company}",
                "subtitle": f"{itype} — {role}", "company": company, "role": role}
    if tbl == "applications":
        company, role = (nk + ["", ""])[:2]
        status = (row or {}).get("status") or ""
        return {**base, "type": "application_update", "title": f"{company}: {status}" if status else f"{company} updated",
                "subtitle": role, "company": company, "role": role}
    if tbl == "application_events":
        etype = (nk + [""])[0].replace("_", " ")
        return {**base, "type": "activity", "title": etype.capitalize(),
                "subtitle": (row or {}).get("notes") or ""}
    if tbl == "rejections":
        company, role = (nk + ["", ""])[:2]
        return {**base, "type": "rejection", "title": f"Rejection: {company}", "subtitle": role,
                "company": company, "role": role}
    return None


@router.get("/events")
async def inbox_events(
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
    since_id: int = 0,
    limit: int = 50,
) -> dict:
    """Newest-first inbox feed. Pass since_id=0 for the latest page; the
    response's oldest id can be used as before_id-style pagination later."""
    from lib.db import get_connection
    from lib.sync import _SPECS_BY_NAME, _row_payload

    limit = max(1, min(limit, 200))
    events: list[dict] = []
    with get_connection() as con:
        rows = con.execute(
            "SELECT id, tbl, op, nk, ts FROM sync_log "
            "WHERE id > ? ORDER BY id DESC LIMIT ?",
            (since_id, limit * 3),  # headroom: not every entry maps to an event
        ).fetchall()
        for r in rows:
            spec = _SPECS_BY_NAME.get(r["tbl"])
            row = None
            if spec is not None and r["op"] != "delete":
                try:
                    row = _row_payload(con, spec, json.loads(r["nk"]))
                except Exception:  # noqa: BLE001
                    row = None
            event = _event_for(dict(r), row)
            if event:
                events.append(event)
            if len(events) >= limit:
                break
    return {"events": events, "latest_id": events[0]["id"] if events else since_id}


# ── push tokens ────────────────────────────────────────────────────────────────

def _ensure_push_table(con) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS push_tokens (
            token      TEXT PRIMARY KEY,
            platform   TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )"""
    )


class PushRegisterRequest(BaseModel):
    token: str      # Expo push token (ExponentPushToken[...])
    platform: str = ""


@router.post("/push/register")
async def push_register(
    request: PushRegisterRequest,
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
) -> dict:
    from lib.db import get_connection

    token = request.token.strip()
    if not token.startswith("ExponentPushToken"):
        raise HTTPException(status_code=422, detail="Expected an Expo push token.")
    with get_connection() as con:
        _ensure_push_table(con)
        con.execute(
            "INSERT OR REPLACE INTO push_tokens (token, platform) VALUES (?, ?)",
            (token, request.platform.strip()),
        )
        con.commit()
    return {"status": "registered"}


def send_push(title: str, body: str, data: "dict | None" = None) -> int:
    """Best-effort Expo push to every registered device. Returns send count."""
    import httpx

    from lib.db import get_connection

    with get_connection() as con:
        _ensure_push_table(con)
        tokens = [r[0] for r in con.execute("SELECT token FROM push_tokens").fetchall()]
    if not tokens:
        return 0
    messages = [
        {"to": t, "title": title, "body": body, "data": data or {}, "sound": "default"}
        for t in tokens
    ]
    try:
        httpx.post("https://exp.host/--/api/v2/push/send", json=messages, timeout=15.0)
    except Exception as exc:  # noqa: BLE001 — pushes must never break the caller
        _log.warning("push send failed: %s", exc)
        return 0
    return len(messages)


# ── share-sheet capture ────────────────────────────────────────────────────────

class CaptureRequest(BaseModel):
    url: str = ""
    text: str = ""   # future: pasted JD text instead of a URL


def _capture_and_assess(inputs: dict) -> dict:
    """Work executor (kind=capture_url): import → queue → assess → push.

    Runs under the dispatcher, which sets the partition context from the work
    row's home partition — the outcome (success, failure, artifacts, error)
    is durably recorded on the row either way. Pushes are the human-facing
    signal; the row is the system of record.
    """
    url = inputs["url"]
    try:
        return _capture_and_assess_inner(url)
    except Exception:  # noqa: BLE001 — the user is waiting on a push either way
        _log.exception("capture worker failed for %s", url)
        send_push(
            "Assessment failed",
            "Something went wrong while evaluating that job. Try sharing it again.",
            {"type": "capture_failed"},
        )
        raise  # the work row records the failure + traceback


def _capture_and_assess_inner(url: str) -> dict:
    from tools.job_scraper import scrape_job_url

    result = scrape_job_url(url, auto_queue=True)
    company = role = ""
    for line in str(result).splitlines():
        if line.lower().startswith("company:"):
            company = line.split(":", 1)[1].strip()
        elif line.lower().startswith("role:"):
            role = line.split(":", 1)[1].strip()
    if not company:
        send_push("Import failed", "Couldn't read that job posting.", {"type": "capture_failed"})
        return {"imported": False}

    from lib.db import get_connection

    with get_connection() as con:
        row = con.execute(
            "SELECT jd FROM job_queue WHERE company = ? ORDER BY id DESC LIMIT 1", (company,)
        ).fetchone()
    jd = row[0] if row else ""

    from tools.fitment import run_job_assessment

    outcome = run_job_assessment(company, role or "Unknown role", jd)
    score = ""
    for line in str(outcome).splitlines():
        if "/10" in line:
            score = line.strip().lstrip("#").strip()
            break
    send_push(
        f"Assessment complete: {score or 'done'}",
        f"{company} — {role}",
        {"type": "assessment_done", "company": company, "role": role},
    )
    return {"imported": True, "company": company, "role": role, "score": score}


work.register_kind("capture_url", _capture_and_assess)


@router.post("/capture")
async def capture(
    request: CaptureRequest,
    user: Annotated[User, Depends(require_authenticated_user)],  # noqa: ARG001
) -> dict:
    """Share-sheet entry: enqueue a durable work item, return its id fast.
    The dispatcher assesses in the background and pushes when it lands."""
    url = request.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Share a job posting URL.")
    work_id = work.enqueue("capture_url", {"url": url}, origin="mobile-share")
    return {"status": "capturing", "work_id": work_id, "detail": "Saved. Assessment running…"}
