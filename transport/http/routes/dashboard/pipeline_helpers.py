"""Pipeline dashboard — data-access helpers, business logic, and request models.

Extracted from pipeline.py to keep the route module focused on HTTP handling.
All symbols here are imported back into pipeline.py so existing code is unaffected.
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Literal
import re
from urllib.parse import quote

from fastapi import HTTPException
from pydantic import BaseModel, Field

from lib import config
from lib.io import _load_json, _load_master_context, _save_json

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


