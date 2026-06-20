"""
AI-powered resume and cover letter generation — v4.1

generate_resume(company, role, job_description)
generate_cover_letter(company, role, job_description)

If `openai_api_key` is set in config.json, these tools make a direct OpenAI API
call, then auto-save the .txt and export the PDF — returning the finished PDF path.

If the key is not configured, they return a fully-structured context package with
detailed format instructions so the orchestrating AI (Copilot / Claude) can write
the content and then call save_resume_txt / export_resume_pdf.

Model used: config.json `openai_model` key (default: gpt-4o-mini).
"""

import re

from lib import config
from lib.io import _load_master_context
from lib.openai_calls import create_chat_completion
from lib.story_retrieval import (
    RetrievalDiagnostics,
    estimate_tokens,
    format_stories,
    retrieve_stories,
)
from tools.fitment import get_customization_strategy
from tools.interviews import get_interview_context
from tools.context import get_personal_context
from tools.tone import get_tone_profile, get_tone_profile_budgeted, get_cover_letter_tone_profile_budgeted
from tools.resume import save_resume_txt, save_cover_letter_txt
from tools.generate_prompts import (
    COVER_LETTER_HOOK_TAGS,
    COMPANY_HOOK_TAGS,
    RESUME_FORMAT_SPEC,
    COVER_LETTER_FORMAT_SPEC,
    RESUME_SYSTEM,
    COVER_LETTER_SYSTEM,
)

# Back-compat aliases (private names used internally throughout this module)
_COVER_LETTER_HOOK_TAGS = COVER_LETTER_HOOK_TAGS
_COMPANY_HOOK_TAGS = COMPANY_HOOK_TAGS
_RESUME_FORMAT_SPEC = RESUME_FORMAT_SPEC
_COVER_LETTER_FORMAT_SPEC = COVER_LETTER_FORMAT_SPEC
_RESUME_SYSTEM = RESUME_SYSTEM
_COVER_LETTER_SYSTEM = COVER_LETTER_SYSTEM


def _chat_completion_create(client, **kwargs):
    return create_chat_completion(client, **kwargs)

_NO_PERSONAL_STORIES = "No personal stories found"
_PERSONAL_CONTEXT_HEADER = "──── PERSONAL CONTEXT ────\n"



def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())

def _story_has_company_hook_tags(story: dict) -> bool:
    tags = {_slug(str(t)) for t in (story.get("tags") or [])}
    hook_tags = {_slug(t) for t in _COMPANY_HOOK_TAGS}
    return bool(tags & hook_tags)

def _story_matches_company(story: dict, company: str) -> bool:
    company_slug = _slug(company)
    if not company_slug:
        return False
    company_terms = {_slug(part) for part in re.split(r"\s+", company) if len(part) > 2}
    fields = [story.get("title", ""), story.get("story", "")]
    fields.extend(str(t) for t in (story.get("tags") or []))
    haystack = _slug(" ".join(fields))
    return company_slug in haystack or any(term and term in haystack for term in company_terms)

def _filter_cross_company_hook_stories(stories: list[dict], company: str) -> tuple[list[dict], bool]:
    """Reject brand/company hooks that belong to a different employer.

    A Home Depot childhood story is valid for Home Depot and poisonous for
    Workday. Project/leadership stories can still pass through; company-affinity
    stories require an exact company match.

    Exception: stories tagged 'ai_role_hook' are intentionally cross-company
    origin stories (e.g. Uncle Roy / Intellicorp) meant to serve as P1 hooks
    for any AI role regardless of target company. They always pass through.
    """
    kept: list[dict] = []
    rejected_any = False
    for story in stories:
        tags = {t.lower() for t in story.get("tags", [])}
        if "ai_role_hook" in tags:
            kept.append(story)
            continue
        if _story_has_company_hook_tags(story) and not _story_matches_company(story, company):
            rejected_any = True
            continue
        kept.append(story)
    return kept, rejected_any


def _role_is_compatible(candidate: str, target: str) -> bool:
    candidate_l = (candidate or "").strip().lower()
    target_l = (target or "").strip().lower()
    return candidate_l == target_l or target_l in candidate_l or candidate_l in target_l


def _matching_assessment_jobs(jobs: list[dict], company: str, role: str) -> list[dict]:
    company_l = (company or "").strip().lower()
    matches = []
    for job in jobs:
        if str(job.get("company") or "").strip().lower() != company_l:
            continue
        if not _role_is_compatible(str(job.get("role") or ""), role):
            continue
        if str(job.get("fitment_context") or "").strip():
            matches.append(job)
    return matches



# ── HELPERS ────────────────────────────────────────────────────────────────────

def _openai_client():
    """Return an OpenAI client using whichever provider is configured (openai or ollama)."""
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
        return str(model or config.get_config_value("openai_model", "gpt-4o-mini"))
    except Exception:
        return str(config.get_config_value("openai_model", "gpt-4o-mini"))


def _portfolio_metrics_block() -> str:
    """Return live/stored GitHub metrics for prompt grounding.

    Clone/view counts drift constantly and the master resume can lag behind.
    Generation prompts should treat this block as the source of truth for
    portfolio traffic numbers and ignore stale clone counts elsewhere.
    """
    try:
        from tools.github import get_portfolio_metrics

        metrics = get_portfolio_metrics().strip()
    except Exception:
        return ""

    if not metrics or metrics.startswith("No portfolio metrics recorded yet"):
        return ""
    if metrics.startswith("⚠"):
        return ""
    return (
        "GITHUB PORTFOLIO METRICS (source of truth for clone/view counts; "
        "override stale clone counts in the master resume):\n"
        f"{metrics}"
    )


def _assessment_context_block(company: str, role: str) -> str:
    """Return the latest queued fitment assessment for this company/role.

    Cover letters should be grounded first in structured assessment evidence,
    then optionally in personal stories. This prevents story retrieval from
    forcing a weak or wrong company-affinity hook.
    """
    try:
        from lib.io import _load_json

        data = _load_json(config.JOB_QUEUE_FILE, {"jobs": []})
    except Exception:
        return ""

    matches = _matching_assessment_jobs(data.get("jobs", []) or [], company, role)
    if not matches:
        return ""
    matches.sort(key=lambda j: str(j.get("added_date") or ""), reverse=True)
    job = matches[0]
    ctx = str(job.get("fitment_context") or "").strip()
    if len(ctx) > 3500:
        ctx = ctx[:3500] + "\n[assessment truncated for prompt budget]"
    return (
        "STRUCTURED FITMENT ASSESSMENT (primary cover-letter evidence; use before stories):\n"
        f"Status: {job.get('status', '')}\n"
        f"Fitment score: {job.get('fitment_score') or 'see assessment'}\n"
        f"{ctx}"
    )


def _is_ai_role(role: str, job_description: str) -> bool:
    text = f"{role}\n{job_description}".lower()
    return bool(re.search(
        r"\b(ai|llm|rag|copilot|mcp|agent|agents|agentic|prompt|prompts)\b"
        r"|machine learning|generative|model context protocol",
        text,
    ))


def _cover_letter_narrative_plan(company: str, role: str, job_description: str) -> str:
    """Hard narrative contract for cover letters.

    The LLM tends to satisfy metric requirements by dumping every good artifact.
    This plan forces one coherent spine and keeps current projects out of the
    past tense.
    """
    base = [
        "COVER LETTER NARRATIVE PLAN (follow this before selecting bullets):",
        "- Write one coherent story, not a catalog of achievements.",
        "- Use no more than one primary project in Paragraph 2 and no more than three supporting artifacts in Paragraph 3.",
        "- Do not repeat the same evidence in multiple paragraphs.",
        "- GitHub traffic phrasing must be natural: say 'currently shows X clones in the last 14 days' or 'has X clones in the last 14 days'; do not say 'cloned X times'.",
        "- Avoid sweeping alignment claims like 'aligns perfectly'; name the actual engineering overlap instead.",
    ]
    if _is_ai_role(role, job_description):
        base.extend([
            f"- Narrative spine for {company}: current AI platform builder with production platform instincts.",
            "- Paragraph 1: FIRST check PERSONAL CONTEXT. If it contains a story explicitly marked 'PRIMARY COVER LETTER HOOK' tied to this company, use that story verbatim in the candidate's plain voice — concrete, understated, no inspirational gloss. "
            "SECOND: if no company hook exists, look for a story tagged 'PRIMARY COVER LETTER HOOK (AI ROLE — cross-company origin story)' in PERSONAL CONTEXT and use it as the Para 1 hook. "
            "Write it in first person; if it references another person, identify their relationship clearly the first time. "
            "In Paragraph 1, refer to any primary AI project generically ('the server', 'the platform', 'that project') if it will be named in Paragraph 2. "
            "ONLY IF no hook is present in PERSONAL CONTEXT: open with a professional angle grounded in what AI tools actually need to be production-ready.",
            "- Paragraph 2: use the candidate's primary AI/platform project from the master resume as the ownership story. Name it once, then use 'the server' or 'the project'. Make end-to-end ownership explicit; include live GitHub metrics from the portfolio block when available.",
            "- Paragraph 3: add supporting proof from the master resume: AI adoption metrics, cloud/platform reliability, and one performance or full-stack project if it directly strengthens the role fit.",
            "- Do not lead with cloud migration as the headline for an AI Platform role; use it as supporting platform reliability evidence.",
        ])
    return "\n".join(base)


def _trim_lines_to_token_budget(lines: list[str], token_budget: int) -> str:
    """Keep whole lines until a token budget is reached."""
    kept: list[str] = []
    for line in lines:
        candidate = "\n".join(kept + [line]).strip()
        if candidate and estimate_tokens(candidate) > token_budget:
            break
        kept.append(line)
    return "\n".join(kept).strip()


def _load_cover_letter_master_context(role: str, job_description: str) -> str:
    """Return a compact source-of-truth resume slice for cover letters.

    Full `_load_master_context()` includes the master resume plus awards and peer
    feedback. That is useful for fitment and interview prep, but it costs ~7.6K
    tokens in cover-letter prompts and causes TPM 429s when the dashboard makes
    multiple calls close together. Cover letters need verified facts and metrics,
    not the full source archive, so this keeps only role/JD-relevant lines plus
    recurring metric-bearing project bullets.
    """
    try:
        # Resolve the master resume for the ACTIVE REQUEST'S user, not the
        # global config.MASTER_RESUME constant which always points to the owner's file.
        master_path = config.get_active_master_resume_path()
        raw = master_path.read_text(encoding="utf-8")
    except Exception:
        return _load_master_context()

    query_terms = {
        term.lower()
        for term in re.findall(r"[A-Za-z][A-Za-z0-9+#.\-]{2,}", f"{role}\n{job_description}")
    }
    pinned_terms = {
        "ai", "claude", "copilot", "agent", "agentic", "mcp", "model context",
        "jobcontextmcp", "langgraph", "rag", "faiss", "embedding", "openai",
        "fastapi", "python", "backend", "platform", "memory", "retrieval",
        "azure", "container apps", "terraform", "postgresql", "redis", "kafka",
        "oauth2", "msal", "sla", "zero downtime", "98%", "35%", "80%",
        "77", "574", "livevox", "2.8ms", "12.7ms", "retrospicam",
        "raspberry", "iot", "test coverage", "500k",
    }
    keep_terms = query_terms | pinned_terms

    kept: list[str] = [
        "COVER LETTER MASTER RESUME EXTRACT (verified facts only; full archive omitted to fit TPM limits):"
    ]
    previous_blank = False
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            previous_blank = True
            continue

        lower = stripped.lower()
        is_structural = stripped in {
            "CORE TECHNICAL SKILLS",
            "RECENT PROJECT (Post-GM, January 2026)",
            "PROFESSIONAL EXPERIENCE",
            "Cloud Infrastructure Migration & Performance:",
            "Distributed Systems & Architecture:",
            "AI-Driven Innovation & Leadership:",
            "Testing & Code Quality:",
            "NOTABLE METRICS & ACHIEVEMENTS:",
        }
        is_skill_line = stripped.startswith((
            "Languages & Frameworks:", "Cloud & Infrastructure:", "Backend:",
            "AI & Innovation:", "Testing:", "Development Tools:",
        ))
        has_relevant_term = any(term in lower for term in keep_terms)
        has_metric = bool(re.search(r"\b\d+(?:\.\d+)?\s*(?:%|ms|tools|passing tests|lines|weeks?|days?)\b", lower))

        if is_structural or is_skill_line or has_relevant_term or has_metric:
            if previous_blank and kept and kept[-1] != "":
                kept.append("")
            kept.append(stripped)
            previous_blank = False

    return _trim_lines_to_token_budget(kept, 2200)


def _infer_role_type(role: str) -> str:
    """Best-effort mapping of a job title to a customization strategy role_type."""
    r = role.lower()
    if any(x in r for x in ("test", "qa", "quality", "sdet", "automation")):
        return "testing"
    if any(x in r for x in ("cloud", "devops", "sre", "platform", "infrastructure", "reliability")):
        return "cloud"
    if any(x in r for x in ("data", "etl", "pipeline", "warehouse", "analytics")):
        return "data_engineering"
    if any(x in r for x in ("full", "fullstack", "full-stack")):
        return "fullstack"
    if any(x in r for x in ("ai", "ml", "machine learning", "llm", "foundation")):
        return "ai_innovation"
    if any(x in r for x in ("iot", "embedded", "firmware", "hardware")):
        return "iot"
    return "backend"


def _safe_filename(company: str, role: str, suffix: str) -> str:
    """Generate a safe default output filename."""
    slug = re.sub(r"[^A-Za-z0-9 ]", "", f"{company} {role} {suffix}").strip()
    slug = re.sub(r"\s+", " ", slug)
    name = config.get_contact_name("")
    if name:
        return f"{name} Resume - {slug}.txt" if suffix == "Resume" else f"{name} Cover Letter - {slug}.txt"
    # Unconfigured user: use neutral company/role stem with no personal name.
    return f"{slug}.txt"


def _no_company_story_block(company: str) -> str:
    return (
        _PERSONAL_CONTEXT_HEADER +
        f"NO COMPANY-SPECIFIC PERSONAL STORY FOUND for {company or 'this company'}. "
        "Do not borrow a brand/childhood/fan story from another company. "
        "Use the structured fitment assessment and a concise professional intro grounded in the JD instead."
    )


def _semantic_story_prefix(selected: list[dict], company: str) -> str:
    # Check for a universal AI-role hook (e.g. Uncle Roy / Intellicorp) first.
    # These pass the cross-company filter intentionally and carry their own label.
    ai_role_hooks = [
        s for s in selected
        if "ai_role_hook" in {t.lower() for t in s.get("tags", [])}
    ]
    if ai_role_hooks:
        return (
            _PERSONAL_CONTEXT_HEADER +
            "PRIMARY COVER LETTER HOOK (AI ROLE — cross-company origin story): "
            "The first story below is tagged 'ai_role_hook'. Use it as the Para 1 hook "
            "for this AI role regardless of company. It is a universal engineering origin "
            "story, not a company-specific brand hook. Open directly with the story and identify him as 'my uncle Roy'; "
            "do NOT say 'Growing up' or 'I have always been passionate about AI'.\n\n"
        )
    if company and any(_story_has_company_hook_tags(s) for s in selected):
        return (
            _PERSONAL_CONTEXT_HEADER +
            "PRIMARY COVER LETTER HOOK: The first company-connection story below "
            f"is explicitly tied to {company}. Use it only because it matches this "
            "company. Include one concrete detail, not a generic theme.\n\n"
        )
    return _no_company_story_block(company) + "\n\n"


def _load_ai_role_hook_stories() -> list[dict]:
    """Directly load stories tagged 'ai_role_hook' from disk.

    Used to force-inject the Uncle Roy / origin story for AI roles regardless
    of whether semantic retrieval ranked it high enough to include it.
    """
    try:
        data = _load_json(config.PERSONAL_CONTEXT_FILE, {"stories": []})
        return [
            s for s in data.get("stories", [])
            if "ai_role_hook" in {t.lower() for t in s.get("tags", [])}
        ]
    except Exception:
        return []


def _ranked_personal_context_block(
    role: str,
    job_description: str,
    company: str,
    token_budget: int,
    max_stories: int,
    boost_tags: set[str] | None,
    semantic: bool,
) -> tuple[str, RetrievalDiagnostics | None]:
    selected, diag = retrieve_stories(
        role,
        job_description,
        path=config.PERSONAL_CONTEXT_FILE,
        token_budget=token_budget,
        max_stories=max_stories,
        boost_tags=boost_tags,
        semantic=semantic,
    )
    if not selected:
        return "", diag

    rejected_cross_company = False
    if semantic and company:
        selected, rejected_cross_company = _filter_cross_company_hook_stories(selected, company)
    if not selected and rejected_cross_company:
        return _no_company_story_block(company), diag
    if not selected:
        return "", diag

    # For AI roles: guarantee the ai_role_hook story is in the list and is first.
    # Retrieval scoring can legitimately rank it below the cutoff; this bypass
    # ensures it always reaches the model for AI role cover letters.
    if semantic and _is_ai_role(role, job_description):
        injected = _load_ai_role_hook_stories()
        if injected:
            selected_ids = {s.get("id") for s in selected}
            new_hooks = [s for s in injected if s.get("id") not in selected_ids]
            existing_hooks = [s for s in selected if "ai_role_hook" in {t.lower() for t in s.get("tags", [])}]
            rest = [s for s in selected if "ai_role_hook" not in {t.lower() for t in s.get("tags", [])}]
            selected = existing_hooks + new_hooks + rest

    prefix = _semantic_story_prefix(selected, company) if semantic else _PERSONAL_CONTEXT_HEADER
    return prefix + format_stories(selected), diag


def _build_personal_context_block(
    role: str = "",
    job_description: str = "",
    company: str = "",
    token_budget: int | None = None,
    boost_tags: set[str] | None = None,
    semantic: bool = False,
) -> tuple[str, RetrievalDiagnostics | None]:
    """Return a (block, diagnostics) tuple for the personal-context section.

    Uses the local retrieval layer (lib.story_retrieval) to select only the
    most role-relevant stories within ``token_budget`` tokens. Only candidate
    stories sharing a query term are scored, so this scales as the library
    grows. When no role/JD is provided, falls back to the unranked full list
    (used by the no-API context-package path).

    ``boost_tags`` (cover-letter path) multiplies the score of human/identity/
    brand stories so they compete with work stories that share more literal
    technical vocabulary with the role title.

    ``semantic`` enables an embedding-backed story pass for cover-letter hooks
    where mission/product alignment often has little literal keyword overlap.
    """
    budgets = config.get_generation_budgets()
    if token_budget is None:
        token_budget = budgets["personal_context_token_budget"]
    token_budget = int(token_budget or 0)
    max_stories = budgets["max_personal_stories"]

    try:
        if role or job_description:
            return _ranked_personal_context_block(
                role,
                job_description,
                company,
                token_budget,
                max_stories,
                boost_tags,
                semantic,
            )

        personal = get_personal_context()
        if personal.startswith(_NO_PERSONAL_STORIES):
            return "", None
        return _PERSONAL_CONTEXT_HEADER + personal, None
    except Exception:
        return "", None


def _dynamic_personal_budget(fixed_sections: list[str], max_tokens: int, safety: int) -> int:
    """Tokens available for the personal-context block after fixed sections.

    Guarantees fixed_cost + personal_budget <= max_tokens - safety, so the
    assembled prompt stays under the model ceiling no matter how large the
    story library grows. Also clamped to the configured per-request budget.
    """
    budgets = config.get_generation_budgets()
    configured = budgets["personal_context_token_budget"]
    fixed_cost = estimate_tokens("\n\n".join(s for s in fixed_sections if s))
    headroom = max_tokens - fixed_cost - safety
    return max(0, min(configured, headroom))


def _enforce_token_ceiling(message: str, max_tokens: int) -> str:
    """Absolute last-resort guard: hard-truncate if somehow over the ceiling.

    With dynamic budgeting this should never fire, but it guarantees the
    contract that the prompt can never exceed ``max_tokens``.
    """
    if estimate_tokens(message) <= max_tokens:
        return message
    # Truncate by characters using the ~4 chars/token heuristic, then trim a
    # little extra to absorb tokenizer variance.
    approx_chars = max(0, int(max_tokens * 4 * 0.95))
    truncated = message[:approx_chars]
    return truncated + "\n\n[context truncated to honor token ceiling]"


_JD_NOISY_LINE_RE = re.compile(
    r"^(apply|sign in|join now|email or phone|password|show|forgot password|"
    r"new to linkedin|by clicking continue|user agreement|privacy policy|"
    r"cookie policy|skip to main content|expand search|clear text|jobs|people|"
    r"learning|see who .* hired|this button displays|join to apply)\b",
    re.IGNORECASE,
)

_JD_ANCHOR_TERMS = (
    "advance human", "democratize", "about", "mission", "culture",
    "responsibilities", "requirements", "qualifications", "backend",
    "content foundations", "java", "python", "api", "cloud",
    "distributed", "microservices", "platform", "stories", "knowledge",
    "curiosity", "ideas", "customer",
)


def _compact_jd_lines(lines: list[str], max_chars: int) -> str:
    if len("\n".join(lines)) <= max_chars:
        return "\n".join(lines)
    selected: list[str] = []
    for line in lines:
        lower = line.lower()
        if any(term in lower for term in _JD_ANCHOR_TERMS):
            selected.append(line)
        if len("\n".join(selected)) >= max_chars:
            break
    return "\n".join(selected) or "\n".join(lines)[:max_chars]


def _clean_job_description_for_prompt(
    company: str,
    role: str,
    job_description: str,
    *,
    max_chars: int = 3600,
) -> str:
    """Strip scraper chrome from a JD before prompt budgeting.

    LinkedIn fetches often include the whole public page: sign-in forms, image
    markdown, repeated apply panels, legal links, and CDN hashes. Passing all of
    that to cover-letter generation crowds out the personal-context block, which
    is where the human hook lives. Keep the useful role/mission text and discard
    navigation metadata.
    """
    text = job_description or ""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)
    text = re.sub(r"\b[a-z0-9]*\d[a-z0-9]{12,}\b", " ", text, flags=re.IGNORECASE)

    lines = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip(" -*#\t")
        if not line or _JD_NOISY_LINE_RE.search(line):
            continue
        if len(line) < 4:
            continue
        lines.append(line)
    cleaned = "\n".join(dict.fromkeys(lines))
    body = _compact_jd_lines(list(dict.fromkeys(lines)), max_chars) if len(cleaned) > max_chars else cleaned

    return "\n".join([
        f"Company: {company}",
        f"Role: {role}",
        "Cleaned job description / mission excerpts:",
        body[:max_chars],
    ])


def _build_resume_user_message(company: str, role: str, job_description: str) -> str:
    budgets = config.get_generation_budgets()
    max_tokens = budgets["resume_max_tokens"]
    safety = budgets["safety_margin_tokens"]

    master = _load_master_context()
    portfolio_metrics = _portfolio_metrics_block()
    tone = get_tone_profile_budgeted(
        token_budget=min(budgets["tone_token_budget"], 800),
        max_samples=min(budgets["max_tone_samples"], 3),
    )
    strategy = get_customization_strategy(_infer_role_type(role))
    interview_block = get_interview_context(company=company, role=role)

    fixed_sections = [
        f"TARGET COMPANY: {company}",
        f"TARGET ROLE: {role}",
        f"JOB DESCRIPTION:\n{job_description}",
        f"CUSTOMIZATION STRATEGY:\n{strategy}",
        portfolio_metrics,
        f"MASTER RESUME (source of truth — use real metrics only):\n{master}",
        interview_block or "",
        f"TONE PROFILE (write in this voice):\n{tone}",
        _RESUME_FORMAT_SPEC,
        "Now write the resume. Output the raw .txt content only.",
    ]
    personal_budget = _dynamic_personal_budget(fixed_sections, max_tokens, safety)
    personal, _diag = _build_personal_context_block(
        role,
        job_description,
        token_budget=personal_budget,
    )

    sections = [
        f"TARGET COMPANY: {company}",
        f"TARGET ROLE: {role}",
        f"JOB DESCRIPTION:\n{job_description}",
        f"CUSTOMIZATION STRATEGY:\n{strategy}",
        portfolio_metrics,
        f"MASTER RESUME (source of truth — use real metrics only):\n{master}",
        personal,
    ]
    if interview_block:
        sections.append(interview_block)
    sections.extend([
        f"TONE PROFILE (write in this voice):\n{tone}",
        _RESUME_FORMAT_SPEC,
        "Now write the resume. Output the raw .txt content only.",
    ])
    return _enforce_token_ceiling("\n\n".join(s for s in sections if s), max_tokens)


def _build_cover_letter_user_message(company: str, role: str, job_description: str) -> str:
    budgets = config.get_generation_budgets()
    max_tokens = budgets["cover_letter_max_tokens"]
    safety = budgets["safety_margin_tokens"]
    clean_job_description = _clean_job_description_for_prompt(company, role, job_description)

    master = _load_cover_letter_master_context(role, clean_job_description)
    portfolio_metrics = _portfolio_metrics_block()
    tone = get_cover_letter_tone_profile_budgeted(
        token_budget=max(budgets["tone_token_budget"], 1800),
        max_samples=max(budgets["max_tone_samples"], 7),
    )
    strategy = get_customization_strategy(_infer_role_type(role))
    assessment_context = _assessment_context_block(company, role)
    narrative_plan = _cover_letter_narrative_plan(company, role, clean_job_description)

    _contact   = config.get_contact_info()
    name     = str(_contact.get("name", "") or "").strip()
    phone    = str(_contact.get("phone", "") or "").strip()
    email    = str(_contact.get("email", "") or "").strip()
    _li      = str(_contact.get("linkedin", "") or "").strip().replace("https://www.linkedin.com/in/", "").replace("www.linkedin.com/in/", "").strip("/")
    _gh      = str(_contact.get("github", "") or "").strip().replace("https://github.com/", "").replace("https://www.github.com/", "").strip("/")
    _linkedin_line = f"\nlinkedin: {_li}" if _li else ""
    _github_line   = f"\ngithub: {_gh}" if _gh else ""
    contact_block = f"{name.upper()}\n\nphone: {phone}\nemail: {email}{_linkedin_line}{_github_line}" if name else ""
    interview_block = get_interview_context(company=company, role=role)

    instructions = (
        f"Now write the cover letter for {company}. Output the raw .txt content only.\n"
        "Use the structured fitment assessment first, then the resume, customization strategy, interview context, personal context, tone profile, and job description.\n"
        "\n"
        "VOICE COMES FIRST: the TONE PROFILE samples are the authority on how this candidate sounds.\n"
        "Match their rhythm, sentence length, and register. If any structure rule below fights\n"
        "that voice, keep the voice. Write like the samples, not like a template.\n"
        "If PERSONAL CONTEXT provides a PRIMARY COVER LETTER HOOK, write it in the candidate's\n"
        "plain spoken voice: concrete, understated, no inspirational gloss. Identify any people\n"
        "mentioned by their relationship the first time. Keep the human thread, then pivot into\n"
        "the professional evidence.\n"
        "PROJECT-NAME BUDGET: any primary project from the master resume should appear at most once\n"
        "by name in the body. In Paragraph 1, refer to it generically ('the server', 'that project')\n"
        "if it will be named in Paragraph 2.\n"
        "Avoid thesis-sentence sludge. Do not explain what the paragraph 'demonstrates',\n"
        "'showcases', 'highlights', or 'aligns with'. State the artifact, the constraint,\n"
        "the metric, and why it matters in plain English.\n"
        "\n"
        "STRUCTURE: exactly 4 paragraphs. Do not merge them. The word counts below are guidance,\n"
        "not quotas; say each point in as few words as it takes and never pad with filler.\n"
        "COHERENCE RULE: follow the COVER LETTER NARRATIVE PLAN. The letter must read like one\n"
        "story with a clear throughline, not a shuffled list of unrelated resume bullets.\n"
        "PAGE FILL: the PDF page is fixed-size and currently runs short. Aim for a full page:\n"
        "target 380-430 words total. Reach it with substance (a second concrete project, a real\n"
        "constraint, a verbatim metric), never with adjectives or restated claims.\n"
        "\n"
        "PARA 1 (~80-100 words): Hook. FIRST check PERSONAL CONTEXT for a PRIMARY COVER LETTER HOOK.\n"
        "  TWO cases where you MUST open with the personal story:\n"
        "  (A) The block says 'PRIMARY COVER LETTER HOOK' and ties the story to THIS company — use it.\n"
        "  (B) The block says 'PRIMARY COVER LETTER HOOK (AI ROLE — cross-company origin story)' —\n"
        "      PERSONAL CONTEXT contains this story. Use it verbatim in the candidate's voice:\n"
        "      plain first person, concrete, understated. Identify any people by their relationship\n"
        "      the first time they are mentioned. Do NOT say 'Growing up'. Pivot directly from\n"
        "      the story into the role without inspirational gloss.\n"
        "  If PERSONAL CONTEXT says NO COMPANY-SPECIFIC PERSONAL STORY FOUND, do not invent one;\n"
        "  open with a crisp professional hook grounded in the JD instead.\n"
        "  Never borrow a brand/childhood/fan story from another company (Home Depot, Coca-Cola, Ford)\n"
        "  unless the block explicitly names this target company.\n"
        "  Follow with one or two concrete sentences on why THIS company/role, grounded in real\n"
        "  JD details and the assessment.\n"
        "\n"
        "PARA 2 (~120-150 words): Primary ownership story. One major example with concrete metrics\n"
        "  from the master resume. For AI/LLM/platform roles, use the candidate's primary AI project\n"
        "  unless the assessment says a different artifact is clearly stronger. Name it once, then\n"
        "  use 'the server' or 'the project' for the rest of the paragraph. Describe it as active\n"
        "  work ('I built and maintain X' or 'X currently...'). Make the end-to-end ownership chain\n"
        "  explicit. State facts cleanly; do not append a justifying clause to every metric.\n"
        "\n"
        "PARA 3 (~140-170 words): Cover THREE distinct artifacts from the master resume to show range.\n"
        "  Lead with the STRONGEST match to this specific JD (the AI/RAG tooling, a side project, or\n"
        "  performance work) in two sentences with verbatim metrics, then add TWO more artifacts, one\n"
        "  sentence each, every one carrying a distinct real metric verbatim from the master resume\n"
        "  (e.g. measured latency, SLA percentages, or migration scope from the master resume). Close with one\n"
        "  sentence on what they demonstrate together. If a side project is referenced, clone/view\n"
        "  traffic MUST come from GITHUB PORTFOLIO METRICS, not stale clone counts in the master resume.\n"
        "  Phrase GitHub traffic naturally: 'currently shows X clones in the last 14 days' or 'has\n"
        "  X clones in the last 14 days'; never write 'cloned X times'.\n"
        "  Every sentence carries a distinct fact; no padding.\n"
        "\n"
        "PARA 4 (~50-70 words): Closer. State the fit directly in the candidate's own words, then\n"
        "  invite a conversation. Write a fresh invite in the candidate's voice (follow the tone\n"
        "  samples); do NOT paste a stock closing line and do NOT end with 'I look forward to\n"
        "  hearing from you' or similar boilerplate.\n"
        "\n"
        "Do not use: 'strong fit', 'I am prepared', 'my comprehensive experience', 'makes me a strong', 'aligns perfectly', 'resonates deeply', 'resonates with', 'igniting a passion', 'led to my current role', 'showcases my ability', 'showcasing', 'highlights my capability', 'demonstrates my ability', 'mission aligns', 'aspirations', 'contribute to your success', 'best practices'.\n"
        "\n"
        "FINAL SELF-CHECK before you finish: count the words in the body (salutation through sign-off\n"
        "name). If it is under 380, you stopped too early. Go back into Para 2 and Para 3 and add\n"
        "another concrete artifact with a verbatim metric until the body reaches 380-430. Do not add\n"
        "adjectives, restated claims, or a longer closer to hit the count; add real substance only."
    )

    fixed_sections = [
        f"TARGET COMPANY: {company}",
        f"TARGET ROLE: {role}",
        f"JOB DESCRIPTION:\n{clean_job_description}",
        f"CUSTOMIZATION STRATEGY:\n{strategy}",
        narrative_plan,
        assessment_context,
        portfolio_metrics,
        f"MASTER RESUME (source of truth — use real metrics only):\n{master}",
        interview_block or "",
        f"TONE PROFILE (write in this voice):\n{tone}",
        f"CONTACT BLOCK (use this exactly as the file header, no address fields):\n{contact_block}",
        _COVER_LETTER_FORMAT_SPEC,
        instructions,
    ]
    personal_budget = _dynamic_personal_budget(fixed_sections, max_tokens, safety)
    personal, _diag = _build_personal_context_block(
        role,
        clean_job_description,
        company=company,
        token_budget=personal_budget,
        boost_tags=_COVER_LETTER_HOOK_TAGS,
        semantic=True,
    )

    sections = [
        f"TARGET COMPANY: {company}",
        f"TARGET ROLE: {role}",
        f"JOB DESCRIPTION:\n{clean_job_description}",
        f"CUSTOMIZATION STRATEGY:\n{strategy}",
        narrative_plan,
        assessment_context,
        portfolio_metrics,
        f"MASTER RESUME (source of truth — use real metrics only):\n{master}",
        personal,
    ]
    if interview_block:
        sections.append(interview_block)
    sections.extend([
        f"TONE PROFILE (write in this voice):\n{tone}",
        f"CONTACT BLOCK (use this exactly as the file header, no address fields):\n{contact_block}",
        _COVER_LETTER_FORMAT_SPEC,
        instructions,
    ])
    return _enforce_token_ceiling("\n\n".join(s for s in sections if s), max_tokens)


def _context_fallback(system: str, user: str, tool_name: str) -> str:
    """Return a packaged context block for Copilot/Claude to handle when no API key."""
    return "\n".join([
        f"═══ {tool_name.upper()} — CONTEXT PACKAGE ═══",
        "No openai_api_key found in config.json.",
        "Use the context below to write the output, then call save_resume_txt / save_cover_letter_txt,"
        " then call export_resume_pdf / export_cover_letter_pdf.",
        "",
        "── SYSTEM INSTRUCTIONS ──",
        system,
        "",
        "── USER CONTEXT ──",
        user,
    ])


def _extract_cover_letter_body(content: str) -> str:
    """Extract only the prose body paragraphs for LaTeX pipeline export.

    The LaTeX template supplies its own salutation ("Dear Hiring Manager,") and
    sign-off ("Regards, \\name"), so this must strip BOTH ends off the model's
    draft. The model does not always use the canonical wording: it may invent a
    salutation ("Dear Scribd Hiring Team,"), prepend a company/address header,
    or close with "Best regards," plus contact lines. Match all of those loosely
    so nothing leaks into the rendered letter as a duplicate.
    """
    text = content.strip()
    if not text:
        return ""

    lines = [ln.rstrip() for ln in text.splitlines()]

    # Start AFTER the salutation. Accept any "Dear ...," line; this also discards
    # any leading company/address header the model prepended above it.
    start = 0
    for i, ln in enumerate(lines):
        if ln.strip().lower().startswith("dear "):
            start = i + 1
            break

    body_lines = lines[start:]

    # Stop BEFORE the sign-off block. Cut at the first of:
    #   - a closing phrase ("Regards,", "Best regards,", "Sincerely,", ...)
    #   - a courtesy line the prompt bans ("Thank you for considering ...")
    #   - a stray contact line (email / phone) that escaped the header
    _CLOSERS = {
        "kindest regards,", "kind regards,", "regards,", "best regards,",
        "warm regards,", "best,", "sincerely,", "respectfully,", "cheers,",
        "kindest regards", "regards", "best regards", "sincerely", "thank you,",
    }
    _email_re = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
    _phone_re = re.compile(r"\+?\d[\d().\s-]{7,}")
    end = len(body_lines)
    for i, ln in enumerate(body_lines):
        low = ln.strip().lower()
        if (
            low in _CLOSERS
            or low.startswith("thank you for")
            or _email_re.search(ln)
            or _phone_re.search(ln.strip())
        ):
            end = i
            break

    body = "\n".join(body_lines[:end]).strip()
    return body


# Deterministic backstop substitutions for the stock opener/closer phrases the
# prompt bans. "I" stays capitalized in every position, so a fixed replacement
# is grammatically safe anywhere in a sentence.
_WANT_TO = "I want to"
_BANNED_LEADIN_SUBS = [
    (r"\bI(?:'m| am) eager to\b", _WANT_TO),
    (r"\bI(?:'m| am) excited to\b", _WANT_TO),
    # "excited about/by" slips past the "excited to" pattern; the model reaches
    # for it in the closer ("I am excited about the opportunity to...").
    (r"\bI(?:'m| am) excited (?:about|by) the (?:opportunity|chance) to\b", _WANT_TO),
    (r"\bI(?:'m| am) excited (?:about|by)\b", "I am interested in"),
    (r"\bI(?:'m| am) thrilled to\b", _WANT_TO),
    (r"\bI would love to\b", _WANT_TO),
    (r"\bI(?:'m| am) passionate about\b", "I care about"),
    # Closer-paragraph variants the model reaches for at higher temperature.
    (r"\bI(?:'d| would) welcome the (?:chance|opportunity) to\b", _WANT_TO),
    (r"\bI(?:'d| would) welcome\b", "I want"),
    # "look forward to" takes a gerund OR a noun; "I would enjoy" is the only
    # swap that stays grammatical before both ("...enjoy discussing" / "...enjoy
    # the conversation"). Do not use "I want to talk about" here: it produces
    # "I want to talk about the conversation" when a noun follows.
    (r"\bI look forward to\b", "I would enjoy"),
    (r"\bLooking forward to\b", "I would enjoy"),
    (r"\b(?:the opportunity|the chance|this role|this) excites me\b", "this interests me"),
    (r"\bexcites me\b", "interests me"),
    (r"\bstrong fit\b", "solid match"),
    (r"\baligns perfectly with\b", "maps directly to"),
    (r"\balign perfectly with\b", "map directly to"),
]


_CORPORATE_STYLE_SUBS = [
    (
        r"Your mission to enable collaboration between people and AI agents resonates with the work I've been doing, turning cognitive architectures into reliable, scalable platforms\.",
        "Sema4.ai is working on the same problem I keep circling in my own work: how to turn agentic AI into something people can actually use, operate, and trust.",
    ),
    (
        r"This project demonstrates my ability to translate AI capabilities into durable backend systems\.",
        "That is the part I care about: turning AI capability into backend systems with state, retrieval, and operational surfaces.",
    ),
    (
        r"The architecture follows FastAPI best practices, with tools organized into specialized modules\.",
        "It is a FastAPI service with the tools split into focused modules instead of one giant prompt-shaped blob.",
    ),
    (
        r"My work on LiveVox's cross-platform audio monitoring application achieved 2\.8ms latency on web and 12\.7ms on iPhone, showcasing elite-level performance optimization\.",
        "On LiveVox's cross-platform audio monitoring application, I measured round-trip audio latency from microphone input to speaker output and got it to 2.8ms on web and 12.7ms on iPhone.",
    ),
    (
        r"On LiveVox's cross-platform audio monitoring application, I got render latency to 2\.8ms on web and 12\.7ms on iPhone; that was performance work measured on real hardware, not a slide\.",
        "On LiveVox's cross-platform audio monitoring application, I measured round-trip audio latency from microphone input to speaker output and got it to 2.8ms on web and 12.7ms on iPhone.",
    ),
    (
        r"These projects highlight my capability to build robust systems that perform at scale\.",
        "Different projects, same habit: make the thing work under real constraints.",
    ),
    (
        r"Sema4\.ai's focus on transforming knowledge work aligns with my experience in building platforms that are not just intelligent but operable and reliable\.",
        "That is what pulls me toward Sema4.ai: not AI as a demo, AI as something operable enough to sit inside real work.",
    ),
    (
        r"I want a conversation to explore how my background can contribute to your Agent Platform's success\.",
        "I want to talk through where that experience would be useful on the Agent Platform.",
    ),
]


def _limit_jobcontextmcp_mentions(text: str, max_mentions: int = 1) -> str:
    """Avoid turning the cover letter into a jobContextMCP drinking game."""
    count = 0

    def repl(match: re.Match) -> str:
        nonlocal count
        count += 1
        if count <= max_mentions:
            return match.group(0)
        return "the server"

    return re.sub(r"\bjobContextMCP\b", repl, text)


def _sanitize_cover_letter_output(content: str) -> str:
    """Remove wrapper chatter so the saved file contains only the letter."""
    text = (content or "").strip()
    if not text:
        return ""

    lines = text.splitlines()
    while lines:
        first = lines[0].strip().lower()
        if not first:
            lines.pop(0)
            continue
        if first.startswith(("here is the cover letter", "cover letter in .txt format")):
            lines.pop(0)
            continue
        break

    cleaned = "\n".join(lines).strip()
    cleaned = re.sub(
        r"^Here is the cover letter in \.txt format, following the specified rules:\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        r"improved query performance by \d+% and reduced costs by \d+%",
        "improved query performance and reduced costs through resource rightsizing and auto-scaling policies",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\bdrastically improved load times\b",
        "improved query responsiveness",
        cleaned,
        flags=re.IGNORECASE,
    )

    # Deterministic em-dash / double-hyphen backstop. The prompt forbids them,
    # but the model still leaks one occasionally; never ship one to the PDF.
    # A comma is the lowest-damage substitution for a stray dash.
    cleaned = re.sub(r"\s*(?:—|--)\s*", ", ", cleaned)
    cleaned = re.sub(r"\s+,", ",", cleaned)
    cleaned = re.sub(r",\s*,", ",", cleaned)

    # Normalize typographic apostrophes/quotes to ASCII first. The model often
    # emits a curly apostrophe (U+2019) in contractions ("I’m"), which would slip
    # past the straight-quote banned-phrase patterns below; ASCII is also safer
    # for the strict txt -> PDF parser.
    cleaned = cleaned.replace("\u2019", "'").replace("\u2018", "'")
    cleaned = cleaned.replace("\u201c", '"').replace("\u201d", '"')

    # Deterministic banned-lead-in backstop. The prompt bans these stock
    # opener/closer phrases, but the model still leaks one ("I'm eager to...");
    # swap each for a neutral, grammatically-safe equivalent. "I" stays
    # capitalized in every position, so a fixed replacement is safe anywhere.
    for pattern, repl in _BANNED_LEADIN_SUBS:
        cleaned = re.sub(pattern, repl, cleaned)

    # Backstop for corporate template filler that can survive the prompt while
    # still technically obeying the hook/story instructions. These substitutions
    # preserve the factual claims but put them back into Frank's plainer cadence.
    for pattern, repl in _CORPORATE_STYLE_SUBS:
        cleaned = re.sub(pattern, repl, cleaned, flags=re.IGNORECASE)

    # Readers do not know who Roy is unless the opener identifies the
    # relationship. If the model starts cold with "Uncle Roy", make it
    # first-person and contextual.
    cleaned = re.sub(
        r"(^|\n)(Uncle Roy\b)",
        r"\1My uncle Roy",
        cleaned,
        count=1,
    )

    # The Uncle Roy hook should create the throughline without burning the
    # project name before the ownership paragraph gets to use it.
    cleaned = re.sub(
        r"direct line from that to the jobContextMCP server",
        "direct line from that to the MCP server",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"direct line from (?:KEE to )?that Pi to jobContextMCP",
        lambda m: m.group(0).replace("jobContextMCP", "the MCP server"),
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = _limit_jobcontextmcp_mentions(cleaned, max_mentions=1)

    # Backstop for awkward/past-tense portfolio phrasing. GitHub reports clone
    # events; the project was not "cloned 371 times" as a completed event, and
    # jobContextMCP is an active project, not just a past artifact.
    cleaned = re.sub(
        r"I built a Model Context Protocol \(MCP\) server, open-sourced and cloned ([\d,]+) times in the last 14 days",
        r"I built and maintain jobContextMCP, an open-source Model Context Protocol (MCP) server that currently shows \1 clones in the last 14 days",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\bopen-sourced and cloned ([\d,]+) times in the last 14 days\b",
        r"open source and currently shows \1 clones in the last 14 days",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\bcloned ([\d,]+) times in the last 14 days\b",
        r"currently shows \1 clones in the last 14 days",
        cleaned,
        flags=re.IGNORECASE,
    )

    # Enforce correct salutation — model sometimes uses a contact name it
    # hallucinated from the JD or assessment. Always "Dear Hiring Manager,".
    cleaned = re.sub(
        r"^Dear [^\n,]+,",
        "Dear Hiring Manager,",
        cleaned,
        flags=re.MULTILINE,
    )

    # Enforce canonical sign-off in the saved text. The LaTeX template supplies
    # its own sign-off, but the TXT should be correct too.
    cleaned = re.sub(
        r"^(?:Kind regards|Regards|Best regards|Warm regards|Best|Sincerely|Respectfully),?\s*$",
        "Kindest Regards,",
        cleaned,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    # Normalise the sign-off name to the configured contact name so that
    # middle names, suffixes, or model hallucinations don't leak through.
    # Skip entirely when no name is configured (empty workspace).
    _configured_name = config.get_contact_name("")
    if _configured_name:
        # Build a pattern that matches any variant of the configured name
        # (e.g. with/without middle initial or suffix) and normalise to the
        # plain "First Last" form stored in contact.name.
        _name_parts = _configured_name.split()
        if len(_name_parts) >= 2:
            _first = re.escape(_name_parts[0])
            _last  = re.escape(_name_parts[-1])
            cleaned = re.sub(
                rf"\b{_first}(?:\s+\w+{{1,2}})?\s+{_last}(?:\s+[IVX]{{1,4}})?\b",
                _configured_name,
                cleaned,
            )

    return cleaned.strip()


# Page-fill floor. gpt-4o single-shot reliably undershoots; below this we make
# one expansion pass rather than ship a half-empty page.
_COVER_LETTER_WORD_FLOOR = 380


def _cover_letter_body_word_count(content: str) -> int:
    """Word count of the letter body only (salutation through sign-off)."""
    body = _extract_cover_letter_body(content) or content
    return len(re.findall(r"\S+", body))


def _expand_cover_letter_if_short(
    client,
    content: str,
    user_msg: str,
    *,
    floor: int = _COVER_LETTER_WORD_FLOOR,
) -> str:
    """Deterministic page-fill backstop (Option A): up to two expansion passes.

    gpt-4o stops short of the word floor from a single prompt no matter how the
    target is phrased. Rather than pad the prompt (which it ignores), re-send the
    draft and instruct it to lengthen Para 2 and Para 3 with additional concrete
    artifacts and verbatim metrics from the master resume already in `user_msg`.
    Returns the original draft unchanged on any error or non-improvement.
    """
    best = content
    count = _cover_letter_body_word_count(best)
    for _ in range(1):  # single expansion pass — avoids back-to-back 429s
        if count >= floor:
            return best
        import time
        time.sleep(3)  # brief pause so consecutive cover-letter calls don't stack
        try:
            response = _chat_completion_create(
                client,
                label="cover_letter_expand",
                model=_model(),
                messages=[
                    {"role": "system", "content": _COVER_LETTER_SYSTEM},
                    {"role": "user", "content": user_msg},
                    {"role": "assistant", "content": best},
                    {
                        "role": "user",
                        "content": (
                            f"The extracted letter body is {count} words; the fixed-size page needs "
                            "380-430. Expand Para 2 and Para 3 by 70-100 words total, ONLY by adding "
                            "more concrete artifacts and verbatim metrics from the master resume already "
                            "provided above (distinct projects, real constraints, real numbers). Do NOT "
                            "invent or paraphrase metrics; if a metric is not exactly present in the source "
                            "context, remove it. Do NOT add adjectives, restated claims, a longer closer, or "
                            "any new paragraph; keep exactly 4 paragraphs and the same voice. Obey every "
                            "voice and banned-phrase rule. Output the full revised letter only."
                        ),
                    },
                ],
                temperature=0.3,
                max_tokens=2000,
            )
            expanded = response.choices[0].message.content or ""
        except Exception:
            break
        expanded_count = _cover_letter_body_word_count(expanded)
        if expanded_count <= count:
            break
        best = expanded
        count = expanded_count
    return best


# ── PUBLIC TOOLS ───────────────────────────────────────────────────────────────

def generate_resume(
    company: str,
    role: str,
    job_description: str,
    output_filename: str = "",
) -> str:
    """
    Generate a tailored resume for a specific company and role.

    If openai_api_key is configured in config.json, calls the OpenAI API directly
    (model: openai_model, default gpt-4o-mini), saves the .txt, exports a PDF, and
    returns the finished PDF path.

    If no API key is configured, returns a fully-structured context package with
    master resume, tone profile, customization strategy, and exact .txt format
    instructions so Copilot / Claude can write the content and call save_resume_txt
    + export_resume_pdf.

    Constraints the caller must respect:
    - All metrics and achievements must come verbatim from master resume (no invention).
    - Section headers must be ALL CAPS.
    - Bullets must use • (U+2022), not - or *.
    - Job header format: Title | Company, Location | Month YYYY - Month YYYY
    - Target length: 650–800 words (one tight page).
    """
    user_msg = _build_resume_user_message(company, role, job_description)
    client = _openai_client()

    if client is None:
        return _context_fallback(_RESUME_SYSTEM, user_msg, "generate_resume")

    # ── API call ──
    filename = output_filename or _safe_filename(company, role, "Resume")
    try:
        response = _chat_completion_create(
            client,
            label="resume_generate",
            model=_model(),
            messages=[
                {"role": "system", "content": _RESUME_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            max_tokens=2800,
        )
        content = response.choices[0].message.content or ""
    except Exception as exc:
        return f"✗ OpenAI API error: {exc}\n\nFalling back to context package:\n\n{_context_fallback(_RESUME_SYSTEM, user_msg, 'generate_resume')}"

    save_result = save_resume_txt(filename, content)

    try:
        from tools.export import export_resume_pdf
        pdf_result = export_resume_pdf(filename)
    except Exception as exc:
        pdf_result = f"⚠ PDF export failed: {exc}"

    usage = response.usage
    cost_note = ""
    if usage:
        # gpt-4o-mini: $0.15/1M input, $0.60/1M output (as of 2025)
        est = (usage.prompt_tokens * 0.15 + usage.completion_tokens * 0.60) / 1_000_000
        cost_note = f"\n  tokens: {usage.prompt_tokens} in / {usage.completion_tokens} out / est ${est:.4f}"

    return "\n".join([
        f"✓ Resume generated for {role} @ {company}",
        f"  model:  {_model()}{cost_note}",
        f"  {save_result}",
        f"  {pdf_result}",
    ])


def generate_cover_letter(
    company: str,
    role: str,
    job_description: str,
    output_filename: str = "",
    export_pipeline: str = "html",
    role_title: str = "Full Stack Software Engineer",
) -> str:
    """
    Generate a tailored cover letter for a specific company and role.

    If openai_api_key is configured in config.json, calls the OpenAI API directly,
    saves the .txt, exports a PDF, and returns the finished PDF path.

    If no API key is configured, returns a context package for Copilot / Claude to
    write the content.

    Hard constraints enforced in the prompt (the PDF template is fixed-size):
    - TARGET 380–430 words in the letter body to fill the page; reach it with substance, not filler.
    - Exactly 4 paragraphs.
    - No date, no address block, no company name, no Re: line.
    - No bullets, no bold, no headers — prose only.
    - Salutation must be: Dear Hiring Manager,
    - Voice from the tone samples takes priority over the structure template.
    - Paragraph 4 is a short closer (1-2 sentences) written in Frank's voice.
    """
    user_msg = _build_cover_letter_user_message(company, role, job_description)
    client = _openai_client()

    if client is None:
        return _context_fallback(_COVER_LETTER_SYSTEM, user_msg, "generate_cover_letter")

    # ── API call ──
    filename = output_filename or _safe_filename(company, role, "Cover Letter")
    try:
        response = _chat_completion_create(
            client,
            label="cover_letter_generate",
            model=_model(),
            messages=[
                {"role": "system", "content": _COVER_LETTER_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            max_tokens=2000,
        )
        content = response.choices[0].message.content or ""
    except Exception as exc:
        return f"✗ OpenAI API error: {exc}\n\nFalling back to context package:\n\n{_context_fallback(_COVER_LETTER_SYSTEM, user_msg, 'generate_cover_letter')}"

    # Do not re-prompt for page fill here. The dashboard pipeline can generate
    # resume + cover-letter calls back-to-back; resending the full cover-letter
    # prompt for expansion was the main TPM-rate-limit trigger.
    content = _sanitize_cover_letter_output(content)
    save_result = save_cover_letter_txt(filename, content)

    try:
        if export_pipeline == "latex":
            from tools.latex_export import generate_cover_letter_latex

            body = _extract_cover_letter_body(content)
            if not body:
                raise RuntimeError("Unable to extract cover letter body for LaTeX export")

            latex_pdf = generate_cover_letter_latex(body=body, company=company, role=role, role_title=role_title)
            pdf_result = f"✓ PDF exported (LaTeX): {latex_pdf}"
        else:
            from tools.export import export_cover_letter_pdf

            pdf_result = export_cover_letter_pdf(filename, footer_tag=role_title.upper())
    except Exception as exc:
        pdf_result = f"⚠ PDF export failed: {exc}"

    usage = response.usage
    cost_note = ""
    if usage:
        est = (usage.prompt_tokens * 0.15 + usage.completion_tokens * 0.60) / 1_000_000
        cost_note = f"\n  tokens: {usage.prompt_tokens} in / {usage.completion_tokens} out / est ${est:.4f}"

    return "\n".join([
        f"✓ Cover letter generated for {role} @ {company}",
        f"  export pipeline: {export_pipeline}",
        f"  model:  {_model()}{cost_note}",
        f"  {save_result}",
        f"  {pdf_result}",
    ])


def preview_story_retrieval(role: str, job_description: str = "") -> str:
    """Preview which personal stories the retrieval layer would inject for a role.

    Runs the same local inverted-index retrieval used by resume/cover-letter
    generation and returns full diagnostics: library size, how many candidate
    stories were actually scored (vs the full library), relevance scores, token
    counts, the active token budget, and which stories were selected. Use this
    to tune relevance or verify the context stays within budget as the story
    library grows.

    Args:
        role:            Target role title.
        job_description: Optional JD text (improves relevance signal).

    Returns:
        Formatted diagnostics report.
    """
    budgets = config.get_generation_budgets()
    _selected, diag = retrieve_stories(
        role,
        job_description,
        path=config.PERSONAL_CONTEXT_FILE,
        token_budget=budgets["personal_context_token_budget"],
        max_stories=budgets["max_personal_stories"],
    )
    return diag.render()


def register(mcp) -> None:
    mcp.tool()(generate_resume)
    mcp.tool()(generate_cover_letter)
    mcp.tool()(preview_story_retrieval)
