"""Pipeline dashboard — queue + assessment + resume choice + cover letter + apply."""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Literal
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from lib import config
from lib.io import _load_json, _load_master_context, _now, _save_json
from lib.openai_calls import create_chat_completion
from services import JobAnalysisService, ResumeService
from services.persona_service import PersonaService, DEFAULT_PERSONA
from tools.export import export_cover_letter_pdf, export_resume_pdf
from tools.generate import _extract_cover_letter_body, _sanitize_cover_letter_output
from tools.job_hunt import log_application_event, update_application
from tools.latex_export import generate_cover_letter_latex
from tools.resume import save_cover_letter_txt, save_resume_txt
from transport.http.auth import require_api_key
from .shared import html_page
from .pipeline_helpers import (
    _JobActionRequest, _ResumeReadRequest, _ResumeEditRequest,
    _CoverLetterReadRequest, _CoverLetterEditRequest, _CoverLetterAcceptRequest,
    _CoverLetterCancelRequest, _load_queue_jobs, _find_job, _update_job,
    _list_resume_options, _optimized_resume_dir, _list_optimized_resume_options,
    _cover_letter_dir, _list_cover_letter_options, _resolve_optimized_resume,
    _resolve_cover_letter, _resolve_cover_letter_draft, _cover_letter_draft_pattern,
    _list_cover_letter_drafts, _next_cover_letter_draft_path, _delete_cover_letter_drafts,
    _suggest_optimized_resume_for_job, _suggest_cover_letter_for_job,
    _resume_edit_output_name, _cover_letter_edit_output_name,
    _build_resume_edit_messages, _build_cover_letter_edit_messages,
    _strip_model_wrapper, _material_href_for_pdf, _draft_href,
    _pdf_path_from_export_result, _recommend_resume, _fitment_preview,
    _normalize_fitment_context, _extract_md_section, _extract_bullets,
    _first_sentence, _signal_line, _is_ai_focused, _contains_keyword,
    _ai_evidence_from_master, _ai_assessment_caveat, _assessment_summary,
    _next_action_for_recommendation, _source_url_from_jd, _synthesize_assessment,
)

router = APIRouter(dependencies=[Depends(require_api_key)])

_COMPACT_TOKEN_RE = r"[^a-z0-9]+"

def _pipeline_payload() -> dict:
    jobs = _load_queue_jobs()
    resume_options = _list_resume_options()
    optimized_resume_options = _list_optimized_resume_options()
    cover_letter_options = _list_cover_letter_options()
    persona_options = PersonaService.list_personas()

    # Owner = the authenticated user's OID matches the configured ENTRA_OWNER_OID
    from lib.user_context import get_current_user_oid
    from lib.config import OWNER_OID as _OWNER_OID
    is_owner: bool = bool(_OWNER_OID) and get_current_user_oid() == _OWNER_OID

    payload_jobs = []
    for j in jobs:
        role = j.get("role", "")
        status = (j.get("status") or "pending").lower()
        assessment_summary, assessment_detail = _synthesize_assessment(j)
        payload_jobs.append({
            "id": j.get("id"),
            "company": j.get("company", ""),
            "role": role,
            "status": status,
            "source": j.get("source", ""),
            "added_date": j.get("added_date", ""),
            "fitment_score": j.get("fitment_score") or "",
            "decision_notes": j.get("decision_notes") or "",
            "assessed": status in {"evaluated", "added", "applied", "dismissed"},
            "assessment_summary": assessment_summary,
            "assessment_detail": assessment_detail,
            "recommended_resume": _recommend_resume(role, j.get("jd", ""), resume_options),
            "selected_resume": j.get("selected_resume") or "",
            "last_edited_resume": j.get("last_edited_resume") or "",
            "suggested_edit_resume": _suggest_optimized_resume_for_job(j, optimized_resume_options),
            "last_edited_cover_letter": j.get("last_edited_cover_letter") or "",
            "suggested_edit_cover_letter": _suggest_cover_letter_for_job(j, cover_letter_options),
        })

    return {
        "total": len(payload_jobs),
        "resume_options": resume_options,
        "optimized_resume_options": optimized_resume_options,
        "cover_letter_options": cover_letter_options,
        "persona_options": persona_options,
        "default_persona": DEFAULT_PERSONA,
        "is_owner": is_owner,
        "jobs": payload_jobs,
    }


@router.get("/pipeline/data")
async def pipeline_data() -> JSONResponse:
    return JSONResponse(_pipeline_payload())


@router.post("/pipeline/evaluate", responses={404: {"description": "Job id not found"}})
async def pipeline_evaluate(req: _JobActionRequest) -> JSONResponse:
    job = _find_job(req.job_id)
    result = JobAnalysisService.evaluate(
        company=job.get("company", ""),
        role=job.get("role", ""),
        job_description=job.get("jd", ""),
        source=job.get("source", ""),
        persona=req.persona,
    )
    _update_job(req.job_id, lambda j: j.update({
        "fitment_context": _normalize_fitment_context(result.fitment_context or j.get("fitment_context", "")),
        "status": result.queue_status or j.get("status", "pending"),
    }))
    return JSONResponse({
        "ok": True,
        "result": {
            "company": result.company,
            "role": result.role,
            "queue_status": result.queue_status,
            "evaluated": result.evaluated,
        },
    })


@router.post("/pipeline/generate-resume", responses={404: {"description": "Job id not found"}})
async def pipeline_generate_resume(req: _JobActionRequest) -> JSONResponse:
    job = _find_job(req.job_id)
    selected = (job.get("selected_resume") or "").strip()
    if not selected:
        selected = _recommend_resume(job.get("role", ""), job.get("jd", ""), _list_resume_options())
        _update_job(req.job_id, lambda j: j.update({"selected_resume": selected}))

    result = ResumeService.generate(
        company=job.get("company", ""),
        role=job.get("role", ""),
        job_description=job.get("jd", ""),
        output_filename=req.output_filename,
        kind="resume",
        persona=req.persona,
    )
    return JSONResponse({
        "ok": result.success,
        "content": result.content,
        "notes": result.notes,
        "selected_resume": selected,
    })


@router.post("/pipeline/generate-cover-letter", responses={403: {"description": "Owner-only feature"}, 404: {"description": "Job id not found"}})
async def pipeline_generate_cover_letter(req: _JobActionRequest) -> JSONResponse:
    # LaTeX pipeline is owner-only — tectonic is not installed for beta users
    # and the template assets live in the owner's workspace.
    if req.export_pipeline == "latex":
        from lib.user_context import get_current_user_oid
        from lib.config import OWNER_OID as _OWNER_OID
        if not (bool(_OWNER_OID) and get_current_user_oid() == _OWNER_OID):
            raise HTTPException(status_code=403, detail="LaTeX export is not available for beta accounts.")

    job = _find_job(req.job_id)
    selected = (job.get("selected_resume") or "").strip()
    if not selected:
        selected = _recommend_resume(job.get("role", ""), job.get("jd", ""), _list_resume_options())
        _update_job(req.job_id, lambda j: j.update({"selected_resume": selected}))

    result = ResumeService.generate(
        company=job.get("company", ""),
        role=job.get("role", ""),
        job_description=job.get("jd", ""),
        output_filename=req.output_filename,
        kind="cover_letter",
        export_pipeline=req.export_pipeline,
        persona=req.persona,
        selected_resume=selected,
    )
    return JSONResponse({
        "ok": result.success,
        "content": result.content,
        "notes": result.notes,
        "selected_resume": selected,
    })


@router.post(
    "/pipeline/select-resume",
    responses={
        400: {"description": "Missing resume_name"},
        404: {"description": "Job id not found"},
    },
)
async def pipeline_select_resume(req: _JobActionRequest) -> JSONResponse:
    if not req.resume_name:
        raise HTTPException(status_code=400, detail="resume_name is required")

    _update_job(req.job_id, lambda j: j.update({"selected_resume": req.resume_name}))
    return JSONResponse({"ok": True, "job_id": req.job_id, "selected_resume": req.resume_name})


@router.post(
    "/pipeline/read-resume",
    responses={
        400: {"description": "Only optimized resume .txt files can be read"},
        404: {"description": "Resume file not found"},
    },
)
async def pipeline_read_resume(req: _ResumeReadRequest) -> JSONResponse:
    path = _resolve_optimized_resume(req.resume_name)
    return JSONResponse({
        "ok": True,
        "resume_name": path.name,
        "content": path.read_text(encoding="utf-8"),
    })


@router.post(
    "/pipeline/edit-resume",
    responses={
        400: {"description": "Invalid edit request"},
        404: {"description": "Job id or resume file not found"},
        502: {"description": "Model returned an invalid edit"},
        503: {"description": "LLM client not configured"},
    },
)
async def pipeline_edit_resume(req: _ResumeEditRequest) -> JSONResponse:
    job = _find_job(req.job_id)
    source = _resolve_optimized_resume(req.resume_name)
    current_resume = source.read_text(encoding="utf-8")
    instructions = req.instructions.strip()
    if not instructions:
        raise HTTPException(status_code=400, detail="Edit instructions are required")

    client, model = config.get_llm_client()
    if client is None:
        raise HTTPException(status_code=503, detail="OpenAI API key is not configured")

    messages = _build_resume_edit_messages(
        company=job.get("company", ""),
        role=job.get("role", ""),
        job_description=job.get("jd", ""),
        current_resume=current_resume,
        instructions=instructions,
    )
    response = create_chat_completion(
        client,
        label="resume_edit_dialog",
        model=model or str(config.get_config_value("openai_model", "gpt-4o")),
        messages=messages,
        temperature=0.2,
        max_tokens=3500,
    )
    edited = _strip_model_wrapper(response.choices[0].message.content or "")
    if not edited:
        raise HTTPException(status_code=502, detail="Model returned an empty edited resume")

    output_name = _resume_edit_output_name(
        source.name,
        job.get("company", ""),
        job.get("role", ""),
        req.output_filename,
    )
    save_result = save_resume_txt(output_name, edited)
    pdf_result = ""
    if req.export_pdf:
        pdf_result = export_resume_pdf(output_name)

    _update_job(req.job_id, lambda j: j.update({"last_edited_resume": output_name}))

    return JSONResponse({
        "ok": True,
        "job_id": req.job_id,
        "source_resume": source.name,
        "edited_resume": output_name,
        "save_result": save_result,
        "pdf_result": pdf_result,
        "usage": {
            "prompt_tokens": getattr(response.usage, "prompt_tokens", None) if response.usage else None,
            "completion_tokens": getattr(response.usage, "completion_tokens", None) if response.usage else None,
            "total_tokens": getattr(response.usage, "total_tokens", None) if response.usage else None,
        },
    })


@router.post(
    "/pipeline/read-cover-letter",
    responses={
        400: {"description": "Only cover-letter .txt files can be read"},
        404: {"description": "Cover-letter file not found"},
    },
)
async def pipeline_read_cover_letter(req: _CoverLetterReadRequest) -> JSONResponse:
    path = _resolve_cover_letter(req.cover_letter_name)
    return JSONResponse({
        "ok": True,
        "cover_letter_name": path.name,
        "content": path.read_text(encoding="utf-8"),
    })


@router.get(
    "/pipeline/cover-letter-draft/{draft_name:path}",
    responses={
        400: {"description": "Only cover-letter .tmp draft files can be opened"},
        404: {"description": "Cover-letter draft not found"},
    },
)
async def pipeline_cover_letter_draft(draft_name: str) -> FileResponse:
    path = _resolve_cover_letter_draft(draft_name)
    return FileResponse(path, media_type="text/plain; charset=utf-8", filename=path.name)


def _export_cover_letter_draft_html(draft_path: Path, role: str) -> str:
    """Export a transient .tmp draft through the existing HTML exporter."""
    temp_txt = draft_path.with_name(f"{draft_path.name}.txt")
    try:
        temp_txt.write_text(draft_path.read_text(encoding="utf-8"), encoding="utf-8")
        return export_cover_letter_pdf(
            temp_txt.name,
            output_filename=f"{draft_path.stem}.pdf",
            footer_tag=(role or "SOFTWARE ENGINEER").upper(),
        )
    finally:
        temp_txt.unlink(missing_ok=True)


@router.post(
    "/pipeline/edit-cover-letter",
    responses={
        400: {"description": "Invalid edit request"},
        404: {"description": "Job id or cover-letter file not found"},
        502: {"description": "Model returned an invalid edit"},
        503: {"description": "LLM client not configured"},
    },
)
async def pipeline_edit_cover_letter(req: _CoverLetterEditRequest) -> JSONResponse:
    job = _find_job(req.job_id)
    source = _resolve_cover_letter(req.cover_letter_name)
    current_source = _resolve_cover_letter_draft(req.draft_name) if req.draft_name.strip() else source
    current_cover_letter = current_source.read_text(encoding="utf-8")
    instructions = req.instructions.strip()
    if not instructions:
        raise HTTPException(status_code=400, detail="Edit instructions are required")

    client, model = config.get_llm_client()
    if client is None:
        raise HTTPException(status_code=503, detail="OpenAI API key is not configured")

    messages = _build_cover_letter_edit_messages(
        company=job.get("company", ""),
        role=job.get("role", ""),
        job_description=job.get("jd", ""),
        current_cover_letter=current_cover_letter,
        instructions=instructions,
    )
    response = create_chat_completion(
        client,
        label="cover_letter_edit_dialog",
        model=model or str(config.get_config_value("openai_model", "gpt-4o")),
        messages=messages,
        temperature=0.2,
        max_tokens=2500,
    )
    edited = _sanitize_cover_letter_output(_strip_model_wrapper(response.choices[0].message.content or ""))
    if not edited:
        raise HTTPException(status_code=502, detail="Model returned an empty edited cover letter")

    draft_path = _next_cover_letter_draft_path(source.name)
    draft_path.write_text(edited, encoding="utf-8")
    save_result = f"✓ Cover letter draft saved: {draft_path}"
    pdf_result = ""
    pdf_href = ""
    if req.export_pdf:
        if req.export_pipeline == "latex":
            body = _extract_cover_letter_body(edited) or edited
            pdf_path = generate_cover_letter_latex(
                body=body,
                company=job.get("company", ""),
                role=job.get("role", ""),
                role_title=job.get("role", "") or "Full Stack Software Engineer",
            )
            pdf_result = f"✓ PDF exported: {pdf_path}"
            pdf_href = _material_href_for_pdf(pdf_path)
        else:
            pdf_result = _export_cover_letter_draft_html(draft_path, job.get("role", ""))
            pdf_href = _material_href_for_pdf(_pdf_path_from_export_result(pdf_result))

    _update_job(req.job_id, lambda j: j.update({"last_edited_cover_letter": source.name}))

    return JSONResponse({
        "ok": True,
        "job_id": req.job_id,
        "source_cover_letter": source.name,
        "edited_cover_letter": draft_path.name,
        "draft_name": draft_path.name,
        "draft_href": _draft_href(draft_path),
        "draft_content": edited,
        "save_result": save_result,
        "pdf_result": pdf_result,
        "pdf_href": pdf_href,
        "export_pipeline": req.export_pipeline,
        "usage": {
            "prompt_tokens": getattr(response.usage, "prompt_tokens", None) if response.usage else None,
            "completion_tokens": getattr(response.usage, "completion_tokens", None) if response.usage else None,
            "total_tokens": getattr(response.usage, "total_tokens", None) if response.usage else None,
        },
    })


@router.post(
    "/pipeline/accept-cover-letter-edit",
    responses={
        400: {"description": "Invalid accept request"},
        404: {"description": "Cover-letter file or draft not found"},
    },
)
async def pipeline_accept_cover_letter_edit(req: _CoverLetterAcceptRequest) -> JSONResponse:
    source = _resolve_cover_letter(req.cover_letter_name)
    draft = _resolve_cover_letter_draft(req.draft_name)
    if draft not in _list_cover_letter_drafts(source.name):
        raise HTTPException(status_code=400, detail="Draft does not belong to this cover letter")

    backup = source.with_name(f"{source.name}.bak")
    backup.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    source.write_text(draft.read_text(encoding="utf-8"), encoding="utf-8")
    deleted = _delete_cover_letter_drafts(source.name)
    return JSONResponse({
        "ok": True,
        "cover_letter_name": source.name,
        "backup_name": backup.name,
        "deleted_drafts": deleted,
        "href": f"/dashboard/materials/file/cover_letters/{quote(source.name, safe='')}",
    })


@router.post(
    "/pipeline/cancel-cover-letter-edit",
    responses={
        400: {"description": "Only cover-letter .txt files can be cancelled"},
        404: {"description": "Cover-letter file not found"},
    },
)
async def pipeline_cancel_cover_letter_edit(req: _CoverLetterCancelRequest) -> JSONResponse:
    source = _resolve_cover_letter(req.cover_letter_name)
    deleted = _delete_cover_letter_drafts(source.name)
    return JSONResponse({"ok": True, "cover_letter_name": source.name, "deleted_drafts": deleted})


@router.post("/pipeline/queue-apply", responses={404: {"description": "Job id not found"}})
async def pipeline_queue_apply(req: _JobActionRequest) -> JSONResponse:
    job = _find_job(req.job_id)
    result = JobAnalysisService.decide(
        company=job.get("company", ""),
        role=job.get("role", ""),
        decision="add",
        notes=req.notes,
        fitment_score=job.get("fitment_score") or "",
    )
    return JSONResponse({"ok": True, "result": result})


@router.post("/pipeline/mark-applied", responses={404: {"description": "Job id not found"}})
async def pipeline_mark_applied(req: _JobActionRequest) -> JSONResponse:
    job = _find_job(req.job_id)
    company = job.get("company", "")
    role = job.get("role", "")
    note = req.notes.strip() or "Marked applied from dashboard queue."

    def mutate(j: dict) -> None:
        j["status"] = "applied"
        j["decision_notes"] = note
        j["decided_date"] = _now()

    updated_job = _update_job(req.job_id, mutate)
    app_result = update_application(
        company=company,
        role=role,
        status="applied",
        notes=note,
    )
    event_result = log_application_event(
        company=company,
        role=role,
        event_type="applied",
        notes=note,
    )
    return JSONResponse({
        "ok": True,
        "job_id": req.job_id,
        "status": updated_job.get("status"),
        "application_result": app_result,
        "event_result": event_result,
    })


@router.post("/pipeline/unqueue", responses={404: {"description": "Job id not found"}})
async def pipeline_unqueue(req: _JobActionRequest) -> JSONResponse:
    _update_job(req.job_id, lambda j: j.update({
        "status": "pending",
        "fitment_score": None,
        "decision_notes": None,
        "decided_date": None,
    }))
    return JSONResponse({"ok": True, "job_id": req.job_id, "status": "pending"})


@router.post("/pipeline/remove", responses={404: {"description": "Job id not found"}})
async def pipeline_remove(req: _JobActionRequest) -> JSONResponse:
    data = _load_json(config.JOB_QUEUE_FILE, {"jobs": []})
    jobs = data.get("jobs", [])
    before = len(jobs)
    jobs = [j for j in jobs if int(j.get("id", 0)) != int(req.job_id)]
    if len(jobs) == before:
        raise HTTPException(status_code=404, detail=f"Job id {req.job_id} not found")
    data["jobs"] = jobs
    _save_json(config.JOB_QUEUE_FILE, data)
    return JSONResponse({"ok": True, "removed_job_id": req.job_id})


_PREVIEW_FALLBACK_DATA: dict = {
    "name": "Your Name",
    "tagline": "Senior Software Engineer",
    "contact": {
        "phone": "555-000-0000",
        "email": "you@example.com",
        "linkedin": "linkedin.com/in/yourname",
        "github": "github.com/yourname",
        "location": "Atlanta, GA",
        "city_state": "Atlanta, GA",
        "address": "",
    },
    "synopsis": (
        "Experienced software engineer with 6+ years building high-throughput distributed systems, "
        "modernizing Java 8 monoliths to cloud-native microservices, and driving AI tool adoption "
        "across engineering organizations. Strong track record of 98% SLA and 80%+ test coverage."
    ),
    "sections": [
        {
            "type": "skills", "title": "TECHNICAL SKILLS",
            "items": [
                {"label": "Languages", "value": "Java (8–21), Python, TypeScript, SQL"},
                {"label": "Frameworks", "value": "Spring Boot, FastAPI, Angular 6–18"},
                {"label": "Cloud / DevOps", "value": "Azure Container Apps, Docker, Kubernetes, Terraform"},
                {"label": "AI / ML Tooling", "value": "LangGraph, LangChain, OpenAI API, agentic pipelines"},
            ],
        },
        {
            "type": "experience", "title": "EXPERIENCE",
            "jobs": [
                {
                    "title": "Software Engineer — Level 6",
                    "company": "General Motors",
                    "dates": "January 2022 – December 2025",
                    "groups": [],
                    "bullets": [
                        "Modernized 500K+ LOC Java 8 legacy platform to Java 21 / Spring Boot 3.5, achieving 98% SLA.",
                        "Architected event-driven microservice mesh on Azure Container Apps; reduced deploy time by 40%.",
                        "Led org-wide AI tool adoption initiative — drove 35%+ usage across 80-person engineering org.",
                        "Maintained 80%+ test coverage across all owned services via JUnit 5 / Mockito / Testcontainers.",
                    ],
                },
            ],
        },
        {
            "type": "projects", "title": "PERSONAL PROJECTS",
            "projects": [
                {
                    "name": "jobContextMCP — AI-powered job search platform",
                    "bullets": [
                        "MCP server exposing 40+ tools for resume generation, fitment analysis, and outreach drafting.",
                        "Agentic pipeline built with LangGraph; renders PDF resumes via WeasyPrint template system.",
                        "FastAPI dashboard with real-time SSE streaming and multi-tenant auth via Microsoft Entra ID.",
                    ],
                },
            ],
        },
        {
            "type": "education", "title": "EDUCATION",
            "degree": "B.S. Internet of Things Engineering",
            "school": "Florida International University, Miami, FL",
            "details": ["GPA: 3.85 — Magna Cum Laude"],
            "coursework": "Cloud Computing, Algorithms, Systems Design, Embedded Systems",
        },
        {
            "type": "leadership", "title": "CERTIFICATIONS & AWARDS",
            "items": [
                {"label": "Hackathon 1st Place", "value": "GM Innovation Hackathon 2023"},
                {"label": "Peer Award", "value": "GM Engineering Excellence — Q3 2024"},
                {"label": "Certification", "value": "Microsoft Azure Fundamentals (AZ-900)"},
            ],
        },
    ],
    "footer_tag": "SOFTWARE_ENGINEER",
}


@router.get("/pipeline/preview-template/{template_name}")
async def pipeline_preview_template(template_name: str) -> HTMLResponse:
    """Render the master resume with the requested template for inline browser preview."""
    from lib.resume_parser import _parse_resume_txt as _parse
    from lib.template_loader import render_resume as _render, VALID_TEMPLATES as _VALID

    if template_name not in _VALID:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown template {template_name!r}. Valid: {sorted(_VALID)}",
        )

    data: dict | None = None
    try:
        master_path = config.get_active_master_resume_path()
        if master_path.exists():
            try:
                text = master_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = master_path.read_text(encoding="latin-1")
            data = _parse(text)
            data["footer_tag"] = "SOFTWARE_ENGINEER"
    except Exception:
        pass

    if not data:
        data = dict(_PREVIEW_FALLBACK_DATA)

    html_str = _render(data, template=template_name)
    return HTMLResponse(html_str)


@router.get("/pipeline")
async def pipeline_board() -> HTMLResponse:
    body = """
<section class='cards' id='summary'></section>
<div class='bar'>
  <input id='q' class='search' placeholder='Filter company / role / status' style='min-width:260px;max-width:420px;flex:1' />
  <button id='addJobBtn' onclick='openAddJob()' style='white-space:nowrap'>＋ Add Job</button>
</div>
<section class='list' id='list'></section>

<!-- Add Job modal -->
<div id='addJobOverlay' style='display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:900;overflow-y:auto;padding:20px 12px'>
  <div style='max-width:540px;margin:0 auto;background:#0d1526;border:1px solid #2a3a5e;border-radius:14px;padding:20px'>
    <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:16px'>
      <span style='font-weight:700;font-size:1.05rem'>Add Job</span>
      <button onclick='closeAddJob()' style='background:none;border:none;font-size:1.4rem;color:#8899bb;cursor:pointer;padding:0 4px'>✕</button>
    </div>
    <label style='display:block;margin-bottom:12px'>
      <div style='font-size:0.82rem;color:#8899bb;margin-bottom:5px'>Company</div>
      <input id='ajCompany' placeholder='e.g. Stripe' style='width:100%;box-sizing:border-box;background:#0a1120;border:1px solid #2a3a5e;border-radius:8px;padding:9px 10px;color:#e0e8ff;font-size:0.9rem' />
    </label>
    <label style='display:block;margin-bottom:12px'>
      <div style='font-size:0.82rem;color:#8899bb;margin-bottom:5px'>Role</div>
      <input id='ajRole' placeholder='e.g. Senior Software Engineer' style='width:100%;box-sizing:border-box;background:#0a1120;border:1px solid #2a3a5e;border-radius:8px;padding:9px 10px;color:#e0e8ff;font-size:0.9rem' />
    </label>
    <label style='display:block;margin-bottom:16px'>
      <div style='font-size:0.82rem;color:#8899bb;margin-bottom:5px'>Job Description <span style='color:#556;font-weight:400'>(paste full text)</span></div>
      <textarea id='ajJD' rows='10' placeholder='Paste the job description here…' style='width:100%;box-sizing:border-box;background:#0a1120;border:1px solid #2a3a5e;border-radius:8px;padding:9px 10px;color:#e0e8ff;font-size:0.85rem;line-height:1.45;resize:vertical'></textarea>
    </label>
    <div style='display:flex;gap:10px;justify-content:flex-end'>
      <button onclick='closeAddJob()'>Cancel</button>
      <button id='ajSubmit' onclick='submitAddJob()' style='background:#1a3a6e;border-color:#3a5aae;color:#d0e4ff'>Queue &amp; Assess</button>
    </div>
    <div id='ajError' style='display:none;margin-top:10px;color:#ffaaaa;font-size:0.82rem'></div>
  </div>
</div>

<!-- Edit Resume modal -->
<div id='editResumeOverlay' style='display:none;position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:910;overflow-y:auto;padding:18px 10px'>
    <div style='max-width:1080px;margin:0 auto;background:#0d1526;border:1px solid #2a3a5e;border-radius:14px;padding:18px'>
        <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;gap:12px'>
            <div>
                <div style='font-weight:700;font-size:1.05rem'>Edit Resume</div>
                <div id='erJobLabel' style='color:#8899bb;font-size:0.82rem;margin-top:3px'></div>
            </div>
            <button onclick='closeEditResume()' style='background:none;border:none;font-size:1.4rem;color:#8899bb;cursor:pointer;padding:0 4px'>✕</button>
        </div>
        <div style='display:grid;grid-template-columns:minmax(0,1fr) minmax(300px,420px);gap:12px'>
            <div>
                <div style='display:flex;gap:8px;align-items:end;margin-bottom:10px;flex-wrap:wrap'>
                    <label style='flex:1;min-width:280px'>
                        <div style='font-size:0.82rem;color:#8899bb;margin-bottom:5px'>Source resume from Materials → Optimized Resumes</div>
                        <select id='erResume' onchange='loadEditResumeSource()' style='width:100%;box-sizing:border-box;background:#0a1120;border:1px solid #2a3a5e;border-radius:8px;padding:9px 10px;color:#e0e8ff;font-size:0.85rem'></select>
                    </label>
                    <button onclick='loadEditResumeSource()'>Reload</button>
                </div>
                <textarea id='erSource' rows='24' readonly style='width:100%;box-sizing:border-box;background:#07101e;border:1px solid #243452;border-radius:9px;padding:10px;color:#c8d8f4;font:0.78rem/1.42 ui-monospace,SFMono-Regular,Menlo,monospace;resize:vertical'></textarea>
            </div>
            <div>
                <label style='display:block;margin-bottom:10px'>
                    <div style='font-size:0.82rem;color:#8899bb;margin-bottom:5px'>Edit instructions</div>
                    <textarea id='erInstructions' rows='12' placeholder='Example: Read the resume you have. Keep the format, but make the AI platform evidence stronger, reduce LiveVox to one bullet, and add LangGraph where it fits.' style='width:100%;box-sizing:border-box;background:#0a1120;border:1px solid #2a3a5e;border-radius:8px;padding:9px 10px;color:#e0e8ff;font-size:0.85rem;line-height:1.45;resize:vertical'></textarea>
                </label>
                <label style='display:block;margin-bottom:12px'>
                    <div style='font-size:0.82rem;color:#8899bb;margin-bottom:5px'>Output filename <span style='color:#556;font-weight:400'>(optional)</span></div>
                    <input id='erOutput' placeholder='Leave blank for "source - Edited company_role_timestamp.txt"' style='width:100%;box-sizing:border-box;background:#0a1120;border:1px solid #2a3a5e;border-radius:8px;padding:9px 10px;color:#e0e8ff;font-size:0.85rem' />
                </label>
                <label style='display:flex;gap:8px;align-items:center;margin-bottom:16px;color:#c8d8f4;font-size:0.85rem'>
                    <input id='erExportPdf' type='checkbox' checked /> Export PDF after save
                </label>
                <div style='display:flex;gap:10px;justify-content:flex-end;flex-wrap:wrap'>
                    <button onclick='closeEditResume()'>Cancel</button>
                    <button id='erSubmit' onclick='submitEditResume()' style='background:#1a3a6e;border-color:#3a5aae;color:#d0e4ff'>Apply Edit</button>
                </div>
                <div id='erStatus' style='margin-top:12px;color:#aebcda;font-size:0.82rem;white-space:pre-wrap'></div>
            </div>
        </div>
    </div>
</div>

<!-- Edit Cover Letter modal -->
<div id='editCoverLetterOverlay' style='display:none;position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:915;overflow-y:auto;padding:18px 10px'>
    <div style='max-width:1080px;margin:0 auto;background:#0d1526;border:1px solid #2a3a5e;border-radius:14px;padding:18px'>
        <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;gap:12px'>
            <div>
                <div style='font-weight:700;font-size:1.05rem'>Edit Cover Letter</div>
                <div id='eclJobLabel' style='color:#8899bb;font-size:0.82rem;margin-top:3px'></div>
            </div>
            <button onclick='closeEditCoverLetter()' style='background:none;border:none;font-size:1.4rem;color:#8899bb;cursor:pointer;padding:0 4px'>✕</button>
        </div>
        <div style='display:grid;grid-template-columns:minmax(0,1fr) minmax(300px,420px);gap:12px'>
            <div>
                <div style='display:flex;gap:8px;align-items:end;margin-bottom:10px;flex-wrap:wrap'>
                    <label style='flex:1;min-width:280px'>
                        <div style='font-size:0.82rem;color:#8899bb;margin-bottom:5px'>Source cover letter from Materials → Cover Letters</div>
                        <select id='eclCoverLetter' onchange='loadEditCoverLetterSource()' style='width:100%;box-sizing:border-box;background:#0a1120;border:1px solid #2a3a5e;border-radius:8px;padding:9px 10px;color:#e0e8ff;font-size:0.85rem'></select>
                    </label>
                    <button onclick='loadEditCoverLetterSource()'>Reload</button>
                </div>
                <textarea id='eclSource' rows='24' readonly style='width:100%;box-sizing:border-box;background:#07101e;border:1px solid #243452;border-radius:9px;padding:10px;color:#c8d8f4;font:0.78rem/1.42 ui-monospace,SFMono-Regular,Menlo,monospace;resize:vertical'></textarea>
            </div>
            <div>
                <label style='display:block;margin-bottom:10px'>
                    <div style='font-size:0.82rem;color:#8899bb;margin-bottom:5px'>Edit instructions</div>
                    <textarea id='eclInstructions' rows='12' placeholder='Example: Read the cover letter you have. Keep the voice and structure, but make paragraph 2 less corporate, mention the LiveVox microphone-to-speaker latency, and export with LaTeX.' style='width:100%;box-sizing:border-box;background:#0a1120;border:1px solid #2a3a5e;border-radius:8px;padding:9px 10px;color:#e0e8ff;font-size:0.85rem;line-height:1.45;resize:vertical'></textarea>
                </label>
                <label style='display:block;margin-bottom:12px'>
                    <div style='font-size:0.82rem;color:#8899bb;margin-bottom:5px'>Output filename <span style='color:#556;font-weight:400'>(optional)</span></div>
                    <input id='eclOutput' placeholder='Leave blank for "source - Edited company_role_timestamp.txt"' style='width:100%;box-sizing:border-box;background:#0a1120;border:1px solid #2a3a5e;border-radius:8px;padding:9px 10px;color:#e0e8ff;font-size:0.85rem' />
                </label>
                <label style='display:block;margin-bottom:12px'>
                    <div style='font-size:0.82rem;color:#8899bb;margin-bottom:5px'>PDF export pipeline</div>
                    <select id='eclExportPipeline' style='width:100%;box-sizing:border-box;background:#0a1120;border:1px solid #2a3a5e;border-radius:8px;padding:9px 10px;color:#e0e8ff;font-size:0.85rem'>
                        <option value='latex' selected>LaTeX / tectonic</option>
                        <option value='html'>HTML / WeasyPrint</option>
                    </select>
                </label>
                <label style='display:flex;gap:8px;align-items:center;margin-bottom:16px;color:#c8d8f4;font-size:0.85rem'>
                    <input id='eclExportPdf' type='checkbox' checked /> Export PDF after save
                </label>
                <div style='display:flex;gap:10px;justify-content:flex-end;flex-wrap:wrap'>
                    <button onclick='closeEditCoverLetter()'>Cancel</button>
                    <button id='eclSubmit' onclick='submitEditCoverLetter()' style='background:#1a3a6e;border-color:#3a5aae;color:#d0e4ff'>Apply Edit</button>
                </div>
                <div id='eclStatus' style='margin-top:12px;color:#aebcda;font-size:0.82rem;white-space:pre-wrap'></div>
                <div id='eclResultActions' style='display:none;margin-top:12px;gap:10px;justify-content:flex-end;flex-wrap:wrap'>
                    <button onclick='closeEditCoverLetter()'>Close / Cancel</button>
                    <button id='eclOpenDraft' onclick='openEditedCoverLetterDraft()' style='background:#1b2f55;border-color:#4a6fb3;color:#dce9ff'>Open Edited Letter</button>
                    <button id='eclOpenPdf' onclick='openEditedCoverLetterPdf()' style='background:#123c2a;border-color:#2a8f62;color:#d7ffe9'>Open Edited PDF</button>
                    <button id='eclAccept' onclick='acceptCoverLetterChanges()' style='background:#3d2f12;border-color:#a77a2a;color:#fff0c8'>Accept Changes</button>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- Template Preview modal -->
<div id='templatePreviewOverlay' style='display:none;position:fixed;inset:0;background:rgba(0,0,0,.82);z-index:920;overflow-y:auto;padding:16px 10px'>
  <div style='max-width:1120px;margin:0 auto;background:#0d1526;border:1px solid #2a3a5e;border-radius:14px;padding:18px;display:flex;flex-direction:column;gap:12px'>

    <!-- Header -->
    <div style='display:flex;justify-content:space-between;align-items:flex-start;gap:12px'>
      <div>
        <div style='font-weight:700;font-size:1.05rem'>Resume Template Preview</div>
        <div id='tpJobLabel' style='color:#8899bb;font-size:0.82rem;margin-top:3px'></div>
      </div>
      <button onclick='closeTemplatePreviews()' style='background:none;border:none;font-size:1.4rem;color:#8899bb;cursor:pointer;padding:0 4px;flex-shrink:0'>✕</button>
    </div>

    <!-- Template tabs -->
    <div style='display:flex;gap:8px;flex-wrap:wrap'>
      <button id='tpTab-modern'    onclick='switchTemplate("modern")'    class='tp-tab'>Modern</button>
      <button id='tpTab-executive' onclick='switchTemplate("executive")' class='tp-tab'>Executive</button>
      <button id='tpTab-sidebar'   onclick='switchTemplate("sidebar")'   class='tp-tab'>Sidebar</button>
      <button id='tpTab-portfolio' onclick='switchTemplate("portfolio")' class='tp-tab'>Portfolio</button>
    </div>

    <!-- Description strip -->
    <div id='tpDesc' style='font-size:0.82rem;color:#8899bb;min-height:1.2em'></div>

    <!-- Loading bar -->
    <div id='tpLoading' style='display:none;height:3px;background:#1b2943;border-radius:999px;overflow:hidden'>
      <div style='height:100%;width:35%;background:#06b6d4;animation:slide 1.2s linear infinite'></div>
    </div>

    <!-- Preview iframe -->
    <iframe id='tpFrame' src='about:blank' title='Resume template preview'
      style='width:100%;height:72vh;border:1px solid #2a3a5e;border-radius:10px;background:#fff;transition:opacity .15s'
    ></iframe>

    <!-- Footer note -->
    <div style='font-size:0.77rem;color:#556;text-align:right'>
      Preview uses your master resume. Actual export uses the selected optimized resume.
    </div>
  </div>
</div>

<script>
const el = {
  summary: document.getElementById('summary'),
  list: document.getElementById('list'),
  q: document.getElementById('q'),
};
let state = { jobs: [], resume_options: [], optimized_resume_options: [], cover_letter_options: [], total: 0 };
let busy = false;
let busyMessage = '';
let editJobId = null;
let editCoverLetterJobId = null;
let editCoverLetterSourceName = '';
let editCoverLetterDraftName = '';
let editCoverLetterDraftHref = '';
let editCoverLetterPdfHref = '';
let editCoverLetterAccepted = false;

/* ── Template Preview ──────────────────────────────── */
const TEMPLATE_META = {
  modern:    { label: 'Modern',    desc: 'Clean single-column, sans-serif, ATS-friendly. Blue section headers. Standard corporate layout. Best for most SWE roles.' },
  executive: { label: 'Executive', desc: 'Larger serif type, centered header, prominent left-bordered summary. Best for senior, principal, staff, or director roles.' },
  sidebar:   { label: 'Sidebar',   desc: 'Two-column layout. Left sidebar: contact, skills, education (dark navy). Right column: summary, experience, projects.' },
  portfolio: { label: 'Portfolio', desc: 'Projects section appears before experience. GitHub highlighted at top. Green accent. Best for open-source contributors and technical creators.' },
};
let tpCurrentTemplate = 'modern';

function _setActiveTab(name) {
  Object.keys(TEMPLATE_META).forEach(t => {
    const btn = document.getElementById(`tpTab-${t}`);
    if (!btn) return;
    if (t === name) {
      btn.style.background = '#1a3a6e';
      btn.style.borderColor = '#3a5aae';
      btn.style.color = '#d0e4ff';
    } else {
      btn.style.background = '';
      btn.style.borderColor = '';
      btn.style.color = '';
    }
  });
}

function switchTemplate(name) {
  if (!TEMPLATE_META[name]) return;
  tpCurrentTemplate = name;
  _setActiveTab(name);
  document.getElementById('tpDesc').textContent = TEMPLATE_META[name].desc;
  const frame = document.getElementById('tpFrame');
  const loading = document.getElementById('tpLoading');
  frame.style.opacity = '0.35';
  loading.style.display = 'block';
  frame.src = `/dashboard/pipeline/preview-template/${name}`;
}

function openTemplatePreviews(jobId, company, role) {
  const label = (company && role) ? `${company} — ${role}` : 'Master Resume';
  document.getElementById('tpJobLabel').textContent = `Previewing templates for: ${label}`;
  document.getElementById('templatePreviewOverlay').style.display = 'block';
  // Always start on modern; only load if not already showing
  if (tpCurrentTemplate !== 'modern' || document.getElementById('tpFrame').src.includes('about:blank')) {
    switchTemplate('modern');
  } else {
    _setActiveTab('modern');
    document.getElementById('tpDesc').textContent = TEMPLATE_META['modern'].desc;
  }
}

function closeTemplatePreviews() {
  document.getElementById('templatePreviewOverlay').style.display = 'none';
}

(function() {
  const frame = document.getElementById('tpFrame');
  if (frame) {
    frame.addEventListener('load', function() {
      this.style.opacity = '1';
      document.getElementById('tpLoading').style.display = 'none';
    });
  }
  const overlay = document.getElementById('templatePreviewOverlay');
  if (overlay) {
    overlay.addEventListener('click', function(e) {
      if (e.target === this) closeTemplatePreviews();
    });
  }
})();
/* ─────────────────────────────────────────────────── */

function esc(s){ return String(s||'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'); }

async function post(url, payload){
  const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', body: JSON.stringify(payload) });
  const txt = await res.text();
  if(!res.ok){ alert(`Request failed (${res.status})\n${txt}`); throw new Error(txt); }
  try { return JSON.parse(txt); } catch { return { ok: true, raw: txt }; }
}

function openAddJob(){
  document.getElementById('ajCompany').value = '';
  document.getElementById('ajRole').value = '';
  document.getElementById('ajJD').value = '';
  document.getElementById('ajError').style.display = 'none';
  document.getElementById('addJobOverlay').style.display = 'block';
  setTimeout(()=>document.getElementById('ajCompany').focus(), 50);
}
function closeAddJob(){ document.getElementById('addJobOverlay').style.display = 'none'; }
async function submitAddJob(){
  const company = document.getElementById('ajCompany').value.trim();
  const role    = document.getElementById('ajRole').value.trim();
  const jd      = document.getElementById('ajJD').value.trim();
  const errEl   = document.getElementById('ajError');
  if(!company || !role || !jd){
    errEl.textContent = 'Company, role, and job description are all required.';
    errEl.style.display = 'block';
    return;
  }
  const btn = document.getElementById('ajSubmit');
  btn.disabled = true;
  btn.textContent = 'Queueing…';
  errEl.style.display = 'none';
  try {
    await post('/jobs/evaluate', { company, role, job_description: jd, source: 'dashboard_manual' });
    closeAddJob();
    await load();
  } catch(e){
    errEl.textContent = String(e);
    errEl.style.display = 'block';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Queue & Assess';
  }
}
document.getElementById('addJobOverlay').addEventListener('click', function(e){
  if(e.target === this) closeAddJob();
});

function findJob(jobId){ return (state.jobs || []).find(j => Number(j.id) === Number(jobId)); }
function closeEditResume(){ document.getElementById('editResumeOverlay').style.display = 'none'; editJobId = null; }
async function openEditResume(jobId){
    const job = findJob(jobId);
    if(!job) return alert(`Job #${jobId} not found in current page state.`);
    const options = state.optimized_resume_options || [];
    if(!options.length) return alert('No optimized resume .txt files found in Materials. Generate or save a resume first.');
    editJobId = jobId;
    document.getElementById('erJobLabel').textContent = `#${job.id} · ${job.company} · ${job.role}`;
    const sel = document.getElementById('erResume');
    const preferred = job.last_edited_resume || job.suggested_edit_resume || options[0];
    sel.innerHTML = options.map(name => `<option value='${esc(name)}' ${name === preferred ? 'selected' : ''}>${esc(name)}</option>`).join('');
    document.getElementById('erInstructions').value = '';
    document.getElementById('erOutput').value = '';
    document.getElementById('erExportPdf').checked = true;
    document.getElementById('erStatus').textContent = '';
    document.getElementById('editResumeOverlay').style.display = 'block';
    await loadEditResumeSource();
    setTimeout(()=>document.getElementById('erInstructions').focus(), 50);
}
async function loadEditResumeSource(){
    const name = document.getElementById('erResume').value;
    if(!name) return;
    document.getElementById('erSource').value = 'Loading resume…';
    const res = await post('/dashboard/pipeline/read-resume', { resume_name: name });
    document.getElementById('erSource').value = res.content || '';
}
async function submitEditResume(){
    const instructions = document.getElementById('erInstructions').value.trim();
    if(!instructions) return alert('Add edit instructions first.');
    const btn = document.getElementById('erSubmit');
    const status = document.getElementById('erStatus');
    btn.disabled = true;
    btn.textContent = 'Editing…';
    status.textContent = 'Applying edit with the selected resume as source…';
    try {
        const res = await post('/dashboard/pipeline/edit-resume', {
            job_id: editJobId,
            resume_name: document.getElementById('erResume').value,
            instructions,
            output_filename: document.getElementById('erOutput').value.trim(),
            export_pdf: document.getElementById('erExportPdf').checked,
        });
        status.textContent = `Saved: ${res.edited_resume}\n${res.pdf_result || ''}`;
        await load();
    } finally {
        btn.disabled = false;
        btn.textContent = 'Apply Edit';
    }
}
document.getElementById('editResumeOverlay').addEventListener('click', function(e){
    if(e.target === this) closeEditResume();
});

async function cancelEditCoverLetterSession(){
    if(editCoverLetterSourceName && editCoverLetterDraftName && !editCoverLetterAccepted){
        try { await post('/dashboard/pipeline/cancel-cover-letter-edit', { cover_letter_name: editCoverLetterSourceName }); }
        catch(e) { console.warn('Failed to clean cover-letter drafts', e); }
    }
}
async function closeEditCoverLetter(){
    await cancelEditCoverLetterSession();
    document.getElementById('editCoverLetterOverlay').style.display = 'none';
    editCoverLetterJobId = null;
    editCoverLetterSourceName = '';
    editCoverLetterDraftName = '';
    editCoverLetterDraftHref = '';
    editCoverLetterPdfHref = '';
    editCoverLetterAccepted = false;
}
async function openEditCoverLetter(jobId){
    const job = findJob(jobId);
    if(!job) return alert(`Job #${jobId} not found in current page state.`);
    const options = state.cover_letter_options || [];
    if(!options.length) return alert('No cover-letter .txt files found in Materials. Generate a cover letter first.');
    editCoverLetterJobId = jobId;
    document.getElementById('eclJobLabel').textContent = `#${job.id} · ${job.company} · ${job.role}`;
    const sel = document.getElementById('eclCoverLetter');
    const preferred = job.last_edited_cover_letter || job.suggested_edit_cover_letter || options[0];
    sel.innerHTML = options.map(name => `<option value='${esc(name)}' ${name === preferred ? 'selected' : ''}>${esc(name)}</option>`).join('');
    editCoverLetterSourceName = preferred;
    editCoverLetterDraftName = '';
    editCoverLetterDraftHref = '';
    editCoverLetterAccepted = false;
    document.getElementById('eclInstructions').value = '';
    document.getElementById('eclOutput').value = '';
    document.getElementById('eclExportPipeline').value = 'latex';
    document.getElementById('eclExportPdf').checked = true;
    document.getElementById('eclStatus').textContent = '';
    editCoverLetterPdfHref = '';
    document.getElementById('eclResultActions').style.display = 'none';
    document.getElementById('eclOpenDraft').disabled = true;
    document.getElementById('eclOpenPdf').disabled = true;
    document.getElementById('eclAccept').disabled = true;
    document.getElementById('editCoverLetterOverlay').style.display = 'block';
    await loadEditCoverLetterSource();
    setTimeout(()=>document.getElementById('eclInstructions').focus(), 50);
}
async function loadEditCoverLetterSource(){
    const name = document.getElementById('eclCoverLetter').value;
    if(!name) return;
    if(editCoverLetterDraftName && name !== editCoverLetterSourceName) await cancelEditCoverLetterSession();
    editCoverLetterSourceName = name;
    editCoverLetterDraftName = '';
    editCoverLetterDraftHref = '';
    editCoverLetterPdfHref = '';
    editCoverLetterAccepted = false;
    document.getElementById('eclResultActions').style.display = 'none';
    document.getElementById('eclSource').value = 'Loading cover letter…';
    const res = await post('/dashboard/pipeline/read-cover-letter', { cover_letter_name: name });
    document.getElementById('eclSource').value = res.content || '';
}
async function submitEditCoverLetter(){
    const instructions = document.getElementById('eclInstructions').value.trim();
    if(!instructions) return alert('Add edit instructions first.');
    const btn = document.getElementById('eclSubmit');
    const status = document.getElementById('eclStatus');
    btn.disabled = true;
    btn.textContent = 'Editing…';
    status.textContent = 'Applying edit with the selected cover letter as source…';
    editCoverLetterPdfHref = '';
    document.getElementById('eclResultActions').style.display = 'none';
    try {
        const res = await post('/dashboard/pipeline/edit-cover-letter', {
            job_id: editCoverLetterJobId,
            cover_letter_name: editCoverLetterSourceName || document.getElementById('eclCoverLetter').value,
            draft_name: editCoverLetterDraftName,
            instructions,
            output_filename: document.getElementById('eclOutput').value.trim(),
            export_pdf: document.getElementById('eclExportPdf').checked,
            export_pipeline: document.getElementById('eclExportPipeline').value,
        });
        editCoverLetterDraftName = res.draft_name || res.edited_cover_letter || '';
        editCoverLetterDraftHref = res.draft_href || '';
        editCoverLetterPdfHref = res.pdf_href || '';
        document.getElementById('eclSource').value = res.draft_content || document.getElementById('eclSource').value;
        status.textContent = `Draft: ${editCoverLetterDraftName}\nPipeline: ${res.export_pipeline}\n${res.pdf_result || ''}\n\nOriginal file is unchanged until you click Accept Changes.`;
        const draftBtn = document.getElementById('eclOpenDraft');
        const openBtn = document.getElementById('eclOpenPdf');
        const acceptBtn = document.getElementById('eclAccept');
        draftBtn.disabled = !editCoverLetterDraftHref;
        openBtn.disabled = !editCoverLetterPdfHref;
        openBtn.textContent = editCoverLetterPdfHref ? 'Open Edited PDF' : 'No PDF to Open';
        acceptBtn.disabled = !editCoverLetterDraftName;
        document.getElementById('eclResultActions').style.display = 'flex';
        await load();
    } finally {
        btn.disabled = false;
        btn.textContent = 'Apply Edit';
    }
}
function openEditedCoverLetterDraft(){
    if(!editCoverLetterDraftHref) return alert('No edited draft is available for this run.');
    const win = window.open(editCoverLetterDraftHref, '_blank');
    if(win) win.opener = null;
}
function openEditedCoverLetterPdf(){
    if(!editCoverLetterPdfHref) return alert('No edited PDF is available for this run.');
    const win = window.open(editCoverLetterPdfHref, '_blank');
    if(win) win.opener = null;
}
async function acceptCoverLetterChanges(){
    if(!editCoverLetterSourceName || !editCoverLetterDraftName) return alert('No draft is available to accept.');
    const res = await post('/dashboard/pipeline/accept-cover-letter-edit', {
        cover_letter_name: editCoverLetterSourceName,
        draft_name: editCoverLetterDraftName,
    });
    editCoverLetterAccepted = true;
    document.getElementById('eclStatus').textContent = `Accepted changes into: ${res.cover_letter_name}\nBackup: ${res.backup_name}\nTemporary drafts removed: ${res.deleted_drafts}`;
    document.getElementById('eclAccept').disabled = true;
    document.getElementById('eclOpenDraft').disabled = true;
    await load();
}
document.getElementById('editCoverLetterOverlay').addEventListener('click', function(e){
    if(e.target === this) closeEditCoverLetter();
});

function setBusy(on, message=''){
    busy = on;
    busyMessage = message;
    renderBusy();
}

function renderBusy(){
    const old = document.getElementById('busy');
    if(old) old.remove();
    if(!busy) return;
    const node = document.createElement('div');
    node.id = 'busy';
    node.className = 'busy';
    node.innerHTML = `<div>${esc(busyMessage || 'Working...')}</div><div class='progress'><span></span></div>`;
    el.list.parentElement.insertBefore(node, el.list);
}

async function action(jobId, type){
    const personaSel = document.getElementById(`persona-select-${jobId}`);
    const persona = personaSel ? personaSel.value : (state.default_persona || 'default');
    try {
        if(type === 'eval') {
            setBusy(true, `Running assessment for job #${jobId}...`);
            await post('/dashboard/pipeline/evaluate', { job_id: jobId });
        }
        if(type === 'select') {
            setBusy(true, `Saving selected resume for job #${jobId}...`);
            const sel = document.getElementById(`resume-select-${jobId}`);
            await post('/dashboard/pipeline/select-resume', { job_id: jobId, resume_name: sel ? sel.value : '' });
        }
        if(type === 'resume') {
            setBusy(true, `Generating resume for job #${jobId}...`);
            const res = await post('/dashboard/pipeline/generate-resume', { job_id: jobId, persona });
            if(!res?.ok){
                const msg = String(res?.content || 'Resume generation failed.').split('\\n').slice(0, 8).join('\\n');
                alert(`Resume generation did not produce files.\\n\\n${msg}`);
            }
        }
        if(type === 'edit-resume') {
            await openEditResume(jobId);
            return;
        }
        if(type === 'edit-cover-letter') {
            await openEditCoverLetter(jobId);
            return;
        }
        if(type === 'cl-latex') {
            setBusy(true, `Generating cover letter (LaTeX) for job #${jobId}...`);
            const res = await post('/dashboard/pipeline/generate-cover-letter', { job_id: jobId, export_pipeline: 'latex', persona });
            if(!res?.ok){
                const msg = String(res?.content || 'Cover letter generation failed.').split('\\n').slice(0, 10).join('\\n');
                alert(`Cover letter generation did not produce files (likely API rate limit or provider error).\\n\\n${msg}`);
            }
        }
        if(type === 'cl-html') {
            setBusy(true, `Generating cover letter (HTML) for job #${jobId}...`);
            const res = await post('/dashboard/pipeline/generate-cover-letter', { job_id: jobId, export_pipeline: 'html', persona });
            if(!res?.ok){
                const msg = String(res?.content || 'Cover letter generation failed.').split('\\n').slice(0, 10).join('\\n');
                alert(`Cover letter generation did not produce files (likely API rate limit or provider error).\\n\\n${msg}`);
            }
        }
        if(type === 'apply') {
            setBusy(true, `Queueing application for job #${jobId}...`);
            await post('/dashboard/pipeline/queue-apply', { job_id: jobId });
        }
        if(type === 'applied') {
            const note = prompt('Optional application note:', 'Applied manually from dashboard.');
            if(note === null) return;
            setBusy(true, `Marking job #${jobId} applied...`);
            await post('/dashboard/pipeline/mark-applied', { job_id: jobId, notes: note });
        }
        if(type === 'unqueue') {
            setBusy(true, `Resetting job #${jobId} to pending...`);
            await post('/dashboard/pipeline/unqueue', { job_id: jobId });
        }
        if(type === 'remove') {
            if(!confirm(`Remove job #${jobId} from pipeline? This deletes the entry.`)) return;
            setBusy(true, `Removing job #${jobId}...`);
            await post('/dashboard/pipeline/remove', { job_id: jobId });
        }
        await load();
    } finally {
        setBusy(false);
    }
}

function filtered(){
  const q = (el.q.value || '').trim().toLowerCase();
  if(!q) return state.jobs;
  return state.jobs.filter(j => [j.company, j.role, j.status, j.source, j.decision_notes].join(' ').toLowerCase().includes(q));
}

function render(){
  const pending = state.jobs.filter(j => j.status === 'pending').length;
  const evald = state.jobs.filter(j => j.status === 'evaluated').length;
  const added = state.jobs.filter(j => j.status === 'added').length;
    const applied = state.jobs.filter(j => j.status === 'applied').length;
  el.summary.innerHTML = [
    {k:'Queue Total', v:state.total},
    {k:'Pending', v:pending},
    {k:'Evaluated', v:evald},
        {k:'Added', v:added},
        {k:'Applied', v:applied}
  ].map(c => `<article class='card'><div class='k'>${esc(c.k)}</div><div class='v'>${esc(c.v)}</div></article>`).join('');

  const jobs = filtered();
  if(!jobs.length){ el.list.innerHTML = '<div class="empty">No jobs found.</div>'; return; }

  el.list.innerHTML = jobs.map(j => {
    const disabledEval = (j.status === 'added' || j.status === 'applied' || j.status === 'dismissed') ? 'disabled' : '';
    const disabledApply = j.status !== 'evaluated' ? 'disabled' : '';
    const disabledApplied = (j.status === 'applied' || j.status === 'dismissed') ? 'disabled' : '';
    const statusClass = (j.status || '').replace(/[^a-z0-9_-]/g,'-');
    const evalLabel = j.assessed ? 'Re-run Assessment' : 'Run Assessment';
    return `<article class='item'>
      <div class='top'>
        <div>
          <div class='title'>${esc(j.company)} — ${esc(j.role)}</div>
          <div class='meta'>#${esc(j.id)} · ${esc(j.source || 'n/a')} · ${esc(j.added_date || '')}</div>
        </div>
        <span class='status ${statusClass}'>${esc(j.status)}</span>
      </div>
            <div class='detail'><strong>Assessment:</strong> ${j.assessed ? 'run' : 'not run yet'}</div>
            <div class='detail'><strong>Assessment summary:</strong> ${esc(j.assessment_summary || '')}</div>
            <details class='detail detail-box'>
                <summary>Assessment details</summary>
                <pre>${esc(j.assessment_detail || '')}</pre>
            </details>

      ${j.fitment_score ? `<div class='detail'><strong>Fitment score:</strong> ${esc(j.fitment_score)}</div>` : ''}
      ${j.decision_notes ? `<div class='detail'><strong>Notes:</strong> ${esc(j.decision_notes)}</div>` : ''}
      <div class='btnrow'>
        <button onclick='action(${j.id},"eval")' ${disabledEval}>${evalLabel}</button>
        <button onclick='action(${j.id},"resume")'>Generate Resume</button>
                <button onclick='action(${j.id},"edit-resume")'>Edit Resume</button>
        ${state.is_owner ? `<button onclick='action(${j.id},"cl-latex")'>Cover Letter (LaTeX)</button>` : ''}
        <button onclick='action(${j.id},"cl-html")'>Cover Letter (HTML)</button>
            <button onclick='action(${j.id},"edit-cover-letter")'>Edit Cover Letter</button>
        <button onclick='action(${j.id},"apply")' ${disabledApply}>Queue Apply</button>
        <button onclick='action(${j.id},"applied")' ${disabledApplied}>Applied</button>
                <button onclick='action(${j.id},"unqueue")'>Unqueue</button>
                <button class='danger' onclick='action(${j.id},"remove")'>Remove</button>
        <button class='tp-btn' onclick='openTemplatePreviews(${j.id}, "${esc(j.company)}", "${esc(j.role)}")' title='Preview resume in all four visual formats'>Preview Formats</button>
      </div>
    </article>`;
  }).join('');
}

async function load(){
  try {
    const res = await fetch('/dashboard/pipeline/data', { credentials: 'same-origin' });
    if(!res.ok){
      const msg = `Failed to load pipeline data (HTTP ${res.status}). Check server logs.`;
      el.list.innerHTML = `<div class='empty'>${msg}</div>`;
      console.error('[pipeline] data fetch failed:', res.status, res.statusText);
      return;
    }
    let json;
    try {
      json = await res.json();
    } catch(parseErr) {
      el.list.innerHTML = `<div class='empty'>Pipeline data response is not valid JSON. The server may have returned an error page. Check the Console for details.</div>`;
      console.error('[pipeline] JSON parse error — server may be redirecting to login or returning HTML:', parseErr);
      return;
    }
    state = json;
    render();
  } catch(networkErr) {
    el.list.innerHTML = `<div class='empty'>Network error loading pipeline data: ${String(networkErr)}</div>`;
    console.error('[pipeline] network error in load():', networkErr);
  }
}

el.q.addEventListener('input', render);
load();
</script>
"""

    extra_css = """
.bar { display:flex; justify-content:space-between; gap:12px; align-items:center; margin: 8px 0 14px; flex-wrap: wrap; }
.list { display:grid; gap:10px; }
.item { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 14px; }
.top { display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; align-items:baseline; }
.title { font-weight: 650; font-size: 1rem; }
.meta { color: var(--muted); font-size: 0.8rem; margin-top: 4px; }
.status { font-size: 0.8rem; font-weight: 600; border: 1px solid var(--line); border-radius: 999px; padding: 6px 10px; background: #0f1728; color: #dbe8ff; text-transform: lowercase; }
.status.added { border-color: color-mix(in srgb, var(--ok) 45%, var(--line)); color: #d9ffe6; }
.status.applied { border-color: color-mix(in srgb, var(--ok) 65%, var(--line)); color: #bfffd2; background: #0f2418; }
.status.dismissed { border-color: color-mix(in srgb, var(--danger) 45%, var(--line)); color: #ffdede; }
.hint { color: var(--muted); font-size: 0.78rem; }
.busy { background: #0e1628; border:1px solid var(--line); border-radius:10px; padding:10px 12px; margin-bottom:10px; color:#d7e3f8; }
.progress { margin-top:8px; height:6px; border-radius:999px; overflow:hidden; background:#1b2943; }
.progress > span { display:block; height:100%; width:35%; background:var(--accent); animation: slide 1.2s linear infinite; }
@keyframes slide { from { transform: translateX(-120%); } to { transform: translateX(320%); } }
.detail { margin-top: 10px; color: var(--text); font-size: 0.9rem; line-height: 1.45; white-space: pre-wrap; }
.detail-box { background:#0e1628; border:1px solid var(--line); border-radius:10px; padding:8px 10px; }
.detail-box summary { cursor:pointer; color:#c8d8f4; font-weight:600; }
.detail-box pre { margin:8px 0 0; white-space:pre-wrap; font: 0.82rem/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; color:#b8c6df; }
.btnrow { display:flex; flex-wrap: wrap; gap:8px; margin-top:10px; }
button { background: var(--chip); border:1px solid var(--line); color: var(--text); border-radius: 8px; padding: 8px 10px; cursor:pointer; font-size: 0.82rem; }
button:hover { border-color: var(--accent); }
button:disabled { opacity: 0.45; cursor: not-allowed; }
button.danger { border-color: color-mix(in srgb, var(--danger) 55%, var(--line)); color: #ffdede; }
button.tp-btn {
  border-color: color-mix(in srgb, var(--accent) 45%, var(--line));
  color: #a0e8f0;
  background: color-mix(in srgb, var(--accent) 8%, var(--chip));
}
button.tp-btn:hover { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 16%, var(--chip)); }
.tp-tab { font-size: 0.85rem; font-weight: 600; padding: 8px 16px; }
"""

    return HTMLResponse(
        html_page(
            title="Pipeline",
            active_tab="pipeline",
            subtitle="Share-sheet intake → assessment → resume choice → cover letter → queue apply",
            extra_css=extra_css,
            body=body,
        )
    )
