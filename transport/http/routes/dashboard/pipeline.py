"""Pipeline dashboard — queue + assessment + resume choice + cover letter + apply."""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Literal
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from lib import config
from lib.io import _load_json, _load_master_context, _now, _save_json
from lib.openai_calls import create_chat_completion
from services import JobAnalysisService, ResumeService
from tools.export import export_cover_letter_pdf, export_resume_pdf
from tools.generate import _extract_cover_letter_body, _sanitize_cover_letter_output
from tools.job_hunt import log_application_event, update_application
from tools.latex_export import generate_cover_letter_latex
from tools.resume import save_cover_letter_txt, save_resume_txt
from transport.http.auth import require_api_key
from .shared import html_page

router = APIRouter(dependencies=[Depends(require_api_key)])

_COMPACT_TOKEN_RE = r"[^a-z0-9]+"


class _JobActionRequest(BaseModel):
    job_id: int = Field(..., ge=1)
    persona: str | None = None
    output_filename: str = ""
    export_pipeline: Literal["html", "latex"] = "latex"
    notes: str = ""
    resume_name: str = ""


class _ResumeReadRequest(BaseModel):
    resume_name: str = Field(..., min_length=1)


class _ResumeEditRequest(BaseModel):
    job_id: int = Field(..., ge=1)
    resume_name: str = Field(..., min_length=1)
    instructions: str = Field(..., min_length=3)
    output_filename: str = ""
    export_pdf: bool = True


class _CoverLetterReadRequest(BaseModel):
    cover_letter_name: str = Field(..., min_length=1)


class _CoverLetterEditRequest(BaseModel):
    job_id: int = Field(..., ge=1)
    cover_letter_name: str = Field(..., min_length=1)
    draft_name: str = ""
    instructions: str = Field(..., min_length=3)
    output_filename: str = ""
    export_pdf: bool = True
    export_pipeline: Literal["html", "latex"] = "latex"


class _CoverLetterAcceptRequest(BaseModel):
    cover_letter_name: str = Field(..., min_length=1)
    draft_name: str = Field(..., min_length=1)


class _CoverLetterCancelRequest(BaseModel):
    cover_letter_name: str = Field(..., min_length=1)


def _load_queue_jobs() -> list[dict]:
    data = _load_json(config.JOB_QUEUE_FILE, {"jobs": []})
    jobs = data.get("jobs", [])
    return sorted(jobs, key=lambda j: j.get("added_date", ""), reverse=True)


def _find_job(job_id: int) -> dict:
    jobs = _load_queue_jobs()
    for job in jobs:
        if int(job.get("id", 0)) == int(job_id):
            return job
    raise HTTPException(status_code=404, detail=f"Job id {job_id} not found")


def _update_job(job_id: int, mutate) -> dict:
    data = _load_json(config.JOB_QUEUE_FILE, {"jobs": []})
    jobs = data.get("jobs", [])
    for job in jobs:
        if int(job.get("id", 0)) == int(job_id):
            mutate(job)
            _save_json(config.JOB_QUEUE_FILE, data)
            return job
    raise HTTPException(status_code=404, detail=f"Job id {job_id} not found")


def _list_resume_options() -> list[str]:
    target_names = ["Frank_MacBride_Resume.pdf", "Frank_MacBride_Resume_MODERN.pdf"]

    # Resume choices are intentionally locked to exactly these two PDFs.
    latex_dir = config.LATEX_RESUME_DIR
    if not latex_dir:
        return target_names

    output_dir = latex_dir / "output"
    available = {p.name for p in output_dir.glob("*.pdf")} if output_dir.exists() else set()
    ordered = [name for name in target_names if name in available]
    return ordered or target_names


def _optimized_resume_dir() -> Path:
    return config.get_active_workspace_folder() / config._cfg.get("optimized_resumes_dir", "01-Current-Optimized")


def _list_optimized_resume_options() -> list[str]:
    directory = _optimized_resume_dir()
    if not directory.exists():
        return []
    return [
        f.name for f in sorted(
            directory.glob("*.txt"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if "MASTER" not in f.name
    ]


def _cover_letter_dir() -> Path:
    return config.get_active_workspace_folder() / config._cfg.get("cover_letters_dir", "02-Cover-Letters")


def _list_cover_letter_options() -> list[str]:
    directory = _cover_letter_dir()
    if not directory.exists():
        return []
    return [
        f.name for f in sorted(
            directory.glob("*.txt"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if "MASTER" not in f.name
    ]


def _resolve_optimized_resume(filename: str) -> Path:
    directory = _optimized_resume_dir()
    root = directory.resolve()
    target = (directory / filename).resolve()
    if root != target.parent and root not in target.parents:
        raise HTTPException(status_code=404, detail="Invalid resume path")
    if target.suffix.lower() != ".txt":
        raise HTTPException(status_code=400, detail="Only optimized resume .txt files can be edited")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"Resume not found: {filename}")
    return target


def _resolve_cover_letter(filename: str) -> Path:
    directory = _cover_letter_dir()
    root = directory.resolve()
    target = (directory / filename).resolve()
    if root != target.parent and root not in target.parents:
        raise HTTPException(status_code=404, detail="Invalid cover-letter path")
    if target.suffix.lower() != ".txt":
        raise HTTPException(status_code=400, detail="Only cover-letter .txt files can be edited")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"Cover letter not found: {filename}")
    return target


def _resolve_cover_letter_draft(filename: str) -> Path:
    directory = _cover_letter_dir()
    root = directory.resolve()
    target = (directory / filename).resolve()
    if root != target.parent and root not in target.parents:
        raise HTTPException(status_code=404, detail="Invalid cover-letter draft path")
    if target.suffix.lower() != ".tmp":
        raise HTTPException(status_code=400, detail="Only cover-letter .tmp draft files can be read")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"Cover-letter draft not found: {filename}")
    return target


def _cover_letter_draft_pattern(source_name: str) -> re.Pattern:
    source_stem = re.escape(Path(source_name).stem)
    return re.compile(rf"^{source_stem}\.edit(?P<num>\d+)\.tmp$")


def _list_cover_letter_drafts(source_name: str) -> list[Path]:
    directory = _cover_letter_dir()
    if not directory.exists():
        return []
    pattern = _cover_letter_draft_pattern(source_name)
    drafts = [p for p in directory.glob(f"{Path(source_name).stem}.edit*.tmp") if pattern.match(p.name)]

    def draft_number(path: Path) -> int:
        match = pattern.match(path.name)
        return int(match.group("num")) if match else 0

    return sorted(drafts, key=draft_number)


def _next_cover_letter_draft_path(source_name: str) -> Path:
    directory = _cover_letter_dir()
    directory.mkdir(parents=True, exist_ok=True)
    pattern = _cover_letter_draft_pattern(source_name)
    nums = [int(m.group("num")) for p in _list_cover_letter_drafts(source_name) if (m := pattern.match(p.name))]
    next_num = (max(nums) + 1) if nums else 1
    return directory / f"{Path(source_name).stem}.edit{next_num}.tmp"


def _delete_cover_letter_drafts(source_name: str) -> int:
    deleted = 0
    for draft in _list_cover_letter_drafts(source_name):
        draft.unlink(missing_ok=True)
        deleted += 1
    return deleted


def _suggest_optimized_resume_for_job(job: dict, options: list[str]) -> str:
    if not options:
        return ""
    last = (job.get("last_edited_resume") or "").strip()
    if last in options:
        return last

    haystacks = [job.get("company", ""), job.get("role", "")]
    tokens = [
        re.sub(_COMPACT_TOKEN_RE, "", token.lower())
        for text in haystacks
        for token in re.findall(r"[A-Za-z0-9]+", text)
        if len(token) >= 4
    ]
    for name in options:
        compact = re.sub(_COMPACT_TOKEN_RE, "", name.lower())
        if any(token and token in compact for token in tokens):
            return name
    return options[0]


def _suggest_cover_letter_for_job(job: dict, options: list[str]) -> str:
    if not options:
        return ""
    last = (job.get("last_edited_cover_letter") or "").strip()
    if last in options:
        return last

    haystacks = [job.get("company", ""), job.get("role", "")]
    tokens = [
        re.sub(_COMPACT_TOKEN_RE, "", token.lower())
        for text in haystacks
        for token in re.findall(r"[A-Za-z0-9]+", text)
        if len(token) >= 4
    ]
    for name in options:
        compact = re.sub(_COMPACT_TOKEN_RE, "", name.lower())
        if any(token and token in compact for token in tokens):
            return name
    return options[0]


def _resume_edit_output_name(source_name: str, company: str, role: str, output_filename: str = "") -> str:
    if output_filename.strip():
        name = output_filename.strip()
        return name if name.endswith(".txt") else f"{name}.txt"

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    source_stem = Path(source_name).stem
    raw_suffix = f"{company}_{role}".strip("_") or "Edited"
    suffix = re.sub(r"[^A-Za-z0-9]+", "_", raw_suffix).strip("_")
    return f"{source_stem} - Edited {suffix}_{stamp}.txt"


def _cover_letter_edit_output_name(source_name: str, company: str, role: str, output_filename: str = "") -> str:
    if output_filename.strip():
        name = output_filename.strip()
        return name if name.endswith(".txt") else f"{name}.txt"

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    source_stem = Path(source_name).stem
    raw_suffix = f"{company}_{role}".strip("_") or "Edited"
    suffix = re.sub(r"[^A-Za-z0-9]+", "_", raw_suffix).strip("_")
    return f"{source_stem} - Edited {suffix}_{stamp}.txt"


def _build_resume_edit_messages(
    *,
    company: str,
    role: str,
    job_description: str,
    current_resume: str,
    instructions: str,
) -> list[dict]:
    system = (
        "You are editing an existing resume, not regenerating from scratch. "
        "Preserve the resume's structure, section order, formatting conventions, contact block, "
        "and verified metrics unless the edit instructions explicitly say otherwise. "
        "Apply only the requested changes. Do not invent employers, dates, tools, or metrics. "
        "Output ONLY the full revised resume text. No markdown fences, no commentary."
    )
    user = "\n\n".join([
        f"TARGET COMPANY: {company}",
        f"TARGET ROLE: {role}",
        f"JOB DESCRIPTION CONTEXT:\n{job_description[:5000]}",
        f"CURRENT RESUME TEXT:\n{current_resume}",
        f"EDIT INSTRUCTIONS:\n{instructions}",
        "Return the complete revised resume text only.",
    ])
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _build_cover_letter_edit_messages(
    *,
    company: str,
    role: str,
    job_description: str,
    current_cover_letter: str,
    instructions: str,
) -> list[dict]:
    system = (
        "You are editing an existing cover letter, not regenerating from scratch. "
        "Preserve Frank's plainspoken voice, the current contact block if present, the salutation, "
        "and the 4-paragraph body structure unless the edit instructions explicitly say otherwise. "
        "Apply only the requested changes. Do not invent employers, dates, tools, metrics, or claims. "
        "Do not add a date block; the PDF template owns the printed date and signature. "
        "Output ONLY the full revised cover-letter text. No markdown fences, no commentary."
    )
    user = "\n\n".join([
        f"TARGET COMPANY: {company}",
        f"TARGET ROLE: {role}",
        f"JOB DESCRIPTION CONTEXT:\n{job_description[:5000]}",
        f"CURRENT COVER LETTER TEXT:\n{current_cover_letter}",
        f"EDIT INSTRUCTIONS:\n{instructions}",
        "Return the complete revised cover-letter text only.",
    ])
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _strip_model_wrapper(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def _material_href_for_pdf(path: Path | str | None) -> str:
    if not path:
        return ""
    pdf_path = Path(path)
    folder_key_by_name = {
        config._cfg.get("cover_letter_pdfs_dir", "09-Cover-Letter-PDFs"): "cover_letter_pdfs",
        config._cfg.get("cover_letters_dir", "02-Cover-Letters"): "cover_letters",
        "03-Resume-PDFs": "resume_pdfs",
    }
    folder_key = folder_key_by_name.get(pdf_path.parent.name)
    if not folder_key:
        return ""
    return f"/dashboard/materials/file/{folder_key}/{quote(pdf_path.name, safe='')}"


def _draft_href(path: Path | str | None) -> str:
    if not path:
        return ""
    return f"/dashboard/pipeline/cover-letter-draft/{quote(Path(path).name, safe='')}"


def _pdf_path_from_export_result(result: str) -> Path | None:
    match = re.search(r"PDF exported:\s*(.+)$", result or "")
    if not match:
        return None
    return Path(match.group(1).strip())


def _recommend_resume(role: str, jd: str, options: list[str]) -> str:
    if not options:
        return "Generate new resume"

    text = f"{role}\n{jd}".lower()
    ai_focus = any(
        kw in text
        for kw in (
            "ai",
            "llm",
            "rag",
            "agent",
            "machine learning",
            "generative",
            "copilot",
            "prompt",
        )
    )

    modern = next((x for x in options if "modern" in x.lower()), None)
    classic = next((x for x in options if "modern" not in x.lower()), None)

    if ai_focus and modern:
        return modern
    if classic:
        return classic
    return options[0]


def _fitment_preview(text: str) -> str:
    if not text:
        return ""
    text = _normalize_fitment_context(text)
    # Prefer the first non-empty lines after the assessment header.
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    body = []
    for ln in lines:
        ln_upper = ln.upper()
        if (
            "FITMENT ASSESSMENT" in ln_upper
            or ln.startswith("✓")
            or ln.startswith("tokens:")
            or "Saved job assessment" in ln
        ):
            continue
        body.append(ln)
        if len(body) >= 4:
            break
    return " ".join(body)[:500]


def _normalize_fitment_context(text: str) -> str:
    """Strip wrapper lines and keep the structured assessment body.

    run_job_assessment returns a wrapper (status + token/cost + saved path)
    followed by the actual markdown assessment. For dashboard display, keep
    the markdown starting at "## FITMENT SCORE" when present.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return ""

    marker = "## FITMENT SCORE"
    idx = cleaned.find(marker)
    if idx >= 0:
        return cleaned[idx:].strip()

    return cleaned


def _extract_md_section(text: str, heading: str) -> str:
    """Extract markdown section body for a heading like 'FITMENT SCORE'."""
    if not text:
        return ""
    pattern = re.compile(
        rf"^##\s*{re.escape(heading)}\s*$\n(?P<body>.*?)(?=^##\s+|\Z)",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(text)
    return (m.group("body") if m else "").strip()


def _extract_bullets(section_text: str, limit: int = 2) -> list[str]:
    if not section_text:
        return []
    lines = []
    for raw in section_text.splitlines():
        ln = raw.strip()
        if not ln:
            continue
        if ln.startswith(("- ", "* ", "• ")):
            lines.append(ln[2:].strip())
    return lines[:limit]


def _first_sentence(text: str, max_len: int = 240) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return ""
    m = re.search(r"([^.?!]+[.?!])", t)
    s = (m.group(1) if m else t).strip()
    return s[:max_len]


def _signal_line(role: str, jd: str) -> str:
    text = f"{role}\n{jd}".lower()
    signals = {
        "ai/llm": ["llm", "openai", "rag", "agent", "copilot", "prompt", "semantic kernel", "langchain", "llamaindex"],
        "backend": ["python", "java", "node", "api", "microservice", "backend", "distributed"],
        "cloud/platform": ["aws", "azure", "gcp", "kubernetes", "docker", "terraform", "ci/cd", "infrastructure"],
        "frontend": ["react", "typescript", "javascript", "frontend", "ui"],
    }
    hit_counts = sorted(
        ((sum(1 for kw in kws if kw in text), label) for label, kws in signals.items()),
        reverse=True,
    )
    top_hits = [label for count, label in hit_counts if count][:3]
    return ", ".join(top_hits) if top_hits else "no strong keyword signal"


def _is_ai_focused(role: str, jd: str) -> bool:
    text = f"{role}\n{jd}".lower()
    return any(_contains_keyword(text, kw) for kw in _AI_ROLE_KEYWORDS)


_AI_ROLE_KEYWORDS = (
    "ai",
    "llm",
    "rag",
    "agent",
    "machine learning",
    "generative",
    "copilot",
    "prompt",
    "model context protocol",
    "mcp",
)


def _contains_keyword(text: str, keyword: str) -> bool:
    if " " in keyword or "/" in keyword or "-" in keyword:
        return keyword in text
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def _ai_evidence_from_master(limit: int = 4) -> list[str]:
    """Return high-signal AI platform evidence from the master resume.

    The LLM assessment can underweight side-project/platform evidence. The
    dashboard should still surface concrete MCP/RAG/LangGraph/OpenAI evidence
    when the queued role is AI-focused.
    """
    try:
        master = _load_master_context()
    except Exception:
        return []

    keywords = (
        "model context protocol",
        "mcp",
        "fastmcp",
        "rag",
        "semantic search",
        "openai api",
        "langgraph",
        "vector",
        "embedding",
        "github copilot",
        "claude ai",
        "ai-assisted",
        "ai tool adoption",
    )
    evidence: list[str] = []
    for raw in master.splitlines():
        line = re.sub(r"\s+", " ", raw).strip().lstrip("•- ").strip()
        if not line:
            continue
        lower = line.lower()
        if any(_contains_keyword(lower, keyword) for keyword in keywords):
            evidence.append(line)
        if len(evidence) >= limit:
            break
    return evidence


def _ai_assessment_caveat(role: str, jd: str, fitment_context: str) -> str:
    if not _is_ai_focused(role, jd):
        return ""
    lower = fitment_context.lower()
    contradiction = any(
        phrase in lower
        for phrase in (
            "lacks direct ai platform experience",
            "lack of direct ai platform experience",
            "no explicit experience in building or maintaining ai platforms",
            "limited machine learning exposure",
        )
    )
    evidence = _ai_evidence_from_master()
    if not evidence:
        return ""
    prefix = "AI evidence from resume"
    if contradiction:
        prefix = "AI evidence the assessment underweighted"
    return f"{prefix}: " + " | ".join(evidence)


def _assessment_summary(status: str, score: str, signal_line: str) -> str:
    if score:
        return f"Fitment score: {score} • signal: {signal_line}"
    if status == "pending":
        return f"Not evaluated yet • signal pre-read: {signal_line}"
    if status == "evaluated":
        return f"Evaluated • signal: {signal_line}"
    return f"Status: {status} • signal: {signal_line}"


def _next_action_for_recommendation(recommendation: str) -> str:
    if not recommendation:
        return "Run assessment to generate recommendation."
    rec_l = recommendation.lower()
    if "apply aggressively" in rec_l:
        return "Queue apply now, then tailor resume bullets to the top 1-2 strengths."
    if "caveat" in rec_l:
        return "Apply with caveats: address top risk in cover letter paragraph 2."
    if "do not apply" in rec_l:
        return "Do not queue apply; keep notes and move this role to dismissed."
    return "Run assessment to generate recommendation."


def _source_url_from_jd(jd: str) -> str:
    source_url_match = re.search(r"https?://\S+", jd)
    return source_url_match.group(0) if source_url_match else "No source URL found in JD."


def _synthesize_assessment(j: dict) -> tuple[str, str]:
    """Return (summary, detail) synthesized from stored queue data."""
    status = (j.get("status") or "pending").lower()
    score = (j.get("fitment_score") or "").strip()
    notes = (j.get("decision_notes") or "").strip()
    jd = (j.get("jd") or "").strip()
    fitment_context = _normalize_fitment_context((j.get("fitment_context") or "").strip())
    role = j.get("role", "")
    signal_line = _signal_line(role, jd)
    summary = _assessment_summary(status, score, signal_line)
    ai_caveat = _ai_assessment_caveat(role, jd, fitment_context)

    fitment_summary = _fitment_preview(fitment_context)
    score_section = _extract_md_section(fitment_context, "FITMENT SCORE")
    recommendation_section = _extract_md_section(fitment_context, "RECOMMENDATION")
    strong_matches = _extract_bullets(_extract_md_section(fitment_context, "STRONG MATCHES"), limit=2)
    gaps_risks = _extract_bullets(_extract_md_section(fitment_context, "GAPS / RISKS"), limit=2)

    effective_score = score or _first_sentence(score_section, max_len=32)
    recommendation = _first_sentence(recommendation_section, max_len=220)
    next_action = _next_action_for_recommendation(recommendation)

    short_notes = re.sub(r"\s+", " ", notes)[:450] if notes else "No decision notes saved."

    strengths_line = " | ".join(strong_matches) if strong_matches else "No extracted strengths."
    risks_line = " | ".join(gaps_risks) if gaps_risks else "No extracted risks."

    detail = "\n".join([
        f"Status: {status}",
        f"Fitment score: {effective_score or 'n/a'}",
        f"Signal tags: {signal_line}",
        f"Recommendation: {recommendation or 'No recommendation extracted.'}",
        f"Top strengths: {strengths_line}",
        f"Top risks: {risks_line}",
        f"AI platform evidence: {ai_caveat or 'No AI-specific evidence surfaced for this role.'}",
        f"Next action: {next_action}",
        f"Fitment context preview: {fitment_summary or 'No stored fitment context.'}",
        f"Notes: {short_notes}",
        f"Source: {_source_url_from_jd(jd)}",
    ])
    return summary, detail


def _pipeline_payload() -> dict:
    jobs = _load_queue_jobs()
    resume_options = _list_resume_options()
    optimized_resume_options = _list_optimized_resume_options()
    cover_letter_options = _list_cover_letter_options()

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


@router.post("/pipeline/generate-cover-letter", responses={404: {"description": "Job id not found"}})
async def pipeline_generate_cover_letter(req: _JobActionRequest) -> JSONResponse:
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
        model=model or config._cfg.get("openai_model", "gpt-4o"),
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
        model=model or config._cfg.get("openai_model", "gpt-4o"),
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
            const res = await post('/dashboard/pipeline/generate-resume', { job_id: jobId });
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
            const res = await post('/dashboard/pipeline/generate-cover-letter', { job_id: jobId, export_pipeline: 'latex' });
            if(!res?.ok){
                const msg = String(res?.content || 'Cover letter generation failed.').split('\\n').slice(0, 10).join('\\n');
                alert(`Cover letter generation did not produce files (likely API rate limit or provider error).\\n\\n${msg}`);
            }
        }
        if(type === 'cl-html') {
            setBusy(true, `Generating cover letter (HTML) for job #${jobId}...`);
            const res = await post('/dashboard/pipeline/generate-cover-letter', { job_id: jobId, export_pipeline: 'html' });
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
      <div class='detail'><strong>Recommended resume:</strong> ${esc(j.recommended_resume)} <span class='hint'>(auto-picked from current resume output set)</span></div>
            <div class='detail'>
                <strong>Selected resume:</strong>
                <select id='resume-select-${j.id}' style='margin-left:8px;background:#0e1628;color:#e6edf7;border:1px solid #23324d;border-radius:8px;padding:6px;'>
                    ${state.resume_options.map(r => `<option value='${esc(r)}' ${(j.selected_resume ? j.selected_resume === r : j.recommended_resume === r) ? 'selected' : ''}>${esc(r)}</option>`).join('')}
                </select>
            </div>
      ${j.fitment_score ? `<div class='detail'><strong>Fitment score:</strong> ${esc(j.fitment_score)}</div>` : ''}
      ${j.decision_notes ? `<div class='detail'><strong>Notes:</strong> ${esc(j.decision_notes)}</div>` : ''}
      <div class='btnrow'>
        <button onclick='action(${j.id},"eval")' ${disabledEval}>${evalLabel}</button>
                <button onclick='action(${j.id},"select")'>Use Existing</button>
        <button onclick='action(${j.id},"resume")'>Generate Resume</button>
                <button onclick='action(${j.id},"edit-resume")'>Edit Resume</button>
        <button onclick='action(${j.id},"cl-latex")'>Cover Letter (LaTeX)</button>
        <button onclick='action(${j.id},"cl-html")'>Cover Letter (HTML)</button>
            <button onclick='action(${j.id},"edit-cover-letter")'>Edit Cover Letter</button>
        <button onclick='action(${j.id},"apply")' ${disabledApply}>Queue Apply</button>
        <button onclick='action(${j.id},"applied")' ${disabledApplied}>Applied</button>
                <button onclick='action(${j.id},"unqueue")'>Unqueue</button>
                <button class='danger' onclick='action(${j.id},"remove")'>Remove</button>
      </div>
    </article>`;
  }).join('');
}

async function load(){
  const res = await fetch('/dashboard/pipeline/data', { credentials: 'same-origin' });
  if(!res.ok){ el.list.innerHTML = `<div class='empty'>Failed to load (${res.status})</div>`; return; }
  state = await res.json();
  render();
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
