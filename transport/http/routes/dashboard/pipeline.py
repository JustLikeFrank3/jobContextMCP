"""Pipeline dashboard — queue + assessment + resume choice + cover letter + apply."""
from __future__ import annotations

from pathlib import Path
from typing import Literal
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from lib import config
from lib.io import _load_json, _load_master_context, _now, _save_json
from services import JobAnalysisService, ResumeService
from tools.job_hunt import log_application_event, update_application
from transport.http.auth import require_api_key
from .shared import html_page

router = APIRouter(dependencies=[Depends(require_api_key)])


class _JobActionRequest(BaseModel):
    job_id: int = Field(..., ge=1)
    persona: str | None = None
    output_filename: str = ""
    export_pipeline: Literal["html", "latex"] = "latex"
    notes: str = ""
    resume_name: str = ""


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
        })

    return {
        "total": len(payload_jobs),
        "resume_options": resume_options,
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

<script>
const el = {
  summary: document.getElementById('summary'),
  list: document.getElementById('list'),
  q: document.getElementById('q'),
};
let state = { jobs: [], resume_options: [], total: 0 };
let busy = false;
let busyMessage = '';

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
        <button onclick='action(${j.id},"cl-latex")'>Cover Letter (LaTeX)</button>
        <button onclick='action(${j.id},"cl-html")'>Cover Letter (HTML)</button>
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
