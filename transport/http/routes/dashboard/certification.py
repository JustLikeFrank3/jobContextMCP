"""Certification dashboard: weekly work-search reports for the claim portal.

JSON endpoints the React Certification screen consumes:

    GET  /dashboard/certification/data          index + live current-week progress
    GET  /dashboard/certification/report/{id}   one frozen report, full detail
    POST /dashboard/certification/profile       update state rules (the dropdown)
    POST /dashboard/certification/generate      freeze a report for a week
    POST /dashboard/certification/submit        mark a version as the filed record
"""
from __future__ import annotations

import asyncio
import datetime
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from transport.http.auth import require_api_key

router = APIRouter(dependencies=[Depends(require_api_key)])


def _index_payload() -> dict:
    from lib.db import get_connection
    from tools import certification

    profile = certification.get_state_profile()
    target = int(profile.get("min_activities_per_week", 3))

    # Live progress for the RUNNING week — derived, not frozen. This is the
    # Wednesday "2/3 so far" signal that turns a Sunday compliance problem
    # into a Thursday to-do.
    end_date = certification.current_week_ending(profile)
    start, end_date = certification._week_window(end_date)
    activities = certification.derive_activities(start, end_date, profile)
    picked, _ = certification.select_entries(activities, target)
    progress = {
        "logged": len(picked),
        "target": target,
        "weekStart": start.isoformat(),
        "weekEnding": end_date.isoformat(),
        "onTrack": len(picked) >= target,
    }

    with get_connection() as con:
        rows = con.execute(
            "SELECT id, week_ending, version, state, entries_json, gaps_json, generated_at"
            " FROM certification_report ORDER BY week_ending DESC, version DESC LIMIT 60"
        ).fetchall()
        submitted = certification.submissions_by_week(con)
    reports = []
    for row in rows:
        try:
            n_entries = len(json.loads(row["entries_json"] or "[]"))
            gaps = json.loads(row["gaps_json"] or "[]")
        except (TypeError, ValueError):
            n_entries, gaps = 0, []
        stamp = submitted.get(row["week_ending"])
        reports.append({
            "id": row["id"],
            "weekEnding": row["week_ending"],
            "version": row["version"],
            "state": row["state"],
            "entries": n_entries,
            "gaps": len(gaps),
            "generatedAt": row["generated_at"],
            "submitted": bool(stamp and stamp["version"] == row["version"]),
        })
    # Archive: one line per week — what was (or wasn't) filed. The filed
    # version is resolved back to a local report id when that row is present
    # (sync peers may hold the stamp before the report row arrives).
    weeks: dict[str, dict] = {}
    for rep in reports:
        wk = rep["weekEnding"]
        stamp = submitted.get(wk)
        if wk not in weeks:
            weeks[wk] = {
                "weekEnding": wk,
                "versions": 0,
                "submittedVersion": stamp["version"] if stamp else None,
                "submittedAt": stamp["submitted_at"] if stamp else "",
                "confirmation": stamp["confirmation_number"] if stamp else "",
                "reportId": None,
            }
        weeks[wk]["versions"] += 1
        if stamp and rep["version"] == stamp["version"] and weeks[wk]["reportId"] is None:
            weeks[wk]["reportId"] = rep["id"]
    archive = sorted(weeks.values(), key=lambda w: w["weekEnding"], reverse=True)
    return {
        "configured": certification.is_configured(),
        "profile": profile,
        "progress": progress,
        "reports": reports,
        "archive": archive,
        "total": len(reports),
    }


@router.get("/certification/data")
async def certification_data() -> JSONResponse:
    return JSONResponse(await asyncio.to_thread(_index_payload))


def _report_payload(report_id: int) -> "dict | None":
    from lib.db import get_connection
    from tools import certification

    with get_connection() as con:
        report = certification._load_report(con, report_id)
    if report is None:
        return None
    return {
        "id": report["id"],
        "weekEnding": report["week_ending"],
        "version": report["version"],
        "state": report["state"],
        "profile": report["profile"],
        "entries": report["entries"],
        "alternates": report["alternates"],
        "gaps": report["gaps"],
        "generatedAt": report["generated_at"],
        "exports": report["exports"],
    }


@router.get("/certification/report/{report_id}")
async def certification_report(report_id: int) -> JSONResponse:
    payload = await asyncio.to_thread(_report_payload, report_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"No report with id={report_id}")
    return JSONResponse(payload)


class ProfileBody(BaseModel):
    min_activities_per_week: int = 0
    state: str = ""
    week_ends_on: str = ""
    counts_inbound_recruiter: "bool | None" = None


@router.post("/certification/profile")
async def certification_profile(body: ProfileBody) -> JSONResponse:
    from tools import certification

    result = await asyncio.to_thread(
        certification.certification_state_profile,
        mode="set",
        state=body.state,
        min_activities_per_week=body.min_activities_per_week,
        week_ends_on=body.week_ends_on,
        counts_inbound_recruiter=body.counts_inbound_recruiter,
    )
    if result.startswith("✗"):
        raise HTTPException(status_code=400, detail=result)
    return JSONResponse({"ok": True, "message": result})


class SubmitBody(BaseModel):
    report_id: int
    confirmation_number: str = ""


@router.post("/certification/submit")
async def certification_submit(body: SubmitBody) -> JSONResponse:
    from tools import certification

    result = await asyncio.to_thread(
        certification.mark_certification_submitted,
        body.report_id,
        confirmation_number=body.confirmation_number,
    )
    if result.startswith("✗"):
        raise HTTPException(status_code=400, detail=result)
    return JSONResponse({"ok": True, "message": result})


class GenerateBody(BaseModel):
    week_ending: str = ""


@router.post("/certification/generate")
async def certification_generate(body: GenerateBody) -> JSONResponse:
    from tools import certification

    week = body.week_ending.strip()
    if week:
        try:
            datetime.date.fromisoformat(week)
        except ValueError:
            raise HTTPException(status_code=400, detail="week_ending must be YYYY-MM-DD")
    result = await asyncio.to_thread(
        certification.weekly_certification_report, week_ending=week
    )
    if result.startswith("✗"):
        raise HTTPException(status_code=400, detail=result)
    return JSONResponse({"ok": True, "summary": result})
