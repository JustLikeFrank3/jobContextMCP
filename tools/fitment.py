import textwrap
from pathlib import Path
import re

from lib.io import _load_master_context
from lib import config
from lib.openai_calls import create_chat_completion
from tools.interviews import get_interview_context

_ASSESSMENT_SYSTEM = textwrap.dedent("""\
    You are a brutally honest senior engineering hiring advisor. Your job is to
    assess how well a candidate's background matches a specific job description
    and produce a concise, actionable fitment report.

    Output a structured assessment with exactly these sections:

    ## FITMENT SCORE
    X/10 — one sentence explaining the score.

    ## STRONG MATCHES
    Bullet list of 4-6 specific qualifications or experiences that directly map
    to stated requirements. Be concrete — cite actual resume items vs JD items.

    ## GAPS / RISKS
    Bullet list of real gaps or risks. Be honest. If there are none, say so.
    Do not invent gaps, but do not soften real ones.

    ## KEY ANGLES TO EMPHASIZE
    3-4 bullets on what to lead with in a resume, cover letter, or interview for
    THIS specific role and company. Concrete and tactical.

    ## COMP ASSESSMENT
    One paragraph on whether the posted comp range matches the candidate's level
    and market value. Include any negotiation notes.
    BUG GUARD (ingestion workflow): The job description you receive may be
    truncated or may omit compensation entirely. Only reference comp numbers
    that appear verbatim in the provided job description. If no comp range is
    present, write exactly "No compensation range was provided in the posting."
    and stop. Never invent, estimate, or infer a "competitive range" — a
    fabricated number here poisons downstream negotiation prep.

    ## RECOMMENDATION
    One sentence: Apply aggressively / Apply with caveats / Do not apply.
    Follow with 2-3 sentences of reasoning.

    Be direct. No filler. No hedge language. If the fit is weak, say so.
    GLOBAL ANTI-FABRICATION RULE: Every claim in every section must be grounded
    in either the provided master resume or the provided job description. If a
    detail is not present in your inputs, do not assert it as fact.

    AI PLATFORM CALIBRATION RULE: If the master resume includes explicit work
    building MCP servers, RAG / semantic search, vector embeddings, LangGraph
    workflows, OpenAI API integrations, dashboard/HTTP transports for AI tools,
    or AI tool adoption programs, surface that evidence in STRONG MATCHES and
    KEY ANGLES for AI Platform / Agent Platform / LLM / RAG roles. Do not call
    the candidate's AI platform experience "absent" merely because it comes
    from a side project or platform project rather than a formal ML-model title.
    You may still distinguish AI platform engineering from ML model training,
    but the distinction must acknowledge the concrete AI platform evidence.
""")


_AI_ROLE_KEYWORDS = (
    "ai",
    "llm",
    "rag",
    "agent",
    "copilot",
    "machine learning",
    "generative",
    "prompt",
    "model context protocol",
    "mcp",
)

_AI_EVIDENCE_KEYWORDS = (
    "ai",
    "llm",
    "rag",
    "copilot",
    "claude",
    "openai",
    "model context protocol",
    "mcp",
    "fastmcp",
    "langgraph",
    "agent",
    "semantic search",
    "faiss",
    "vector",
    "embedding",
    "prompt",
)


def _contains_keyword(text: str, keyword: str) -> bool:
    if " " in keyword or "/" in keyword or "-" in keyword:
        return keyword in text
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def _is_ai_focused(role: str, job_description: str) -> bool:
    text = f"{role}\n{job_description}".lower()
    return any(_contains_keyword(text, keyword) for keyword in _AI_ROLE_KEYWORDS)


def _extract_ai_platform_evidence(master: str, limit: int = 10) -> str:
    """Pull concrete AI-platform evidence to the front of assessment prompts.

    The full master resume can be long enough that side-project AI platform work
    gets underweighted by the LLM. This deterministic excerpt keeps MCP/RAG/
    LangGraph/OpenAI evidence visible for AI Platform and Agent Platform roles.
    """
    evidence: list[str] = []
    for raw in master.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        lower = line.lower()
        if any(_contains_keyword(lower, keyword) for keyword in _AI_EVIDENCE_KEYWORDS):
            evidence.append(line)
        if len(evidence) >= limit:
            break

    if not evidence:
        return ""
    return "\n".join(f"- {line}" for line in evidence)


def assess_job_fitment(company: str, role: str, job_description: str, persona: str = "") -> str:
    """Package the candidate's master resume alongside a job description so the AI can assess fit, identify gaps, and recommend which experience to emphasize for this specific role.

    When `persona` is set, prepends the persona's prompt block to the context
    pack so the consuming agent reads it as a role-specific lens (e.g.
    'faang_technical' weighs systems depth differently than 'executive_polish').
    """
    master = _load_master_context()
    interview_block = get_interview_context(company=company, role=role)
    interview_section = f"\n\n{interview_block}" if interview_block else ""
    ai_evidence_section = ""
    if _is_ai_focused(role, job_description):
        ai_evidence = _extract_ai_platform_evidence(master)
        if ai_evidence:
            ai_evidence_section = (
                "──── AI PLATFORM EVIDENCE EXTRACTED FROM MASTER RESUME ────\n"
                "Use this evidence when assessing AI Platform / Agent Platform fit.\n"
                f"{ai_evidence}\n\n"
            )

    persona_section = ""
    if persona:
        # Lazy import: services/__init__ -> resume_service -> tools.generate ->
        # tools.fitment, so importing PersonaService at module top would cycle.
        from services.persona_service import PersonaService, UnknownPersonaError
        try:
            cfg = PersonaService.get(persona)
            persona_section = f"──── PERSONA LENS ────\n{cfg.to_prompt_block()}\n\n"
        except UnknownPersonaError as exc:
            persona_section = f"──── PERSONA LENS ────\n[warning: {exc}]\n\n"

    return (
        f"═══ FITMENT ASSESSMENT ═══\n"
        f"Company: {company}\n"
        f"Role:    {role}\n\n"
        f"{persona_section}"
        f"──── JOB DESCRIPTION ────\n{job_description}\n\n"
        f"{ai_evidence_section}"
        f"──── CANDIDATE MASTER RESUME ────\n{master}"
        f"{interview_section}"
    )


def get_customization_strategy(role_type: str) -> str:
    """Return a resume customization strategy for a given role type. Valid values: testing, cloud, data_engineering, backend, fullstack, ai_innovation, iot. Advises which skills and stories to lead with based on the candidate's master resume."""
    strategies = {
        "testing": (
            "Lead with testing expertise, coverage metrics, and TDD practices. "
            "Feature any story about defect prevention or quality improvements. "
            "Highlight both backend (JUnit/Mockito) and frontend (Karma/Jest) testing if present."
        ),
        "cloud": (
            "Lead with cloud platform experience, infrastructure-as-code, and migration work. "
            "Emphasize containerization, CI/CD pipelines, and zero-downtime deployment stories."
        ),
        "data_engineering": (
            "Lead with ETL pipeline experience, data migration work, and warehouse projects. "
            "Emphasize data modeling, multi-source integration, and throughput improvements."
        ),
        "backend": (
            "Lead with microservices architecture, event-driven messaging, and API ownership. "
            "Emphasize SLA compliance, distributed systems debugging, on-call experience, and observability."
        ),
        "fullstack": (
            "Lead with end-to-end ownership across backend APIs and frontend interfaces. "
            "Emphasize API design, modernization work, and cross-functional product collaboration."
        ),
        "ai_innovation": (
            "Lead with AI tooling adoption and technical evangelism stories. "
            "Emphasize measurable team impact, org-wide adoption metrics, and agentic/LLM platform work."
        ),
        "iot": (
            "Lead with hardware/software integration experience and IoT or embedded adjacent projects. "
            "Highlight edge/cloud connectivity, latency work, and real-time data handling."
        ),
    }
    result = strategies.get(role_type.lower())
    if result:
        return f"Strategy for '{role_type}':\n\n{result}"
    return f"Unknown role type: '{role_type}'\nAvailable options: {', '.join(strategies)}"


def save_job_assessment(company: str, content: str, filename: str = "", source: str = "") -> str:
    """Save a generated job fitment assessment to the 07-Job-Assessments folder as a .md file.

    If `source` is provided (e.g. 'Miguel Referral', 'AirBnb', 'Cold Apply'), the file is
    saved into a subfolder of that name under 07-Job-Assessments/ for organisation.
    Filename defaults to {Company} - Fitment Assessment.md.
    Always use this tool to save assessments instead of creating files directly.
    """
    if not filename:
        slug = company.strip().replace("/", "-")
        filename = f"{slug} - Fitment Assessment.md"
    if not filename.endswith(".md"):
        filename += ".md"

    cleaned = "\n".join(line.rstrip() for line in content.splitlines())

    _assessments_folder = config.get_active_job_assessments_dir()
    folder = _assessments_folder
    if source:
        # Sanitise source into a safe folder name
        safe_source = source.strip().replace("/", "-").replace("\\", "-")
        folder = folder / safe_source

    target = folder / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(cleaned, encoding="utf-8")

    relative = target.relative_to(_assessments_folder)
    return f"\u2713 Saved job assessment: {relative}"


def run_job_assessment(company: str, role: str, job_description: str, persona: str = "", auto_save: bool = True) -> str:
    """
    Run a real LLM-powered fitment assessment for a job posting.

    Unlike assess_job_fitment (which is a context packer), this tool actually calls
    the OpenAI API and returns a structured analysis: fitment score, strong matches,
    gaps, key angles to emphasize, comp assessment, and recommendation.

    When `persona` is set (e.g. 'faang_technical', 'executive_polish'), the
    persona's prompt block is prepended to the system message so the LLM
    applies role-specific weighting and tone to the assessment.

    If auto_save=True (default), saves the result to 07-Job-Assessments automatically.
    """
    try:
        from lib.config import get_llm_client
        client, model = get_llm_client(task="assessment")
    except Exception:
        return "✗ Failed to load LLM client. Check config.json llm_provider settings."
    if client is None:
        return assess_job_fitment(company, role, job_description, persona=persona)

    system_prompt = _ASSESSMENT_SYSTEM
    persona_note = ""
    if persona:
        from services.persona_service import PersonaService, UnknownPersonaError
        try:
            cfg = PersonaService.get(persona)
            system_prompt = f"{cfg.to_prompt_block()}\n\n{_ASSESSMENT_SYSTEM}"
            persona_note = f" (persona: {cfg.name})"
        except UnknownPersonaError as exc:
            persona_note = f" (persona warning: {exc})"

    master = _load_master_context()
    candidate_name = config.get_contact_name("the candidate")
    ai_evidence_msg = ""
    if _is_ai_focused(role, job_description):
        ai_evidence = _extract_ai_platform_evidence(master)
        if ai_evidence:
            ai_evidence_msg = (
                "AI PLATFORM EVIDENCE EXTRACTED FROM MASTER RESUME:\n"
                "This is high-signal context for AI Platform / Agent Platform roles. "
                "Do not ignore it when scoring direct platform fit.\n"
                f"{ai_evidence}"
            )
    user_msg = "\n\n".join([
        f"CANDIDATE: {candidate_name}",
        f"TARGET COMPANY: {company}",
        f"TARGET ROLE: {role}",
        f"JOB DESCRIPTION:\n{job_description}",
        ai_evidence_msg,
        f"MASTER RESUME / FULL CAREER CONTEXT:\n{master}",
        "Now produce the fitment assessment.",
    ]).replace("\n\n\n", "\n\n")

    try:
        response = create_chat_completion(
            client,
            label="fitment_assessment",
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
            max_tokens=1200,
        )
        content = response.choices[0].message.content or ""
    except Exception as exc:
        return f"✗ OpenAI API error: {exc}"

    usage = response.usage
    cost_note = ""
    if usage:
        est = (usage.prompt_tokens * 0.15 + usage.completion_tokens * 0.60) / 1_000_000
        cost_note = f"  tokens: {usage.prompt_tokens} in / {usage.completion_tokens} out / est ${est:.4f}\n"

    if auto_save:
        slug = f"{company} {role} - Fitment Assessment.md".replace("/", "-")
        save_result = save_job_assessment(company, content, slug, source="run_job_assessment")
    else:
        save_result = "(not saved — pass auto_save=True to persist)"

    return f"✓ Assessment complete for {role} @ {company}{persona_note}\n{cost_note}  {save_result}\n\n{content}"


def register(mcp) -> None:
    mcp.tool()(assess_job_fitment)
    mcp.tool()(run_job_assessment)
    mcp.tool()(get_customization_strategy)
    mcp.tool()(save_job_assessment)
